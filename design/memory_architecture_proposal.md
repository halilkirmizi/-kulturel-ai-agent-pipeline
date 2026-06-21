# Memory Architecture Proposal

> **Purpose:** Evaluate whether the current Claude context management system should be restructured into a modular, layered memory architecture.
> **Audience:** Software engineer unfamiliar with the project.
> **Status:** Draft — not implemented.

---

## 1. Project Overview (What Are We Building?)

A **YouTube Shorts production pipeline** — given a YouTube URL, it:

1. Downloads the video
2. Transcribes audio (Whisper GPU)
3. Scores clips via LLM (Groq)
4. Crops to 9:16 (vertical Shorts format)
5. Adds captions + overlays (hook text, subscribe button)
6. Composes final video with audio enhancements
7. Optionally uploads to YouTube

**Tech stack:** Python, yt-dlp, Whisper, FFmpeg, Groq LLM, YouTube API v3

**Key design decisions already in place:**
- `state.json` is the single source of truth for pipeline state
- `ffmpeg_builder.py` is the only module allowed to call subprocess
- Artifact Ownership Registry (AOR) enforces single-writer rules at runtime
- ControlArbiter resolves conflicts across 5 influence layers (DAG/Contract > AOR > MemoryInfluence > StepTracker > ClipScoring)
- Memory write-back system (`memory_writer.py`, `memory_influence.py`) stores execution signals in `memory_store.json` for adaptive behavior

```
Pipeline directory structure:
pipeline/
├── main.py                 # Entry point
├── core/                   # Core infrastructure
│   ├── artifact_registry.py
│   ├── artifact_auditor.py
│   ├── config.py
│   ├── contract_validator.py
│   ├── control_arbiter.py
│   ├── memory_writer.py
│   ├── memory_influence.py
│   ├── steptracker.py
│   ├── state.py
│   └── logger.py
├── ingest/
│   └── downloader.py
├── analysis/
│   ├── transcription.py
│   ├── clip_scoring.py
│   ├── topic_detection.py
│   └── translation.py
├── editing/
│   ├── ffmpeg_builder.py
│   ├── captions.py
│   ├── overlays.py
│   ├── audio.py
│   └── render_core.py
├── formats/
│   ├── format1.json
│   └── format_football_interview.json
├── upload/
│   └── youtube.py
└── obsidian_bridge/
    ├── build_graph.py
    └── graph_query.py
```

---

## 2. The Real Problem: Claude Context Management

The pipeline code runs on a local machine. **The AI agent (Claude) assists the developer** by reading/writing code, running tests, and discussing design decisions. Each conversation with Claude is a **session**.

**The problem Claude faces:** When a new session starts, Claude has zero memory of:
- What was built in previous sessions
- What decisions were made
- What the current state of the project is
- What rules and constraints apply

Without a context system, every session starts from scratch — the developer must re-explain everything.

### 2.1 Current Solution (Implemented This Session)

Three files at the pipeline root serve as Claude's context:

| File | Lines | Purpose | When Read |
|------|-------|---------|-----------|
| `CLAUDE.md` | 26 | Architecture rules, priorities, sensitive files | Every prompt |
| `SESSION.md` | ~100 | Session history, current state, key decisions, next steps | Every session start |
| `CHANGELOG.md` | 11 | One-line-per-decision changelog (append-only) | On demand |

**How it works:**
1. Developer says "start working"
2. Claude reads `SESSION.md` → understands current state
3. `CLAUDE.md` is injected automatically by the tool
4. Developer and Claude work through the session
5. At session end, Claude updates `SESSION.md` with new decisions + state
6. Developer commits to git

**Strengths:**
- Simple — only 3 files
- Easy to maintain
- Git-tracked (history preserved)

