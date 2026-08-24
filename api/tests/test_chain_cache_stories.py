import json
from pathlib import Path

from app.services.chain_cache import ChainCache, SCHEMA_VERSION

from tests.helpers import minimal_chain_cache_entry as _entry


def test_new_fields_default_empty_and_round_trip(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    e = _entry(trade_stories={"t1": {"verdict": "v", "body": "b",
                                     "facts_hash": "h", "generated_at": "now"}})
    c.write("L", e)
    back = c.read("L")
    assert back.trade_stories["t1"]["verdict"] == "v"
    assert back.owner_dossiers == {}


def test_pre_migration_file_without_story_fields_loads(tmp_path: Path):
    # A cache file written before these fields existed (has 'owners', no stories).
    raw = dict(
        league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="now",
        warnings=[],
        schema_version=SCHEMA_VERSION,
    )
    (tmp_path / "chain_L.json").write_text(json.dumps(raw))
    back = ChainCache(cache_dir=tmp_path).read("L")
    assert back is not None and back.trade_stories == {}
