"""Phase 2: audio enhance => captions => compose final.

Orchestrates the second half of the pipeline:
1. Load state.json and resolve DAG
2. Optionally translate captions
3. Enhance intro audio
4. Generate ASS subtitles (optional)
5. Compose final video with overlays
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from core.config import PipelineConfig
from core.logger import get_logger
from core.feature_registry import registry
from core.contract_validator import validate_state, validate_ffmpeg_command
from core.state import read_state, write_state
from core.artifact_registry import AOR
from analysis.translation import translate_segments
from editing.captions import write_ass
from editing.ffmpeg_builder import ffmpeg_path, execute, probe_duration
from editing.render_core import build_compose_command
from editing.audio import build_enhance_command


log = get_logger(__name__)


# ── Phase 2 Feature Declarations ──────────────────────────────────
registry.declare("translate", "optional", "Groq LLM translation es->en")
registry.declare("audio_enhance", "core", "Audio noise reduction and EQ")
registry.declare("captions", "core", "ASS subtitle generation")
registry.declare("compose", "core", "Final video composition with overlays")
registry.declare("gpu_encode", "optional", "NVENC GPU accelerated encoding (phase2)")


class PipelineError(Exception):
    """Base exception for pipeline stage failures."""


def _assert_valid_video(path: Path) -> None:
    """Validate video file via existence, size, ffmpeg probe."""
    from editing.ffmpeg_builder import probe_duration, probe_file

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


def run_phase2(
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
    from core.phase1 import _resolve_dag, PipelineError

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
                      margin_bottom=config.captions.margin_bottom,
                      karaoke=config.captions.karaoke,
                      highlight_color=config.captions.highlight_color)

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
        final_tmp.replace(clip_dir / "final.mp4")  # replace: overwrites on re-run (Windows rename does not)
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
