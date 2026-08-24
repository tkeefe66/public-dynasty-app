from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.common import OwnerRef
from app.models.leaderboard import PillarBreakdown
from app.models.trade import ProductionPoint, ProductionVerdictView, TradeProductionView


class SeasonArc(BaseModel):
    season: int
    net_ktc: float
    production_total: float
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    # Starters-only, all weeks. Added so the career-arc chart can show what a
    # franchise actually DEPLOYED per season, not just what it accumulated —
    # the gap between this and production_total is the bench.
    production_started: float = 0.0
    trades: int


class OwnerTradeRow(BaseModel):
    """One trade from a single owner's perspective. Swings are this owner's
    share (keyed by their user_id), not the trade's first party — so the
    deep-dive receipts table reads as "what this deal did for me"."""

    trade_id: str
    date: str
    season: int
    week: int | None = None
    counterparties: list[OwnerRef] = []
    assets_short: str
    swing_ktc: float
    swing_prod: float
    swing_regular: float
    swing_playoff: float
    swing_toilet: float = 0.0
    # Starters-only, ALL weeks — not the sum of the three phase metrics above.
    # `production_playoff` counts live title-path games only, so started points
    # in a placement game or an eliminated week belong to no phase at all.
    # Measured on the live league: 14 of 52 non-zero owner/trade pairs differ
    # from regular+playoff+toilet, by up to 23.6 points. Deriving it by summing
    # would have been wrong, not merely inelegant.
    swing_started: float = 0.0
    # Share of this haul's points that were actually STARTED — the bench-miss
    # reading. `swing_started / swing_prod`, via services/start_rate.py so the
    # trade page and this page cannot disagree. None for a haul that has not
    # played: 0% would read as "you benched everything", which is the most
    # damning reading of the least information.
    start_pct: float | None = None


class OwnerProfile(BaseModel):
    """The league "voice" data for one owner, keyed externally by user_id.

    All fields optional so a half-filled profile still saves. ``rivals`` holds
    the user_ids of this owner's rivals (the UI renders them as names)."""

    win_name: str | None = None
    loss_name: str | None = None
    archetype: str | None = None
    rivals: list[str] = []
    roast: str | None = None


class PlayerLite(BaseModel):
    player_id: str
    full_name: str
    position: str
    age: int | None = None


class AgeProfileView(BaseModel):
    avg_age_by_position: dict[str, float]
    # position -> the LEAGUE's mean age there (pooled over every rostered
    # player, the same way this owner's own avg_age_by_position is pooled).
    # Empty on a pre-feature blob and on the CLI path; the rooms chart then
    # draws no dots rather than inventing a baseline.
    league_avg_age_by_position: dict[str, float] = {}
    overall_avg_age: float
    aging_risks: list[PlayerLite] = []
    core_young: list[PlayerLite] = []


class DraftCapitalView(BaseModel):
    picks_by_season: dict[str, int]
    picks_by_season_round: dict[str, int]
    net_vs_average: float
    status: str
    total_value: float = 0.0   # KTC value of held future picks (outlook signal)


class DraftNeedView(BaseModel):
    position: str
    urgency: str
    reason: str
    # Players held at this position and the roster-construction target.
    # Emitted on every need, but only `kind == "depth"` is a shortfall against
    # `ideal` -- the UI draws depth pips on that branch alone, because the
    # aging branch is reached only when held >= ideal and full pips beside a
    # live need reads as a contradiction. 0/0/"" on a pre-feature blob.
    held: int = 0
    ideal: int = 0
    kind: str = ""


class OutlookView(BaseModel):
    """The Assets pillar's own page.

    `window` is the competitive-window stage DERIVED from this league's
    Franchise Rating (gm_rating.rating_to_stage), computed at read time and
    persisted nowhere. `str | None`: an unrated owner -- first season, new
    franchise, or a league whose signal stage threw -- has no rating, so has no
    stage, and every surface renders that as an absence captioned by
    `unrated_reason`. The retired `classify_window` always returned a label;
    this deliberately does not.
    """

    window: str | None = None
    # The rating's own two pillar z's, straight off PillarBreakdown.z -- no new
    # derivation. `tilt` is assets_z - results_z: a signed readout of whether
    # the roster is ahead of the trophy case. It is NOT the rung selector; a
    # relation cannot be monotone on an ordered rail.
    results_z: float | None = None
    assets_z: float | None = None
    tilt: float | None = None
    # signal key -> rank among the rated population, 1 = best. Duplicates
    # franchise_rating.pillars["assets"].signal_ranks, which the same response
    # carries; kept here so the Outlook tab reads one object.
    assets_signal_ranks: dict[str, int] = {}
    age_profile: AgeProfileView
    draft_capital: DraftCapitalView
    draft_needs: list[DraftNeedView] = []


class RankView(BaseModel):
    rank: int
    of: int


class DraftSkillView(BaseModel):
    score: float
    rank: int
    of: int


