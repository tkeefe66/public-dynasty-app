from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.common import OwnerRef


class LeagueSummary(BaseModel):
    league_id: str
    name: str
    season: int
    total_rosters: int
    status: str
    seasons: list[int] | None = None
    last_refreshed: str | None = None


class HeroStat(BaseModel):
    value: str
    context: str
    label: str | None = None
    owner: str | None = None
    owner_user_id: str | None = None
    trade_id: str | None = None
    date: str | None = None
    counterparty: str | None = None
    counterparty_user_id: str | None = None


class HeroStats(BaseModel):
    top_gm: HeroStat
    biggest_weekly_rise: HeroStat
    best_roster: HeroStat
    draft_ace: HeroStat


class StandingRow(BaseModel):
    rank: int
    user_id: str
    owner: OwnerRef
    net_ktc: float
    production_total: float
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    # Starters-only across every week. NOT regular + playoff + toilet: playoff
    # counts live title-path games only, so started points in a placement game
    # or an eliminated week belong to no phase (measured: 14 of 52 non-zero
    # owner/trade pairs differ, by up to 23.6 points).
    production_started: float = 0.0
    trades: int
    grade: str
    net_ktc_at_trade: float = 0.0
    net_ktc_aged: float = 0.0
    # GM intelligence fields (None when entry has no signals yet)
    gm_rating: int | None = None
    gm_letter: str | None = None   # Franchise Rating letter (gm_rating → letter)
    gm_rank: int | None = None
    gm_trend: int = 0
    # The competitive-window stage, DERIVED from `gm_rating` on the same line
    # (gm_rating.py::rating_to_stage) — not a second model. None for an
    # unrated franchise and for a redraft league, which has no Outlook layer
    # at all; the frontend omits the column entirely on that signal rather
    # than ruling it out as a row of em-dashes.
    window: str | None = None
    # None (not 0.0) when the league has no Outlook layer at all — redraft.
    # 0.0 still means "dynasty owner holding no future picks"; the frontend
    # omits the column only when NO row carries a value.
    draft_capital_value: float | None = 0.0
    season_record: str | None = None   # "8-5" (year view) or "32-24" (all-time)
    best_finish: str | None = None     # "3rd" (year view) or "Won 2×" (all-time)
    season_wins: int | None = None     # numeric wins for sorting
    season_rank: int | None = None     # final rank (1-based) for sorting; None on all-time
    playoff_record: str | None = None  # career playoff W-L e.g. "4-0" (all-time only)
    # Where this owner's current roster ranks by value among the league (1 =
    # best). Read straight off entry.roster_ranks (already computed at
    # refresh; never recomputed here). None (not 0, not blank) alongside the
    # other Outlook-derived columns when the league has no roster to rank
    # (redraft) - the frontend omits the column entirely on that signal, same
    # as window/draft_capital_value above.
    roster_rank: int | None = None
    roster_of: int | None = None


class LatestTrade(BaseModel):
    trade_id: str
    date: str
    week: int
    parties: list[OwnerRef]
    assets_short: str
    swing_ktc: float
    swing_prod: float
    # The dashboard lead names a winner. Both are derived at response time from
    # the grade blob (no cache field, no SCHEMA_VERSION bump). None when the
    # grade blob is missing or carries fewer than two graded sides.
    value_winner: OwnerRef | None = None
    production_winner: OwnerRef | None = None
    # (value winner's received total, the other side's) — ordered by the VALUE
    # winner so the lead's left-hand figure is always the same person. Only for
    # exactly-two-side trades; None otherwise.
    production_split: tuple[float, float] | None = None


class Records(BaseModel):
    biggest_value_swing: float
    biggest_value_swing_owner: str | None = None
    biggest_value_swing_owner_user_id: str | None = None
    biggest_production: float
    biggest_production_owner: str | None = None
    biggest_production_owner_user_id: str | None = None
    biggest_playoff: float
    biggest_playoff_owner: str | None = None
    biggest_playoff_owner_user_id: str | None = None
    most_trades: int
    most_trades_owner: str | None = None
    most_trades_owner_user_id: str | None = None


Lens = Literal["ktc", "production"]
Year = int | Literal["all"]


