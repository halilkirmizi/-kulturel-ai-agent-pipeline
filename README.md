# Kültürel AI Agent — Content Strategy

Faceless **football news** Shorts, produced end-to-end by one command.

## Why this format (2026-07-11 pivot)
Talking-head / clip-extraction Shorts died on retention: ~5s average view,
~0.1% viewed, near-zero distribution — even when public. The YouTube Shorts
algorithm tests each Short on a small audience and only expands it if the first
1–5 seconds hold viewers. Static talking heads don't. The winning format:

**Original news script → AI (or self) voiceover → fast-cut license-safe motion
b-roll + real player photos → kinetic captions → music.**

## Hard rules
- **Demonetization-safe:** no broadcast match footage (Content ID). Only
  license-safe Pixabay stock + CC Wikimedia player photos + **original**
  commentary (not reused). AI voice alone does not flag a channel.
- **Publish only at peak slots — 12:00 / 18:00 (local). Never dead hours.**
  Always schedule via `--publish-at` / `next_publish_slot()`.
- Hook in the first second; the title must not promise visuals the video can't
  show (a "GOAL" title over a talking head = instant swipe).

## Produce a video
```bash
python main.py --news "France beat Morocco 2-0, Mbappe 8th goal, into semifinal"          # render only
python main.py --news "<topic>" --upload                                                   # + scheduled public
```
Requires `PIXABAY_API_KEY` in `.env`. Pipeline: `core/news_mode.py` (see WORKFLOW.md).

## Next
Auto trend detection (topic is manual today) · cron for hands-off daily runs ·
caption word-highlight animation · wire news videos into the analytics/learning loop.

The legacy clip-extraction pipeline (YouTube URL → clips) still works but is no
longer the channel's direction.
