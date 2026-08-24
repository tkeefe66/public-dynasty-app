> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# LLM Cost Control + Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut LLM API costs by defaulting all writers to Haiku, then surface per-feature spend in a `/settings` page with period-scoped breakdown.

**Architecture:** A new `LlmCostStore` (engine layer, `src/sleeper_dynasty/llm/cost_store.py`) appends one JSONL record per LLM call. Gen modules read token counts from the Anthropic response and write to the store. A new `/api/settings/llm-cost` endpoint aggregates by period + writer. The existing `/api/app/routes/settings.py` file gains the new endpoints (router is already registered in `main.py`). A new `/settings` Next.js page displays the data.

**Tech Stack:** Python (pydantic-settings, FastAPI, anthropic SDK), Next.js 14 App Router, Tailwind, existing CSS custom-property tokens (`--bg`, `--ink`, `--pos`, `--bg-alt`, `--border`, `--ink-dim`).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/sleeper_dynasty/llm/cost_store.py` | **Create** | Append-only JSONL store + pricing table |
| `src/sleeper_dynasty/llm/trade_story_writer.py` | Modify | Switch DEFAULT_MODEL; return `_usage` in write() |
| `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` | Modify | Switch DEFAULT_MODEL; return `_usage` in write() |
| `src/sleeper_dynasty/llm/franchise_outlook_writer.py` | Modify | Switch DEFAULT_MODEL; return `_usage` in write() |
| `src/sleeper_dynasty/llm/recap_writer.py` | Modify | Switch DEFAULT_MODEL; optional `cost_store` param |
| `api/app/config.py` | Modify | Add `llm_model: str \| None = None` |
| `api/app/services/grader.py` | Modify | Thread `llm_model` override + `cost_store` to gen calls |
| `api/app/services/story_gen.py` | Modify | Accept `cost_store` + `league_id`; record after each call |
| `api/app/services/blurb_gen.py` | Modify | Accept `cost_store` + `league_id`; record after each call |
| `api/app/services/franchise_blurb_gen.py` | Modify | Accept `cost_store` + `league_id`; record after each call |
| `api/app/routes/settings.py` | Modify | Add `/api/settings/llm-cost` + `/api/settings/config` |
| `api/.env.example` | Modify | Document `TRADE_GRADER_LLM_MODEL` |
| `tests/test_llm_cost_store.py` | **Create** | Unit tests for LlmCostStore |
| `api/tests/test_settings_llm_cost.py` | **Create** | Integration tests for new endpoints |
| `web/app/settings/page.tsx` | **Create** | Settings page shell |
| `web/components/LlmCostPanel.tsx` | **Create** | Period toggle + chart + breakdown table |

---

## Task 1: Create LlmCostStore (TDD)

**Files:**
- Create: `src/sleeper_dynasty/llm/cost_store.py`
- Create: `tests/test_llm_cost_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_llm_cost_store.py
from pathlib import Path
import json
import pytest
from sleeper_dynasty.llm.cost_store import LlmCostStore, _cost_usd


def test_read_empty(tmp_path):
    store = LlmCostStore(tmp_path)
    assert store.read_all() == []


def test_record_creates_file(tmp_path):
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    assert (tmp_path / "llm_costs.jsonl").exists()


def test_record_and_read(tmp_path):
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    records = store.read_all()
    assert len(records) == 1
    r = records[0]
    assert r["writer"] == "trade_story"
    assert r["model"] == "claude-haiku-4-5-20251001"
    assert r["league_id"] == "L1"
    assert r["input_tokens"] == 500
    assert r["output_tokens"] == 200
    assert r["cost_usd"] > 0
    assert "ts" in r


def test_cost_calculation_haiku_input():
    # 1M input tokens × $0.80/MTok = $0.80
    cost = _cost_usd("claude-haiku-4-5-20251001", 1_000_000, 0)
    assert abs(cost - 0.80) < 0.001


def test_cost_calculation_haiku_output():
    # 1M output tokens × $4.00/MTok = $4.00
    cost = _cost_usd("claude-haiku-4-5-20251001", 0, 1_000_000)
    assert abs(cost - 4.00) < 0.001


def test_multiple_records_append(tmp_path):
    store = LlmCostStore(tmp_path)
    for i in range(3):
        store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                     league_id="L1", input_tokens=100, output_tokens=50)
    assert len(store.read_all()) == 3


def test_unknown_model_uses_fallback(tmp_path):
    store = LlmCostStore(tmp_path)
    # Should not raise — falls back to mid-tier pricing
    store.record(model="claude-unknown-future", writer="recap",
                 league_id="", input_tokens=1000, output_tokens=500)
    records = store.read_all()
    assert records[0]["cost_usd"] > 0


