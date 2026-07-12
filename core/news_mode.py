"""News mode orchestrator: topic -> script -> voice -> stock media -> montage -> upload.

A separate flow from the clip-extraction pipeline (no source download, no whisper,
no clip scoring) that reuses shared services: config, logger, demonetization,
upload. License-safe media + original narration keep it demonetization-safe;
uploads schedule to the next peak slot (12:00 / 18:00 local) — never dead-hour public.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from core.logger import get_logger

log = get_logger(__name__)

_HERE = Path(__file__).resolve().parent.parent
_MUSIC = _HERE / "assets" / "music" / "cutting-edge.mp3"
_VOICE = "en-US-GuyNeural"
_RATE = "+12%"


def next_publish_slot(slots=(12, 18)) -> str:
    """RFC3339 timestamp for the next peak slot (local tz). Never a dead hour."""
    now = datetime.now().astimezone()
    for hh in slots:
        cand = now.replace(hour=hh, minute=0, second=0, microsecond=0)
        if cand > now + timedelta(minutes=5):
            return cand.isoformat()
    nxt = (now + timedelta(days=1)).replace(hour=slots[0], minute=0, second=0, microsecond=0)
    return nxt.isoformat()


def run_news(topic: str, config) -> Path:
    """Produce (and, when config.upload_enabled, schedule-publish) a news Short.

    Script source: an authored JSON at ``config.news_script_path`` when set
    (bring-your-own-script — lets the operator condense a source article to an
    exact length), otherwise an LLM-generated script from ``topic``.
    """
    from analysis.news_script import generate_news_script, load_news_script
    from analysis import tts, stock_media
    from editing.montage import build_montage

    if not config.pixabay_api_key:
        raise RuntimeError("PIXABAY_API_KEY missing (.env) — required for news stock media")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(config.output_dir) / f"news_{ts}"
    media_dir = out_dir / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("=== News mode: %r -> %s ===", topic or config.news_script_path, out_dir.name)

    # 1. script + metadata (authored file, or LLM from topic)
    if getattr(config, "news_script_path", ""):
        script = load_news_script(config.news_script_path)
    else:
        script = generate_news_script(topic, config)
    (out_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. voiceover + timed subtitles
    voice_mp3 = out_dir / "voice.mp3"
    voice_vtt = out_dir / "voice.vtt"
    if getattr(config, "voice_file_path", ""):
        # Bring-your-own-voice: use the operator's recording instead of AI TTS.
        # A recording has no TTS-written VTT, so transcribe it to recover the
        # caption timings the montage needs (subtitle burn + visual cut pacing).
        import shutil
        from analysis.transcription import transcribe
        src = Path(config.voice_file_path)
        if not src.exists():
            raise RuntimeError(f"--voice-file not found: {src}")
        shutil.copyfile(src, voice_mp3)
        log.info("[news] using recorded voiceover %s (%d KB)", src.name, src.stat().st_size // 1024)
        segments, _ = transcribe(voice_mp3, config)
        tts.vtt_from_segments(segments, voice_vtt)
    else:
        tts.synthesize(script["narration"], voice_mp3, voice_vtt, voice=_VOICE, rate=_RATE)

    # 3. stock media, in visual order (photos = Wikimedia players, videos = Pixabay b-roll)
    visuals = script["visuals"]
    video_queries = [v["query"] for v in visuals if v["type"] == "video"]
    videos = stock_media.fetch_pixabay_videos(
        config.pixabay_api_key, video_queries, media_dir, count=len(video_queries))

    media: List[dict] = []
    photo_cache: dict = {}
    vi = 0
    for v in visuals:
        if v["type"] == "photo":
            subj = v["subject"]
            if subj not in photo_cache:
                photo_cache[subj] = stock_media.fetch_wikimedia_photo(
                    subj, media_dir / f"p_{len(photo_cache)}.jpg")
            p = photo_cache[subj]
            if p:
                media.append({"path": f"media/{Path(p).name}", "is_photo": True})
        else:
            if vi < len(videos):
                media.append({"path": f"media/{videos[vi].name}", "is_photo": False,
                              "start": 1 + (vi % 3)})
                vi += 1
    # pad if the plan under-delivered (failed fetches) so we still have a montage
    while len(media) < 4 and vi < len(videos):
        media.append({"path": f"media/{videos[vi].name}", "is_photo": False, "start": 2})
        vi += 1
    if len(media) < 2:
        raise RuntimeError(f"news mode: only {len(media)} usable visuals — aborting")

    # 4. montage
    final = build_montage(out_dir, "voice.mp3", "voice.vtt", media, "final.mp4",
                          config, music_abs=str(_MUSIC) if _MUSIC.exists() else None)

    # 5. demonetization check (informational — never blocks)
    try:
        from analysis.demonetization import assess_demonetization, format_report
        res = assess_demonetization(script["narration"], title=script["title"],
                                    early_text=script["narration"][:120])
        log.info(format_report(res, "news"))
    except Exception as exc:
        log.warning("[news] demonetization check skipped: %s", exc)

    # 6. scheduled upload (peak slot)
    if getattr(config, "upload_enabled", False):
        from upload.youtube import upload_video
        pub = next_publish_slot()
        vid = upload_video(final, title=script["title"], description=script["description"],
                           tags=script["tags"], publish_at=pub, category_id="17", language="en")
        if vid:
            log.info("[news] uploaded %s — scheduled public at %s", vid, pub)
            (out_dir / "upload.json").write_text(
                json.dumps({"video_id": vid, "publish_at": pub, "title": script["title"]},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            log.error("[news] upload failed")
    else:
        log.info("[news] render complete (no --upload). Preview: %s", final)

    return final
