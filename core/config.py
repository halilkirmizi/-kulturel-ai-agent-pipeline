"""Central configuration loader.

Loads format JSON + environment variables into a single immutable config object.
No global mutable state — each module receives its config explicitly.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv


@dataclass(frozen=True)
class CaptionConfig:
    enabled: bool = True
    fontsize: int = 38
    uppercase: bool = True
    outline: int = 2
    box_border: int = 4
    margin_bottom: int = 160
    box_color: str = "black@0.4"
    shadow_color: str = "black"
    font: str = "C:/Windows/Fonts/impact.ttf"
    # Karaoke (per-word highlight). Opt-in; default keeps static captions.
    karaoke: bool = False
    highlight_color: str = "&H0000FFFF"  # ASS BBGGRR — yellow


@dataclass(frozen=True)
class AudioConfig:
    highpass: int = 80
    lowpass: int = 8000
    noise_reduction: str = "anlmdn=s=6:p=0.05"
    normalization: str = "dynaudnorm=f=150:g=15:p=0.95"
    bitrate: str = "192k"
    eq: List[Dict[str, Any]] = field(default_factory=list)
    ambient_volume: float = 0.90
    intro_duck_volume: float = 0.70
    crossfade_duration: float = 3.0


@dataclass(frozen=True)
class HookConfig:
    fontsize: int = 72
    uppercase: bool = True
    duration: float = 2.0
    y: str = "h*0.15"
    font: str = "C:/Windows/Fonts/impact.ttf"


@dataclass(frozen=True)
class SubscribeConfig:
    fontsize: int = 48
    text: str = "SUBSCRIBE"
    duration: float = 1.0
    font: str = "C:/Windows/Fonts/impact.ttf"
    fontcolor: str = "white"
    bordercolor: str = "black"
    borderw: int = 3


@dataclass(frozen=True)
class WhisperConfig:
    # Speed
    beam_size: int = 1
    vad_filter: bool = True
    condition_on_previous_text: bool = False
    # Safety
    temperature: float = 0.0
    best_of: int = 1
    # Memory stability
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0


@dataclass(frozen=True)
class ClipConfig:
    resize_flags: str = "lanczos"


@dataclass(frozen=True)
class ComposeConfig:
    codec: str = "libx264"
    preset: str = "fast"
    crf: int = 23
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"


@dataclass(frozen=True)
class PipelineConfig:
    """Immutable pipeline configuration."""

    # Whisper
    whisper_model: str = "base"
    whisper_device: str = "cuda"
    whisper_compute: str = "float16"
    # "transcribe" = source language; "translate" = Whisper translates any
    # source language directly to English (used for non-English sources).
    whisper_task: str = "transcribe"

    # LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.3
    llm_max_chars: int = 30000

    # Stock media (news mode) — license-safe b-roll/photos
    pixabay_api_key: str = ""

    # Clip-selection provider: "groq" (default) or "claude" (Anthropic — stronger
    # editorial judgment). Claude path reads ANTHROPIC_API_KEY from env.
    select_provider: str = "groq"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # Paths
    output_dir: Path = Path("./shorts_output")
    temp_dir: Path = Path("./temp")

    # Content
    content_type: str = "general"

    # Framing: "crop" (9:16 centre crop, default) or "fit" (full frame on
    # blurred fill — keeps full-width burned-in subtitles visible).
    framing: str = "crop"

    # Clip selection: rich window context (full text) by default. Set legacy_select
    # to revert to the old preview-only listing.
    legacy_select: bool = False

    # Apply learned scoring-dimension weights (closes the feedback loop). Opt-in;
    # no-op until a confident weights proposal exists.
    apply_weights: bool = False

    # Reframe (subject-aware crop). Opt-in; default keeps centre crop.
    auto_reframe: bool = False

    # Silence trim (pre-transcription, keeps captions in sync). Opt-in.
    trim_silence: bool = False
    silence_noise_db: str = "-30dB"
    silence_min_dur: float = 0.5

    # Format
    format_name: str = "format1"

    # Video
    clip: ClipConfig = field(default_factory=ClipConfig)
    hook: HookConfig = field(default_factory=HookConfig)
    subscribe: SubscribeConfig = field(default_factory=SubscribeConfig)
    compose: ComposeConfig = field(default_factory=ComposeConfig)

    # Audio
    audio: AudioConfig = field(default_factory=AudioConfig)

    # Captions
    captions: CaptionConfig = field(default_factory=CaptionConfig)

    # Whisper speed/safety
    whisper: WhisperConfig = field(default_factory=WhisperConfig)

    # GPU
    gpu_enabled: bool = True

    # Upload
    upload_enabled: bool = False
    schedule_days: int = -1
    publish_at: str = ""          # exact "YYYY-MM-DD HH:MM" scheduled publish (local time)
    video_language: str = "en"    # snippet defaultLanguage / defaultAudioLanguage
    video_category_id: str = "17"  # 17 = Sports (was 22 People & Blogs)
    public: bool = False           # upload as Public; default unlisted (ignored when scheduled)

    def output_path(self) -> Path:
        return self.output_dir.resolve()

    def temp_path(self) -> Path:
        return self.temp_dir.resolve()


def load_env() -> None:
    """Load .env from pipeline root or cwd."""
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p)
            return
    load_dotenv()


def load_format(format_name: str = "format1") -> Dict[str, Any]:
    """Load a format JSON and return raw dict."""
    formats_dir = Path(__file__).resolve().parent.parent / "formats"
    path = formats_dir / f"{format_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Format not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_config(format_name: str = "format1", **overrides: Any) -> PipelineConfig:
    """Build an immutable PipelineConfig from format JSON + env + overrides.

    Keyword overrides win over everything (for CLI flag injection).
    """
    load_env()

    raw = load_format(format_name)

    def _g(section: str, key: str, default: Any = None) -> Any:
        s = raw.get(section, {})
        return s.get(key, default) if isinstance(s, dict) else default

    cap_raw = raw.get("captions", {})

    return PipelineConfig(
        # Whisper
        whisper_model=os.getenv("WHISPER_MODEL", "base"),
        whisper_device="cuda" if os.getenv("CUDA_VISIBLE_DEVICES", "") != "-1" else "cpu",
        whisper_compute="float16" if os.getenv("CUDA_VISIBLE_DEVICES", "") != "-1" else "int8",
        whisper_task=os.getenv("WHISPER_TASK", "transcribe"),
        # LLM
        groq_api_key=overrides.get("groq_api_key") or os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        llm_max_chars=int(os.getenv("LLM_MAX_CHARS", "30000")),
        select_provider=overrides.get("select_provider", os.getenv("SELECT_PROVIDER", "groq")),
        anthropic_api_key=overrides.get("anthropic_api_key") or os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8"),
        # Content
        content_type=overrides.get("content_type", "general"),
        legacy_select=overrides.get("legacy_select", False),
        apply_weights=overrides.get("apply_weights", False),
        framing=overrides.get("framing", _g("clip", "framing", "crop")),
        auto_reframe=overrides.get("auto_reframe", False),
        trim_silence=overrides.get("trim_silence", False),
        silence_noise_db=str(_g("silence", "noise_db", "-30dB")),
        silence_min_dur=float(_g("silence", "min_dur", 0.5)),

        # Format
        format_name=format_name,
        # Video
        clip=ClipConfig(
            resize_flags=_g("clip", "resize_flags", "lanczos"),
        ),
        hook=HookConfig(
            fontsize=int(_g("hook_overlay", "fontsize", 72)),
            uppercase=bool(_g("hook_overlay", "uppercase", True)),
            duration=float(_g("hook_overlay", "duration", 2.0)),
            y=_g("hook_overlay", "y", "h*0.15"),
            font=str(_g("hook_overlay", "font", "C:/Windows/Fonts/impact.ttf")),
        ),
        subscribe=SubscribeConfig(
            fontsize=int(_g("subscribe_overlay", "fontsize", 48)),
            text=_g("subscribe_overlay", "text", "SUBSCRIBE"),
            duration=float(_g("subscribe_overlay", "duration", 1.0)),
            font=_g("subscribe_overlay", "font", "C:/Windows/Fonts/impact.ttf"),
            fontcolor=_g("subscribe_overlay", "fontcolor", "white"),
            bordercolor=_g("subscribe_overlay", "bordercolor", "black"),
            borderw=int(_g("subscribe_overlay", "borderw", 3)),
        ),
        compose=ComposeConfig(
            codec=_g("compose", "codec", "libx264"),
            preset=_g("compose", "preset", "fast"),
            crf=int(_g("compose", "crf", 23)),
            audio_codec=_g("compose", "audio_codec", "aac"),
            audio_bitrate=_g("compose", "audio_bitrate", "128k"),
        ),
        audio=AudioConfig(
            highpass=int(_g("audio", "highpass", 80)),
            lowpass=int(_g("audio", "lowpass", 8000)),
            noise_reduction=_g("audio", "noise_reduction", "anlmdn=s=6:p=0.05"),
            normalization=_g("audio", "normalization", "dynaudnorm=f=150:g=15:p=0.95"),
            bitrate=_g("audio", "bitrate", "192k"),
            eq=_g("audio", "eq", []),
            ambient_volume=float(_g("audio", "ambient_volume", 0.90)),
            intro_duck_volume=float(_g("audio", "intro_duck_volume", 0.70)),
            crossfade_duration=float(_g("audio", "crossfade_duration", 3.0)),
        ),
        captions=CaptionConfig(
            # Disabled by the --no-captions flag OR by the format ("enabled": false,
            # e.g. for sources that already have burned-in subtitles).
            enabled=bool(cap_raw.get("enabled", True)) and not overrides.get("no_captions", False),
            fontsize=int(cap_raw.get("fontsize", 38)),
            uppercase=bool(cap_raw.get("uppercase", True)),
            outline=int(cap_raw.get("outline", 2)),
            box_border=int(cap_raw.get("box_border", 4)),
            margin_bottom=int(cap_raw.get("margin_bottom", 160)),
            box_color=str(cap_raw.get("box_color", "black@0.4")),
            shadow_color=str(cap_raw.get("shadow_color", "black")),
            font=str(cap_raw.get("font", "C:/Windows/Fonts/impact.ttf")),
            karaoke=bool(overrides.get("karaoke", cap_raw.get("karaoke", False))),
            highlight_color=str(cap_raw.get("highlight_color", "&H0000FFFF")),
        ),
        gpu_enabled=overrides.get("gpu", os.getenv("USE_GPU", "1") == "1"),
        whisper=WhisperConfig(
            beam_size=int(_g("whisper", "beam_size", 1)),
            vad_filter=bool(_g("whisper", "vad_filter", True)),
            condition_on_previous_text=bool(_g("whisper", "condition_on_previous_text", False)),
            temperature=float(_g("whisper", "temperature", 0.0)),
            best_of=int(_g("whisper", "best_of", 1)),
            compression_ratio_threshold=float(_g("whisper", "compression_ratio_threshold", 2.4)),
            log_prob_threshold=float(_g("whisper", "log_prob_threshold", -1.0)),
        ),
        upload_enabled=overrides.get("upload", False),
        schedule_days=overrides.get("schedule_days", -1),
        publish_at=overrides.get("publish_at", ""),
        video_language=overrides.get("video_language", os.getenv("VIDEO_LANGUAGE", "en")),
        video_category_id=os.getenv("VIDEO_CATEGORY_ID", "17"),
        public=overrides.get("public", False),
        output_dir=Path(overrides.get("output_dir", "./shorts_output")),
        temp_dir=Path(overrides.get("temp_dir", "./temp")),
    )
