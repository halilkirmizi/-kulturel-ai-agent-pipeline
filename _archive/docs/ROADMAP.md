# Self-Learning Pipeline — Full Spec

> Hedef: "çalışan video pipeline + logging + validation" → "kendi output'unu ölçen, hatalarını analiz eden, weight güncelleyen, memory update eden adaptive system"

---

## 1. Eksik Katmanlar (Mandatory Gap List)

### A. Feedback / Evaluation Layer (EN KRİTİK)
**Gereklilik:** Her run sonunda sistem şunları üretmeli:
- clip quality score (LLM + heuristic)
- render quality score (ffmpeg validation + visual heuristics)
- hook effectiveness score
- upload success quality signal (engagement hook placeholder)

**Eksik:** hiçbir "run evaluation function" yok — sadece execution var, assessment yok.

### B. Weight Learning System (adaptive tuning)
**Gereklilik:** `topics_weight`, `clip_score_threshold`, `graph_enrichment_weight`, `hook_weight` — bunları geçmiş run performansına göre güncellemeli.

**Eksik:** static weights, 0 learning loop.

### C. Memory Write-back Layer (Obsidian / Graph update)
**Gereklilik:** Başarılı clip pattern'lerini graph'a yazmalı, başarısız topic pattern'lerini negative memory olarak kaydetmeli, "hangi topic → iyi clip üretti" ilişkisini öğrenmeli.

**Eksik:** graph sadece READ-ONLY.

### D. Run Analytics Layer
**Gereklilik:** Her pipeline run sonunda: run_id, duration per stage, LLM latency, clip yield ratio, failure points, score distribution.

**Eksik:** feature_registry sadece event log, analytics yok.

### E. Simulation / Replay System
**Gereklilik:** Geçmiş run'ı replay et, weight değişince ne olur gör, A/B scoring comparison.

**Eksik:** test harness yok, simulation yok.

### F. Intent Tracking Layer
**Gereklilik:** Her feature için: intent ("why this exists"), implementation ("where it is used"), validation ("is it actually active?").

**Eksik:** feature_registry only runtime tracking, intent layer yok.

---

## 2. Yeni Modüller (Minimal Addition Model)

Mevcut sistem bozulmayacak. Sadece 3 yeni modül eklenecek:

### 🔵 1. `core/feedback_engine.py`
Pipeline output → scoring.
- `evaluate_run(state, clips) -> RunMetrics`
- `score_clip_quality(clip) -> float`
- `compute_hook_effectiveness(hook_text) -> float`

Output: `{"clip_quality": 0.72, "hook_quality": 0.61, "render_quality": 0.88}`

### 🟡 2. `core/learning_engine.py`
Weights update.
- `update_weights(metrics, current_weights) -> new_weights`
- `compute_gradient_like_adjustment()`
- `persist_weights()`

Logic: high quality → reinforce pattern, low quality → reduce weight influence.

### 🟢 3. `core/memory_writer.py`
Obsidian graph update.
- `write_success_pattern(topics, clips)`
- `write_failure_pattern(failed_topics)`
- `link_topic_to_quality_score()`

---

## 3. Yeni Pipeline Flow

```
BEFORE:
download → transcribe → topics → graph → scoring → ffmpeg → upload

AFTER:
download → transcribe → topics → graph → scoring → render → upload
  ↓
──────────────────── FEEDBACK LOOP (NEW) ────────────────────
  ↓
feedback_engine.evaluate_run()
  ↓
learning_engine.update_weights()
  ↓
memory_writer.update_graph()
  ↓
persist weights + metrics
```

---

## 4. Implementation Steps (Ordered)

### 🥇 STEP 1 — Freeze current system
- `git commit` checkpoint
- clean working tree
- tag: `baseline_before_learning`

### 🥈 STEP 2 — Add feedback_engine (read-only first)
- only compute metrics
- DO NOT modify pipeline yet
- output: `run_metrics.json`

### 🥉 STEP 3 — Add learning_engine (simulation mode)
- compute new weights
- BUT DO NOT APPLY yet
- output: `proposed_weights.json`

### 🏁 STEP 4 — Add memory_writer (write-only)
- write patterns to Obsidian graph
- success/failure tagging

### ⚙️ STEP 5 — Enable live weight update
- connect learning_engine → config injection
- weights become dynamic per run

### 🧪 STEP 6 — Add replay mode
- `--simulate-run`
- compare old vs new weights

---

## 5. Design Rules (Critical)

### Rule 1 — NO real-time mutation in v1
learning happens AFTER pipeline finishes

### Rule 2 — no LLM dependency in learning layer
only metrics + deterministic scoring

### Rule 3 — memory write is append-only
never overwrite existing graph nodes

### Rule 4 — weights must be versioned
```
weights_v1.json
weights_v2.json
```

---

## 6. Final System Architecture

```
                ┌──────────────┐
                │  main.py      │
                └──────┬───────┘
                       │
        ┌──────────────┼──────────────┐
        │                              │
   PIPELINE CORE                FEEDBACK LAYER
        │                              │
download → render → upload     feedback_engine
        │                              │
        └──────────────┬──────────────┘
                       │
              learning_engine
                       │
              memory_writer (Obsidian)
                       │
               weights.json update
```

---

## 7. Real Impact (Why This Matters)

| Önce | Sonra |
|---|---|
| pipeline sadece üretir | pipeline üretir + değerlendirir + öğrenir + kendini optimize eder |
| static weights | weight space evolve olur |
| graph read-only | Obsidian graph'ı büyütür |
| her run aynı | her run bir öncekinden daha iyi |
