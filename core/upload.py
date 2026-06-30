"""Upload final video to YouTube via Data API v3 OAuth.

Reads state.json for title/description, validates artifacts,
and uploads with retry + quota tracking.
"""

from __future__ import annotations

from pathlib import Path

from core.config import PipelineConfig
from core.logger import get_logger
from core.feature_registry import registry
from core.contract_validator import validate_state
from core.state import read_state, write_state
from upload.youtube import upload_with_retry


log = get_logger(__name__)


# ── Upload Feature Declaration ────────────────────────────────────
registry.declare("upload", "optional", "YouTube Data API upload")


class PipelineError(Exception):
    """Base exception for pipeline stage failures."""


# Performance store lives at pipeline root (gitignored, like memory_store.json).
PERF_STORE = Path(__file__).resolve().parent.parent / "performance_store.json"


def _record_provenance(video_id: str, state: dict, config: PipelineConfig) -> None:
    """Record what produced this upload, so analytics can be tied back later.

    Best-effort: never breaks the upload on failure.
    """
    try:
        from core.performance import PerformanceStore, build_record
        features = {
            "auto_reframe": getattr(config, "auto_reframe", False),
            "karaoke": config.captions.karaoke,
            "trim_silence": getattr(config, "trim_silence", False),
        }
        store = PerformanceStore(PERF_STORE)
        store.upsert(build_record(video_id, state, features))
        store.save()
        log.info("  [perf] provenance recorded for %s", video_id)
    except Exception as exc:
        log.warning("  [perf] provenance record failed: %s", exc)


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


def run_upload(final_path: Path, config: PipelineConfig) -> None:
    """Upload final video. Blocks upload if state or artifact is invalid."""
    if not config.upload_enabled:
        return

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
        video_id = upload_with_retry(
            str(final_path),
            title=title,
            description=description,
            privacy_status="unlisted" if config.schedule_days < 0 else "private",
            schedule_days=config.schedule_days,
        )
        if video_id:
            log.info("  [OK] Upload complete")
            state["pipeline_stage"] = "uploaded"
            state["youtube_video_id"] = video_id
            write_state(state_path, state)
            registry.use("upload")
            _record_provenance(video_id, state, config)
        else:
            log.warning("  [FAIL] Upload failed — pipeline continues")
            state["pipeline_stage"] = "upload_failed"
            write_state(state_path, state)
    except Exception as exc:
        log.warning("  [FAIL] Upload error: %s — pipeline continues", exc)
        state["pipeline_stage"] = "upload_failed"
        write_state(state_path, state)
