# Pipeline Session Log

> **Read this file first at the start of each session.** This is the conversation history backup.
> Links: `CHANGELOG.md` (what changed) · `CLAUDE.md` (rules)

---

## GÜNCEL DURUM — 2026-07-11 #3 (trend otomatik tespiti `--news-trend` + assets commit)

**1) `assets/` commit'lendi (`b0997da`):** `--news` montajının kullandığı runtime varlıkları (emoji overlay PNG'leri + 2 telif-güvenli mp3 müzik) git'te değildi → fresh clone montajı kırardı. Commit'lendi+push. NOT: SESSION #2'deki "`--news-script` commit bekliyor" notu bayatmış — özellik zaten `9f8f042`'de commit'liymiş, origin/main ile senkrondu.

**2) YENİ ÖZELLİK: `--news-trend` — trend otomatik tespiti (commit+push `b8ada31`).**
- **Sorun:** haber konusu manueldi ("bugünün futbol haberi"ni elle yazıyorduk). WebSearch benim (Claude) tool'um, pipeline standalone Python runtime'ında YOK.
- **Çözüm — `analysis/trend_detector.py`:** 4 telif-siz/key-siz futbol RSS feed'i (BBC Sport / Guardian / ESPN soccer / Sky) → taze pencere filtresi (default **36s**, `TREND_WINDOW_HOURS`, shelf-life kuralına uyar) → cross-source dedup → **Groq LLM en iyi hook'lu taze haberi seçer** ve self-contained factual topic döndürür → `generate_news_script`'i besler. Groq yoksa/başarısızsa **heuristik fallback** (en taze haber). Saf parse/rank fonksiyonları test edilebilir; ağ I/O izole (stock_media stili).
- **İki guard (canlı testte ortaya çıktı):** LLM önce **25 yaşında oyuncu ölümünü**, sonra **golf rekorunu** seçti. İkisi de hype Short için yanlış → (a) ölüm/suç terimleri `_SKIP_TITLE`'da havuzdan elenir (heuristik yolu da korur), (b) LLM prompt'u **futbol-only + trajedi-yasağı**. Sonuç: tutarlı gerçek futbol haberi (Portugal/Jorge Jesus/Ronaldo canlı seçildi).
- **Wiring:** CLI `--news-trend` (topic gerekmez) · main.py ~4 satır route (`args.news_trend` ve topic boşsa `detect_trending_topic(config)`) · config değişmedi (detect `config.groq_api_key`/`groq_model` okur).
- **Canlı doğrulama:** 4 feed → 100 taze haber → LLM uygun futbol haberi seçti (render/upload yapılmadı, sadece detection). **Test: `tests/run_all.py` 17/17 suite, 246/246 check PASS** (yeni `test_trend_detector` 27/27; 219→246).

**Kullanım:**
```bash
python main.py --news-trend            # otomatik trend konu → render (önizleme)
python main.py --news-trend --upload   # otomatik trend → 12/18 programlı public
TREND_WINDOW_HOURS=24 python main.py --news-trend   # daha dar taze pencere
```

**Açık / sonraki adımlar:** Cron tam otomatik (günde 1-2 `--news-trend --upload`, peak saate) · b-roll kalitesi (jenerik stok query havuzu) · trend seçimini provenance/öğrenme döngüsüne bağla · birkaç gün sonra `--fetch-analytics` → `xVaQLTb1zAc` gerçek stats.

---

## GÜNCEL DURUM — 2026-07-11 #2 (bring-your-own-script `--news-script` + Haaland Short yayında)

**Yeni özellik: `--news-script <path>` (commit bekliyor) — hazır metin besleme.**
- Kullanıcı elinde bir kaynak makale/metin ile geldi ("bunu 15-20sn shorts scriptine çevir + kurgula"). `--news` konudan LLM ile ~60-80 kelime (~25sn) üretir → kullanıcının istediği 15-20sn'lik KESİN uzunluk için uymuyordu.
- Çözüm: **bring-your-own-script** yolu. LLM yerine elle yazılmış `script.json` yüklenir; aynı şema + aynı doğrulama (montaj onu LLM çıktısıyla ÖZDEŞ işler). Operatör kaynak makaleyi tam istediği uzunlukta kısaltır.
- **Mimari (minimal, main.py şişmedi):** `news_script.py` → doğrulama `_validate_script()`'e ayrıldı + `load_news_script(path)` eklendi. `news_mode.run_news` → `config.news_script_path` doluysa dosyadan yükler, yoksa eski LLM yolu. `config.news_script_path` alanı + `--news-script` CLI (`--news` artık `nargs="?"`; ikisinden biri news modunu tetikler).
- **Doğrulama:** Haaland/Norveç metni → `news_scripts/haaland_brazil.json` (53 kelime, 9 görsel). E2E render: **20.0s**, 1080x1920, 9.7MB, demonetize LOW. Kareler kontrol edildi: açılış havadan saha, gerçek Haaland/Mbappé/Messi fotoları, "2-1" altyazıda + TTS'te doğru. **Test 219/219 PASS.**

**Yayınlandı (kullanıcı "paylaşalım" dedi):**
- **`xVaQLTb1zAc`** ("Haaland STUNS Brazil — Norway's First-Ever World Cup Quarter-Final!") → **2026-07-11 18:00 (İsviçre) scheduled public.** Provenance kaydedildi. Maç sonucu → aynı gün yayın ([[kulturel-shorts-shelf-life]]).