def test_record_failure_is_silent(tmp_path):
    # Write to a path that's actually a file (can't create dir inside it)
    bad_dir = tmp_path / "a_file"
    bad_dir.write_text("not a dir")
    store = LlmCostStore(bad_dir)  # path/llm_costs.jsonl can't be created
    # Should not raise
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=100, output_tokens=50)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
pytest tests/test_llm_cost_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'sleeper_dynasty.llm.cost_store'`

- [ ] **Step 3: Create the store**

```python
# src/sleeper_dynasty/llm/cost_store.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# Cost per million tokens (input, output).
# Verify current rates at https://www.anthropic.com/pricing
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-haiku-4-5":          (0.80, 4.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-8":           (15.00, 75.00),
    "claude-opus-4-7":           (15.00, 75.00),
}
_FALLBACK_PRICING = (3.00, 15.00)  # unknown model: assume mid-tier


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = _PRICING.get(model, _FALLBACK_PRICING)
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


class LlmCostStore:
    def __init__(self, cache_dir: Path) -> None:
        self._path = Path(cache_dir) / "llm_costs.jsonl"

    def record(
        self,
        *,
        model: str,
        writer: str,
        league_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        cost = _cost_usd(model, input_tokens, output_tokens)
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "writer": writer,
            "league_id": league_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }
        try:
            with self._path.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            log.warning("failed to write LLM cost record", exc_info=True)

    def read_all(self) -> list[dict]:
        if not self._path.exists():
            return []
        records: list[dict] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_llm_cost_store.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/llm/cost_store.py tests/test_llm_cost_store.py
git commit -m "feat(llm): LlmCostStore — append-only JSONL cost recorder"
```

---

## Task 2: Switch all 4 writers to Haiku + return `_usage`

**Files:**
- Modify: `src/sleeper_dynasty/llm/trade_story_writer.py`
- Modify: `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py`
- Modify: `src/sleeper_dynasty/llm/franchise_outlook_writer.py`
- Modify: `src/sleeper_dynasty/llm/recap_writer.py`

The `write()` method on each writer currently returns content and discards `resp.usage`. We need the token counts for cost recording. The pattern: add `_usage` to the return dict (trade_story, blurb, franchise) or accept an optional `cost_store` on the class (recap, since it returns a plain string).

- [ ] **Step 1: Update `trade_story_writer.py`**

Change `DEFAULT_MODEL` and extend `write()` to include `_usage`:

```python
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

In `TradeStoryWriter.write()`, change the return:

```python
def write(self, facts: TradeStoryFacts) -> dict[str, str]:
    system, messages = self.build_request(facts)
    logger.info("Requesting trade story from %s (trade %s)",
                self.model, facts.trade_id)
    resp = self._client.messages.create(
        model=self.model, max_tokens=MAX_TOKENS,
        system=system, messages=messages,
    )
    result = parse_story(resp.content[0].text)
    result["_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return result
```

- [ ] **Step 2: Update `gm_rating_blurb_writer.py`**

