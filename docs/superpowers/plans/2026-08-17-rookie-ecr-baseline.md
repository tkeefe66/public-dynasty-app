# Rookie ECR Baseline Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give dynasty rookie drafts a real external baseline — FantasyPros dynasty rookie consensus (ECR) dated on-or-before each draft — replacing two columns that are structurally blank on every dynasty season.

**Architecture:** A committed 74KB file carries immutable historical boards; a store captures new boards weekly from a 1MB CSV and merges both into one timeline; a pure engine module resolves the board dated on-or-before a draft and computes the delta. The grader forks on `DraftClass.axis`: `"production"` classes keep Sleeper ADP, dynasty rookie classes get ECR. Both write to new `baseline*` fields, leaving `adp`/`adp_delta` untouched.

**Tech Stack:** Python 3.11, httpx, pytest, FastAPI/Pydantic, Next.js 14 + TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md`

## Global Constraints

- **Branch:** all work on `new-draft-board`. Never commit to `main`.
- **No `SCHEMA_VERSION` bump.** New persisted fields are additive with `default_factory` plus a read-time fallback (`league_phase` precedent).
- **The rookie ECR baseline must never feed Franchise Rating.** `engine/draft_signals.py::draft_skill` stays the only baseline that does. This is what keeps the change no-bump.
- **`adp` and `adp_delta` keep their exact current meaning.** Redefining them is a shape change and would force a bump.
- **Never render "KTC" in UI.** It is "Trade Value" / "Value".
- **Data source of record is `db_fpecr.parquet`, never `db_fpecr.csv.gz`.** The `.csv.gz` is 104,685,532 bytes, over GitHub's 100MB cap, frozen at 2025-08-08, and still gunzips cleanly — using it silently costs the entire 2026 class.
- **R's literal `"NA"` must be filtered** from every DynastyProcess CSV id column, or it becomes a catch-all key.
- **An unmapped player is dropped, never zero-ranked.**
- **Resolution is on-or-before, never after.** A board published after a draft is hindsight.
- **Test commands:** engine/CLI `pytest tests/` from repo root (bare `pytest` breaks — `api/tests` and `tests/` are both packages named `tests`). Backend `cd api && pytest -v`. Frontend `cd web && npx vitest --config tests/vitest.config.ts run` (bare `npx vitest run` silently uses NO config and fails on JSX).

---

### Task 1: Shared DynastyProcess id crosswalk

`api/yahoo_ids.py` already fetches and parses `db_playerids.csv` for `yahoo_id → sleeper_id`. We need `fantasypros_id → sleeper_id` from the same 2.6MB file. Lift the shared parts into one module rather than fetching it twice.

**Files:**
- Create: `src/sleeper_dynasty/api/player_ids.py`
- Modify: `src/sleeper_dynasty/api/yahoo_ids.py`
- Test: `tests/test_player_ids.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `player_ids.IDS_URL: str`
  - `player_ids.clean_id(raw) -> str`
  - `player_ids.build_id_map(rows: list[dict], *, source_col: str) -> dict[str, str]`
  - `player_ids.build_fantasypros_to_sleeper(rows: list[dict]) -> dict[str, str]`
  - `async player_ids.fetch_fantasypros_to_sleeper(cache=None) -> dict[str, str]`
  - `yahoo_ids.build_yahoo_to_sleeper` keeps its existing signature and behaviour.

- [ ] **Step 1: Write the failing test**

Create `tests/test_player_ids.py`:

```python
from sleeper_dynasty.api.player_ids import (
    build_fantasypros_to_sleeper, build_id_map, clean_id,
)


def test_clean_id_strips_pandas_float_suffix():
    assert clean_id("31002.0") == "31002"


def test_clean_id_rejects_r_null_tokens():
    # R writes its null as the literal "NA"; unfiltered it becomes a catch-all
    # key that swallows every unmapped player into one wrong person.
    for token in ("NA", "na", "N/A", "", "  ", "nan", "None", "null"):
        assert clean_id(token) == ""


def test_build_id_map_skips_rows_missing_either_side():
    rows = [
        {"fantasypros_id": "1234", "sleeper_id": "4046"},
        {"fantasypros_id": "NA", "sleeper_id": "9999"},
        {"fantasypros_id": "5678", "sleeper_id": "NA"},
        {"fantasypros_id": "", "sleeper_id": ""},
    ]
    assert build_id_map(rows, source_col="fantasypros_id") == {"1234": "4046"}


def test_build_id_map_first_row_wins_on_duplicate():
    rows = [
        {"fantasypros_id": "1234", "sleeper_id": "aaa"},
        {"fantasypros_id": "1234", "sleeper_id": "bbb"},
    ]
    assert build_id_map(rows, source_col="fantasypros_id") == {"1234": "aaa"}


def test_build_fantasypros_to_sleeper_reads_the_right_column():
    rows = [{"fantasypros_id": "1234", "yahoo_id": "777", "sleeper_id": "4046"}]
    assert build_fantasypros_to_sleeper(rows) == {"1234": "4046"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_player_ids.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.api.player_ids'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/api/player_ids.py`:

```python
"""DynastyProcess ``db_playerids.csv`` -> Sleeper player ids.

Sleeper's ``player_id`` is this app's canonical key. Every external source
translates at its own boundary and nothing inward ever sees a foreign id.

This module owns the fetch and the parse; ``yahoo_ids`` and the rookie-ECR
baseline are two accessors over the same 2.6MB file, so it is pulled once.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Same source engine/injury_data.py uses. Kept as its own constant so a change
# to one consumer's URL cannot silently repoint the other.
IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"

_CACHE_TTL = 7 * 24 * 3600  # ids change only when players enter the league
_FP_CACHE_KEY = "fantasypros_to_sleeper_ids.json"

# R writes its null as the literal string "NA" when this CSV is generated, and
# pandas hands it back as text rather than a missing value. Observed live: one
# row maps yahoo_id "NA" -> a real sleeper_id, which would then swallow every
# unmapped player into one wrong person.
NULL_TOKENS = {"", "na", "n/a", "nan", "none", "null"}


def clean_id(raw) -> str:
    """Normalize a CSV id cell to a bare string, or "" if it is not an id.

    Two upstream quirks, both observed in the live file:
    * numeric columns round-trip through pandas, so an id can arrive as
      "31002.0" — left alone that never matches a player key;
    * nulls arrive as the literal text "NA" rather than an empty cell.
    """
    s = str(raw or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return "" if s.lower() in NULL_TOKENS else s


def build_id_map(rows: list[dict], *, source_col: str) -> dict[str, str]:
    """Pure: CSV rows -> {source id: sleeper_id}.

    Rows missing either id are skipped — a partial mapping is worse than no
    mapping, because it silently drops players. First row wins on a duplicate
    so two runs over the same CSV can never disagree.
    """
    out: dict[str, str] = {}
    for row in rows:
        src = clean_id(row.get(source_col))
        sid = clean_id(row.get("sleeper_id"))
        if not src or not sid:
            continue
        out.setdefault(src, sid)
    return out


def build_fantasypros_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """Pure: CSV rows -> {fantasypros_id: sleeper_id}."""
    return build_id_map(rows, source_col="fantasypros_id")


async def fetch_fantasypros_to_sleeper(cache=None) -> dict[str, str]:
    """Fetch (or read cached) the fantasypros_id -> sleeper_id map.

    Returns {} on any failure. Callers decide what an empty map means; raising
    here would take down an otherwise healthy refresh at the fetch layer.
    """
    if cache is not None:
        cached = cache.read(_FP_CACHE_KEY, max_age_seconds=_CACHE_TTL)
        if cached:
            return cached
    try:
        from sleeper_dynasty.engine.injury_data import _fetch_csv_rows
        rows = _fetch_csv_rows(IDS_URL)
    except Exception:
        log.warning("player id map fetch failed", exc_info=True)
        return {}
    mapping = build_fantasypros_to_sleeper(rows)
    log.info(
        "player id map: %d fantasypros ids resolved to sleeper ids", len(mapping))
    if cache is not None and mapping:
        cache.write(_FP_CACHE_KEY, mapping)
    return mapping
```

- [ ] **Step 4: Point `yahoo_ids` at the shared parts**

In `src/sleeper_dynasty/api/yahoo_ids.py`, replace the `IDS_URL` constant, the `_NULL_TOKENS` set, the `_clean_id` function and the body of `build_yahoo_to_sleeper` with delegations. Keep the module docstring and `fetch_yahoo_to_sleeper` as they are.

Replace lines 19-62 with:

```python
from sleeper_dynasty.api.player_ids import IDS_URL, build_id_map  # noqa: F401

_CACHE_KEY = "yahoo_to_sleeper_ids.json"
_CACHE_TTL = 7 * 24 * 3600  # ids change only when players enter the league


def build_yahoo_to_sleeper(rows: list[dict]) -> dict[str, str]:
    """Pure: CSV rows -> {yahoo_id: sleeper_id}. See player_ids.build_id_map."""
    return build_id_map(rows, source_col="yahoo_id")
```

- [ ] **Step 5: Run both test suites to verify they pass**

Run: `pytest tests/test_player_ids.py tests/test_yahoo_ids.py -v`
Expected: PASS. `tests/test_yahoo_ids.py` exists and must pass **unchanged** — if any of its tests fail, the delegation changed behaviour, and the delegation is what gets fixed, never the test.

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/api/player_ids.py src/sleeper_dynasty/api/yahoo_ids.py tests/test_player_ids.py
git commit -m "refactor: share the DynastyProcess id crosswalk between consumers"
```

---

### Task 2: Pure rookie-board resolution

**Files:**
- Create: `src/sleeper_dynasty/engine/rookie_board.py`
- Test: `tests/test_rookie_board.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_boards(raw: dict) -> dict[str, dict[str, float]]` — `{"YYYY-MM-DD": {sleeper_id: ecr}}`
  - `resolve_board(boards: dict[str, dict[str, float]], drafted_on: date) -> tuple[str, dict[str, float]] | None`
  - `board_delta(*, pick_no: int, ecr: float | None) -> float | None`

This module is **pure — no I/O**. The packaged file is read by the store in Task 4.

- [ ] **Step 1: Write the failing test**

Create `tests/test_rookie_board.py`:

```python
from datetime import date

import pytest

from sleeper_dynasty.engine.rookie_board import (
    board_delta, parse_boards, resolve_board,
)

BOARDS = {
    "2025-05-09": {"111": 1.0, "222": 2.5},
    "2025-05-16": {"111": 1.0, "222": 2.9, "333": 7.6},
    "2025-05-23": {"111": 1.0, "222": 4.0},
}


def test_parse_boards_coerces_ids_to_str_and_ecr_to_float():
    raw = {"2025-05-16": {111: "1.05", "222": 2}}
    assert parse_boards(raw) == {"2025-05-16": {"111": 1.05, "222": 2.0}}


def test_parse_boards_drops_unusable_entries():
    raw = {"2025-05-16": {"111": None, "222": "not-a-number", "333": 3.0}}
    assert parse_boards(raw) == {"2025-05-16": {"333": 3.0}}


def test_parse_boards_drops_a_date_with_nothing_usable():
    # An empty board is indistinguishable from a failed fetch downstream.
    raw = {"2025-05-16": {"111": None}, "2025-05-23": {"222": 1.0}}
    assert parse_boards(raw) == {"2025-05-23": {"222": 1.0}}


def test_resolve_board_prefers_the_drafts_own_day():
    day, board = resolve_board(BOARDS, date(2025, 5, 16))
    assert day == "2025-05-16"
    assert board["333"] == 7.6


def test_resolve_board_falls_back_to_the_nearest_earlier_day():
    day, _ = resolve_board(BOARDS, date(2025, 5, 15))
    assert day == "2025-05-09"


def test_resolve_board_never_returns_a_later_board():
    # Grading against a board published after the draft is hindsight, which is
    # the entire failure this resolver exists to prevent.
    assert resolve_board(BOARDS, date(2025, 5, 1)) is None


