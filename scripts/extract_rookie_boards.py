"""Regenerate the committed dynasty rookie ECR history.

Run this to refresh `src/sleeper_dynasty/data/rookie_ecr.json.gz`:

    pip install -e '.[dev]'
    python scripts/extract_rookie_boards.py

WHY THIS FILE HAS AN END DATE. It carries boards up to whenever it was last
generated. A fresh install deployed long after that has a gap between the
file's last date and its own first weekly capture. Re-running this script
closes the gap. This is a maintenance task, not a runtime one.

WHY THE PARQUET AND NOT THE .csv.gz. `files/db_fpecr.csv.gz` is
104,685,532 bytes — over GitHub's 100MB per-file cap — so the automated
weekly scrape can no longer commit it. It is FROZEN at 2025-08-08 and still
gunzips cleanly into ~25,819 well-formed rows, so nothing about reading it
signals the problem. `db_fpecr.parquet` is 37MB and still committed weekly.
Verify with:

    curl -s "https://api.github.com/repos/dynastyprocess/data/commits?path=files/db_fpecr.parquet&per_page=1"
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

from sleeper_dynasty.api.player_ids import IDS_URL, build_fantasypros_to_sleeper
from sleeper_dynasty.engine.rookie_board import ROOKIE_ECR_TYPE

ECR_PARQUET = ("https://raw.githubusercontent.com/dynastyprocess/data/"
               "master/files/db_fpecr.parquet")
OUT = Path(__file__).resolve().parents[1] / "src/sleeper_dynasty/data/rookie_ecr.json.gz"


def _crosswalk() -> dict[str, str]:
    raw = urllib.request.urlopen(IDS_URL).read().decode("utf-8", "replace")
    return build_fantasypros_to_sleeper(list(csv.DictReader(io.StringIO(raw))))


def _norm(day) -> str:
    return day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]


def main() -> int:
    xw = _crosswalk()
    print(f"crosswalk: {len(xw)} fantasypros ids -> sleeper ids")

    with urllib.request.urlopen(ECR_PARQUET) as resp:
        blob = resp.read()
    print(f"parquet: {len(blob) / 1e6:.1f} MB")
    table = pq.read_table(io.BytesIO(blob),
                          columns=["ecr_type", "id", "ecr", "scrape_date"])
    cols = {c: table.column(c).to_pylist()
            for c in ("ecr_type", "id", "ecr", "scrape_date")}

    boards: dict[str, dict[str, float]] = {}
    unmapped = 0
    for i in range(table.num_rows):
        if cols["ecr_type"][i] != ROOKIE_ECR_TYPE:
            continue
        ecr = cols["ecr"][i]
        if ecr is None:
            continue
        sleeper_id = xw.get(str(cols["id"][i]))
        if not sleeper_id:
            unmapped += 1  # dropped, never zero-ranked
            continue
        boards.setdefault(_norm(cols["scrape_date"][i]), {})[sleeper_id] = round(
            float(ecr), 2)

    if not boards:
        print("refusing to write an empty history", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(boards, separators=(",", ":"), sort_keys=True)
    OUT.write_bytes(gzip.compress(payload.encode(), 9))
    days = sorted(boards)
    print(f"wrote {OUT} — {len(boards)} boards, "
          f"{sum(len(b) for b in boards.values())} entries, "
          f"{days[0]} -> {days[-1]}, {OUT.stat().st_size / 1024:.0f} KB "
          f"({unmapped} unmapped entries dropped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
