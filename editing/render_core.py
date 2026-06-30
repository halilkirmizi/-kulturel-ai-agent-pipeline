"""Pure FFmpeg command builders — crop and compose.

No subprocess. No file I/O. No execution. Returns command lists only.
All durations and dimensions are received as parameters (never probed internally).
"""

from __future__ import annotations

from pathlib import Path


from core.config import PipelineConfig
from editing.ffmpeg_builder import ffmpeg_path, gpu_encode_args
from editing.overlays import build_hook_overlay, build_subscribe_overlay
from editing.audio import build_audio_mix


def build_crop_command(
    video_path: Path,
    start: float,
    end: float,
    output_path: Path,
    config: PipelineConfig,
    crop_x: int | None = None,
) -> list:
    """Build FFmpeg command to crop a segment to 9:16 vertical (1080x1920).

    Args:
        crop_x: optional horizontal pixel offset for the crop window. When
            ``None`` the window is centred (the original behaviour). When an
            integer is given (from ``analysis.reframe.detect_crop_x``) the
            window is shifted to keep the subject in frame. Only honoured for
            the general content type; ``football`` keeps its own framing.

    Returns:
        Command list for ffmpeg_builder.execute().
    """
    duration = end - start
    clip_cfg = config.clip

    vf_parts = ["setpts=PTS-STARTPTS"]

    if config.content_type == "football":
        vf_parts.append("crop=ih*9/16:ih-160:(iw-ih*9/16)/2:0")
        vf_parts.append("scale=1080:1920")
        vf_parts.append("setsar=1")
    else:
        # Crop with extra height to include hardcoded subtitles at bottom
        # Use exact 9:16 ratio, scale handles the rest
        if crop_x is None:
            x_expr = "(iw-ih*9/16)/2"  # centred (default)
        else:
            x_expr = str(int(crop_x))  # subject-centred (auto-reframe)
        vf_parts.append(f"crop=ih*9/16:ih:{x_expr}:0")
        vf_parts.append(f"scale=1080:1920:flags={clip_cfg.resize_flags}")
        vf_parts.append("setsar=1")

    vf = ",".join(vf_parts)

    cmd = [
        ffmpeg_path(), "-y",
        "-ss", str(start),
        "-i", str(video_path),
        "-t", str(duration),
        "-vf", vf,
        "-c:a", "aac",
        "-b:a", "128k",
        "-vsync", "0",
    ]
    cmd.extend(gpu_encode_args(config))
    cmd.append(str(output_path))

    if config.gpu_enabled:
        cmd.insert(cmd.index("-ss"), "-hwaccel")
        cmd.insert(cmd.index("-hwaccel") + 1, "cuda")

    return cmd


def build_compose_command(
    clip_captioned: Path,
    intro_audio: Path,
    output_path: Path,
    hook_text: str,
    config: PipelineConfig,
    intro_duration: float,
    clip_duration: float,
) -> list:
    """Build FFmpeg command for final composition (overlays + audio mix).

    All durations must be pre-probed and passed explicitly.

    Returns:
        Command list for ffmpeg_builder.execute().
    """
    vf_parts = []

    hook_str = build_hook_overlay(hook_text, config)
    if hook_str:
        vf_parts.append(hook_str)

    sub_str = build_subscribe_overlay(config, clip_duration)
    vf_parts.append(sub_str)

    vf_str = ",".join(vf_parts)

    audio_mix = build_audio_mix(intro_duration, clip_duration, config)

    filter_complex = f"[0:v]{vf_str}[allv];" + audio_mix

    cmd = [
        ffmpeg_path(), "-y",
        "-i", str(clip_captioned),
        "-i", str(intro_audio),
        "-filter_complex", filter_complex,
        "-map", "[allv]",
        "-map", "[outa]",
        "-vsync", "0",
    ]
    cmd.extend(gpu_encode_args(config))
    cmd.extend([
        "-c:a", config.compose.audio_codec,
        "-b:a", config.compose.audio_bitrate,
        str(output_path),
    ])

    if config.gpu_enabled:
        cmd.insert(1, "-hwaccel")
        cmd.insert(2, "cuda")

    return cmd
