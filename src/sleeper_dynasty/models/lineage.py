from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["player", "pick"]
Terminal = Literal["on_roster", "dropped", "undrafted"]


@dataclass
class LineageNode:
    """One asset in one owner's possession, with what it became next."""
    label: str
    kind: Kind
    flipped_at: str | None                 # date the owner flipped it; None if terminal
    terminal_state: Terminal | None        # set only when not flipped
    became_player: str | None              # for a pick that resolved to a player
    children: list["LineageNode"] = field(default_factory=list)
    # Terminal-leaf identity (used by terminal_assets / the became-grade).
    # The API/tree ignore these harmlessly.
    terminal_player_id: str | None = None
    terminal_pick: tuple[int, int] | None = None  # (season, round) for undrafted picks
    # Flip metadata (set only on a flip node) — lets a consumer link the flip to
    # that trade's detail page and name the counterparty.
    flip_trade_id: str | None = None
    flip_league_id: str | None = None
    flip_counterparty_uid: str | None = None
    # True only when this node is a PICK the owner flipped *as a pick* (before
    # the draft). Such an owner never realized the slot's draftee, so a receipt
    # row built from this node must drop the "(<draftee>)" annotation.
    flipped_as_pick: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "kind": self.kind, "flipped_at": self.flipped_at,
            "terminal_state": self.terminal_state, "became_player": self.became_player,
            "flip_trade_id": self.flip_trade_id, "flip_league_id": self.flip_league_id,
            "flip_counterparty_uid": self.flip_counterparty_uid,
            "children": [c.to_dict() for c in self.children],
        }
