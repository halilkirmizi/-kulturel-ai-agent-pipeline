# Pipeline Session Log

> **Read this file first at the start of each session.** This is the conversation history backup.
> Links: `CHANGELOG.md` (what changed) · `CLAUDE.md` (rules)

---

## GÜNCEL DURUM — 2026-07-14 (Analytics API teşhis katmanı + İngiltere-Arjantin teaser + çapraz-paylaşım telif dersleri)

**1) YENİ ÖZELLİK: Analytics API teşhis katmanı (commit `a4dbd8b`, push bekliyor).**
- `--fetch-analytics` artık Data API stats'ın üstüne **retention + trafik-kaynağı** çekiyor (youtubeAnalytics v2 `reports.query`) ve video-başı deterministik teşhis basıyor: `retention_problem` / `good_retention_low_reach` / `healthy_feed_distribution` / `distributed_no_feed` / `low_reach` / `no_data`.
- Mimari: `upload/youtube.py` → `yt-analytics.readonly` scope + `_get_credentials()`/`get_analytics_service()` (v2). `analysis/youtube_analytics.py` (yeni, saf+mock-test). `core/performance.py` → `attach_analytics`/`analytics_pending_ids`/`summary.analyzed`. `main.py` → teşhis tablosu. Test: yeni `test_youtube_analytics.py` 25 check → **19/19 suite, 283/283 PASS**.
- **DÜRÜST KISIT:** thumbnail impressions + CTR public Analytics API'de YOK (Studio-only). Onun yerine `averageViewPercentage` (retention) + `insightTrafficSourceType` (SHORTS feed) — flag sorusu için zaten daha kesin.

**2) KANAL TEŞHİSİ (Studio + analytics): kanal FLAGLI DEĞİL, futbol yanlış kitle.**
- Kanıt: eski Messi Short **1.291 izlenme / 48 gösterim** (feed'den geldi) → shadowban olsa imkansız. Toplam 1.212 gösterim/28g → dağıtım aktif.
- Futbol HABER Short'ları kanalın **EN KÖTÜ** içeriği (Spain/France ~5 view, %0 CTR). Kanal `truth`/CIA izleyicisiyle etiketli → futbol yanlış kitleye düşüyor.
- **Kanalın kazanan damarı: CIA/whistleblower/truth** (CTR %3.9-5.3, futbolun 2-3 katı). Gelecek yön oraya.

**3) İngiltere-Arjantin "...YOU." teaser (elle build, scratchpad — pipeline'a girmedi).**
- Konsept: İngiltere kutlama → gerilim/kararma "YOUR NEXT OPPONENT IS..." → HARD CUT + drop → Messi "...YOU." → Arjantin tehdidi (aura + WORLD CHAMPIONS kartı) → end card. 22sn.
- **Telif-güvenli görsel:** yeni Commons CC fetcher (lisans-filtreli, soyadı-zorunlu, top-bias crop) → Bellingham kırmızı #10, Messi Arjantin dik-bakış + kollar-havada aura, Declan Rice aksiyon (hepsi CC BY / CC BY-SA 2026 maçları). **Broadcast klip ASLA.**
- **Kartlar:** PIL ile premium (gradient, takım renkleri, gold VS, çizili yıldızlar). NOT: **CC "Messi kupa kaldırma" fotosu YOK** (hepsi Getty) → yerine "WORLD CHAMPIONS · ARGENTINA 2022" kartı + Messi formasındaki 2022 arması.
- **Ses:** ffmpeg ile sıfırdan trailer ses-tasarımı (riser + BRAAAM impact + drone + pulse), drop'a senkron, %100 telifsiz. + sessiz sürüm.
- Dosyalar: `temp/teaser_v6_FINAL.mp4` (sesli/YouTube) + `temp/teaser_v6_SILENT_tiktok.mp4`.

**4) ÇAPRAZ-PAYLAŞIM TELİF DERSLERİ (önemli):**
- "Your Next Opponent Is You" = Xundr'ın Spotify parçası = **telifli.** TikTok/IG'de uygulama-içi ses lisanslı; YouTube'da Content ID claim = demonetize.
- **Her platforma temiz kaynaktan AYRI yükle + sesi o platformun uygulamasından ekle.** TikTok'tan indirip IG'ye atma → watermark + telif → IG reel'i gizler ("content may be hidden", sadece sahibi görür).
- IG **İşletme hesabı** müzik kütüphanesini kısıtlar → Kişisel hesap gerekir. YouTube'da sonradan trend-ses eklenmez (sessiz yüklersen sessiz kalır).
- Uzun açıklama viral kaldıracı DEĞİL (retention öyle); tek meşru faydası SEO/arama + CC atıf zorunluluğu.