class BracketWatch(BaseModel):
    """Live title-path state for the postseason lead
    (engine/playoff_phase.py::build_bracket_watch).

    `top_seed` is regular-season rank (1 = best) among owners still alive, and
    is null when seeds aren't known — an unnamed cell beats a wrong one.
    `playoff_points_leader` is the trade metric, matching the rest of the app:
    points from players an owner *received in trades*, scored in live
    title-path games. Null when nobody has any.
    """

    season: int
    entered: int
    alive_count: int
    alive: list[OwnerRef] = Field(default_factory=list)
    top_seed_owner: OwnerRef | None = None
    top_seed: int | None = None
    playoff_points_leader: OwnerRef | None = None
    playoff_points: float | None = None


class DraftReviewPick(BaseModel):
    """One pick, graded against its own draft class (``best``/``worst``) or
    against draft-day consensus (``best_value``/``reach``) — never both on
    the same row, so the unused pair stays null rather than fabricated."""

    player_id: str
    full_name: str
    position: str = ""
    drafter_id: str
    owner: OwnerRef | None = None
    round: int
    slot: int
    draft_position: int          # overall pick number (round 2 slot 1 = 13th)
    production_total: float | None = None
    slot_delta: int | None = None        # positive = finished ahead of where he went
    # Pick number minus consensus rank (rookie ECR, else Sleeper ADP):
    # positive = fell past consensus (a steal), negative = a reach. Needs no
    # played game, so it's set on best_value/reach even while the class is
    # still ungraded.
    baseline_delta: float | None = None
    baseline_source: str = ""


class DraftReview(BaseModel):
    """How the most recent draft panned out
    (engine/draft_results.py::build_draft_review).

    Drives the draft-window lead. Each pick is ranked against its own class
    rather than an external baseline, so no ADP table or positional model is
    needed.

    ``graded`` is False for a class that has not played yet — the results are
    real the moment the draft completes, but a "best pick" chosen out of an
    all-zero field would be invented. Consumers render results and omit the
    grade rather than falling back. ``best_value``/``reach`` are the
    ungraded window's story instead: draft-day value vs consensus, which
    needs no played game and so is set whenever the class has at least two
    picks matched to a baseline — ``matched`` reports that coverage, since a
    thin-coverage class (e.g. a redraft league before the first ADP
    snapshot) should fall back rather than print a hollow "best value".
    """

    season: int
    graded: bool = True
    best: DraftReviewPick | None = None
    worst: DraftReviewPick | None = None
    beat_slot: int
    total: int
    best_value: DraftReviewPick | None = None
    reach: DraftReviewPick | None = None
    matched: int = 0


class WeekRecapFigure(BaseModel):
    """One owner and one figure — the shape both the high score and the
    traded-points line take."""

    user_id: str
    owner: OwnerRef | None = None
    points: float


class WeekRecapBlowout(BaseModel):
    winner_user_id: str
    winner: OwnerRef | None = None
    loser_user_id: str
    loser: OwnerRef | None = None
    margin: float


class WeekRecap(BaseModel):
    """The most recent COMPLETED regular-season week (services/week_recap.py).

    Never an in-progress week: the recap week is strictly earlier than Sleeper's
    current week, so a partial Sunday score can't reach the lead. `traded_points`
    is null when no owner started a trade-acquired player for points.
    """

    season: str
    week: int
    high_score: WeekRecapFigure
    blowout: WeekRecapBlowout
    traded_points: WeekRecapFigure | None = None


class LeagueCapabilitiesResp(BaseModel):
    """What this league supports (see engine/capabilities.py). Drives which
    sections the UI renders at all — absence, never an empty state."""

    format: Literal["dynasty", "keeper", "redraft"] = "dynasty"
    future_picks: bool = True
    roster_continuity: bool = True
    multiyear_history: bool = True


class DashboardResp(BaseModel):
    league: LeagueSummary
    selected_year: Year
    selected_lens: Lens
    hero_stats: HeroStats
    standings: list[StandingRow]
    latest_trades: list[LatestTrade] = Field(default_factory=list)
    # Most consequential trades in the window, ranked by Trade Value swing.
    # Powers the dashboard's "Headline Moves" hero (each links to its detail page).
    headline_trades: list[LatestTrade] = Field(default_factory=list)
    records: Records
    total_trades: int = 0
    warnings: list[str] = Field(default_factory=list)
    # League-calendar phase for the lead section (services/league_phase.py):
    # "regular"/"post" during scored regular-season/bracket weeks, "draft"
    # from a draft's buildup through its aftermath up to NFL week 1,
    # "offseason" otherwise. Derived from the same inputs as
    # production_week_phases so the two can never disagree.
    phase: Literal["regular", "post", "draft", "offseason"] = "offseason"
    phase_season: int = 0
    phase_week: int | None = None  # null outside regular season and playoffs
    # Most recent COMPLETED regular-season week, for the in-season lead. Null
    # outside the regular season, before week 2, and on pre-feature caches.
    week_recap: WeekRecap | None = None
    # How the last draft panned out, for the draft-window lead. Null outside
    # that window and on a class with fewer than two picks; an unplayed class
    # still comes back with `graded=False` rather than null (see DraftReview).
    draft_review: DraftReview | None = None
    # Live title-path state, for the postseason lead. Null outside the
    # playoffs and on caches written before the field existed.
    bracket_watch: BracketWatch | None = None
    # What this league supports. Defaults are full dynasty so pre-feature
    # caches and any un-populated path behave exactly as before.
    capabilities: LeagueCapabilitiesResp = Field(
        default_factory=LeagueCapabilitiesResp)


