# Draft Needs — Phase 5 Design

**Date:** 2026-08-17 · **revised after review the same day**
**Status:** proposed — ready to plan from
**Parent spec:** `docs/superpowers/specs/2026-08-17-draft-board-redesign-design.md` § Needs reconstruction
**Depends on:** phases 1–4, merged to `main` at `8b1b822` and deployed

## What this is

The draft board answers *who drafted well* against a baseline and against the field. It does not
answer **what the owner needed**. Phase 5 reconstructs each roster as it stood on draft day,
decides which starting slots were holes, and reports whether the draft addressed them.

**Scope, decided 2026-08-17.** Two verdicts, not three:

1. **Drafted into the need?** — the pick's position matches a hole open at draft time.
2. **Started at all?** — the pick recorded at least one start for that owner (`games_started`).

The parent spec's third verdict — *did the unfilled hole cost them?* — is **deferred**. It is the
most interesting claim and the least defensible: it compares a real player against a synthetic
baseline over a season the owner also spent making waiver moves. The first two are measurements;
the third is a model. Deferring it does not hollow out the rest — *"went in with QB and TE holes,
drafted a TE, and started him"* is a complete sentence.

**Note verdict 2 is weaker than the parent spec implied**, deliberately. See § Verdict 2 below.

**Surface:** a new **"Going in"** panel on the league draft board, below Picks. One row per owner.
It adds no column to any existing table — the Owners table has **2px** of slack under the 910px
gate and Picks has 6px.

## The premise, measured

Both load-bearing claims were probed against the real league (`Example League`) during review.
Neither is speculative any more.

### The protocol gap is real — 16% of events are invisible

`LeaguePlatform` (`api/platform.py:93-103`) exposes only two transaction feeds, and both are
filtered views built for other purposes:

| Method | Filter |
|---|---|
| `get_trade_transactions` | `type == "trade"` and `status == "complete"` |
| `get_drop_transactions` | non-trade, complete, **and `tx["drops"]` non-empty** (`sleeper.py:260`) |

**An add that drops nobody passes neither filter.** Measured:

| League | total transactions | complete non-trade with **no drops** |
|---|---|---|
| 2025 (`1191785397019561984`) | 400 | **63 (16%)** |
| 2026 (`9000000000000000001`) | 128 | **14 (11%)** |

A reconstruction from the existing feeds drifts low, silently, and worst on the deepest-rostered
teams — the ones most likely to have an open spot to add into.

`SleeperClient.get_transactions(league_id, week)` exists (`sleeper.py:187`) but is deliberately
**not** on the Protocol. Reaching past the protocol into the client is the platform-encoding leak
the protocol exists to prevent, so phase 5 adds a method.

### The week-range risk is CLOSED — Sleeper files offseason moves under leg 1

`_all_week_transactions` fetches `range(1, 19)` (`sleeper.py:235`). The concern was that a May
rookie draft is reconstructed almost entirely from Feb–July moves that might fall outside it.

Probed weeks −1 through 22 on the 2025 league:

```
by path week: {-1:0, 0:0, 1:116, 2:12, ... 17:5, 18:0, 19:0, 20:0, 21:0, 22:0}   total 400
by month:     {02:6, 03:1, 05:57, 06:11, 07:6, 08:24, 09:47, 10:107, 11:83, 12:58}
(path week, leg) pairs always equal
```

**All 105 pre-season 2025 moves sit inside week 1's 116 rows**, including the 57 in May the parent
spec cites. Weeks 0 and negative return empty; nothing past 18. The 2026 league is the same shape.
`api/tests/test_grader_service.py:331` already encodes this (`"leg": 1`, a May-dated `created`).

That is the negative control: the month the parent spec names was picked deliberately and the
fetch returns it. **No probe task is needed; `range(1, 19)` is correct.**

Also measured: `status_updated`/`created` is present on **100% of 528 transactions** across both
seasons. The "a transaction with no usable timestamp is skipped, never guessed at" rule stays as
a defensive invariant, but **do not build a skip counter for the UI** — it would always render 0.

## The protocol method

```python
async def get_roster_transactions(self, league_id: str) -> list[dict]:
    """Every COMPLETED roster-changing transaction — adds and drops, trades
    included. The two existing feeds are filtered views for other purposes;
    this is the unfiltered one reconstruction needs.

    `status == "complete"` only: the 2025 feed carries 28 failed waivers, and
    a failed claim never touched a roster.
    """
```