**5) AI-VIDEO HYBRID TEASER workflow (yeni, güçlü — elle build, scratchpad).**
- Kullanıcı gerçek Bellingham/Messi YÜZÜ istedi. Çözüm zinciri: **text-to-video benzemez + ünlü filtresi** → **image-to-video** (gerçek fotoğrafı başlangıç karesi yap, AI hareketlendirir, yüz gerçek kalır). **GPT Image / Firefly gerçek ünlü üretmez** (Firefly kurumsal öğrenci hesabında admin kapatmış → "accès" hatası).
- **Ücretsiz araç taktiği:** günlük-kredi yenilenenleri dağıt (Kling / Hailuo / Pixverse / Vidu). Kling kredisi bitince Hailuo'ya geçildi. Kling free = 720p + watermark; Hailuo benzer. **Watermark'ı hafif zoom-crop ile kırp** (scale 1210:2150 → crop 1080:1920) + 1080p'ye upscale.
- **Sonuç:** Bellingham 2× klip (Kling, kutlama) + Messi smirk klibi (Hailuo, image-to-video ← `temp/messi_portrait.jpg`) → pipeline'da birleştirildi: darken/flash geçiş + trailer sesi (drop 8.4s) + **PIL bayrak end card** (İngiltere St George + Arjantin güneşli, çizildi = telifsiz). Dosya: `temp/teaser_AIVIDEO_ENG_ARG.mp4` (+SILENT).
- **CC foto sınırı doğrulandı:** Openverse (Flickr+tüm CC) = tüm serbest internette ~2-3 Yamal fotosu, hepsi Wikimedia. İkonik anlar (Messi kupa) hep Getty → CC yok. Foto Content-ID taranmaz (still), riski müzik/videodan düşük → kullanıcı isterse press foto SAĞLAR (ben Getty indirmem).
- Ayrıca ESP-FRA teaser (`temp/teaser_ESP_FRA_*`): Yamal+Pedri+Rodri / Mbappé reveal / bayraklı end card, ara kart yok.

**6) TEASER TERCİHLERİ (kullanıcı onayı — bir sonraki sefer uygula):**
- **Reveal stili:** Mbappé "**villain / kırmızı-lazer göz**" klibi (Magic Hour image-to-video, `output.mp4`) → kullanıcı BEĞENDİ. Reveal dramatik/meme olsun.
- **Kesme:** kırmızı flash İSTEMİYOR ("alakasız"). Temiz hard cut.
- **Reveal segmenti GİDEREK KARARSIN** (bright→dark, `eq=brightness='-0.6*min(1,t/DUR)'`) → lazer gözler öne çıksın. Kararma reveal İÇİNDE, ayrı siyah-filtre değil.
- **Tek yazı = "...YOU."** (SPAIN ARE THROUGH / INTO THE SEMIS vb. yazıları İSTEMİYOR).
- **Yapı:** ~9sn kutlama sahneleri → Mbappé'den ÖNCE Yamal anı → drop → Mbappé "...YOU." → bayrak kartı.
- **Watermark:** Kling/Hailuo/Magic Hour → zoom-crop ile kes (kare 640 için scale 2200 → crop top-biased y=30).
- **⚠️ Broadcast TEST:** kullanıcı Spain-Belgium highlights'tan test kesti (`temp/TEST_DONOTPUBLISH_*`, Yamal şut 1:16-1:19 + kutlamalar 0:32/1:40). Sadece "nasıl durur" testi — YAYINLANMAZ (Content ID). Yayın için broadcast→CC foto + AI klip.

**Açık / sonraki adımlar:**
1. **Kanal yönü: CIA/truth/mystery'e dön** (analytics-destekli). Piller: declassified sırlar, çözülmemiş gizemler/kayıplar, UFO/UAP (kanal adı `The Truth Is Out There`), devlet örtbasları. Somut ilk video seçilecek.
2. Teaser'lar TikTok/IG (silent + in-app ses) + YouTube (trailer sesli) yayınlanacak — maç 15 Tem, aynı gün çıkmalı.
3. `a4dbd8b` + `01ae7b1` push bekliyor.

---

## GÜNCEL DURUM — 2026-07-12 (`--voice-file` kendi-ses özelliği + beat-timed elle montaj + 2 public video)

