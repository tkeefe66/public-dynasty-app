from sleeper_dynasty.engine.gm_rating_blurb import SIGNAL_LABELS, build_owner_rating_facts
from sleeper_dynasty.llm.gm_rating_blurb_writer import _PILLAR_KEYS
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash


def _facts(**over):
    base = dict(
        user_id="u1", owner_name="Bob", team_name="Sticky Icky",
        scope_label="career", rank=2, rating=1741,
        pillars=[
            {"label": "Outcomes", "weight": 0.45, "contribution": 148,
             "top_signals": [{"label": "Championships", "contribution": 55}],
             "worst_signals": []},
        ],
        championships=1, made_playoffs_rate=0.6, draft_capital_counted=False,
    )
    base.update(over)
    return OwnerRatingFacts(**base)


def test_to_dict_rounds_and_includes_scope():
    d = _facts().to_dict()
    assert d["scope_label"] == "career"
    assert d["rating"] == 1741
    assert d["pillars"][0]["label"] == "Outcomes"
    assert d["draft_capital_counted"] is False


def test_hash_is_stable_and_changes_on_rating():
    a = rating_facts_hash(_facts())
    b = rating_facts_hash(_facts())
    # rating band is 150: a small tick (1741 -> 1800) is sub-band and reuses;
    # a significant move (1741 -> 1950) crosses a bucket and regenerates.
    same = rating_facts_hash(_facts(rating=1800))
    c = rating_facts_hash(_facts(rating=1950))
    assert a == b == same and a != c
    assert len(a) == 16


def _pillars():
    # v2 keys: results / assets (replaces the retired results / skill / outlook)
    return {
        "results": {"weight": 0.60, "z": 0.5, "contribution": 148, "signals": {
            "expected_wins": {"raw": 1.0, "z": 1.2, "weight": 0.55, "contribution": 55},
            "playoff_success": {"raw": 3.0, "z": 0.9, "weight": 0.30, "contribution": 52},
            "luck": {"raw": 0.6, "z": 0.0, "weight": 0.15, "contribution": 0},
        }},
        "assets": {"weight": 0.40, "z": -0.1, "contribution": -8, "signals": {
            "roster_value_share": {"raw": 50000.0, "z": 0.2, "weight": 0.45, "contribution": 13},
            "draft_capital": {"raw": 0.0, "z": 0.0, "weight": 0.20, "contribution": 0},
            "young_core_share": {"raw": -27.0, "z": -0.8, "weight": 0.35, "contribution": -22},
        }},
    }


def test_build_facts_selects_top_and_worst_signals():
    f = build_owner_rating_facts(
        scope_label="career", owner_name="Bob", team_name="Icky",
        rank=2, rating=1741, pillars=_pillars(),
    )
    # Results pillar must appear with its signals
    out = next(p for p in f.pillars if p["label"] == "Results")
    # top signals are highest positive contributions, human-labeled, max 3
    assert out["top_signals"][0]["label"] == "Expected Wins"
    assert out["top_signals"][0]["contribution"] == 55
    assert len(out["top_signals"]) <= 3
    # Assets pillar (replaces the retired Skill/Outlook) must appear
    assets = next(p for p in f.pillars if p["label"] == "Assets")
    assert any(s["label"] == "Roster Value" for s in assets["top_signals"])
    # assets worst signal is the negative Young Core
    assert assets["worst_signals"][0]["label"] == "Young Core"
    assert assets["worst_signals"][0]["contribution"] == -22


def test_pillar_keys_are_the_v2_pair():
    assert _PILLAR_KEYS == {"Results", "Assets"}


def test_every_v2_signal_has_a_label():
    for sig in ("expected_wins", "playoff_success", "luck",
                "roster_value_share", "young_core_share", "draft_capital"):
        assert sig in SIGNAL_LABELS
        assert SIGNAL_LABELS[sig] != sig


def test_build_facts_season_scope_label():
    f = build_owner_rating_facts(
        scope_label="the 2025 season", owner_name="Bob", team_name=None,
        rank=1, rating=1900, pillars=_pillars(),
    )
    assert f.scope_label == "the 2025 season"


def test_championships_read_from_outcome_signals_not_pillar_breakdown():
    # Regression: championships/made_playoffs were dropped from the v2
    # Results signal set (expected_wins/playoff_success/luck only) but kept
    # in outcome_signals for exactly this. A three-time champion must not
    # read as zero just because the scoring tree stopped carrying the count.
    f = build_owner_rating_facts(
        scope_label="career", owner_name="Bob", team_name="Icky",
        rank=1, rating=1900, pillars=_pillars(),
        outcome_signals={"championships": 3.0, "made_playoffs": 0.6},
    )
    assert f.championships == 3


def test_made_playoffs_rate_read_from_outcome_signals_not_pillar_breakdown():
    f = build_owner_rating_facts(
        scope_label="career", owner_name="Bob", team_name="Icky",
        rank=1, rating=1900, pillars=_pillars(),
        outcome_signals={"championships": 3.0, "made_playoffs": 0.75},
    )
    assert f.made_playoffs_rate == 0.75


def test_owner_absent_from_outcome_signals_yields_zeros_not_a_raise():
    f = build_owner_rating_facts(
        scope_label="career", owner_name="Bob", team_name="Icky",
        rank=1, rating=1900, pillars=_pillars(), outcome_signals=None,
    )
    assert f.championships == 0
    assert f.made_playoffs_rate == 0.0
