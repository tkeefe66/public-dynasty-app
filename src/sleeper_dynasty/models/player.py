from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class Player:
    player_id: str
    full_name: str
    position: str  # QB, RB, WR, TE, K, DEF
    team: str | None
    birth_date: date | None = None
    years_exp: int | None = None

    def age(self, as_of: date | None = None) -> int | None:
        if self.birth_date is None:
            return None
        ref = as_of or date.today()
        years = ref.year - self.birth_date.year
        if (ref.month, ref.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


@dataclass
class PlayerProjection:
    player_id: str
    source: str  # "sleeper" or "fantasypros"
    season: int
    week: int | None  # None = full season
    projected_points: float
    stats: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# External-source projection / value models
#
# These exist alongside the simulator-facing PlayerProjection so the data
# layer can capture the raw, source-of-truth structure (stat-level FP
# projections, KTC dynasty values) without contorting the simpler model
# the rest of the pipeline already consumes.
# ---------------------------------------------------------------------------


@dataclass
class FantasyProsProjection:
    """Stat-level FantasyPros consensus projection for a single player.

    Mirrors a FantasyPros projections page row. ``stats`` holds the raw
    per-stat numbers (passing yards, receptions, etc.) using snake_case
    keys that match the Sleeper league ``scoring_settings`` keys so the
    same ``normalize_projection`` math works on either source.

    ``projected_points_ppr`` is the FP-computed PPR total — useful as a
    sanity check, but for league-specific scoring callers should
    re-normalize ``stats`` against ``league.scoring_settings``.
    """

    name: str
    normalized_name: str
    team: str | None
    position: str
    stats: dict[str, float]
    projected_points_ppr: float
    projected_points_high: float | None = None
    projected_points_low: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "team": self.team,
            "position": self.position,
            "stats": dict(self.stats),
            "projected_points_ppr": self.projected_points_ppr,
            "projected_points_high": self.projected_points_high,
            "projected_points_low": self.projected_points_low,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FantasyProsProjection:
        return cls(
            name=data["name"],
            normalized_name=data["normalized_name"],
            team=data.get("team"),
            position=data["position"],
            stats=dict(data.get("stats", {})),
            projected_points_ppr=float(data["projected_points_ppr"]),
            projected_points_high=(
                float(data["projected_points_high"])
                if data.get("projected_points_high") is not None
                else None
            ),
            projected_points_low=(
                float(data["projected_points_low"])
                if data.get("projected_points_low") is not None
                else None
            ),
        )


@dataclass
class KTCValue:
    """KeepTradeCut dynasty value for a single player or rookie pick.

    KTC publishes a 0-9999 integer value scale. We capture both Superflex
    and 1QB values so the consumer can pick whichever matches their
    league format. ``position`` is one of QB/RB/WR/TE/RDP (rookie draft
    pick). ``superflex_position_rank`` / ``one_qb_position_rank`` are the
    rankings within that position (1 = QB1, etc.).

    Any field can be ``None`` if KTC didn't return a value for that
    format — e.g., a player who only appears in one of the two ranking
    sets.
    """

    name: str
    normalized_name: str
    position: str
    superflex_value: int | None = None
    one_qb_value: int | None = None
    superflex_position_rank: int | None = None
    one_qb_position_rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "position": self.position,
            "superflex_value": self.superflex_value,
            "one_qb_value": self.one_qb_value,
            "superflex_position_rank": self.superflex_position_rank,
            "one_qb_position_rank": self.one_qb_position_rank,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KTCValue:
        def _opt_int(key: str) -> int | None:
            v = data.get(key)
            return int(v) if v is not None else None

        return cls(
            name=data["name"],
            normalized_name=data["normalized_name"],
            position=data["position"],
            superflex_value=_opt_int("superflex_value"),
            one_qb_value=_opt_int("one_qb_value"),
            superflex_position_rank=_opt_int("superflex_position_rank"),
            one_qb_position_rank=_opt_int("one_qb_position_rank"),
        )


def parse_birth_date(raw: Any) -> date | None:
    """Parse a Sleeper ``birth_date`` (ISO string like "1996-07-26") into a date.

    Missing or malformed values degrade gracefully to ``None``.
    """
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def build_players(raw_players: dict[str, Any]) -> dict[str, Player]:
    """Convert the raw Sleeper players-NFL dump into ``Player`` objects."""
    players: dict[str, Player] = {}
    for pid, raw in raw_players.items():
        if not isinstance(raw, dict):
            continue
        full_name = (
            raw.get("full_name")
            or f"{raw.get('first_name', '')} {raw.get('last_name', '')}".strip()
            or pid
        )
        players[pid] = Player(
            player_id=pid,
            full_name=full_name,
            position=raw.get("position") or "",
            team=raw.get("team"),
            birth_date=parse_birth_date(raw.get("birth_date")),
            years_exp=raw.get("years_exp"),
        )
    return players