class DraftBoardPick(BaseModel):
    """One pick on the league-wide draft board."""

    player_id: str
    full_name: str
    position: str
    drafter_id: str
    owner: OwnerRef | None = None
    round: int
    slot: int
    # Picks per round in this class (usually the roster count). Lets the
    # frontend derive a pick's position WITHIN its round — `slot` alone
    # reverses every even round of a snake draft, so it is not that position.
    picks_in_round: int = 0
    pick_no: int
    is_keeper: bool = False
    production_total: float = 0.0
    # Started points across EVERY week — phase-blind. Regular + Playoff +
    # Toilet is LESS than this, because a bye or placement week belongs to no
    # phase. Never present those three as summing to anything.
    production_started: float = 0.0
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    games_started: int = 0
    # Null rather than zero when the player has no market/projection reading.
    adp: float | None = None
    adp_delta: float | None = None
    projected_points: float | None = None
    # The external expectation this class actually has: rookie consensus for a
    # dynasty rookie class, Sleeper ADP for redraft/keeper. Null rather than
    # zero when the player is unranked — ungraded is not a score of zero.
    baseline: float | None = None
    baseline_delta: float | None = None
    baseline_source: str = ""
    # "hit" | "average" | "bust" | "" — empty when unranked, keeper, auction,
    # or the cohort cell has too few players. Never a guess.
    verdict: str = ""
    # The pick's current standing with the drafting owner — "rostered" |
    # "traded" | "dropped". Mirrors `DraftPickResult.roster_status`
    # (`derive_roster_status` in `draft_results.py`), threaded through the
    # same way `verdict` is: already computed on the persisted pick row,
    # just not previously projected onto this response.
    roster_status: str = "rostered"


class DraftBoardOwner(BaseModel):
    """One owner's summary for a single draft class.

    ``adp_total_delta`` is null for an owner with no matched picks — an
    ungraded draft, not an average one. ``graded_picks`` / ``total_picks``
    state the coverage so the reader knows what the number covers.
    """

    user_id: str
    owner: OwnerRef | None = None
    adp_total_delta: float | None = None
    graded_picks: int = 0
    total_picks: int = 0
    production_total: float = 0.0
    production_started: float = 0.0
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    # Summed pick production minus each pick's round average. Zero-sum across
    # the class, so it measures drafting well rather than picking early. Null
    # when the class has nothing scorable.
    points_above_round: float | None = None
    # Hit / Average / Bust counts, rolled up from THIS owner's pick verdicts —
    # the same per-pick strings the Picks ledger renders, never recomputed.
    # The board's headline-equals-the-rows-beneath-it rule applies literally:
    # `hit` must equal the number of rows below reading "hit".
    hit: int = 0
    average: int = 0
    bust: int = 0
    # Every pick this owner MADE in the class, keepers and auction bids
    # included -- it answers "how big was their class", and it is the count of
    # rows the Picks ledger actually shows for them. Distinct from
    # `total_picks`, which counts only the SCORED subset (the denominator the
    # ADP coverage figure reports).
    picks_made: int = 0


