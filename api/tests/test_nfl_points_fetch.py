import asyncio
from app.services.grader_io import fetch_nfl_points


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
