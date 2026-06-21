#!/usr/bin/env python3
"""YouTube Shorts Pipeline — main orchestrator.

No subprocess allowed outside ffmpeg_builder.

Stateless entry point. Each command builds a PipelineConfig and
dispatches to the appropriate modules.

Usage:
    python main.py https://youtube.com/watch?v=XXX          # Phase 1 (full)
    python main.py --url https://youtube.com/watch?v=XXX     # Phase 1 (explicit)
    python main.py --resume short_20260618_123456/clip_1     # Phase 2 (resume)
    python main.py --url ... --upload                        # Phase 1 + upload
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure pipeline root is on sys.path for module imports
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.artifact_registry import AOR, ArtifactRecord
from core.config import build_config, PipelineConfig
from core.logger import get_logger, setup_logging
from core.memory_writer import MemoryWriter
from core.steptracker import StepTracker
from core.feature_registry import registry
from core.contract_validator import (
    validate_state,
    validate_scored_clip,
    validate_ffmpeg_command,
    validate_dag_transition,
)

log = get_logger(__name__)

# ── Feature declarations ───────────────────────────────────────
registry.declare("step_tracker", "core", "Execution step gating with persistence")
registry.declare("download_video", "core", "yt-dlp video download")
registry.declare("transcribe", "core", "Whisper GPU/CPU transcription")
registry.declare("extract_topics", "core", "Keyword extraction from transcript")
registry.declare("knowledge_graph", "optional", "Obsidian graph enrichment")
registry.declare("score_clips", "core", "Groq LLM clip scoring")
registry.declare("crop", "core", "FFmpeg segment crop to 9:16")
registry.declare("translate", "optional", "Groq LLM translation es->en")
registry.declare("audio_enhance", "core", "Audio noise reduction and EQ")
registry.declare("captions", "core", "ASS subtitle generation")
registry.declare("compose", "core", "Final video composition with overlays")
registry.declare("gpu_encode", "optional", "NVENC GPU accelerated encoding")
registry.declare("upload", "optional", "YouTube Data API upload")

# ── AOR declarations ─────────────────────────────────────────
AOR.declare(ArtifactRecord(name="source_video", path_pattern="temp/<id>.mp4", owner="ingest.downloader", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="transcript_segments", path_pattern="memory", owner="analysis.transcription", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="topics", path_pattern="memory", owner="analysis.topic_detection", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="scored_clips", path_pattern="memory", owner="analysis.clip_scoring", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="cropped_clip", path_pattern="shorts_output/.../clip.mp4", owner="editing.render_core", lifecycle="derived", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="state_json", path_pattern="shorts_output/.../state.json", owner="core.state", lifecycle="persistent", source_of_truth=True))
AOR.declare(ArtifactRecord(name="enhanced_intro", path_pattern="temp/intro_enhanced_<hash>.mp3", owner="editing.audio", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="captions_ass", path_pattern="shorts_output/.../captions.ass", owner="editing.captions", lifecycle="derived", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="captioned_video", path_pattern="temp/captioned_<hash>.mp4", owner="editing.render_core", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="final_video", path_pattern="shorts_output/.../final.mp4", owner="editing.render_core", lifecycle="persistent", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="execution_trace", path_pattern="execution_trace.json", owner="core.steptracker", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="upload_log", path_pattern="upload/.upload_log.json", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="upload_quota", path_pattern="upload/.upload_quota.json", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="graph_store", path_pattern="obsidian_bridge/graph_store.json", owner="obsidian_bridge.build_graph", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="format_config", path_pattern="formats/format1.json", owner="core.config", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="oauth_token", path_pattern="~/.youtube_upload_token.pickle", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="client_secret", path_pattern="upload/client_secret.json", owner="upload.youtube", lifecycle="persistent"))
AOR.freeze()


# ──────────────────────────────────────────────
# Phase 1: download → transcribe → score → crop
# ──────────────────────────────────────────────


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
    from editing.ffmpeg_builder import probe_duration, probe_file

    if not path.exists():
        raise PipelineError(f"Video artifact missing: {path}")
    if path.stat().st_size == 0:
        raise PipelineError(f"Video artifact empty: {path}")

    dur = probe_duration(path)
    if dur <= 0:
        raise PipelineError(f"Video artifact unreadable (probe returned 0): {path}")

    # Optional: deep probe via ffprobe (gracefully degrade if unavailable)
    info = probe_file(path)
    streams = info.get("streams", [])
    if streams:
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        if not video_streams:
            raise PipelineError(f"Video artifact has no video stream: {path}")
        if video_streams[0].get("codec_name") in (None, "unknown"):
            raise PipelineError(f"Video artifact has unknown codec: {path}")


def _run_phase1(
    url: str,
    config: PipelineConfig,
    memory_bias: Optional[Dict] = None,
) -> List[Tuple[str, Path, Path, str, bool]]:
    """Execute full Phase 1 pipeline."""
    from datetime import datetime

    from ingest.downloader import download_video
    from analysis.transcription import transcribe, format_transcript
    from analysis.topic_detection import extract_topics
    from analysis.clip_scoring import score_clips
    from editing.render_core import build_crop_command
    from editing.ffmpeg_builder import execute
    from core.state import write_state

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
    #   weight = 0.3  if low topic overlap (graph brings novel context)
    #   weight = 0.1  if high topic overlap (graph confirms, adds little)
    #   weight = 0.0  if graph confidence low (avg score < 3)
    #   Final topics = original + (qualified_graph × weight).
    _original = topics[:]
    try:
        if not _original:
            log.info("  [K] Skipping (no base topics to enrich)")
        else:
            from obsidian_bridge.graph_query import query_graph
            _gp = Path(__file__).resolve().parent / "obsidian_bridge" / "graph_store.json"
            if not _gp.exists():
                log.warning("  [K] Graph store missing: %s", _gp)
            else:
                import json as _json
                _graph = _json.loads(_gp.read_text(encoding="utf-8"))
                AOR.register_read("graph_store", _gp, __name__)
                _results = query_graph(_graph, " ".join(_original))

                # Adaptive weight from graph confidence + topic overlap
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
        cmd = build_crop_command(video_path, sc.start, sc.end, cropped_tmp, config)
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


# ──────────────────────────────────────────────
# Phase 2: captions → compose final
# ──────────────────────────────────────────────


def _run_phase2(
    resume_path: str,
    config: PipelineConfig,
    intro_audio: Optional[Path] = None,
    translate: bool = False,
) -> Path:
    """Execute Phase 2: captions + composition for a single clip.

    Args:
        resume_path: 'short_TIMESTAMP/clip_N' relative path.
        config: PipelineConfig.
        intro_audio: Optional intro/enhanced audio. If None, searches clip dir.

    Returns:
        Path to final.mp4.
    """
    from core.state import read_state, write_state
    from editing.captions import write_ass
    from editing.ffmpeg_builder import ffmpeg_path
    from editing.render_core import build_compose_command
    from editing.audio import build_enhance_command
    from editing.ffmpeg_builder import execute, probe_duration

    clip_dir = config.output_path() / resume_path
    if not clip_dir.exists():
        raise PipelineError(f"Clip directory not found: {clip_dir}")

    clip_path = clip_dir / "clip.mp4"
    if not clip_path.exists():
        raise PipelineError(f"clip.mp4 not found in {clip_dir}")

    # Find or copy intro audio
    if intro_audio is None:
        intro_candidates = list(clip_dir.glob("intro.*"))
        if not intro_candidates:
            raise PipelineError(f"No intro audio found in {clip_dir} (place intro.mp3)")
        intro_audio = intro_candidates[0]

    log.info("=== Phase 2 starting: %s ===", clip_dir.name)

    # Load state.json and resolve DAG
    state = read_state(clip_dir / "state.json")
    validate_state(state)
    next_stage = _resolve_dag(state, clip_dir)

    if next_stage is None:
        log.info("Pipeline already complete (stage=uploaded or blocked) — exiting")
        sys.exit(0)

    if next_stage == "analysis":
        raise PipelineError("DAG suggests 'analysis' but Phase 2 context cannot run analysis — corrupt state?")

    if next_stage == "upload":
        final_path = clip_dir / "final.mp4"
        if not final_path.exists():
            raise PipelineError(f"DAG suggests 'upload' but final.mp4 not found in {clip_dir}")
        log.info("DAG suggests 'upload' — skipping Phase 2 work")
        return final_path

    segments_raw = state["transcript"]
    # Convert to objects with .start, .end, .text attributes
    class _Seg:
        def __init__(self, d): self.start, self.end, self.text = d["start"], d["end"], d["text"]
    segments = [_Seg(s) for s in segments_raw]
    log.info("  [OK] Loaded %d segments from state.json", len(segments))

    if translate:
        try:
            log.info("[1.5/4] Translating captions (es -> en)...")
            from analysis.translation import translate_segments
            segments = translate_segments(segments, config)
            registry.use("translate")
            log.info("  [OK] Translation complete")
        except Exception as exc:
            raise PipelineError(f"Translation failed: {exc}") from exc

    try:
        log.info("[2/4] Enhancing intro audio...")
        config.temp_path().mkdir(parents=True, exist_ok=True)
        intro_enhanced = config.temp_path() / f"intro_enhanced_{os.urandom(4).hex()}.mp3"
        cmd = build_enhance_command(intro_audio, intro_enhanced, config)
        validate_ffmpeg_command(cmd, "enhance")
        execute(cmd)
        AOR.register_write("enhanced_intro", intro_enhanced, __name__)
        registry.use("audio_enhance")
        log.info("  [OK] Audio enhanced")
    except Exception as exc:
        state["pipeline_stage"] = "render_failed"
        write_state(clip_dir / "state.json", state)
        raise PipelineError(f"Audio enhance failed: {exc}") from exc

    if config.captions.enabled:
        try:
            log.info("[3/4] Generating subtitles...")
            clip_dur = probe_duration(clip_path)
            ass_path = clip_dir / "captions.ass"
            write_ass(segments, ass_path, clip_dur, 0.0,
                      fontsize=config.captions.fontsize,
                      margin_bottom=config.captions.margin_bottom)

            captioned = config.temp_path() / f"captioned_{os.urandom(4).hex()}.mp4"
            ass_escaped = ass_path.as_posix().replace(":", "\\:")
            vf = f"subtitles='{ass_escaped}':original_size=1080x1920"
            cmd = [
                ffmpeg_path(), "-y",
                "-i", str(clip_path),
                "-vf", vf,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "copy",
                "-vsync", "0",
                str(captioned),
            ]
            rc = execute(cmd)
            if rc != 0:
                cmd[cmd.index("-crf") + 1] = "23"
                rc = execute(cmd)
                if rc != 0:
                    raise RuntimeError(f"Subtitle render failed (rc={rc})")
            AOR.register_write("captioned_video", captioned, __name__)
            registry.use("captions")
            log.info("  [OK] Captions applied")
        except Exception as exc:
            state["pipeline_stage"] = "render_failed"
            write_state(clip_dir / "state.json", state)
            raise PipelineError(f"Caption overlay failed: {exc}") from exc
    else:
        log.info("[3/4] Skipping captions (disabled per --no-captions)")
        captioned = clip_path

    try:
        log.info("[4/4] Composing final video...")
        hook_text = state["clips"][0].get("hook_text", "")
        final_tmp = clip_dir / "final.tmp.mp4"
        intro_dur = probe_duration(intro_enhanced)
        clip_dur = probe_duration(captioned)
        cmd = build_compose_command(captioned, intro_enhanced, final_tmp, hook_text, config, intro_dur, clip_dur)
        validate_ffmpeg_command(cmd, "compose")
        execute(cmd)
        _assert_valid_video(final_tmp)
        final_tmp.rename(clip_dir / "final.mp4")
        final_path = clip_dir / "final.mp4"
        AOR.register_write("final_video", final_path, __name__)
        if config.gpu_enabled:
            registry.use("gpu_encode")
        registry.use("compose")
        log.info("  [OK] Composition complete")
    except Exception as exc:
        state["pipeline_stage"] = "render_failed"
        write_state(clip_dir / "state.json", state)
        raise PipelineError(f"Composition failed: {exc}") from exc

    state["pipeline_stage"] = "render_complete"
    write_state(clip_dir / "state.json", state)

    log.info("=== Phase 2 complete: %s ===", final_path)
    return final_path


# ──────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────


def _do_upload(final_path: Path, config: PipelineConfig) -> None:
    """Upload final video. Blocks upload if state or artifact is invalid."""
    if not config.upload_enabled:
        return

    from upload.youtube import upload_with_retry
    from core.state import read_state, write_state

    log.info("Uploading %s to YouTube...", final_path.name)

    state_path = final_path.parent / "state.json"
    if not state_path.exists():
        raise PipelineError("Upload: state.json not found — cannot upload")

    try:
        state = read_state(state_path)
        validate_state(state)
        clip = state["clips"][0]
        hook = clip.get("hook_text", "")
        reason = clip.get("metadata", {}).get("reason", "")
        title = hook if hook else "Untitled Analytical Short"
        description = f"{reason}\n\n#shorts #analysis #culture" if reason else ""
    except Exception as exc:
        raise PipelineError(f"Upload: state.json invalid — {exc}") from exc

    try:
        _assert_valid_video(final_path)
    except PipelineError:
        state["pipeline_stage"] = "upload_blocked"
        write_state(state_path, state)
        raise

    state["pipeline_stage"] = "ready_for_upload"
    write_state(state_path, state)

    try:
        ok = upload_with_retry(
            str(final_path),
            title=title,
            description=description,
            privacy_status="unlisted" if config.schedule_days < 0 else "private",
            schedule_days=config.schedule_days,
        )
        if ok:
            log.info("  [OK] Upload complete")
            state["pipeline_stage"] = "uploaded"
            write_state(state_path, state)
            registry.use("upload")
        else:
            log.warning("  [FAIL] Upload failed — pipeline continues")
            state["pipeline_stage"] = "upload_failed"
            write_state(state_path, state)
    except Exception as exc:
        log.warning("  [FAIL] Upload error: %s — pipeline continues", exc)
        state["pipeline_stage"] = "upload_failed"
        write_state(state_path, state)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analytical YouTube Shorts Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py https://youtube.com/watch?v=xxx\n"
            "  python main.py --url https://youtube.com/watch?v=xxx --upload\n"
            "  python main.py --resume short_20260618_123456/clip_1\n"
        ),
    )
    parser.add_argument("url", nargs="?", help="YouTube video URL for Phase 1")
    parser.add_argument("--resume", help="Resume Phase 2 from clip path (e.g. short_XXX/clip_1)")
    parser.add_argument("--format", default="format1", help="Format config name (default: format1)")
    parser.add_argument("--content-type", default="general", choices=["general", "football"],
                        help="Content type for specialized framing (default: general)")
    parser.add_argument("--upload", action="store_true", help="Upload final video to YouTube")
    parser.add_argument("--schedule", type=int, default=-1, help="Schedule upload N days from now")
    parser.add_argument("--no-captions", action="store_true", help="Skip caption overlay")
    parser.add_argument("--translate", action="store_true", help="Translate captions (es->en)")
    parser.add_argument("--intro", help="Path to intro audio (default: search clip dir)")
    parser.add_argument("--gpu", action="store_true", default=True, help="Enable GPU acceleration")
    parser.add_argument("--no-gpu", action="store_false", dest="gpu", help="Disable GPU acceleration")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")
    parser.add_argument("--memory-report", action="store_true",
                        help="Print memory store summary and exit")
    parser.add_argument("--memory-dry-run", action="store_true",
                        help="Run memory write-back in dry-run mode (no save)")
    parser.add_argument("--memory-compact", action="store_true",
                        help="Dedup and prune old memory entries")
    parser.add_argument("--mode", default="observation_only",
                        choices=["observation_only", "adaptive_mode"],
                        help="Memory influence mode (default: observation_only)")
    parser.add_argument("--trace-arbiter", action="store_true",
                        help="Print full arbitration decision chain")
    return parser.parse_args(argv)


def _run_memory_writer(
    tracker: StepTracker,
    aor_path: Path,
    root_dir: Path,
    dry_run: bool = False,
) -> None:
    """Collect signals and run memory write-back."""
    from core.memory_writer import MemoryWriter
    mw = MemoryWriter(root_dir)
    summary = mw.run(
        execution_trace_path=tracker._path,
        aor_state_path=aor_path,
        dry_run=dry_run,
    )
    if summary["promoted"] > 0:
        log.info("Memory: %d new entries (dry_run=%s)", summary["promoted"], dry_run)


def main(argv: Optional[List[str]] = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)

    # Setup logging
    setup_logging(level=args.log_level)
    log.info("Pipeline starting (format=%s, gpu=%s, upload=%s)", args.format, args.gpu, args.upload)

    # Build config
    config = build_config(
        format_name=args.format,
        content_type=args.content_type,
        gpu=args.gpu,
        upload=args.upload,
        schedule_days=args.schedule,
        no_captions=args.no_captions,
    )
    AOR.register_read("format_config", f"formats/{args.format}.json", __name__)

    # Load persisted AOR state
    aor_path = config.output_path() / ".artifact_registry.json"
    AOR.load(aor_path)

    # Standalone memory commands
    mw = MemoryWriter(_HERE)
    if args.memory_report:
        report = mw.store.report()
        print(f"Memory store: {report['total']} entries")
        for cat, count in report["counts"].items():
            print(f"  {cat}: {count}")
        print(f"  path: {report['path']}")
        return
    if args.memory_compact:
        removed = mw.store.compact()
        print(f"Memory compact: {removed} entries removed")
        return

    # Memory dry-run flag — passed to _run_memory_writer after pipeline
    _memory_dry_run = args.memory_dry_run

    # ── Memory influence engine ────────────────────────────────
    from core.memory_influence import MemoryInfluenceEngine
    influence = MemoryInfluenceEngine(_HERE / "memory_store.json", mode=args.mode)
    influence_patch = influence.compute_patch()

    # ── Control arbiter — resolves all influence inputs ────────
    from core.control_arbiter import ControlArbiter, ArbitrationInput
    arbiter = ControlArbiter(trace_enabled=args.trace_arbiter)

    # Get StepTracker heuristics from local trace (if resuming)
    tracker = StepTracker(config.output_path())
    step_hints = tracker.heuristic_adjustments()

    arbiter_input = ArbitrationInput(
        memory_threshold_adjustments=influence_patch.threshold_adjustments,
        memory_scoring_bias=influence_patch.scoring_bias,
        memory_routing=influence_patch.pipeline_routing,
        step_threshold_adjustments=step_hints,
    )

    unified_config = arbiter.resolve(arbiter_input)
    flat_config = unified_config.to_flat_dict()

    if flat_config:
        log.info("ControlArbiter resolved runtime config (mode=%s)", args.mode)
        for section, values in flat_config.items():
            log.info("  %s: %s", section, values)
    if args.trace_arbiter:
        arbiter.print_trace()

    # Apply resolved config
    tracker.apply_influence(flat_config)
    registry.use("step_tracker")

    if args.resume:
        # Phase 2
        tracker.gate()
        sid = tracker.begin("phase_2")
        try:
            intro_path = Path(args.intro) if args.intro else None
            final = _run_phase2(args.resume, config, intro_audio=intro_path, translate=args.translate)
            _do_upload(final, config)
            tracker.complete(sid, artifacts=[str(final)], notes="Phase 2 render + upload done")
        except PipelineError as exc:
            tracker.fail(sid, reason=str(exc))
            log.error("Phase 2 failed: %s", exc)
            AOR.print_report()
            registry.print_report()
            AOR.save(aor_path)
            _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
            sys.exit(1)
        AOR.print_report()
        registry.print_report()
        AOR.save(aor_path)
        _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
        return

    if args.url:
        # Phase 1
        tracker.gate()
        sid = tracker.begin("phase_1")
        try:
            bias = flat_config.get("scoring_bias") if flat_config else None
            results = _run_phase1(args.url, config, memory_bias=bias)
            artifacts = [str(r[1]) for r in results]
            tracker.complete(sid, artifacts=artifacts, notes=f"{len(results)} clips produced")
        except PipelineError as exc:
            tracker.fail(sid, reason=str(exc))
            log.error("Phase 1 failed: %s", exc)
            AOR.print_report()
            registry.print_report()
            AOR.save(aor_path)
            _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
            sys.exit(1)

        AOR.print_report()
        registry.print_report()
        AOR.save(aor_path)
        _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
        log.info("Pipeline complete. %d clips produced.", len(results))
        for clip_slug, clip_dir, _, hook, _ in results:
            rel = clip_dir.relative_to(config.output_path())
            log.info("  %s: hook='%s'", rel, hook)
        if config.upload_enabled:
            log.warning("Upload flag set but Phase 2 (captions+compose) not run yet.")
            log.warning("Run: python main.py --resume <path> --upload")
        return

    # No args
    print("Usage: python main.py <URL>")
    print("       python main.py --resume <clip_path>")
    print("       python main.py <URL> --upload")
    AOR.print_report()
    registry.print_report()
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except PipelineError as exc:
        log.error("=== PIPELINE FAILED at stage: %s ===", exc)
        AOR.print_report()
        registry.print_report()
        sys.exit(1)
    except KeyboardInterrupt:
        AOR.print_report()
        registry.print_report()
        log.warning("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as exc:
        log.error("=== UNEXPECTED PIPELINE FAILURE: %s ===", exc, exc_info=True)
        AOR.print_report()
        registry.print_report()
        sys.exit(1)