**Açık / sonraki adımlar:** (öncekiyle aynı) trend otomatik tespiti · cron tam otomatik · b-roll kalitesi (jenerik stok; "soccer fans crowd" query'si amatör saha getiriyor, daha iyi query havuzu) · birkaç gün sonra `--fetch-analytics` → `xVaQLTb1zAc` gerçek stats.

---

## GÜNCEL DURUM — 2026-07-11 (STRATEJİ DÖNÜŞÜ: faceless futbol HABER modu + retention teşhisi)

**Büyük karar: kanal klip-çıkarma'dan FACELESS FUTBOL HABER formatına döndü.** Sebep gerçek veri.

**Retention teşhisi (analytics ekranı):**
- Klip-çıkarma / talking-head Short'ları **çöküyor**: örn. Lamin Yamal videosu = **78 gösterim, 5sn ortalama izlenme, %0.1**. YouTube küçük bir gruba gösterip retention düşük olunca dağıtımı kesiyor → 0 izlenme. Unlisted değil, PUBLIC'ti — sorun keşif değil, **retention (ilk 1-5 saniye tutmuyor)**.
- Aynı kanaldaki **CIA/whistleblower içeriği TUTUYOR**: 1000+ izlenme, %22-29 retention. Yani kanal itilebiliyor; talking-head futbol formatı yanlıştı.
- Ek sorun: sansasyonel başlık ("...DEBUT GOAL") görsel vaat ediyor ama talking-head gol göstermiyor → izleyici 5sn'de kaçıyor.

**Prototip süreci:**
- İlk deneme: statik foto slayt gösterisi → kullanıcı **reddetti** ("kimse izlemez").
- Kullanıcı yönü: telif-güvenli (demonetize yok) futbol HABER, AI/kendi sesi, ön planda video+foto, ilgi çekici.
- Kazanan format: **haber metni + AI ses + hızlı-kesme hareketli stok video + oyuncu fotoları + kinetik altyazı + müzik** → kullanıcı **onayladı**.

**Demonetize netliği (kullanıcıya):**
- Maç VİDEO footage = Content ID = demonetize ❌ · Getty/basın "o an" fotosu = telif riski ⚠️ · **CC oyuncu fotosu (Wikimedia) = GÜVENLİ ✅** · özgün metin = reused-content değil ✅ · **AI ses tek başına flag'lemez**.

**Yeni özellik: `--news` TAM OTOMATİK modu (commit+push `f566ef8`):**
- `python main.py --news "<konu>"` → LLM özgün metin → edge-tts ses+VTT → Pixabay video (etiket-filtreli+dedup) + Wikimedia foto (redirect+thumbnail fallback) → hızlı-kesme kinetik-altyazılı montaj → demonetize kontrolü → `--upload` ile **peak-saate (12/18) programlı** upload.
- **Mimari (main.py şişmesin):** `analysis/news_script.py` · `analysis/stock_media.py` · `analysis/tts.py` · `editing/montage.py` · `core/news_mode.py` (+`next_publish_slot()`) · main.py ~8 satır route · config `pixabay_api_key` · `ffmpeg_builder.execute(cwd=)` (Windows colon-path).
- **Pixabay anahtarı `.env`'de** (PIXABAY_API_KEY, gitignored). Kullanıcı sağladı.
- E2E doğrulandı: France 2-0 Morocco → 18.96s, 10 görsel, Mbappe+Dembele foto + filtreli b-roll, demonetize LOW. **Test 219/219 PASS.**

**Yayın kuralı (kesinleşti):** her video **12:00 veya 18:00** (İsviçre) — ölü saatte public YOK. Hep `--publish-at`/next_publish_slot. (Bugün 06:00'da yanlışlıkla public yaptım → `videos.update` scope yetersiz olduğu için Studio'dan düzeltildi.)

**Bugün yüklenen/programlanan:**
- `K8hKbAEGh8k` (DISCIPLINE / Mbappé konuşma klibi) — public (2026-07-10).
- `iTUo-J_4nPE` (PASSION! klibi) — 2026-07-10 20:39 scheduled.
- `u0aAeEUzuao` (AI-intro+stamp "France UNSTOPPABLE") — Studio'dan 12:00'a alındı.
- **`wFJm_N_g3yI` (haber formatı "FRANCE REACH SEMIS!") — 2026-07-11 12:00 scheduled.** ⚠️ u0aAeEUzuao ile aynı slot; kullanıcı eskisini 18:00/unlisted yapacak (haber formatı tercih edildi).

**Açık / sonraki adımlar:**
1. **Trend otomatik tespiti** — konu şu an manuel; "bugünün futbol haberi"ni otomatik bulmak (WebSearch/RSS).
2. **Cron / zamanlanmış** tam otomatik (günde 1-2 news, `--publish-at` peak).
3. Altyazı kelime-vurgu animasyonu (retention+); news video'ları provenance/öğrenme döngüsüne bağla.
4. Ufak: "foosball" gibi kenar durum için tag-filtre biraz daha sıkı.
5. Eski klip-çıkarma pipeline'ı duruyor (bozulmadı) ama kanal yönü artık HABER.

---

## GÜNCEL DURUM — 2026-07-10 (analytics re-auth + öğrenme döngüsü GERÇEK VERİ + FR→EN + İLK PUBLIC Short'lar)

**1) Analytics re-auth ARTIK ÇALIŞIYOR — 2 gerçek fix (commit+push `9ffe999`):**
- Kök sorun: eski upload-only token refresh edilince eski scope korunuyor → `youtube.py` re-auth'u atlıyordu. Ayrıca `--fetch-analytics`, `youtube_stats._default_service` üzerinden pickle'ı DOĞRUDAN okuyup re-auth akışını hiç çağırmıyordu → readonly consent İMKANSIZDI (SESSION-07-04 notundaki "sadece --fetch-analytics çalıştır" talimatı yanlıştı).
- Fix 1 `upload/youtube.py`: **scope-subset kontrolü** — cached token gerekli scope'lardan birini içermiyorsa creds atılır, tam re-auth (tarayıcı consent) tetiklenir.
- Fix 2 `analysis/youtube_stats.py`: `_default_service` artık `_get_authenticated_service()` üzerinden gider (refresh + scope-check + consent tek yerde).
- **Sonuç:** re-auth tamamlandı (upload+readonly). 6 videodan **5'i gerçek stats aldı** (avg perf 0.0971; Yamal `nrCzqdP-BMs` 11 view en yüksek). 1 video (`oK2Jx8Vx4TU`) stats dönmedi (silinmiş/erişilemez olabilir).
- **Öğrenme döngüsü GERÇEK VERİYLE kapandı:** `--propose-weights` → ilk **güvenilir** `weights_v2` (curiosity 1.023, educational 1.022, emotional 0.997; feature_lift None çünkü tüm videoların feature'ı aynı). `load_latest_weights` v2'yi alıyor → `--apply-weights` çalışır. UYARI: sinyal zayıf/yanlı (hepsi unlisted 0-11 view; Yamal ekstra prodüksiyondan).

**2) Germany klipleri İPTAL:** Kullanıcı "tarihi geçti, izlenmez" dedi (RtfvglX7hiM batch'i ölü). Ders → hafıza [[kulturel-shorts-shelf-life]]: haber/trend Short'ları AYNI GÜN yayınla yoksa bayatlar.

**3) Fransızca→İngilizce — yeni özellik `WHISPER_TASK=translate` (commit+push `c1122b4`):**
- `core/config.py` `whisper_task` (env, default "transcribe") + `analysis/transcription.py` `task=config.whisper_task`. Whisper herhangi bir dili DOĞRUDAN İngilizce'ye çevirir (zamanlama korunur, isimler düzelir). Eski `translate_segments` sadece es→en (İspanyolca prompt) idi.
- Kaynak: MadeinFOOT `-zbKCSIe_Sw` (Mbappé'nin France 2-0 Morocco sonrası konuşması, FR, **bugün yüklendi, 241k view**). small-GPU translate → temiz İngilizce ama 1 klipte "world champion" garble; **medium-CPU translate → 2 temiz klip** (garble klibi otomatik düştü).
- **GPU/CPU gotcha:** whisper **medium 6GB GPU'da çöküyor** → `CUDA_VISIBLE_DEVICES=-1` (CPU whisper) gerekli; o da NVENC encode'u kırıyor → `--no-gpu` ile BİRLİKTE kullan. İki lever ayrı (biri whisper, biri encode).

**4) AI intro sesi + center stamp (one-off, opt-in — [[no-hardcoded-creative-treatments]]):**
- Kullanıcı kendi sesi yerine **AI ses** istedi → `edge-tts` (GuyNeural) ile intro_script → `intro.mp3`. Phase 2 intro'yu zorunlu kılıyor; AI ses bu ihtiyacı karşıladı (mikrofon açmadan).
- ffmpeg drawtext ile **ekran ortasına Impact büyük kelime stamp'i** (clip_1 "DISCIPLINE", clip_2 "PASSION!"). Gotcha: font-path'teki `C:` iki noktası ffmpeg filtre parser'ını bozar → font'u klip dizinine kopyalayıp GÖRELİ yolla çöz.

**5) İLK PUBLIC Short'lar yüklendi (18:39 CEST):**
- clip_1 (DISCIPLINE / "FEAR DOESN'T WIN MATCHES") → **`K8hKbAEGh8k` PUBLIC — canlı**.
- clip_2 (PASSION! / "PASSION DRIVES SUCCESS") → **`iTUo-J_4nPE`, 2026-07-10 20:39'a scheduled public** (`--publish-at`, o ana kadar private).
- İkisi de demonetize LOW, provenance kaydedildi. Not: upload `final.mp4`'ü yüklüyor → stamp'li versiyonu `final.mp4` yapıp orijinali `final_nostamp.mp4`'e yedekledik.

