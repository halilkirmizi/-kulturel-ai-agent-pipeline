# Kültürel AI Agent Pipeline — Claude Rules

## Coding Discipline (Karpathy Guidelines)

> Kaynak: `multica-ai/andrej-karpathy-skills` (CLAUDE.md). LLM kod hatalarını azaltan davranış kuralları. Bias: hız yerine dikkat; trivial işlerde muhakeme kullan.

1. **Kodlamadan önce düşün.** Varsayımlarını açıkça söyle; emin değilsen SOR. Birden çok yorum varsa hepsini sun, sessizce seçme. Daha basit yol varsa söyle. Belirsizlik varsa DUR, neyin karışık olduğunu adlandır.
2. **Önce sadelik.** Problemi çözen minimum kod. İstenmeyen özellik/soyutlama/"esneklik"/imkânsız-senaryo error handling yok. 200 satır 50 olabiliyorsa yeniden yaz. Test: "Kıdemli bir mühendis bunu fazla karmaşık bulur mu?"
3. **Cerrahi değişiklik.** Sadece gerekeni değiştir. Bitişik kodu/yorumu/formatı "iyileştirme", bozuk olmayanı refactor etme, mevcut stile uy. Alakasız ölü kodu SİLME — sadece belirt. Kendi değişikliğinin yarattığı orphan import/değişkeni temizle. Test: her değişen satır doğrudan isteğe izlenebilmeli.
4. **Hedef-odaklı yürütme.** Görevi doğrulanabilir hedefe çevir ("validation ekle" → "geçersiz girdi için test yaz, geçir"). Çok adımlı işte kısa plan ver (adım → doğrulama). Güçlü başarı kriteri bağımsız çalışmayı sağlar; "çalışsın yeter" sürekli soru gerektirir.

**Çalışıyor sinyali:** diff'te daha az gereksiz değişiklik, aşırı-karmaşıklıktan daha az yeniden-yazım, sorular hatadan SONRA değil ÖNCE geliyor.

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

## FFmpeg Render Presets
- Test render: `-preset ultrafast -crf 28` (5x hizli) · Final: `-preset slow -crf 18` (en iyi kalite)

## Disk Hijyeni (temizlik kurali)
- Upload dogrulandiktan sonra batch klasorunden `final*.mp4` HARIC her sey silinebilir (kaynak/klip/ara-render yeniden uretilebilir).
- `temp/` serbestce bosaltilir — AKTIF kampanya varliklari haric (or. yaklasan mac icin teaser/AI klipler; olay gecince onlar da gider).
- `performance_store.json` + `weights/` ASLA silinmez (ogrenme dongusunun canli verisi). `logs/` kucuk kalir, dokunma.

## Multi-Part Video Workflow (Altın Kural)

1. **Step 1:** Ilk parcayi pipeline'dan gecir, cikar
2. **Kullanici onayi:** Klipleri degerlendir, "devam edelim mi?" diye sor
3. **Step 2:** Sadece onay verdiginde diger parcalari isle

Kural: 2 saatten uzun videolari 30 dakikalik parcalara bol, her parcasi icin yeni pipeline calistir.

## Sensitive Files (never commit)
`.env`, `upload/client_secret.json`, `*.pickle`, `*.token`

## Commit Kurali (Altın Kural)

Her session sonunda GitHub'a commit yap. 12 mesajda bir commit kontrolu yap. Commit mesaji:
- Ne degistirildi
- Test sonuclari
- Bilinen sorunlar
