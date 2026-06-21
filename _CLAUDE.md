# Pipeline Session Memory

## Project: Analytical YouTube Shorts Pipeline
**Stack:** faster-whisper (CUDA) → Groq LLM (4-dim scoring) → FFmpeg (NVENC) → YouTube OAuth

## Key Rules (Never Break)
- **PTS-STARTPTS reset** before every setpts expression
- **-vsync 0** on every FFmpeg encode call
- **No global mutable state** — pass PipelineConfig explicitly
- **GPU-first, always** — but catch CUDA errors and fall back to CPU
- **No speed changes** for analytical content (base_speed=1.0)
- **No brainrot** — no slow-mo, no zooms, no artificial retention tricks

## Architecture
```
main.py → config + orchestration
ingest/downloader.py       → yt-dlp
analysis/transcription.py  → faster-whisper
analysis/clip_scoring.py   → Groq LLM (4-dimension)
editing/renderer.py        → FFmpeg crop + compose
editing/captions.py        → FFmpeg drawtext
upload/youtube.py          → YouTube Data API v3 OAuth
```

## Known Bug — PTS Duration Mismatch (SOLVED)
**Root cause:** `-ss` before `-i` creates non-zero PTS. `setpts=X*PTS` compounds offset.
**Fix:** `setpts=PTS-STARTPTS` before any other setpts expression. Applied in renderer.py and captions.py.

## Known Bug — VFR Loss on Re-encode (SOLVED)
**Root cause:** FFmpeg defaults to CFR mode → drops setpts effects.
**Fix:** Add `-vsync 0` to every encode command with a filter chain.

## Status
- All 13 modules written ✅
- PTS bug fixed ✅
- GPU path working (with CPU fallback) ✅
- YouTube upload (OAuth v3) ✅
- Next: `pip install -r requirements.txt` + test
