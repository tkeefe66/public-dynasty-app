from app.models.trade import ProductionPoint, ProductionVerdictView, TradeDetailResp


def test_production_point_and_verdict():
    p = ProductionPoint(season=2024, week=5, value=10.0)
    assert (p.season, p.week, p.value) == (2024, 5, 10.0)
    v = ProductionVerdictView(label="Won the production battle.", sentence="Tom is ahead by 195 total points.",
                              tone="good", winner_uid="u1", totals={"u1": 900.0, "u2": 705.0})
    assert v.winner_uid == "u1"


def test_trade_detail_has_production_fields():
    r = TradeDetailResp.model_construct()
    assert hasattr(r, "production_series")
    assert hasattr(r, "production_verdict")
    assert hasattr(r, "production_week_axis")
