"""Trending football-topic auto-detection for news mode.

Pulls headlines from free, key-less football RSS feeds (BBC/Guardian/ESPN/Sky),
keeps only fresh items (shelf-life rule — news Shorts go stale fast), dedupes,
and lets the Groq LLM pick the single most engaging story for a 20s Short —
returning a concise, factual topic string that feeds ``generate_news_script``.

Design mirrors ``stock_media``: network I/O is isolated in small helpers; the
parsing/ranking logic is pure and unit-tested. Any single feed failing (or the
LLM being unavailable) degrades gracefully — a heuristic picks the freshest item.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET

from core.logger import get_logger

log = get_logger(__name__)

_UA = {"User-Agent": "kulturel-ai-agent/1.0 (news mode; trend detection)"}

# Free, no-key football RSS feeds, in priority order (BBC/Guardian first).
_FEEDS = [
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Guardian", "https://www.theguardian.com/football/rss"),
    ("ESPN", "https://www.espn.com/espn/rss/soccer/news"),
    ("Sky Sports", "https://www.skysports.com/rss/12040"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Drop weak/fast-stale items (fixtures blobs, quizzes, gossip) AND tragedies/crime
# — a hype Short about a death or court case is tasteless + demonetization-risky,
# so these never enter the pool (protects the no-LLM heuristic path too).
_SKIP_TITLE = ("quiz", "gossip", "rumour", "how to watch", "in pictures",
               "your team", "football scores", "watch:", "video:",
               "dies", "dead", "death", "obituary", "passed away", "tribute",
               "arrested", "charged", "court", "jail", "prison", "abuse",
               "racism", "racist", "assault")


@dataclass
class NewsItem:
    title: str
    summary: str
    link: str
    published: Optional[datetime]
    source: str


def _clean(text: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    if not text:
        return ""
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()


def _parse_pubdate(raw: str) -> Optional[datetime]:
    """RFC-822 pubDate -> tz-aware UTC datetime (None if unparseable)."""
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _localname(tag: str) -> str:
    """Strip an XML namespace: '{http://www.w3.org/2005/Atom}entry' -> 'entry'."""
    return tag.rsplit("}", 1)[-1]


def parse_rss(xml_text: str, source: str = "") -> List[NewsItem]:
    """Parse RSS 2.0 (<item>) or Atom (<entry>) into NewsItems. Pure/testable."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("[trend] RSS parse failed (%s): %s", source, exc)
        return []

    items: List[NewsItem] = []
    for node in root.iter():
        if _localname(node.tag) not in ("item", "entry"):
            continue
        title = summary = link = pub = ""
        for child in node:
            name = _localname(child.tag)
            if name == "title":
                title = child.text or ""
            elif name in ("description", "summary"):
                summary = summary or (child.text or "")
            elif name == "link":
                # RSS: text; Atom: href attribute
                link = link or (child.text or child.get("href") or "")
            elif name in ("pubDate", "published", "updated"):
                pub = pub or (child.text or "")
        title = _clean(title)
        if not title:
            continue
        items.append(NewsItem(
            title=title,
            summary=_clean(summary),
            link=link.strip(),
            published=_parse_pubdate(pub),
            source=source,
        ))
    return items


def is_recent(item: NewsItem, now: datetime, hours: float) -> bool:
    """Fresh enough to publish today. Undated items are kept (feed order = recency)."""
    if item.published is None:
        return True
    return item.published >= now - timedelta(hours=hours)


def _norm_title(title: str) -> str:
    return _WS_RE.sub(" ", re.sub(r"[^a-z0-9 ]", "", title.lower())).strip()


def dedupe(items: List[NewsItem]) -> List[NewsItem]:
    """Drop cross-source duplicates (same normalized title, or one contained in another)."""
    kept: List[NewsItem] = []
    seen: List[str] = []
    for it in items:
        n = _norm_title(it.title)
        if not n or any(n == s or n in s or s in n for s in seen):
            continue
        seen.append(n)
        kept.append(it)
    return kept


def _skip(item: NewsItem) -> bool:
    low = item.title.lower()
    return any(s in low for s in _SKIP_TITLE)


def _fetch_feed(url: str, timeout: int = 15) -> str:
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=_UA), timeout=timeout
    ).read().decode("utf-8", errors="replace")


