"""Pure domain rules for side bets: invariants + ledger rollup math."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.side_bets import (
    BetValidationError,
    summarize,
    validate_bet_fields,
    validate_status,
)


def _bet(status="open", winner=None, a="u_a", b="u_b", cents=10000):
    return SimpleNamespace(
        status=status,
        winner_owner_id=winner,
        side_a_owner_id=a,
        side_b_owner_id=b,
        amount_cents=cents,
    )


class TestValidateBetFields:
    def test_accepts_a_valid_bet(self):
        validate_bet_fields(
            side_a_owner_id="u_a",
            side_b_owner_id="u_b",
            amount_cents=50000,
            description="A over B",
        )

    def test_rejects_same_owner_both_sides(self):
        with pytest.raises(BetValidationError):
            validate_bet_fields(
                side_a_owner_id="u_a",
                side_b_owner_id="u_a",
                amount_cents=100,
                description="x",
            )

    def test_rejects_non_positive_amount(self):
        with pytest.raises(BetValidationError):
            validate_bet_fields(
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
                amount_cents=0,
                description="x",
            )

    def test_rejects_blank_description(self):
        with pytest.raises(BetValidationError):
            validate_bet_fields(
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
                amount_cents=100,
                description="   ",
            )


class TestValidateStatus:
    def test_settled_requires_winner_from_the_sides(self):
        validate_status(
            status="settled",
            winner_owner_id="u_a",
            side_a_owner_id="u_a",
            side_b_owner_id="u_b",
        )
        with pytest.raises(BetValidationError):
            validate_status(
                status="settled",
                winner_owner_id="u_zzz",
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
            )
        with pytest.raises(BetValidationError):
            validate_status(
                status="settled",
                winner_owner_id=None,
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
            )

    @pytest.mark.parametrize("status", ["open", "push", "void"])
    def test_non_settled_forbids_winner(self, status):
        validate_status(
            status=status,
            winner_owner_id=None,
            side_a_owner_id="u_a",
            side_b_owner_id="u_b",
        )
        with pytest.raises(BetValidationError):
            validate_status(
                status=status,
                winner_owner_id="u_a",
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
            )

    def test_unknown_status_rejected(self):
        with pytest.raises(BetValidationError):
            validate_status(
                status="cancelled",
                winner_owner_id=None,
                side_a_owner_id="u_a",
                side_b_owner_id="u_b",
            )


class TestSummarize:
    def test_settled_bet_moves_money_both_ways(self):
        totals = summarize([_bet(status="settled", winner="u_a", cents=50000)])
        assert totals["u_a"].won == 1
        assert totals["u_a"].cents_won == 50000
        assert totals["u_a"].net_cents == 50000
        assert totals["u_a"].biggest_win_cents == 50000
        assert totals["u_b"].lost == 1
        assert totals["u_b"].cents_lost == 50000
        assert totals["u_b"].net_cents == -50000
        assert totals["u_b"].worst_loss_cents == 50000

    def test_push_counts_for_both_and_moves_nothing(self):
        totals = summarize([_bet(status="push")])
        assert totals["u_a"].pushed == 1
        assert totals["u_b"].pushed == 1
        assert totals["u_a"].net_cents == 0

    def test_void_contributes_nothing(self):
        totals = summarize([_bet(status="void")])
        assert totals == {} or all(
            t.won == t.lost == t.pushed == t.cents_at_stake == 0
            for t in totals.values()
        )

    def test_open_bet_is_at_stake_for_both(self):
        totals = summarize([_bet(status="open", cents=2500)])
        assert totals["u_a"].cents_at_stake == 2500
        assert totals["u_b"].cents_at_stake == 2500
        assert totals["u_a"].net_cents == 0

    def test_mixed_ledger_accumulates(self):
        totals = summarize(
            [
                _bet(status="settled", winner="u_a", cents=50000),
                _bet(status="settled", winner="u_b", cents=10000),
                _bet(status="open", cents=2000),
                _bet(status="settled", winner="u_a", a="u_a", b="u_c", cents=7500),
            ]
        )
        assert totals["u_a"].won == 2
        assert totals["u_a"].lost == 1
        assert totals["u_a"].net_cents == 50000 - 10000 + 7500
        assert totals["u_a"].biggest_win_cents == 50000
        assert totals["u_c"].net_cents == -7500
