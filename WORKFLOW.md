# YouTube Shorts Pipeline — Technical Workflow

> Links: [[kulturel AI agent]] · [[Key Decisions]] · [[SESSION]]

## Pipeline Architecture

### Phase 1 (fully automated)

```
YouTube URL
    ↓ [ingest/downloader.py]
yt-dlp (bestvideo+bestaudio, MP4 merge)
    ↓ [analysis/transcription.py]
faster-whisper (GPU CUDA float16, word-level timestamps)
    ↓ [analysis/topic_detection.py]
Topic extraction (keywords + named entities)
    ↓ [analysis/clip_scoring.py]
Groq LLaMA 3.3 70B — 4-dimension scoring:
  • curiosity (0-10)
  • emotional_relevance (0-10)
  • educational_value (0-10)
  • narrative_completeness (0-10)
    ↓ Sort by total score → pick top 3-5
    ↓ [editing/renderer.py]
FFmpeg crop (9:16, 1080x1920, PTS-STARTPTS reset)
    ↓
shorts_output/<timestamp>/clip_N/{clip.mp4, clip_metadata.json, hook_text.txt, intro_script.txt}
```

### Phase 2 (captions + composition)

```
clip.mp4
    ↓ [analysis/transcription.py]
faster-whisper (word-level for caption timing)
    ↓ [editing/captions.py]
FFmpeg drawtext — word-level captions (PTS-STARTPTS + -vsync 0)
    ↓ [editing/renderer.py]
FFmpeg composition — hook overlay + subscribe overlay + audio mix
    ↓
final.mp4
    ↓ [upload/youtube.py]
YouTube Data API v3 OAuth upload
```

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| PTS-STARTPTS reset | Prevents duration mismatch when -ss creates non-zero PTS start |
| -vsync 0 on all encodes | Preserves VFR from filter chain |
| Immutable PipelineConfig | No global state — each module is independently testable |
| 4-dimension LLM scoring | Objective clip selection criteria, not just "viral potential" |
| GPU-first with CPU fallback | Graceful degradation on CUDA errors |

## Critical Bug Prevention

### PTS Timestamp Safety

Bad (old code):
```python
vf_filter = f"setpts={speed}*PTS,crop=..."
```
Input with non-zero PTS (from `-ss` before `-i`) → duration compounds.

Good (new code):
```python
vf = "setpts=PTS-STARTPTS,crop=...,setsar=1"
```
Always reset before any speed expression.

### GPU Fallback

Every module that uses CUDA catches RuntimeError for cublas/cuda errors
and retries on CPU. No single GPU failure kills the pipeline.

## File Overview

| File | Lines | Responsibility |
|------|-------|----------------|
| `main.py` | ~200 | Orchestrator, CLI parsing |
| `core/config.py` | ~210 | Immutable config builder |
| `core/logger.py` | ~50 | Structured logging |
| `ingest/downloader.py` | ~65 | yt-dlp wrapper |
| `analysis/transcription.py` | ~110 | Whisper GPU/CPU |
| `analysis/topic_detection.py` | ~60 | Keyword extraction |
| `analysis/clip_scoring.py` | ~170 | LLM scoring |
| `editing/captions.py` | ~150 | Word-level captions |
| `editing/renderer.py` | ~240 | Crop + compose + audio |
| `editing/effects.py` | ~25 | Placeholder |
| `formats/format_loader.py` | ~20 | JSON loader |
| `upload/youtube.py` | ~140 | OAuth upload |
