# Safe Execution Sequence — Pipeline Refactor

## EXECUTION OWNERSHIP CONTRACT (validated before Step 1)

```
subprocess.run / Popen / os.system / FFmpeg CLI call
                │
     ┌──────────┴──────────┐
     │  ffmpeg_builder.py  │ ← ONLY MODULE allowed
     │  execute(cmd)       │ ← SINGLE execution function
     └─────────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
 main.py    render_core   audio.py
 (calls     (returns      (returns
  execute)   cmd specs)    cmd specs)
    │
    ▼
 captions   overlays.py   state.py
 (ASS only) (strings     (declarative
            only)         only)
```

### Hard Rules

| Module | Allowed | Forbidden |
|--------|---------|-----------|
| `ffmpeg_builder.py` | `subprocess.run()`, FFmpeg CLI calls, `probe_duration()`, `execute(cmd)` | Nothing — this is the execution layer |
| `main.py` | Import modules, call `state.read_state()`, call `ffmpeg_builder.execute(cmd)`, orchestrate phase flow | `subprocess.run()`, `os.system()`, any FFmpeg/CLI call, `Popen()` |
| `captions.py` | Segment → ASS file. `write_ass()`, `translate_segments()`. Pure string/ASS processing. | `subprocess`, FFmpeg, `_ffmpeg()`, `_get_duration()` via ffprobe |
| `render_core.py` | Build command specs for composition. Call `overlays.*`, `audio.*`, `ffmpeg_builder.probe_duration()`. Return structured cmd list. | `subprocess`, `execute()`, any execution |
| `audio.py` | `build_enhance_command()` returns cmd list. `build_audio_mix()` returns filter strings. | `subprocess`, FFmpeg execution |
| `overlays.py` | `build_hook_overlay()` returns drawtext string. `build_subscribe_overlay()` returns drawtext string. `esc()` returns escaped string. | `subprocess`, FFmpeg, any execution |
| `state.py` | Read/write JSON. Validation checks. | Import from editing/, any execution |

### Architecture Rule

- All modules EXCEPT `ffmpeg_builder` return ONLY: command lists (`List[str]`) or filter strings
- `ffmpeg_builder` is the SINGLE execution gateway with exactly ONE entry point:
  - `execute(cmd: List[str])` — the ONLY function that calls `subprocess.run()`

### State Guarantee

- `state.py` imports NOTHING from `editing/`, `analysis/`, `ingest/`, `upload/`
- `state.json` is declarative-only: version, state flag, metadata, transcript
- No execution context, no runtime state, no cache

---

## Safe Migration Order (8 steps)

---

### STEP 1 — Create `ffmpeg_builder.py`
**Risk: LOW.** New file, zero existing code changed.

| Action | Detail |
|--------|--------|
| CREATE | `editing/ffmpeg_builder.py` |
| Contents | `ffmpeg_path()`, `probe_duration()`, `run_ffmpeg()`, `nvenc_available()`, `gpu_encode_args()`, `execute_subtitles()`, `execute_audio()`, `execute_compose()`, `build_subtitle_command()`, `build_enhance_command()` |
| NOT changed | `renderer.py`, `captions.py`, `main.py`, any other file |

**Why this order:** Zero dependencies. No module needs to change. File can be imported and tested in isolation.

**Contract validation:** Grep `subprocess.run` across entire `editing/` — only `ffmpeg_builder.py` contains it.

**Verification:** `import ffmpeg_builder; ffmpeg_builder.probe_duration("test.mp4")` works.

**Rollback:** Delete file.

---

### STEP 2 — Create `overlays.py`
**Risk: LOW.** New file, zero dependencies, zero existing code changed.

| Action | Detail |
|--------|--------|
| CREATE | `editing/overlays.py` |
| Contents | `esc(text)`, `build_hook_overlay(hook_text, config, clip_dur)` returns drawtext string, `build_subscribe_overlay(config, clip_dur)` returns drawtext string |
| NOT changed | Any existing file |

**Contract validation:** `overlays.py` has zero imports from editing/. No subprocess. Pure string functions.

**Rollback:** Delete file.

---

### STEP 3 — Create `audio.py`
**Risk: LOW.** New file, imports only `ffmpeg_builder` for utilities.

| Action | Detail |
|--------|--------|
| CREATE | `editing/audio.py` |
| Contents | `build_enhance_command(input_path, output_path, config)` returns cmd list. `build_audio_mix(intro_dur, clip_dur, config)` returns (ambient_expr, intro_expr, filter_part). |
| Import | `from editing.ffmpeg_builder import ffmpeg_path, probe_duration` |
| NOT changed | Any existing file |

**Contract validation:** `audio.py` has NO `subprocess.run()`. Returns cmd lists only. Doesn't call `run_ffmpeg()`.

