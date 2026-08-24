"""RecapWriter: turn a facts packet into roast-comedy prose via Claude.

The system prompt (persona) is static and prompt-cached; the user turn carries
the league lore + the week's facts JSON. The model is instructed to use only
packet facts.
"""

from __future__ import annotations

import json
import logging
from importlib import resources

import anthropic

from sleeper_dynasty.llm._usage import usage_dict
from sleeper_dynasty.llm.usage import report
from sleeper_dynasty.models.recap import OutlookFacts, RecapFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096


def load_default_persona() -> str:
    """Load the built-in Analyst persona system prompt."""
    return resources.files(_PROMPTS).joinpath("analyst_persona.md").read_text()


def load_lore_template() -> str:
    """Load the starter league-lore template (for scaffolding a lore file)."""
    return (
        resources.files(_PROMPTS).joinpath("league_lore_template.md").read_text()
    )


class RecapWriter:
    """Generates recap prose from a facts packet using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        persona: str | None = None,
        cost_store=None,  # optional LlmCostStore instance
    ) -> None:
        self.model = model
        self.persona = persona or load_default_persona()
        # api_key=None lets the SDK read ANTHROPIC_API_KEY from the env.
        self._client = anthropic.Anthropic(api_key=api_key)
        self._cost_store = cost_store

    def build_request(
        self, facts: RecapFacts, lore: str | None,
        outlook: "OutlookFacts | None" = None,
    ) -> tuple[list[dict], list[dict]]:
        """Build the (system, messages) pair for the Messages API.

        The user turn carries optional lore + the facts JSON. No cache_control:
        the persona is under Haiku 4.5's 4096-token cache minimum, so a
        breakpoint here never activates.
        """
        system = [{"type": "text", "text": self.persona}]

        user_parts = []
        if lore:
            user_parts.append(
                "LEAGUE LORE (weave these in where relevant):\n\n" + lore
            )
        user_parts.append(
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite this week's segment."
        )
        if outlook is not None:
            user_parts.append(
                "OUTLOOK PACKET for the UPCOMING week (use ONLY these "
                "facts):\n\n```json\n"
                + json.dumps(outlook.to_dict(), indent=2)
                + "\n```"
            )
        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": "\n\n".join(user_parts)}],
        }]
        return system, messages

    def write(
        self, facts: RecapFacts, lore: str | None = None,
        outlook: "OutlookFacts | None" = None,
    ) -> str:
        """Call Claude and return the recap markdown.

        Raises anthropic.APIError subclasses on auth/rate-limit/timeout; the
        CLI surfaces an actionable message.
        """
        system, messages = self.build_request(facts, lore, outlook)
        logger.info("Requesting recap from %s (week %d)", self.model, facts.week)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )
        report("public-dynasty", self.model, resp.usage)
        if self._cost_store is not None:
            try:
                u = usage_dict(resp.usage)
                self._cost_store.record(
                    model=self.model,
                    writer="recap",
                    league_id="",
                    input_tokens=u["input_tokens"],
                    output_tokens=u["output_tokens"],
                    cache_read_input_tokens=u["cache_read_input_tokens"],
                    cache_creation_input_tokens=u["cache_creation_input_tokens"],
                )
            except Exception:
                logger.warning("failed to record recap LLM cost", exc_info=True)
        return resp.content[0].text
