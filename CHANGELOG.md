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