**Rollback:** Delete file.

---

### STEP 4 — Create `render_core.py`
**Risk: LOW.** New file, imports other new modules only.

| Action | Detail |
|--------|--------|
| CREATE | `editing/render_core.py` |
| Contents | `build_compose_command(clip_captioned, intro_audio, output_path, hook_text, config)` returns cmd list. `crop_clip(video_path, start, end, output_path, config)` returns cmd list. |
| Import | `overlays`, `audio`, `ffmpeg_builder` (probe_duration, gpu_encode_args, ffmpeg_path only) |
| NOT changed | `renderer.py`, `captions.py`, `main.py` |

**Contract validation:** `render_core.py` has NO `subprocess.run()`. NO `run_ffmpeg()` call. Returns cmd lists only.

**Verification:** `render_core.build_compose_command(...)` returns `["ffmpeg", "-y", "-i", ...]`.

**Rollback:** Delete file.

---

### STEP 5 — Cutover: update `main.py` + delete `renderer.py`
**Risk: MEDIUM.** System switches from old renderer to new modules.

| Action | Detail |
|--------|--------|
| MODIFY | `main.py` `_run_phase1()`: Change `from editing.renderer import crop_clip` → `from editing.render_core import build_crop_command`. Replace `crop_clip(...)` with `cmd = build_crop_command(...); ffmpeg_builder.execute(cmd)` |
| MODIFY | `main.py` `_run_phase2()`: Change `from editing.renderer import compose_final, enhance_audio` → new imports. Replace `enhance_audio(...)` with `cmd = audio.build_enhance_command(...); ffmpeg_builder.execute(cmd)`. Replace `compose_final(...)` with `cmd = render_core.build_compose_command(...); ffmpeg_builder.execute(cmd)` |
| DELETE | `editing/renderer.py` — all functionality migrated |
| KEEP | `captions.py` unchanged (still has its own `_ffmpeg`/`_get_duration` — will be cleaned in Step 6) |

**Contract validation after step:**
- Grep `subprocess.run` across `main.py` → 0 matches
- Grep `subprocess.run` across `editing/` → ONLY in `ffmpeg_builder.py`
- Grep `run_ffmpeg(` across `editing/` → ONLY in `ffmpeg_builder.py` (the definition)
- `main.py` calls `ffmpeg_builder.execute_*()` — allowed, this is the gateway API

**Runnable condition:** `python main.py --resume short_X/clip_1` produces identical `final.mp4`.

**Verification:** Side-by-side compare final.mp4 with pre-refactor run (Phase 2 only).

**Rollback:** Restore `renderer.py` from git. Revert `main.py` imports. Delete `render_core.py`, `audio.py`, `overlays.py` if needed.

---

### STEP 6 — Clean `captions.py` + move subtitle command to `ffmpeg_builder`
**Risk: MEDIUM.** Changes captions.py API.

| Action | Detail |
|--------|--------|
| MODIFY | `editing/captions.py`: |
| REMOVE | `_ffmpeg()` function |
| REMOVE | `_get_duration()` function |
| REMOVE | `phase1_has_subtitles` parameter |
| REMOVE | FFmpeg execution block (old lines 88-130 — the `subprocess.run()` + fallback logic) |
| CHANGE | `add_captions(video_path, segments, output_path, start_offset, config, phase1_has_subtitles)` → `write_ass(segments, ass_path, clip_duration, start_offset, config)` |
| ADD | `write_ass()` calls `_write_ass()`, returns `ass_path` |
| KEEP | `_chunk_text()`, `_to_ass_time()`, `_write_ass()` — pure ASS functions, unchanged |
| UPDATE | `ffmpeg_builder.build_subtitle_command(video_path, ass_path, output_path, config)` — moved FFmpeg logic from old captions.py lines 102-130. Returns cmd list. |
| MODIFY | `main.py` `_run_phase2()`: Replace `add_captions(clip_path, segments, captioned, ...)` with: `clip_dur = ffmpeg_builder.probe_duration(clip_path); ass_path = captions.write_ass(segments, ass_file, clip_dur, 0, config); cmd = ffmpeg_builder.build_subtitle_command(clip_path, ass_path, captioned_path, config); ffmpeg_builder.execute(cmd)` |
| DELETE | `captions.ass` file from clip_dir after Phase 2? No — keep for debugging, but never read again |

**Contract validation:**
- `captions.py` has ZERO `subprocess` imports
- `captions.py` has ZERO `ffmpeg` references
- `captions.py` imports NOTHING from `editing/` 
- `ffmpeg_builder.build_subtitle_command()` returns cmd list (does NOT execute)
- `ffmpeg_builder.execute_subtitles(cmd)` is the only execution path

