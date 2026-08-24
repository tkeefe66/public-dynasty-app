from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class StandingAtTrade(BaseModel):
    rank: int
    wins: int
    losses: int
    ties: int
    points_for: float
    total_teams: int


class AssetLine(BaseModel):
    """One player or pick in a side's haul, with its own per-metric line.
    Production fields are received-only (points scored while owned); a pick
    carries KTC value only.

    Journey fields (set on a *received* asset): ``terminal_state`` tags a kept
    asset (on_roster / dropped / undrafted); ``flip`` is present iff the asset
    was traded onward (carries the linkable flip trade + what it became)."""

    label: str
    kind: str  # "player" | "pick"
    player_id: str | None = None
    ktc: float = 0.0
    production_total: float = 0.0
    production_started: float = 0.0
    production_after_drop: float = 0.0  # started pts scored elsewhere after this side dropped him
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    from_pick: str | None = None  # "2024 2nd" — set when a player came via a drafted pick
    from_pick_owner: str | None = None  # display name of the pick's original owner
    terminal_state: str | None = None  # "on_roster" | "dropped" | "undrafted"
    flip: "AssetFlip | None" = None


class AssetFlip(BaseModel):
    """The onward trade a received asset was flipped in, and what it became."""

    to_owner: str
    trade_id: str | None = None
    league_id: str | None = None
    date: str | None = None
    became: list[AssetLine] = []


AssetLine.model_rebuild()


class TradeSideView(BaseModel):
    user_id: str
    owner_name: str
    team_name: str | None = None
    avatar_url: str | None = None
    received: list[dict[str, Any]]
    given: list[dict[str, Any]]
    snapshot_ktc_swing: float
    received_ktc: float = 0.0
    production_total: float
    production_started: float = 0.0
    start_pct: float | None = None
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    breakdown: list[AssetLine] = []
    at_trade_ktc_swing: float | None = None
    aged_ktc_swing: float | None = None
    at_trade_approx: bool = False
    at_trade_snapshot_date: str | None = None
    at_trade_standing: StandingAtTrade | None = None


class TradeStory(BaseModel):
    verdict: str
    lede: str = ""
    beats: list[str] = []
    body: str
    generated_at: str | None = None


class LineageNode(BaseModel):
    label: str
    kind: str
    flipped_at: str | None = None
    terminal_state: str | None = None
    became_player: str | None = None
    children: list["LineageNode"] = []


LineageNode.model_rebuild()


class BecameMetrics(BaseModel):
    """What one side's haul ultimately became, under the bounded lineage walk.

    Fields:
    - ``ktc``: current KTC market value of terminal players.
    - ``production``: bench-inclusive total points across all weeks.
    - ``regular``: started points, regular-season weeks only.
    - ``playoff``: started points, playoff-bracket weeks only.
    - ``toilet``: started points, toilet-bracket weeks only.
    """
    ktc: float = 0.0
    production: float = 0.0
    regular: float = 0.0
    playoff: float = 0.0
    toilet: float = 0.0
    terminal_labels: list[str] = []
    breakdown: list[AssetLine] = []


class ProductionPoint(BaseModel):
    season: int
    week: int
    value: float


class ProductionVerdictView(BaseModel):
    label: str
    sentence: str
    tone: str  # "good" | "bad" | "neutral"
    winner_uid: str | None = None
    totals: dict[str, float] = {}


class PlayerProductionView(BaseModel):
    player_id: str
    series: dict[str, list[ProductionPoint]] = {}  # metric -> points


class PlayerInjuryView(BaseModel):
    games_missed: dict[str, int] = {}       # {"regular", "playoff", "toilet"}
    missed_weeks: list[list] = []           # [[season, week, confidence], ...]
    currently_out: bool = False
    out_detail: str | None = None


class DepartureView(BaseModel):
    player_id: str
    season: int
    week: int
    kind: str  # "dropped" | "traded"


class TradeProductionView(BaseModel):
    trade_id: str
    series: dict[str, list[ProductionPoint]] = {}  # metric -> points


class TwistView(BaseModel):
    kind: str
    owner: str
    label: str
    detail: str


class LensWinners(BaseModel):
    """Winning user_id per lens (Trade Value / Total / Regular Season /
    Playoff / Toilet Bowl); null when the lens is tied or unscored."""

    value: str | None = None
    total: str | None = None
    regular: str | None = None
    playoff: str | None = None
    toilet: str | None = None


class LensMargins(BaseModel):
    """Winning side's realized figure minus the runner-up's, per lens — the
    same rows-plus-became totals the breakdown renders, so summing the visible
    rows reproduces each margin. Null when the lens is tied or unscored."""

    value: float | None = None
    total: float | None = None
    regular: float | None = None
    playoff: float | None = None
    toilet: float | None = None


class TradeDetailResp(BaseModel):
    league_id: str
    trade_id: str
    date: str
    week: int
    season: int
    league_name: str
    sides: list[TradeSideView]
    story: TradeStory | None = None
    lineage: dict[str, list[LineageNode]] = {}
    became: dict[str, BecameMetrics] = {}
    # All league owners (uid → display name), so the UI can resolve a pick's
    # original owner even when they aren't a party to this trade.
    owner_names: dict[str, str] = {}
    # Production timeline (Phase 1): uid -> metric -> [points]; metric -> verdict.
    production_series: dict[str, dict[str, list[ProductionPoint]]] = {}
    production_verdict: dict[str, ProductionVerdictView] = {}
    production_week_axis: list[list[int]] = []
    # ["regular"|"post", ...] parallel to the axis (chart playoff highlight)
    production_week_phases: list[str] = []
    # Per-player drill: uid -> [PlayerProductionView]
    production_players: dict[str, list[PlayerProductionView]] = {}
    # Per-received-player injury context: uid -> player_id -> view
    injury: dict[str, dict[str, PlayerInjuryView]] = {}
    # Received players that left the roster (dropped/traded), for chart markers: uid -> [DepartureView]
    departures: dict[str, list[DepartureView]] = {}
    # Engine-derived "twist" callout for the hero card
    twist: TwistView | None = None
    # Hero card inputs: who won (by received Trade Value) and how lopsided (0..1).
    winner_user_id: str | None = None
    lopsidedness: float = 0.0
    # Per-lens verdicts over each side's realized totals (see LensMargins).
    # A lens both sides left at zero is unscored: excluded from call/tally.
    winners_by_lens: LensWinners = Field(default_factory=LensWinners)
    margins_by_lens: LensMargins = Field(default_factory=LensMargins)
    # "unanimous": every decided lens went one way; "split": more than one
    # winner across decided lenses; "none": nothing decided (tied/unscored).
    call: Literal["unanimous", "split", "none"] = "none"
    # Lenses won per side, most-won first, e.g. "4-1" (ties count for nobody).
    lens_tally: str = "0"
