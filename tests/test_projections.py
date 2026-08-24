from sleeper_dynasty.api.projections import blend_projections, normalize_projection
from sleeper_dynasty.models.player import FantasyProsProjection, PlayerProjection
from sleeper_dynasty.util.name_match import normalize_player_name


def test_blend_prefers_fantasypros_when_available():
    sleeper = PlayerProjection(
        player_id="4046", source="sleeper", season=2026, week=None,
        projected_points=20.0,
    )
    fp = PlayerProjection(
        player_id="4046", source="fantasypros", season=2026, week=None,
        projected_points=24.0,
    )
    blended = blend_projections(sleeper_proj=sleeper, external_proj=fp)
    # 40% sleeper + 60% fantasypros = 0.4*20 + 0.6*24 = 22.4
    assert abs(blended.projected_points - 22.4) < 0.01
    assert blended.source == "blended"


def test_blend_uses_sleeper_only_when_no_external():
    sleeper = PlayerProjection(
        player_id="4046", source="sleeper", season=2026, week=None,
        projected_points=20.0,
    )
    blended = blend_projections(sleeper_proj=sleeper, external_proj=None)
    assert blended.projected_points == 20.0
    assert blended.source == "sleeper"


def test_normalize_projection_ppr():
    scoring = {"rec": 1.0, "pass_td": 4.0, "rush_td": 6.0, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1}
    stats = {"rec": 5.0, "pass_td": 2.0, "rush_td": 0.0, "pass_yd": 250.0, "rush_yd": 0.0, "rec_yd": 60.0}
    # 5*1 + 2*4 + 0 + 250*0.04 + 0 + 60*0.1 = 5 + 8 + 10 + 6 = 29.0
    points = normalize_projection(stats, scoring)
    assert abs(points - 29.0) < 0.01


def test_normalize_projection_half_ppr():
    scoring = {"rec": 0.5, "rush_td": 6.0, "rush_yd": 0.1, "rec_yd": 0.1}
    stats = {"rec": 4.0, "rush_td": 1.0, "rush_yd": 80.0, "rec_yd": 40.0}
    # 4*0.5 + 1*6 + 80*0.1 + 40*0.1 = 2 + 6 + 8 + 4 = 20.0
    points = normalize_projection(stats, scoring)
    assert abs(points - 20.0) < 0.01


def test_blend_uses_fantasypros_stats_renormalized_to_league_scoring():
    """End-to-end blending logic: take a FantasyProsProjection, run its
    stats through normalize_projection against the league's scoring
    settings, build a PlayerProjection from it, and blend with Sleeper.
    This is the exact code path the CLI now uses.
    """
    fp = FantasyProsProjection(
        name="A.J. Brown",
        normalized_name=normalize_player_name("A.J. Brown"),
        team="PHI",
        position="WR",
        stats={"rec": 80.0, "rec_yd": 1100.0, "rec_td": 8.0, "fum_lost": 1.0},
        projected_points_ppr=238.0,
    )
    # Half-PPR scoring. Re-normalized: 80*0.5 + 1100*0.1 + 8*6 + 1*-2 = 196
    half_ppr_scoring = {
        "rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0, "fum_lost": -2.0,
    }
    league_pts = normalize_projection(fp.stats, half_ppr_scoring)
    assert abs(league_pts - 196.0) < 0.01

    # Per-week mean assuming 14 regular-season weeks.
    weekly = league_pts / 14
    fp_proj = PlayerProjection(
        player_id="",
        source="fantasypros",
        season=2026,
        week=None,
        projected_points=weekly,
        stats=fp.stats,
    )
    sleeper = PlayerProjection(
        player_id="6794", source="sleeper", season=2026, week=None,
        projected_points=12.5,
    )
    blended = blend_projections(sleeper, fp_proj)
    expected = 0.4 * 12.5 + 0.6 * weekly  # 0.4*12.5 + 0.6*14.0 = 13.4
    assert abs(blended.projected_points - expected) < 0.01
    assert blended.source == "blended"


def test_blend_falls_back_when_fantasypros_match_missing():
    """If normalized-name lookup misses, blend_projections gets None for
    the external arg and we keep the Sleeper-only number unchanged.
    """
    external_by_norm_name: dict[str, PlayerProjection] = {}
    sleeper_name = "Marvin Harrison Jr."
    sleeper_proj = PlayerProjection(
        player_id="X", source="sleeper", season=2026, week=None,
        projected_points=15.0,
    )
    external = external_by_norm_name.get(normalize_player_name(sleeper_name))
    blended = blend_projections(sleeper_proj, external)
    assert blended.projected_points == 15.0
    assert blended.source == "sleeper"


def test_normalized_name_match_handles_punctuation_diff():
    """The bug we're fixing: 'A.J. Brown' on FP should join 'AJ Brown'
    on Sleeper through normalized-name lookup.
    """
    external_by_norm_name = {
        normalize_player_name("A.J. Brown"): PlayerProjection(
            player_id="", source="fantasypros", season=2026, week=None,
            projected_points=14.0,
        )
    }
    sleeper_full_name = "AJ Brown"
    hit = external_by_norm_name.get(normalize_player_name(sleeper_full_name))
    assert hit is not None
    assert hit.projected_points == 14.0
