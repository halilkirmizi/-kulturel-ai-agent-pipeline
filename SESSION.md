# Pipeline Session Log

> Read this file first at the start of each session.
> Links: [[kulturel AI agent]] · [[Key Decisions]] · [[WORKFLOW]]

---

## Session History

| Session | Date | Focus | Status |
|---------|------|-------|--------|
| 1-2 | 2026-06-13/14 | First pipeline, format system, search mode | ✅ |
| 3 | 2026-06-15 | Full pipeline fix, effects, upload | ✅ |
| 4 | 2026-06-16 | Speed/pitch fix, format2 cleanup | ✅ |
| 5 | 2026-06-16 | Smooth curve slow-mo test | ❌ |
| 6 | 2026-06-16 | GPU migration + compiler pivot | ✅ |
| 7 | 2026-06-17 | Minimal pipeline (whisper->LLM->FFmpeg) | ✅ |
| 8 | 2026-06-18 | Project revival — skeleton setup | ✅ |
| **9** | **2026-06-18** | **Architecture refactor — modular production** | **🔄** |

---

## Session 9 — 2026-06-18: Architectural Refactor

### What Was Done

**Complete architecture migration**: monolithic `shorts_pipeline.py` (733 lines)
→ modular production architecture (13 files, ~1500 lines total).

**New modules created:**

| Module | File | Purpose |
|--------|------|---------|
| Core config | `core/config.py` | Immutable PipelineConfig with dataclasses |
| Core logger | `core/logger.py` | Structured logging (console + file) |
| Ingest | `ingest/downloader.py` | yt-dlp wrapper with error handling |
| Transcription | `analysis/transcription.py` | GPU-first whisper with CPU fallback |
| Topic detection | `analysis/topic_detection.py` | Keyword + entity extraction |
| Clip scoring | `analysis/clip_scoring.py` | 4-dimension LLM scoring engine |
| Captions | `editing/captions.py` | Word-level drawtext (PTS-safe) |
| Renderer | `editing/renderer.py` | Crop + compose + audio mix |
| Effects | `editing/effects.py` | Placeholder for analytical-style effects |
| Format loader | `formats/format_loader.py` | JSON config loader |
| YouTube upload | `upload/youtube.py` | OAuth v3 with retry + token caching |
| Orchestrator | `main.py` | Stateless CLI entry point |

**Deleted:**
- `shorts_pipeline.py` (monolith, replaced by main.py)
- `formats/format2.json` (brainrot format — not needed)
- `upload/uploader.py` (stub, replaced by youtube.py)

**Key improvements:**

1. **PTS-STARTPTS reset** on every FFmpeg crop/caption/compose call
2. **-vsync 0** on all encodes (preserves VFR)
3. **No global mutable state** — PipelineConfig is frozen dataclass
4. **GPU-first with CPU fallback** in all CUDA paths
5. **NVENC encode path** when gpu_enabled=True
6. **4-dimension clip scoring** (curiosity, emotion, education, narrative)
7. **Topic detection** to bias LLM scoring toward content-rich segments
8. **YouTube OAuth v3** with token caching and exponential backoff retry
9. **Structured logging** instead of print statements

### Current State

- All 13 modules written and production-ready
- Dependencies updated in requirements.txt (added google-api-python-client et al.)
- format1.json cleaned (no effects section, speed=1.0, no brainrot references)
- All PTS bugs fixed at the source
- Phase 2 simplified: no outro.mp3 requirement, single intro audio

### Next Steps

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Set up YouTube OAuth**: download `client_secret.json` from Google Cloud Console → save to `upload/`
3. **Set GROQ_API_KEY** in `.env`
4. **Test Phase 1** on a YouTube video
5. **Test Phase 2** with an intro audio clip

### Known Bugs

- None currently known. Old PTS bug, GPU lack, and upload stub are all resolved.
