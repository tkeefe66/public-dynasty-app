# tests/test_chain_cache_became.py
import json
from pathlib import Path
from app.services.chain_cache import ChainCache, SCHEMA_VERSION

from tests.helpers import minimal_chain_cache_entry as _entry


def test_became_grades_round_trips_and_defaults(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    grade = {"t1": {"u_a": {"ktc": 5000.0, "production": 10.0, "started": 10.0,
                            "playoff": 0.0, "terminal_labels": ["Player B"],
                            "terminal_hash": "abc123"}}}
    c.write("L", _entry(became_grades=grade))
    assert c.read("L").became_grades == grade


def test_pre_migration_file_loads_with_empty_became(tmp_path: Path):
    raw = dict(league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
               playoff_weeks_by_league={}, roster_to_user_by_league={},
               league_name_by_id={}, league_season_by_id={}, cached_at="now", warnings=[],
               schema_version=SCHEMA_VERSION)
    (tmp_path / "chain_L.json").write_text(json.dumps(raw))
    assert ChainCache(cache_dir=tmp_path).read("L").became_grades == {}
