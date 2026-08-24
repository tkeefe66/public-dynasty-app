# Franchise Rating v2.1 — Growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Growth pillar — asset-share trajectory — moving the tree from `0.60 · Results + 0.40 · Assets` to `0.50 · Results + 0.30 · Growth + 0.20 · Assets`.

**Architecture:** Recover the waiver/free-agent *add* side of transactions that the Sleeper client currently discards, replay the whole transaction log forward from the startup draft to reconstruct who held what when, price both endpoints at today's values, and express each owner's change in share of total league asset value as two signals (all-time and recent).

**Tech Stack:** Python 3.11 / pytest (engine + API), Next.js 14 / TypeScript / vitest (web).

**Spec:** `docs/superpowers/specs/2026-08-16-franchise-rating-v2-design.md` — the "Growth (0.30) — asset-share trajectory" section is the authority, including its scoping probe.

## Global Constraints

- **Pricing is at today's values, for both endpoints.** There is no historical price data — FantasyCalc publishes no historical endpoint and the snapshot store only captures forward from the day it started. Growth is therefore explicitly **outcome-based**: an owner is credited for acquiring a player who *became* valuable, not for a trade that looked smart on the day. That is hindsight by construction and the methodology page must say so in those words.
- **Every `player_id` crossing the platform boundary is a Sleeper id.**
- **Absence beats a confident zero.** An owner whose history cannot be reconstructed gets no Growth signal, not a zero.
- Comments explain *why*, not *what*.
- Engine signal functions are pure — no I/O, no clock.
- **Run test suites in the FOREGROUND.** A backgrounded run never reports back; five implementers on the previous branch stalled forever on this.
- Engine: `pytest tests/ -q` from the worktree root. API: `cd api && pytest tests/ -q` (~2 min). Web: `cd web && npx vitest --config tests/vitest.config.ts run` (a bare `npx vitest run` uses no config and fails on JSX). Typecheck: `cd web && npx tsc --noEmit`.
- Do NOT verify imports with `python -c "import sleeper_dynasty"` — it resolves to a different checkout. `pytest` is homebrew python 3.11; neither `.venv` has pytest.

---

### Task 1: Recover the discarded adds

**Files:**
- Modify: `src/sleeper_dynasty/api/platform.py` (the `LeaguePlatform` protocol)
- Modify: `src/sleeper_dynasty/api/sleeper.py`
- Modify: `api/yahoo.py` or wherever `YahooAdapter` lives (stub is acceptable — Yahoo ingestion is blocked on API entitlement)
- Test: `tests/test_sleeper_client.py` (or the existing client test module)

**Interfaces:**
- Produces: `LeaguePlatform.get_adds(league_id: str) -> list[dict]` — one row per completed transaction carrying a non-empty `adds` map, mirroring `get_drops`'s shape.

**The defect being fixed.** `SleeperClient.get_drops` filters `type in ("drop", "waiver", "free_agent")` **and then requires a non-empty `drops` dict**. A waiver claim into an open roster spot has no drop side, so it is discarded before it is ever cached. Measured on the reference league: 143 of 760 drops (18.8%) reference a player the replay never saw arrive — that gap is these rows and nothing else.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_get_adds_keeps_add_only_transactions():
    # A waiver claim into an open roster spot has no drop side. get_drops
    # discards it, which is why 18.8% of drops in the reference league are of
    # players the replay never saw arrive.
    client = _client_with_transactions([
        {"type": "waiver", "status": "complete", "adds": {"1234": 3}, "drops": None},
        {"type": "free_agent", "status": "complete", "adds": {"5678": 7}, "drops": {"9999": 7}},
        {"type": "waiver", "status": "failed", "adds": {"4321": 2}, "drops": None},
        {"type": "trade", "status": "complete", "adds": {"1111": 1}, "drops": {"2222": 2}},
    ])
    rows = await client.get_adds("L1")
    added = {pid for r in rows for pid in (r.get("adds") or {})}
    assert "1234" in added          # add-only row survives
    assert "5678" in added          # paired row still counted
    assert "4321" not in added      # failed transactions excluded
    assert "1111" not in added      # trades are a separate call


@pytest.mark.asyncio
async def test_get_adds_and_get_drops_share_one_fetch():
    # Sleeper serves both from the same 18-week feed and the client memoizes
    # one league id. Calling both must not double the request count.
    client, counter = _counting_client()
    await client.get_adds("L1")
    await client.get_drops("L1")
    assert counter.weeks_fetched == 18
```

- [ ] **Step 2: Run to verify they fail** — `pytest tests/ -k get_adds -v`. Expected: `AttributeError: 'SleeperClient' object has no attribute 'get_adds'`.

- [ ] **Step 3: Implement.** Add `get_adds` to the protocol and the client, mirroring `get_drops` but requiring a non-empty `adds`. Reuse `_all_week_transactions` — it already memoizes one league id, which is what keeps the request count flat. Give the Yahoo adapter a matching method (raise `NotImplementedError` with a message naming the blocked entitlement if that matches how its other unimplemented members behave — read the file first).

- [ ] **Step 4: Run** — `pytest tests/ -q`, then `cd api && pytest tests/ -q`.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(platform): get_adds — recover the waiver adds get_drops throws away"
```

