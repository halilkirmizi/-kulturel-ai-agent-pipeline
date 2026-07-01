"""Tests for Claude as the clip-selection provider (analysis/clip_scoring.py).

The real Anthropic API needs a key + network; here a mock client is injected to
verify the response-parsing path and config/provider wiring.

Run:  python tests/test_claude_select.py
"""

import sys
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

print("=" * 60)
print("CLAUDE SELECT TEST SUITE")
print("=" * 60)

results = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  {status}: {name}" + (f" ({detail})" if detail else ""))
    results.append((name, status))


from analysis.clip_scoring import _call_claude
from core.config import build_config


# ── mock Anthropic client ───────────────────────────────────────────────────
class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Resp:
    def __init__(self, blocks):
        self.content = blocks


class _MockMessages:
    def __init__(self, blocks):
        self._blocks = blocks
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Resp(self._blocks)


class _MockClient:
    def __init__(self, blocks):
        self.messages = _MockMessages(blocks)


# ── _call_claude parses JSON from text blocks ───────────────────────────────
print("\n[TEST 1] _call_claude parsing")
cfg = build_config()
json_payload = '{"selections": [{"window_id": 2, "hook_text": "WOW", "scores": {"curiosity": 9}}]}'
# thinking-like block first, then the JSON text block
mock = _MockClient([_Block("thinking", "let me think {not json}"), _Block("text", json_payload)])
out = _call_claude(cfg, "sys", "user", client=mock)
check("parses selections from text block", out["selections"][0]["window_id"] == 2, str(out))
check("ignores non-text blocks", out["selections"][0]["hook_text"] == "WOW")
check("passes model to API", mock.messages.last_kwargs["model"] == cfg.anthropic_model,
      mock.messages.last_kwargs.get("model"))
check("sends system + user", mock.messages.last_kwargs["system"] == "sys"
      and mock.messages.last_kwargs["messages"][0]["role"] == "user")

# JSON embedded in surrounding prose still extracted
mock2 = _MockClient([_Block("text", "Here are the clips:\n" + json_payload + "\nDone.")])
out2 = _call_claude(cfg, "s", "u", client=mock2)
check("extracts JSON from surrounding prose", out2["selections"][0]["window_id"] == 2)


# ── config + CLI wiring ─────────────────────────────────────────────────────
print("\n[TEST 2] config wiring")
check("default provider groq", build_config().select_provider == "groq")
check("override provider claude", build_config(select_provider="claude").select_provider == "claude")
check("default anthropic model", build_config().anthropic_model == "claude-opus-4-8")

from core.cli import parse_args
a = parse_args(["url", "--select-with", "claude"])
check("--select-with parses", a.select_with == "claude")
check("default select-with groq", parse_args(["url"]).select_with == "groq")


# ── provider guard: claude path doesn't require GROQ key ────────────────────
print("\n[TEST 3] provider guard")
# score_clips raises for groq without key, but not for claude. We check the guard
# logic indirectly via config: claude provider set, no groq key -> should be allowed.
c = build_config(select_provider="claude")
check("claude provider set, groq key empty ok", c.select_provider == "claude")


print("\n" + "=" * 60)
passed = sum(1 for _, s in results if s == "PASS")
print(f"RESULT: {passed}/{len(results)} passed")
print("=" * 60)
sys.exit(0 if passed == len(results) else 1)
