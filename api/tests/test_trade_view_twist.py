from app.services.trade_view import _select_twist


def test_twist_prefers_dropped_high_value_asset():
    sides = [
        {"owner_name": "Tom", "start_pct": 0.4, "breakdown": [
            {"label": "Nick Chubb", "terminal_state": "dropped", "ktc": 0.0,
             "production_total": 118.0},
        ]},
        {"owner_name": "Mikey", "start_pct": 0.85, "breakdown": [
            {"label": "Bijan Robinson", "terminal_state": "on_roster", "ktc": 9998.0,
             "production_total": 705.0},
        ]},
    ]
    t = _select_twist(sides)
    assert t["kind"] == "dropped" and t["owner"] == "Tom"
    assert "Chubb" in t["detail"]


def test_twist_falls_back_to_low_deployment():
    sides = [
        {"owner_name": "Tom", "start_pct": 0.40, "breakdown": [
            {"label": "X", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
        {"owner_name": "Mikey", "start_pct": 0.88, "breakdown": [
            {"label": "Y", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
    ]
    t = _select_twist(sides)
    assert t["kind"] == "low_deploy" and t["owner"] == "Tom"


def test_twist_dropped_picks_highest_production():
    sides = [
        {"owner_name": "A", "start_pct": 0.6, "breakdown": [
            {"label": "Low Scorer", "terminal_state": "dropped", "ktc": 0.0, "production_total": 50.0}]},
        {"owner_name": "B", "start_pct": 0.6, "breakdown": [
            {"label": "High Scorer", "terminal_state": "dropped", "ktc": 0.0, "production_total": 300.0}]},
    ]
    t = _select_twist(sides)
    assert t["kind"] == "dropped" and t["owner"] == "B"
    assert "High Scorer" in t["detail"]


def test_twist_none_when_unremarkable():
    sides = [
        {"owner_name": "A", "start_pct": 0.8, "breakdown": [
            {"label": "X", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
        {"owner_name": "B", "start_pct": 0.82, "breakdown": [
            {"label": "Y", "terminal_state": "on_roster", "ktc": 100.0, "production_total": 50.0}]},
    ]
    assert _select_twist(sides)["kind"] == "none"
