from datetime import date

from sleeper_dynasty.models.league import League, Roster, Matchup, DraftPick
from sleeper_dynasty.models.player import Player, PlayerProjection


def test_player_age_calculation():
    player = Player(
        player_id="4046",
        full_name="Patrick Mahomes",
        position="QB",
        team="KC",
        birth_date=date(1995, 9, 17),
    )
    age = player.age(as_of=date(2026, 9, 1))
    assert age == 30


def test_player_age_none_when_no_birth_date():
    player = Player(
        player_id="DEF_KC",
        full_name="Kansas City",
        position="DEF",
        team="KC",
        birth_date=None,
    )
    assert player.age(as_of=date(2026, 9, 1)) is None


def test_player_projection():
    proj = PlayerProjection(
        player_id="4046",
        source="sleeper",
        season=2026,
        week=None,
        projected_points=22.5,
    )
    assert proj.projected_points == 22.5
    assert proj.week is None



def test_league_creation():
    league = League(
        league_id="123",
        name="Dynasty Bros",
        season=2026,
        total_rosters=12,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K", "DEF"],
        scoring_settings={"pass_td": 4.0, "rec": 1.0},
        playoff_week_start=15,
        num_playoff_teams=6,
        status="in_season",
    )
    assert league.name == "Dynasty Bros"
    assert league.total_rosters == 12
    assert league.roster_positions.count("FLEX") == 2


def test_roster_creation():
    roster = Roster(
        roster_id=1,
        owner_id="user_abc",
        owner_name="Tom",
        players=["4046", "6794", "4984"],
        wins=5,
        losses=3,
        ties=0,
        points_for=1205.5,
        points_against=1100.2,
    )
    assert roster.owner_name == "Tom"
    assert len(roster.players) == 3


def test_matchup_creation():
    matchup = Matchup(
        week=1,
        roster_id_1=1,
        roster_id_2=2,
        points_1=None,
        points_2=None,
    )
    assert matchup.week == 1


def test_draft_pick_creation():
    pick = DraftPick(
        season=2027,
        round=1,
        original_owner_id=1,
        current_owner_id=3,
    )
    assert pick.current_owner_id == 3
    assert pick.season == 2027
