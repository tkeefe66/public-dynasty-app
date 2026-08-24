# LLM Cost Control + Visibility Design

**Date:** 2026-06-15
**Status:** Approved

## Problem

All four LLM writers use `claude-opus-4-8` by default. During local development every test refresh regenerates all stories/blurbs from scratch at Opus pricing. In production the auto-refresh scheduler (every 3 hours) silently triggers additional API calls whenever facts hashes change. The developer has no visibility into when calls fire or what they cost.

## Goals

1. Cut local dev API costs by defaulting all writers to Haiku.
2. Provide a single env var override to switch models globally.
3. Track every LLM call (model, writer, tokens, cost) in a lightweight store.
4. Expose a settings page in the web app showing spend by time period and feature.

## Out of Scope

- Disabling LLM on auto-refresh (current behavior kept).
- Per-league cost attribution.
- Real-time streaming cost updates.

---

## Section 1 — Model Configuration

### Config change (`api/app/config.py`)

Add one optional field:

```python
llm_model: str | None = None  # env: TRADE_GRADER_LLM_MODEL
```

When set, this value is passed as the `model` argument to every writer at instantiation time in `grader.py`. When absent, each writer uses its own hardcoded default.

### Writer default changes

All four writers permanently switch to Haiku as their default:

| Writer | Old default | New default |
|---|---|---|
| `trade_story_writer.py` | `claude-opus-4-8` | `claude-haiku-4-5-20251001` |
| `gm_rating_blurb_writer.py` | `claude-opus-4-8` | `claude-haiku-4-5-20251001` |
| `franchise_outlook_writer.py` | `claude-opus-4-8` | `claude-haiku-4-5-20251001` |
| `recap_writer.py` | `claude-opus-4-8` | `claude-haiku-4-5-20251001` |

### Usage

- **Local dev:** add `TRADE_GRADER_LLM_MODEL=claude-haiku-4-5-20251001` to `api/.env` (already the default — this is for explicit override back to Opus if needed during testing).
- **Production:** set `TRADE_GRADER_LLM_MODEL=claude-opus-4-8` in Railway env vars when you want to restore Opus for stories.
- **No env var set:** all writers use Haiku.

---

## Section 2 — LlmCostStore

### File

`api/app/services/llm_cost_store.py`

### Storage

Appends to `<cache_dir>/llm_costs.jsonl` — newline-delimited JSON, one record per call. Append-only means no full-file rewrite on each call and no locking needed for sequential writes.

### Record schema

```json
{
  "ts": "2026-06-15T14:32:01Z",
  "model": "claude-haiku-4-5-20251001",
  "writer": "trade_story",
  "league_id": "123456789",
  "input_tokens": 840,
  "output_tokens": 312,
  "cost_usd": 0.000198
}
```

`writer` values: `trade_story` | `gm_rating_blurb` | `franchise_blurb` | `recap`

### Pricing table

Static dict in the store keyed by model name — input and output cost per million tokens. Updated manually when Anthropic changes rates. Cost is computed from the `usage` field on the Anthropic API response (already returned on every call, no extra requests).

### Integration points

The store is written to from the gen modules after each successful call:
- `api/app/services/story_gen.py` — after `writer.write(facts)` succeeds
- `api/app/services/blurb_gen.py` — after `writer.write(facts)` succeeds
- `api/app/services/franchise_blurb_gen.py` — after `writer.write(facts)` succeeds
- `src/sleeper_dynasty/llm/recap_writer.py` — after `_client.messages.create()` returns (CLI path). Recap has no `cache_dir` injection, so the store falls back to `~/.sleeper-dynasty/cache/llm_costs.jsonl` directly (same default path the backend uses when `TRADE_GRADER_CACHE_DIR` is set to its default).

The writer classes themselves stay pure (no store dependency) except recap, which is CLI-only and must resolve the path itself. The backend gen modules receive the store path via the `cache_dir` already threaded through.

