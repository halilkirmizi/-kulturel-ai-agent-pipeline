# Changelog
<!-- Append-only. One line per significant change. Git tracks code; this tracks decisions. -->

2026-06-21: Init: ilk video YouTube'a yüklendi (Arjantin WC interview, "Eternal Number 10")
2026-06-21: Add: format_football_interview.json (hook 120px/5sn, subscribe kırmızı/siyah outline, intro_duck=0.0, noise_reduction kapalı)
2026-06-21: Add: subscribe overlay fontcolor/bordercolor/borderw config desteği (overlays.py + config.py)
2026-06-21: Fix: HookConfig fontsize/uppercase/font cap_raw yerine hook_overlay'dan okuyor (config.py:201-205)
2026-06-21: Fix: downloader glob+mtime → deterministic video ID binding (ingest/downloader.py:56-68)
2026-06-21: Add: StepTracker UUID isolation (execution_trace_<uuid>.json) (core/steptracker.py:58-63)
2026-06-21: Test: cross-run contamination = NONE (3 consecutive transcribe failure runs, 0 leakage)
2026-06-21: Fix: youtube OTP'siz de kullanılacaksa Phase 2 tamamlanmalı
2026-06-30: Add: subject-aware reframe (analysis/reframe.py) — yüz takipli 9:16 crop, opt-in `--auto-reframe`, default kapalı, yüz bulunmazsa merkez-crop'a düşer (opencv-python-headless)
2026-06-30: Add: karaoke captions — opt-in `--karaoke`, per-word `\k` ASS highlight (sung=sarı, upcoming=beyaz), default kapalı, statik mod bit-bit aynı (captions.py)
2026-06-30: Add: silence trim — opt-in `--trim-silence`, transkript-ÖNCESİ kaynak medyadan sessizlik keser (altyazı senkronda kalır), default kapalı, hata/boşta orijinalle devam (editing/silence.py)
2026-06-30: Add: performance feedback (#2) — upload video_id artık saklanıyor (state + performance_store.json), provenance kaydı, `--fetch-analytics` ile YouTube stats çekip deterministik performance_score (core/performance.py, analysis/youtube_stats.py)
2026-06-30: Change: upload_video/upload_with_retry artık bool yerine video_id (Optional[str]) döner — truthiness korundu, geriye uyumlu
2026-06-30: Fix: Path.rename -> Path.replace (phase1 clip.mp4, phase2 final.mp4) — Windows'ta yeniden render'da "dosya zaten var" hatası (rename üzerine yazmıyor, replace yazıyor)
2026-06-30: Add: 'fit' framing (`--framing fit`) — yatay kareyi tam genişlikte 9:16 tuvale sığdırır + bulanık arka plan dolgusu; tam-genişlik gömülü altyazılar kesilmez. Default 'crop' (render_core._build_fit_command)
2026-06-30: Add: format_subtitled profili — gömülü altyazılı kaynaklar için (framing=fit + captions kapalı). Kullanım: `--format format_subtitled`. captions.enabled artık format JSON'dan da okunuyor
2026-06-30: Add: learning_engine (SİMÜLASYON, ROADMAP STEP 3) — performance_score'dan boyut-ağırlığı + feature lift önerir, versiyonlu weights_vN.json yazar, ASLA uygulamaz. `--propose-weights` (core/learning_engine.py)
2026-06-30: Fix: klip seçim kalitesi — LLM artık pencerelerin TAM metnini görüyor (önceden sadece baş/son önizleme → kör seçim). Mid-thought işaretleme + sertleştirilmiş prompt. Eski davranış `--legacy-select`. JSON sözleşmesi değişmedi. Gerçek A/B: yeni mod açılış klibini buldu + örtüşen klipleri eledi (clip_scoring.py)
2026-06-30: Add: örtüşen klip dedupe — seçim sonrası >%50 zaman örtüşen klipler elenir (yüksek skorlu tutulur), deterministik. legacy_select'te kapalı (clip_scoring._dedupe_overlapping)
