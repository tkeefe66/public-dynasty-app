from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)
from sleeper_dynasty.engine.franchise_outlook import MAX_LISTED, build_franchise_facts


def _facts(**over):
    base = dict(
        user_id="uA", owner_name="Alice", team_name="Team A",
        league_format="dynasty", window="Contending", young_core_share=0.62,
        roster_rank=3, roster_of=12,
        young_core=["Young Gun"], aging_risks=["Old Back"],
        draft_capital_status="pick-rich", draft_capital_net=3.0,
        top_need="RB (immediate)", signature_trade="received Bijan (+1400)",
    )
    base.update(over)
    return FranchiseFacts(**base)


def test_to_dict_is_json_safe_and_complete():
    import json
    d = _facts().to_dict()
    json.dumps(d)
    assert d["window"] == "Contending"
    assert d["young_core"] == ["Young Gun"]
    assert d["league_format"] == "dynasty"
    assert d["young_core_share"] == 0.62


def test_hash_stable_and_sensitive():
    h1 = franchise_facts_hash(_facts())
    h2 = franchise_facts_hash(_facts())
    h3 = franchise_facts_hash(_facts(window="Rebuilding"))
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16


# --- pruning: a fact that says nothing is not sent (B1) ---------------------

def test_neutral_draft_capital_is_omitted_entirely():
    """A model told "use ONLY these facts" will reach for a signal that carries
    no information. "that neutral draft capital" was in the shipped prose."""
    d = _facts(draft_capital_status="neutral", draft_capital_net=0.0).to_dict()
    assert "draft_capital_status" not in d
    assert "draft_capital_net" not in d


def test_near_zero_draft_capital_net_is_omitted_with_its_status():
    d = _facts(draft_capital_status="pick-rich", draft_capital_net=0.0).to_dict()
    assert "draft_capital_status" not in d and "draft_capital_net" not in d


def test_informative_draft_capital_survives():
    d = _facts(draft_capital_status="pick-poor", draft_capital_net=-4.0).to_dict()
    assert d["draft_capital_status"] == "pick-poor"
    assert d["draft_capital_net"] == -4.0


def test_empty_and_null_fields_are_omitted():
    d = _facts(team_name=None, aging_risks=[], top_need=None,
               signature_trade=None, window="").to_dict()
    for k in ("team_name", "aging_risks", "top_need", "signature_trade", "window"):
        assert k not in d
    # Identity is never pruned — the packet has to name whose franchise it is.
    assert d["user_id"] == "uA" and d["owner_name"] == "Alice"


def test_a_zero_young_core_share_is_kept_but_an_absent_one_is_dropped():
    # 0.0 means "no value in players 25-and-under" — that is a fact.
    assert _facts(young_core_share=0.0).to_dict()["young_core_share"] == 0.0
    assert "young_core_share" not in _facts(young_core_share=None).to_dict()


def test_pruning_moves_the_hash():
    """Otherwise a packet that stopped carrying a dead signal would reuse the
    prose written from it."""
    full = _facts(draft_capital_status="neutral", draft_capital_net=0.0)
    assert franchise_facts_hash(full) != franchise_facts_hash(_facts())


_OUTLOOK = {
    "window": "Ascending", "trajectory": "young + pick-rich",
    "age_profile": {
        "avg_age_by_position": {"RB": 23.5}, "overall_avg_age": 24.2,
        "aging_risks": [{"player_id": "rb_old", "full_name": "Old Back", "position": "RB", "age": 29}],
        "core_young": [{"player_id": "wr_y", "full_name": "Young Gun", "position": "WR", "age": 22}],
    },
    "draft_capital": {"picks_by_season": {"2027": 5}, "picks_by_season_round": {},
                      "net_vs_average": 3.0, "status": "pick-rich"},
    "draft_needs": [{"position": "RB", "urgency": "immediate", "reason": "thin"},
                    {"position": "TE", "urgency": "developing", "reason": "ok"}],
}


def test_build_franchise_facts_reads_roster_shape_from_the_outlook_dict():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name="Team A",
        outlook=_OUTLOOK, roster_rank={"rank": 3, "of": 12},
        signature_trade="received Bijan (+1400)")
    # window is NOT pulled from the outlook dict any more (Assets-led
    # redesign) — it defaults to "" here since no window= was passed. See
    # test_a_stale_blob_cannot_leak_a_retired_stage_into_the_packet below.
    assert facts.window == ""
    assert facts.young_core == ["Young Gun"]
    assert facts.aging_risks == ["Old Back"]
    assert facts.top_need == "RB (immediate)"   # first/most-urgent need
    assert facts.roster_rank == 3 and facts.roster_of == 12
    assert facts.draft_capital_net == 3.0