Sleeper's implementation is a third filter over `_all_week_transactions`, whose single-slot memo is
exactly why a third caller is safe.

**Three edits the method drags with it**, each a named plan step:

- **`tests/helpers.py:27` `_DERIVED_FROM_GET_TRANSACTIONS`** must gain the new name, or every
  double wired through `wire_transaction_protocol` — CLAUDE.md's sanctioned path — silently lacks
  the method.
- **`tests/test_platform_protocol.py:42-47`** has a hardcoded `required` set asserted with
  `required <= set(dir(...))`. It will not fail when the method is missing from the set; it will
  just stop guarding it. Add the name.
- **There is no `YahooAdapter` class in the repo yet** — only a docstring reference in
  `platform.py`. Nothing to raise `NotImplementedError` from. Adding the method to the Protocol is
  what makes the gap visible **when that adapter is written**.

`isinstance(SleeperClient(), LeaguePlatform)` keeps passing, since `SleeperClient` implements it.

## The fetch path — not free as wired

The Sleeper *client* implementation is free. **The pipeline is not.**

`trade_history.py:361-366` caches the whole trade bundle in `LeagueRawCache` for any league with
`status == "complete"`. For a sealed season the two existing feeds are never called — no HTTP, and
`_all_week_transactions`' memo is never reached. A `get_roster_transactions` called from elsewhere
triggers a **fresh 18-week walk per sealed league-season**, the exact doubling the memo exists to
prevent, once per season across the chain.

**Fix:** add `raw_roster_txs` to the bundle at `trade_history.py:387-394`, beside `raw_trades` and
`raw_drops`, so it inherits both the memo and the sealed-league cache.

