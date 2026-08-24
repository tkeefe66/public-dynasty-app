import asyncio
from datetime import datetime

from app.services.story_gen import generate_stories
from sleeper_dynasty.models.trade import (
    PlayerAsset, PickAsset, Trade, TradeSide, ResolvedTrade,
)


class FakeWriter:
    def __init__(self):
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return {"verdict": f"V {facts.trade_id}", "body": "B"}


def _rt(tx):
    pick = PickAsset(season=2025, round=1, original_owner_user_id="u_mike")
    player = PlayerAsset(player_id="p1", name="Bijan Robinson")
    mike = TradeSide("u_mike", received=[player], given=[pick])
    tom = TradeSide("u_tom", received=[pick], given=[player])
    t = Trade(tx, "L", 2024, 1, datetime(2024, 6, 1),
              {"u_mike": mike, "u_tom": tom})
    return ResolvedTrade(trade=t, sides={"u_mike": mike, "u_tom": tom})


def _supporting():
    return dict(matchups={}, roster_to_user_by_league={},
                playoff_weeks_by_league={}, league_season_by_id={"L": 2024},
                positions={}, owners_display={"u_mike": "Mike", "u_tom": "Tom"})


def test_generates_for_new_trades_and_skips_unchanged():
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    writer = FakeWriter()

    stories, dossiers = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_concurrency=4,
    ))
    assert writer.calls == 1
    assert stories["t1"]["verdict"] == "V t1"
    assert "facts_hash" in stories["t1"] and "u_mike" in dossiers

    # Re-run with the prior stories; same facts => skipped.
    writer2 = FakeWriter()
    stories2, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories=stories, writer=writer2, max_concurrency=4,
    ))
    assert writer2.calls == 0
    assert stories2["t1"]["verdict"] == "V t1"


def test_throttle_reuses_changed_prior_but_still_makes_new():
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    w1 = FakeWriter()
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=w1,
    ))
    # Corrupt the prior hash so it no longer matches — without the throttle this
    # would regenerate; with it, the existing story is reused verbatim.
    stories["t1"]["facts_hash"] = "stale-does-not-match"

    # New trade t2 has no prior, so it must still generate even while throttled.
    resolved2 = [_rt("t1"), _rt("t2")]
    grades2 = {"t1": grades["t1"], "t2": grades["t1"]}
    w2 = FakeWriter()
    out, _ = asyncio.run(generate_stories(
        resolved=resolved2, grades=grades2, supporting=_supporting(),
        prior_stories=stories, writer=w2, reuse_prior_on_throttle=True,
    ))
    assert w2.calls == 1            # only the brand-new t2 generated
    assert out["t1"]["verdict"] == "V t1"   # changed-hash prior reused
    assert out["t2"]["verdict"] == "V t2"


def test_persistent_failure_is_isolated_and_retried():
    class Boom(FakeWriter):
        def write(self, facts):
            self.calls += 1
            raise RuntimeError("api down")

    boom = Boom()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=boom, max_attempts=3, retry_delay=0,
    ))
    assert stories == {}            # failed trade simply absent
    assert boom.calls == 3          # retried up to max_attempts


def test_transient_failure_is_backfilled_on_retry():
    class Flaky(FakeWriter):
        def __init__(self):
            super().__init__()
            self.failed_once = set()

        def write(self, facts):
            self.calls += 1
            if facts.trade_id not in self.failed_once:
                self.failed_once.add(facts.trade_id)
                raise RuntimeError("overloaded")
            return {"verdict": f"V {facts.trade_id}", "body": "B"}

    flaky = Flaky()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=flaky, max_attempts=3, retry_delay=0,
    ))
    assert stories["t1"]["verdict"] == "V t1"   # backfilled on the retry
    assert flaky.calls == 2                       # failed once, then succeeded


