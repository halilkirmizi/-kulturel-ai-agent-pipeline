"""GPU-accelerated speech transcription via faster-whisper.

Usage:
    from analysis.transcription import transcribe
    segments, info = transcribe("video.mp4")
    for seg in segments:
        print(seg.start, seg.end, seg.text)
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
from typing import List, Tuple

from core.config import PipelineConfig
from core.logger import get_logger

log = get_logger(__name__)


def _cuda_available() -> bool:
    """Detect CUDA availability without hard crash."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _inject_cuda_paths() -> None:
    """Ensure CUDA DLLs are findable for faster-whisper. Safe no-op if CUDA absent."""
    try:
        for pkg in ["nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"]:
            spec = importlib.util.find_spec(pkg)
            if spec and spec.submodule_search_locations:
                for lib_dir in spec.submodule_search_locations:
                    if os.path.isdir(lib_dir):
                        os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass
    try:
        import imageio_ffmpeg
        ff_dir = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
        os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def transcribe(
    video_path: str | Path,
    config: PipelineConfig,
    model=None,
) -> Tuple[List, object]:
    """Transcribe video with word-level timestamps.

    Uses GPU (CUDA float16) by default, falls back to CPU on CUDA errors.

    Args:
        video_path: Path to video file.
        config: PipelineConfig (whisper_model, device, compute).
        model: Optional pre-loaded WhisperModel (for reuse across calls).

    Returns:
        (segments_list, info) where segments have .start, .end, .text attributes.

    Raises:
        RuntimeError: if both GPU and CPU transcription fail.
    """
    from faster_whisper import WhisperModel

    video_path = str(video_path)
    log.info("Transcribing %s (model=%s, device=%s)", video_path, config.whisper_model, config.whisper_device)

    _inject_cuda_paths()
    use_cuda = config.gpu_enabled and config.whisper_device == "cuda" and _cuda_available()

    if model is None:
        if use_cuda:
            try:
                model = WhisperModel(
                    config.whisper_model,
                    device="cuda",
                    compute_type=config.whisper_compute,
                    num_workers=1,
                    cpu_threads=4,
                )
            except Exception as exc:
                log.warning("GPU whisper init failed: %s. Falling back to CPU.", exc)
                model = WhisperModel(
                    config.whisper_model,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                )
        else:
            model = WhisperModel(
                config.whisper_model,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
            )

    try:
        segments, info = model.transcribe(
            video_path,
            beam_size=config.whisper.beam_size,
            word_timestamps=True,
            vad_filter=config.whisper.vad_filter,
            condition_on_previous_text=config.whisper.condition_on_previous_text,
            temperature=config.whisper.temperature,
            best_of=config.whisper.best_of,
            compression_ratio_threshold=config.whisper.compression_ratio_threshold,
            log_prob_threshold=config.whisper.log_prob_threshold,
        )
    except RuntimeError as exc:
        if "cublas" in str(exc).lower() or "cuda" in str(exc).lower():
            log.warning("CUDA runtime error: %s. Retrying with CPU.", exc)
            model = WhisperModel(
                config.whisper_model,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
            )
            segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)
        else:
            log.error("Whisper transcription failed: %s", exc)
            raise

    result = list(segments)
    log.info(
        "Transcription complete: %d segments, %.1f%% confidence (%s)",
        len(result),
        info.language_probability * 100,
        info.language,
    )
    return result, info


def format_transcript(segments: list, max_chars: int = 30000) -> str:
    """Format whisper segments into a timestamped transcript for LLM consumption.

    Args:
        segments: List of whisper segment objects (with .start, .end, .text).
        max_chars: Hard character cap.

    Returns:
        Formatted transcript string.
    """
    total_dur = max(s.end for s in segments) if segments else 0
    lines = [f"Total video duration: {int(total_dur // 60)}:{total_dur % 60:04.1f}"]
    for s in segments:
        start = f"{int(s.start // 60):02d}:{s.start % 60:05.2f}"
        end = f"{int(s.end // 60):02d}:{s.end % 60:05.2f}"
        lines.append(f"[{start} -> {end}] {s.text.strip()}")

    full = "\n".join(lines)
    if len(full) > max_chars:
        log.warning("Transcript truncated from %d to %d chars", len(full), max_chars)
        full = full[:max_chars]
    return full
