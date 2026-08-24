"""TradeStoryWriter: turn a TradeStoryFacts packet into verdict+story prose.

Mirrors RecapWriter: a static prompt-cached persona system block plus a user
turn carrying the facts JSON. The model is told to use only packet facts.
"""

from __future__ import annotations

import json
import logging
import re
from importlib import resources

import anthropic

from sleeper_dynasty.llm._usage import usage_dict
from sleeper_dynasty.llm.story_validation import repair_prose, tidy_headline
from sleeper_dynasty.llm.usage import report
from sleeper_dynasty.models.trade_story import TradeStoryFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

# Deterministic guard: the persona bans "KTC" (it is "Trade Value" to users),
# but a weaker model occasionally leaks it. Strip it before caching so it can
# never reach the page regardless of what the model emits. Order matters:
# collapse the qualified phrases first, then bare "KTC". \b keeps us from
# mangling unrelated words. We deliberately do NOT touch "swing" — it is common
# English and over-eager replacement would mangle legitimate prose.
_KTC = r"K\.?T\.?C\.?"
_KTC_SUBS = [
    (re.compile(rf"\b{_KTC}\s+market value\b", re.I), "market value"),
    (re.compile(rf"\b{_KTC}\s+value\b", re.I), "trade value"),
    (re.compile(rf"\b{_KTC}\b", re.I), "trade value"),
]


def sanitize_prose(text: str) -> str:
    """Strip market-data jargon the persona bans but a model may still leak."""
    for pat, repl in _KTC_SUBS:
        text = pat.sub(repl, text)
    return text


def load_persona() -> str:
    return resources.files(_PROMPTS).joinpath("trade_story_persona.md").read_text()


_BULLETS = ("- ", "* ", "• ", "› ")


def parse_story(text: str) -> dict:
    """Split raw model output into {verdict, lede, beats, body}.

    Verdict = first non-empty line (markdown bold stripped). The remainder is
    split into bullet lines (beats) and non-bullet prose (the lede). `body` is a
    readable fallback (lede then beats) for stories rendered before the
    structured shape existed. Degrades to lede-only when no bullets are present.
    """
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    verdict = ""
    rest_start = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            verdict = ln.strip().strip("*").strip()
            rest_start = i + 1
            break
    beats: list[str] = []
    lede_parts: list[str] = []
    for ln in lines[rest_start:]:
        s = ln.strip()
        if not s:
            continue
        if s[:2] in _BULLETS:
            beats.append(s[2:].strip())
        else:
            lede_parts.append(s)
    lede = " ".join(lede_parts).strip()
    body = "\n\n".join(([lede] if lede else []) + beats).strip()
    return {"verdict": verdict, "lede": lede, "beats": beats, "body": body}


class TradeStoryWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: TradeStoryFacts) -> tuple[list[dict], list[dict]]:
        # No cache_control: the persona (~1.4K tokens) is far under Haiku 4.5's
        # 4096-token minimum cacheable prefix, so a breakpoint here never
        # activates. Per-call input is dominated by the unique facts packet.
        system = [{"type": "text", "text": self.persona}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the verdict line and the story."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: TradeStoryFacts) -> dict[str, str]:
        system, messages = self.build_request(facts)
        logger.info("Requesting trade story from %s (trade %s)",
                    self.model, facts.trade_id)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages,
        )
        report("public-dynasty", self.model, resp.usage)
        result = parse_story(resp.content[0].text)
        # Sanitize banned jargon, then apply always-safe repairs (dashes, headline
        # punctuation/markdown) to every rendered part. Semantic checks happen in
        # story_gen, which can regenerate; these transforms need no regeneration.
        result["verdict"] = tidy_headline(repair_prose(sanitize_prose(result["verdict"])))
        result["lede"] = repair_prose(sanitize_prose(result.get("lede", "")))
        result["beats"] = [repair_prose(sanitize_prose(b)) for b in result.get("beats", [])]
        result["body"] = repair_prose(sanitize_prose(result["body"]))
        result["_usage"] = usage_dict(resp.usage)
        return result
