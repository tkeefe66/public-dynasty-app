from pathlib import Path

from app.services.chain_cache import ChainCache

from tests.helpers import minimal_chain_cache_entry as _entry


def test_owner_rating_blurbs_round_trip(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    e = _entry(owner_rating_blurbs={
        "all": {"u1": {"blurb": "Bob rules.", "facts_hash": "h", "generated_at": "now"}},
    })
    c.write("L", e)
    back = c.read("L")
    assert back.owner_rating_blurbs["all"]["u1"]["blurb"] == "Bob rules."


def test_owner_rating_blurbs_defaults_empty(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    c.write("L", _entry())
    assert c.read("L").owner_rating_blurbs == {}
