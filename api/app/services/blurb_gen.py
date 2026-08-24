"""Eager + incremental + concurrent per-owner GM-rating blurb generation.

Mirrors story_gen.generate_stories: build a facts packet per (scope, owner),
skip any whose facts hash matches the prior cached blurb, generate the rest
concurrently with bounded retry, never fail the refresh.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.models.leaderboard import GMRow
from app.services.chain_cache import ChainCacheEntry
from app.services.leaderboard import build_leaderboard
from sleeper_dynasty.engine.gm_rating_blurb import build_owner_rating_facts
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash

log = logging.getLogger(__name__)

# Bump to force every cached GM blurb to regenerate on the next refresh even
# when its facts are unchanged (e.g. a persona/output-shape change). Folded into
# the skip-hash. "2" = added per-pillar highlights to the writer output.
# "4" = pillars follow the v2 tree (Results/Assets, not Results/Skill/Outlook)
# — every cached blurb was written about pillars that no longer exist, so all
# of them regenerate once past the offseason gate / time throttle.
BLURB_PROMPT_VERSION = "4"


def _scope_label(scope_key: str) -> str:
    return "career" if scope_key == "all" else f"the {scope_key} season"


def _facts_from_row(
    scope_key: str, row: GMRow, outcome_signals: dict[str, dict[str, float]],
) -> OwnerRatingFacts:
    facts = build_owner_rating_facts(
        scope_label=_scope_label(scope_key),
        owner_name=row.owner.owner_name,
        team_name=row.owner.team_name,
        rank=row.rank,
        rating=row.rating,
        pillars={p: pb.model_dump() for p, pb in row.pillars.items()},
        # championships/made_playoffs live in the persisted outcome_signals
        # rollup, not the (v2, scoring-only) pillar breakdown above — see
        # gm_rating_blurb.build_owner_rating_facts.
        outcome_signals=outcome_signals.get(row.user_id),
    )
    facts.user_id = row.user_id
    return facts


def owner_rating_facts_by_scope(
    entry: ChainCacheEntry,
) -> dict[str, dict[str, OwnerRatingFacts]]:
    """``{"all": {uid: facts}}`` — the all-time scope, and only that one.

    This used to loop the whole season list too, stamping "the 2023 season"
    into the packet the persona writes to. Under v2 there is no per-season
    rating to describe: ``live_ratings`` ignores ``year`` (the signals are
    all-time and recency-decayed), so every season scope handed Haiku a career
    grade labelled as that season's and paid for the sentence. A 5-season,
    12-owner league bought 72 calls of which 60 were fabrication — the same
    defect Task 6b closed for ``season_ratings``, one call site short.

    The old ``_scope_is_ratable`` gate went with them: it withheld the blurb
    (and with it the Overview tab's pillar highlights) unless two owners had
    traded, which was a v1 proxy for "the Skill pillar has something to say".
    v2 dropped Skill and every trade signal with it, so on a league of
    non-traders the gate suppressed prose about a grade trading never touched.
    Owners with no rating at all are already absent from the leaderboard rows
    (``franchise_redesign.rated_owners``), which is the gate that belongs here.
    """
    resp = build_leaderboard(entry, year="all", prev_ratings={})
    rows = {
        r.user_id: _facts_from_row("all", r, entry.outcome_signals)
        for r in resp.rows
    }
    return {"all": rows} if rows else {}


async def generate_owner_rating_blurbs(
    *,
    facts_by_scope: dict[str, dict[str, OwnerRatingFacts]],
    prior_blurbs: dict[str, dict[str, dict]],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,
    league_id: str = "",
    reuse_prior_on_throttle: bool = False,
) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    pending: list[tuple[str, str, OwnerRatingFacts, str]] = []

    for scope_key, owners in facts_by_scope.items():
        out.setdefault(scope_key, {})
        for uid, facts in owners.items():
            h = f"{rating_facts_hash(facts)}:{BLURB_PROMPT_VERSION}"
            prior = (prior_blurbs.get(scope_key) or {}).get(uid)
            if prior and (reuse_prior_on_throttle or prior.get("facts_hash") == h):
                out[scope_key][uid] = prior  # incremental skip (or throttled reuse)
                continue
            pending.append((scope_key, uid, facts, h))

    if not pending:
        return out

    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0

    async def _one(scope_key: str, uid: str, facts: OwnerRatingFacts, h: str):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("GM blurb generation failed for %s/%s", scope_key, uid)
                return
            # Extract and strip _usage before caching
            _usage = result.pop("_usage", None)
            if cost_store is not None and _usage is not None:
                try:
                    cost_store.record(
                        model=writer.model,
                        writer="gm_rating_blurb",
                        league_id=league_id,
                        input_tokens=_usage["input_tokens"],
                        output_tokens=_usage["output_tokens"],
                        cache_read_input_tokens=_usage.get("cache_read_input_tokens", 0),
                        cache_creation_input_tokens=_usage.get("cache_creation_input_tokens", 0),
                    )
                except Exception:
                    log.warning("failed to record gm_rating_blurb LLM cost", exc_info=True)
            out[scope_key][uid] = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        done += 1
        if progress_cb is not None:
            await progress_cb("owner_blurbs",
                              f"Writing GM profiles {done}/{len(pending)}")

    todo = pending
    for attempt in range(max(1, max_attempts)):
        if not todo:
            break
        if attempt > 0:
            log.warning("retrying %d GM blurb(s), round %d/%d",
                        len(todo), attempt + 1, max_attempts)
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)
        await asyncio.gather(*(_one(s, u, f, h) for s, u, f, h in todo))
        todo = [(s, u, f, h) for (s, u, f, h) in pending if u not in out.get(s, {})]

    if todo:
        log.error("%d GM blurb(s) still missing after %d attempts",
                  len(todo), max_attempts)
    return out
