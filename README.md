# Kültürel AI Agent — Content Strategy

Faceless, analytical YouTube Shorts, produced end-to-end by one command.

## Channel direction (2026-07-14 diagnosis — analytics-backed)

The channel is **not** flagged or shadowbanned (old Short: 1,291 views from feed;
distribution is active). The problem was **audience fit**:

- **Football news Shorts = the channel's worst content** (~5 views, ~0% CTR).
  Wrong audience — the channel is labeled with `truth`-seeking viewers.
- **Winning lane: CIA / whistleblower / truth / unsolved mystery / declassified**
  (CTR 3.9–5.3%, retention 22–29% — 2–3x football).

**Rule of thumb:** default new content to the truth/mystery lane. If a trending
(football or other) topic is wanted, **bridge it** — find its hidden-story /
conspiracy / mystery angle (e.g. 1966 "Animals" origin story, ArgenFIFA) rather
than reporting the news straight. A topic that can't be bridged is probably the
wrong video. See the `kulturel-video` skill for the full pre-production checklist.

## Format history (why we got here)

1. **Clip-extraction / talking-head** (Jun) → died on retention (~5s avg view,
   0.1%): the first 1–5 seconds never paid off the title's promise.
2. **Faceless news** (`--news`, Jul 11) → production format works (script → TTS
   or own voice → license-safe b-roll + CC photos → kinetic captions → music),
   but *football* topics underperform (wrong audience).
3. **Truth/mystery pivot** (Jul 14) → same production machine, winning topics.

## Hard rules (unchanged)

- **Demonetization-safe:** no broadcast footage ever (Content ID — a single
  second is claimed). License-safe stock + CC/PD photos + self-made cards +
  original commentary. AI voice alone does not flag a channel.
- **Publish only at peak slots — 12:00 / 18:00 (local),** always scheduled via
  `--publish-at` / `next_publish_slot()`. Never dead hours.
- **Same-day rule:** event-tied Shorts (match results, breaking news) go stale
  in hours — render + upload the same day or don't start. Evergreen/mystery
  framing survives longer.
- Hook in the first second; the title must not promise visuals the video can't show.

## Produce a video

```bash
python main.py --news "<topic>" [--upload]                    # LLM script
python main.py --news-script news_scripts/<x>.json [--upload]  # your own script
python main.py --news-trend [--upload]                         # auto topic (RSS)
```

Requires `PIXABAY_API_KEY` in `.env`. Details: `WORKFLOW.md`.
The legacy clip-extraction pipeline (YouTube URL → clips) still works but is
not the channel's direction.

## Next

First truth/mystery-lane video (concrete topic TBD) · wire news videos into the
analytics/learning loop · beat-timing + visual-provenance as a pipeline option
(currently a hand-built script for top-quality videos).
