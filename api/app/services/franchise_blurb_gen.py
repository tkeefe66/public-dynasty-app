"""Incremental generation of per-owner franchise blurbs (mirrors blurb_gen).

Retry/validation structure is ``story_gen``'s, deliberately: bounded rounds, a
deterministic validator that sends a violating blurb back for a fresh sample,
and a best-effort candidate promoted at the end so a flawed blurb still beats a
missing one.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sleeper_dynasty.llm.franchise_validation import find_violations
from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)

log = logging.getLogger(__name__)

# Bump when the franchise-blurb PROMPT or its validator changes in a way that
# should regenerate every cached blurb. The facts hash only moves on data
# changes, so a persona-only edit would otherwise be skipped forever. Folded
# into the stored hash below, the way STORY_PROMPT_VERSION and
# BLURB_PROMPT_VERSION are. Self-correcting: only the new code stamps it.
# v2: bounded/pruned facts packet (top-3 lists, neutral signals omitted),
#     league_format stated, young_core_share replaces mean roster age, the
#     invention ban widened to league mechanics, and a prose validator added.
# v3: the blurb is a LEAD plus a MARKED BODY. Every cached blurb has to
#     regenerate — a v2 record has no lead and no segments, so it would render
#     forever through the plain-text fallback and the emphasis would never
#     appear. Also raises the word cap 60 -> 75 and gives the persona a concrete
#     budget; the cap is part of the prompt contract, so it belongs on this
#     version rather than waiting for a facts change that may never come.
FRANCHISE_PROMPT_VERSION = "3"


async def generate_franchise_blurbs(
    *,
    facts_by_owner: dict[str, FranchiseFacts],
    prior_blurbs: dict[str, dict],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,
    league_id: str = "",
    reuse_prior_on_throttle: bool = False,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    pending: list[tuple[str, FranchiseFacts, str]] = []
    for uid, facts in facts_by_owner.items():
        h = f"{franchise_facts_hash(facts)}:{FRANCHISE_PROMPT_VERSION}"
        prior = prior_blurbs.get(uid)
        if prior and (reuse_prior_on_throttle or prior.get("facts_hash") == h):
            out[uid] = prior  # incremental skip (or throttled reuse)
            continue
        pending.append((uid, facts, h))

    if not pending:
        return out

    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0
    # Best-effort fallback: the most recent (possibly violating) blurb for an
    # owner, promoted after the loop so one that failed validation and then
    # errored on a later attempt still ships rather than vanishing.
    candidates: dict[str, dict] = {}

    async def _one(uid: str, facts: FranchiseFacts, h: str, is_last: bool):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("franchise blurb failed for %s", uid)
                return
            # Extract and strip _usage before caching
            _usage = result.pop("_usage", None)
            if cost_store is not None and _usage is not None:
                try:
                    cost_store.record(
                        model=writer.model,
                        writer="franchise_blurb",
                        league_id=league_id,
                        input_tokens=_usage["input_tokens"],
                        output_tokens=_usage["output_tokens"],
                        cache_read_input_tokens=_usage.get("cache_read_input_tokens", 0),
                        cache_creation_input_tokens=_usage.get("cache_creation_input_tokens", 0),
                    )
                except Exception:
                    log.warning("failed to record franchise_blurb LLM cost", exc_info=True)
            blurb = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            candidates[uid] = blurb  # keep the latest even if it violates
            # The MARKED body, not the stripped `blurb`: stripped text has no
            # tags left, so validating it would silently pass every malformed
            # mark. `find_violations` strips internally for the checks that
            # want plain text. `body` falls back to `blurb` for a pre-marks
            # cached shape, where the two are the same thing.
            violations = find_violations(
                result.get("body") or result.get("blurb", ""), facts,
                lead=result.get("lead", ""))
            if violations and not is_last:
                log.warning("franchise blurb %s has violations, regenerating: %s",
                            uid, "; ".join(violations))
                return  # leave out of `out` so the loop retries it
            if violations:
                log.warning("franchise blurb %s shipped with violations "
                            "(attempts exhausted): %s", uid, "; ".join(violations))
            out[uid] = blurb
        done += 1
        if progress_cb is not None:
            await progress_cb("franchise_blurbs",
                              f"Writing franchise outlooks {done}/{len(pending)}")

    todo = pending
    rounds = max(1, max_attempts)
    for attempt in range(rounds):
        if not todo:
            break
        if attempt > 0:
            log.warning("retrying %d franchise blurb(s), round %d/%d",
                        len(todo), attempt + 1, max_attempts)
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)
        is_last = attempt == rounds - 1
        await asyncio.gather(*(_one(u, f, h, is_last) for u, f, h in todo))
        todo = [(u, f, h) for (u, f, h) in pending if u not in out]

    for uid, blurb in candidates.items():
        out.setdefault(uid, blurb)

    still_missing = [u for (u, _, _) in pending if u not in out]
    if still_missing:
        log.error("%d franchise blurb(s) still missing after %d attempts",
                  len(still_missing), max_attempts)
    return out
