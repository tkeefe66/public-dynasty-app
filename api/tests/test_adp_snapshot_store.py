from datetime import date

from app.services.adp_snapshot_store import AdpSnapshotStore

# Daily files hold every scoring variant at once (see the store's module
# docstring), so the fixtures below spell one out rather than a bare map.
PPR = "adp_ppr"
QB2 = "adp_2qb"


def daily(**by_variant: dict[str, float]) -> dict[str, dict[str, float]]:
    return dict(by_variant)


def test_capture_then_read_round_trips(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    assert store.capture("d1", {"p1": 12.5, "p2": 40.0}) is True
    assert store.read("d1") == {"p1": 12.5, "p2": 40.0}


def test_capture_is_write_once(tmp_path):
    """The draft-day baseline is the whole point. A later refresh must never
    overwrite it with mid-season ADP, or 'beat the market' becomes 'beat
    hindsight'."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 12.5})
    assert store.capture("d1", {"p1": 99.0}) is False
    assert store.read("d1") == {"p1": 12.5}


def test_read_of_an_uncaptured_draft_is_none(tmp_path):
    assert AdpSnapshotStore(tmp_path).read("nope") is None


def test_empty_capture_is_refused(tmp_path):
    """An empty ADP map means the fetch failed. Writing it would permanently
    poison this draft's baseline, since capture is write-once."""
    store = AdpSnapshotStore(tmp_path)
    assert store.capture("d1", {}) is False
    assert store.read("d1") is None


def test_corrupt_snapshot_reads_as_none(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text("{not json")
    assert store.read("d1") is None


def test_snapshot_with_nonnumeric_string_value_reads_as_none(tmp_path):
    """Semantically-corrupt snapshot: value is not a number. Must degrade
    to None, not raise ValueError on float coercion."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text('{"p1": "not-a-number"}')
    assert store.read("d1") is None


def test_snapshot_with_noncoercible_value_reads_as_none(tmp_path):
    """Semantically-corrupt snapshot: value is a non-coercible type (list).
    Must degrade to None, not raise TypeError on float coercion."""
    store = AdpSnapshotStore(tmp_path)
    store.capture("d1", {"p1": 1.0})
    (tmp_path / "adp" / "d1.json").write_text('{"p1": [1, 2, 3]}')
    assert store.read("d1") is None


def test_daily_capture_is_dated_and_listable(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    assert store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 14)) is True
    assert store.capture_daily(daily(adp_ppr={"p1": 5.0}), date(2026, 8, 16)) is True
    assert store.list_dates() == [date(2026, 8, 14), date(2026, 8, 16)]


def test_daily_capture_is_write_once_per_day(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 14))
    assert store.capture_daily(
        daily(adp_ppr={"p1": 99.0}), date(2026, 8, 14)) is False


def test_empty_daily_capture_is_refused(tmp_path):
    assert AdpSnapshotStore(tmp_path).capture_daily({}, date(2026, 8, 14)) is False


def test_daily_capture_of_only_empty_variants_is_refused(tmp_path):
    """Every variant empty is the same failed fetch as no variants at all —
    and write-once means storing it poisons the day permanently."""
    store = AdpSnapshotStore(tmp_path)
    assert store.capture_daily(daily(adp_ppr={}, adp_2qb={}), date(2026, 8, 14)) is False
    assert store.list_dates() == []


def test_resolve_uses_the_snapshot_from_the_drafts_own_day(tmp_path):
    """Two leagues, two draft dates, two different markets."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 1))
    store.capture_daily(daily(adp_ppr={"p1": 20.0}), date(2026, 8, 26))
    assert store.resolve_for_draft(
        "early", date(2026, 8, 1), field=PPR) == {"p1": 3.0}
    assert store.resolve_for_draft(
        "late", date(2026, 8, 26), field=PPR) == {"p1": 20.0}


def test_resolve_falls_back_to_the_nearest_earlier_day(tmp_path):
    """A draft is graded against the market as it stood going IN, never after."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 10))
    store.capture_daily(daily(adp_ppr={"p1": 20.0}), date(2026, 8, 20))
    assert store.resolve_for_draft(
        "mid", date(2026, 8, 15), field=PPR) == {"p1": 3.0}


def test_resolve_is_none_when_no_snapshot_predates_the_draft(tmp_path):
    """A draft older than our snapshot history has no baseline, permanently.
    Returning a later snapshot would be grading against hindsight."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 20))
    assert store.resolve_for_draft("ancient", date(2026, 5, 6), field=PPR) is None


def test_resolve_pins_the_result_write_once(tmp_path):
    """Once resolved, a draft's baseline is frozen — later daily snapshots
    must never change it."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 1))
    assert store.resolve_for_draft("d1", date(2026, 8, 1), field=PPR) == {"p1": 3.0}
    store.capture_daily(daily(adp_ppr={"p1": 99.0}), date(2026, 8, 2))
    assert store.resolve_for_draft("d1", date(2026, 8, 2), field=PPR) == {"p1": 3.0}


# --- Scoring-variant namespacing --------------------------------------------
#
# The install is multi-tenant: a superflex dynasty league and a PPR redraft
# league share one cache dir. Before this, whichever refreshed first each day
# wrote its own variant into a single dated file, and — daily file and
# per-draft file both being write-once — froze the wrong board into the other
# league's class forever.

def test_each_variant_resolves_to_its_own_market(tmp_path):
    """QBs sit ~20-25 picks higher in 2QB than in PPR. One dated file, two
    readings, neither able to pin the other."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(
        daily(adp_ppr={"qb1": 45.0}, adp_2qb={"qb1": 20.0}), date(2026, 8, 11))
    assert store.resolve_for_draft(
        "ppr-league", date(2026, 8, 11), field=PPR) == {"qb1": 45.0}
    assert store.resolve_for_draft(
        "sf-league", date(2026, 8, 11), field=QB2) == {"qb1": 20.0}


def test_one_leagues_refresh_captures_every_leagues_variant(tmp_path):
    """The redraft league's baseline must not depend on the redraft league
    being the one that refreshed that day."""
    store = AdpSnapshotStore(tmp_path)
    # A superflex dynasty league happens to refresh first.
    store.capture_daily(
        daily(adp_ppr={"p1": 30.0}, adp_2qb={"p1": 12.0}), date(2026, 8, 11))
    assert store.resolve_for_draft(
        "redraft", date(2026, 8, 11), field=PPR) == {"p1": 30.0}


def test_resolve_skips_a_day_missing_that_variant_and_walks_back(tmp_path):
    """A day that carries nothing for this variant is stepped OVER, backward
    — never forward, which would be hindsight grading."""
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 10))
    store.capture_daily(daily(adp_2qb={"p1": 99.0}), date(2026, 8, 12))
    assert store.resolve_for_draft(
        "d1", date(2026, 8, 13), field=PPR) == {"p1": 3.0}