---

### Task 2: Persist adds in the raw bundle

**Files:**
- Modify: `api/app/services/grader_io.py` (the assembler that builds `trade_bundle`)
- Modify: wherever the raw-bundle `schema_version` is declared
- Test: the grader-io test module

**Why a schema bump.** Add-only rows never reached disk, so this is not a filter change against existing caches — the raw bundles must be re-fetched. Find the raw cache's own `schema_version` (distinct from `ChainCacheEntry.SCHEMA_VERSION`) and bump it.

- [ ] **Step 1: Write the failing test** — assert the assembled `trade_bundle` carries a `raw_adds` list, that an add-only transaction appears in it, and that bumping the schema invalidates a prior bundle.

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Implement.** Call `get_adds` alongside `get_drops`, store as `raw_adds`. Do not change `raw_drops`' shape — other consumers read it.

- [ ] **Step 4: Run both suites.**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(api): persist raw adds; bump the raw-bundle schema to force a re-fetch"
```

---

### Task 3: The roster-composition timeline

**Files:**
- Create: `src/sleeper_dynasty/engine/roster_timeline.py`
- Test: `tests/test_roster_timeline.py`

**Interfaces:**
- Produces: `replay_rosters(*, origin_picks, trades, adds, drops, roster_to_user_by_league, season_by_league) -> dict[str, dict[str, set[str]]]` — season → uid → set of held `player_id`s at that season's start. Exact signature is yours; the properties below are the requirement.

**Two rules the scoping probe established, both load-bearing:**
1. **Drops are applied before adds within a single transaction.** Sleeper keys a trade's `drops` by the *giving* roster; the reverse order reports a 100% false mismatch.
2. **Chain origin comes from the raw bundle's draft picks, not `ChainCacheEntry.drafted_picks`.** That field holds rookie drafts only (36 picks/season). The 2023 startup — 276 picks, 23 rounds — exists only in the raw bundle.

- [ ] **Step 1: Write the failing tests**

```python
def test_drops_are_applied_before_adds_within_one_transaction():
    # Sleeper keys a trade's `drops` by the GIVING roster. Applying adds first
    # sets the holder to the receiver, and the drop check then compares against
    # the giver and always misses — a 100% false mismatch.
    ...

def test_a_player_added_off_waivers_is_held_until_dropped():
    ...

def test_a_pick_follows_its_owner_through_a_trade():
    ...

def test_an_unknown_player_id_does_not_crash_the_replay():
    ...
```

Fill these in against the module you design. Each must fail before the implementation exists.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** the replay: seed from the origin draft, order every event by `created`, apply drops-then-adds per transaction, and track pick ownership alongside players.

- [ ] **Step 4: The round-trip test — this is the safety net for the whole pillar.**

Replaying chain-origin rosters forward through every trade, add, drop and draft pick must reproduce **today's** rosters exactly. Note the constraint the scoping probe found: **this cannot be written against the shared local cache**, because the current season's raw bundle is not in it — a naive end-to-end replay scored 66% purely from a missing season. Either build a full-chain fixture, or write it to run in-process during a refresh where every league's bundle is in hand. State which you chose and why.

If the round trip does not reach 100%, **stop and report** rather than tuning a threshold. A replay that is 97% right silently misattributes assets, and the whole pillar rests on it.

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(engine): roster-composition timeline, with a round-trip proof"
```

---

### Task 4: The Growth signals

**Files:**
- Create: `src/sleeper_dynasty/engine/growth_signals.py`
- Test: `tests/test_growth_signals.py`

**Interfaces:**
- Produces: `growth_signals(*, rosters_by_season, value_by_player, pick_value_by_key, owners, latest_played_season) -> dict[str, dict[str, float]]` returning `{"asset_share_delta", "asset_share_delta_recent"}`.

**Definitions:** asset value = rostered players plus owned future picks, all priced at **today's** values. Share = this owner's asset value ÷ the league's total. `asset_share_delta` is share now minus share at chain origin; `asset_share_delta_recent` is the same over the last two played seasons.