def test_resolve_board_returns_none_when_empty():
    assert resolve_board({}, date(2025, 5, 16)) is None


def test_board_delta_positive_means_taken_later_than_consensus():
    assert board_delta(pick_no=10, ecr=4.0) == 6.0


def test_board_delta_negative_means_a_reach():
    assert board_delta(pick_no=2, ecr=9.0) == -7.0


def test_board_delta_is_none_for_an_unranked_player():
    # Ungraded on this baseline is not the same as scoring zero.
    assert board_delta(pick_no=10, ecr=None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rookie_board.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.rookie_board'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/rookie_board.py`:

```python
"""Dynasty rookie consensus boards, resolved to each draft's own date.

Sleeper publishes no usable rookie ADP: ``adp_rookie`` is unpopulated, and the
overall-NFL ADP that IS published would grade a 1.01 rookie against ~30th
overall and print a 29-pick reach. That is why ``grader.py`` skipped the ADP
block for dynasty entirely, leaving two permanently blank columns.

FantasyPros publishes a dynasty ROOKIE consensus ranking, mirrored by
DynastyProcess with a ``scrape_date``, weekly, back to 2020. Unlike KTC and
FantasyCalc it has dated history, so it grades past classes as well as future
ones.

Resolution picks the board dated on the draft's own day, else the nearest
EARLIER day, never later — a draft is graded against the market as it stood
going in.

Pure. No I/O — callers thread in the parsed boards.
"""

from __future__ import annotations

from datetime import date


def _numeric(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_boards(raw: dict) -> dict[str, dict[str, float]]:
    """``{date: {player_id: ecr}}``, non-numeric entries dropped.

    A date whose entries are all unusable is dropped rather than stored empty:
    an empty board is indistinguishable from a failed fetch downstream, and the
    store refuses empties for exactly that reason.
    """
    out: dict[str, dict[str, float]] = {}
    for day, entries in (raw or {}).items():
        if not isinstance(entries, dict):
            continue
        board: dict[str, float] = {}
        for pid, ecr in entries.items():
            val = _numeric(ecr)
            if val is None:
                continue
            board[str(pid)] = val
        if board:
            out[str(day)] = board
    return out


def resolve_board(
    boards: dict[str, dict[str, float]], drafted_on: date,
) -> tuple[str, dict[str, float]] | None:
    """The board dated on-or-before ``drafted_on``, newest first.

    Returns ``(date_string, board)``, or None when no board predates the draft:
    that class is older than our history and has no baseline, permanently.
    Handing back a later board would be exactly the hindsight grading this
    resolver exists to prevent.
    """
    target = drafted_on.isoformat()
    candidates = sorted((d for d in boards if d <= target), reverse=True)
    for day in candidates:
        board = boards.get(day)
        if board:
            return day, board
    return None


def board_delta(*, pick_no: int, ecr: float | None) -> float | None:
    """How far past his consensus rank a player was taken.

    Positive = still there later than the market ranked him (value).
    Negative = a reach. None when the player is unranked — the pick is
    ungraded on this baseline, which is not the same as scoring zero.
    """
    if ecr is None:
        return None
    return float(pick_no) - float(ecr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rookie_board.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/rookie_board.py tests/test_rookie_board.py
git commit -m "feat(engine): rookie consensus board resolution, on-or-before only"
```

---

### Task 3: Committed board history + extract script

**Files:**
- Create: `scripts/extract_rookie_boards.py`
- Create: `src/sleeper_dynasty/data/__init__.py`
- Create: `src/sleeper_dynasty/data/rookie_ecr.json.gz` (generated by the script)
- Modify: `pyproject.toml:33-34` (`[tool.setuptools.package-data]`, `[project.optional-dependencies]`)
- Test: `tests/test_rookie_ecr_data.py`

**Interfaces:**
- Consumes: `player_ids.build_fantasypros_to_sleeper` (Task 1).
- Produces: the packaged resource `sleeper_dynasty.data/rookie_ecr.json.gz`, a gzipped JSON object of `{"YYYY-MM-DD": {sleeper_id: ecr}}`, readable by `parse_boards`.

- [ ] **Step 1: Add the packaging entries**

In `pyproject.toml`, extend the dev extra and the package-data glob:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pyarrow>=15.0"]
```

```toml
[tool.setuptools.package-data]
sleeper_dynasty = ["llm/prompts/*.md", "data/*.json.gz"]
```

`pyarrow` is a **dev-only** dependency: it is needed to regenerate the committed file and must never enter the runtime image. Reading the file at runtime needs only `gzip` and `json`.

- [ ] **Step 2: Write the extract script**

Create `scripts/extract_rookie_boards.py`:

```python
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

ECR_PARQUET = ("https://raw.githubusercontent.com/dynastyprocess/data/"
               "master/files/db_fpecr.parquet")
# FantasyPros' dynasty ROOKIE consensus. Not "do" (dynasty-overall) and not
# "dsf" (superflex) — those rank the whole player pool.
ROOKIE_ECR_TYPE = "drk"
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
```

- [ ] **Step 3: Generate the file**

```bash
pip install -e '.[dev]'
mkdir -p src/sleeper_dynasty/data && touch src/sleeper_dynasty/data/__init__.py
python scripts/extract_rookie_boards.py
```

Expected output: roughly `309 boards, 29082 entries, 2020-10-17 -> <recent>, ~74 KB`. If it prints 0 boards, the parquet schema changed — stop and investigate rather than committing an empty file.

- [ ] **Step 4: Write the test**

Create `tests/test_rookie_ecr_data.py`:

```python
"""The committed history is data, so the test asserts its SHAPE, not its values.

Values move every time the file is regenerated; shape must not.
"""
import gzip
import json
from datetime import date
from importlib.resources import files

from sleeper_dynasty.engine.rookie_board import parse_boards, resolve_board


def _load() -> dict:
    blob = files("sleeper_dynasty.data").joinpath("rookie_ecr.json.gz").read_bytes()
    return json.loads(gzip.decompress(blob))


def test_committed_history_is_readable_and_non_empty():
    boards = _load()
    assert len(boards) > 200, "history should carry several years of weekly boards"


def test_every_key_is_an_iso_date_and_every_board_is_non_empty():
    for day, board in _load().items():
        date.fromisoformat(day)  # raises if malformed
        assert board, f"{day} is an empty board"


def test_ids_are_strings_and_ecr_values_are_positive_numbers():
    for day, board in _load().items():
        for pid, ecr in board.items():
            assert isinstance(pid, str) and pid, f"bad id on {day}"
            assert isinstance(ecr, (int, float)) and ecr > 0, f"bad ecr on {day}"


def test_parse_boards_accepts_the_committed_file_unchanged():
    raw = _load()
    assert parse_boards(raw) == {k: {i: float(v) for i, v in b.items()}
                                 for k, b in raw.items()}


def test_history_resolves_a_board_for_a_recent_draft_date():
    resolved = resolve_board(parse_boards(_load()), date(2025, 5, 16))
    assert resolved is not None
    day, board = resolved
    assert day <= "2025-05-16"
    assert len(board) > 50
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_rookie_ecr_data.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add scripts/extract_rookie_boards.py src/sleeper_dynasty/data/ pyproject.toml tests/test_rookie_ecr_data.py
git commit -m "feat(data): commit dynasty rookie ECR history, 2020-present"
```

---

### Task 4: Rookie board store

Merges the committed history with weekly captures into one timeline, and pins each draft's board write-once.

**Files:**
- Create: `api/app/services/rookie_board_store.py`
- Test: `api/tests/test_rookie_board_store.py`

**Interfaces:**
- Consumes: `engine.rookie_board.parse_boards`, `resolve_board` (Task 2); the packaged file (Task 3).
- Produces:
  - `RookieBoardStore(cache_dir: Path)`
  - `.committed() -> dict[str, dict[str, float]]`
  - `.capture_daily(board: dict[str, float], today: date) -> bool`
  - `.all_boards() -> dict[str, dict[str, float]]`
  - `.resolve_for_draft(draft_id: str, drafted_on: date) -> dict[str, float] | None`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_rookie_board_store.py`:

```python
from datetime import date

import pytest

from app.services.rookie_board_store import RookieBoardStore


@pytest.fixture
def store(tmp_path):
    return RookieBoardStore(tmp_path)


def test_committed_history_loads_from_the_package(store):
    assert len(store.committed()) > 200


def test_capture_daily_writes_once(store):
    assert store.capture_daily({"111": 1.0}, date(2026, 9, 1)) is True
    assert store.capture_daily({"111": 9.9}, date(2026, 9, 1)) is False
    assert store.all_boards()["2026-09-01"] == {"111": 1.0}


def test_capture_daily_refuses_an_empty_board(store):
    # An empty result means the fetch failed; capture is write-once, so storing
    # it would poison the baseline forever.
    assert store.capture_daily({}, date(2026, 9, 1)) is False
    assert "2026-09-01" not in store.all_boards()


def test_resolve_for_draft_uses_a_captured_board_on_the_draft_day(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 1))
    assert store.resolve_for_draft("d1", date(2026, 9, 1)) == {"111": 3.0}


def test_resolve_for_draft_never_uses_a_later_board(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 10))
    # Nothing captured on-or-before, and the committed history ends well before
    # 2026-09; a later board must not be handed back.
    assert store.resolve_for_draft("d1", date(2026, 9, 1)) != {"111": 3.0}


def test_resolve_for_draft_is_pinned_write_once(store):
    store.capture_daily({"111": 3.0}, date(2026, 9, 1))
    first = store.resolve_for_draft("d1", date(2026, 9, 5))
    store.capture_daily({"111": 99.0}, date(2026, 9, 3))
    assert store.resolve_for_draft("d1", date(2026, 9, 5)) == first


def test_resolve_for_draft_returns_none_before_all_history(store):
    assert store.resolve_for_draft("d1", date(2015, 5, 1)) is None


def test_committed_history_serves_a_real_past_draft(store):
    board = store.resolve_for_draft("d-2025", date(2025, 5, 16))
    assert board is not None and len(board) > 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_rookie_board_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.rookie_board_store'`

- [ ] **Step 3: Write the implementation**

Create `api/app/services/rookie_board_store.py`:

```python
"""Dynasty rookie consensus boards: committed history plus weekly capture.

Two layers, merged into ONE timeline so there is no seam between backfilled
and live:

- The committed history (``sleeper_dynasty/data/rookie_ecr.json.gz``) carries
  every board up to the day it was generated. Historical boards are immutable,
  so they ship with the code rather than being fetched, and they survive a
  cache-volume wipe — which the snapshot stores do not.
- ``capture_daily`` records boards from ``db_fpecr_latest.csv`` (a 1MB plain
  CSV, scraped weekly) going forward. No parquet reader at runtime.

Each draft's board is resolved once — on-or-before its own day, never after —
and then frozen write-once per ``draft_id``, exactly as ``AdpSnapshotStore``
does. Keying by draft id rather than by date makes immutability structural.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import date
from importlib.resources import files
from pathlib import Path

from sleeper_dynasty.engine.rookie_board import parse_boards, resolve_board
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)

_SUBDIR = "rookie_ecr"
_DAILY_SUBDIR = "daily"
_PACKAGED = ("sleeper_dynasty.data", "rookie_ecr.json.gz")


class RookieBoardStore:
    def __init__(self, cache_dir: Path):
        self._dir = Path(cache_dir) / _SUBDIR
        self._committed: dict[str, dict[str, float]] | None = None

    # ---- committed history -------------------------------------------------

    def committed(self) -> dict[str, dict[str, float]]:
        """Every board that shipped with the code. Parsed once per instance."""
        if self._committed is None:
            try:
                blob = files(_PACKAGED[0]).joinpath(_PACKAGED[1]).read_bytes()
                self._committed = parse_boards(json.loads(gzip.decompress(blob)))
            except (OSError, ValueError, ModuleNotFoundError):
                log.exception("committed rookie ECR history unreadable")
                self._committed = {}
        return self._committed

    # ---- weekly capture ----------------------------------------------------

    def _daily_path(self, day: date) -> Path:
        return self._dir / _DAILY_SUBDIR / f"{day.isoformat()}.json"

    def capture_daily(self, board: dict[str, float], today: date) -> bool:
        """Write today's board if absent and non-empty. True if written.

        Refuses an empty board: an empty result means the fetch failed, and
        since resolution pins write-once, storing it would poison a baseline
        permanently.
        """
        if not board:
            log.warning("refusing empty rookie ECR capture for %s", today)
            return False
        path = self._daily_path(today)
        if path.exists():
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, {str(k): float(v) for k, v in board.items()})
        except OSError:
            log.exception("rookie ECR capture failed for %s", today)
            return False
        log.info("captured rookie ECR for %s (%d players)", today, len(board))
        return True

    def _captured(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for path in (self._dir / _DAILY_SUBDIR).glob("*.json"):
            try:
                date.fromisoformat(path.stem)
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue  # a corrupt day is stepped over, never guessed at
            if isinstance(data, dict) and data:
                out[path.stem] = {str(k): float(v) for k, v in data.items()}
        return out

    def all_boards(self) -> dict[str, dict[str, float]]:
        """Committed history and captured days as one timeline.

        A captured day wins over a committed one of the same date: capture is
        the fresher observation of a board that has since stopped being
        republished.
        """
        merged = dict(self.committed())
        merged.update(self._captured())
        return merged

    # ---- per-draft pin -----------------------------------------------------

    def _pin_path(self, draft_id: str) -> Path:
        return self._dir / f"{draft_id}.json"

    def _read_pin(self, draft_id: str) -> dict[str, float] | None:
        path = self._pin_path(draft_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            log.exception("rookie ECR pin unreadable for draft %s", draft_id)
            return None
        if not isinstance(data, dict) or not data:
            return None
        return {str(k): float(v) for k, v in data.items()}

    def resolve_for_draft(
        self, draft_id: str, drafted_on: date,
    ) -> dict[str, float] | None:
        """This draft's frozen board, resolving it from the timeline once.

        Returns None when no board predates the draft: that class is older than
        our history and has no baseline, permanently.
        """
        pinned = self._read_pin(draft_id)
        if pinned is not None:
            return pinned
        resolved = resolve_board(self.all_boards(), drafted_on)
        if resolved is None:
            return None
        _day, board = resolved
        path = self._pin_path(draft_id)
        if not path.exists():
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                write_json_atomic(path, board)
            except OSError:
                log.exception("rookie ECR pin write failed for %s", draft_id)
        return board
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && pytest tests/test_rookie_board_store.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/rookie_board_store.py api/tests/test_rookie_board_store.py
git commit -m "feat(api): rookie board store — committed history plus weekly capture"
```

---

### Task 5: Per-pick baseline fields

`build_drafted_pick_results` currently emits `adp` / `adp_delta` from Sleeper ADP only. Add the three baseline fields alongside, without touching the existing two.

**Files:**
- Modify: `src/sleeper_dynasty/engine/draft_results.py:101-186`
- Test: `tests/test_draft_results_baseline.py`

**Interfaces:**
- Consumes: `rookie_board.board_delta` (Task 2).
- Produces: `build_drafted_pick_results(..., rookie_ecr_by_draft: dict[str, dict[str, float]] | None = None)`, and three new keys on every row: `baseline: float | None`, `baseline_delta: float | None`, `baseline_source: str` (`"sleeper_adp"` | `"rookie_ecr"` | `""`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft_results_baseline.py`:

```python
from sleeper_dynasty.engine.draft_results import build_drafted_pick_results
from sleeper_dynasty.engine.draft_signals import DraftedPick


def _pick(**over) -> DraftedPick:
    base = dict(draft_id="d1", round=1, slot=4, picks_in_round=12,
                player_id="111", drafter_id="u1", draft_season=2025, pick_no=4,
                draft_kind="rookie", is_keeper=False, gradeable=True)
    base.update(over)
    return DraftedPick(**base)


def _build(picks, **kw):
    return build_drafted_pick_results(
        picks, ktc_floats={}, normalized_name_by_pid={}, names={},
        positions={}, extremes_by_name={}, acquired_set=set(),
        points_fn=lambda p, u, ph: 0.0, games_fn=lambda p, u: 0,
        current_holders={}, traded_away_set=set(), **kw)


def test_rookie_ecr_populates_baseline_and_names_its_source():
    rows = _build([_pick()], rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline"] == 1.5
    assert rows[0]["baseline_delta"] == 2.5     # pick 4 taken at consensus 1.5
    assert rows[0]["baseline_source"] == "rookie_ecr"


def test_sleeper_adp_fills_the_baseline_when_there_is_no_rookie_board():
    rows = _build([_pick()], adp_by_draft={"d1": {"111": 9.0}})
    assert rows[0]["baseline"] == 9.0
    assert rows[0]["baseline_delta"] == -5.0    # pick 4 on a 9.0 board = reach
    assert rows[0]["baseline_source"] == "sleeper_adp"


def test_rookie_ecr_wins_when_both_are_present():
    # A dynasty rookie class must never be graded against overall-NFL ADP.
    rows = _build([_pick()],
                  adp_by_draft={"d1": {"111": 9.0}},
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline_source"] == "rookie_ecr"
    assert rows[0]["baseline"] == 1.5


def test_adp_fields_keep_their_existing_meaning():
    # adp/adp_delta must stay Sleeper ADP. Repointing them is a shape change.
    rows = _build([_pick()],
                  adp_by_draft={"d1": {"111": 9.0}},
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["adp"] == 9.0
    assert rows[0]["adp_delta"] == -5.0


def test_unranked_pick_is_null_not_zero():
    rows = _build([_pick()], rookie_ecr_by_draft={"d1": {"999": 1.5}})
    assert rows[0]["baseline"] is None
    assert rows[0]["baseline_delta"] is None
    assert rows[0]["baseline_source"] == ""


def test_an_ungradeable_pick_gets_no_baseline():
    # An auction pick_no is the order money changed hands, so a slot delta
    # against it is noise.
    rows = _build([_pick(gradeable=False)],
                  rookie_ecr_by_draft={"d1": {"111": 1.5}})
    assert rows[0]["baseline"] is None
    assert rows[0]["baseline_source"] == ""


def test_baselines_are_keyed_per_draft_not_flattened():
    # A player drafted in two seasons must grade against each season's own
    # market, not whichever class was read last.
    picks = [_pick(), _pick(draft_id="d2", draft_season=2026, pick_no=20)]
    rows = _build(picks, rookie_ecr_by_draft={"d1": {"111": 1.5}, "d2": {"111": 30.0}})
    assert rows[0]["baseline"] == 1.5
    assert rows[1]["baseline"] == 30.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_draft_results_baseline.py -v`
Expected: FAIL with `TypeError: build_drafted_pick_results() got an unexpected keyword argument 'rookie_ecr_by_draft'`

- [ ] **Step 3: Write the implementation**

In `src/sleeper_dynasty/engine/draft_results.py`, add the import at the top alongside the existing `adp_delta` import:

```python
from sleeper_dynasty.engine.rookie_board import board_delta
```

Add the parameter to `build_drafted_pick_results`, after `projected_by_player`:

```python
    rookie_ecr_by_draft: dict[str, dict[str, float]] | None = None,
```

Inside the `for p in picks:` loop, directly after the existing `adp = (...)` assignment, add:

```python
        # The BASELINE is whichever external expectation this class actually
        # has. A dynasty rookie class has a rookie consensus board; a
        # redraft/keeper class has Sleeper ADP. Rookie ECR wins when both are
        # present — grading a rookie class against overall-NFL ADP would price
        # a 1.01 against ~30th overall and print a 29-pick reach.
        #
        # `adp`/`adp_delta` below keep their existing Sleeper-ADP meaning.
        # Repointing them would be a shape change on a persisted field.
        ecr = (
            (rookie_ecr_by_draft or {}).get(p.draft_id, {}).get(p.player_id)
            if p.gradeable else None
        )
        if ecr is not None:
            baseline, baseline_source = ecr, "rookie_ecr"
        elif adp is not None:
            baseline, baseline_source = adp, "sleeper_adp"
        else:
            baseline, baseline_source = None, ""
```

Add the three keys to the appended dict, immediately after `"adp_delta": adp_delta(...)`:

```python
            "baseline": baseline,
            "baseline_delta": board_delta(pick_no=p.pick_no, ecr=baseline),
            "baseline_source": baseline_source,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_draft_results_baseline.py tests/test_draft_results.py -v`
Expected: PASS. The existing `test_draft_results.py` must pass unchanged — the new parameter defaults to `None`.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/draft_results.py tests/test_draft_results_baseline.py
git commit -m "feat(engine): per-pick baseline fields, rookie ECR preferred over ADP"
```

---

### Task 6: Grader fork

**Files:**
- Modify: `api/app/services/grader.py:861-877` (the `cls.axis != "production"` gate) and `:1070-1084` (the `build_drafted_pick_results` call)
- Test: `api/tests/test_grader_rookie_ecr.py`

**Interfaces:**
- Consumes: `RookieBoardStore` (Task 4), `build_drafted_pick_results(..., rookie_ecr_by_draft=...)` (Task 5).
- Produces: `drafted_picks` rows carrying `baseline` / `baseline_delta` / `baseline_source` for dynasty rookie classes.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_grader_rookie_ecr.py`:

```python
"""The fork: a dynasty class gets a rookie board where it used to get nothing.

These exercise the resolution + wiring seam directly rather than driving a full
GraderService.run (those tests take ~30s each because MagicMock clients fall
into real retry/backoff).
"""
from datetime import date

from app.services.rookie_board_store import RookieBoardStore
from sleeper_dynasty.engine.draft_class import build_draft_classes


def test_a_dynasty_rookie_class_is_not_axis_production():
    # This is WHY the ADP block skipped dynasty: the gate is `axis !=
    # "production"`. The fork must key on something else.
    classes = build_draft_classes(
        drafts_by_league={"lg": [{
            "draft_id": "d1", "season": 2025, "status": "complete",
            "type": "snake", "settings": {"player_type": 1, "teams": 12},
        }]},
        league_format="dynasty", origin_season=2023)
    assert len(classes) == 1
    assert classes[0].kind == "rookie"
    assert classes[0].axis == "blend"


def test_store_resolves_a_board_for_a_dynasty_rookie_class(tmp_path):
    store = RookieBoardStore(tmp_path)
    board = store.resolve_for_draft("d1", date(2025, 5, 16))
    assert board is not None, "committed history must cover a May 2025 draft"
    assert len(board) > 50


def test_resolution_is_bounded_by_the_draft_date(tmp_path):
    store = RookieBoardStore(tmp_path)
    early = store.resolve_for_draft("d-early", date(2025, 5, 16))
    late = store.resolve_for_draft("d-late", date(2026, 5, 6))
    assert early is not None and late is not None
    assert early != late, "two drafts a year apart must face different boards"
```

- [ ] **Step 2: Run the test to characterise current behaviour**

This task's tests are **characterisation tests, not failing-first tests** — they pin the
behaviour the fork depends on (a dynasty rookie class is `axis == "blend"`, which is exactly
why the ADP loop skips it) rather than describing code that does not exist yet. The wiring in
Step 3 has no new unit surface of its own; it is covered by the existing grader tests in Step 4.

Run: `cd api && pytest tests/test_grader_rookie_ecr.py -v`
Expected: all PASS, given Tasks 2-4 have landed. If `test_resolution_is_bounded_by_the_draft_date`
fails, the committed history is missing one of the two draft years — regenerate it with
`scripts/extract_rookie_boards.py` before continuing rather than weakening the test.

- [ ] **Step 3: Wire the fork into the grader**

In `api/app/services/grader.py`, add beside the existing `adp_by_draft` declaration at line 731:

```python
        rookie_ecr_by_draft: dict[str, dict[str, float]] = {}
```

Add a second loop **inside the `if adp_store is not None:` block**, immediately after the existing `for cls in draft_classes:` loop that handles `axis == "production"`. Placement matters for two reasons: `last_picked_by_draft` is built inside that block and does not exist outside it, and `RookieBoardStore` needs the same `cache_dir` that gates it — with no cache dir there is nowhere to pin a board, so no baseline is the correct outcome.

Do not modify the existing loop. Redraft and keeper leagues keep Sleeper ADP exactly as they have it, and the two loops cannot collide: `build_draft_classes` assigns `kind = "full"` to every class in a redraft or keeper league, so `kind == "rookie"` selects dynasty classes only.

```python
                # The rookie fork. A dynasty class is axis "blend", which is
                # precisely why the ADP loop above skips it: Sleeper's
                # `adp_rookie` is unpopulated and its overall-NFL ADP would
                # grade a 1.01 against ~30th overall. FantasyPros' dynasty
                # ROOKIE consensus is the baseline that class actually has,
                # and unlike ADP it has dated history, so past classes grade
                # too — not going-forward only.
                from app.services.rookie_board_store import RookieBoardStore

                rookie_store = RookieBoardStore(cache_dir)
                for cls in draft_classes:
                    if cls.kind != "rookie":
                        continue
                    lp_ms = last_picked_by_draft.get(cls.draft_id)
                    if not lp_ms:
                        continue
                    drafted_on = _dt.datetime.fromtimestamp(
                        lp_ms / 1000, tz=timezone.utc).date()
                    board = rookie_store.resolve_for_draft(
                        cls.draft_id, drafted_on)
                    if board:
                        rookie_ecr_by_draft[cls.draft_id] = board
```

At the `build_drafted_pick_results` call (line 1070), add the new argument after `projected_by_player`:

```python
                rookie_ecr_by_draft=rookie_ecr_by_draft,
```

- [ ] **Step 4: Run the backend suite to verify nothing regressed**

Run: `cd api && pytest tests/test_grader_rookie_ecr.py tests/test_grader_draft_inputs.py tests/test_draft_board_view.py -v`
Expected: PASS. The rookie loop sits inside the same best-effort `try/except` as ADP, so a failure there drops the columns rather than failing the refresh.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/grader.py api/tests/test_grader_rookie_ecr.py
git commit -m "feat(api): grade dynasty rookie classes against a dated consensus board"
```

---

### Task 7: Surface the baseline on the draft board

Replace the two structurally-blank columns with the baseline the class actually has.

**Files:**
- Modify: `api/app/models/league.py:255-272` (`DraftBoardPick`)
- Modify: `api/app/services/draft_board_view.py:45-62`
- Modify: `web/lib/types.ts` (`DraftBoardPick`)
- Modify: `web/components/DraftBoard.tsx:197-254`
- Test: `api/tests/test_draft_board_baseline.py`

**Interfaces:**
- Consumes: `drafted_picks` rows with `baseline` / `baseline_delta` / `baseline_source` (Tasks 5–6).
- Produces: `DraftBoardPick.baseline`, `.baseline_delta`, `.baseline_source`; `DraftBoardResp.baseline_label: str`.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_draft_board_baseline.py`:

```python
from app.services.draft_board_view import build_draft_board
from tests.helpers import minimal_chain_cache_entry


def _entry(**pick_over):
    pick = dict(player_id="111", full_name="A Rookie", position="RB",
                drafter_id="u1", round=1, slot=4, picks_in_round=12,
                pick_no=4, draft_season=2025, production_total=0.0)
    pick.update(pick_over)
    return minimal_chain_cache_entry(drafted_picks=[pick, {**pick,
                                                          "player_id": "222",
                                                          "pick_no": 5}])


def test_baseline_fields_reach_the_response():
    board = build_draft_board(
        _entry(baseline=1.5, baseline_delta=2.5, baseline_source="rookie_ecr"),
        season=2025)
    assert board.picks[0].baseline == 1.5
    assert board.picks[0].baseline_delta == 2.5
    assert board.picks[0].baseline_source == "rookie_ecr"


def test_label_names_the_baseline_the_class_actually_has():
    ecr = build_draft_board(_entry(baseline=1.5, baseline_source="rookie_ecr"),
                            season=2025)
    assert ecr.baseline_label == "ECR"
    adp = build_draft_board(_entry(baseline=9.0, baseline_source="sleeper_adp"),
                            season=2025)
    assert adp.baseline_label == "ADP"


def test_label_is_empty_when_no_pick_carries_a_baseline():
    # A class with no baseline must not claim one. The UI drops the columns.
    board = build_draft_board(_entry(), season=2025)
    assert board.baseline_label == ""


def test_pre_feature_rows_default_rather_than_raise():
    # Rows written before this feature carry none of the three keys.
    board = build_draft_board(_entry(), season=2025)
    assert board.picks[0].baseline is None
    assert board.picks[0].baseline_source == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && pytest tests/test_draft_board_baseline.py -v`
Expected: FAIL with `AttributeError: 'DraftBoardPick' object has no attribute 'baseline'`

- [ ] **Step 3: Add the model fields**

In `api/app/models/league.py`, inside `class DraftBoardPick`, after `projected_points`:

```python
    # The external expectation this class actually has: rookie consensus for a
    # dynasty rookie class, Sleeper ADP for redraft/keeper. Null rather than
    # zero when the player is unranked — ungraded is not a score of zero.
    baseline: float | None = None
    baseline_delta: float | None = None
    baseline_source: str = ""
```

In `class DraftBoardResp`, add:

```python
    # "ECR", "ADP", or "" when no pick in the class carries a baseline. The UI
    # drops the columns on empty rather than printing a header over dashes.
    baseline_label: str = ""
```

- [ ] **Step 4: Populate them in the view**

In `api/app/services/draft_board_view.py`, add to the `DraftBoardPick(...)` construction inside the `picks = [...]` comprehension, after `projected_points=r.get("projected_points"),`:

```python
            baseline=r.get("baseline"),
            baseline_delta=r.get("baseline_delta"),
            baseline_source=str(r.get("baseline_source") or ""),
```

Before the `return DraftBoardResp(...)`, add:

```python
    # Named from the data rather than from the league format: one place decides
    # what the column is called, and it is the same place that filled it.
    _SOURCE_LABELS = {"rookie_ecr": "ECR", "sleeper_adp": "ADP"}
    baseline_label = ""
    for r in rows:
        label = _SOURCE_LABELS.get(str(r.get("baseline_source") or ""))
        if label and r.get("baseline") is not None:
            baseline_label = label
            break
```

Add `baseline_label=baseline_label,` to the `DraftBoardResp(...)` call.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd api && pytest tests/test_draft_board_baseline.py tests/test_draft_board_view.py -v`
Expected: PASS.

- [ ] **Step 6: Update the frontend types and table**

In `web/lib/types.ts`, add to the `DraftBoardPick` interface:

```typescript
  baseline?: number | null;
  baseline_delta?: number | null;
  baseline_source?: string;
```

and to `DraftBoardResp`:

```typescript
  baseline_label?: string;
```

In `web/components/DraftBoard.tsx`, in `PicksSection`, replace the `hasAdp` derivation:

```typescript
  const label = board.baseline_label ?? "";
  const hasBaseline = label !== "" && board.picks.some((p) => p.baseline != null);
```

Replace the two ADP column headers with:

```tsx
            {hasBaseline && (
              <>
                <div role="columnheader" className="text-right">{label}</div>
                <div role="columnheader" className="text-right">Slot +/-</div>
              </>
            )}
```

Replace the two ADP cells with:

```tsx
              {hasBaseline && (
                <>
                  <div role="cell" className="text-right">
                    {p.baseline != null ? p.baseline.toFixed(1) : <span className="text-dim">—</span>}
                  </div>
                  <div role="cell" className="text-right"><Signed value={p.baseline_delta} decimals={1} /></div>
                </>
              )}
```

Rename the `hasAdp` prop threaded into `pickGrid(...)` and `<DraftPicksMobile ... hasAdp={hasBaseline} />` to pass `hasBaseline`. Update `web/components/DraftPicksMobile.tsx` to read `p.baseline` / `p.baseline_delta` and to label the stat cell with the `label` prop rather than the literal `"ADP"`.

**The mobile rendering must keep every column.** `DraftBoard.tsx`'s own docstring is explicit: this is the one screen where a phone reader is the primary audience, and no field may be `display:none` with no alternate rendering.

- [ ] **Step 7: Run the frontend tests**

Run: `cd web && npx vitest --config tests/vitest.config.ts run`
Expected: PASS, including `tests/furniture-rules.test.ts`.

- [ ] **Step 8: Commit**

```bash
git add api/app/models/league.py api/app/services/draft_board_view.py api/tests/test_draft_board_baseline.py web/lib/types.ts web/components/DraftBoard.tsx web/components/DraftPicksMobile.tsx
git commit -m "feat(web): show the baseline a draft class actually has"
```

---

### Task 8: Full-suite verification

- [ ] **Step 1: Run every suite**

```bash
pytest tests/
cd api && pytest -v && cd ..
cd web && npx vitest --config tests/vitest.config.ts run && cd ..
```

Expected: all PASS. Do not proceed on a failure — fix it.

- [ ] **Step 2: Verify the Docker build still finds the packaged data file**

```bash
docker build -f api/Dockerfile -t trade-grader-api:local .
docker run --rm trade-grader-api:local python -c "
from importlib.resources import files
b = files('sleeper_dynasty.data').joinpath('rookie_ecr.json.gz').read_bytes()
print('packaged rookie ECR history:', len(b), 'bytes')
assert len(b) > 10_000
"
```

Expected: prints roughly 75,000 bytes. **If this fails, the `package-data` glob in Task 3 did not take effect** and the feature will work locally and be silently dead in production — the exact failure mode the `design-system-sync` skill documents for `.design/` assets.

- [ ] **Step 3: Commit any fixes and push the branch**

```bash
git push -u origin new-draft-board
```

---

## Self-Review

**Spec coverage (phase 1 only).** Committed history + package-data → Task 3. `rookie_board.py` → Task 2. Store with merged timeline and write-once pin → Task 4. Crosswalk reuse with `"NA"` filtering → Task 1. Grader fork keyed on `cls.kind == "rookie"` rather than `axis` → Task 6. `adp`/`adp_delta` unchanged → asserted in Task 5. No `SCHEMA_VERSION` bump → no `ChainCacheEntry` field is added; the three new keys ride on `drafted_picks`, already in the always-recomputed value layer. ECR never reaches Franchise Rating → no task touches `draft_signals.py` or `gm_rating.py`.

**Deferred to later phases, deliberately:** Start % and the `"started"` phase, Points Above Round, cohort verdicts, the grouped header, sorting, tooltips, the nav entry, and needs reconstruction. Phase 1 ships ECR + Slot +/- on the existing table shape.

**Known gap carried from the spec.** The ~6% owner-total reconciliation discrepancy is *not* addressed here and does not block phase 1 — phase 1 adds no owner-level aggregate. It must be resolved before phase 2, which builds Points Above Round on those totals.

**Type consistency.** `baseline` / `baseline_delta` / `baseline_source` are spelled identically in `draft_results.py`, `draft_board_view.py`, `league.py`, `types.ts` and `DraftBoard.tsx`. `rookie_ecr_by_draft` is the parameter name in both `build_drafted_pick_results` and the grader call site. `resolve_for_draft(draft_id, drafted_on)` matches `AdpSnapshotStore`'s existing signature minus its `field` kwarg, which has no analogue here (a rookie board has no scoring variants).