def test_resolve_is_none_when_no_earlier_day_has_the_variant(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_2qb={"p1": 99.0}), date(2026, 8, 12))
    assert store.resolve_for_draft("d1", date(2026, 8, 13), field=PPR) is None


def test_corrupt_daily_file_is_stepped_over_not_raised(tmp_path):
    store = AdpSnapshotStore(tmp_path)
    store.capture_daily(daily(adp_ppr={"p1": 3.0}), date(2026, 8, 10))
    store.capture_daily(daily(adp_ppr={"p1": 20.0}), date(2026, 8, 12))
    (tmp_path / "adp" / "daily" / "2026-08-12.json").write_text("{not json")
    assert store.resolve_for_draft(
        "d1", date(2026, 8, 13), field=PPR) == {"p1": 3.0}


def test_legacy_flat_daily_file_is_ignored_rather_than_misread(tmp_path):
    """A pre-namespacing file carries no record of WHICH scoring wrote it.
    Reading it back for an arbitrary variant is the exact bug — so it reads
    as absent, and resolution walks past it."""
    store = AdpSnapshotStore(tmp_path)
    (tmp_path / "adp" / "daily").mkdir(parents=True)
    (tmp_path / "adp" / "daily" / "2026-08-12.json").write_text('{"p1": 7.0}')
    assert store.resolve_for_draft("d1", date(2026, 8, 13), field=PPR) is None
