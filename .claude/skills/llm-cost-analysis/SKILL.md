---
name: llm-cost-analysis
description: Use when investigating LLM spend, Anthropic API costs, llm_costs.jsonl, the LLM throttle, or why trade stories / GM blurbs / franchise outlooks regenerate too often (skip-hash churn, daily regeneration, offseason cost), or before triggering a manual / `force=true` league refresh.
---

# LLM Cost Analysis

## Overview

All LLM cost in this app is prose generation on Haiku 4.5 during refresh. **Churn — regenerating prose whose facts didn't materially change — dominates cost, not per-call price.** Diagnose churn first; model/caching changes are almost never the answer (avg input ~3.4k tokens is below Haiku's 4096-token cacheable minimum, so prompt caching silently never engages).

## Subsystem map

| Piece | Where |
|---|---|
| Writers (all `claude-haiku-4-5-20251001`) | `src/sleeper_dynasty/llm/{trade_story,gm_rating_blurb,franchise_outlook,recap}_writer.py` |
| Cost ledger (JSONL, one row per call) | `LlmCostStore` → `<cache_dir>/llm_costs.jsonl`; prod: `/data/sleeper-dynasty/cache/llm_costs.jsonl` |
| Generators + skip logic | `api/app/services/{story_gen,blurb_gen,franchise_blurb_gen}.py` (`*_PROMPT_VERSION` folded into hash) |
| Coarsened skip-hash | `src/sleeper_dynasty/models/_signature.py` (+ `facts_hash` per model) |
| Throttle (one LLM pass per interval) | `grader.py` "LLM-regeneration throttle"; `llm_min_interval_seconds` (default 20h) → env `TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS` |
| Offseason/no-new-trades signal | `grader.py` incremental-reuse decision (`scoring_in_progress` + `new_transaction_ids`) |
| Admin surfacing | `api/app/routes/admin.py` (per-league cost rollup) |

## Pull the prod ledger

```bash
railway ssh --service api "cat /data/sleeper-dynasty/cache/llm_costs.jsonl" > /tmp/llm_costs.jsonl
```

(Confirm `railway status` shows project `public-dynasty` first.)

## Analyze

```python
import json, collections
recs = [json.loads(l) for l in open("/tmp/llm_costs.jsonl") if l.strip()]
print("total $", round(sum(r["cost_usd"] for r in recs), 2))
bw = collections.defaultdict(lambda: [0, 0.0])
for r in recs:
    bw[r["writer"]][0] += 1; bw[r["writer"]][1] += r["cost_usd"]
for w, (n, c) in sorted(bw.items(), key=lambda x: -x[1][1]):
    print(f"{w:24s} n={n:5d} ${c:.2f}")
d = collections.defaultdict(collections.Counter)
for r in recs:
    d[r["ts"][:10]][r["writer"]] += 1
for day in sorted(d)[-14:]:
    print(day, dict(d[day]))
```

## Churn diagnosis (read the daily counts)

- **Healthy offseason: ~0 calls/day.** Facts shouldn't move when no games are played and no trades happen.
- **`franchise_blurb` count == owner count every day** → 100% churn; the facts hash moves daily.
- Known signature leak spots (`_signature.py`): **ints bypass banding** (only floats and `rating` are banded — int-valued KTC fields stay exact); **ranks kept exact** (adjacent owners swap daily on KTC drift); **exact-kept derived strings/ordered lists** (`young_core`, `aging_risks`, `top_need`, `signature_trade`).
- Verify a suspected leak by capturing facts packets from two consecutive refreshes and diffing the coarsened dicts — hashes must match when nothing happened.
- Two benign one-day spikes to rule out before suspecting a new leak: a per-writer `*_PROMPT_VERSION` bump (regenerates everything once), and the 20h throttle cadence occasionally fitting two LLM passes into one calendar day (~2× the normal count).

## Levers (state as of Aug 2026)

1. **Shipped:** offseason gate — `grader.py::llm_pass_throttled` forces prose reuse when incremental reuse is engaged (offseason + no new trades). Tests: `api/tests/test_llm_throttle_gate.py`.
2. **Shipped:** signature fixes — int-typed `FIELD_BANDS` fields band like floats; string lists sort in the signature. Tests: `tests/test_signature_coarsening.py`. Note: any coarsening change moves existing hashes → one-time full regen on the next ungated pass (expected, like a prompt-version bump).
3. **Tunable, no deploy:** `TRADE_GRADER_LLM_MIN_INTERVAL_SECONDS` via `railway variables --set` (set to 604800 in Aug 2026; **revert to default 72000 before the season** or in-season prose lags a week).
4. Batch API / prompt caching / model swaps: not worth it at post-fix volume — re-check only if in-season spend surprises.

## Manually triggered refreshes are the other cost source

Churn is the *background* cost. The foreground one is somebody — including you, verifying
a deploy — calling `GET /api/league/{id}/refresh` by hand. `force=true` bypasses every
lever above: the throttle, the offseason gate, and all skip-hash reuse. Measured Aug 2026
on the 11-owner league: **177 Haiku calls, ~$0.86, one run.** Without `force`, the same
call is usually free because reuse engages.

Never spend it just to prove a deploy is live — the runtime logs answer that. Spend it
only when the thing under test *is* the LLM path (a new writer, a reporter, a prompt
change), and say the number out loud before you run it. See the `railway-deploy` skill,
"Actually calling a gated API route", for the mechanics.

Since Aug 2026 these calls also POST to coach-web (`src/sleeper_dynasty/llm/usage.py`), so
a manual refresh shows up as a `public-dynasty` row in that dashboard's `llm_daily` —
useful as confirmation, and worth remembering before you read a spike there as organic.
