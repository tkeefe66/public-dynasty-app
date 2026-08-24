"""Regenerate the committed rookie component-stat history.

    pip install -e '.[dev]'
    PYTHONPATH=src python3 scripts/extract_rookie_stats.py

WHY COMPONENTS AND NOT POINTS. The verdict bars are percentiles of fantasy
points, and fantasy points depend on the league's own scoring — 6-point pass
TDs versus 4 moves a QB-heavy cohort's bar by ~30 points. A committed table of
POINTS would be correct for exactly one league. Committing the raw components
and scoring them per league at refresh is correct for all of them.

WHY THIS PATH. nflverse renamed the release: `player_stats/player_stats_2025.csv`
404s while `player_stats/player_stats_1999.csv` still returns 200, so the legacy
path serves history only and silently omits the most recent season. Verify with:

    curl -sL -o /dev/null -w '%{http_code}\\n' \\
      https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_2025.csv

WHY THIS FILE HAS AN END DATE. It carries classes up to whenever it was last
generated. Re-run to extend it. A maintenance task, not a runtime one.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from sleeper_dynasty.api.player_ids import IDS_URL, build_fantasypros_to_sleeper
from sleeper_dynasty.engine.rookie_board import ROOKIE_ECR_TYPE

STATS_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
             "stats_player/stats_player_week_%d.csv")
ECR_PARQUET = ("https://raw.githubusercontent.com/dynastyprocess/data/"
               "master/files/db_fpecr.parquet")
OUT = Path(__file__).resolve().parents[1] / "src/sleeper_dynasty/data/rookie_stats.json.gz"

# Every component this app's scoring settings can price. Anything absent from a
# league's settings simply scores 0 — but a component missing from THIS list can
# never be priced at all, so it is the real contract.
COMPONENTS = (
    "passing_yards", "passing_tds", "interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
)
# Classes whose rookie season has completed. Extend as seasons finish.
CLASSES = (2021, 2022, 2023, 2024, 2025)
# The window a class's May board falls in. 2020's board sat outside a narrower
# window and was silently skipped in an earlier pass; this is deliberately wide.
BOARD_FROM, BOARD_TO = "-04-20", "-05-31"


def _num(row, key):
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    import pyarrow.parquet as pq

    raw_ids = urllib.request.urlopen(IDS_URL).read().decode("utf-8", "replace")
    xw = build_fantasypros_to_sleeper(list(csv.DictReader(io.StringIO(raw_ids))))
    print(f"crosswalk: {len(xw)} fantasypros -> sleeper")

    with urllib.request.urlopen(ECR_PARQUET) as r:
        table = pq.read_table(io.BytesIO(r.read()),
                              columns=["ecr_type", "id", "ecr", "scrape_date"])
    cols = {c: table.column(c).to_pylist()
            for c in ("ecr_type", "id", "ecr", "scrape_date")}

    def norm(d):
        return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]

    # One board per class: the latest inside that class's May window.
    boards: dict[int, dict[str, float]] = {}
    picked: dict[int, str] = {}
    for i in range(table.num_rows):
        if cols["ecr_type"][i] != ROOKIE_ECR_TYPE or cols["ecr"][i] is None:
            continue
        day = norm(cols["scrape_date"][i])
        year = int(day[:4])
        if year not in CLASSES or not (f"{year}{BOARD_FROM}" <= day <= f"{year}{BOARD_TO}"):
            continue
        if picked.get(year, "") > day:
            continue
        if picked.get(year) != day:
            picked[year], boards[year] = day, {}
        sid = xw.get(str(cols["id"][i]))
        if sid:  # unmapped is dropped, never zero-ranked
            boards[year][sid] = round(float(cols["ecr"][i]), 2)
    for y in sorted(boards):
        print(f"  class {y}: board {picked[y]}, {len(boards[y])} ranked")

    # Component stats per (player, season), regular season only.
    per_season: dict[int, dict[str, dict]] = {}
    for season in range(min(CLASSES), max(CLASSES) + 1):
        txt = urllib.request.urlopen(STATS_URL % season).read().decode("utf-8", "replace")
        acc: dict[str, dict] = defaultdict(lambda: dict.fromkeys(COMPONENTS, 0.0))
        for row in csv.DictReader(io.StringIO(txt)):
            if (row.get("season_type") or "REG") != "REG":
                continue
            tot = acc[row["player_id"]]
            for c in COMPONENTS:
                tot[c] += _num(row, c)
        per_season[season] = acc
        print(f"  stats {season}: {len(acc)} players")

    gsis = {}
    for r in csv.DictReader(io.StringIO(raw_ids)):
        fp, g = (r.get("fantasypros_id") or "").strip(), (r.get("gsis_id") or "").strip()
        sl = xw.get(fp)
        if sl and g and g != "NA":
            gsis[sl] = g

    out: dict[str, dict] = {}
    for cls_year, board in boards.items():
        for sid, ecr in board.items():
            g = gsis.get(sid)
            if not g:
                continue
            seasons = []
            for n, season in enumerate(range(cls_year, max(CLASSES) + 1), start=1):
                stats = per_season.get(season, {}).get(g)
                if stats is None:
                    break
                seasons.append({"n": n, **{k: round(v, 2) for k, v in stats.items()}})
            if seasons:
                out[sid] = {"ecr": ecr, "class": cls_year, "seasons": seasons}

    if not out:
        print("refusing to write an empty history", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    blob = gzip.compress(json.dumps(out, separators=(",", ":"), sort_keys=True).encode(), 9)
    OUT.write_bytes(blob)
    print(f"wrote {OUT} — {len(out)} players, {OUT.stat().st_size/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
