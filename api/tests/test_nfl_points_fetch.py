import asyncio
from app.services.grader_io import fetch_nfl_points
from sleeper_dynasty.models.scoring import ThresholdBonus


class FakeClient:
    def __init__(self):
        self.calls = []
        self.weeks = {
            (2024, 9): {"p1": {"rec": 5.0}},
            (2024, 10): {"p1": {"rec": 3.0}},
        }

    async def get_stats(self, season, week):
        self.calls.append((season, week))
        return self.weeks.get((season, week), {})


class FailClient(FakeClient):
    async def get_stats(self, season, week):
        self.calls.append((season, week))
        raise RuntimeError("sleeper down")


def test_fetch_scores_and_caches(tmp_path):
    from sleeper_dynasty.cache import FileCache
    cache = FileCache(cache_dir=tmp_path)
    client = FakeClient()
    scoring = {"rec": 1.0}
    pts = asyncio.run(fetch_nfl_points(
        client, [(2024, 9), (2024, 10)], scoring, cache))
    assert pts[(2024, 9)]["p1"] == 5.0
    assert pts[(2024, 10)]["p1"] == 3.0
    assert len(client.calls) == 2
    # second run: completed weeks served from cache, no new fetches
    client2 = FakeClient()
    pts2 = asyncio.run(fetch_nfl_points(
        client2, [(2024, 9), (2024, 10)], scoring, cache))
    assert pts2[(2024, 9)]["p1"] == 5.0
    assert client2.calls == []


def test_fetch_failure_degrades_to_zero(tmp_path):
    from sleeper_dynasty.cache import FileCache
    cache = FileCache(cache_dir=tmp_path)
    client = FailClient()
    pts = asyncio.run(fetch_nfl_points(client, [(2024, 9)], {"rec": 1.0}, cache))
    assert pts[(2024, 9)] == {}        # failed fetch -> empty, no exception


def test_live_week_refetched_not_frozen(tmp_path):
    # The in-progress week must never be cached, else its partial stats freeze
    # under the historical TTL once the week completes.
    from sleeper_dynasty.cache import FileCache
    cache = FileCache(cache_dir=tmp_path)
    scoring = {"rec": 1.0}
    live = FakeClient()
    live.weeks[(2024, 11)] = {"p1": {"rec": 9.0}}     # partial, mid-week
    asyncio.run(fetch_nfl_points(
        live, [(2024, 11)], scoring, cache, current_sw=(2024, 11)))
    # next refresh, same live week now final -> must re-fetch, not serve 9.0
    final = FakeClient()
    final.weeks[(2024, 11)] = {"p1": {"rec": 20.0}}
    pts = asyncio.run(fetch_nfl_points(
        final, [(2024, 11)], scoring, cache, current_sw=(2024, 11)))
    assert pts[(2024, 11)]["p1"] == 20.0
    assert final.calls == [(2024, 11)]


def test_cached_raw_stats_are_rescored_for_each_leagues_thresholds(tmp_path):
    from sleeper_dynasty.cache import FileCache

    cache, first, second = FileCache(tmp_path), FakeClient(), FakeClient()
    first_result = asyncio.run(fetch_nfl_points(first, [(2024, 9)], {"rec": 1}, cache,
        bonuses=[ThresholdBonus(("rec",), 5, 3)]))
    second_result = asyncio.run(fetch_nfl_points(second, [(2024, 9)], {"rec": 2}, cache,
        bonuses=[ThresholdBonus(("rec",), 6, 7)]))
    assert first_result[(2024, 9)]["p1"] == 8
    assert second_result[(2024, 9)]["p1"] == 10
    assert second.calls == []
    assert cache.read("nfl_stats_sleeper_2024_9.json") == first.weeks[(2024, 9)]


