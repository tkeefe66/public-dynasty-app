from sleeper_dynasty.engine.lineup import solve_optimal_lineup


def test_basic_lineup_no_flex():
    roster_positions = ["QB", "RB", "RB", "WR", "WR", "TE"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 12.0),
        "rb3": ("RB", 8.0),
        "wr1": ("WR", 18.0),
        "wr2": ("WR", 14.0),
        "wr3": ("WR", 10.0),
        "te1": ("TE", 11.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0 + 12.0 + 18.0 + 14.0 + 11.0  # 90.0
    assert "qb1" in starters
    assert "rb1" in starters
    assert "rb2" in starters
    assert "wr1" in starters
    assert "wr2" in starters
    assert "te1" in starters


def test_flex_picks_best_remaining():
    roster_positions = ["QB", "RB", "WR", "TE", "FLEX"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 13.0),
        "wr1": ("WR", 18.0),
        "wr2": ("WR", 16.0),
        "te1": ("TE", 10.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    # FLEX should pick wr2 (16) over rb2 (13)
    assert total == 20.0 + 15.0 + 18.0 + 10.0 + 16.0  # 79.0
    assert "wr2" in starters


def test_superflex_picks_best_qb_or_flex():
    roster_positions = ["QB", "RB", "WR", "TE", "SUPER_FLEX"]
    players = {
        "qb1": ("QB", 22.0),
        "qb2": ("QB", 19.0),
        "rb1": ("RB", 15.0),
        "wr1": ("WR", 14.0),
        "te1": ("TE", 10.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    # SF should take qb2 (19) since it's the best remaining eligible player
    assert total == 22.0 + 15.0 + 14.0 + 10.0 + 19.0  # 80.0
    assert "qb2" in starters


def test_empty_position_scores_zero():
    roster_positions = ["QB", "RB", "WR", "TE", "K"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "wr1": ("WR", 14.0),
        "te1": ("TE", 10.0),
        # no kicker
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0 + 14.0 + 10.0  # 59.0, K slot empty


def test_bench_slots_ignored():
    roster_positions = ["QB", "RB", "BN", "BN", "BN"]
    players = {
        "qb1": ("QB", 20.0),
        "rb1": ("RB", 15.0),
        "rb2": ("RB", 12.0),
    }
    starters, total = solve_optimal_lineup(roster_positions, players)
    assert total == 20.0 + 15.0  # 35.0, bench not scored
    assert len(starters) == 2


def test_realistic_dynasty_lineup_is_fast():
    """Regression test: a 25-player roster with SUPER_FLEX must solve quickly."""
    import time

    roster_positions = [
        "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K", "DEF",
        "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN", "BN",
        "IR", "IR", "TAXI", "TAXI", "TAXI",
    ]
    players = {}
    positions_cycle = ["QB", "RB", "WR", "TE", "K", "DEF"]
    for i in range(25):
        pos = positions_cycle[i % len(positions_cycle)]
        players[f"p{i}"] = (pos, 20.0 - i * 0.3)

    start = time.time()
    starters, total = solve_optimal_lineup(roster_positions, players)
    elapsed = time.time() - start

    assert elapsed < 0.05, f"Solver took {elapsed:.3f}s — must be <50ms"
    assert total > 0
    assert len(starters) > 0