class SlotStandingResp(BaseModel):
    """One starting slot INSTANCE's standing against the league-relative
    replacement line. Mirrors the engine's ``draft_needs.py::SlotStanding``
    dataclass exactly -- the ONE keyspace ``OwnerNeedsResp`` is built on
    (2026-08-17 keyspace-fix revision: the earlier ``hole_margins`` /
    ``softest_slot`` pair used two DIFFERENT keyspaces -- bare position label
    vs. slot-instance key -- that silently disagreed the moment a position
    had more than one starting slot).
    """

    slot: str        # the slot-instance key, e.g. "RB_2" -- the ONE keyspace
    position: str     # the occupant's real position, e.g. "RB" -- for display
    # Points vs that position's replacement line; negative = below. `None`
    # -- never a non-finite float -- when there's nothing to compare: no
    # occupant in the slot, or the slot's label has no replacement line at
    # all. C1 fix (2026-08-17): `float("-inf")`/`float("inf")` reaching this
    # field used to 500 the WHOLE draft board -- Starlette's
    # `JSONResponse.render` uses `allow_nan=False`. See
    # `engine/draft_needs.py::SlotStanding.margin` (the mirrored field this
    # is built from) for the full mechanism.
    margin: float | None
    is_hole: bool     # below the line AND not vetoed
    vetoed: bool      # below the line but ECR rates the player above it


class OwnerNeedsResp(BaseModel):
    """One owner's draft-day picture: which starting slots were holes against
    a league-relative replacement line, and whether the draft addressed them.

    Deliberately a SEPARATE Pydantic model from the engine's ``OwnerNeeds``
    dataclass (``engine/draft_needs.py``) — a mapping function sits at the
    boundary. It does NOT carry ``starters_by_slot``: that field is what
    makes the engine's hole verdict debuggable, but the API surface carries
    only what the panel renders.

    Display-only, inferred from a roster reconstruction, a third-party
    ranking, and a replacement line — must NEVER feed Franchise Rating.
    """

    user_id: str
    # Positions, most-severe hole first (furthest below the replacement line).
    # Derived from `slots` (the `is_hole` entries) so the two can never
    # disagree -- see SlotStandingResp's docstring.
    holes: list[str] = Field(default_factory=list)
    # The owner's picks whose position matched an open hole.
    drafted_into: list[str] = Field(default_factory=list)
    # Of `drafted_into`, how many ever recorded a start (games_started > 0).
    # Renders as a `started`/`drafted_into_count` fraction in the frontend
    # rather than a formatted string, keeping formatting out of the API.
    started: int = 0
    drafted_into_count: int = 0
    # Combined production the credited picks put up, regardless of whether
    # they ever started -- replaces "Started" as the panel's trailing figure
    # (Biggest Needs redesign, 2026-08-19): a binary "did it ever happen" was
    # thin signal since most credited rookie picks show zero starts. A real
    # number, including a real 0.0 for a credited pick that produced
    # nothing, distinct from the panel omitting the figure entirely for an
    # owner with no credited picks to sum at all (see the frontend's
    # `n.drafted_into_count === 0` branch inside `pointsReading` in
    # DraftGoingIn.tsx). Defaults to 0.0 so a pre-revision cached row missing
    # this key still deserialises.
    production: float = 0.0
    # One entry per STARTING slot, in `roster_positions` order -- the softest
    # slot is `min(slots, key=lambda s: s.margin)`, and a vetoed slot is any
    # entry with `vetoed=True`. Defaults to [] so a pre-revision cached row
    # (this field's predecessor, Task 1's `hole_margins`/`softest_slot` pair,
    # predates it) still deserialises instead of raising -- `_needs_for_season`
    # isn't wrapped in a try/except, so a missing default would 500 the whole
    # board.
    slots: list[SlotStandingResp] = Field(default_factory=list)


class DraftBoardResp(BaseModel):
    league_id: str
    season: int
    seasons: list[int]
    # False until the class has played. Consumers render results and omit the
    # grade columns rather than showing zeros.
    graded: bool
    format: str = "dynasty"
    picks: list[DraftBoardPick]
    owners: list[DraftBoardOwner]
    # "ECR", "ADP", or "" when no pick in the class carries a baseline. The UI
    # drops the columns on empty rather than printing a header over dashes.
    baseline_label: str = ""
    # True when at least one pick carries a non-empty verdict. The UI drops
    # the Verdict column entirely rather than showing a header over dashes.
    has_verdicts: bool = False
    # None (absent), not [], when the league is ineligible for the
    # reconstruction (redraft, or a first-season startup dynasty with no
    # prior roster) -- the frontend omits the "Going in" panel rather than
    # rendering an empty one. See draft_board_view.py::build_draft_board.
    needs: list[OwnerNeedsResp] | None = None


class DraftSeasonsResp(BaseModel):
    """Every draft season on the chain, newest first.

    Exists so the nav can link to `/league/{id}/draft` without already
    knowing a season — the redirect route reads this to pick the newest one.
    """

    seasons: list[int]