**Weaknesses:**
- `SESSION.md` is monolithic — session history, current state, decisions, everything in one file
- No layering — all context loaded at once regardless of relevance
- No short-term vs long-term distinction
- No retrieval gating (you can't say "only load decisions, skip history")

---

## 3. Proposed Change: Layered Memory Architecture

Replace the 3-file system with a modular memory hierarchy inspired by human memory models (short-term → working → long-term).

### 3.1 Architecture

```
Context loading at session start:
┌─────────────────────────────────────────────────┐
│  STEP 1: Load SHORT-TERM memory (every prompt)  │
│  ├── ALWAYS.md (rules, constraints)             │
│  └── CLAUDE.md (architecture, priority)          │
├─────────────────────────────────────────────────┤
│  STEP 2: Load WORKING memory (current task)      │
│  ├── PROJECT.md (current goal, next steps)       │
│  └── CHANGELOG.md (recent changes)               │
├─────────────────────────────────────────────────┤
│  STEP 3: Load LONG-TERM memory (on demand only)  │
│  ├── ARCHIVE/INDEX.md (session history index)    │
│  ├── ARCHIVE/SESSION_XX.md (full session logs)   │
│  └── KEY_DECISIONS.md (all decisions registry)   │
└─────────────────────────────────────────────────┘
```

### 3.2 File Breakdown

#### Short-term (loaded every prompt — ~50-70 lines total)
| File | Contents | Size Target |
|------|----------|-------------|
| `ALWAYS.md` | Production constraints (9:16, framing, timing, content strategy rules) | ~40 lines |
| `CLAUDE.md` | Architecture rules, priority order, sensitive files (keep as-is) | ~25 lines |

#### Working memory (loaded at session start — ~30-50 lines total)
| File | Contents | Size Target |
|------|----------|-------------|
| `PROJECT.md` | One-paragraph current goal, 3-5 next steps, current blockers | ~15 lines |
| `CHANGELOG.md` | Append-only, one line per change (keep as-is) | grows slowly |

#### Long-term (loaded only when specifically referenced — grows unbounded)
| File | Contents |
|------|----------|
| `ARCHIVE/INDEX.md` | Table of session dates + focus + links to detail files |
| `ARCHIVE/SESSION_01.md` | Full session log (if needed for reference) |
| `ARCHIVE/SESSION_02.md` | Full session log |
| `KEY_DECISIONS.md` | All decisions ever made, sorted by domain |

### 3.3 Comparison

| Aspect | Current (3-file) | Proposed (Layered) |
|--------|------------------|-------------------|
| **Files to read** | 2 per session (CLAUDE.md auto) | 2-4 per session (lazy load) |
| **Lines loaded by default** | ~120 | ~80 |
| **Long-term history** | Inflates SESSION.md | Archived separately |
| **Retrieval** | Always full SESSION.md | Index + on-demand detail |
| **Maintenance burden** | Low (update 1 file) | Medium (update 3 files) |
| **Finding old decisions** | Scroll SESSION.md | Browse ARCHIVE/index + KEY_DECISIONS.md |
| **Risk of stale data** | Medium (SESSION.md updated irregularly) | Low (each file has clear scope) |

### 3.4 What DOESN'T Change

- **Zero pipeline code changes** — MEMORY/ files are for Claude only, not read by any Python module
- `obsidian_bridge/` unaffected
- `core/memory_writer.py` unaffected (it writes `memory_store.json`, not MEMORY/ files)
- Git workflow unchanged
- No new dependencies

### 3.5 What Changes

1. Create `ALWAYS.md` (move content from old `MEMORY/ALWAYS.md`, update with current rules)
2. Create `ARCHIVE/INDEX.md` with links to individual session files
3. Move session history out of `SESSION.md` into `ARCHIVE/SESSION_10.md`
4. Trim `SESSION.md` to only current-session decisions
5. Update `CLAUDE.md` to reference the new file structure
6. Delete old `MEMORY/` directory after migration

---

## 4. Evaluation Questions

1. **Does the added complexity justify the benefit?** The current 3-file system works. Adding a directory hierarchy with indexed archives increases maintenance surface. Is the retrieval benefit worth it?

2. **Who maintains this?** The AI agent (Claude) updates these files at session end. If Claude is thorough, the system self-maintains. If Claude skips updates, the system decays faster than a single-file system.

3. **How many sessions before ARCHIVE/ becomes unwieldy?** At ~1 session per week, 52 sessions/year. Would ~52 archive files be manageable, or would we need a cleanup/compaction strategy?

4. **Is the short-term/working/long-term distinction meaningful for an AI agent?** A human brain benefits from memory layering because of cognitive load limits. An AI agent has a fixed context window (not a graded memory model). Loading an ARCHIVE index costs the same context as loading the actual data — layering is a **convention**, not a technical optimization.

5. **Alternative: Keep 3-file system but trim SESSION.md?** Instead of a full architecture change, we could keep CLAUDE.md + SESSION.md + CHANGELOG.md but make SESSION.md strictly current-session only, and move old sessions to git history (git log does this already).

---

## 5. Recommendation

**Not implemented yet.** This document exists to evaluate the tradeoffs. The current 3-file system (CLAUDE.md + SESSION.md + CHANGELOG.md) was established in Session 10 and has not been exercised across multiple sessions yet. A decision should be made after observing how well (or poorly) the simple system performs over 2-3 sessions.
