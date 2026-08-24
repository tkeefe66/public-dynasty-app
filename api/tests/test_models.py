import pytest

from app.models.common import OwnerRef
from app.models.league import (
    DashboardResp,
    HeroStat,
    HeroStats,
    LeagueSummary,
    StandingRow,
    LatestTrade,
    Records,
)
from app.models.owner import OwnerDetailResp, SeasonArc
from app.models.trade import TradeDetailResp, TradeSideView


def test_dashboard_resp_assembles():
    resp = DashboardResp(
        league=LeagueSummary(league_id="L1", name="Bros", season=2026,
                             total_rosters=12, status="in_season",
                             seasons=[2023, 2024, 2025, 2026],
                             last_refreshed="2026-05-28T12:00:00Z"),
        selected_year="all",
        selected_lens="ktc",
        hero_stats=HeroStats(
            top_gm=HeroStat(value="1650", context="GM Rating"),
            biggest_weekly_rise=HeroStat(value="▲3", context="GM Rating positions gained"),
            best_roster=HeroStat(value="14500", context="KTC roster value"),
            draft_ace=HeroStat(value="+0.45", context="draft skill score"),
        ),
        standings=[
            StandingRow(rank=1, user_id="u1",
                        owner=OwnerRef(user_id="u1", owner_name="Tom", team_name="Tom's Team", avatar_url=None),
                        net_ktc=2755, production_total=406.8,
                        production_regular=300.0,
                        production_playoff=80.0,
                        production_toilet=15.0,
                        trades=5, grade="A"),
        ],
        latest_trades=[
            LatestTrade(trade_id="tx1", date="2024-11-12", week=11,
                        parties=[OwnerRef(user_id="u1", owner_name="Tom"), OwnerRef(user_id="u2", owner_name="Mike")],
                        assets_short="Bijan ↔ Justin Jefferson",
                        swing_ktc=2755, swing_prod=406.8),
        ],
        records=Records(
            biggest_value_swing=2755,
            biggest_production=406.8,
            biggest_playoff=120.0,
            most_trades=5,
            biggest_value_swing_owner="Tom",
            biggest_production_owner="Tom",
            biggest_playoff_owner="Tom",
            most_trades_owner="Mike",
        ),
    )
    assert resp.standings[0].grade == "A"


def test_owner_detail_resp_assembles():
    r = OwnerDetailResp(
        league_id="L1",
        user_id="u1",
        owner=OwnerRef(user_id="u1", owner_name="Tom"),
        totals_by_lens={
            "ktc": 2755,
            "production": 406.8,
            "regular": 300.0,
            "playoff": 80.0,
        },
        career_arc=[
            SeasonArc(season=2024, net_ktc=2755, production_total=406.8, trades=5),
        ],
        best_trade_id="tx1",
        worst_trade_id=None,
    )
    assert r.career_arc[0].net_ktc == 2755


def test_trade_detail_resp_assembles():
    r = TradeDetailResp(
        league_id="L1",
        trade_id="tx1",
        date="2024-11-12",
        week=11,
        season=2024,
        league_name="Bros",
        sides=[
            TradeSideView(
                user_id="u1",
                owner_name="Tom",
                received=[{"kind": "player", "name": "Bijan Robinson"}],
                given=[{"kind": "player", "name": "Justin Jefferson"}],
                snapshot_ktc_swing=2755,
                production_total=406.8,
                production_regular=300.0,
                production_playoff=80.0,
                production_toilet=15.0,
            ),
        ],
    )
    assert r.sides[0].snapshot_ktc_swing == 2755