- [ ] **Step 1: Write the failing tests.** At minimum: shares sum to 1.0 at every point in time; `asset_share_delta` sums to ~0 across owners (it is zero-sum by construction — this is the strongest available check); an owner who never transacted has a delta near zero; an owner who acquired everything valuable has a positive delta and their counterparties negative ones; **an owner who joined mid-chain measures from their own first season, not chain origin** (charging a replacement manager for the previous owner's roster is the same defect the thin-evidence gate exists to prevent).

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `pytest tests/ -q`.**
- [ ] **Step 5: Commit**

```bash
git commit -am "feat(engine): asset-share trajectory — what you added, not what you hold"
```

---

### Task 5: Wire Growth into the refresh

**Files:**
- Modify: `api/app/services/rating_signals.py`
- Modify: `api/app/services/chain_cache.py` (`SCHEMA_VERSION` → 18)
- Test: `api/tests/services/`

**Placement:** the Growth signals describe **history**, not present state, so they belong in `outcome_signals` (the frozen rollup), not `outlook_signals`. But note the pricing is today's — so re-read `grader.py`'s reuse block and decide deliberately whether freezing them is right, given a frozen Growth number would stop tracking market movement through the offseason. **State your reasoning in the report; this is the judgement call of the task.**

**Use the `chain-cache-field` skill** before touching the schema.

- [ ] **Step 1: Write the failing test** — the new keys reach the persisted signal dicts, and no existing key is removed.
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement**, including the schema bump.
- [ ] **Step 4: Run both suites in the foreground.**
- [ ] **Step 5: Commit**

---

### Task 6: The tree moves to three pillars

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py`
- Modify: `api/app/services/franchise_redesign.py`
- Test: `tests/test_gm_rating.py`, `tests/test_gm_rating_guards.py`

**The trees:** dynasty and keeper become `{results: 0.50, growth: 0.30, assets: 0.20}`. Growth's weight comes **out of Assets** — a share *delta* is the better-measured version of what a share *level* stands in for. Redraft is unchanged: Results only, since nothing carries over to accumulate.

Growth's signal tree: `asset_share_delta` 0.60, `asset_share_delta_recent` 0.40.

- [ ] **Step 1: Write the failing tests** — every tree still sums to 1.0; every pillar has a matching signal sub-tree; redraft still has exactly one pillar; the existing additivity and flat-league guards still hold with three pillars.
- [ ] **Step 2–4: Run to fail, implement, run.** Existing tests asserting two pillars encode the tree being replaced — update those; a test asserting something *structural* is a real signal, so fix the code instead. Say which you did for each.
- [ ] **Step 5: Commit**

---

### Task 7: Recalibrate

**Use the `franchise-rating-calibration` skill.**

Adding a third pillar changes the composite sd, so `REFERENCE_COMPOSITE_SD = 0.6854` — measured for the two-pillar tree on 2026-08-17 — is stale the moment Task 6 lands.

- [ ] **Step 1:** Rebuild the reference league into an **isolated** cache dir with `ANTHROPIC_API_KEY` unset (the grader catches the writer's failure and skips prose, so this costs nothing and leaves the shared cache alone).
- [ ] **Step 2:** Measure the composite sd under the three-pillar tree and set the constant.
- [ ] **Step 3:** Check the letter distribution — at least five distinct letters across twelve owners, and no owner below D−.
- [ ] **Step 4:** Record the table in the spec, replacing the two-pillar one.
- [ ] **Step 5: Commit** both files together.

---

### Task 8: Surfaces

**Files:** `web/components/methodology/MethodologyContent.tsx` and `sample.ts`, `web/components/Leaderboard.tsx` (`PILLAR_ORDER`), `web/components/ownerdeepdive/OverviewTab.tsx` (`PILLARS`), `web/components/ownerdeepdive/util.tsx` (`SIGNAL_LABELS`), `src/sleeper_dynasty/engine/gm_rating_blurb.py`, `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`, `api/app/services/blurb_gen.py`

**This list is not optional and it is not cosmetic.** During v2, `PILLAR_ORDER` and `PILLARS` were left holding retired keys, and the Assets pillar — 40% of every grade — silently rendered nowhere on either the `/gm` breakdown or the owner page's "why this grade" card. The same omission here would hide Growth.

- [ ] Add `growth` to both pillar lists and `PILLAR_LABELS`/`_PILLAR_ORDER`.
- [ ] Add `SIGNAL_LABELS` for both new signals — **the same wording on the Python and TypeScript sides**. Suggested: "Asset Growth" and "Recent Growth".
- [ ] Update the methodology page: the new weights, what asset-share trajectory means, and — stated plainly — that it is priced at today's values and is therefore **hindsight by construction**.
- [ ] Bump `BLURB_PROMPT_VERSION` so cached blurbs regenerate against three pillars.
- [ ] Verify the `/gm` receipt and the Overview card both render three pillars, with a test that asserts the Growth label appears.
- [ ] Run all four checks. Commit.

---

## Self-Review

**Spec coverage.** Ingestion → Tasks 1–2. Timeline → Task 3. Signals → Task 4. Persistence → Task 5. Tree → Task 6. Calibration → Task 7. Surfaces → Task 8.

**Known risk, stated up front:** Task 3's round trip is where this plan fails if it fails. Everything downstream assumes the replay is exact, and a replay that is nearly right misattributes assets silently rather than loudly. If it will not reach 100%, the pillar should not ship.

**Open question deliberately left to Task 5:** whether Growth belongs in the frozen rollup. It describes history but is priced today, so freezing it stops it tracking the market. Decided by the implementer with reasoning recorded, not pre-empted here.
