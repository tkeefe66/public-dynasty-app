"""GmRatingBlurbWriter: turn an OwnerRatingFacts packet into one paragraph.

Mirrors TradeStoryWriter: a static persona system block plus a user turn
carrying the facts JSON. The model uses only packet facts.
"""

from __future__ import annotations

import json
import logging
import re
from importlib import resources

import anthropic

from sleeper_dynasty.llm._usage import usage_dict
from sleeper_dynasty.llm.usage import report
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 768

# Pillar-highlight labels the model may return in its JSON. v2 tree: Results
# (always present) and Assets (dropped for redraft, nothing carries over).
# Each label's packet key is exactly its lowercase form, so no separate
# label->key map is needed the way the retired three-pillar set required.
_PILLAR_KEYS = {"Results", "Assets"}


def load_blurb_persona() -> str:
    return resources.files(_PROMPTS).joinpath("gm_rating_blurb_persona.md").read_text()


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip())


def parse_blurb(text: str) -> dict:
    """Parse the model's JSON output into ``{blurb, pillars?}``.

    Expects ``{"blurb": "...", "highlights": {"Outcomes": "...", ...}}``. Strips a
    markdown fence if present. Falls back to treating the whole output as the
    paragraph (no pillars) when it isn't valid JSON, so a malformed response still
    yields a usable blurb.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()).strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"blurb": _collapse(cleaned)}

    result: dict = {"blurb": _collapse(data.get("blurb", ""))}
    highlights = data.get("highlights")
    if isinstance(highlights, dict):
        pillars = {
            label.lower(): _collapse(highlights[label])
            for label in _PILLAR_KEYS
            if highlights.get(label)
        }
        if pillars:
            result["pillars"] = pillars
    return result


class GmRatingBlurbWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_blurb_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: OwnerRatingFacts) -> tuple[list[dict], list[dict]]:
        # No cache_control: persona is under Haiku 4.5's 4096-token cache
        # minimum, so a breakpoint here never activates. See trade_story_writer.
        system = [{"type": "text", "text": self.persona}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the one-paragraph profile."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: OwnerRatingFacts) -> dict[str, str]:
        system, messages = self.build_request(facts)
        logger.info("Requesting GM blurb from %s (owner %s, %s)",
                    self.model, facts.owner_name, facts.scope_label)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages,
        )
        report("public-dynasty", self.model, resp.usage)
        result = parse_blurb(resp.content[0].text)
        result["_usage"] = usage_dict(resp.usage)
        return result