def test_provider_stat_normalizations_cannot_share_a_cache_entry(tmp_path):
    from sleeper_dynasty.cache import FileCache

    cache, sleeper, yahoo = FileCache(tmp_path), FakeClient(), FakeClient()
    sleeper.weeks[(2024, 9)] = {"def": {"gp": 1, "yds_allow_0_100": 1, "yds_allow": 100}}
    yahoo.weeks[(2024, 9)] = {"def": {"gp": 1, "yds_allow_0_100": 0, "yds_allow": 100}}
    # The old mixed-provider file also cannot be trusted after this change.
    cache.write("nfl_stats_2024_9.json", {"def": {"yds_allow_0_100": 999}})
    scoring, bonuses = {"yds_allow_0_100": 4}, [ThresholdBonus(("yds_allow_0_100",), 1, 2)]
    first = asyncio.run(fetch_nfl_points(sleeper, [(2024, 9)], scoring, cache,
                                         bonuses=bonuses, source_namespace="sleeper"))
    second = asyncio.run(fetch_nfl_points(yahoo, [(2024, 9)], scoring, cache,
                                          bonuses=bonuses, source_namespace="yahoo"))
    assert first[(2024, 9)]["def"] == 6
    assert second[(2024, 9)]["def"] == 0
    assert yahoo.calls == [(2024, 9)]


def test_supporting_data_threads_bonuses_and_keeps_platform_matchups_authoritative(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import app.services.grader_io as io
    from sleeper_dynasty.cache import FileCache
    from sleeper_dynasty.models.league import League

    league = League("470.l.123", "Example", 2026, 2, ["WR", "TE"],
                    {"rec_yd": .1, "rec": 1, "bonus_rec_te": .5}, 15, 2, "in_season",
                    scoring_bonuses=[ThresholdBonus(("rec_yd",), 100, 3)])
    matchup = {"players_points": {"wr": 17.75}, "players": ["wr"], "starters": ["wr"]}
    bundle = {"league_name": league.name, "season": 2026, "playoff_week_start": 15,
              "roster_to_user": {}, "owners": {}, "phase_map": {},
              "matchups": {(league.league_id, 1, 1): matchup}}
    monkeypatch.setattr(io, "fetch_ktc_values", AsyncMock(return_value={}))
    monkeypatch.setattr(io, "fetch_fantasycalc_values", AsyncMock(return_value={}))
    monkeypatch.setattr(io, "_league_matchup_bundle", AsyncMock(return_value=bundle))
    client = SimpleNamespace(
        get_nfl_state=AsyncMock(return_value={"season": 2026, "week": 1}),
        get_stats=AsyncMock(return_value={"wr": {"gp": 1, "rec_yd": 110, "rec": 5},
                                         "te": {"gp": 1, "rec_yd": 100, "rec": 4}}),
    )
    # A warm Sleeper file must not hide the adapter's different conventions.
    FileCache(tmp_path).write("nfl_stats_sleeper_2026_1.json", {"wr": {"rec": 999}})
    result = asyncio.run(io.pull_supporting_data(client, [league],
        players={"wr": {"position": "WR"}, "te": {"position": "TE"}},
        league_cache=SimpleNamespace(cache_dir=tmp_path)))
    assert result["nfl_points"][(2026, 1)] == {"wr": 19, "te": 19}
    assert result["matchups"][(league.league_id, 1, 1)]["players_points"] == {"wr": 17.75}
    client.get_stats.assert_awaited_once_with(2026, 1)


def test_nfl_weeks_to_fetch_includes_wk18_and_caps_current_season():
    from app.services.grader_io import _nfl_weeks_to_fetch
    # a completed season is fetched in full, weeks 1..18 (matchups omit wk18)
    done = _nfl_weeks_to_fetch({2023}, current_sw=(2024, 5))
    assert (2023, 18) in done and len(done) == 18
    # the in-progress season is capped at the current week (no future fetches)
    mixed = _nfl_weeks_to_fetch({2023, 2024}, current_sw=(2024, 5))
    assert (2024, 5) in mixed and (2024, 6) not in mixed
    assert (2023, 18) in mixed
    # offseason / unknown current week -> full seasons
    off = _nfl_weeks_to_fetch({2024}, current_sw=None)
    assert len(off) == 18 and (2024, 18) in off
