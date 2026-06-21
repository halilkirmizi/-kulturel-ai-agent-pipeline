# Pipeline Session Log

> Read this file first at the start of each session.
> Links: [[kulturel AI agent]] · [[Key Decisions]] · [[CLAUDE.md]] · [[CHANGELOG.md]]

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
| 9 | 2026-06-18 | Architecture refactor — modular production | ✅ |
| **10** | **2026-06-21** | **Git remote + dosya temizliği + session.md işlevi** | **🔄** |

---

## Session 10 — 2026-06-21: Git remote + File Cleanup + Session.md Contract

### What Was Done

**Artifact Ownership Registry** (`core/artifact_registry.py`): 17 artifact types, single-writer enforcement, validate(), print_report(), save()/load() via `.artifact_registry.json`, freeze()

**External Artifact Auditor** (`core/artifact_auditor.py`): 3 modes (bootstrap/drift/verify), ghost/missing/duplicate_writer/shadow detection, severity classification

**Memory Write-Back System** (`core/memory_writer.py`): MemoryCandidate (+semantic_class), MemoryStore (bounded 50/cat, 30d compaction, behavior_hints()), CompressionLayer (class-aware dedup), SemanticSignalFilter, LearningLoopGate, MemoryWriter

**Semantic Memory Filter Layer**: `SemanticSignalFilter.classify_signal()` returns PROMOTE/REJECT/DOWNGRADE; non-semantic path patterns blocked; structural/invariant signals PROMOTE

**Memory Feedback Loop** (`core/memory_influence.py`): MemoryInfluenceEngine, RuntimeConfigPatch, threshold/scoring/routing hints, enforce_guards()

**ControlArbiter** (`core/control_arbiter.py`): 5-layer priority resolution, UnifiedRuntimeConfig, ResolvedValue (provenance), print_trace()

**StepTracker** (`core/steptracker.py`): heuristic_adjustments(), apply_influence() dict support, get_adjusted_threshold()

**Fixes:**
- StepTracker UUID isolation: `execution_trace.json` → `execution_trace_<uuid>.json` (per-run, no shared lock)
- Downloader identity fix: removed glob+mtime file selection; uses `info["id"]` from yt-dlp for deterministic output path
- Hook config bug fix: HookConfig was reading from `cap_raw` (captions) instead of `hook_overlay`
- Subscribe overlay config extended: added `fontcolor`, `bordercolor`, `borderw` fields

**Format:**
- Created `format_football_interview.json` (hook 120px/5sn, subscribe red/120px/black outline, intro_duck_volume=0.0, noise_reduction disabled)
- format1.json audio EQ cleaned (200Hz/-2dB + 3000Hz/+3dB)

**Pipeline verified end-to-end**: Real video download → transcribe (222 segments, 96.7% es) → score (3 clips) → crop → Phase 2 compose → final.mp4 (no captions) → first YouTube upload (Arjantin WC interview, "Eternal Number 10")

**Cross-run contamination test**: 3 consecutive runs with same failure → NONE detected (gate, memory, AOR all clean)

**Adaptive mode test**: Ran `--mode adaptive_mode --trace-arbiter` — arbitration chain works but memory_store empty → all values default/zero

**Cleanup**: temp/ (125 files, 1.68 GB → 0), old run dirs (16 → 1 kept), execution_trace files (10 → 0), logs (107 → 0), memory_store reset to empty

**Git & Repo Setup:**
- Created `.gitignore` (temp/, logs/, downloads/, shorts_output/, memory_store.json, .env, client_secret.json, *.pickle, .Rhistory)
- Created `CHANGELOG.md` (Dory format — append-only, one line per decision)
- Created `CLAUDE.md` (30-line rule file — architecture, priority, rules, sensitive files)
- Initialized separate git repo in pipeline/ directory (NOT vault root)
- Added remote: `halilkirmizi/-kulturel-ai-agent-pipeline.git`
- Initial commit: 48 files, 8523 lines
- Pushed to `main` branch

### Key Decisions

1. **SESSION.md = conversation history backup.** Three-file system: CHANGELOG.md (what changed), SESSION.md (decisions + context), CLAUDE.md (rules). SESSION.md updated at end of each session, read at start of next.
2. Memory promotion requires ≥1 artifact reference (except source=artifact_registry)
3. Compression keys on `signature|semantic_class` — lifecycle_noise NEVER merges into semantic
4. Semantic filter uses path patterns not AOR lifecycle — `temp/` prefix → lifecycle_noise
5. AOR persistence uses atomic `.tmp.json` + rename
6. ControlArbiter priority: DAG/Contract (1) > AOR (2) > MemoryInfluence (3) > StepTracker (4) > ClipScoring (5)
7. Priority order for runtime config: DAG/Contract (1) > AOR (2) > MemoryInfluence (3) > StepTracker (4) > ClipScoring (5)
8. All runtime config must pass through ControlArbiter — no direct patch application
9. `--mode observation_only` (default): no memory influence; `adaptive_mode`: memory influences execution
10. Downloader path resolved via `info["id"]` from yt-dlp — no glob, no mtime
11. Hook config fields read from `hook_overlay` JSON section, not `captions`
12. Subscribe overlay uses config-driven fontcolor/bordercolor/borderw
13. `--no-captions` is CLI-only flag, does not persist in any config
14. User records own intro audio separately (no unsolicited microphone recording)
15. `obsidian_bridge/` kept — user wants to use it later

### Next Steps

1. Run new video through full pipeline to generate real memory_store entries
2. Exercise adaptive mode with populated memory_store
3. Use obsidian_bridge when user asks for it

### Known Bugs / Issues

- LSP errors in downloader.py (yt-dlp type stub mismatch) and clip_scoring.py (Optional str → str) are pre-existing
- Windows `tempfile.mkstemp` PermissionError known quirk — real pipeline paths (shorts_output/) unaffected
- ASS captions still use Arial font (hardcoded)
