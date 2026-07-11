# YouTube Shorts Pipeline — Technical Workflow

> Links: [[kulturel AI agent]] · [[Key Decisions]] · [[SESSION]] · [[CLAUDE]]
> Güncel: 2026-07-11 (`--news-trend` trend otomatik tespiti + `--news`/`--news-script` faceless HABER modu). Önceki: analytics re-auth GERÇEK VERİ + `WHISPER_TASK=translate` (2026-07-10). Modüler yapı Session 11/12.

## Pipeline Architecture

### Phase 1 — analiz + crop (`core/phase1.py`)

```
YouTube URL
    ↓ [ingest/downloader.py]
yt-dlp (bestvideo+bestaudio, MP4 merge, deterministic video ID binding)
    ↓ [analysis/transcription.py]
faster-whisper (GPU CUDA float16, CPU int8 fallback, word-level timestamps)
    │   WHISPER_MODEL=small/medium (isim doğruluğu) · WHISPER_TASK=translate (non-EN kaynağı doğrudan EN'e çevir)
    │   NOT: medium 6GB GPU'da çöker → CUDA_VISIBLE_DEVICES=-1 (CPU whisper) + --no-gpu (CPU encode) birlikte
    ↓ [analysis/topic_detection.py]
Topic extraction (keywords + named entities)
    ↓ [analysis/clip_scoring.py]
Aday pencereler kurulur → _is_intro_text() ile podcast intro/housekeeping/sponsor pencereleri ELENIR
    ↓
Groq LLaMA 3.3 70B — 4-boyut puanlama:
  • curiosity · emotional_relevance · educational_value · narrative_completeness
    ↓ toplam skora göre sırala → en iyi 3-5 klip
    ↓ _snap_to_sentences(): klip başı/sonu CÜMLE sınırına (. ! ?) snap'lenir (yarıda kesmez)
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
    ↓ [analysis/demonetization.py]  ← ÜRETİM SONRASI, feedback/memory ÖNCESİ
DEMONETIZATION RISK raporu (LOW/MEDIUM/HIGH) — bilgilendirici, bloklamaz
    ↓ [core/upload.py → upload/youtube.py]
YouTube Data API v3 OAuth upload (scope: upload+readonly, quota tracking)
  • privacy: default unlisted · `--public` → public · `--publish-at`/scheduled → private
```

### Demonetize-risk (`analysis/demonetization.py`)
- Saf/deterministik (LLM yok). Konuşma metni + başlığı YouTube reklam-dostu kategorilerine göre tarar.
- Kategoriler: hate_slur, profanity_strong/mild, adult_sexual, graphic_violence, sensitive_tragedy, gambling, content_id_music.
- **Futbol metaforları (kill/attack/shoot/war/death/beat) bilinçli HARİÇ** → yanlış-pozitif yok.
- İlk ~8sn'de güçlü küfür → ek boost (YouTube "ilk 7 saniye" kuralı). Content ID: `has_external_music=True` ise +0.5.
- phase1: kliplerden sonra · phase2: render sonrası, upload öncesi çalışır.

### Analytics / öğrenme döngüsü — ARTIK ÇALIŞIYOR (2026-07-10)
- `--fetch-analytics` istatistik okur (`videos.list part=statistics`) → **`youtube.readonly` scope şart**.
- **Re-auth fix (2026-07-10):** `youtube.py` artık cached token'da eksik scope varsa creds'i atıp tarayıcı consent'i tetikler (eski upload-only token refresh'te scope'u koruyup re-auth'u atlıyordu); `youtube_stats._default_service` de `_get_authenticated_service()` üzerinden gider. Bu iki fix olmadan re-auth imkansızdı.
- **Döngü gerçek veriyle kapandı:** upload→provenance → `--fetch-analytics` (gerçek views) → `compute_performance_score` → `--propose-weights` (weights_vN) → `--apply-weights`. İlk güvenilir öneri `weights_v2` (5 örnek). Feature_lift için feature varyasyonlu upload gerekir (şu an hepsi aynı).

### Faceless HABER modu (`--news`) — YENİ ANA YÖN (2026-07-11)

