# Pipeline Session Log

> **Read this file first at the start of each session.** This is the conversation history backup.
> Links: `CHANGELOG.md` (what changed) · `CLAUDE.md` (rules)

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
