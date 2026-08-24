import asyncio

from app.services.blurb_gen import BLURB_PROMPT_VERSION, generate_owner_rating_blurbs
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash


def _prior_hash(facts) -> str:
    """The skip-hash the generator stores: facts hash + prompt version."""
    return f"{rating_facts_hash(facts)}:{BLURB_PROMPT_VERSION}"


def _facts(uid, rating):
    return OwnerRatingFacts(
        user_id=uid, owner_name=uid, team_name=None, scope_label="career",
        rank=1, rating=rating, pillars=[], championships=0,
        made_playoffs_rate=0.0, draft_capital_counted=False,
    )


class _FakeWriter:
    def __init__(self):
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return {"blurb": f"{facts.owner_name}@{facts.rating}"}


def test_generates_and_skips_unchanged():
    w = _FakeWriter()
    facts_by_scope = {"all": {"u1": _facts("u1", 1700), "u2": _facts("u2", 1500)}}
    prior = {"all": {"u1": {"blurb": "old", "facts_hash": _prior_hash(_facts("u1", 1700)),
                            "generated_at": "t0"}}}
    out = asyncio.run(generate_owner_rating_blurbs(
        facts_by_scope=facts_by_scope, prior_blurbs=prior, writer=w))
    # u1 unchanged -> reused prior; u2 newly written
    assert out["all"]["u1"]["blurb"] == "old"
    assert out["all"]["u2"]["blurb"] == "u2@1500"
    assert w.calls == 1


def test_regenerates_when_rating_changes():
    w = _FakeWriter()
    facts_by_scope = {"all": {"u1": _facts("u1", 1800)}}
    prior = {"all": {"u1": {"blurb": "old", "facts_hash": _prior_hash(_facts("u1", 1700)),
                            "generated_at": "t0"}}}
    out = asyncio.run(generate_owner_rating_blurbs(
        facts_by_scope=facts_by_scope, prior_blurbs=prior, writer=w))
    assert out["all"]["u1"]["blurb"] == "u1@1800"
    assert w.calls == 1


def _multi_season_entry():
    """A three-season, two-owner league with nobody trading."""
    from app.services.chain_cache import ChainCacheEntry

    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "Alice"}, "u2": {"owner_name": "Bob"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={"L1": 2023, "L2": 2024, "L3": 2025},
        cached_at="2026-08-16T00:00:00+00:00",
        outcome_signals={
            "u1": {"expected_wins": 0.7, "playoff_success": 0.9, "luck": 0.1},
            "u2": {"expected_wins": 0.3, "playoff_success": 0.4, "luck": -0.1},
        },
        outlook_signals={
            "u1": {"roster_value_share": 0.6, "young_core_share": 0.6, "draft_capital": 0.6},
            "u2": {"roster_value_share": 0.4, "young_core_share": 0.4, "draft_capital": 0.4},
        },
        season_records={
            str(y): {"u1": {"wins": 10, "losses": 4, "ties": 0},
                     "u2": {"wins": 4, "losses": 10, "ties": 0}}
            for y in (2023, 2024, 2025)
        },
    )


def test_facts_are_built_for_the_all_time_scope_only():
    """The v2 rating is all-time and decayed — live_ratings ignores `year`. A
    per-season scope would stamp "the 2023 season" onto a career grade and pay
    Haiku to assert it: 5 seasons x 12 owners = 72 calls, 60 of them fiction."""
    from app.services.blurb_gen import owner_rating_facts_by_scope

    out = owner_rating_facts_by_scope(_multi_season_entry())
    assert list(out) == ["all"]
    assert set(out["all"]) == {"u1", "u2"}
    assert all(f.scope_label == "career" for f in out["all"].values())


def test_a_league_of_non_traders_still_gets_its_all_time_facts():
    """The retired `_scope_is_ratable` gate withheld the blurb (and with it the
    Overview tab's pillar highlights) unless two owners had traded — a v1
    proxy for "the rating has something to say" that v2 invalidated when it
    dropped the Skill pillar and with it every trade signal."""
    from app.services.blurb_gen import owner_rating_facts_by_scope

    entry = _multi_season_entry()
    assert entry.resolved_trades == []
    assert set(owner_rating_facts_by_scope(entry)["all"]) == {"u1", "u2"}
