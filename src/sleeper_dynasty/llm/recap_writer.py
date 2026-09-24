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
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

from sleeper_dynasty.llm._usage import usage_dict
from sleeper_dynasty.llm.trade_story_writer import sanitize_prose
from sleeper_dynasty.llm.usage import report
from sleeper_dynasty.models.recap import OutlookFacts, RecapFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
# Full matchup recaps plus standings, bets and outlook can exceed 4096 tokens.
MAX_TOKENS = 8192
REVIEW_MAX_TOKENS = 4096
REVIEW_TOOL: anthropic.types.ToolParam = {
    "name": "submit_recap_review",
    "description": (
        "Submit the factual audit of the complete recap against its evidence. "
        "Set approved to true only when every claim is supported. "
        "List specific unsupported claims in violations; an approved draft has none."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {"type": "boolean"},
            "violations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["approved", "violations"],
        "additionalProperties": False,
    },
}


def load_default_persona() -> str:
    """Load the built-in Analyst persona system prompt."""
    return resources.files(_PROMPTS).joinpath("analyst_persona.md").read_text()


def load_lore_template() -> str:
    """Load the starter league-lore template (for scaffolding a lore file)."""
    return resources.files(_PROMPTS).joinpath("league_lore_template.md").read_text()


class RecapWriter:
    """Generates recap prose from a facts packet using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        persona: str | None = None,
        cost_store=None,  # optional LlmCostStore instance
        league_id: str = "",
    ) -> None:
        self.model = model
        self.persona = persona or load_default_persona()
        # api_key=None lets the SDK read ANTHROPIC_API_KEY from the env.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=90.0, max_retries=2)
        self._cost_store = cost_store
        self._league_id = league_id

    def build_request(
        self,
        facts: RecapFacts,
        lore: str | None,
        outlook: OutlookFacts | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Build the (system, messages) pair for the Messages API.

        The user turn carries optional lore + the facts JSON. No cache_control:
        the persona is under Haiku 4.5's 4096-token cache minimum, so a
        breakpoint here never activates.
        """
        system = [{"type": "text", "text": self.persona}]

        user_parts = []
        if lore:
            user_parts.append("LEAGUE LORE (weave these in where relevant):\n\n" + lore)
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
        messages = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "\n\n".join(user_parts)}],
            }
        ]
        return system, messages

    def _request(self, system, messages, *, stage: str) -> anthropic.types.Message:
        logger.info("Requesting %s from %s", stage, self.model)
        review = stage == "recap_review"
        options: MessageCreateParamsNonStreaming = {
            "model": self.model,
            "max_tokens": REVIEW_MAX_TOKENS if review else MAX_TOKENS,
            "system": system,
            "messages": messages,
        }
        if review:
            options["tools"] = [REVIEW_TOOL]
            options["tool_choice"] = {"type": "tool", "name": REVIEW_TOOL["name"]}
        resp = self._client.messages.create(**options)
        report("public-dynasty", self.model, resp.usage)
        if self._cost_store is not None:
            try:
                u = usage_dict(resp.usage)
                self._cost_store.record(
                    model=self.model,
                    writer=stage,
                    league_id=self._league_id,
                    input_tokens=u["input_tokens"],
                    output_tokens=u["output_tokens"],
                    cache_read_input_tokens=u["cache_read_input_tokens"],
                    cache_creation_input_tokens=u["cache_creation_input_tokens"],
                )
            except Exception:
                logger.warning("failed to record recap LLM cost", exc_info=True)
        logger.info(
            "Analyst %s response: stop_reason=%s output_tokens=%s",
            stage,
            resp.stop_reason,
            resp.usage.output_tokens,
        )
        if resp.stop_reason == "max_tokens":
            raise ValueError(f"Analyst {stage} was truncated; refusing publication")
        return resp

    def write(
        self,
        facts: RecapFacts,
        lore: str | None = None,
        outlook: OutlookFacts | None = None,
    ) -> str:
        """Generate once, then require a separate factual review before saving.

        The review is an additional model-based safeguard, not a proof of truth.
        Provider failures, malformed verdicts and flagged claims fail closed.
        No paid retry loop occurs within an edition attempt.
        """
        system, messages = self.build_request(facts, lore, outlook)
        draft = self._request(system, messages, stage="recap")
        text = sanitize_prose(
            "\n".join(block.text for block in draft.content if block.type == "text")
        )
        if not text.strip():
            raise ValueError("Analyst recap returned no text; retry generation")
        review_prompt = (
            resources.files(_PROMPTS).joinpath("analyst_review.md").read_text()
        )
        evidence = {
            "facts": facts.to_dict(),
            "outlook": outlook.to_dict() if outlook else None,
            "draft": text,
        }
        review = self._request(
            [{"type": "text", "text": review_prompt}],
            [{"role": "user", "content": json.dumps(evidence)}],
            stage="recap_review",
        )
        # Tool input is decoded by the SDK, independent of Markdown fences or
        # explanatory text. Never guess a verdict from arbitrary response text.
        verdicts = [block for block in review.content if block.type == "tool_use"]
        if (
            review.stop_reason != "tool_use"
            or len(verdicts) != 1
            or verdicts[0].name != REVIEW_TOOL["name"]
        ):
            raise ValueError(
                "Analyst review returned no single structured verdict; refusing publication"
            )
        verdict = verdicts[0].input
        if (
            not isinstance(verdict, dict)
            or verdict.get("approved") is not True
            or verdict.get("violations") != []
        ):
            logger.warning(
                "Analyst factual review rejected week %s: %s", facts.week, verdict
            )
            raise ValueError(
                "Analyst factual review did not approve the draft; refusing publication"
            )
        return text
