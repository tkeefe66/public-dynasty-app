from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# ---------------------------------------------------------------------------
# Asset taxonomy
# ---------------------------------------------------------------------------


@dataclass
class PickAsset:
    """A future or unused draft pick.

    ``original_owner_user_id`` is the stable user_id of whoever originally
    held this pick (i.e., before any trade). This is what determines the
    draft slot once the draft happens.

    ``drafted_player_id`` / ``drafted_player_name`` are populated when the
    pick's draft is complete but this pick is NOT being upgraded to a
    PlayerAsset in this trade (i.e., the team in this trade flipped the
    pick rather than drafting with it). They exist purely so the snapshot
    lens can value the pick at the drafted player's current market value.
    They are intentionally invisible to production/impact, which gate on
    PlayerAsset.
    """

    season: int
    round: int
    original_owner_user_id: str
    drafted_player_id: str | None = None
    drafted_player_name: str | None = None


@dataclass
class PlayerAsset:
    """A specific NFL player traded as an asset.

    ``via_pick`` is set when this PlayerAsset originated from a PickAsset
    that got resolved to its drafted player. The original pick metadata
    (season, round, original owner) is preserved so consumers can
    distinguish "traded directly for player X" from "received pick → X".
    """

    player_id: str
    name: str
    via_pick: PickAsset | None = None


@dataclass
class FaabAsset:
    """A FAAB (free-agent budget) dollar transfer. Recorded, not valued in v1."""

    amount: int


# A TradeAsset is one of the three above. We use isinstance dispatch instead
# of inheritance to keep each shape minimal.
TradeAsset = PlayerAsset | PickAsset | FaabAsset


# ---------------------------------------------------------------------------
# Trade shapes
# ---------------------------------------------------------------------------


@dataclass
class TradeSide:
    """One participant's side of a trade.

    ``received`` and ``given`` are lists of TradeAssets. For a 2-team trade
    each side has exactly the assets the other side gave. For 3+ team trades
    we just record what each side independently received and gave.
    """

    user_id: str
    received: list[TradeAsset]
    given: list[TradeAsset]


@dataclass
class Trade:
    """A complete trade transaction, owner-identified."""

    transaction_id: str
    league_id: str
    season: int
    week: int
    traded_at: datetime
    sides: dict[str, TradeSide]  # keyed by user_id


@dataclass
class ResolvedTrade:
    """A Trade after pick resolution.

    `trade` is the original; `sides` is the post-resolution side map with
    any resolved PickAssets replaced by PlayerAssets representing the
    actual drafted player.
    """

    trade: Trade
    sides: dict[str, TradeSide]


# ---------------------------------------------------------------------------
# Grading shapes
# ---------------------------------------------------------------------------


@dataclass
class AssetLine:
    """One player or pick in a side's haul, with its own per-metric line.

    Production fields are received-only (points the asset scored while owned by
    this side, post-trade). A pick carries KTC value only (zero production until
    it resolves to a player)."""

    label: str                 # "Bijan Robinson" or "2027 1st"
    kind: str                  # "player" | "pick"
    player_id: str | None
    ktc: float
    production_total: float
    production_regular: float
    production_playoff: float
    production_toilet: float
    production_started: float = 0.0   # starters-only, all weeks (not a phase split)
    # Started points this player scored elsewhere AFTER this side stopped
    # rostering him post-trade — the "drop regret" figure. 0 while still held.
    production_after_drop: float = 0.0
    # Provenance: set when a player row came from a drafted pick (the pick's
    # resolution trade), e.g. "2024 2nd" with the original owner's user_id.
    # Lets the UI show "Player · from 2024 2nd pick (orig: X)" so a received
    # pick reads the same as it does on the giving side's exchange line,
    # instead of collapsing silently to the draftee. The owner_uid is resolved
    # to a display name at the API layer (the engine has no name map).
    from_pick: str | None = None
    from_pick_owner_uid: str | None = None


@dataclass
class TradeGrade:
    """The graded value swings for a single trade, keyed by user_id.

    Five points-or-value views per side: today's market value (KTC), total
    production (bench included), and started-only production split into three
    phases — regular season, playoff (winners-bracket), and toilet bowl
    (losers-bracket).

    ``received_ktc`` is each side's gross received KTC (sum of its breakdown
    rows), as opposed to the zero-sum ``snapshot_value_swing``. ``breakdown``
    is the per-asset stat lines whose columns sum to the per-side totals."""

    trade_id: str
    snapshot_value_swing: dict[str, float] = field(default_factory=dict)
    production_total: dict[str, float] = field(default_factory=dict)
    production_regular: dict[str, float] = field(default_factory=dict)
    production_playoff: dict[str, float] = field(default_factory=dict)
    production_toilet: dict[str, float] = field(default_factory=dict)
    production_started: dict[str, float] = field(default_factory=dict)
    received_ktc: dict[str, float] = field(default_factory=dict)
    breakdown: dict[str, list[AssetLine]] = field(default_factory=dict)


@dataclass
class OwnerTradeRecord:
    """Per-owner aggregate across all their trades in the chain."""

    user_id: str
    display_name: str
    trades: int = 0
    net_ktc: float = 0.0
    production_total: float = 0.0
    production_regular: float = 0.0
    production_playoff: float = 0.0
    production_toilet: float = 0.0
    best_trade_id: str | None = None
    worst_trade_id: str | None = None
