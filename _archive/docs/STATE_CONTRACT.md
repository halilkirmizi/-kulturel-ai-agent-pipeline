# Pipeline State Contract v1

## 1. state.json — Schema

```json
{
  "version": 1,
  "state": "immutable",
  "generated_at": "2026-06-18T21:50:42",
  "source_url": "https://youtube.com/watch?v=XXX",

  "clip": {
    "start": 192.58,
    "end": 217.12,
    "duration": 24.54
  },

  "scoring": {
    "hook_text": "Airport Bound",
    "intro_script": "Heading to the airport, what's next?",
    "outro_script": "The journey begins with a seat",
    "reason": "Clear story arc",
    "scores": {
      "curiosity": 7.0,
      "emotional_relevance": 5.0,
      "educational_value": 4.0,
      "narrative_completeness": 8.0
    },
    "score_total": 24.0
  },

  "transcript": [
    {"start": 0.00, "end": 2.34, "text": "Heading to the airport"},
    {"start": 2.35, "end": 5.10, "text": "what's next for the team?"}
  ]
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `version` | YES | Must be `1`. |
| `state` | YES | `"immutable"`. Phase 2 rejects anything else. |
| `generated_at` | YES | ISO 8601. Phase 1 write time. |
| `clip.start`, `end`, `duration` | YES | Absolute seconds in source video. |
| `scoring.*` | YES | All fields from ScoredClip. |
| `transcript` | YES | Array of `{start, end, text}`. **Non-empty.** Timestamps relative to clip start (0.0 = clip beginning). |

**Immutability:** Written once by Phase 1. Never modified. Phase 2 opens read-only. Translation is in-memory only.

---

## 2. Phase 2 — Whitelist / Blacklist

| Allowed | Source |
|---------|--------|
| `state.json` | `clip_dir / state.json` — read-only, must pass validation |
| `clip.mp4` | `clip_dir / clip.mp4` |
| Intro audio | `clip_dir / intro.*` or `--intro` path |
| `PipelineConfig` | CLI args + format JSON |

| Forbidden | Reason |
|-----------|--------|
| Whisper/faster-whisper | No re-transcription under any condition |
| Any speech-to-text | No alternative STT model either |
| Obsidian vault access | Execution must not read strategic memory |
| Writing to `state.json` | Immutable by contract |
| All other inputs | Not in whitelist = forbidden |

**Failure mode:** Validation fail → `PipelineError`, stop. No fallback. No "best effort". No default transcript.

---

## 3. Subtitle System

```
state.json.transcript  →  captions.py  →  .ass  →  FFmpeg subtitles=
```

- Exactly one `.ass` file per clip.
- Exactly one `subtitles=` filter per clip.
- `compose_final()` uses `drawtext` only for hook overlay + subscribe button. Never word-level captions.
- Translation: in-memory only. Never written to disk.

---

## 4. Enforcement Layer

### 4.1 Validator Gate — `core/state.py`

```
read_state(path) -> dict     6-step validation, raises PipelineError on fail
write_state(path, data)      Atomic write, sets state="immutable" + generated_at
```

Called at Phase 2 entry, before any other operation.

### 4.2 Validation Checks

```
01  FileExists    → "state.json not found"
02  .version == 1 → "state.json version mismatch"
03  .state == "immutable" → "state.json not immutable"
04  type(.transcript) is list → "transcript must be array"
05  len(.transcript) > 0 → "transcript is empty"
06  all fields present → "transcript[{i}] missing field '{f}'"
```

### 4.3 Sequential FFmpeg Passes

Pass 1 — `captions.py`: `subtitles=` filter only. Input: `clip.mp4`. Output: `captioned.mp4`.
Pass 2 — `renderer.py` `compose_final()`: `drawtext` (hook) + `drawtext` (subscribe) + `amix`. Input: `captioned.mp4` + `intro.mp3`. Output: `final.mp4`.

| File | Owns | NEVER |
|------|------|-------|
| `captions.py` | Word-level captions → `.ass` → `subtitles=` | `drawtext=`, hook, subscribe, audio |
| `renderer.py` | Hook `drawtext`, subscribe `drawtext`, `amix` (audio) | `subtitles=`, `.ass`, word-level captions |

**Linked by filesystem, NOT by filter_complex.** A single FFmpeg invocation with both `subtitles=` and `drawtext=` is a system failure.

### 4.4 State Transition

1. Phase 1: download → transcribe (ONLY Whisper call) → score clips → for each clip: crop + `write_state()` (atomic, immutable).
2. Phase 2 entry: `read_state()` — 6 checks. Any fail → hard stop.
3. Load transcript in memory (optionally translate).
4. Pass 1: `captions.py` → `captioned.mp4`.
5. Pass 2: `compose_final()` → `final.mp4`.