**Test:** `tests/run_all.py` → **16/16 suite, 219/219 PASS** (her iki commit'te).

**Açık konular / next:**
- Footage kararı (A talking-head kabul / B b-roll) hâlâ ertelendi.
- **Whisper GPU→CPU otomatik fallback + `--no-gpu` transkripti de kapsasın** (medium-GPU crash + flag decoupling düzeltilsin).
- Birkaç gün sonra `--fetch-analytics` → `K8hKbAEGh8k` + `iTUo-J_4nPE` gerçek stats → `--propose-weights`/`--apply-weights` daha anlamlı.
- ESPN kaynağı `Bdf7whnn11I` klipleri de mevcut (`short_20260710_004954` small + `_110753`); istenirse 3. Short için hazır.

---

## GÜNCEL DURUM — 2026-07-05 (session sonu — klip kalitesi fix'leri)

**Yeni video:** The Athletic FC — *"Why have Germany lost their World Cup aura?"* (`RtfvglX7hiM`, 44dk). `WHISPER_MODEL=small` + `LLM_MAX_CHARS=15000` ile çalıştırıldı. Demonetize-risk otomatik çalıştı (hepsi LOW).

**Kullanıcı geri bildirimi → 2 klip-kalitesi bug'ı bulundu ve KALICI ÇÖZÜLDÜ (commit+push+test):**

1. **Cümleler yarıda kesiliyordu** (klip "play and actually..." ile başlayıp "...over the last" ile kesiliyordu). Kök neden: pencereler whisper VAD segment sınırına (~5-6sn, cümle ortası) snap'leniyordu; `_opens_mid_thought` sadece yumuşak START ipucuydu, END'i hiç kontrol etmiyordu.
   - **Fix `f3ceb7d`:** `_snap_to_sentences()` — seçilen klip başı/sonu NOKTALAMA tabanlı cümle sınırına snap'lenir (start = önceki segment `. ! ?` ile bitince; end = kendisi `. ! ?` ile biten segment; süre [12,35] içinde). Noktalama yoksa `_expand_to_boundaries`'e güvenli fallback. 3 finalizasyon call-site değişti.

2. **LLM ısrarla podcast açılışını seçiyordu** (0-18sn "Hello and welcome to the Athletic FC podcast with me..."). Yeniden-seçtirmek çözmüyordu.
   - **Fix `d341355`:** `_is_intro_text()` — yüksek-hassasiyetli kalıp eşlemesi (welcome to the, podcast with me, brought to you by, delivers the latest, subscribe, thanks for listening, my name is...). `_build_windows` bu pencereleri skorlamaya girmeden eler; hepsi eşleşirse orijinali korur.

**Doğrulama (gerçek re-run):** intro elendi ("Dropped 2 intro/housekeeping window(s)"), iki klip de gerçek içerik + temiz cümle sınırları (clip_1 UEFA's Bad Night skor 32, clip_2 Royal Rumble skor 29).
**Test:** `tests/run_all.py` → **16/16 suite, 219/219 check PASS** (yeni: test_sentence_snap 13/13, test_intro_filter 10/10).

**Hâlâ AÇIK konular:**
- **Sorun 2 — footage:** Kaynak stüdyo talking-head podcast'i, arkada maç görüntüsü yok. İki yol: (A) görüntülü kaynak seç (highlight/reaction), (B) b-roll bindirme sistemi (büyük iş + lisans). Kullanıcı henüz seçmedi.
- **İnce:** dolgulu ama gramatik açılış cümleleri ("But yeah, so hopefully...") hâlâ geçebilir (zayıf hook, ayrı konu).
- Germany klipleri Phase 2 bekliyor (intro sesi gerekir; cold-open/seslendirmesiz seçenek var).
- (Önceki oturumdan) `--fetch-analytics` re-auth (kullanıcı tarayıcı consent), publish-at ile programlı yayın, clip_1 (Yamal) müzik lisansı+altyazı ismi düzeltilmeden public yapılmaz.

---

## GÜNCEL DURUM — 2026-07-04 (session sonu)

**Trend + ilk analitik podcast pipeline:** FIFA Dünya Kupası 2026 (19 Tem finali) trend belirlendi → kaynak **The Athletic FC Podcast — "Who is winning the World Cup so far?"** (`PYJsZRViYL8`, 40dk). Phase 1 → 2 klip: **clip_1 (Lamin Yamal Scores, 32.0)**, **clip_2 (Cape Verde Shocks Spain, 29.0)**.

**Bug fix (Groq 413):** 40dk podcast skorlama prompt'u 14.3K token → Groq ücretsiz TPM limiti 12K'yı aşıyordu. Çözüm: `LLM_MAX_CHARS=15000` (env, kod değişmeden) → transkript+listing küçülür, prompt ~9K token. Kural: uzun kaynaklarda `LLM_MAX_CHARS` düşür.

**"Cold-open" yaratıcı kurgu (ONE-OFF prototip, pipeline'a ENTEGRE DEĞİL):** Kullanıcı talebiyle haber-tarzı giriş kurgusu ffmpeg ile elle üretildi: gerçek oyuncu/bayrak görseli (Wikimedia CC) arka plan + renkli emoji hook + haber müziği (Chosic) + kullanıcı seslendirmesi (opsiyonel) → yumuşak xfade → altyazılı klip → SUBSCRIBE butonu (PIL, kırmızı pill) → sonda fade-out. **Karar: bunlar pipeline'a default gömülMEZ** — her video farklı, opsiyonel kalır. Bkz. hafıza [[no-hardcoded-creative-treatments]].
- clip_1: gerçek Yamal fotoğrafı + kullanıcı sesi (1.35x atempo) → `nrCzqdP-BMs` **unlisted** yüklendi (altyazı isim hatası + müzik lisansı beklediği için public değil).
- clip_2: Cape Verde bayrağı + seslendirmesiz + **whisper `small`** ile yeniden transkript (temiz altyazı) → `final_full.mp4` (36s, hatasız).

**İki gerçek pipeline hatası bulundu + DÜZELTİLDİ (commit + push):**
1. **Analytics hiç okunamıyordu:** `upload/youtube.py` `_SCOPES` sadece `youtube.upload` → `--fetch-analytics` 403 "insufficient scopes". Tüm öğrenme döngüsü gerçek veri alamıyordu. → **`youtube.readonly` eklendi.** Eski token yedeklendi (`~/.youtube_upload_token.pickle.old_uploadonly_bak`). **Kullanıcı `python main.py --fetch-analytics` ile tarayıcıdan yeniden yetkilendirmeli** (upload+readonly consent).
2. **Hep unlisted yükleniyordu** (0 izlenme = keşfedilemez). → **`--public` bayrağı** eklendi (default unlisted, scheduled→private).

**Yeni özellik — demonetize-risk kontrolü:** `analysis/demonetization.py` (saf/deterministik). Üretim sonrası, **feedback(upload)/memory ÖNCESİ** çalışır (phase1: klipler sonrası; phase2: render sonrası, upload öncesi). Konuşma+başlığı YouTube reklam-dostu kategorilerine göre tarar → risk 0-1 + LOW/MEDIUM/HIGH + flag'ler. Futbol metaforları (kill/attack/shoot/war) bilinçli hariç → yanlış-pozitif yok. Content ID müzik bayrağı + ilk-8sn küfür boost.

**Test:** `python tests/run_all.py` → **14/14 suite, 196/196 check PASS** (yeni: test_demonetization 18/18, test_upload_meta 24/24).
**Commit'ler (push edildi):** `bfc5567` (--public + readonly scope), `7bfcede` (demonetization).
**Açık konular (sonraki oturum):** (1) `--fetch-analytics` re-auth (kullanıcı tarayıcı onayı) → gerçek analytics + öğrenme döngüsü. (2) Yayınlar `--publish-at` ile belirlenen zamanlarda programlı public. (3) Sonraki videolarda `WHISPER_MODEL=small/medium` (isim doğruluğu). (4) clip_1 public'e almadan önce müzik lisansı + altyazı ismi düzelt.

---

## GÜNCEL DURUM — 2026-07-03 (session sonu)

**İlk tam E2E + yükleme yapıldı:** Haaland WC vlog → 3 Short üretildi + YouTube'a yüklendi (unlisted). Ayrıca Arjantin/Messi klibi (İngilizce çevrili altyazı) yüklendi. Toplam 4 video canlı.
**Bu oturumda eklenenler:**
- `--select-with claude` (Groq yerine Claude klip seçer; ANTHROPIC_API_KEY gerekir, default groq).
- **Altyazı konumu fix:** ASS'e PlayResX/Y=1080x1920 (yoksa libass 384x288 varsayıp altyazıyı kaçırıyordu). format1 fontsize 78, margin_bottom 420 (alt-üçte-bir).
- **Hook/başlık capturing:** CLIP_SYSTEM_PROMPT HOOK RULES + youtube_title/description alanları (sansasyonel ALL CAPS + emoji + hashtag). upload.py bunları kullanır, alansız kliplere fallback.
- **Yükleme görünürlük:** `--publish-at "YYYY-MM-DD HH:MM"` (programlı public), dil en (`--lang`), kategori Sports(17), otomatik 3-5 etiket, madeForKids=false.
- Windows saati Avrupa (CEST) → publish-at makinenin tz'ini kullanır, doğru.
**Test:** `python tests/run_all.py` → **13/13 suite, 169/169 check PASS**.
**Açık konu (sonraki oturum):** Yüklenenler `unlisted` → 0 izlenme normal; izlenme için Public gerekir. İstenirse `--public` bayrağı eklenecek. Ayrıca eski render'lı ~5 klip yüklenmeyi bekliyor (düzeltilmiş altyazıyla yeniden render + başlıkla).

---

## GÜNCEL DURUM — 2026-07-01

**Klip seçiciyi Claude yapabiliyor:** `--select-with claude` → Groq/LLaMA yerine Anthropic Claude (`claude-opus-4-8`) klip seçer. Default `groq` (bozulmadı). anthropic SDK kuruldu + requirements'ta.

---

## GÜNCEL DURUM — 2026-06-30

**Repo:** pipeline/.git tek aktif depo, GitHub origin/main ile senkron, çalışma ağacı temiz. (Legacy dış git `_archive`'a alındı.)
**Test:** `python tests/run_all.py` → **11/11 suite, 143/143 check PASS**.
**Öğrenme döngüsü KAPANDI:** `--apply-weights` öğrenilen ağırlıkları skorlamaya uygular (opt-in, gerçek veri yokken no-op). Tek kalan: gerçek upload+analytics verisi.
**Klip seçim kalitesi düzeltildi:** LLM artık pencerelerin tam metnini görüyor (önceden kör). `--legacy-select` ile eskiye dönülür. Gerçek A/B yapısal iyileşmeyi gösterdi.

**learning_engine eklendi (SİMÜLASYON):** `--propose-weights` performans verisinden boyut-ağırlığı + feature lift önerir, weights_vN.json yazar, ASLA uygulamaz. Geri besleme döngüsünün "öğrenme" hesabı artık var; tek kalan onu config'e UYGULAMAK (canlı mod, gerçek veri biriktikten sonra).

**Bu oturumda eklenen (hepsi opt-in, testli, regresyonsuz):**
- #1 yüz takipli crop (`--auto-reframe`)
- #3a karaoke altyazı (`--karaoke`)
- #3b sessizlik-kesme (`--trim-silence`, transkript-öncesi)
- #2 performans geri besleme (upload→video_id+provenance, `--fetch-analytics`→performance_score)
- `fit` çerçeveleme (`--framing fit`) + `format_subtitled` profili (gömülü altyazılı kaynaklar)
- Bug fix: Windows `rename`→`replace`; kapsamlı test runner `tests/run_all.py`

**Sıradaki tek büyük iş:** `learning_engine` — performance_score → klip-seçim ağırlıkları (ROADMAP STEP 3, simulation-first). Geri besleme döngüsünü kapatır.
**Test edilmeyen (kullanıcı tetikler):** gerçek YouTube URL ile Phase 1 E2E; gerçek upload + 1-2 gün sonra `--fetch-analytics` canlı stats.
**Kural:** Her feature sonunda `tests/run_all.py` (büyük çaplı test) çalıştır.

---

## Session 25 — 2026-07-01: Klip Seçiciyi Claude Yapabilme

### İstek (kullanıcı)
- "Groq çok kötü klip seçiyor — Groq yerine sen (Claude) seç." → seçim adımını sağlayıcı-seçmeli yap.

### Yapıldı
- **clip_scoring._call_claude:** Anthropic Python SDK ile `client.messages.create(model=claude-opus-4-8, system=CLIP_SYSTEM_PROMPT, messages=[user])`; text bloklarından JSON parse (`_parse_llm_json`). `client` enjekte edilebilir (test).
- **score_clips:** `provider = config.select_provider`. claude → `_call_claude`; groq → eski yol (aynı). Groq anahtar kontrolü sadece groq'ta. Retry/parse/validation/dedupe/fallback aynı.
- **config/cli/main:** `--select-with {groq,claude}` (default groq) + `PipelineConfig.select_provider` + `anthropic_api_key` (env ANTHROPIC_API_KEY) + `anthropic_model` (default claude-opus-4-8).
- **requirements:** `anthropic>=0.40.0` (kuruldu). CLIP_SYSTEM_PROMPT/pencere yapısı sağlayıcıdan bağımsız — ikisi de aynı zengin prompt'u alır.

### Not / kısıt
- claude-api skill'i okundu (doğru model ID + SDK kullanımı). thinking kullanılmadı (SDK-versiyon uyumu + JSON temizliği için); Opus 4.8 ham hâliyle LLaMA 3.3 70B'den çok üstün.
- Gerçek API çağrısı test edilmedi (anahtar yok) → mock client ile parse/wiring test edildi. **Canlı kullanım için kullanıcı `.env`'e `ANTHROPIC_API_KEY` eklemeli.**

### Test
- `tests/test_claude_select.py` 11/11. Tam matris: **12/12 suite, 154/154 check PASS**.

### Kullanım
- `python main.py <link> --select-with claude`  (Groq default; Claude opt-in)

---

## Session 23 — 2026-06-30: Klip Seçim Kalitesi Düzeltmesi

### Kök neden
- `_build_window_listing` LLM'e her aday pencerenin sadece **baş/son cümle önizlemesini** veriyordu (~80 char). Model pencerelerin **içeriğini görmeden** seçim yapıyordu → kötü klipler.

### Düzeltme (pipeline kırılmadan — JSON sözleşmesi + return tipi aynı)
- **clip_scoring.py:** `_build_window_listing(rich=True)` artık pencerenin **TAM metnini** (≤600 char) gösteriyor. `_opens_mid_thought()` ile cümle-ortası başlayan pencereler "!! starts mid-thought" işaretleniyor. Prompt sertleştirildi (net "REJECT" kuralları, "be HARSH", tam metni oku).
- **Geri dönüş kapısı:** `--legacy-select` / `legacy_select` config → eski önizleme davranışı. Default = yeni (rich).
- Window building, validation, fallback, sort — hepsi değişmedi.

### Gerçek A/B kanıtı (temp/XyU3zRLJ-Xs.mp4, 3.3dk, CPU whisper + 2 Groq çağrısı)
- LEGACY: 2 klip **birbiriyle örtüşüyordu** (128-159 + 146-167), [1] mid-thought başlıyordu, skorlar 30-31 (şişkin).
- RICH: **0-29s açılış klibini buldu** (legacy kaçırmıştı), örtüşmeyi eledi, çeşitli (0/84/146), skorlar 25-29 (ayırt edici).

### Test
- `tests/test_clip_selection.py` 14/14 PASS (mid-thought, tam-metin liste, legacy fallback, prompt, config).
- Tam matris: **10/10 suite, 116/116 check PASS**.

### Not
- Gerçek "kalite" subjektif; A/B yapısal iyileşmeyi gösteriyor (içerik görünürlüğü, örtüşme elenmesi, hook bulma).

### Ek (aynı oturum): örtüşen klip dedupe
- `_overlap_ratio` + `_dedupe_overlapping` (clip_scoring.py): seçim sonrası >%50 örtüşen klipler elenir, yüksek skorlu tutulur. Deterministik, legacy_select'te kapalı. Return tipi/sözleşme aynı.
- Test: test_clip_selection 20/20.

### Ek (aynı oturum): fallback klip kalitesi
- `_fallback_window_score` + yeniden yazılan `_fallback_clip`: model hiç klip seçemezse "en uzun segment" yerine aday pencereler arasından **bilgi-yoğun + cümle-ortası başlamayan** en iyi pencereyi seçer (deterministik, TARGET_WIN'e yakın süre tercih). Last-resort açılış span'i korundu.
- Test: test_clip_selection 25/25.

### Ek (aynı oturum): çok-uzunluklu pencereler
- `_build_windows` artık 15/22/30sn hedeflerinde pencere üretir (düşünce tek boyuta zorlanmaz), dedupe + MAX_WINDOWS=30 cap (prompt bütçesi). Listing metni 450 char/pencere.
- Test: test_clip_selection 30/30. Tam matris: **10/10 suite, 132/132 check PASS**.
- **Klip seçim kalitesi 4 katman tamamlandı:** tam-metin görünürlük + sert prompt/mid-thought + örtüşme dedupe + kaliteli fallback + çok-uzunluklu aday.

---

## Session 22 — 2026-06-30: learning_engine (simülasyon-önce)

### Yapıldı (ROADMAP STEP 3)
- **core/learning_engine.py (yeni, saf, LLM yok):**
  - `compute_dimension_weights(records)` — performansla *birlikte yükselen* boyuta >1.0 çarpan (clamp 0.5–1.5), düz boyuta ~1.0. Az örnekte ({}).
  - `compute_feature_lift(records)` — her feature ON vs OFF ortalama performans farkı (tek grup → None).
  - `propose_weights(records)` — `applied:false`, low_confidence bayrağı (MIN_SAMPLES=3).
  - `save_proposal` — `weights/weights_vN.json`, asla üzerine yazmaz (Rule 4).
- **CLI `--propose-weights`** (erken-çıkış, simülasyon). main'de versiyon path'ten okunur.
- **.gitignore:** `weights/`.

### Disiplin (ROADMAP kuralları)
- Rule 1: gerçek-zamanlı mutasyon YOK; pipeline sonrası, sadece öneri yazar.
- Rule 2: LLM YOK, deterministik.
- Rule 4: versiyonlu, üzerine yazmaz.
- **Hiçbir şey weights'i geri okumuyor** → şu an saf gözlem/simülasyon.

### Bug fix
- main: `proposal['version']` KeyError (save_proposal versiyonu yerel kopyaya ekliyordu) → versiyon `path.stem`'den okunuyor.

### Test
- `tests/test_learning.py` 12/12 PASS. Tam matris: **9/9 suite, 102/102 check PASS**.
- Canlı komut: `python main.py --propose-weights` (0 örnek → low_confidence nötr öneri, güvenli).

### Sıradaki (döngüyü kapatmak için son adım)
1. Gerçek veri biriktir: `--upload` → 1-2 gün → `--fetch-analytics` → `--propose-weights`.
2. CANLI mod: bir weights_vN proposal'ını ControlArbiter scoring_bias'a bağla (ROADMAP STEP 5, ayrı + dikkatli; influence ≤30%, DAG/AOR/Contract ezilmez).

---

## Session 24 — 2026-06-30: Öğrenme Döngüsü Kapatıldı (STEP 5)

### Yapıldı
- **learning_engine.load_latest_weights(dir):** en yüksek versiyonlu, low_confidence OLMAYAN proposal'ın dimension_weights'ini döndürür ({} yoksa → uygulama no-op).
- **clip_scoring._weighted_total(scores, dim_weights):** ağırlık yoksa düz toplam (davranış aynı); varsa `score * weight` (ağırlıklar 0.5–1.5 clamp'li). score_clips'e `dim_weights` param eklendi; score_total bundan hesaplanıyor.
- **phase1:** `--apply-weights` açıkken latest weights yüklenip score_clips'e geçilir. Güvenilir öneri yoksa eşit ağırlık (no-op). Hata → eşit ağırlık.
- **config/cli/main:** `--apply-weights` + `PipelineConfig.apply_weights` (default False).

### Disiplin
- Opt-in, default kapalı. Ağırlıklar sınırlı → skorlamayı yeniden sıralar ama domine etmez. DAG/AOR/Contract'a DOKUNMAZ (sadece LLM-skorlu kliplerin sıralaması). Gerçek veri yoksa otomatik no-op.

### Test
- `tests/test_apply_weights.py` 11/11 (ağırlıklı toplam, sentetik ağırlıkla sıralama flip, latest-weights versiyon/güven seçimi, config).
- Tam matris: **11/11 suite, 143/143 check PASS**.

### Döngü artık tam
download→…→**score (öğrenilen ağırlık)**→render→upload→**video_id+provenance**→**fetch-analytics→performance_score**→**propose-weights**→**apply-weights**→score…
- **Kalan tek eksik: GERÇEK VERİ.** Birkaç gerçek upload + birikmiş analytics olunca propose confident olur, apply anlamlı çalışır.

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
| **10** | **2026-06-21** | **Git remote + CLAUDE/CHANGELOG + SESSION.md işlevi** | **✅** |
| **11** | **2026-06-26** | **Pipeline refactor: main.py → 4 modül** | **✅** |
| **12** | **2026-06-26** | **Feature registry modüllere dağıtıldı, CLAUDE.md güncellendi** | **✅** |
| **13** | **2026-06-30** | **Stabilizasyon: legacy dış git deposu arşivlendi, çalışma ağacı temizlendi** | **✅** |
| **14** | **2026-06-30** | **Workflow gap analizi (Opus Clip/OSS kıyas) + #1 yüz takipli reframe eklendi** | **✅** |
| **15** | **2026-06-30** | **#8 WORKFLOW.md güncellendi + #3a karaoke altyazı eklendi** | **✅** |
| **16** | **2026-06-30** | **#3b sessizlik-kesme (transkript-öncesi, senkron-güvenli)** | **✅** |
| **17** | **2026-06-30** | **Gerçek-yürütme entegrasyon testi (ffmpeg E2E, 3 özellik doğrulandı)** | **✅** |
| **18** | **2026-06-30** | **#2 Performans geri besleme katmanı (video_id + analytics + score)** | **✅** |
| **19** | **2026-06-30** | **Canlı render testi (karaoke) + Windows rename->replace fix + test runner** | **✅** |
| **20** | **2026-06-30** | **'fit' framing (tam genişlik + bulanık dolgu) — gömülü altyazı kesilmesin** | **✅** |
| **21** | **2026-06-30** | **format_subtitled profili (fit + altyazı kapalı) — kaynak türüne göre otomatik** | **✅** |

---

## Session 10 — 2026-06-21: Git Remote + File Structure + SESSION.md Contract

### What We Did This Session

**1. GitHub repo kurulumu**
- Pipeline dizininde bağımsız git repo başlatıldı (`git init`)
- Remote eklendi: `halilkirmizi/-kulturel-ai-agent-pipeline.git`
- `.gitignore` oluşturuldu: `temp/`, `logs/`, `downloads/`, `shorts_output/`, `memory_store.json`, `.env`, `client_secret.json`, `*.pickle`, `.Rhistory`
- `CHANGELOG.md` oluşturuldu (Dory format — append-only, satır başına bir karar)
- `CLAUDE.md` oluşturuldu (kısa kurallar — mimari, priority, hassas dosyalar)
- İlk commit: 48 dosya, 8523 satır → `main` branch'e push
- Vault'un `game-developping.git` remote'una dokunulmadı

**2. Eski dosyaların değerlendirilmesi**
- `obsidian_bridge/` → **kalsın**, kullanıcı sonra kullanmak istiyor
- `MEMORY/` (ALWAYS.md, PROJECT.md, ARCHIVE/INDEX.md) → elle yazılmış eski notlar, `CLAUDE.md` aynı işi görüyor
- `SESSION.md`, `REFACTOR_SEQUENCE.md`, `STATE_CONTRACT.md` okundu, ne işe yaradıkları açıklandı
- `SESSION.md`'nin gerçek işlevi belirlendi: **konuşma geçmişi yedeği**

**3. SESSION.md Contract (Kesin Kural)**
- **Her session başında** `SESSION.md` oku → nerede kaldığını bil
- **Her session sonunda** `SESSION.md` güncelle → kararlar, bağlam, yapılanlar kaybolmasın
- `CHANGELOG.md` = ne değişti (git log)
- `SESSION.md` = konuşma geçmişi yedeği (kararlar + bağlam)
- `CLAUDE.md` = sabit kurallar (dokunma, sadece değişiklik gerekirse güncelle)

**4. Eski dosyaların derinlemesine analizi**
- `STATE_CONTRACT.md` — küçümsendi, hatalıydım. Kullanıcı düzeltti: Bu dosya **resmî referans dokümanı**. Runtime'da hata alınınca başvurulacak kaynak. Kod değişince güncellenmeli. Önemli.
- `MEMORY/ALWAYS.md` — production constraint'ler, content strategy, teknik kurallar. `CLAUDE.md`'de olmayan bilgiler içeriyor (9:16 framing, timing kuralları, content strategist modu).
- `MEMORY/PROJECT.md` — tamamen güncelliğini yitirmiş next steps (pip install, .env, client_secret — hepsi yapıldı).
- `MEMORY/ARCHIVE/INDEX.md` — eski session indeksi + terk edilmiş özellikler listesi (Temporal IR, easing curves, Format2 brainrot).

**5. Memory Architecture Proposal**
- Kullanıcının orijinal tasarımı: short-term (ALWAYS.md) / working (PROJECT.md) / long-term (ARCHIVE/) katmanlı sistem
- Mevcut sistem (CLAUDE.md + SESSION.md + CHANGELOG.md) ile karşılaştırıldı
- Kod değişikliği gerektirmediği tespit edildi (MEMORY/ dosyaları sadece Claude içindir, pipeline Python kodları okumaz)
- `design/memory_architecture_proposal.md` yazıldı — projeyi bilmeyen bir yazılım mühendisinin değerlendirmesi için
- **Karar:** Henüz uygulanmadı. 2-3 session sonra değerlendirilecek.

### Current Project State (Özet)

| Modül | Durum |
|---|---|
| `core/artifact_registry.py` | 17 artifact type, single-writer enforcement, freeze, save/load |
| `core/artifact_auditor.py` | 3 mod (bootstrap/drift/verify), ghost/missing/shadow detection |
| `core/memory_writer.py` | MemoryStore (50/cat, 30d compaction), SemanticSignalFilter, CompressionLayer |
| `core/memory_influence.py` | MemoryInfluenceEngine, RuntimeConfigPatch, enforce_guards() |
| `core/control_arbiter.py` | 5-layer priority resolution, ResolvedValue provenance |
| `core/steptracker.py` | UUID isolation, heuristic_adjustments(), apply_influence() |
| `core/config.py` | HookConfig hook_overlay'dan okur, SubscribeConfig fontcolor/bordercolor/borderw |
| `ingest/downloader.py` | Deterministic video ID binding (no glob+mtime) |
| `editing/overlays.py` | Config-driven subscribe overlay (fontcolor/bordercolor/borderw) |
| `formats/` | format1.json (general), format_football_interview.json (football interview) |
| `upload/youtube.py` | OAuth v3, quota tracking |
| Git | **Pipeline bağımsız repo**, GitHub'da, 2 commit |
| Test | Cross-run contamination = NONE, ControlArbiter 7/7, Memory 5/5 |
| YouTube | İlk upload yapıldı (Arjantin WC interview, "Eternal Number 10") |
| Cleanup | temp/ logs/ execution_trace/ hepsi temiz, memory_store sıfırlandı |

**Not:** AOR, MemoryWriter, MemoryInfluence, ControlArbiter, auditor gibi büyük modüller önceki session'larda yazıldı (Session 9 sonrası). Bu dosyaların kodları duruyor, testleri geçiyor.

### Key Decisions (Tümü)

1. **SESSION.md = conversation history backup.** Üç dosya sistemi: CHANGELOG.md (ne değişti), SESSION.md (kararlar+bağlam), CLAUDE.md (kurallar)
2. Memory promotion ≥1 artifact reference (artifact_registry hariç)
3. Compression: `signature|semantic_class` — lifecycle_noise semantic ile merge edilmez
4. Semantic filter path pattern kullanır: `temp/` prefix → lifecycle_noise
5. AOR atomic write: `.tmp.json` + rename
6. ControlArbiter priority: DAG/Contract(1) > AOR(2) > MemoryInfluence(3) > StepTracker(4) > ClipScoring(5)
7. Tüm runtime config ControlArbiter'dan geçer — direkt patch yok
8. `--mode observation_only` (default): memory influence kapalı; `adaptive_mode`: açık
9. Downloader: `info["id"]` ile çözüm, glob+mtime kullanılmaz
10. Hook config `hook_overlay` JSON bölümünden okur (`captions` değil)
11. Subscribe overlay config-driven (fontcolor/bordercolor/borderw hardcoded değil)
12. `--no-captions` CLI flag'tir, format/config'te kalıcı değildir
13. Kullanıcı kendi intro sesini kaydeder (mikrofon izinsiz açılmaz)
14. `obsidian_bridge/` kalsın — kullanıcı sonra kullanacak
15. Memory influence DAG/AOR/Contract kurallarını asla ezemez

### Next Steps

1. Yeni video pipeline'dan geçir → memory_store dolsun
2. Dolu memory_store ile adaptive_mode test et
3. `obsidian_bridge/` kullanımı — kullanıcı istediğinde

### Known Issues

- LSP errors: downloader.py (yt-dlp type stub), clip_scoring.py (Optional[str] → str) — önceden var, bizden değil
- Windows `tempfile.mkstemp` PermissionError — pipeline shorts_output/ kullanır, etkilenmez
- ASS caption'larda Arial font hala hardcoded

---

## Session 11 — 2026-06-26: Pipeline Refactor (main.py → 4 modül)

### Neden main.py bölündü?
- 763 satır, her şey tek dosyada (download, transcribe, score, crop, compose, upload, CLI)
- Bir şeyi değiştirmek her şeyi bozuyor
- Test yazmak imkansızdı

### Ne yapıldı?
- `core/phase1.py` — download → transcribe → score → crop orchestration
- `core/phase2.py` — audio enhance → captions → compose orchestration
- `core/upload.py` — YouTube upload orchestration
- `core/cli.py` — Arg parsing
- `main.py` — Sadece orchestration (~140 satır)

### Test sonuçları
- Unit test: 10/10 PASS
- E2E: Phase 1 (2 clip) + Phase 2 (final.mp4) başarılı
- Stres test: 3/3 PASS (aynı video 2x, kısa video, geçersiz API key)
- AOR: 0 duplicate writer

### Dosya yapısı
```
pipeline/
├── main.py (~140 satır, orchestrator)
├── core/
│   ├── phase1.py (~255 satır)
│   ├── phase2.py (~212 satır)
│   ├── upload.py (~101 satır)
│   ├── cli.py (~45 satır)
│   └── ...
├── tests/
│   ├── test_refactor.py
│   └── REFACTOR_TEST_REPORT_20260626.md
```

---

## Session 12 — 2026-06-26: Feature Registry + CLAUDE.md Güncelleme

### Feature Registry Modüllere Dağıtıldı
- Önce: Tüm feature'lar main.py'de declare ediliyordu
- Sonra: Her modül kendi feature'larını declare ediyor
- main.py'de sadece step_tracker kaldı

### CLAUDE.md Güncellendi
- Multi-Part Video Workflow (Altın Kural): 30dk parçalama, kullanıcı onayı
- Commit Kuralı: Her session sonunda commit, 12 mesajda bir kontrol

### Bilinen Sorunlar
- Memory Influence: Kod var ama adaptive_mode henüz test edilmedi
- Graph store path: Düzeltildi ama obsidian bridge hâlâ entegre değil
- 12 mesaj kuralı: Bu session'da kaçırıldı (yaklaşık 30 mesaj oldu)

### Next Steps
1. Memory write-back test (adaptive_mode)
2. Workflow dosyasını güncelle (9:16 crop, yeni yapı)
3. AOR owner path'leri otomatikleştir
4. Joe Rogan video testi (multi-part workflow)

---

## Session 13 — 2026-06-30: Stabilizasyon

### Sorun
- `kulturel AI agent/` klasöründe **iki git deposu iç içeydi**:
  - `pipeline/.git` → gerçek, güncel repo (branch `main`, GitHub remote'lu, senkron)
  - `kulturel AI agent/.git` → eski "GPU pipeline" deposu (branch `master`, remote YOK), aynı dosyaları çift izliyordu
- Bu yüzden klasörde `git status` yanıltıcıydı: pipeline tertemiz olmasına rağmen "her şey değişmiş" görünüyordu.

### Ne yapıldı
1. **Legacy dış depo arşivlendi** (silinmedi): `kulturel AI agent/.git` → `01_Projects/_archive/legacy_kulturel_outer_git_20260630/git_folder`. Geri alınabilir. Boyut 277K, master, remote yok → kayıp riski yok.
2. **Doğrulama:** `kulturel AI agent/` artık üst vault deposuna ait (`rev-parse --show-toplevel` → SecondBrain-vault). İç pipeline reposu bağımsız ve sağlam.
3. **Kaydedilmemiş tek değişiklik commit'lendi:** `editing/render_core.py` — crop komutuna 2 satır açıklama yorumu (mantık değişikliği yok). Commit `a85a55e`.
4. **GitHub'a push'landı** → `pipeline` reposu origin/main ile tam senkron, çalışma ağacı temiz.

### Sonuç
- Tek aktif depo: `pipeline/.git` (temiz + yedekli).
- Kod/test durumu değişmedi (Session 11/12'deki yeşil durum korunuyor).

### Next Steps (devam, Session 12'den taşındı)
1. Memory write-back test (adaptive_mode) — hâlâ test edilmemiş en büyük risk
2. `_archive`'daki legacy git'i birkaç hafta sorun çıkmazsa tamamen sil

---

## Session 14 — 2026-06-30: Workflow Gap Analizi + Yüz Takipli Reframe

### Gap analizi (Opus Clip + SamurAIGPT/OpenShorts/ShortGPT kıyası)
Tespit edilen eksikler (öncelik sırasıyla):
1. **Yüz/konu takipli crop** (statik merkez-crop konuşanı kesiyordu) ← BU SESSION YAPILDI
2. YouTube Analytics geri beslemesi yok → self-learning katmanının zemini eksik
3. Animasyonlu altyazı (düz drawtext) + sessizlik/dolgu kelime kesme yok
4. Sadece YouTube + anında yükleme (scheduler/çoklu platform yok)
5. SEO başlık/açıklama/hashtag otomasyonu zayıf; b-roll yok
6. `WORKFLOW.md` eski dosya yapısını anlatıyor (güncellenmeli)

### Yapıldı: #1 Subject-aware reframe
- **Yeni modül:** `analysis/reframe.py`
  - `compute_crop_x()` — saf geometri (test edilebilir)
  - `detect_crop_x()` — OpenCV Haar cascade, klipten N kare örnekler, dominant yüzün medyan x'ini bulur. cv2 yok / yüz yok / okuma hatası → `None` (merkez-crop'a düşer). Pipeline'ı asla bozmaz.
- **render_core.build_crop_command** — opsiyonel `crop_x` parametresi aldı (None = eski merkez davranış, bit-bit aynı). render_core saf kaldı (video okumaz).
- **Opt-in:** `--auto-reframe` CLI flag, `PipelineConfig.auto_reframe` (default False). Football content-type'ı kendi framing'ini korur.
- **Bağımlılık:** `opencv-python-headless>=4.8.0` (requirements.txt + kuruldu).
- **Test:** `tests/test_reframe.py` 10/10 PASS. Regresyon: `tests/test_refactor.py` 10/10 PASS.

### Bilinen kısıt
- Gerçek videoyla uçtan uca (E2E) çalıştırma yapılmadı — sadece birim test + komut doğrulama. Bir sonraki gerçek run'da `--auto-reframe` ile görsel doğrulama yapılmalı.
- MVP statik per-clip offset (klip boyunca tek x). Opus Clip tarzı yumuşak hareket-takibi (dynamic pan) bir sonraki iterasyon.

### Next Steps
1. `--auto-reframe` ile gerçek video E2E + görsel kontrol
2. Sıradaki gap: #2 (Analytics feedback) veya #3 (animasyonlu altyazı)

---

## Session 15 — 2026-06-30: WORKFLOW.md güncelleme + Karaoke Altyazı

### #8 — WORKFLOW.md güncellendi
- Eski (Session 11 öncesi) dosya yapısını anlatıyordu (renderer.py vb. yok).
- Gerçek modül yapısına göre yenilendi: phase1/phase2/upload/cli + analysis/reframe, gerçek satır sayıları, reframe akışı + CLI örnekleri.

### #3a — Karaoke (animasyonlu) altyazı
- **captions.py:** `_karaoke_text()` (kelime başına `\k` etiketi, süreyi eşit dağıtır, yuvarlama artığı son kelimeye), `_style_line()` (karaoke: Primary=highlight/sarı, Secondary=beyaz). `write_ass(... karaoke=, highlight_color=)`.
- **Opt-in:** `--karaoke` CLI + `CaptionConfig.karaoke` (default False). Statik mod **bit-bit aynı** (regresyon yok).
- **Kelime zamanlaması notu:** state.json'da word-level timestamp yok; chunk süresi kelimelere eşit bölünerek yaklaşık karaoke sweep yapılıyor. Gerçek word-level için transcription'ın word_timestamps çıktısı ileride bağlanabilir.
- **Test:** `tests/test_captions_karaoke.py` 9/9 PASS. Regresyon: reframe 10/10, refactor 10/10.

### Yapılmadı (bilinçli ertelendi): #3b Sessizlik-kesme
- **Neden:** Phase 2 klibi yeniden transkript ETMİYOR; altyazı zamanlamasını Phase 1 transkriptinden alıyor. Klip seviyesinde sessizlik kesme → altyazı desync. Güvenli yer **transkriptten önce** (Phase 1 download sonrası kaynak medyayı kırpmak), böylece tüm timestamp'ler doğru kurulur. Ayrı, daha büyük değişiklik — sonraki oturuma.

### Next Steps
1. Gerçek video E2E: `--auto-reframe --karaoke` görsel kontrol
2. #3b sessizlik-kesme (transkript-öncesi tasarımıyla) VEYA #2 Analytics feedback

---

## Session 16 — 2026-06-30: Sessizlik-Kesme (#3b)

### Tasarım (senkron-güvenli)
- Sessizlik **transkriptten ÖNCE**, Phase 1'de indirme sonrası kaynak medyadan kesilir. Whisper kesilmiş medyada çalıştığı için tüm downstream timestamp'ler (scoring/crop/caption) doğru kurulur → **altyazı desync YOK**. (Phase 2 klibi yeniden transkript etmiyor; çözüm bu yüzden Phase 1'de.)

### Kod
- **Yeni `editing/silence.py` (saf):** `build_silencedetect_command`, `parse_silencedetect`, `compute_keep_segments` (sessizlikleri pad ile küçültüp konuşma aralıklarına çevirir), `kept_fraction`, `build_trim_command` (tek-pass select/concat + setpts/asetpts, A/V senkron).
- **ffmpeg_builder:** `run_silencedetect()` — stderr yakalayan tek subprocess (gateway kuralı korundu).
- **phase1:** indirme→[sessizlik kes]→transkript. Hata/boş/az-fayda (kept ≥ %97) → orijinalle devam. AOR `trimmed_video` write + `_assert_valid_video`.
- **Opt-in:** `--trim-silence` + `PipelineConfig.trim_silence` (default False). Eşikler config'ten (`silence.noise_db`/`min_dur`).

### Test
- `tests/test_silence.py` 16/16 PASS (parse, keep-segment matematiği, pad davranışı, komut üretimi).
- Regresyon: refactor 10/10, reframe 10/10, karaoke 9/9 — hepsi PASS.

### Bilinen kısıt
- Gerçek video E2E yapılmadı (subprocess yolu); saf mantık tam test edildi. `--trim-silence` ile bir gerçek run'da süre/senkron gözle doğrulanmalı.
- Uzun videoda tüm kaynağı yeniden encode eder (yavaş olabilir); opt-in olduğu için kabul.

### Next Steps
1. Gerçek video E2E: `--auto-reframe --karaoke --trim-silence` birlikte görsel kontrol
2. #2 Analytics feedback (öğrenen sistemin zemini) — sıradaki büyük gap

---

## Session 17 — 2026-06-30: Gerçek-Yürütme Entegrasyon Testi

### Ne yapıldı
- `tests/test_integration_ffmpeg.py`: sentetik 6sn fixture üretir (ton/SESSİZ/ton, 1280x720) ve **gerçek ffmpeg/cv2** ile yeni 3 özelliği uçtan uca çalıştırır. YouTube/Groq/GPU gerektirmez.
- Sonuç **8/8 PASS**:
  - Sessizlik: kurulan boşluk `[1.999, 4.000]` tespit edildi, trim 6.0sn → 4.11sn ✅
  - Crop: `crop_x`'li + varsayılan → çıktı 1080x1920 (cv2 ile ölçüldü) ✅
  - Karaoke: ASS altyazı gerçekten gömüldü, 3.00sn çıktı ✅
  - Reframe: cv2 yolu çalıştı, yüz yok → güvenli None ✅
- **"Subprocess yolu E2E test edilmedi" uyarısı kapandı** (rendering tarafı için).

### fixture notu (gotcha)
- lavfi `aevalsrc` ifadesindeki virgüller ffmpeg'de filtergraph ayırıcısı; Python argv'de `\,` ile escape şart (`lt(mod(t\,4)\,2)`).

### Hâlâ test edilmeyen (kasıtlı)
- yt-dlp indirme, Whisper doğruluğu, Groq scoring, YouTube upload — gerçek URL + .env gerektirir. Bunlar rendering değil, ayrı entegrasyonlar.

### Test matrisi (tümü PASS)
refactor 10/10 · reframe 10/10 · karaoke 9/9 · silence 16/16 · integration 8/8

### Next Steps
1. Tam gerçek video E2E (kullanıcı URL + .env ile tetikler)
2. #2 Analytics feedback — sıradaki büyük gap

---

## Session 18 — 2026-06-30: #2 Performans Geri Besleme Katmanı

### Sorun
- `upload_video` YouTube'dan dönen `video_id`'yi alıp atıyordu → hangi videonun nasıl performans gösterdiği geri bağlanamıyordu. Öğrenen sistemin **zemini** yoktu.

### Yapıldı (zemin + analytics, learning_engine HENÜZ değil)
- **upload zinciri:** `upload_video`/`upload_with_retry` artık `bool` yerine `Optional[str]` (video_id) döner. Truthiness korundu (`if vid:`), geriye uyumlu. `core/upload.py` başarılı upload'ta `state["youtube_video_id"]` yazar + provenance kaydı oluşturur.
- **core/performance.py (yeni, saf):** `compute_performance_score(stats)` (deterministik: log-ölçekli reach %60 + engagement %40, 0..1 clamp), `build_record(video_id, state, features)` (hook + LLM skor + 4-boyut + hangi flag'ler açıktı), `PerformanceStore` (video_id keyed, atomic save, pending/attach/summary).
- **analysis/youtube_stats.py (yeni, ince):** `fetch_stats(video_ids, service=None)` Data API `videos.list(part=statistics)` → views/likes/comments. Kimlik yok/hata → `{}` (graceful). `service` enjekte edilebilir (test için). `parse_stats_response` saf.
- **CLI `--fetch-analytics`:** performance_store'daki pending video'ların stats'ını çeker, score hesaplar, kaydeder, özet basar (erken-çıkış komut).
- **.gitignore:** `performance_store.json` (yerel veri).

### Test
- `tests/test_performance.py` 19/19 PASS (scoring monotonluk/clamp, store round-trip, mock servisle stats parse + graceful error).
- Regresyon: refactor 10/10, reframe 10/10, karaoke 9/9, silence 16/16, integration 8/8 — hepsi PASS.

### Bilinen kısıt / sonraki adım
- Gerçek API çağrısı kimlik gerektirdiği için mock'landı; canlı stats için kullanıcı `--upload` ile video yükleyip 1-2 gün sonra `--fetch-analytics` çalıştırmalı.
- **learning_engine HENÜZ yok:** performance_score üretiliyor ama henüz weight güncellemesine bağlı değil. ROADMAP STEP 3/5 = bu skoru config'e geri besleyen learning loop. Sıradaki büyük iş.
- YouTube **retention** (izlenme süresi) için ayrı `yt-analytics.readonly` OAuth scope gerekir; şu an sadece Data API statistics (views/likes/comments).

### Next Steps
1. learning_engine: performance_score → weight ayarı (ROADMAP STEP 3 simulation-first)
2. Gerçek upload + `--fetch-analytics` canlı doğrulama

---

## Session 19 — 2026-06-30: Canlı Render Testi + rename->replace Fix + Test Runner

### Test runner (kullanıcı kuralı)
- Kullanıcı: "her feature'dan sonra büyük çaplı test yap." → `tests/run_all.py` eklendi (tüm test_*.py suite'lerini koşar, konsolide özet). Kural hafızaya da yazıldı.

### Canlı render testi (karaoke)
- Mevcut gerçek bir klip (`short_20260626_203058/clip_1`) kopyalanıp Phase 2 `--resume --karaoke --no-gpu` ile çalıştırıldı (URL/Groq/upload gerekmedi).
- Sonuç: final.mp4 1080x1920 18.69s, captions.ass'te 50 `\k` etiketi, stil sarı/beyaz → karaoke gerçekten render edildi. ✅

### Kullanıcı geri bildirimi (ÖNEMLİ ürün notu)
- Kaynak videoda ZATEN gömülü (hardcoded) altyazı varsa, bizim ASS altyazı katmanımız ÇİFT altyazı yaratıyor (bizimki üstte, gömülü altta) → kötü görünüyor.
- Bu video için `--no-captions` ile yeniden render edildi → tek altyazı (gömülü). Kullanıcı onayladı.
- **İleride değerlendir:** kaynakta gömülü altyazı tespiti veya format/source başına "captions kapalı" varsayılanı. Şimdilik manuel `--no-captions`.

### Bug fix: Windows rename -> replace
- `final.tmp.mp4 -> final.mp4` yeniden render'da WinError 183 ("dosya zaten var"). Windows `Path.rename` üzerine yazmaz; `Path.replace` yazar.
- Düzeltildi: `core/phase1.py` (clip.mp4), `core/phase2.py` (final.mp4). İlk run'da fark yok; yeniden render artık çalışıyor.

### Test (kural gereği tam matris)
- `python tests/run_all.py` → 6/6 suite, 72/72 check PASS.

### Next Steps
1. learning_engine (performance_score → weight, simulation-first)
2. Gerçek YouTube URL ile Phase 1 E2E (`--auto-reframe --trim-silence`)

---

## Session 20 — 2026-06-30: 'fit' framing (gömülü altyazı kesilmesini önle)

### Sorun (kullanıcı)
- Kaynak yatay (1920x1080), altyazı tam genişlikte gömülü. 9:16 ortadan crop sağ/sol kenarları (altyazının baş/son kısmını) kesiyor → altyazının bir kısmı görünmüyor.

### Çözüm: 'fit' framing modu
- **render_core._build_fit_command:** `[0:v]split` → bg (scale increase + crop 1080x1920 + boxblur) + fg (scale decrease, tam kare sığar) → overlay merkez. filter_complex form, `-map 0:a?`.
- Tam genişlik korunur → gömülü altyazı tam görünür. Standart "blurred background" shorts görünümü.
- **Opt-in:** `--framing {crop,fit}` (default crop) + `PipelineConfig.framing` + format JSON `clip.framing`. Football kendi crop'unu korur.

### Doğrulama
- `tests/test_framing.py` 11/11 PASS (komut şekli + config + gerçek ffmpeg fit render 1080x1920).
- Tam matris: `tests/run_all.py` **7/7 suite, 83/83 check PASS**.
- **Canlı kanıt:** orijinal kaynak `temp/XyU3zRLJ-Xs.mp4` (1920x1080) segment 147.94–166.62 fit ile render edildi → `clip_FIT_demo.mp4` (1080x1920), kullanıcıya gösterildi.

### Açık karar
- fit dolgu stili şimdilik bulanık-bg. Alternatif (siyah bar) istenirse tek satır değişiklik. Kullanıcı fit demosunu izliyor.

---

## Session 21 — 2026-06-30: format_subtitled profili (kaynak türüne göre otomatik)

### İstek (kullanıcı)
- "Altyazısı gömülü videoları bu şekilde (fit + altyazısız) editle; diğerlerini değil." → her seferinde flag yazmak yerine kaynak türüne göre profil.

### Çözüm
- **formats/format_subtitled.json (yeni):** `clip.framing="fit"` + `captions.enabled=false`. Gömülü altyazılı yatay kaynaklar için.
- **config.py:** `captions.enabled` artık format JSON'dan da okunuyor (`cap_raw.get("enabled", True) AND not --no-captions`). Önceden sadece `--no-captions` kontrol ediyordu.
- **Kullanım:**
  - Gömülü altyazılı kaynak → `python main.py <link> --format format_subtitled` (fit + bizim altyazı kapalı, çift altyazı yok)
  - Normal video → default `format1` (crop + karaoke/altyazı)

### Doğrulama
- `tests/test_formats.py` 7/7 PASS (default değişmedi; subtitled profili fit+captions-off; flag etkileşimleri).
- Tam matris: **8/8 suite, 90/90 check PASS**.

### Next Steps
1. learning_engine (performance_score → weight, simulation-first)
2. Gerçek YouTube URL ile Phase 1 E2E (`--format format_subtitled` veya `--auto-reframe --trim-silence`)
