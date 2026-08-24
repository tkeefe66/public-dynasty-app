from app.services.chain_cache import ChainCacheEntry
from app.services.leaderboard import build_leaderboard


def _entry():
    # Minimal single-owner entry; no trades -> trade_impact zero, but a row exists.
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "Bob", "team_name": "Icky"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={"L": 2025}, cached_at="now",
        outcome_signals={"u1": {}}, outlook_signals={"u1": {}},
        # One completed season, so the owner clears live_ratings' thin-evidence
        # gate and a row exists for the blurb to hang off.
        season_records={"2025": {"u1": {"wins": 7, "losses": 7, "ties": 0}}},
        owner_rating_blurbs={"all": {"u1": {"blurb": "Bob rules.",
                                            "facts_hash": "h", "generated_at": "now"}}},
    )


def test_blurb_attached_for_scope():
    resp = build_leaderboard(_entry(), year="all", prev_ratings={})
    row = next(r for r in resp.rows if r.user_id == "u1")
    assert row.blurb == "Bob rules."


def test_blurb_none_when_missing_for_scope():
    # owner_rating_blurbs only has the "all" scope; the 2025 scope has no entry,
    # so the row's blurb is None.
    resp = build_leaderboard(_entry(), year=2025, prev_ratings={})
    row = next(r for r in resp.rows if r.user_id == "u1")
    assert row.blurb is None
