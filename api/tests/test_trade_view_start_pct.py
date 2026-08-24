from app.models.trade import AssetFlip, AssetLine
from app.services.trade_view import _side_start_pct


def test_start_pct_rolls_up_realized_rows():
    """Flipped pick's became production folds into start_pct (real nested shape).

    A kept player counts directly; a flipped pick's top-level row is 0/0 but
    its flip.became players carry the realized production that should fold in.
    """
    kept = AssetLine(
        label="Bijan Robinson", kind="player", player_id="pid1",
        production_started=600.0, production_total=705.0,
    )
    became_mhj = AssetLine(
        label="MHJ", kind="player", player_id="pid2",
        production_started=90.0, production_total=240.0,
    )
    became_wright = AssetLine(
        label="Wright", kind="player", player_id="pid3",
        production_started=20.0, production_total=65.0,
    )
    flipped = AssetLine(
        label="2025 1st (MHJ)", kind="pick",
        production_started=0.0, production_total=0.0,
        flip=AssetFlip(to_owner="Other Team", became=[became_mhj, became_wright]),
    )

    pct = _side_start_pct([kept, flipped])
    expected = (600 + 90 + 20) / (705 + 240 + 65)
    assert round(pct, 3) == round(expected, 3)  # ≈ 0.703


def test_start_pct_none_when_no_total():
    assert _side_start_pct([{"production_started": 0.0, "production_total": 0.0}]) is None


def test_start_pct_handles_object_rows():
    from types import SimpleNamespace
    rows = [SimpleNamespace(production_started=600.0, production_total=705.0)]
    pct = _side_start_pct(rows)
    assert round(pct, 3) == round(600.0 / 705.0, 3)
