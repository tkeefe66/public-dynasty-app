"""Side-bet domain rules: validation invariants and ledger rollup math.

Pure functions over SideBet-shaped objects (attribute access only) so they
unit-test without a database and stay dialect-agnostic — same convention as
the Python-side aggregation in app/repositories/events.py."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

OPEN = "open"
SETTLED = "settled"
PUSH = "push"
VOID = "void"
STATUSES = {OPEN, SETTLED, PUSH, VOID}


class BetValidationError(ValueError):
    """A bet violates a domain invariant. Routes map this to HTTP 422."""


def validate_bet_fields(
    *,
    side_a_owner_id: str,
    side_b_owner_id: str,
    amount_cents: int,
    description: str,
) -> None:
    if not description or not description.strip():
        raise BetValidationError("description is required")
    if amount_cents <= 0:
        raise BetValidationError("amount must be positive")
    if side_a_owner_id == side_b_owner_id:
        raise BetValidationError("a bet needs two different owners")


def validate_status(
    *,
    status: str,
    winner_owner_id: str | None,
    side_a_owner_id: str,
    side_b_owner_id: str,
) -> None:
    if status not in STATUSES:
        raise BetValidationError(f"unknown status {status!r}")
    if status == SETTLED:
        if winner_owner_id not in (side_a_owner_id, side_b_owner_id):
            raise BetValidationError("winner must be one of the bet's two sides")
    elif winner_owner_id is not None:
        raise BetValidationError("winner is only allowed on settled bets")


@dataclass
class OwnerBetTotals:
    """One owner's rollup. Ledger math: settled moves the amount from loser
    to winner; push counts for both, moves nothing; void contributes nothing
    (history only); open contributes only to at-stake exposure."""

    owner_id: str
    won: int = 0
    lost: int = 0
    pushed: int = 0
    cents_won: int = 0
    cents_lost: int = 0
    cents_at_stake: int = 0
    biggest_win_cents: int = 0
    worst_loss_cents: int = 0

    @property
    def net_cents(self) -> int:
        return self.cents_won - self.cents_lost


def summarize(bets: Iterable) -> dict[str, OwnerBetTotals]:
    totals: dict[str, OwnerBetTotals] = {}

    def t(owner_id: str) -> OwnerBetTotals:
        return totals.setdefault(owner_id, OwnerBetTotals(owner_id=owner_id))

    for bet in bets:
        a, b = bet.side_a_owner_id, bet.side_b_owner_id
        if bet.status == OPEN:
            t(a).cents_at_stake += bet.amount_cents
            t(b).cents_at_stake += bet.amount_cents
        elif bet.status == PUSH:
            t(a).pushed += 1
            t(b).pushed += 1
        elif bet.status == SETTLED:
            winner = bet.winner_owner_id
            loser = b if winner == a else a
            tw, tl = t(winner), t(loser)
            tw.won += 1
            tw.cents_won += bet.amount_cents
            tw.biggest_win_cents = max(tw.biggest_win_cents, bet.amount_cents)
            tl.lost += 1
            tl.cents_lost += bet.amount_cents
            tl.worst_loss_cents = max(tl.worst_loss_cents, bet.amount_cents)
        # VOID: kept in history, contributes nothing to any rollup.
    return totals
