# ALWAYS.md — Loaded at every prompt
## Project: Analytical YouTube Shorts Pipeline
**Stack:** Whisper GPU → Groq LLM → FFmpeg NVENC → YouTube OAuth

## Rules
- PTS-STARTPTS before every setpts
- -vsync 0 on every encode
- No global state — pass PipelineConfig explicitly
- No brainrot (no speed changes, no zooms, no effects)
- GPU-first, CPU fallback
- **content_type="general"** by default, **"football"** for match highlights only

## Architecture
```
main.py → download → whisper → topic detection → LLM scoring → crop → captions → compose → upload
```

## HARD PRODUCTION CONSTRAINTS (NEVER NEGOTIATE)

### 1. FORMAT
- Output must be 9:16 (1080x1920)
- No black bars allowed
- No letterboxing or pillarboxing

### 2. FRAMING
- Main subject must always be visible
- No cutting off heads, ball, or action
- Subject must occupy 40–80% of frame

### 3. TIMING
- Clip length: 12–35 seconds
- First 1.5 seconds must contain main action (hook moment)
- No dead time allowed

### 4. EDITING RULE
- Must maintain high visual change frequency (max 2s per visual state)
- No static long frames

### 5. FAILURE CONDITIONS
Reject output if:
- subject is cropped incorrectly
- action is outside frame
- video has black bars
- pacing is too slow

## CONTENT STRATEGIST MODE (hook & title only — no editing, no rendering)

When asked for content strategy, follow these rules:

- Hook must be based on a real moment in the clip
- Must be 1 short sentence
- Must increase curiosity or tension
- No generic phrases allowed

Strategy output format:
- **Hook idea**: (1 sentence, based on actual clip content)
- **Key moment**: (timestamp + what happens)
- **Emotional angle**: (why viewer should care)
- **Title suggestion**: (Short-form friendly)