def gather_items(now: Optional[datetime] = None, hours: float = 36.0,
                 feeds=_FEEDS) -> List[NewsItem]:
    """Fetch every feed, keep fresh non-junk items, dedupe. Freshest first."""
    now = now or datetime.now(timezone.utc)
    all_items: List[NewsItem] = []
    for source, url in feeds:
        try:
            xml_text = _fetch_feed(url)
        except Exception as exc:
            log.warning("[trend] feed '%s' unreachable: %s", source, exc)
            continue
        got = parse_rss(xml_text, source)
        fresh = [it for it in got if is_recent(it, now, hours) and not _skip(it)]
        log.info("[trend] %s: %d items, %d fresh", source, len(got), len(fresh))
        all_items.extend(fresh)

    # Freshest first; undated sink to the bottom but stay (feeds list newest-first).
    all_items.sort(key=lambda it: it.published or datetime.min.replace(tzinfo=timezone.utc),
                   reverse=True)
    return dedupe(all_items)


def _heuristic_topic(items: List[NewsItem]) -> str:
    """No-LLM fallback: freshest item -> a self-contained factual topic line."""
    it = items[0]
    topic = it.title
    if it.summary:
        topic += f". {it.summary}"
    return _WS_RE.sub(" ", topic).strip()[:400]


_SELECT_SYSTEM = """You are a FOOTBALL (soccer) news editor choosing today's single \
best story for an upbeat, hype 20-25 second YouTube Short. From the numbered headlines \
below, pick the ONE with the strongest positive hook: a big result, a star player's \
performance, a stunning goal, a record, or a major transfer.

MUST be association football (soccer). NEVER pick another sport — if a headline is \
golf, tennis, cricket, rugby, F1, boxing, NFL, basketball, or anything not soccer, \
skip it entirely, even if it mentions a record.

DO NOT pick tragedies — deaths, obituaries, serious injuries, illness, crime, \
violence, or abuse. A hype Short about a tragedy is tasteless and demonetization-risky. \
Also avoid vague previews, opinion columns, and fixtures lists.

Return ONE JSON object, no prose: {"index": <number>, "topic": "<one or two \
sentences stating the key facts of that story, self-contained, no hashtags>"}. \
The topic must contain the concrete facts (who, what, score/number) so a writer \
can script it without the original article."""


def select_topic(items: List[NewsItem], config, client=None) -> str:
    """LLM-pick the most engaging story -> factual topic line. Heuristic on failure.

    ``client`` may be injected (tests). Falls back to the freshest item's text if
    there is no Groq key or the LLM/JSON fails.
    """
    if not items:
        raise RuntimeError("trend detection found no fresh football stories")

    if not getattr(config, "groq_api_key", ""):
        log.info("[trend] no GROQ_API_KEY — using heuristic (freshest) topic")
        return _heuristic_topic(items)

    listing = "\n".join(
        f"{i}. {it.title}" + (f" — {it.summary[:160]}" if it.summary else "")
        for i, it in enumerate(items[:20])
    )
    try:
        if client is None:
            from groq import Groq
            client = Groq(api_key=config.groq_api_key)
        resp = client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": _SELECT_SYSTEM},
                {"role": "user", "content": listing},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        topic = _WS_RE.sub(" ", str(data.get("topic") or "")).strip()
        if len(topic) < 15:  # LLM gave nothing usable
            raise ValueError(f"empty/short topic: {topic!r}")
        idx = data.get("index")
        picked = items[idx].title if isinstance(idx, int) and 0 <= idx < len(items) else "?"
        log.info("[trend] LLM picked [%s] %r -> topic=%r", idx, picked[:60], topic[:80])
        return topic
    except Exception as exc:
        log.warning("[trend] LLM selection failed (%s) — heuristic fallback", exc)
        return _heuristic_topic(items)


def detect_trending_topic(config, hours: Optional[float] = None) -> str:
    """End-to-end: gather fresh football headlines -> best topic string.

    Window defaults to TREND_WINDOW_HOURS (env) or 36h — fresh enough to publish
    same-day. Raises RuntimeError only if no fresh story is found at all.
    """
    if hours is None:
        hours = float(os.getenv("TREND_WINDOW_HOURS", "36"))
    items = gather_items(hours=hours)
    if not items:
        raise RuntimeError(
            "no fresh football stories found (all feeds empty/unreachable). "
            "Pass a topic manually with --news \"<topic>\".")
    log.info("[trend] %d fresh stories after dedupe; selecting best", len(items))
    topic = select_topic(items, config)
    log.info("[trend] === trending topic: %s ===", topic)
    return topic
