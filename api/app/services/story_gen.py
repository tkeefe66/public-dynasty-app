"""Eager + incremental + concurrent trade-story generation.

Called from GraderService.run after grading. Reuses the engine fact-builders;
the writer is injected so tests can fake it (no live Anthropic calls).

Resilient to transient Anthropic throttling: any trade whose story call fails
(after the SDK's own retries) is re-attempted in a follow-up round, up to
``max_attempts`` rounds total, with ``retry_delay`` seconds between rounds to let
overload subside. A trade that still fails after every round is left without a
story (a refresh never fails on a story error); the next refresh backfills it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sleeper_dynasty.engine.trade_story import (
    build_owner_strategy, build_trade_story_facts,
)
from sleeper_dynasty.llm.story_validation import find_violations
from sleeper_dynasty.models.trade_story import facts_hash

log = logging.getLogger(__name__)

# Bump when the trade-story PROMPT changes in a way that should regenerate every
# cached story (the facts_hash only moves on data changes, so a prompt-only edit
# would otherwise be skipped forever). Folded into the stored hash below.
# v2: forbid bare positional/role epithets for traded players (name collisions
#     read as reversed trade direction).
# v3: point-in-time owner tilt (per-trade strategy excludes later trades) +
#     deterministic KTC-leak sanitizer in the writer.
# v4: per-side received_summary + deterministic this_trade_tilt / fits_career_tilt
#     so the writer stops pasting the owner's career-pattern direction onto a
#     trade that opposes it ("sold the receiver he actually bought").
# v5: structured output — verdict + lede + 2-4 bullet beats (was a paragraph body).
# v6: season_underway fact + persona rule — a not-yet-started season's all-zero
#     arcs must read as "not yet", never "never played / scored nothing".
STORY_PROMPT_VERSION = "6"


async def generate_stories(
    *,
    resolved: list,
    grades: dict[str, dict],
    supporting: dict[str, Any],
    prior_stories: dict[str, dict],
    writer,
    resolved_dicts: list[dict] | None = None,
    current_holders: dict[str, str] | None = None,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,
    league_id: str = "",
    reuse_prior_on_throttle: bool = False,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (trade_stories, owner_dossiers)."""
    owners_display = supporting["owners_display"]
    # Career-wide strategy for the owner DOSSIERS (the per-owner view wants the
    # whole record). Each TRADE's facts instead get a point-in-time strategy
    # (below) so a story never describes a deal using trades made after it.
    owner_strategy = build_owner_strategy(resolved, grades, owners_display)
    dossiers = {uid: f.to_dict() for uid, f in owner_strategy.items()}

    # Build facts for every trade, then decide what needs (re)generation.
    pending: list[tuple[str, Any, str]] = []
    stories: dict[str, dict] = {}
    for rt in resolved:
        tx = rt.trade.transaction_id
        # Pattern as it stood up to this deal (excludes this trade and later).
        as_of_strategy = build_owner_strategy(
            resolved, grades, owners_display, as_of=rt.trade.traded_at)
        facts = build_trade_story_facts(
            rt=rt, grade=grades.get(tx) or {}, owner_strategy=as_of_strategy,
            owners_display=owners_display,
            matchups=supporting["matchups"],
            roster_to_user_by_league=supporting["roster_to_user_by_league"],
            playoff_weeks_by_league=supporting["playoff_weeks_by_league"],
            league_season_by_id=supporting["league_season_by_id"],
            positions=supporting.get("positions") or {},
            resolved_trades=resolved_dicts,
            current_holders=current_holders or {},
        )
        h = f"{facts_hash(facts)}:{STORY_PROMPT_VERSION}"
        prior = prior_stories.get(tx)
        # Reuse the cached story when its facts are materially unchanged, or
        # when throttled (reuse everything that already has a story; brand-new
        # trades below still generate).
        if prior and (reuse_prior_on_throttle or prior.get("facts_hash") == h):
            stories[tx] = prior
            continue
        pending.append((tx, facts, h))

    if not pending:
        return stories, dossiers

    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0
    # Best-effort fallback: the most recent (possibly flawed) story for a trade,
    # promoted after the loop so a trade that produced a violating story but then
    # errored on a later attempt still ships rather than vanishing.
    candidates: dict[str, dict] = {}

    async def _one(tx: str, facts, h: str, is_last: bool):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("trade story generation failed for %s", tx)
                return
            # Extract and strip _usage before caching
            _usage = result.pop("_usage", None)
            if cost_store is not None and _usage is not None:
                try:
                    cost_store.record(
                        model=writer.model,
                        writer="trade_story",
                        league_id=league_id,
                        input_tokens=_usage["input_tokens"],
                        output_tokens=_usage["output_tokens"],
                        cache_read_input_tokens=_usage.get("cache_read_input_tokens", 0),
                        cache_creation_input_tokens=_usage.get("cache_creation_input_tokens", 0),
                    )
                except Exception:
                    log.warning("failed to record trade_story LLM cost", exc_info=True)
            story = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            candidates[tx] = story  # keep the latest even if it has violations
            # Deterministic backstop: a story that reverses trade direction, uses a
            # bare positional epithet, or runs the headline too long is regenerated
            # (the next sample usually fixes a stochastic slip). On the final round
            # we ship it anyway -- a flawed story beats a missing one.
            # Validate over verdict + the full rendered prose (lede + beats).
            _prose = "\n".join(
                [result.get("lede", "")] + (result.get("beats") or [])
            ).strip() or result.get("body", "")
            violations = find_violations(
                result.get("verdict", ""), _prose, facts)
            if violations and not is_last:
                log.warning("trade story %s has violations, regenerating: %s",
                            tx, "; ".join(violations))
                return  # leave out of `stories` so the loop retries it
            if violations:
                log.warning("trade story %s shipped with violations "
                            "(attempts exhausted): %s", tx, "; ".join(violations))
            stories[tx] = story
        done += 1
        if progress_cb is not None:
            await progress_cb("stories",
                              f"Writing trade stories {done}/{len(pending)}",
                              done=done, total=len(pending))

    # Generate, then backfill any trades still missing after transient failures
    # or content violations.
    todo = pending
    rounds = max(1, max_attempts)
    for attempt in range(rounds):
        if not todo:
            break
        if attempt > 0:
            log.warning("retrying %d trade story(ies), round %d/%d",
                        len(todo), attempt + 1, max_attempts)
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)
        is_last = attempt == rounds - 1
        await asyncio.gather(*(_one(tx, f, h, is_last) for tx, f, h in todo))
        todo = [(tx, f, h) for (tx, f, h) in pending if tx not in stories]

    # Ship any best-effort candidate for a trade still missing (e.g. it produced
    # a violating story, then errored on the final attempt).
    for tx, story in candidates.items():
        stories.setdefault(tx, story)

    still_missing = [tx for (tx, _, _) in pending if tx not in stories]
    if still_missing:
        log.error("%d trade story(ies) still missing after %d attempts",
                  len(still_missing), max_attempts)

    return stories, dossiers
