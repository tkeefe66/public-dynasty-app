"""LLM writer for the franchise-outlook blurb (mirrors gm_rating_blurb_writer)."""

from __future__ import annotations

import json
import logging
import re
from importlib import resources

import anthropic

from sleeper_dynasty.llm._usage import usage_dict
from sleeper_dynasty.llm.franchise_marks import (
    normalize_markup, parse_segments, strip_marks,
)
from sleeper_dynasty.llm.usage import report
from sleeper_dynasty.models.franchise_outlook import FranchiseFacts

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400
_PROMPTS = "sleeper_dynasty.llm.prompts"


def load_franchise_persona() -> str:
    return resources.files(_PROMPTS).joinpath("franchise_outlook_persona.md").read_text()


def _collapse(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def parse_franchise(text: str) -> dict:
    """Model output -> ``{lead, body, blurb, segments}``.

    Expects ``{"lead": "...", "body": "...[num]73%[/num]..."}``, the JSON shape
    ``gm_rating_blurb_writer.parse_blurb`` already uses, with a markdown fence
    stripped if present. Four fields come out and each has one consumer, so none
    has to be re-derived downstream:

    ``lead``      the opening claim, set large.
    ``body``      the MARKED source. The validator reads this — checking marks
                  against stripped text would have nothing to check.
    ``blurb``     the body with tags removed. This is what the word cap counts
                  and what the plain-text fallback renders, and it is the field
                  older cached entries already carry, so its meaning is
                  unchanged for anything reading the cache.
    ``segments``  ``[{text, mark}]``. The renderer maps these to React elements,
                  which is what keeps model output off any HTML path.

    A response that is not JSON falls back to the whole output as plain prose
    with no lead — a malformed sample still ships a readable paragraph rather
    than an empty panel.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip()).strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("not an object")
        lead, raw_body = _collapse(data.get("lead")), data.get("body")
    except (json.JSONDecodeError, ValueError, TypeError):
        lead, raw_body = "", cleaned

    body = normalize_markup(raw_body)
    return {
        "lead": lead,
        "body": body,
        "blurb": strip_marks(body),
        "segments": parse_segments(body),
    }


class FranchiseOutlookWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_franchise_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: FranchiseFacts) -> tuple[list[dict], list[dict]]:
        # No cache_control: persona is under Haiku 4.5's 4096-token cache
        # minimum, so a breakpoint here never activates. See trade_story_writer.
        system = [{"type": "text", "text": self.persona}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the franchise outlook as the JSON object "
            "described above."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: FranchiseFacts) -> dict:
        system, messages = self.build_request(facts)
        logger.info("Requesting franchise blurb from %s (owner %s)",
                    self.model, facts.owner_name)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages,
        )
        report("public-dynasty", self.model, resp.usage)
        result = parse_franchise(resp.content[0].text)
        result["_usage"] = usage_dict(resp.usage)
        return result
