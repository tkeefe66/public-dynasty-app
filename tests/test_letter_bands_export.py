"""Guards web/.generated/letter-bands.json against drifting from the engine.

The methodology page renders its letter-band table from this checked-in JSON
(scripts/gen_letter_bands.py) instead of a hand-copied TypeScript array --
hand-copying it is exactly how the page went stale for the v2 rating rebuild.
This test is the engine-side half of that guard: it fails whenever
gm_rating.LETTER_BANDS changes and nobody reran the generator and committed
the result. The other half, web/tests/methodology-bands.test.ts, checks the
page's exported constant against this same JSON file -- together the two
tests mean the page can never disagree with the engine.
"""

import json
from pathlib import Path

from sleeper_dynasty.engine.gm_rating import LETTER_BANDS

BANDS_JSON = Path(__file__).resolve().parent.parent / "web" / ".generated" / "letter-bands.json"


def test_generated_json_matches_the_live_engine_bands():
    checked_in = json.loads(BANDS_JSON.read_text())
    expected = [{"letter": letter, "delta": delta} for delta, letter in LETTER_BANDS]
    assert checked_in == expected, (
        "web/.generated/letter-bands.json is stale against "
        "gm_rating.LETTER_BANDS -- run `python3 scripts/gen_letter_bands.py` "
        "and commit the result"
    )