class DraftPickResult(BaseModel):
    player_id: str
    full_name: str
    position: str
    round: int
    slot: int
    picks_in_round: int
    draft_season: int
    acquired_via_trade: bool
    current_value: float
    lowest_value: float
    highest_value: float
    avg_slot_value: float
    production_total: float
    # Phase-blind started points. Regular + Playoff + Toilet is LESS than this;
    # the gap is bye and placement weeks, which belong to no phase.
    production_started: float = 0.0
    production_regular: float
    production_playoff: float
    production_toilet: float
    games_started: int = 0
    roster_status: str = "rostered"
    is_keeper: bool = False
    pick_no: int = 0
    # Null, never 0.0 — an unmatched pick is ungraded on this baseline, which
    # is not the same as scoring zero.
    adp: float | None = None
    adp_delta: float | None = None
    projected_points: float | None = None
    # "hit" | "average" | "bust" | "" — empty when unranked, keeper, auction,
    # or the cohort cell has too few players. Never a guess.
    verdict: str = ""


class SeasonResultView(BaseModel):
    season: int
    rank: int                 # regular-season finish (1 = best)
    of: int                   # league size that season
    wins: int
    losses: int
    ties: int
    made_playoffs: bool
    champion: bool
    runner_up: bool
    rounds_won: int           # title-path playoff rounds won
    playoff_place: int | None = None   # 1 = champion; None if not in the bracket
    made_toilet: bool = False           # participated in the losers (toilet) bracket
    toilet_place: int | None = None     # 1 = toilet champ (→ 1.01); None if not in it


class TrackRecordView(BaseModel):
    """A franchise's win/title history — per-season finishes plus career rollups."""

    seasons: list[SeasonResultView] = []
    titles: int = 0
    runner_ups: int = 0
    playoff_appearances: int = 0
    seasons_played: int = 0
    best_finish: int | None = None     # best playoff placement; None if never made it
    career_wins: int = 0
    career_losses: int = 0
    career_ties: int = 0


class H2HView(BaseModel):
    """This owner's all-time regular-season record vs one league-mate."""

    opponent: OwnerRef
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


class FranchiseRatingView(BaseModel):
    """The platform-wide owner verdict: the three-pillar composite as a letter
    (the headline) with the number, rank, and trend as the receipt."""

    letter: str
    rating: int
    rank: int
    # Count of RATED owners (franchise_redesign.rated_owners — a completed
    # season), not the league's full roster of franchises. `rank` is only
    # ever computed over that same population, so this is the only count
    # that keeps rank/of achievable (rank == of is reachable); the standings
    # table's franchise count can legitimately be larger. Surfaced as "of N
    # rated" in the UI so the two numbers never look like a disagreement.
    of: int
    trend: int            # prev_rank - rank: +up, -down, 0 flat/new
    pillars: dict[str, PillarBreakdown] = {}   # the receipt: results/skill/outlook
    # LLM-written one-line highlight per pillar (results/skill/outlook).
    pillar_highlights: dict[str, str] = {}


class ProseSegment(BaseModel):
    """One run of the franchise blurb's body, with its emphasis mark.

    The blurb is written with inline marks (`[num]`, `[who]`, `[good]`,
    `[risk]`) and parsed server-side into these. The web side maps each segment
    to a React element, so the text is escaped and there is no
    `dangerouslySetInnerHTML` anywhere on this path — the whole reason the
    response carries a segment LIST rather than a marked-up string.
    """

    text: str
    # None = plain prose. Any mark name the renderer does not know degrades to
    # plain rather than failing, so this is deliberately not an enum.
    mark: str | None = None


class OwnerDetailResp(BaseModel):
    league_id: str
    user_id: str
    owner: OwnerRef
    # "dynasty" | "keeper" | "redraft" (engine/capabilities.py). Carried so the
    # UI can drop format-specific columns by ASKING the format rather than
    # inferring it from whether the data happens to be all zeros.
    format: str = "dynasty"
    totals_by_lens: dict[str, float]
    career_arc: list[SeasonArc]
    trades: list[OwnerTradeRow] = []
    best_trade_id: str | None
    worst_trade_id: str | None
    outlook: OutlookView | None = None
    roster_rank: RankView | None = None
    draft_skill: DraftSkillView | None = None
    # The blurb, three ways. `franchise_blurb` is the PLAIN body and remains
    # the fallback: a pre-marks cached entry carries only this, and it renders
    # as prose rather than as an empty panel. The other two are absent (not
    # empty) when unavailable, so the UI asks rather than infers.
    franchise_blurb: str | None = None
    franchise_lead: str | None = None
    franchise_segments: list[ProseSegment] | None = None
    # str(season) -> picks the owner drafted that season (Future & Draft tab).
    draft_picks_by_season: dict[str, list[DraftPickResult]] = {}
    # Production timeline (Phase 1): side -> metric -> [points]; metric -> verdict.
    production_series: dict[str, dict[str, list[ProductionPoint]]] = {}
    production_verdict: dict[str, ProductionVerdictView] = {}
    production_week_axis: list[list[int]] = []
    production_week_phases: list[str] = []
    # Per-trade drill: list of TradeProductionView for this owner.
    production_trades: list[TradeProductionView] = []
    # Franchise page (owner-redesign): the platform verdict + win/title history.
    franchise_rating: FranchiseRatingView | None = None
    # Why there is no letter, when `franchise_rating` is absent:
    # "first_season" — the league itself has completed no season, so nobody is
    # rated; "new_franchise" — the league has, this owner has not (a
    # replacement manager holding someone else's roster). None when rated. The
    # UI owns the caption wording; this names the case, not the copy.
    unrated_reason: str | None = None
    track_record: TrackRecordView = TrackRecordView()
    head_to_head: list[H2HView] = []
