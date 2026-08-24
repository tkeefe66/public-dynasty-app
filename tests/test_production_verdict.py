from sleeper_dynasty.engine.production_series import head_to_head_verdict, aggregate_production_verdict


def test_too_early_when_few_games():
    v = head_to_head_verdict(totals={"u1": 50.0, "u2": 10.0}, n_games=1, metric="total")
    assert v["tone"] == "neutral"
    assert "too early" in v["sentence"].lower()
    assert v["winner_uid"] is None


def test_clear_winner_named_with_margin():
    v = head_to_head_verdict(totals={"u1": 900.0, "u2": 705.0}, n_games=20, metric="total",
                             names={"u1": "Tom", "u2": "Mikey"})
    assert v["winner_uid"] == "u1"
    assert v["tone"] == "good"
    assert "Tom" in v["sentence"] and "195" in v["sentence"]


def test_dead_even():
    v = head_to_head_verdict(totals={"u1": 500.0, "u2": 498.0}, n_games=20, metric="total")
    assert v["winner_uid"] is None
    assert v["label"].lower().startswith("dead") or "even" in v["label"].lower()


def test_aggregate_margin_and_too_early():
    early = aggregate_production_verdict(received_total=0.0, given_total=0.0, n_games=0, metric="total")
    assert "too early" in early["sentence"].lower()
    won = aggregate_production_verdict(received_total=1200.0, given_total=888.0, n_games=40,
                                       metric="total", n_trades=7)
    assert won["tone"] == "good"
    assert "312" in won["sentence"] and "7" in won["sentence"]