**1) YENİ ÖZELLİK: `--voice-file` — bring-your-own-voice (commit+push `f62379f`).**
- Kullanıcı haber metnini **kendi sesiyle** okumak istedi (AI TTS yerine). Sorun: kayıtta edge-tts'in yazdığı `voice.vtt` yok → montaj altyazı zamanlaması + görsel kesim temposunu kaybeder.
- Çözüm: `--voice-file <path>` → kayıt `voice.mp3`'e kopyalanır, **faster-whisper ile transkribe edilip** `tts.vtt_from_segments()` montaj-uyumlu WEBVTT üretir. TTS atlanır.
- **Mimari:** `core/config.py` `voice_file_path` alanı + build_config · `core/cli.py` `--voice-file` · `core/news_mode.py` voice-file branch (kopya+whisper) vs TTS · `analysis/tts.py` `vtt_from_segments`+`_fmt_ts` · `main.py` route. `--news-script` ile eşleştir (aynı metin).
- **Test:** yeni `tests/test_voice_file.py` (VTT round-trip, 12 check) → **`tests/run_all.py` 18/18 suite, 258/258 PASS**.

**2) GOTCHA — aksanlı İngilizce'de whisper dili yanlış (Karar 32).** Türk aksanlı İngilizce kayıtta whisper otomatik dili **Türkçe** algıladı → altyazı tamamen bozuk. Fix: `WhisperModel.transcribe(language='en')` ile yeniden çalıştır → doğru metin. İleride voice-file yoluna EN varsayılanı/dil-env eklenebilir.

**3) BEAT-TIMED ELLE MONTAJ + telif-güvenli görsel kaynak (Karar 33).** `montage.build_montage` görselleri EŞİT böler → isimler/anlar ~1 beat kayar. Kaliteli videolar için VTT cue zamanına göre **değişken-süreli** segmentli elle build script (scratchpad). Görseller: gerçek CC maç fotoları (Commons — Haaland Morocco v Norway 2026 CC BY-SA, Mbappé/Yamal/Messi/Álvarez portreleri), PD arşiv (1966 finali, Hurst), PD bayraklar (ffmpeg üretimi FR/ENG), kendi ffmpeg grafik kartlarım (GOAL skor kartı, THE FINAL FOUR 2x2 yüz gridi, WHO WINS, kupa). Ses **1.10x** `atempo` (perde korunur) + VTT `/1.10` ölçekle. **Broadcast maç klibi = Content ID → asla; still CC/PD foto = güvenli.**

**4) İKİ PUBLIC VİDEO yayınlandı (kullanıcı sesiyle):**
- **`xii8AxO7fXw`** — "Bellingham BREAKS Norwegian Hearts" (England 2-1 Norway, çeyrek final). Gerçek maç fotoları + 1966 finali PD foto + GOAL 2-1 kartı. Kullanıcı hemen public istedi (peak-slot bilerek çiğnendi).
- **`Q8gcnH8yt0M`** — "The Final Four Are SET" (yarı final önizleme, EVERGREEN). 2x2 yıldız gridi + ülke bayrakları (kart + oyuncu-beat rozeti) + kupayla ("cup" derken FIFA kupası CC BY-SA) kapanış. Yorum/analiz formatı — tek maça bağlı değil, SF'ye (14-15 Tem) kadar taze.
- İkisi de performance store'a kayıtlı (pending) → birkaç gün sonra `--fetch-analytics`.

**Gözlem — bayrak altyazıda:** Yanan altyazı (libass + Impact) renkli bayrak emojisi basmıyor → bayrak yazının içine gömülemez. Çözüm: bayrağı ekrana **rozet** olarak bindirdim (oyuncu beat'inde sol üst) + kartlarda bayrak görseli.

**İptal:** Argentina 3-1 Switzerland videosu (dünkü tek maç) yapılmadı — kullanıcı daha genel/evergreen "Final Four" yorumunu tercih etti.

**Açık / sonraki adımlar:** pipeline'a beat-timing + görsel-provenance opsiyonu (şu an elle script) · voice-file yolunda whisper dil-zorlama · news moduna `--public`/`--publish-now` (hâlâ eksik — direkt upload'la aşıldı) · birkaç gün sonra `--fetch-analytics` (xii8AxO7fXw, Q8gcnH8yt0M, xVaQLTb1zAc).

---

> **Eski oturumlar:** 2026-07-11 ve oncesi [[SESSION_ARCHIVE]] dosyasina tasindi (2026-07-17 diyet).
> Kural: bu dosyada SON 2-3 oturum kalir; eskiyenler her diyet gununde arsive kayar.
