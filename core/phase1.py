"""Phase 1: download => transcribe => score => crop.

Orchestrates the first half of the pipeline:
1. Download video from YouTube
2. Transcribe with Whisper (GPU/CPU)
3. Extract topics + optional knowledge graph enrichment
4. Score clips via LLM (4-dimension scoring)
5. Crop each clip to 9:16 vertical

Produces state.json per clip in shorts_output/<timestamp>/clip_N/.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.artifact_registry import AOR, ArtifactRecord
from core.config import PipelineConfig
from core.logger import get_logger
from core.feature_registry import registry
from core.contract_validator import validate_state, validate_scored_clip, validate_ffmpeg_command
from core.state import write_state
from ingest.downloader import download_video
from analysis.transcription import transcribe, format_transcript
from analysis.topic_detection import extract_topics
from analysis.clip_scoring import score_clips
from editing.render_core import build_crop_command
from analysis.reframe import detect_crop_x
from editing.ffmpeg_builder import execute, probe_duration, probe_file


log = get_logger(__name__)


# ── Phase 1 Feature Declarations ──────────────────────────────────
registry.declare("download_video", "core", "yt-dlp video download")
registry.declare("transcribe", "core", "Whisper GPU/CPU transcription")
registry.declare("extract_topics", "core", "Keyword extraction from transcript")
registry.declare("knowledge_graph", "optional", "Obsidian graph enrichment")
registry.declare("score_clips", "core", "Groq LLM clip scoring")
registry.declare("crop", "core", "FFmpeg segment crop to 9:16")
registry.declare("gpu_encode", "optional", "NVENC GPU accelerated encoding (phase1)")


class PipelineError(Exception):
    """Base exception for pipeline stage failures."""


# ── DAG definition (explicit stage transitions) ─────────────────

DAG_GRAPH: Dict[Optional[str], str] = {
    None: "analysis",
    "analysis_complete": "render",
    "render_complete": "upload",
    "render_failed": "render",
    "ready_for_upload": "upload",
    "upload_failed": "upload",
}
DAG_TERMINAL = {"uploaded"}
DAG_BLOCKED = {"upload_blocked"}


def _resolve_dag(state: dict, clip_dir: Optional[Path] = None) -> Optional[str]:
    """Resolve next DAG stage with validation.

    Returns next stage name, or None if pipeline is terminal.
    Raises PipelineError on unknown stages, invalid transitions,
    or missing required artifacts.
    """
    from core.contract_validator import validate_dag_transition

    stage: Optional[str] = state.get("pipeline_stage")
    if stage in DAG_TERMINAL:
        return None
    if stage in DAG_BLOCKED:
        raise PipelineError(f"Pipeline blocked: stage={stage!r}")
    next_stage: Optional[str] = DAG_GRAPH.get(stage)
    if next_stage is None:
        raise PipelineError(f"Unknown pipeline stage: {stage!r}")
    validate_dag_transition(stage, next_stage, clip_dir)
    return next_stage


def _assert_valid_video(path: Path) -> None:
    """Validate video file via existence, size, ffmpeg probe, and optional ffprobe check."""
    if not path.exists():
        raise PipelineError(f"Video artifact missing: {path}")
    if path.stat().st_size == 0:
        raise PipelineError(f"Video artifact empty: {path}")

    dur = probe_duration(path)
    if dur <= 0:
        raise PipelineError(f"Video artifact unreadable (probe returned 0): {path}")

    info = probe_file(path)
    streams = info.get("streams", [])
    if streams:
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        if not video_streams:
            raise PipelineError(f"Video artifact has no video stream: {path}")
        if video_streams[0].get("codec_name") in (None, "unknown"):
            raise PipelineError(f"Video artifact has unknown codec: {path}")


def run_phase1(
    url: str,
    config: PipelineConfig,
    memory_bias: Optional[Dict] = None,
) -> List[Tuple[str, Path, Path, str, bool]]:
    """Execute full Phase 1 pipeline.

    Returns:
        List of (clip_slug, clip_dir, cropped_path, hook_text) tuples.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"short_{timestamp}"
    root_dir = config.output_path() / slug
    root_dir.mkdir(parents=True, exist_ok=True)
    config.temp_path().mkdir(parents=True, exist_ok=True)

    log.info("=== Phase 1 starting: %s ===", url)

    try:
        log.info("[1/5] Downloading video...")
        video_path = download_video(url, config.temp_path())
        registry.use("download_video")
        log.info("  [OK] Download complete: %s", video_path.name)
    except Exception as exc:
        registry.fail("download_video")
        raise PipelineError(f"Download failed: {exc}") from exc

    try:
        log.info("[2/5] Transcribing with Whisper (GPU)...")
        segments, _ = transcribe(video_path, config)
        AOR.register_write("transcript_segments", "memory", __name__)
        registry.use("transcribe")
        log.info("  [OK] Transcription complete (%d segments)", len(segments))
    except Exception as exc:
        registry.fail("transcribe")
        raise PipelineError(f"Transcription failed: {exc}") from exc

    try:
        log.info("[3/5] Extracting topics...")
        transcript_text = format_transcript(segments, max_chars=config.llm_max_chars)
        topics = extract_topics(transcript_text)
        AOR.register_write("topics", "memory", __name__)
        registry.use("extract_topics")
        log.info("  [OK] Topics: %s", ", ".join(topics[:8]))
    except Exception as exc:
        log.warning("  [WARN] Topic detection failed: %s — continuing without topics", exc)
        topics = []

    # ── Knowledge enrichment (adaptive weighting) ──
    _original = topics[:]
    try:
        if not _original:
            log.info("  [K] Skipping (no base topics to enrich)")
        else:
            from obsidian_bridge.graph_query import query_graph
            _gp = Path(__file__).resolve().parent.parent / "obsidian_bridge" / "graph_store.json"
            if not _gp.exists():
                log.warning("  [K] Graph store missing: %s", _gp)
            else:
                _graph = json.loads(_gp.read_text(encoding="utf-8"))
                AOR.register_read("graph_store", _gp, __name__)
                _results = query_graph(_graph, " ".join(_original))

                if not _results:
                    _weight = 0.0
                else:
                    _avg = sum(n["score"] for n in _results) / len(_results)
                    if _avg < 3:
                        _weight = 0.0
                    else:
                        _orig_lower = {t.lower() for t in _original}
                        _matched = sum(1 for n in _results if n["label"].lower() in _orig_lower)
                        _overlap = _matched / len(_results)
                        _weight = 0.1 if _overlap > 0.5 else 0.3

                _qualified = [n["label"] for n in _results if n["score"] >= 3]
                _seen = {t.lower() for t in _original}
                _novel = [t for t in _qualified if t.lower() not in _seen]
                _slots = int(len(_original) * _weight)
                _take = _novel[:_slots]
                if _take:
                    topics = _original + _take
                    log.info("  [K] w=%.1f %d/%d blended: %s", _weight, len(_take), _slots, ", ".join(_take))
                elif _results:
                    log.info("  [K] %d results, none qualified (w=%.1f)", len(_results), _weight)
        registry.use("knowledge_graph")
    except Exception as _exc:
        log.warning("  [K] Knowledge graph lookup failed: %s", _exc)

    try:
        log.info("[4/5] Scoring clips via LLM...")
        scored = score_clips(segments, config, topics=topics, memory_bias=memory_bias)
        AOR.register_write("scored_clips", "memory", __name__)
        if not scored:
            raise PipelineError("No clips selected by LLM")
        for i, sc in enumerate(scored):
            validate_scored_clip(sc, i)
        registry.use("score_clips")
        log.info("  [OK] %d clips scored", len(scored))
    except Exception as exc:
        registry.fail("score_clips")
        raise PipelineError(f"Clip scoring failed: {exc}") from exc

    # Step 5: Crop each clip
    log.info("[5/5] Cropping %d clips...", len(scored))
    results: List[Tuple[str, Path, Path, str, bool]] = []

    for idx, sc in enumerate(scored, 1):
        clip_slug = f"clip_{idx}"
        out_dir = root_dir / clip_slug
        out_dir.mkdir(parents=True, exist_ok=True)

        cropped_tmp = out_dir / "clip.tmp.mp4"
        crop_x = None
        if getattr(config, "auto_reframe", False) and config.content_type != "football":
            crop_x = detect_crop_x(video_path, sc.start, sc.end)
            if crop_x is not None:
                log.info("  [reframe] %s subject-centred crop_x=%d", clip_slug, crop_x)
            else:
                log.info("  [reframe] %s no face found, centre crop", clip_slug)
        cmd = build_crop_command(video_path, sc.start, sc.end, cropped_tmp, config, crop_x=crop_x)
        validate_ffmpeg_command(cmd, "crop")
        execute(cmd)
        _assert_valid_video(cropped_tmp)
        cropped_tmp.rename(out_dir / "clip.mp4")
        cropped = out_dir / "clip.mp4"
        AOR.register_write("cropped_clip", cropped, __name__)
        if config.gpu_enabled:
            registry.use("gpu_encode")
        registry.use("crop")

        # Save state.json
        clip_segments = []
        for s in segments:
            if s.end <= sc.start or s.start >= sc.end:
                continue
            clip_segments.append({
                "start": round(max(0, s.start - sc.start), 2),
                "end": round(min(s.end, sc.end) - sc.start, 2),
                "text": s.text.strip(),
            })
        state_data = {
            "source_video_url": url,
            "pipeline_stage": "analysis_complete",
            "clips": [{
                "start": sc.start, "end": sc.end,
                "hook_text": sc.hook_text, "score": sc.score_total,
                "metadata": {
                    "intro_script": sc.intro_script,
                    "outro_script": sc.outro_script,
                    "reason": sc.reason,
                    "scores": sc.scores,
                },
            }],
            "transcript": clip_segments,
        }
        validate_state(state_data)
        write_state(out_dir / "state.json", state_data)

        log.info("  [%d] clip_%d: %.1f-%.1fs (%.1fs) score=%.1f hook='%s'",
                 idx, idx, sc.start, sc.end, sc.duration, sc.score_total, sc.hook_text)
        results.append((clip_slug, out_dir, cropped, sc.hook_text, bool(sc.hook_text)))

    log.info("=== Phase 1 complete: %d clips in %s ===", len(results), root_dir)
    return results