Klip-çıkarmadan AYRI akış (indirme/whisper/skorlama yok). Kanal, talking-head klip
Short'ları retention'da çöktüğü için (5sn izlenme, %0.1) bu formata döndü.

```
python main.py --news "<konu>" [--upload]                    # LLM metin (konu manuel)
python main.py --news-script news_scripts/<x>.json [--upload]  # elle metin (bring-your-own-script)
python main.py --news-trend [--upload]                        # konu OTOMATİK (RSS trend)
    ↓ [analysis/trend_detector.py]  (--news-trend) 4 futbol RSS (BBC/Guardian/ESPN/Sky) → taze pencere (36s, TREND_WINDOW_HOURS, shelf-life) → dedup → Groq LLM en iyi hook'lu haberi seçer → factual topic. Guard: trajedi/ölüm/suç + futbol-dışı spor elenir. Groq yoksa heuristik (en taze). Ağ I/O izole, parse/rank saf/testli.
    ↓ [analysis/news_script.py]  Groq LLM → özgün metin (60-80 kelime, min-retry) + görsel planı + başlık/etiket
    │   VEYA `load_news_script(path)` → elle yazılmış script.json (aynı `_validate_script` şeması; KESİN uzunluk kontrolü, LLM ~25sn yerine 15-20sn)
    ↓ [analysis/tts.py]          edge-tts (GuyNeural) → voice.mp3 + voice.vtt (kelime-zamanlı)
    ↓ [analysis/stock_media.py]  Pixabay video (tag-relevance gate + dedup) + Wikimedia foto (redirect+thumbnail)
    ↓ [editing/montage.py]       segment render (video cover-crop / foto Ken-Burns) → concat → ASS kinetik altyazı → ses+müzik miks
    ↓ [analysis/demonetization.py]  risk raporu (özgün metin + CC/stok → LOW)
    ↓ [core/news_mode.py → upload/youtube.py]  next_publish_slot() (12:00/18:00) ile --publish-at programlı public
```
- **Demonetize-güvenli:** özgün metin (reused-content değil) + telif-güvenli Pixabay + CC Wikimedia (Content ID yok). AI ses tek başına flag'lemez.
- **Gerekli:** `.env` → `PIXABAY_API_KEY`. Music: `assets/music/`.
- **Relevance filtresi:** tag'de "soccer"/"football" şart + reject listesi (konser/okyanus/tenis/CGI/american football eler) + görülmüş-ID dedup.
- **main.py:** ~8 satır route; mantık ayrı modüllerde; altyapı (config/logger/demonetization/upload/ffmpeg_builder) ortak.

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
| `analysis/translation.py` | 52 | Caption çeviri LLM (es→en). Non-EN için tercih: `WHISPER_TASK=translate` (Whisper her dili EN'e çevirir) |
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

# Non-EN kaynak → İngilizce altyazı (Whisper translate)
WHISPER_TASK=translate WHISPER_MODEL=small python main.py <link>
# medium kalite (GPU çöker → tam CPU): whisper CPU + encode CPU
CUDA_VISIBLE_DEVICES=-1 WHISPER_TASK=translate WHISPER_MODEL=medium python main.py <link> --no-gpu

# Yayın: hemen public / N saat sonra programlı public
python main.py --resume short_XXX/clip_1 --upload --public
python main.py --resume short_XXX/clip_2 --upload --publish-at "2026-07-10 20:39"

# Analytics (ilk sefer tarayıcı re-auth: upload+readonly consent)
python main.py --fetch-analytics && python main.py --propose-weights
```

### AI intro sesi + center stamp (one-off, opt-in)
- AI intro: `python -m edge_tts --voice en-US-GuyNeural --rate=+8% --text "<intro_script>" --write-media <clip_dir>/intro.mp3` → Phase 2 kullanır.
- Center stamp: ffmpeg `drawtext` (Impact, ortada). Font-path colon gotcha → font'u klip dizinine kopyala, göreli yolla ver. Orijinali `final_nostamp.mp4`'e yedekle, stamp'li → `final.mp4`.
