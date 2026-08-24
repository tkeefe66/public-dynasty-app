from sleeper_dynasty.engine.injury_live import live_injury


def test_live_injury_currently_out():
    raw = {"injury_status": "Out", "injury_start_date": "2026-09-10", "injury_body_part": "Knee"}
    li = live_injury(raw)
    assert li == {"currently_out": True, "status": "Out", "body_part": "Knee", "since": "2026-09-10"}


def test_live_injury_healthy():
    assert live_injury({"injury_status": None})["currently_out"] is False
    assert live_injury({})["currently_out"] is False