**The trap this opens, and its sanctioned fix.** `league_raw_cache.py:60-68`'s `read_trade_bundle`
has no version field, so every already-written sealed-season file returns a bundle **missing the
new key** — and the reconstruction reports zero roster transactions with no error. The pattern for
this already exists one file over: `grader_io.py:142`'s `if cached is not None and
"winners_bracket" in cached` — a key-presence guard that treats a stale bundle as a miss. Use it.

## Roster as of a date

New pure module `engine/roster_asof.py`. Transactions in, roster out, no I/O.

**The seed is `supporting["matchups"]`, not a `/rosters` fetch.** `get_rosters(prior_league_id)`
returns Sleeper's **live** state, not an as-of-final-week snapshot — for a rolled-over dynasty
league it may already reflect offseason moves, which the reconstruction would then apply a second
time. Instead take the highest week present for the prior season's league id, per roster, from the
`"players"` array each matchup entry already carries (`grader_io.py:122-129`), and map
`roster_id → owner` via `roster_to_user_by_league` (`grader_io.py:301-302`). Genuinely the
final-week roster, already owner-mappable, already chain-aware, and no fetch.

Then apply every completed transaction with `status_updated`/`created` **on or before** the draft
date, in timestamp order, across both the prior and current league ids.

- Owner-keyed, not roster-id-keyed — roster ids are not stable across a chain
  (`standings_snapshot_store`'s precedent).
- A transaction with no usable timestamp is skipped, never guessed at. Defensive only; see above.

Parent-spec validation for 2025-05-16: **12 rosters, 362 transactions applied, sizes 18–24.**

## Quality at that date

Counts are not need: one QB for one QB slot is "covered" and fragile. Quality comes from the
**`dynasty-overall` ECR board** — `ecr_type = "do"`, or `"dsf"` for superflex — dated on-or-before
the draft, from the same DynastyProcess parquet and crosswalk phase 1 built. No new dependency.

**Reuse, corrected.** `resolve_board(boards, drafted_on, max_age_days)` (`rookie_board.py:103-107`)
is **already generic** — it takes parsed boards and never sees an `ecr_type`. The function that
hardcodes `ROOKIE_ECR_TYPE` is **`parse_latest_board` (`rookie_board.py:75`)**; `parse_boards`
(`:38`) is generic. Generalise `parse_latest_board`, not `resolve_board`.

**`MAX_BOARD_AGE_DAYS = 60` does not transfer.** Its 60 is justified by a rookie-class argument —
a board from a *different* rookie class is ~9 months away, so 60 days separates "stale" from
"wrong class". For `do`/`dsf` an old board is merely stale, never about different players. The
parameter already exists on `resolve_board`; pass a different value and say why in the docstring.

**`RookieBoardStore` generalisation is larger than "the same treatment":**

- `_SUBDIR = "rookie_ecr"` (`:32`) and `_PACKAGED` (`:34`) both need parameterising.
- **The pin key collides.** `_pin_path(draft_id)` is `{dir}/{draft_id}.json`, and `resolve_for_draft`
  pins **write-once** — so a rookie and a dynasty-overall board for the same draft would overwrite
  each other **permanently**. The subdir must differ. This is the same class of poison the
  `capture_daily` empty-refusal (`:60-68`) exists to prevent.
- **`dsf` is a third file**, since superflex-ness is per-league and one install may serve both.
- **Size: ~10× the rookie set.** Rookie is 309 boards × ~94 entries = 29,082 → 74KB gzipped.
  Dynasty-overall is 360 boards × 751–956 → **~300,000 entries, roughly 700–800KB gzipped for
  `do` alone, ~1.5MB with `dsf`.** Still fine to commit, and `pyproject.toml:35` already globs
  `data/*.json.gz` so no packaging change is needed — but state the number, because the parent
  spec was careful to state 74KB and this is an image-weight input.
- **A generalised extraction script is real, unlisted work.** `scripts/extract_rookie_boards.py`
  hardcodes `ROOKIE_ECR_TYPE` (`:37`) and `OUT` (`:41`).

**Superflex detection** is `SUPER_FLEX in roster_positions` (`models/league.py:12`). Note **this
league has no `SUPER_FLEX`**, so the `dsf` branch has no real-data test subject — it must be
covered by a synthetic fixture and flagged as unverified against production.

**The two phase-1 traps carry over verbatim:** use the **`.parquet`**, never `db_fpecr.csv.gz`
(frozen at 2025-08-08 and over GitHub's 100MB cap while gunzipping cleanly); and R's literal
`"NA"` must be filtered or it becomes a catch-all key.

## Defining a hole

Fill each starting slot from the reconstructed roster by draft-day ECR using
`engine/lineup.py::solve_optimal_lineup(roster_positions, players)`, reused so FLEX handling stays
identical to the lineup-skill signal.

Four things that will each produce a wrong answer silently:

1. **ECR is a rank; the solver wants a value.** It sorts `reverse=True` on the float
   (`lineup.py:73-75`) and takes the first eligible. Raw ECR in means the *worst* players start.
   Invert it. This gets its own test.
2. **Discard the returned total.** It becomes a sum of inverted ranks and means nothing — `starters,
   _ = solve_optimal_lineup(...)`, matching `outlook.py:124`.
3. **Strip `K` and `DEF` from `roster_positions` before the solve.** `solve_optimal_lineup` filters
   only `BENCH_SLOTS = {"BN","IR","TAXI"}` (`lineup.py:36,62`). Pass the list verbatim with no
   K/DEF players in the map and those slots come back empty — and an empty slot is trivially below
   any replacement line, so **every owner gets two permanent phantom holes**.
4. **Define the sentinel for a player absent from the ECR board.** `outlook.py:120-123` drops
   unmapped players entirely; here that empties the slot and manufactures the same phantom hole.
   An unranked rostered player must rank worse than every ranked player but better than nobody.

> A slot is a **hole** if the player filling it ranks below the league's replacement line at that
> position.

The replacement line is computed **from the league itself** — for a 12-team league starting one QB,
the 12th-best QB across all 12 reconstructed rosters. No external constant, no assumed league size,
and it moves with the league's own depth.

**K and DEF are excluded** as holes: `dynasty-overall` does not meaningfully rank them, they are
streamed, and no rookie draft addresses them. **Bench slots are not holes** — `BN`/`IR` are skipped.

**Greedy is optimal for this league.** Live `roster_positions` on all three seasons is
`['QB','RB','RB','WR','WR','TE','FLEX','FLEX','K','DEF','BN'×10]`. The eligibility sets are not a
total order (the docstring at `lineup.py:9-11` is loose — `{QB}` and `{RB}` are disjoint) but they
are a **laminar family**: every pair is nested or disjoint, which is the actual sufficient
condition. No caveat applies here.

## The two verdicts

**1. Drafted into the need?** For each of the owner's picks in that class, does the player's
position match a slot that was a hole at draft time. A pick at a position with no hole is **not a
failure** — it may be the best player available, which the Verdict column already judges. This
claim is descriptive.

**2. Started at all?** From `games_started`, already computed and owner-gated
(`draft_results.py:68-87`), so already correct about a player traded away mid-season.

**Why not "started at that slot", as the parent spec says.** `started_games_while_on_roster`
returns an **int count** — `if pid in (entry.get("starters") or []): count += 1`. It carries no
slot, and neither does `DraftBoardPick.games_started` (`models/league.py:279`). Slot *is*
recoverable, since Sleeper's `starters` array is index-aligned to `roster_positions`, but nothing
computes or retains it, and a FLEX-started RB drafted into an RB hole would need its own rule.
**Reduced deliberately rather than scoped as free work it isn't.** Restoring the slot-level
reading is a follow-on.

Both verdicts are **display-only and must never feed Franchise Rating.** Needs is inferred, not
measured — it rests on a reconstruction, a third-party ranking, and a replacement line. The moment
an inference feeds a rating, staleness becomes silently wrong and the cache rubric demands a
`SCHEMA_VERSION` bump. This is the same reasoning that kept the rookie ECR baseline out of the
rating in phase 1.

## The "Going in" panel

A fourth section on the league draft board, below Picks. One row per owner:

| Owner | Holes going in | Drafted into | Started |
|---|---|---|---|
| Mikey | QB · TE | TE | 1/1 |
| Dan | RB | — | — |
| Sam | — | — | — |

- **`Started` is a fraction, not a yes/no.** An owner with two picks into two different holes, one
  started and one not, has no cell in a scalar column. `1/2` reads correctly and degrades to `—`
  when the owner drafted into no hole.
- **An owner with no holes renders `—`, not an empty row.** "Went in with a complete starting
  lineup" is a real finding and must not read as missing data.
- Holes listed by position, most-severe first (furthest below the replacement line).
- Mobile is an `EntryCard` per owner; any interaction drives both bodies from one array.
- No colour on the verdicts beyond the sanctioned tone tokens — a hole is not a failure.

**Width.** The grid is cut against the **real** budget, not the breakpoint:
`910 − 48px Shell padding − 2px Panel border = 860px`. `minWidthPx`
(`web/tests/draft-columns.test.ts:78-90`) further charges 10px per gap and 28px cell padding, so a
four-column grid has **`860 − 30 − 28 = 802px`** of actual track budget. The new grid goes into the
same `WIDTH_GATE_BUDGET_PX` test as every other template.

## Cache

**Value layer, always recomputed — NOT a frozen rollup.** (Revised; the first draft said frozen.)

Two reasons, either sufficient:

**The freeze predicate keys on trades only.** `grader.py:553-566` reuses when
`not scoring_in_progress(...) and not new_transaction_ids(...)`, and `refresh_delta.py:28-31`
derives ids solely from `rt["trade"]["transaction_id"]`. Adds, waivers, drops and **a completed
draft** do not invalidate the freeze. A rookie draft completing in May lands squarely in the
offseason window: `drafted_picks` is value-layer so the new class appears on the board
**immediately**, while a frozen needs blob would be copied from an entry predating the draft and
have no entry for that season. The panel would be missing for the newest class until a trade lands
or someone forces a rebuild — during exactly the draft window where it is the point. That is the
same-response-disagreeing-with-itself failure the parent spec's shared-`scored`-list rule exists to
prevent.

**The cost premise was right about the engine compute, and wrong about the whole stage.**
Measured, `engine/draft_needs.py`'s own work is ≤528 dict operations, one board lookup, and 12
lineup solves of O(10 slots × ~25 players) — microseconds, orders of magnitude cheaper than
`compute_production_series_payload`, which is what the frozen tier is calibrated for. **What this
number never covered is `get_roster_transactions`** (Task 1): a real 18-week walk per league id,
not a dict operation. Against the `chain-cache-field` rubric the *compute* is squarely "cheap,
derived from data `_pull_supporting_data` fetches every run anyway"; the *fetch* is not, and is
the reason the shipped implementation reconstructs **only the newest gradeable draft class**, not
every season on the chain (corrected below — the first draft of this section implied per-season
retention via `dict[int, list[...]]` keyed by season, which is not what shipped).

**No `SCHEMA_VERSION` bump.** Additive display data, `default_factory` plus read-time fallback —
the `league_phase` / `capabilities` precedent. A bump makes every prod entry a miss and 409s
dashboards until rebuild.

Compute best-effort (`try`/`except` + `log.exception`) so a refresh never fails on it. The
`chain-cache-field` test quartet applies: round-trip, pre-feature default, grader stamps it (proven
by mutating the wiring out), surface fallback on a pre-feature entry.

### Shipped scope: newest-only, and it actively DROPS the prior season — not just "doesn't add" it

This section originally implied the dict fills up one entry per season over time (`dict[int,
list[OwnerNeeds]]`, "keyed by season"). That is not what shipped, and the difference matters more
than a type nitpick.

Each refresh, `draft_needs` is rebuilt from `{}` and only the current newest gradeable draft class
is ever reconstructed and inserted. It is **never merged with the prior `ChainCacheEntry`'s**
`draft_needs`. The practical effect: the moment a new season's draft becomes the newest, the
*previous* season's already-computed, already-served panel disappears from the response — not
merely "no longer recomputed", but removed from what a viewer previously saw. A user who saw the
2025 "Going in" panel loses it the refresh after the 2026 draft lands.

**Ruling: keep newest-only. Do not carry prior seasons forward.** Two independent reasons converge
on the same answer:

1. **Cost**, as above — per-season retention done naively would mean reconstructing (or at minimum
   re-fetching transactions for) every historical season on every refresh, which is chain-length
   multiplied fetch cost for seasons nobody asked about.
2. **Correctness, which is the stronger reason.** `draft_needs.py` has already needed two Critical
   fixes since this feature was scoped. Carrying an old season's computed answer forward across
   refreshes — rather than recomputing or dropping it — would mean serving output from
   since-corrected hole-detection logic indefinitely, with no way for a reader (or the code) to
   tell a stale-logic answer apart from a fresh one. There is no invalidation signal that fires on
   an engine-logic change. Given the choice between "old season's panel silently reflects
   yesterday's bug" and "old season's panel is silently absent", absence is the honest failure
   mode: it reads as "not shown" rather than "shown, and wrong".

**What a future fix needs, if "keep last season's panel visible after this season's draft" becomes
a real requirement:** BOTH of the following, not either alone —

- **True per-season persistence** — append newly-computed seasons to the stored dict instead of
  replacing it wholesale, so an old season's entry survives a refresh that reconstructs a newer one.
- **An invalidation signal tied to engine-logic changes** — something that lets a `draft_needs.py`
  correctness fix selectively invalidate previously-stored seasons (e.g. a hole-detection logic
  version stamped alongside each stored season's entry, compared against the running code's version
  at read time) rather than trusting old output forever. Persistence without this signal is exactly
  the failure mode the current rebuild-from-scratch design avoids.

Neither exists today. Shipping persistence without the invalidation signal would resolve the
user-visible "it disappeared" surprise at the cost of reintroducing the stale-logic problem this
design deliberately avoided — a regression, not a fix.

## API contract

Named explicitly, because a plan cannot be written without it.

**Corrected 2026-08-17 to match what shipped.** This section originally specified
`dict[int, list[OwnerNeeds]]` and a single `OwnerNeeds` type spanning the engine/API boundary.
Both were wrong: JSON object keys are strings, and one name for two types across a boundary is
how they drift (the pre-flight scan caught it before any code was written).

- **`ChainCacheEntry.draft_needs: dict[str, list[dict]]`** — keyed by season as a **string**,
  `default_factory=dict`, no `SCHEMA_VERSION` bump. Holds at most **one** season; see § Cache on
  the newest-only scope.
- **`OwnerNeedsResp`** (`api/app/models/league.py`) — the **wire** type, deliberately named apart
  from the engine's `OwnerNeeds` dataclass, with a mapping function at the boundary: `user_id:
  str`, `holes: list[str]` (positions, most-severe first), `drafted_into: list[str]`, `started:
  int`, `drafted_into_count: int`. The last two render as the `1/2` fraction — sending the pair
  rather than a formatted string keeps presentation in the frontend.
  It deliberately does **not** carry the engine dataclass's `starters_by_slot`: the API surface
  carries what the panel renders, and an engine type is free to be richer.
- **`DraftBoardResp.needs: list[OwnerNeedsResp] | None`** — `None`, not `[]`, when the league is
  ineligible **or the season is not the newest gradeable class**, so the frontend omits the panel
  rather than rendering an empty one. Assembled in `draft_board_view.py::build_draft_board`,
  which re-checks the capability gate at serve time rather than trusting what was stored.
- **The owner Draft tab does NOT get this in phase 5.** The league board is the surface; adding it
  to `owner_view` is a follow-on. Stated because the first draft was ambiguous.

## Format gating

Gated on **`capabilities.format == "dynasty"`** AND `capabilities.roster_continuity` AND
`multiyear_history`.

The `multiyear_history` condition is not redundant with `roster_continuity`. `roster_continuity` is
`True` for a **first-season startup dynasty league**, where there is no prior roster and every
roster is empty before the draft — identical to the redraft case. `multiyear_history`
(`chain_length > 1`) exists for exactly this.

**Absent, not blank**: the response omits the field and the frontend renders nothing, matching how
Outlook columns are dropped for redraft — backend gate at `aggregations.py:744`, frontend inferring
from data nullity (`StandingsTable.tsx:141-143`'s `hasOutlookColumns`) rather than a flag.

**Corrected during the pre-merge fix round: keeper leagues do NOT get it, and this section was
wrong to say they do.** The original reasoning — "two or three carried players is a real starting
position and a real set of holes" — is sound as a description of what the *question* means for a
keeper league. It says nothing about whether this *implementation* can answer it, and it cannot.
`roster_asof` (§ Roster as of a date) seeds from the prior season's final-week matchup roster and
mutates it only by applying completed transactions. That model is correct for dynasty, where every
roster spot not explicitly traded/dropped/added carries over as a transaction-free continuation.
It is **wrong for keeper**: a keeper league's annual reset — releasing everyone not designated a
keeper — is not represented by any transaction at all. Keepers re-enter the new season **through
the draft** (that is what `is_keeper` on a drafted pick means), so `roster_asof` has no signal to
act on and returns the entire ~20-25-man prior roster as the "draft-day" roster for every owner.
Every starting slot is filled by a plausible veteran, nothing falls below the replacement line, and
the panel renders "— · — · —" for the whole league — not absent, but confidently wrong, which is
worse. The exclusion is therefore about the reconstruction's capability, not about the underlying
question being meaningless for keeper leagues.

**What a future fix would need:** derive the actual kept set from the season's `is_keeper` picks
(rather than trusting `roster_asof`'s transaction-only view) and seed the reconstruction from that
kept set instead of the raw prior-season roster. Until that exists, keeper stays excluded — `format
== "dynasty"` is the gate, and `_CONTINUOUS_FORMATS` (`{"dynasty", "keeper"}` in
`engine/capabilities.py`) is intentionally left unchanged, since other features rely on it for
purposes where the transaction-only model is fine.

## Build order

Three seams, and they are dependent — not one lump:

1. **Data path.** `get_roster_transactions` on the Protocol + `SleeperClient`, `raw_roster_txs` into
   the trade bundle with the key-presence guard, `tests/helpers.py` and
   `tests/test_platform_protocol.py` updated. Nothing downstream can be fed real data until this
   lands.
2. **Board data.** Generalised `parse_latest_board`, the parameterised store with distinct subdirs,
   the generalised extraction script, and the committed `do`/`dsf` files. The hole definition
   cannot be tested against anything real until this exists.
3. **Engine, API, UI.** `roster_asof.py`, the hole definition, the two verdicts, the cache field,
   the response shape, the panel.

## Risks

**Inferred, not measured.** Everything else on this board is a measurement; a need is a judgment
built on three of them. Hence display-only, and hence copy that describes rather than grades.

**Commissioner roster edits do not appear as transactions.** A manually-adjusted roster drifts
silently with no way to detect it from the API. Accepted — state it in the module docstring so the
next reader does not treat the reconstruction as ground truth.

**`dsf` is untested against production data**, since this league has no `SUPER_FLEX`.

**ECR is a third-party ranking with an end date.** Same maintenance burden as the phase-1 rookie
boards: the committed history needs periodic regeneration, stated in the script's docstring.

---

# Revision — the replacement line becomes league-native

**Date:** 2026-08-17, after the first live look at the shipped panel
**Status:** proposed — supersedes § Defining a hole above

## Why

The panel shipped and was observed against the real league for the first time. It works
exactly as specified, and what it says is thin: **six of twelve owners render three
em-dashes.** Reproduced offline against real rosters — 6 of 12, matching production.

The data is correct. The measure is the problem, and in two distinct ways.

### 1. A binary verdict throws away what the engine already knows

`build_draft_needs` computes each owner's full starting lineup and every player's rank,
then reports only *below the line / not below*. Two owners in the same league:

| starting lineup (ECR) | holes reported |
|---|---|
| **1 · 3 · 4 · 5 · 13 · 18 · 19 · 54** | — |
| 43 · 45 · 55 · 57 · 59 · 75 · 97 · 103 | — |

The best roster in the league and a middling one are indistinguishable. Half the table is
blank not because nothing is true of those owners, but because the only thing the panel can
say about them is "not below one cut point".

### 2. ECR does not know this league's scoring

The line is drawn on `dynasty-overall` ECR — a national consensus that assumes roughly
standard scoring. **This league plays 6-point passing touchdowns.** Measured, both lines
computed over the same rostered pool:

| pos | ECR line | prior-season points, league scoring | gap |
|---|---|---|---|
| QB | Brock Purdy — **220 pts** | Baker Mayfield — **312 pts** | **92 pts** |
| RB | David Montgomery — 161 | Rhamondre Stevenson — 144 | 17 |
| WR | Jayden Higgins — 119 | Marvin Harrison — 128 | 9 |
| TE | Mark Andrews — 127 | Mark Andrews — 127 | 0 |

Quarterback is where an external ranking is least able to describe this league, and it is
off by 40%. Baker Mayfield sits at ECR 107 — nowhere near replacement by opinion — and
outscored the ECR-designated line QB by 92 points *under the rules this league actually
plays*.

The rest of this project grades on measurements. The hole definition is the one place it
grades on an opinion, and the opinion is calibrated for a different game.

## The revision

**The replacement line is drawn on the PRIOR season's points, in this league's own scoring.**

- For a draft in May 2026, that is the completed 2025 season — **known on draft day.** This
  is not the ADP hindsight trap: 2026 points do not exist when the draft happens and must
  never be used. The prior season is what the owner knew.
- Points come from `players_points` on the assembled matchups (`grader_io.py:125`), summed
  per player across the prior season. Already fetched; no new call.
- Demand is unchanged — the count of starters the league actually fields at each position,
  flex included.
- The line is the Nth-best **by points**, and each starter is valued the same way.

### Severity replaces the binary

A hole reports **how far below replacement it is, in points.** A slot at or above
replacement reports its margin too. Every row then says something:

| owner | going in |
|---|---|
| Amir | **TE −60 · RB −24** |
| Keegan | softest: QB **+8** |

`—` survives only for an owner with no reconstructable roster at all.

### ECR becomes the fallback, and a veto

Two jobs, both narrow:

1. **No prior-season points** — `players_points` only covers players rostered *in this
   league* that season, so an offseason free-agent pickup has none. Fall back to the ECR
   line for that player rather than reading him as zero, which would manufacture a hole.
   Rare on this surface by construction: the "going in" roster IS the prior season's final
   rosters, so nearly everyone has a full season of points.
2. **A veto for young players.** A second-year breakout who barely played scores like
   replacement level and is not a hole in a dynasty league. **A slot is a hole only if it is
   below replacement on points AND not rated above the line by ECR.** One sentence: *last
   year's production says replaceable, and the market does not disagree.*

The veto is the one place a blend earns its keep. Everywhere else, points decide.

## Consequences to accept

- **Two boards still ship.** ECR is no longer the primary measure but is still required for
  the fallback and the veto, so `dynasty_ecr`/`dynasty_sf_ecr` stay.
- **A league's first season has no prior points.** `multiyear_history` already gates the
  panel, so this is closed by an existing gate.
- **`OwnerNeedsResp` gains fields.** The margin per hole, and the softest slot with its
  margin. This reverses the pre-flight ruling that kept `starters_by_slot` off the wire —
  that ruling was right for what the panel rendered then, and is now the thing preventing it
  from rendering anything useful. The API carries what the panel renders; the panel now
  renders more.
- **Scoring-setting changes move the line.** A league that switches to TE-premium next year
  gets different lines for the same rosters. That is correct — and is exactly what ECR
  cannot do.

## What does not change

Demand counted from what owners actually field. K and DEF excluded. Bench slots are not
holes. The unranked sentinel (worse than everyone, better than nobody) still guards against
an empty slot reading as a phantom hole. Display-only; never feeds Franchise Rating.
