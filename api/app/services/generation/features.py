"""Run bounded writers on immutable facts. Invalid output is never published."""
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.generation.store import digest
from sleeper_dynasty.llm.managed import ManagedClient


@dataclass(frozen=True)
class ValidatedOutput:
    payload: dict
    digest: str
    snapshot_digest: str
    stages: int


def validate(feature, result, facts):
    if feature == "trade_story":
        from sleeper_dynasty.llm.story_validation import find_violations
        prose = "\n".join([result.get("lede", ""), *(result.get("beats") or [])]).strip()
        prose = prose or result.get("body", "")
        errors = find_violations(result.get("verdict", ""), prose, facts)
        if not result.get("verdict") or not prose:
            errors.append("Provide a nonempty verdict and story")
        return errors
    if feature == "franchise_blurb":
        from sleeper_dynasty.llm.franchise_validation import find_violations
        body = result.get("body") or result.get("blurb", "")
        errors = find_violations(body, facts, lead=result.get("lead", ""))
        if not body or not result.get("lead"):
            errors.append("Provide a nonempty lead and body")
        return errors
    errors = []
    if not isinstance(result.get("blurb"), str) or not result["blurb"].strip():
        errors.append("Provide a nonempty GM profile")
    highlights = result.get("highlights", {})
    if not isinstance(highlights, dict):
        return [*errors, "Highlights must be an object"]
    for pillar, text in highlights.items():
        if pillar not in facts.pillars or not isinstance(text, str) or len(text.split()) > 16:
            errors.append("Use only supported pillar highlights of at most 16 words")
    return errors


async def generate(job, gateway):
    saved = json.loads(job.payload_json)
    policy = json.loads(job.policy_json)["policy"]["features"][job.feature]
    managed = ManagedClient(gateway, job.id, job.generation, asyncio.get_running_loop(), policy["max_tokens"])
    kwargs = {"model": policy["model"], "client": managed}

    def run():
        if job.feature == "analyst":
            from sleeper_dynasty.llm.recap_packet import ArchivedPacket
            from sleeper_dynasty.llm.recap_writer import RecapWriter
            edition = saved["edition"]
            writer = RecapWriter(**kwargs, review_model=policy["review_model"])
            markdown = writer.write(ArchivedPacket(edition["facts"]), lore=edition.get("lore"),
                outlook=ArchivedPacket(edition["outlook"]) if edition.get("outlook") else None)
            context = edition["facts"].get("player_context", {})
            return {**edition, "markdown": markdown, "edition_type": "roast",
                "model": policy["model"], "generated_at": datetime.now(UTC).isoformat(),
                "correction_note": job.reason, "sources": context.get("sources", []),
                "context_note": context.get("note")}
        if job.feature == "trade_story":
            from sleeper_dynasty.llm.trade_story_writer import TradeStoryWriter
            from sleeper_dynasty.models.trade_story import TradeStoryFacts
            writer, facts = TradeStoryWriter(**kwargs), TradeStoryFacts(**saved["facts"])
        elif job.feature == "gm_rating_blurb":
            from sleeper_dynasty.llm.gm_rating_blurb_writer import GmRatingBlurbWriter
            from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts
            writer, facts = GmRatingBlurbWriter(**kwargs), OwnerRatingFacts(**saved["facts"])
        elif job.feature == "franchise_blurb":
            from sleeper_dynasty.llm.franchise_outlook_writer import (
                FranchiseOutlookWriter,
            )
            from sleeper_dynasty.models.franchise_outlook import FranchiseFacts
            writer, facts = FranchiseOutlookWriter(**kwargs), FranchiseFacts(**saved["facts"])
        else:
            raise ValueError("Unregistered generation feature")
        for _ in range(min(2, job.max_calls)):
            result = writer.write(facts)
            result.pop("_usage", None)  # Gateway is the authoritative accounting record.
            errors = validate(job.feature, result, facts)
            if not errors:
                return {**result, "generated_at": datetime.now(UTC).isoformat(),
                    "generation_period": {"season": saved.get("season"), "week": saved.get("week")},
                    "facts_hash": job.request_digest}
            managed.feedback = errors
        raise ValueError("Content validation failed after the bounded correction: " + "; ".join(errors))
    result = await asyncio.to_thread(run)
    return ValidatedOutput(result, digest(result), digest(saved), managed.stage)