---

## Section 3 — API Endpoint

### Route

`GET /api/settings/llm-cost?period=today|7d|30d|all`

New file: `api/app/routes/settings.py`

### Response shape

```json
{
  "period": "7d",
  "total_cost_usd": 0.118,
  "total_calls": 134,
  "daily_avg_usd": 0.017,
  "daily": [
    { "date": "2026-06-15", "cost_usd": 0.042, "calls": 18, "by_writer": { "trade_story": 0.031, "gm_rating_blurb": 0.008, "franchise_blurb": 0.003 } },
    { "date": "2026-06-14", "cost_usd": 0.031, "calls": 12, "by_writer": { ... } }
  ],
  "by_writer": {
    "trade_story":      { "cost_usd": 0.089, "calls": 44 },
    "gm_rating_blurb":  { "cost_usd": 0.021, "calls": 72 },
    "franchise_blurb":  { "cost_usd": 0.008, "calls": 24 },
    "recap":            { "cost_usd": 0.000, "calls": 0  }
  },
  "active_model": "claude-haiku-4-5-20251001"
}
```

`daily` buckets: `today` → hourly; `7d` / `30d` → daily; `all` → weekly.

`active_model` is read from `settings.llm_model` (falling back to the trade story writer's default) so the UI can display what's running.

No auth — single-user app.

Also add `GET /api/settings/config` returning `{ "llm_model": "..." }` for the active model callout.

---

## Section 4 — Frontend Settings UI

### Route

`/settings` — new Next.js page. Add a "Settings" link to the existing nav.

### Layout

**LLM Spend (top)**
- Period toggle: **Today · 7 days · 30 days · All time** — drives all data below.
- Three stat chips scoped to the period: **Total cost · Total calls · Daily average**
- Stacked bar chart — one bar per time bucket (hourly / daily / weekly depending on period), each bar color-coded by writer/feature so composition is visible at a glance.

**Breakdown table (below, scoped to same period)**

| Feature | Calls | Cost |
|---|---|---|
| Trade Stories | 44 | $0.089 |
| GM Profiles | 72 | $0.021 |
| Franchise Outlooks | 24 | $0.008 |
| Weekly Recap | 2 | $0.004 |
| **Total** | **142** | **$0.122** |

Sorted by cost descending. Totals row at bottom.

**Active model callout (below table)**

Small text row: `Active model: claude-haiku-4-5-20251001` — pulled from `/api/settings/config`.

### Behavior

- No real-time polling. Manual refresh button re-fetches.
- Period toggle is client-side state; switching periods re-fetches from the API.
- No drilldown per call (too granular for now).

---

## File Changelist

| File | Change |
|---|---|
| `api/app/config.py` | Add `llm_model: str \| None = None` |
| `src/sleeper_dynasty/llm/trade_story_writer.py` | `DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` | `DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `src/sleeper_dynasty/llm/franchise_outlook_writer.py` | `DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `src/sleeper_dynasty/llm/recap_writer.py` | `DEFAULT_MODEL = "claude-haiku-4-5-20251001"` |
| `api/app/services/llm_cost_store.py` | New — append-only JSONL store |
| `api/app/services/story_gen.py` | Write cost record after each successful call |
| `api/app/services/blurb_gen.py` | Write cost record after each successful call |
| `api/app/services/franchise_blurb_gen.py` | Write cost record after each successful call |
| `src/sleeper_dynasty/llm/recap_writer.py` | Write cost record after each successful call |
| `api/app/routes/settings.py` | New — `/api/settings/llm-cost` + `/api/settings/config` |
| `api/app/main.py` | Register settings router |
| `web/app/settings/page.tsx` | New — settings page |
| `web/components/LlmCostPanel.tsx` | New — spend UI component |
| `web/app/globals.css` or nav component | Add Settings nav link |
| `api/.env.example` | Document `TRADE_GRADER_LLM_MODEL` |
