from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import model_for


def _min_raw():
    # A pre-feature entry dict: every required (non-default) field, none of the new ones.
    return dict(
        league_id="L1",
        chain=[],
        resolved_trades=[],
        grades={},
        owners={},
        playoff_weeks_by_league={},
        roster_to_user_by_league={},
        league_name_by_id={},
        league_season_by_id={},
        cached_at="2026-01-01",
    )


def test_pre_feature_entry_scores_as_dynasty():
    assert model_for(ChainCacheEntry(**_min_raw())) == "v2_dynasty"


def test_redraft_entry_selects_the_redraft_tree():
    raw = _min_raw()
    raw["capabilities"] = {"format": "redraft", "future_picks": False,
                            "roster_continuity": False, "multiyear_history": False}
    entry = ChainCacheEntry(**raw)
    assert model_for(entry) == "v2_redraft"


def test_keeper_entry_selects_the_keeper_tree():
    raw = _min_raw()
    raw["capabilities"] = {"format": "keeper", "future_picks": True,
                            "roster_continuity": True, "multiyear_history": True}
    entry = ChainCacheEntry(**raw)
    assert model_for(entry) == "v2_keeper"


def test_keeper_signal_tree_drops_young_core_but_keeps_assets():
    """Two or three keepers is not a young roster, so young_core_share is
    dropped (renormalized over roster_value_share/draft_capital) — but the
    Assets pillar itself survives, unlike redraft where it's dropped outright."""
    from sleeper_dynasty.engine.gm_rating import V2_KEEPER_SIGNAL_WEIGHTS
    assets = V2_KEEPER_SIGNAL_WEIGHTS["assets"]
    assert "young_core_share" not in assets
    assert set(assets) == {"roster_value_share", "draft_capital"}


def test_an_unknown_format_falls_back_to_dynasty():
    """A format this build has never heard of must never demote a league."""
    raw = _min_raw()
    raw["capabilities"] = {"format": "bestball", "future_picks": True,
                            "roster_continuity": True, "multiyear_history": True}
    assert model_for(ChainCacheEntry(**raw)) == "v2_dynasty"


def test_signal_and_pillar_trees_agree_on_pillars():
    """compute_gm_ratings indexes signal_weights[pillar]; a mismatch KeyErrors."""
    from sleeper_dynasty.engine.gm_rating import (
        V2_KEEPER_SIGNAL_WEIGHTS, V2_PILLAR_WEIGHTS, V2_REDRAFT_SIGNAL_WEIGHTS,
        V2_SIGNAL_WEIGHTS,
    )
    signals_by_model = {
        "v2_dynasty": V2_SIGNAL_WEIGHTS,
        "v2_keeper": V2_KEEPER_SIGNAL_WEIGHTS,
        "v2_redraft": V2_REDRAFT_SIGNAL_WEIGHTS,
    }
    for model in ("v2_dynasty", "v2_keeper", "v2_redraft"):
        assert set(V2_PILLAR_WEIGHTS[model]) <= set(signals_by_model[model])
