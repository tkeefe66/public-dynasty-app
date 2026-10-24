"""GM Leaderboard service: ChainCacheEntry -> LeaderboardResp.

Reuses the dashboard's per-owner aggregation (``_aggregate_owner_rows`` +
``_filter_trades_by_year``) for the display fields, and routes the rating itself
through ``franchise_redesign.live_ratings`` (the v2 Results/Assets tree — no
Skill pillar; redraft scores Results only — the single live rating source).
Trend is derived here (prior-week snapshot ranks minus current rank), never
stored on the row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.leaderboard import (
    GMRow, LeaderboardResp, PillarBreakdown,
)
from app.services.aggregations import (
    Year,
    _aggregate_owner_rows,
    _filter_trades_by_year,
)
from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import live_ratings
from app.services.identity import owner_ref
from sleeper_dynasty.engine.capabilities import capabilities_from_dict
from app.services.rating_snapshot_store import RatingSnapshotStore, snapshot_model
from sleeper_dynasty.engine.gm_rating import rating_to_letter


def all_time_ratings(entry: ChainCacheEntry) -> dict[str, int]:
    """All-time ``{uid: rating}`` for the league — the snapshot payload the
    refresh path persists per NFL week."""
    return {uid: r["rating"] for uid, r in live_ratings(entry).items()}


def compute_season_ratings(entry: ChainCacheEntry) -> dict[str, dict[str, int]]:
    """Keep legacy rank-change baselines disabled.

    Dated ratings now resolve from season_rating_inputs, but their eligible
    owner populations and evidence coverage can differ. They must not silently
    become comparable rank-change baselines or change All's existing KPI.
    """
    return {}


def build_leaderboard(
    entry: ChainCacheEntry,
    *,
    year: Year,
    prev_ratings: dict[str, int],
) -> LeaderboardResp:
    rows = _aggregate_owner_rows(entry, _filter_trades_by_year(entry, year))
    ratings = live_ratings(entry, year=year)
    from app.services.season_ratings import rating_scope, scoped_rating_entry
    rating_entry = scoped_rating_entry(entry, year)

    # Same gate aggregations.py uses for the standings row's roster_rank/of
    # (_outlooks_apply): a redraft league carries no roster to rank between
    # seasons, so it stays None rather than reading entry.roster_ranks at
    # all. Not recomputed here — roster_ranks is already persisted at refresh.
    _outlooks_apply = capabilities_from_dict((rating_entry or entry).capabilities).format != "redraft"
    roster_ranks = (rating_entry.roster_ranks or {}) if _outlooks_apply and rating_entry else {}

    # Unrated owners (no completed season — franchise_redesign.rated_owners)
    # are absent from `ratings` and so never reach a row. This board *is* a
    # ranking; there is nothing to rank an owner on who has played nothing,
    # and slotting him in would either invent a rating or push a placeholder
    # rank onto the rated owners around him. He still appears everywhere the
    # league's roster of owners is listed — standings and the Owners tab —
    # with an em dash where the letter goes.
    ordered = sorted(
        (r for r in rows.values() if r["user_id"] in ratings),
        key=lambda r: (
            ratings[r["user_id"]]["rating"],
            r["production_playoff"],
            r["net_ktc"],
        ),
        reverse=True,
    )
    # Prior ranks from the prev snapshot (rank by prior rating desc).
    prev_rank = {
        uid: i + 1
        for i, (uid, _) in enumerate(
            sorted((prev_ratings if year == "all" else {}).items(), key=lambda kv: kv[1], reverse=True)
        )
    }

    scope_key = "all" if year == "all" else str(year)
    # Existing saved year blurbs described the old current-career model.
    blurbs_for_scope = (entry.owner_rating_blurbs or {}).get(scope_key, {}) if year == "all" else {}

    out_rows: list[GMRow] = []
    for i, r in enumerate(ordered):
        uid = r["user_id"]
        rt = ratings[uid]
        pr = prev_rank.get(uid)
        out_rows.append(
            GMRow(
                rank=i + 1,
                user_id=uid,
                owner=owner_ref(entry, uid),
                rating=rt["rating"],
                letter=rating_to_letter(rt["rating"]),
                model=rt["model"],
                pillars={p: PillarBreakdown(**pd) for p, pd in rt["pillars"].items()},
                trend=(pr - (i + 1)) if pr else 0,
                trades=r["trades"],
                net_ktc=r["net_ktc"],
                production_regular=r["production_regular"],
                production_playoff=r["production_playoff"],
                production_toilet=r["production_toilet"],
                blurb=(blurbs_for_scope.get(uid) or {}).get("blurb"),
                roster_rank=(roster_ranks.get(uid) or {}).get("rank"),
                roster_of=(roster_ranks.get(uid) or {}).get("of"),
            )
        )

    return LeaderboardResp(
        rating_scope=rating_scope(entry, year),
        league_id=entry.league_id,
        scope=scope_key,
        rows=out_rows,
        generated_at=entry.cached_at,
    )


def load_prev_ratings(
    cache_dir: Path, league_id: str, *, model: str, owner_identity_version: str = ""
) -> dict[str, int]:
    """The snapshot from the most recent NFL week *before* the latest one on
    file *for this rating model*. The refresh path writes the current week's
    snapshot, so the latest same-model key is "now" and the one before it is
    the trend baseline. Empty when there is no earlier same-model week --
    either a first-ever snapshot, or the only history on file belongs to a
    different model (e.g. right after a rating redesign ships): that
    degrades to "no trend" rather than diffing against a number the new
    model can't compare itself to."""
    model = snapshot_model(model, owner_identity_version)
    store = RatingSnapshotStore(cache_dir=cache_dir)
    prefix = f"{model}:"
    same_model_weeks = [
        k[len(prefix):] for k in store.read(league_id) if k.startswith(prefix)
    ]
    if len(same_model_weeks) < 2:
        return {}
    latest_key = max(same_model_weeks)
    return store.latest_before(league_id, latest_key, model=model)
