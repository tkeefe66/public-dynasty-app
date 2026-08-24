from datetime import date

from app.services.realized_value import make_price_providers


class _FakeStore:
    """match() returns a dated snapshot keyed by name -> object with .superflex_value."""
    def __init__(self, by_date):
        self._by_date = by_date  # {date: {normalized_name: KTCValueLike}}

    def match(self, d, cutoff):
        snap = self._by_date.get(d)
        return (snap, d, False) if snap is not None else (None, None, False)


class _V:
    """Minimal KTCValue-like stub.

    ``name`` defaults to "Not A Pick" — that string doesn't match the pick-name
    regex, so build_pick_value_table skips it — intentional; we're exercising
    the player path, not picks.
    """
    def __init__(self, sf, name="Not A Pick"):
        self.superflex_value = sf
        self.name = name
        self.one_qb_value = None


def test_price_player_today_and_dated():
    today_ktc = {"C": _V(4800)}
    # The snapshot is keyed by *normalized* name ("cee") because
    # resolve_ktc_to_player_id normalizes raw_players[pid]["full_name"]
    # and looks it up in the snapshot dict.
    store = _FakeStore({date(2027, 9, 1): {"cee": _V(6000)}})
    raw_players = {"C": {"full_name": "Cee"}}
    pp, _ = make_price_providers(
        store=store, raw_players=raw_players,
        today_ktc_by_pid=today_ktc, today_pick_table={},
        cutoff=date(2026, 5, 1),
    )
    # Today's value comes straight from today_ktc_by_pid
    assert pp("C", None) == 4800.0
    # Dated value resolves through the snapshot: "cee" -> pid "C" -> 6000
    dated = pp("C", "2027-09-01")
    assert dated == 6000.0, f"expected 6000 from snapshot but got {dated}"
    # Sanity: today != dated, proving the dated branch didn't silently fall back
    assert dated != pp("C", None), "dated should differ from today (4800 vs 6000)"


def test_price_player_falls_back_to_today_when_no_snapshot():
    today_ktc = {"C": _V(4800)}
    store = _FakeStore({})  # no snapshots at all -> match() returns (None, None, False)
    pp, _ = make_price_providers(
        store=store, raw_players={"C": {"full_name": "Cee"}},
        today_ktc_by_pid=today_ktc, today_pick_table={},
        cutoff=date(2026, 5, 1),
    )
    assert pp("C", "2030-01-01") == 4800.0   # fell back to today's table
