"""Pure drawtext string builders for hook and subscribe overlays.

No subprocess. No FFmpeg execution. No file I/O. Pure string functions only.
"""

from __future__ import annotations

from core.config import PipelineConfig


def esc(text: str) -> str:
    return (
        text.replace("'", "'\\''")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("%", "\\\\%")
    )


def build_hook_overlay(hook_text: str, config: PipelineConfig) -> str:
    """Build a drawtext filter string for the hook overlay.

    Args:
        hook_text: The hook text to display.
        config: PipelineConfig (uses hook section).

    Returns:
        FFmpeg drawtext filter string, or empty string if no hook_text.
    """
    if not hook_text:
        return ""

    hook = config.hook
    font_esc = hook.font.replace(":", "\\:")
    display = esc(hook_text.upper() if hook.uppercase else hook_text)

    return (
        f"drawtext=text='{display}'"
        f":fontcolor=white:fontsize={hook.fontsize}"
        f":fontfile='{font_esc}'"
        f":x=(w-text_w)/2:y={hook.y}"
        f":enable='between(t,0,{hook.duration})'"
        f":shadowcolor=black:shadowx=2:shadowy=2"
    )


def build_subscribe_overlay(config: PipelineConfig, clip_duration: float) -> str:
    """Build a drawtext filter string for the subscribe overlay.

    Args:
        config: PipelineConfig (uses subscribe section).
        clip_duration: Total clip duration in seconds.

    Returns:
        FFmpeg drawtext filter string.
    """
    sub = config.subscribe
    sub_dur = sub.duration
    sub_start = max(0, clip_duration - sub_dur)
    font_esc = sub.font.replace(":", "\\:")
    display = esc(sub.text)

    parts = [
        f"drawtext=text='{display}'",
        f":fontcolor={sub.fontcolor}:fontsize={sub.fontsize}",
        f":fontfile='{font_esc}'",
        f":x=(w-text_w)/2:y=(h-text_h)/2",
        f":enable='gte(t,{sub_start})*lt(t,{clip_duration})'",
    ]
    if sub.borderw > 0 and sub.bordercolor:
        parts.append(f":bordercolor={sub.bordercolor}:borderw={sub.borderw}")
    parts.append(f":shadowcolor=black:shadowx=2:shadowy=2")

    return "".join(parts)