def test_build_franchise_facts_tolerates_missing_rank_and_needs():
    ol = {**_OUTLOOK, "draft_needs": []}
    facts = build_franchise_facts(
        user_id="uB", owner_name="Bob", team_name=None,
        outlook=ol, roster_rank=None, signature_trade=None)
    assert facts.top_need is None
    assert facts.roster_rank is None and facts.roster_of is None


def test_mean_age_and_its_prose_never_reach_the_packet():
    """`trajectory` embeds the mean roster age verbatim ("avg 27.4") and
    `overall_avg_age` is that mean. Mean age is the metric v2 dropped from the
    rating because it measures bench filler, which is how a roster with three
    good young players got described as trending downward. One theory of
    "young" across the grade and the prose: young_core_share."""
    d = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_OUTLOOK,
        roster_rank=None, signature_trade=None, young_core_share=0.41).to_dict()
    assert "trajectory" not in d and "overall_avg_age" not in d
    assert d["young_core_share"] == 0.41


def test_league_format_reaches_the_packet():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_OUTLOOK,
        roster_rank=None, signature_trade=None, league_format="redraft")
    assert facts.to_dict()["league_format"] == "redraft"


def test_league_format_defaults_to_dynasty():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_OUTLOOK,
        roster_rank=None, signature_trade=None)
    assert facts.league_format == "dynasty"


# --- bounding: top three, by value (B1) ------------------------------------

def _many(n, prefix, ages):
    return [{"player_id": f"{prefix}{i}", "full_name": f"{prefix} {i}",
             "position": "WR", "age": ages[i]} for i in range(n)]


_CROWDED = {
    **_OUTLOOK,
    "age_profile": {
        **_OUTLOOK["age_profile"],
        "core_young": _many(5, "Kid", [22, 23, 24, 25, 21]),
        "aging_risks": _many(8, "Vet", [30, 31, 29, 32, 33, 30, 34, 29]),
    },
}


def test_lists_are_capped_at_three_each():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_CROWDED,
        roster_rank=None, signature_trade=None)
    assert MAX_LISTED == 3
    assert len(facts.young_core) == 3
    assert len(facts.aging_risks) == 3


def test_the_three_kept_are_the_most_valuable_ones():
    values = {"Kid3": 9000.0, "Kid0": 100.0, "Kid1": 8000.0,
              "Kid2": 50.0, "Kid4": 7000.0,
              "Vet6": 6000.0, "Vet1": 5000.0, "Vet4": 4000.0}
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_CROWDED,
        roster_rank=None, signature_trade=None, value_by_player=values)
    assert facts.young_core == ["Kid 3", "Kid 1", "Kid 4"]
    assert facts.aging_risks == ["Vet 6", "Vet 1", "Vet 4"]


def test_without_values_the_fallback_is_age_and_is_not_list_order():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_CROWDED,
        roster_rank=None, signature_trade=None)
    # Youngest core pieces, oldest risks — not the first three of the list.
    assert facts.young_core == ["Kid 4", "Kid 0", "Kid 1"]   # 21, 22, 23
    assert facts.aging_risks == ["Vet 6", "Vet 4", "Vet 3"]  # 34, 33, 32


def test_value_sort_is_deterministic_when_values_tie():
    values = {f"Kid{i}": 500.0 for i in range(5)}
    a = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_CROWDED,
        roster_rank=None, signature_trade=None, value_by_player=values)
    b = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name=None, outlook=_CROWDED,
        roster_rank=None, signature_trade=None, value_by_player=values)
    assert a.young_core == b.young_core


# --- window is a parameter, not a blob read (stale-cache safety) -----------

def _stale_blob() -> dict:
    """A pre-feature serialized outlook: it still carries a RETIRED stage."""
    return {
        "window": "Peaking",
        "trajectory": "Strong roster but aging (avg 27.4)...",
        "age_profile": {"core_young": [], "aging_risks": []},
        "draft_capital": {"status": "pick-rich", "net_vs_average": 2.0},
        "draft_needs": [{"position": "RB", "urgency": "immediate", "reason": "x"}],
    }


def test_a_stale_blob_cannot_leak_a_retired_stage_into_the_packet():
    """The ONE stale-read path the no-bump decision leaves open. `window` is a
    parameter; the blob's own key is never consulted."""
    facts = build_franchise_facts(
        user_id="u1", owner_name="Tom", team_name=None,
        outlook=_stale_blob(), roster_rank={"rank": 3, "of": 12},
        signature_trade=None, window="Contending",
    )
    assert facts.window == "Contending"
    assert "Peaking" not in str(facts.to_dict())


def test_an_unrated_owner_sends_no_window_at_all():
    """window="" is pruned by FranchiseFacts.to_dict, so the writer is never
    handed an empty stage to reach for."""
    facts = build_franchise_facts(
        user_id="u1", owner_name="Tom", team_name=None,
        outlook=_stale_blob(), roster_rank=None,
        signature_trade=None, window="",
    )
    assert facts.window == ""
    assert "window" not in facts.to_dict()