**Runnable condition:** `python main.py --resume short_X/clip_1` produces identical `final.mp4` with captions.

**Verification:** Compare ASS file content with pre-refactor. Compare final.mp4.

**Rollback:** Restore `captions.py` from git. Remove `build_subtitle_command()` from `ffmpeg_builder`. Revert `main.py`.

---

### STEP 7 — Slim `main.py`: move `_translate_segments`
**Risk: LOW.** Pure function move.

| Action | Detail |
|--------|--------|
| MOVE | `_translate_segments(segments, config)` from `main.py` → `captions.translate_segments(segments, config)` |
| MODIFY | `main.py` `_run_phase2()`: `from editing.captions import translate_segments`. Replace inline call. |
| NOT changed | ffmpeg_builder, render_core, audio, overlays, state |

**Contract validation:** `captions.translate_segments()` returns translated segment list (in-memory). No disk I/O, no execution.

**Rollback:** Move function back to main.py.

---

### STEP 8 — Create `core/state.py` + validator gate
**Risk: LOW.** New module, no execution dependency.

| Action | Detail |
|--------|--------|
| CREATE | `core/state.py`: `write_state(path, data)` — atomic write, sets `state="immutable"`, `generated_at`. `read_state(path)` — 6-step validation (exists, version==1, state=="immutable", transcript is list, non-empty, fields complete). Returns dict or raises `StateError`. |
| IMPORT | `state.py` imports: `json`, `os`, `Path`, `datetime`. ZERO imports from `editing/`, `analysis/`, `ingest/`, `upload/`. |
| MODIFY | `main.py` `_run_phase1()`: After crop + build state dict → `state.write_state(out_dir / "state.json", state_dict)` instead of writing `clip_metadata.json` |
| MODIFY | `main.py` `_run_phase2()`: First line → `state_data = state.read_state(clip_dir / "state.json")`. Load transcript from `state_data["transcript"]`. |
| MODIFY | `main.py` `_do_upload()`: Read title/desc from `state.json` instead of `clip_metadata.json` |
| KEEP | `clip_metadata.json` backward compat? No — remove writes. Old clips without state.json will fail validation (correct behavior per contract). |

**StateError** — custom exception in `state.py`, extends `Exception`. Caught by `main.py` top-level handler.

**Contract validation:**
- `state.py` has ZERO imports from `editing/`, `analysis/`, `ingest/`, `upload/`
- `state.py` has ZERO `subprocess`/FFmpeg calls
- `state.json` on disk contains NO execution context (no temp paths, no runtime flags)

**Runnable condition:** Full pipeline: `python main.py https://youtube.com/...` — writes `state.json`. `python main.py --resume short_X/clip_1` — reads `state.json`, validates, executes Phase 2.

**Rollback:** Delete `core/state.py`. Revert `main.py` write/read calls. Restore `clip_metadata.json` writing.

---

## Guard Rails (validated at every step)

| Check | Method | After which steps |
|-------|--------|-------------------|
| `subprocess.run()` only in `ffmpeg_builder.py` | Grep `subprocess\.(run\|Popen\|call)` across `editing/`, `main.py`, `core/` | Steps 5, 6, 7, 8 |
| `run_ffmpeg()` only called from main.py | Grep `run_ffmpeg(` across `editing/` — should only be definition + internal calls in ffmpeg_builder.py | Steps 5, 6 |
| `captions.py` has no FFmpeg/subprocess | Grep `subprocess\|ffmpeg\|_ffmpeg` in captions.py | Step 6 |
| `render_core.py` has no subprocess | Grep `subprocess\|run_ffmpeg` in render_core.py | Step 5 |
| `state.py` has no editing/ imports | Grep `from editing\|import editing` in state.py | Step 8 |
| No circular imports | Manual dep graph check: main → all. captions → nothing. overlays → nothing. audio → ffmpeg_builder only. render_core → overlays, audio, ffmpeg_builder. state → nothing. | All steps |

## Rollback Master Plan

| Scenario | Action |
|----------|--------|
| Step 1-4 breaks | Just delete the new file(s). System is identical to pre-step state. |
| Step 5 breaks (Phase 2 wrong output) | `git checkout -- editing/renderer.py main.py`. Delete `render_core.py`, `audio.py`, `overlays.py`. |
| Step 6 breaks (captions missing/wrong) | `git checkout -- editing/captions.py main.py editing/ffmpeg_builder.py`. |
| Step 7 breaks (translation fails) | `git checkout -- main.py editing/captions.py`. |
| Step 8 breaks (state validation fails on old clips) | `git checkout -- core/state.py main.py`. |

**Important:** `state.json`, `transcript`, `clip.mp4`, `temp/`, `shorts_output/` are NEVER touched by rollback. These are runtime artifacts, not code.
