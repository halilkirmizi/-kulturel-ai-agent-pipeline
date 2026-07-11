"""Tests for the trending-topic auto-detector (news mode).

Pure parsing/ranking + LLM selection with an injected mock client (no network).

Run:  python tests/test_trend_detector.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from analysis.trend_detector import (
    NewsItem, parse_rss, is_recent, dedupe, gather_items,
    _parse_pubdate, _clean, _heuristic_topic, select_topic,
)

print("=" * 60)
print("TREND DETECTOR TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Feed</title>
  <item>
    <title><![CDATA[Haaland stuns Brazil in quarter-final]]></title>
    <description>&lt;p&gt;Norway win &lt;b&gt;2-1&lt;/b&gt; to reach the semis.&lt;/p&gt;</description>
    <link>https://example.com/a</link>
    <pubDate>Sat, 11 Jul 2026 09:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Transfer gossip: who is moving?</title>
    <description>Latest rumours.</description>
    <link>https://example.com/b</link>
    <pubDate>Sat, 11 Jul 2026 08:00:00 GMT</pubDate>
  </item>
</channel></rss>"""

_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Mbappe scores hat-trick</title>
    <summary>France cruise past Morocco.</summary>
    <link href="https://example.com/c"/>
    <published>2026-07-11T10:00:00Z</published>
  </entry>
</feed>"""

# ── parse_rss ────────────────────────────────────────────────────────────────
print("\n[TEST 1] parse_rss — RSS 2.0")
items = parse_rss(_RSS, "BBC")
check("2 items parsed", len(items) == 2, str(len(items)))
check("CDATA title", items[0].title == "Haaland stuns Brazil in quarter-final", items[0].title)
check("HTML stripped from summary", items[0].summary == "Norway win 2-1 to reach the semis.",
      items[0].summary)
check("link parsed", items[0].link == "https://example.com/a", items[0].link)
check("pubDate parsed", items[0].published is not None and items[0].published.hour == 9,
      str(items[0].published))
check("source tagged", items[0].source == "BBC", items[0].source)

print("\n[TEST 2] parse_rss — Atom entry")
a = parse_rss(_ATOM, "X")
check("1 atom entry", len(a) == 1, str(len(a)))
check("atom title", a and a[0].title == "Mbappe scores hat-trick", a[0].title if a else "-")
check("atom link href", a and a[0].link == "https://example.com/c", a[0].link if a else "-")

print("\n[TEST 3] parse_rss — malformed returns []")
check("bad xml -> []", parse_rss("<not xml", "x") == [])

# ── _clean / _parse_pubdate ──────────────────────────────────────────────────
print("\n[TEST 4] helpers")
check("_clean strips tags+entities", _clean("<b>Hi</b>&amp;bye") == "Hi &bye", _clean("<b>Hi</b>&amp;bye"))
check("_parse_pubdate RFC822", _parse_pubdate("Sat, 11 Jul 2026 09:00:00 GMT") is not None)
check("_parse_pubdate junk -> None", _parse_pubdate("not a date") is None)
check("_parse_pubdate empty -> None", _parse_pubdate("") is None)

# ── is_recent ────────────────────────────────────────────────────────────────
print("\n[TEST 5] is_recent")
fresh = NewsItem("t", "", "", NOW - timedelta(hours=5), "s")
old = NewsItem("t", "", "", NOW - timedelta(hours=50), "s")
undated = NewsItem("t", "", "", None, "s")
check("5h ago is recent (36h)", is_recent(fresh, NOW, 36))
check("50h ago not recent (36h)", not is_recent(old, NOW, 36))
check("undated kept", is_recent(undated, NOW, 36))

# ── dedupe ───────────────────────────────────────────────────────────────────
print("\n[TEST 6] dedupe")
dup = [
    NewsItem("Haaland Stuns Brazil", "", "", NOW, "BBC"),
    NewsItem("haaland stuns brazil!", "", "", NOW, "Sky"),        # exact (normalized)
    NewsItem("Haaland stuns Brazil in the quarter-final", "", "", NOW, "ESPN"),  # superset
    NewsItem("Mbappe hat-trick", "", "", NOW, "Guardian"),
]
d = dedupe(dup)
check("collapses near-dups", len(d) == 2, str([x.title for x in d]))
check("keeps distinct story", any("Mbappe" in x.title for x in d))

# ── gather_items with injected feeds (no network) ────────────────────────────
print("\n[TEST 7] gather_items — filter + sort + junk skip")
import analysis.trend_detector as td
orig_fetch = td._fetch_feed
td._fetch_feed = lambda url, timeout=15: _RSS  # both feeds serve same RSS
try:
    got = td.gather_items(now=NOW, hours=36, feeds=[("A", "u1"), ("B", "u2")])
finally:
    td._fetch_feed = orig_fetch
check("gossip item skipped", all("gossip" not in i.title.lower() for i in got),
      str([i.title for i in got]))
check("real story survived", any("Haaland" in i.title for i in got))
check("cross-feed dupes removed", len(got) == 1, str(len(got)))

# ── _heuristic_topic ─────────────────────────────────────────────────────────
print("\n[TEST 8] _heuristic_topic")
h = _heuristic_topic([NewsItem("Haaland stuns Brazil", "Norway win 2-1.", "", NOW, "BBC")])
check("combines title+summary", h == "Haaland stuns Brazil. Norway win 2-1.", h)


# ── select_topic ─────────────────────────────────────────────────────────────
class _Cfg:
    groq_api_key = "k"
    groq_model = "m"


class _NoKeyCfg:
    groq_api_key = ""
    groq_model = "m"


class _FakeMsg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeMsg(content)]


class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        return _FakeResp(self._content)


print("\n[TEST 9] select_topic — LLM pick")
its = [
    NewsItem("Haaland stuns Brazil", "Norway win 2-1.", "", NOW, "BBC"),
    NewsItem("Mbappe hat-trick", "France win.", "", NOW, "Sky"),
]
client = _FakeClient('{"index": 0, "topic": "Haaland scored twice as Norway beat Brazil 2-1 to reach their first World Cup semi-final."}')
t = select_topic(its, _Cfg(), client=client)
check("returns LLM topic", "Norway beat Brazil 2-1" in t, t[:60])

print("\n[TEST 10] select_topic — no key -> heuristic")
t2 = select_topic(its, _NoKeyCfg())
check("heuristic used", t2.startswith("Haaland stuns Brazil"), t2[:40])

print("\n[TEST 11] select_topic — LLM junk -> heuristic fallback")
t3 = select_topic(its, _Cfg(), client=_FakeClient('{"topic": ""}'))
check("falls back on empty topic", t3.startswith("Haaland stuns Brazil"), t3[:40])

print("\n[TEST 12] select_topic — empty items raises")
try:
    select_topic([], _Cfg())
    check("empty raises", False)
except RuntimeError:
    check("empty raises", True)


# ── summary ──────────────────────────────────────────────────────────────────
passed = sum(1 for _, s in results if s == "PASS")
total = len(results)
print("\n" + "=" * 60)
print(f"RESULT: {passed}/{total} passed")
print("=" * 60)
sys.exit(0 if passed == total else 1)
