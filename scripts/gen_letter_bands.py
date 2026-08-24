"""Regenerate web/.generated/letter-bands.json from the engine's LETTER_BANDS.

The methodology page (web/components/methodology/MethodologyContent.tsx) has
to render the letter-grade band table without importing Python into a
Next.js bundle, so it needs its own copy of the data. Hand-copying that copy
into TypeScript is exactly how it went stale for the v2 rating rebuild (see
docs/superpowers/sdd/2026-08-16-franchise-rating-v2/task-15-report.md).
Regenerate this file whenever gm_rating.LETTER_BANDS changes and commit the
result -- tests/test_letter_bands_export.py fails the build if the checked-in
copy and the live engine disagree.

    python3 scripts/gen_letter_bands.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sleeper_dynasty.engine.gm_rating import LETTER_BANDS  # noqa: E402

OUT = ROOT / "web" / ".generated" / "letter-bands.json"


def bands_as_json() -> list[dict]:
    # LETTER_BANDS is (delta, letter) high to low; the UI wants {letter, delta}
    # in the same order, so it can render the table by index with no reshaping.
    return [{"letter": letter, "delta": delta} for delta, letter in LETTER_BANDS]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bands_as_json(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
