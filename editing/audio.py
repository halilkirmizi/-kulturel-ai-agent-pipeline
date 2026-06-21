"""Audio command builders — enhance and mix.

No subprocess. No FFmpeg execution. Builds command lists and filter strings only.
"""

from __future__ import annotations

from pathlib import Path

from core.config import PipelineConfig
from editing.ffmpeg_builder import ffmpeg_path


def build_enhance_command(input_path: Path, output_path: Path, config: PipelineConfig) -> list:
    """Build FFmpeg command for audio noise reduction, EQ, normalization.

    Returns:
        Command list for ffmpeg_builder.execute().
    """
    audio_cfg = config.audio

    eq_parts = []
    for eq in audio_cfg.eq:
        f = eq.get("frequency", 1000)
        t = eq.get("type", "q")
        w = eq.get("width", 200)
        g = eq.get("gain", 0)
        eq_parts.append(f"equalizer=f={f}:t={t}:w={w}:g={g}")

    filter_parts = [
        f"highpass=f={audio_cfg.highpass}",
        f"lowpass=f={audio_cfg.lowpass}",
    ]
    if audio_cfg.noise_reduction:
        filter_parts.append(audio_cfg.noise_reduction)
    if audio_cfg.normalization:
        filter_parts.append(audio_cfg.normalization)
    filter_parts.extend(eq_parts)

    af_str = ",".join(filter_parts)

    return [
        ffmpeg_path(), "-y",
        "-i", str(input_path),
        "-af", af_str,
        "-c:a", "libmp3lame",
        "-b:a", audio_cfg.bitrate,
        str(output_path),
    ]


def build_audio_mix(intro_duration: float, clip_duration: float, config: PipelineConfig) -> str:
    """Build the audio portion of filter_complex for intro + clip mixing.

    Returns:
        Filter string for the audio mixing section of filter_complex.
    """
    audio_cfg = config.audio
    xfade = audio_cfg.crossfade_duration
    xfade_start = max(0, intro_duration - xfade)
    ambient_vol = audio_cfg.ambient_volume
    intro_duck = audio_cfg.intro_duck_volume

    amb_vol_expr = (
        f"'if(lt(t,{xfade_start}),{intro_duck},"
        f"if(lt(t,{intro_duration}),{intro_duck}+(t-{xfade_start})*({ambient_vol}-{intro_duck})/{xfade},{ambient_vol}))'"
    )
    intro_vol_expr = (
        f"'if(lt(t,{xfade_start}),1.0,"
        f"if(lt(t,{intro_duration}),1.0-(t-{xfade_start})/{xfade},0))'"
    )

    return (
        f"[0:a]volume=volume={amb_vol_expr}:eval=frame[ambient];"
        f"[1:a]volume=volume={intro_vol_expr}:eval=frame[intro_a];"
        "[ambient][intro_a]amix=inputs=2:duration=longest[outa]"
    )