```python
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

In `GmRatingBlurbWriter.write()`:

```python
def write(self, facts: OwnerRatingFacts) -> dict[str, str]:
    system, messages = self.build_request(facts)
    logger.info("Requesting GM blurb from %s (owner %s, %s)",
                self.model, facts.owner_name, facts.scope_label)
    resp = self._client.messages.create(
        model=self.model, max_tokens=MAX_TOKENS,
        system=system, messages=messages,
    )
    result = parse_blurb(resp.content[0].text)
    result["_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return result
```

- [ ] **Step 3: Update `franchise_outlook_writer.py`**

```python
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

In `FranchiseOutlookWriter.write()`:

```python
def write(self, facts: FranchiseFacts) -> dict[str, str]:
    system, messages = self.build_request(facts)
    logger.info("Requesting franchise blurb from %s (owner %s)",
                self.model, facts.owner_name)
    resp = self._client.messages.create(
        model=self.model, max_tokens=MAX_TOKENS,
        system=system, messages=messages,
    )
    result = parse_franchise(resp.content[0].text)
    result["_usage"] = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return result
```

- [ ] **Step 4: Update `recap_writer.py`**

`RecapWriter.write()` returns a plain `str`, so `_usage` doesn't fit the same pattern. Instead, accept an optional `cost_store` at `__init__` and record inline:

```python
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
```

```python
class RecapWriter:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        persona: str | None = None,
        cost_store=None,  # optional LlmCostStore instance
    ) -> None:
        self.model = model
        self.persona = persona or load_default_persona()
        self._client = anthropic.Anthropic(api_key=api_key)
        self._cost_store = cost_store
```

In `RecapWriter.write()`:

```python
def write(
    self, facts: RecapFacts, lore: str | None = None,
    outlook: "OutlookFacts | None" = None,
) -> str:
    system, messages = self.build_request(facts, lore, outlook)
    logger.info("Requesting recap from %s (week %d)", self.model, facts.week)
    resp = self._client.messages.create(
        model=self.model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=messages,
    )
    if self._cost_store is not None:
        try:
            self._cost_store.record(
                model=self.model,
                writer="recap",
                league_id="",
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            )
        except Exception:
            pass
    return resp.content[0].text
```

- [ ] **Step 5: Run existing tests to verify nothing broke**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
pytest tests/test_trade_story_writer.py tests/test_recap_writer.py tests/test_gm_rating_blurb_writer.py -v 2>/dev/null || pytest tests/ -k "story_writer or recap_writer or blurb_writer" -v
```

Expected: all passing (tests use injected writers, so DEFAULT_MODEL change doesn't affect them).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/trade_story_writer.py \
        src/sleeper_dynasty/llm/gm_rating_blurb_writer.py \
        src/sleeper_dynasty/llm/franchise_outlook_writer.py \
        src/sleeper_dynasty/llm/recap_writer.py
git commit -m "feat(llm): default all writers to Haiku; return _usage metadata for cost tracking"
```

---

## Task 3: Add `llm_model` config + thread through grader

**Files:**
- Modify: `api/app/config.py`
- Modify: `api/app/services/grader.py`
- Modify: `api/.env.example`

- [ ] **Step 1: Add field to `api/app/config.py`**

Add one line inside the `Settings` class, after `refresh_interval_seconds`:

```python
llm_model: str | None = None  # env: TRADE_GRADER_LLM_MODEL — overrides all writer defaults
```

- [ ] **Step 2: Thread override through `grader.py`**

In `GraderService.run()`, each writer is instantiated in an `if writer is None:` block. Update each block to pass the config override.

Find the three blocks and update them:

**Trade story writer** (around line 209–211):
```python
if writer is None:
    from sleeper_dynasty.llm.trade_story_writer import TradeStoryWriter
    from app.config import get_settings
    _m = get_settings().llm_model
    writer = TradeStoryWriter(model=_m) if _m else TradeStoryWriter()
```

**GM blurb writer** (around line 380–382):
```python
if blurb_writer is None:
    from sleeper_dynasty.llm.gm_rating_blurb_writer import GmRatingBlurbWriter
    from app.config import get_settings
    _m = get_settings().llm_model
    blurb_writer = GmRatingBlurbWriter(model=_m) if _m else GmRatingBlurbWriter()
```

**Franchise writer** (around line 405–409):
```python
if fr_writer is None:
    from sleeper_dynasty.llm.franchise_outlook_writer import FranchiseOutlookWriter
    from app.config import get_settings
    _m = get_settings().llm_model
    fr_writer = FranchiseOutlookWriter(model=_m) if _m else FranchiseOutlookWriter()
```

- [ ] **Step 3: Update `api/.env.example`**

Add after the `TRADE_GRADER_REFRESH_INTERVAL_SECONDS` line (or at end of LLM section):

```bash
# Override LLM model for all writers. Default: claude-haiku-4-5-20251001
# Set to claude-opus-4-8 in production for higher-quality trade stories.
# TRADE_GRADER_LLM_MODEL=claude-opus-4-8
```

- [ ] **Step 4: Verify API tests still pass**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api"
pytest tests/ -v --tb=short 2>/dev/null | tail -20
```

Expected: existing tests pass (writers are injected in tests, not constructed from config).

- [ ] **Step 5: Commit**

```bash
git add api/app/config.py api/app/services/grader.py api/.env.example
git commit -m "feat(config): TRADE_GRADER_LLM_MODEL override for all LLM writers"
```

---

## Task 4: Wire cost recording in gen modules + grader

**Files:**
- Modify: `api/app/services/story_gen.py`
- Modify: `api/app/services/blurb_gen.py`
- Modify: `api/app/services/franchise_blurb_gen.py`
- Modify: `api/app/services/grader.py`

The gen modules need two new parameters: `cost_store` (optional `LlmCostStore`) and `league_id` (str). The grader creates the store and passes it in.

- [ ] **Step 1: Update `story_gen.py` signature and recording**

Add `cost_store` and `league_id` to `generate_stories`:

```python
async def generate_stories(
    *,
    resolved: list,
    grades: dict[str, dict],
    supporting: dict[str, Any],
    prior_stories: dict[str, dict],
    writer,
    resolved_dicts: list[dict] | None = None,
    current_holders: dict[str, str] | None = None,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,   # optional LlmCostStore
    league_id: str = "",
) -> tuple[dict[str, dict], dict[str, dict]]:
```

Inside the `_one` coroutine, after `result = await asyncio.to_thread(writer.write, facts)` succeeds, add cost recording and strip `_usage` before caching:

```python
result = await asyncio.to_thread(writer.write, facts)
# Record cost before stripping metadata
if cost_store is not None and "_usage" in result:
    try:
        cost_store.record(
            model=writer.model,
            writer="trade_story",
            league_id=league_id,
            input_tokens=result["_usage"]["input_tokens"],
            output_tokens=result["_usage"]["output_tokens"],
        )
    except Exception:
        pass
# Strip internal metadata before caching
content = {k: v for k, v in result.items() if not k.startswith("_")}
```

Then use `content` (not `result`) when building the cache entry for `stories[tx]`. Read the current code in `_one` to find exactly where `result` is stored and replace that reference with `content`.

- [ ] **Step 2: Update `blurb_gen.py` signature and recording**

Add `cost_store` and `league_id` to `generate_owner_rating_blurbs`:

```python
async def generate_owner_rating_blurbs(
    *,
    facts_by_scope: dict[str, dict[str, OwnerRatingFacts]],
    prior_blurbs: dict[str, dict[str, dict]],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,
    league_id: str = "",
) -> dict[str, dict[str, dict]]:
```

After each successful `writer.write(facts)` call (find the `_one` or equivalent coroutine), record cost and strip `_usage`:

```python
result = await asyncio.to_thread(writer.write, facts)
if cost_store is not None and "_usage" in result:
    try:
        cost_store.record(
            model=writer.model,
            writer="gm_rating_blurb",
            league_id=league_id,
            input_tokens=result["_usage"]["input_tokens"],
            output_tokens=result["_usage"]["output_tokens"],
        )
    except Exception:
        pass
content = {k: v for k, v in result.items() if not k.startswith("_")}
```

Use `content` when building the cached blurb entry.

- [ ] **Step 3: Update `franchise_blurb_gen.py` signature and recording**

Add `cost_store` and `league_id` to `generate_franchise_blurbs`:

```python
async def generate_franchise_blurbs(
    *,
    facts_by_owner: dict[str, FranchiseFacts],
    prior_blurbs: dict[str, dict],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
    cost_store=None,
    league_id: str = "",
) -> dict[str, dict]:
```

Same pattern — after `writer.write(facts)` succeeds, record cost and strip `_usage` before caching.

```python
result = await asyncio.to_thread(writer.write, facts)
if cost_store is not None and "_usage" in result:
    try:
        cost_store.record(
            model=writer.model,
            writer="franchise_blurb",
            league_id=league_id,
            input_tokens=result["_usage"]["input_tokens"],
            output_tokens=result["_usage"]["output_tokens"],
        )
    except Exception:
        pass
content = {k: v for k, v in result.items() if not k.startswith("_")}
```

- [ ] **Step 4: Update `grader.py` to create and pass the store**

At the top of `GraderService.run()`, after the `cache_dir` check, instantiate the store:

```python
from sleeper_dynasty.llm.cost_store import LlmCostStore
cost_store = LlmCostStore(cache_dir) if cache_dir is not None else None
```

Then pass it to each gen call:

**story gen call** (around line 226):
```python
trade_stories, owner_dossiers = await generate_stories(
    resolved=resolved, grades=grades, supporting=supporting,
    prior_stories=prior, writer=writer, progress_cb=progress_cb,
    resolved_dicts=resolved_dicts, current_holders=current_holders,
    cost_store=cost_store, league_id=current_league_id,
)
```

**blurb gen call** (around line 390):
```python
entry.owner_rating_blurbs = await generate_owner_rating_blurbs(
    facts_by_scope=facts_by_scope, prior_blurbs=prior_blurbs,
    writer=blurb_writer, progress_cb=progress_cb,
    cost_store=cost_store, league_id=current_league_id,
)
```

**franchise blurb gen call** (around line 443):
```python
entry.franchise_blurbs = await generate_franchise_blurbs(
    facts_by_owner=facts_by_owner, prior_blurbs=prior_fr,
    writer=fr_writer, progress_cb=progress_cb,
    cost_store=cost_store, league_id=current_league_id,
)
```

- [ ] **Step 5: Run API tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api"
pytest tests/ -v --tb=short 2>/dev/null | tail -30
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/story_gen.py \
        api/app/services/blurb_gen.py \
        api/app/services/franchise_blurb_gen.py \
        api/app/services/grader.py \
        src/sleeper_dynasty/llm/cost_store.py
git commit -m "feat(llm): wire LlmCostStore into story/blurb/franchise gen modules"
```

---

## Task 5: Add `/api/settings/llm-cost` + `/api/settings/config` endpoints

**Files:**
- Modify: `api/app/routes/settings.py` (already exists — add to it)
- Create: `api/tests/test_settings_llm_cost.py`

Note: `settings.py` currently contains owner-name endpoints. The router is already registered in `main.py`. Just add the new endpoints to the existing file.

- [ ] **Step 1: Write failing tests**

```python
# api/tests/test_settings_llm_cost.py
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    # Clear settings cache if get_settings uses lru_cache
    try:
        from app.config import get_settings
        get_settings.cache_clear()
    except AttributeError:
        pass
    from app.main import app
    return TestClient(app)


def test_llm_cost_empty(client):
    resp = client.get("/api/settings/llm-cost?period=7d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost_usd"] == 0.0
    assert data["total_calls"] == 0
    assert data["daily"] == []
    assert data["by_writer"] == {}
    assert "active_model" in data


def test_llm_cost_with_record(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=1_000_000, output_tokens=0)

    resp = client.get("/api/settings/llm-cost?period=7d")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_calls"] == 1
    assert abs(data["total_cost_usd"] - 0.80) < 0.01
    assert "trade_story" in data["by_writer"]
    assert data["by_writer"]["trade_story"]["calls"] == 1
    assert len(data["daily"]) == 1


def test_llm_cost_by_writer_breakdown(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story",
                 league_id="L1", input_tokens=500, output_tokens=200)
    store.record(model="claude-haiku-4-5-20251001", writer="gm_rating_blurb",
                 league_id="L1", input_tokens=300, output_tokens=100)

    resp = client.get("/api/settings/llm-cost?period=7d")
    data = resp.json()
    assert set(data["by_writer"].keys()) == {"trade_story", "gm_rating_blurb"}


def test_config_endpoint(client):
    resp = client.get("/api/settings/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "llm_model" in data
    # Default (no env override) should be the Haiku model
    assert "haiku" in data["llm_model"]


def test_period_today_filters_old_records(client, tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    import json
    # Manually write an old record (2020)
    path = tmp_path / "llm_costs.jsonl"
    path.write_text(json.dumps({
        "ts": "2020-01-01T00:00:00+00:00",
        "model": "claude-haiku-4-5-20251001",
        "writer": "trade_story",
        "league_id": "L1",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": 0.003,
    }) + "\n")

    resp = client.get("/api/settings/llm-cost?period=today")
    data = resp.json()
    assert data["total_calls"] == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api"
pytest tests/test_settings_llm_cost.py -v
```

Expected: FAIL (endpoints don't exist yet).

- [ ] **Step 3: Add endpoints to `api/app/routes/settings.py`**

Add the following at the end of the existing `settings.py` file (keep all existing owner-name endpoints intact):

```python
# ── LLM cost tracking ────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel as _BaseModel

from app.deps import get_cache_dir
from sleeper_dynasty.llm.cost_store import LlmCostStore


class _WriterCost(_BaseModel):
    cost_usd: float
    calls: int


class _DailyBucket(_BaseModel):
    date: str
    cost_usd: float
    calls: int
    by_writer: dict[str, float]


class LlmCostResponse(_BaseModel):
    period: str
    total_cost_usd: float
    total_calls: int
    daily_avg_usd: float
    daily: list[_DailyBucket]
    by_writer: dict[str, _WriterCost]
    active_model: str


class ConfigResponse(_BaseModel):
    llm_model: str


@router.get("/api/settings/llm-cost", response_model=LlmCostResponse)
def get_llm_cost(
    period: Literal["today", "7d", "30d", "all"] = "7d",
) -> LlmCostResponse:
    store = LlmCostStore(get_cache_dir())
    records = store.read_all()

    now = datetime.now(tz=timezone.utc)
    if period == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days = 1
    elif period == "7d":
        cutoff = now - timedelta(days=7)
        days = 7
    elif period == "30d":
        cutoff = now - timedelta(days=30)
        days = 30
    else:
        cutoff = None
        days = None

    if cutoff:
        records = [
            r for r in records
            if datetime.fromisoformat(r["ts"]) >= cutoff
        ]

    if not records:
        from sleeper_dynasty.llm.trade_story_writer import DEFAULT_MODEL
        from app.config import get_settings
        active = get_settings().llm_model or DEFAULT_MODEL
        return LlmCostResponse(
            period=period, total_cost_usd=0.0, total_calls=0,
            daily_avg_usd=0.0, daily=[], by_writer={}, active_model=active,
        )

    total_cost = round(sum(r["cost_usd"] for r in records), 6)
    total_calls = len(records)

    if days is None:
        first_ts = datetime.fromisoformat(records[0]["ts"])
        days = max(1, (now - first_ts).days + 1)

    # by_writer
    writer_map: dict[str, _WriterCost] = {}
    for r in records:
        w = r["writer"]
        if w not in writer_map:
            writer_map[w] = _WriterCost(cost_usd=0.0, calls=0)
        writer_map[w].cost_usd = round(writer_map[w].cost_usd + r["cost_usd"], 6)
        writer_map[w].calls += 1

    # daily buckets
    bucket_map: dict[str, dict] = {}
    for r in records:
        date_key = r["ts"][:10]
        if date_key not in bucket_map:
            bucket_map[date_key] = {
                "date": date_key, "cost_usd": 0.0, "calls": 0, "by_writer": {},
            }
        b = bucket_map[date_key]
        b["cost_usd"] = round(b["cost_usd"] + r["cost_usd"], 6)
        b["calls"] += 1
        w = r["writer"]
        b["by_writer"][w] = round(b["by_writer"].get(w, 0.0) + r["cost_usd"], 6)

    daily = [
        _DailyBucket(**b)
        for b in sorted(bucket_map.values(), key=lambda x: x["date"])
    ]

    from sleeper_dynasty.llm.trade_story_writer import DEFAULT_MODEL
    from app.config import get_settings
    active = get_settings().llm_model or DEFAULT_MODEL

    return LlmCostResponse(
        period=period,
        total_cost_usd=total_cost,
        total_calls=total_calls,
        daily_avg_usd=round(total_cost / days, 6),
        daily=daily,
        by_writer=writer_map,
        active_model=active,
    )


@router.get("/api/settings/config", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    from sleeper_dynasty.llm.trade_story_writer import DEFAULT_MODEL
    from app.config import get_settings
    return ConfigResponse(llm_model=get_settings().llm_model or DEFAULT_MODEL)
```

- [ ] **Step 4: Run tests**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/api"
pytest tests/test_settings_llm_cost.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run full API test suite**

```bash
pytest tests/ -v --tb=short 2>/dev/null | tail -20
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add api/app/routes/settings.py api/tests/test_settings_llm_cost.py
git commit -m "feat(api): /api/settings/llm-cost and /api/settings/config endpoints"
```

---

## Task 6: Frontend settings page + LlmCostPanel

**Files:**
- Create: `web/app/settings/page.tsx`
- Create: `web/components/LlmCostPanel.tsx`

The page lives at `/settings`. It uses CSS custom-property tokens already defined in `web/app/globals.css` (`--bg`, `--ink`, `--pos`, `--bg-alt`, `--border`, `--ink-dim`). The stacked bar chart is pure CSS — no new dependencies.

- [ ] **Step 1: Create `web/app/settings/page.tsx`**

```tsx
// web/app/settings/page.tsx
import LlmCostPanel from "@/components/LlmCostPanel";

export const metadata = { title: "Settings · dynasty.report" };

export default function SettingsPage() {
  return (
    <main className="max-w-2xl mx-auto py-10 px-4">
      <h1 className="text-2xl font-bold mb-8">Settings</h1>
      <LlmCostPanel />
    </main>
  );
}
```

- [ ] **Step 2: Create `web/components/LlmCostPanel.tsx`**

```tsx
// web/components/LlmCostPanel.tsx
"use client";

import { useState, useEffect, useCallback } from "react";

type Period = "today" | "7d" | "30d" | "all";

interface WriterCost {
  cost_usd: number;
  calls: number;
}

interface DailyBucket {
  date: string;
  cost_usd: number;
  calls: number;
  by_writer: Record<string, number>;
}

interface LlmCostData {
  period: string;
  total_cost_usd: number;
  total_calls: number;
  daily_avg_usd: number;
  daily: DailyBucket[];
  by_writer: Record<string, WriterCost>;
  active_model: string;
}

const WRITER_LABELS: Record<string, string> = {
  trade_story: "Trade Stories",
  gm_rating_blurb: "GM Profiles",
  franchise_blurb: "Franchise Outlooks",
  recap: "Weekly Recap",
};

const WRITER_COLORS: Record<string, string> = {
  trade_story: "var(--pos)",
  gm_rating_blurb: "#6366f1",
  franchise_blurb: "#f59e0b",
  recap: "#10b981",
};

const PERIOD_LABELS: Record<Period, string> = {
  today: "Today",
  "7d": "7 days",
  "30d": "30 days",
  all: "All time",
};

function fmt(usd: number) {
  return usd < 0.01 ? `$${usd.toFixed(5)}` : `$${usd.toFixed(3)}`;
}

export default function LlmCostPanel() {
  const [period, setPeriod] = useState<Period>("7d");
  const [data, setData] = useState<LlmCostData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/settings/llm-cost?period=${period}`);
      if (!res.ok) throw new Error(`${res.status}`);
      setData(await res.json());
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const writers = data ? Object.keys(data.by_writer) : [];
  const maxCost = data
    ? Math.max(...data.daily.map((d) => d.cost_usd), 0.00001)
    : 1;

  return (
    <section>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">LLM Spend</h2>
        <button
          onClick={fetchData}
          className="text-xs text-[var(--ink-dim)] underline"
        >
          Refresh
        </button>
      </div>

      {/* Period toggle */}
      <div className="flex gap-2 mb-5 flex-wrap">
        {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`px-3 py-1 rounded text-sm transition-colors ${
              period === p
                ? "bg-[var(--pos)] text-white"
                : "bg-[var(--bg-alt)] text-[var(--ink)]"
            }`}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
      </div>

      {loading && (
        <p className="text-sm text-[var(--ink-dim)]">Loading…</p>
      )}

      {!loading && data && (
        <>
          {/* Stat chips */}
          <div className="flex gap-3 mb-6 flex-wrap">
            {[
              { label: "Total", value: fmt(data.total_cost_usd) },
              { label: "Calls", value: String(data.total_calls) },
              { label: "Daily avg", value: fmt(data.daily_avg_usd) },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="bg-[var(--bg-alt)] rounded px-4 py-2 text-center min-w-[80px]"
              >
                <div className="text-xs text-[var(--ink-dim)] mb-0.5">{label}</div>
                <div className="text-sm font-mono font-semibold">{value}</div>
              </div>
            ))}
          </div>

          {/* Stacked bar chart */}
          {data.daily.length > 0 && (
            <div className="mb-6">
              <div className="flex items-end gap-0.5 h-20 mb-1">
                {data.daily.map((day) => (
                  <div
                    key={day.date}
                    className="flex-1 flex flex-col-reverse min-w-0"
                    title={`${day.date}: ${fmt(day.cost_usd)} (${day.calls} calls)`}
                  >
                    {writers.map((w) => {
                      const wCost = day.by_writer[w] || 0;
                      const pct = (wCost / maxCost) * 100;
                      return (
                        <div
                          key={w}
                          style={{
                            height: `${pct}%`,
                            backgroundColor: WRITER_COLORS[w] || "#888",
                          }}
                          title={`${WRITER_LABELS[w] || w}: ${fmt(wCost)}`}
                        />
                      );
                    })}
                  </div>
                ))}
              </div>
              {/* Chart legend */}
              <div className="flex gap-3 flex-wrap">
                {writers.map((w) => (
                  <div
                    key={w}
                    className="flex items-center gap-1 text-xs text-[var(--ink-dim)]"
                  >
                    <div
                      className="w-2 h-2 rounded-sm flex-shrink-0"
                      style={{ backgroundColor: WRITER_COLORS[w] || "#888" }}
                    />
                    {WRITER_LABELS[w] || w}
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.total_calls === 0 && (
            <p className="text-sm text-[var(--ink-dim)] mb-4">
              No LLM calls recorded for this period.
            </p>
          )}

          {/* Breakdown table */}
          {writers.length > 0 && (
            <table className="w-full text-sm mb-4">
              <thead>
                <tr className="text-left text-xs text-[var(--ink-dim)] border-b border-[var(--border)]">
                  <th className="pb-2 font-normal">Feature</th>
                  <th className="pb-2 font-normal text-right">Calls</th>
                  <th className="pb-2 font-normal text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.by_writer)
                  .sort(([, a], [, b]) => b.cost_usd - a.cost_usd)
                  .map(([w, info]) => (
                    <tr
                      key={w}
                      className="border-b border-[var(--border)]"
                    >
                      <td className="py-2">
                        <div className="flex items-center gap-2">
                          <div
                            className="w-2 h-2 rounded-sm flex-shrink-0"
                            style={{
                              backgroundColor: WRITER_COLORS[w] || "#888",
                            }}
                          />
                          {WRITER_LABELS[w] || w}
                        </div>
                      </td>
                      <td className="py-2 text-right font-mono">
                        {info.calls}
                      </td>
                      <td className="py-2 text-right font-mono">
                        {fmt(info.cost_usd)}
                      </td>
                    </tr>
                  ))}
                <tr className="font-semibold text-sm">
                  <td className="pt-2">Total</td>
                  <td className="pt-2 text-right font-mono">
                    {data.total_calls}
                  </td>
                  <td className="pt-2 text-right font-mono">
                    {fmt(data.total_cost_usd)}
                  </td>
                </tr>
              </tbody>
            </table>
          )}

          {/* Active model */}
          <p className="text-xs text-[var(--ink-dim)]">
            Active model:{" "}
            <span className="font-mono">{data.active_model}</span>
          </p>
        </>
      )}
    </section>
  );
}
```

- [ ] **Step 3: Run frontend type check**

```bash
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty/web"
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors for the new files.

- [ ] **Step 4: Commit**

```bash
git add web/app/settings/page.tsx web/components/LlmCostPanel.tsx
git commit -m "feat(web): /settings page with LLM spend breakdown by period + feature"
```

---

## Task 7: Add Settings nav link + smoke test

**Files:**
- Identify and modify the nav/header component (the root layout at `web/app/layout.tsx` delegates to `ThemeProvider` — find where the per-page nav lives by looking at `web/app/league/[id]/` pages or searching for a shared header component)

- [ ] **Step 1: Find the nav component**

```bash
grep -rn "href\|<a \|<Link" "/Users/tomkeefe/Code Apps/sleeper-dynasty/web/app" \
  --include="*.tsx" | grep -v "node_modules" | grep -v ".next" | head -20
find "/Users/tomkeefe/Code Apps/sleeper-dynasty/web/components" -name "*.tsx" | head -20
```

Look at the output to find where navigation links live. Common locations: `web/components/Nav.tsx`, `web/app/league/[id]/layout.tsx`, or inline in `web/app/page.tsx`.

- [ ] **Step 2: Add Settings link**

In whatever file renders the nav, add a link to `/settings`. Example pattern (adapt to match what you find):

```tsx
import Link from "next/link";
// ...inside the nav/header:
<Link
  href="/settings"
  className="text-sm text-[var(--ink-dim)] hover:text-[var(--ink)] transition-colors"
>
  Settings
</Link>
```

- [ ] **Step 3: Start dev servers and verify the page**

```bash
# Terminal 1
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
make dev-api

# Terminal 2
cd "/Users/tomkeefe/Code Apps/sleeper-dynasty"
make dev-web
```

Then open `http://localhost:3000/settings` in a browser.

Verify:
- The page loads without errors
- All four period toggles (Today / 7 days / 30 days / All time) switch data
- "No LLM calls recorded" message shows when the store is empty
- Active model shows `claude-haiku-4-5-20251001`

- [ ] **Step 4: Trigger a refresh and verify cost recording**

Load a league in the app and trigger a manual refresh. Then reload `/settings` — the period=today view should show spend broken down by feature.

If `ANTHROPIC_API_KEY` is set locally: real calls fire and real records appear.
If not set: stories/blurbs are skipped (existing behavior); the store stays empty but the page still renders correctly.

- [ ] **Step 5: Commit**

```bash
git add web/  # or specific nav file
git commit -m "feat(web): Settings nav link; LLM cost visibility complete"
```

---

## Self-Review Checklist

- [x] `LlmCostStore` is in the engine layer (`src/sleeper_dynasty/llm/`) so both the API gen modules and the CLI recap writer can import it without circular deps
- [x] `_usage` key is stripped before caching in all three gen modules — cached blurb/story dicts stay clean
- [x] `settings.py` router is already registered in `main.py` — no `main.py` change needed
- [x] All gen functions have `cost_store=None` default — existing callers (tests) that don't pass it continue to work
- [x] `get_settings()` has no `@lru_cache` — no cache-clear needed in tests
- [x] Pricing table includes the model IDs actually used (`claude-haiku-4-5-20251001`, `claude-opus-4-8`)
- [x] The `fmt()` helper in the frontend uses 5 decimal places for sub-cent amounts, 3 for larger — avoids "$0.00000" rounding to zero
