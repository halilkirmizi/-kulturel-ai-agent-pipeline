# Kültürel AI Agent Pipeline — Claude Rules

## Architecture
- `state.json`: single source of truth for pipeline state
- `ffmpeg_builder`: only module allowed to call subprocess
- StepTracker gates via `gate()` → `begin()` → `complete()`/`fail()`

## Priority (ControlArbiter)
1. DAG/Contract  2. AOR  3. MemoryInfluence  4. StepTracker  5. ClipScoring

## Rules
- AOR single-writer enforces at runtime (2nd writer = ArtifactError)
- Memory max 50 entries per category, 30d compaction, no raw logs — only distilled knowledge
- Memory influence ≤30% and never overrides DAG/AOR/Contract
- `--mode observation_only` (default): no memory write-back; `adaptive_mode`: memory active
- No unsolicited microphone recording or irreversible changes — always ask user first
- `--no-captions` CLI flag only — does not persist in any config
- Format files in `formats/` are the single source for caption/hook/subscribe config

## Workflow
```bash
python pipeline.py <youtube_url> [--mode adaptive_mode] [--trace-arbiter] [--no-captions]
```

## Sensitive Files (never commit)
`.env`, `upload/client_secret.json`, `*.pickle`, `*.token`
