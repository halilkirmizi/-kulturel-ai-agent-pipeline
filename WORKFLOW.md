# YouTube Shorts Pipeline — Technical Workflow

> Links: [[kulturel AI agent]] · [[Key Decisions]] · [[SESSION]] · [[CLAUDE]]
> Güncel: 2026-06-30 (Session 14 — modüler yapı + reframe). Dosya bölünmesi Session 11/12'de yapıldı: `main.py` → `core/phase1|phase2|upload|cli`.

## Pipeline Architecture

### Phase 1 — analiz + crop (`core/phase1.py`)

```
YouTube URL
    ↓ [ingest/downloader.py]
yt-dlp (bestvideo+bestaudio, MP4 merge, deterministic video ID binding)
    ↓ [analysis/transcription.py]
faster-whisper (GPU CUDA float16, CPU int8 fallback, word-level timestamps)
    ↓ [analysis/topic_detection.py]
Topic extraction (keywords + named entities)
    ↓ [analysis/clip_scoring.py]
Groq LLaMA 3.3 70B — 4-boyut puanlama:
  • curiosity · emotional_relevance · educational_value · narrative_completeness
    ↓ toplam skora göre sırala → en iyi 3-5 klip
    ↓ [editing/render_core.py → build_crop_command]
    │   (opsiyonel) [analysis/reframe.py → detect_crop_x]  ← --auto-reframe
FFmpeg crop 9:16 (1080x1920, PTS-STARTPTS reset, setsar=1)
    ↓
shorts_output/<timestamp>/clip_N/{clip.mp4, state.json, ...}
```

### Phase 2 — captions + kompozisyon + upload (`core/phase2.py`, `core/upload.py`)

```
clip.mp4
    ↓ [analysis/transcription.py]
faster-whisper (word-level, caption timing)
    ↓ [editing/captions.py]
Word-level captions (PTS-STARTPTS + -vsync 0)
    ↓ [editing/render_core.py → build_compose_command]
    │   [editing/overlays.py] hook overlay + subscribe overlay
    │   [editing/audio.py]    intro/ambient audio mix
FFmpeg composition → final.mp4
    ↓ [core/upload.py → upload/youtube.py]
YouTube Data API v3 OAuth upload (quota tracking)
```

### Orchestration & control katmanı (`core/`)

| Modül | Rol |
|-------|-----|
| `control_arbiter.py` | 5-katman priority: DAG/Contract > AOR > MemoryInfluence > StepTracker > ClipScoring |
| `artifact_registry.py` (AOR) | Single-writer enforcement, atomic write (.tmp+rename) |
| `steptracker.py` | UUID-izole adım takibi (gate→begin→complete/fail) |
| `state.py` | `state.json` — pipeline state single source of truth |
| `memory_influence.py` / `memory_writer.py` | observation_only (default) / adaptive_mode |

## Key Technical Decisions

| Karar | Gerekçe |
|-------|---------|
| PTS-STARTPTS reset | `-ss` ile sıfır olmayan PTS başlangıcında süre uyuşmazlığını önler |
| Tüm encode'larda -vsync 0 | Filter chain'den gelen VFR'yi korur |
| Immutable PipelineConfig | Global state yok — her modül bağımsız test edilebilir |
| 4-boyut LLM puanlama | "Viral mı" değil, nesnel klip seçim kriteri |
| GPU-first + CPU fallback | CUDA hatasında graceful degradation |
| reframe ayrı modülde | `render_core` saf kalır (video okumaz); reframe `crop_x` döndürür |

## Critical Bug Prevention

### PTS Timestamp Safety
Kötü: `setpts={speed}*PTS,crop=...` → sıfır olmayan PTS girdisinde süre katlanır.
İyi: `setpts=PTS-STARTPTS,crop=...,setsar=1` → her hız ifadesinden önce sıfırla.

### GPU Fallback
CUDA kullanan her modül cublas/cuda RuntimeError'ı yakalar ve CPU'da retry eder. Tek bir GPU hatası pipeline'ı öldürmez.

### Reframe Güvenli Düşüş
`--auto-reframe` açıkken cv2 yok / yüz bulunamaz / okuma hatası → `detect_crop_x` `None` döner → merkez crop'a düşülür. Auto-reframe asla run'ı bozmaz.

## File Overview (gerçek yapı)

| Dosya | ~Satır | Sorumluluk |
|-------|--------|------------|
| `main.py` | 232 | Orchestrator (phase seçimi, config kurulumu) |
| `core/cli.py` | 47 | Arg parsing |
| `core/config.py` | 266 | Immutable config (format JSON + env + override) |
| `core/phase1.py` | 273 | download→transcribe→topics→score→crop |
| `core/phase2.py` | 220 | captions→compose orchestration |
| `core/upload.py` | 105 | YouTube upload orchestration |
| `core/control_arbiter.py` | 337 | 5-katman priority resolution |
| `core/artifact_registry.py` | 248 | AOR single-writer + atomic write |
| `core/steptracker.py` | 320 | UUID-izole adım takibi |
| `core/state.py` | 86 | state.json yönetimi |
| `ingest/downloader.py` | 72 | yt-dlp wrapper |
| `analysis/transcription.py` | 163 | Whisper GPU/CPU |
| `analysis/topic_detection.py` | 47 | Keyword/entity çıkarımı |
| `analysis/clip_scoring.py` | 461 | LLM 4-boyut puanlama |
| `analysis/translation.py` | 52 | Caption çeviri (es→en) |
| `analysis/reframe.py` | 128 | Yüz takipli crop_x (opt-in) |
| `editing/render_core.py` | 131 | Crop + compose komut üreticileri (saf) |
| `editing/captions.py` | 105 | Word-level caption |
| `editing/overlays.py` | 74 | Hook + subscribe overlay |
| `editing/audio.py` | 77 | Audio mix |
| `editing/ffmpeg_builder.py` | 128 | ffmpeg path + execute + gpu args |
| `upload/youtube.py` | 254 | OAuth v3 upload, quota |

## CLI (özet)

```bash
python main.py <youtube_url> [--auto-reframe] [--mode adaptive_mode] [--no-captions] [--upload] [--trace-arbiter]
python main.py --resume short_XXX/clip_1 --upload   # Phase 2'den devam
```
