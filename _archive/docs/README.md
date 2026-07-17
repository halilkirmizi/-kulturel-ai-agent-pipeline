# Arşivlenmiş Dokümanlar (2026-07-17)

Bu dosyalar bayatladığı, tamamlandığı veya güncel yapıyla çeliştiği için arşivlendi.
**Hiçbiri artık otorite değildir** — güncel kurallar `pipeline/CLAUDE.md`'de, akış `WORKFLOW.md`'de, durum `SESSION.md`'de, kararlar `../Key Decisions.md`'de yaşar.

| Dosya | Neden arşivlendi |
|---|---|
| `_CLAUDE.md` | 18 Haziran snapshot'ı; var olmayan `renderer.py`'a referans veriyordu; CLAUDE.md aynı işi görüyor |
| `MEMORY/ALWAYS.md` | "Her prompt'ta yüklenir" iddiası doğru değildi (hiçbir şey yüklemiyordu); eski klip-pipeline kuralları (12-35sn) news moduyla çelişiyor |
| `MEMORY/PROJECT.md` | "Next: pip install" — Haziran'da tamamlanmış kurulum adımları |
| `MEMORY/ARCHIVE/INDEX.md` | Session 9'da donmuş eski oturum indeksi |
| `STATE_CONTRACT.md` | Sadece legacy klip-pipeline'ın state.json sözleşmesi; news yolu kullanmıyor. Legacy pipeline'a dönülürse referans olarak geçerli |
| `REFACTOR_SEQUENCE.md` | Tamamlanmış refactor'ün planı (Session 11-12'de bitti) |
| `ROADMAP.md` | Yol haritasındaki learning-loop maddeleri 30 Haziran'da tamamlandı; kalanlar terk edildi |
| `CHANGELOG.md` | 3 Temmuz'da güncellenmesi durdu; git log aynı işi görüyor |
| `memory_architecture_proposal.md` | Hiç uygulanmamış tasarım önerisi (design/'dan) |

## Arşivlenmiş KOD (2026-07-17, `_archive/code/`)

| Dosya | Neden |
|---|---|
| `artifact_auditor.py` | 568 satır — hiçbir modül import etmiyordu, hiçbir CLI çağırmıyordu (ölü) |
| `obsidian_bridge/` | 174 satır — pipeline'a hiç bağlanmadı; kullanıcı kararı: workflow Obsidian entegrasyonuna ihtiyaç duyacak kadar karmaşık değil |

Arşiv sonrası tam test matrisi: **19/19 suite, 283/283 PASS** (hiçbir şey kırılmadı).
