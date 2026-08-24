from __future__ import annotations

from pydantic import BaseModel

from app.models.common import OwnerRef


class SignalBreakdown(BaseModel):
    raw: float
    z: float
    weight: float
    contribution: int


class PillarBreakdown(BaseModel):
    """One pillar's contribution + its per-signal breakdown (full transparency)."""

    weight: float
    z: float
    contribution: int
    signals: dict[str, SignalBreakdown]
    # signal key -> this owner's rank on that signal's RAW value among the
    # rated population, 1 = best (highest raw). Read-time only: written to no
    # ChainCacheEntry field, because persisting it would reopen the schema
    # question the Assets-led Outlook redesign closed by not bumping.
    #
    # It lives HERE rather than being passed alongside because leaderboard.py
    # rebuilds pillars through `PillarBreakdown(**pd)` and Pydantic drops an
    # extra key -- a rank populated anywhere else silently never arrives.
    # This is a public /gm response-shape change.
    signal_ranks: dict[str, int] = {}


class GMRow(BaseModel):
    rank: int
    user_id: str
    owner: OwnerRef
    rating: int
    letter: str = "C"     # Franchise Rating letter (rating_to_letter); platform headline
    # Which weight tree produced this rating ("v2_dynasty" | "v2_keeper" |
    # "v2_redraft"; see franchise_redesign.model_for — v1's results_led /
    # keeper_led / redraft_led are retired). A rating pooled without knowing
    # which tree produced it is uninterpretable. Required, not defaulted:
    # live_ratings always stamps it, and a default here could only ever mask a
    # caller that forgot to.
    model: str
    pillars: dict[str, PillarBreakdown]   # v2: results / assets
    trend: int            # prev_rank - rank: +up, -down, 0 flat/new
    trades: int
    net_ktc: float
    production_regular: float
    production_playoff: float
    production_toilet: float = 0.0
    blurb: str | None = None   # LLM-written per-scope profile
    # Today's roster-value rank among the league (1 = strongest roster).
    # Mirrors StandingRow.roster_rank/roster_of (api/app/models/league.py) —
    # None together for a redraft league, since nothing carries over between
    # seasons there, so there is no roster to rank. Populated in
    # leaderboard.py from the same entry.roster_ranks source aggregations.py
    # reads, gated the same way.
    roster_rank: int | None = None
    roster_of: int | None = None


class LeaderboardResp(BaseModel):
    league_id: str
    scope: str            # "all" or the season as a string
    rows: list[GMRow]
    generated_at: str