def test_reversed_story_regenerates_then_caches_clean_version():
    # _rt: Mike RECEIVED Bijan Robinson. A story that says Mike "sold" him is a
    # reversal -> regenerate. The second sample is clean -> cache it.
    class ReversalThenClean(FakeWriter):
        def write(self, facts):
            self.calls += 1
            if self.calls == 1:
                return {"verdict": "Mike sells low",
                        "body": "Mike sold Bijan Robinson for a pick."}
            return {"verdict": "Mike wins big",
                    "body": "Mike landed Bijan Robinson for a pick."}

    writer = ReversalThenClean()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_attempts=3, retry_delay=0,
    ))
    assert writer.calls == 2
    assert stories["t1"]["verdict"] == "Mike wins big"


def test_persistently_reversed_story_is_shipped_best_effort():
    # If every sample reverses, ship the last one anyway -- a flawed story beats
    # a missing one (same philosophy as never failing a refresh on a story error).
    class AlwaysReversal(FakeWriter):
        def write(self, facts):
            self.calls += 1
            return {"verdict": "Mike sells low",
                    "body": "Mike sold Bijan Robinson for a pick."}

    writer = AlwaysReversal()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_attempts=2, retry_delay=0,
    ))
    assert writer.calls == 2          # exhausted the attempts trying to fix it
    assert "t1" in stories            # but still shipped, not dropped


class _FakeWriter:
    def __init__(self):
        self.seen = []

    def write(self, facts):
        self.seen.append(facts)
        return {"verdict": "v", "body": "b"}


def _resolved_and_dicts():
    recv = PickAsset(season=2026, round=1, original_owner_user_id="u_x",
                     drafted_player_id="ML", drafted_player_name="Makai Lemon")
    a = TradeSide(user_id="u_a", received=[recv], given=[])
    b = TradeSide(user_id="u_b", received=[], given=[recv])
    t = Trade(transaction_id="t1", league_id="L", season=2025, week=10,
              traded_at=datetime(2025, 11, 7),
              sides={"u_a": a, "u_b": b})
    rt = ResolvedTrade(trade=t, sides={"u_a": a, "u_b": b})
    dicts = [{"trade": {"transaction_id": "t1",
                        "traded_at": "2025-11-07T00:00:00"},
              "sides": {"u_a": {"user_id": "u_a",
                                "received": [{"season": 2026, "round": 1,
                                              "original_owner_user_id": "u_x",
                                              "drafted_player_id": "ML",
                                              "drafted_player_name": "Makai Lemon"}],
                                "given": []},
                        "u_b": {"user_id": "u_b", "received": [],
                                "given": [{"season": 2026, "round": 1,
                                           "original_owner_user_id": "u_x",
                                           "drafted_player_id": "ML",
                                           "drafted_player_name": "Makai Lemon"}]}}}]
    return rt, dicts


def test_structured_story_is_cached_with_lede_and_beats():
    class StructuredWriter(FakeWriter):
        def write(self, facts):
            self.calls += 1
            return {"verdict": f"V {facts.trade_id}", "lede": "L",
                    "beats": ["b1", "b2"], "body": "L\nb1\nb2"}

    writer = StructuredWriter()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_concurrency=4,
    ))
    assert stories["t1"]["lede"] == "L"
    assert stories["t1"]["beats"] == ["b1", "b2"]


def test_generate_stories_passes_current_holders_into_facts():
    rt, dicts = _resolved_and_dicts()
    writer = _FakeWriter()
    supporting = {
        "owners_display": {"u_a": "A", "u_b": "B"},
        "matchups": {}, "roster_to_user_by_league": {},
        "playoff_weeks_by_league": {}, "league_season_by_id": {"L": 2025},
        "positions": {},
    }
    stories, _ = asyncio.run(generate_stories(
        resolved=[rt], grades={}, supporting=supporting,
        prior_stories={}, writer=writer, resolved_dicts=dicts,
        current_holders={},  # ML not held -> dropped fate reaches the writer
    ))
    assert "t1" in stories
    a = next(s for s in writer.seen[0].sides if s["user_id"] == "u_a")
    assert a["pick_outcomes"][0]["terminal_state"] == "dropped"
