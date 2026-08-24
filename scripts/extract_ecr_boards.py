"""Regenerate a committed FantasyPros ECR board history.

Generalised from `extract_rookie_boards.py` (kept as-is, still the entry
point for the rookie file): `ecr_type` and the output path are arguments
here, so the same extraction logic also serves the whole-pool dynasty
consensi (`do` dynasty-overall, `dsf` dynasty-superflex) off the same shared
feed.

Run this to refresh a committed board file, e.g.:

    pip install -e '.[dev]'
    python scripts/extract_ecr_boards.py drk rookie_ecr.json.gz
    python scripts/extract_ecr_boards.py do dynasty_ecr.json.gz
    python scripts/extract_ecr_boards.py dsf dynasty_sf_ecr.json.gz

WHY THIS FILE HAS AN END DATE. Every board it writes carries history up to
whenever it was last generated. A fresh install deployed long after that has
a gap between the file's last date and its own first weekly capture (see
`api/app/services/rookie_board_store.py::capture_daily`). Re-running this
script for each board type closes the gap. This is a maintenance task, not a
runtime one — nothing at request time re-fetches the parquet.

WHY THE PARQUET AND NOT THE .csv.gz. `files/db_fpecr.csv.gz` is
104,685,532 bytes — over GitHub's 100MB per-file cap — so the automated
weekly scrape can no longer commit it. It is FROZEN at 2025-08-08 and still
gunzips cleanly into ~25,819 well-formed rows, so nothing about reading it
signals the problem: it would silently cost the entire current class and
look fine. `db_fpecr.parquet` is 37MB and still committed weekly. Verify
with:

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

ECR_PARQUET = ("https://raw.githubusercontent.com/dynastyprocess/data/"
               "master/files/db_fpecr.parquet")
DATA_DIR = Path(__file__).resolve().parents[1] / "src/sleeper_dynasty/data"


def _crosswalk() -> dict[str, str]:
    raw = urllib.request.urlopen(IDS_URL).read().decode("utf-8", "replace")
    return build_fantasypros_to_sleeper(list(csv.DictReader(io.StringIO(raw))))


def _norm(day) -> str:
    return day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]


def extract(ecr_type: str, out_path: Path) -> int:
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
        if cols["ecr_type"][i] != ecr_type:
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
        print(f"refusing to write an empty history for ecr_type={ecr_type!r}",
              file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(boards, separators=(",", ":"), sort_keys=True)
    out_path.write_bytes(gzip.compress(payload.encode(), 9))
    days = sorted(boards)
    print(f"wrote {out_path} — {len(boards)} boards, "
          f"{sum(len(b) for b in boards.values())} entries, "
          f"{days[0]} -> {days[-1]}, {out_path.stat().st_size / 1024:.0f} KB "
          f"({unmapped} unmapped entries dropped)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0] if argv else sys.argv[0]).name} "
              "<ecr_type> <output_filename>", file=sys.stderr)
        print("  e.g.: drk rookie_ecr.json.gz | do dynasty_ecr.json.gz | "
              "dsf dynasty_sf_ecr.json.gz", file=sys.stderr)
        return 2
    ecr_type, filename = argv
    return extract(ecr_type, DATA_DIR / filename)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
