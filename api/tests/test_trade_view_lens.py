"""Per-lens winners on the trade detail response.

``_realized_lens_totals`` reads a side's enriched breakdown the same way the
stat table's TOTAL row does (kept assets' own line + flipped assets' became);
``_lens_verdict`` turns per-side totals into winners/margins/call/tally.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.models.trade import AssetFlip, AssetLine
from app.services.trade_view import (
    _lens_verdict, _realized_lens_totals, build_trade_detail,
)


def _totals(value=0.0, total=0.0, regular=0.0, playoff=0.0, toilet=0.0):
    return {"value": value, "total": total, "regular": regular,
            "playoff": playoff, "toilet": toilet}


# --- _realized_lens_totals -------------------------------------------------

def test_realized_totals_sum_kept_rows():
    rows = [
        AssetLine(label="Bijan", kind="player", player_id="p1", ktc=9000.0,
                  production_total=705.0, production_regular=500.0,
                  production_playoff=80.0, production_toilet=0.0),
        AssetLine(label="2026 2nd", kind="pick", ktc=1500.0),
    ]
    t = _realized_lens_totals(rows)
    assert t == _totals(value=10500.0, total=705.0, regular=500.0, playoff=80.0)


def test_realized_totals_fold_flip_became():
    """A flipped pick contributes what it became, not its own 0/0 line."""
    became = AssetLine(label="MHJ", kind="player", player_id="p2", ktc=8000.0,
                       production_total=240.0, production_regular=200.0)
    flipped = AssetLine(
        label="2025 1st", kind="pick", ktc=3000.0,
        flip=AssetFlip(to_owner="Other", became=[became]),
    )
    t = _realized_lens_totals([flipped])
    assert t == _totals(value=8000.0, total=240.0, regular=200.0)


def test_realized_totals_flip_without_became_falls_back_to_own_row():
    flipped = AssetLine(label="2025 1st", kind="pick", ktc=3000.0,
                        flip=AssetFlip(to_owner="Other", became=[]))
    t = _realized_lens_totals([flipped])
    assert t == _totals(value=3000.0)


# --- _lens_verdict ---------------------------------------------------------

def test_verdict_unanimous():
    v = _lens_verdict({
        "ua": _totals(value=1000, total=300, regular=200, playoff=50, toilet=10),
        "ub": _totals(value=400, total=100, regular=80, playoff=20, toilet=5),
    })
    assert v["winners"] == {k: "ua" for k in ("value", "total", "regular", "playoff", "toilet")}
    assert v["margins"] == {"value": 600, "total": 200, "regular": 120,
                            "playoff": 30, "toilet": 5}
    assert v["call"] == "unanimous"
    assert v["tally"] == "5-0"


def test_verdict_split_market_vs_field():
    """One manager wins the market, the other wins every points lens."""
    v = _lens_verdict({
        "ua": _totals(value=1000, total=100, regular=80, playoff=10, toilet=2),
        "ub": _totals(value=400, total=300, regular=200, playoff=50, toilet=9),
    })
    assert v["winners"]["value"] == "ua"
    assert all(v["winners"][k] == "ub" for k in ("total", "regular", "playoff", "toilet"))
    assert v["call"] == "split"
    assert v["tally"] == "4-1"


def test_verdict_all_tied_is_none():
    v = _lens_verdict({
        "ua": _totals(value=500, total=100, regular=80, playoff=10, toilet=2),
        "ub": _totals(value=500, total=100, regular=80, playoff=10, toilet=2),
    })
    assert all(w is None for w in v["winners"].values())
    assert all(m is None for m in v["margins"].values())
    assert v["call"] == "none"
    assert v["tally"] == "0-0"


def test_verdict_unscored_lens_excluded():
    """Both sides 0 on toilet -> the lens is unscored: null winner/margin and
    the sweep of the four scored lenses still reads unanimous, tally 4-0."""
    v = _lens_verdict({
        "ua": _totals(value=1000, total=300, regular=200, playoff=50, toilet=0),
        "ub": _totals(value=400, total=100, regular=80, playoff=20, toilet=0),
    })
    assert v["winners"]["toilet"] is None
    assert v["margins"]["toilet"] is None
    assert v["call"] == "unanimous"
    assert v["tally"] == "4-0"


def test_verdict_scored_tie_counts_for_nobody():
    """A scored-but-tied lens breaks nobody's sweep: winner null, tally 4-0,
    call still unanimous (every decided lens went one way)."""
    v = _lens_verdict({
        "ua": _totals(value=1000, total=300, regular=200, playoff=50, toilet=7),
        "ub": _totals(value=400, total=100, regular=80, playoff=20, toilet=7),
    })
    assert v["winners"]["toilet"] is None
    assert v["call"] == "unanimous"
    assert v["tally"] == "4-0"


def test_verdict_nothing_scored_is_none():
    v = _lens_verdict({"ua": _totals(), "ub": _totals()})
    assert v["call"] == "none"
    assert v["tally"] == "0-0"


def test_verdict_three_way_margin_is_vs_runner_up():
    v = _lens_verdict({
        "ua": _totals(value=1000, total=50),
        "ub": _totals(value=700, total=300),
        "uc": _totals(value=100, total=200),
    })
    assert v["winners"]["value"] == "ua"
    assert v["margins"]["value"] == 300  # vs ub, the runner-up — not ua's raw 1000
    assert v["winners"]["total"] == "ub"
    assert v["margins"]["total"] == 100
    assert v["call"] == "split"
    assert v["tally"] == "1-1-0"


# --- build_trade_detail wiring ----------------------------------------------

def _entry():
    rt = {
        "trade": {
            "transaction_id": "t1", "traded_at": "2024-10-01T00:00:00+00:00",
            "week": 4, "season": 2024, "league_id": "LG",
        },
        "sides": {
            "ua": {"received": [], "given": []},
            "ub": {"received": [], "given": []},
        },
    }
    grades = {"t1": {
        "received_ktc": {"ua": 5000.0, "ub": 4000.0},
        "snapshot_value_swing": {"ua": 1000.0, "ub": -1000.0},
        "breakdown": {
            "ua": [{"label": "Bijan", "kind": "player", "player_id": "p1",
                    "ktc": 5000.0, "production_total": 100.0,
                    "production_regular": 80.0}],
            "ub": [{"label": "MHJ", "kind": "player", "player_id": "p2",
                    "ktc": 4000.0, "production_total": 300.0,
                    "production_regular": 200.0}],
        },
    }}
    return SimpleNamespace(
        league_id="ENTRY",
        resolved_trades=[rt],
        grades=grades,
        trade_stories={},
        became_grades={},
        current_holders={},
        league_name_by_id={"LG": "My League"},
        owners={"ua": {"owner_name": "A"}, "ub": {"owner_name": "B"}},
    )


def test_detail_carries_lens_verdicts_and_keeps_winner_user_id():
    detail = build_trade_detail(_entry(), "t1")
    # New per-lens fields, computed from the breakdown rows.
    assert detail.winners_by_lens.value == "ua"
    assert detail.margins_by_lens.value == 1000.0
    assert detail.winners_by_lens.total == "ub"
    assert detail.margins_by_lens.total == 200.0
    assert detail.winners_by_lens.playoff is None    # unscored on both sides
    assert detail.margins_by_lens.playoff is None
    assert detail.call == "split"
    assert detail.lens_tally == "2-1"
    # Existing hero-card fields keep their current behavior (received_ktc).
    assert detail.winner_user_id == "ua"
    assert detail.lopsidedness > 0
