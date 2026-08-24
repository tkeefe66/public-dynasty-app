# Sleeper Redraft Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Sleeper redraft leagues into the app and score them honestly — no Outlook pillar, no dynasty-priced trade values, no faked UI.

**Architecture:** A new pure engine module derives a `LeagueCapabilities` record from each league chain (format + three evidence-based booleans). It is stamped on `ChainCacheEntry` as a value-layer field alongside `league_phase`, then read at three seams: Franchise Rating picks a weight tree, the value layer picks a FantasyCalc value set, and the API omits the Outlook block so the existing frontend conditional drops the tab.

**Tech Stack:** Python 3.11 / FastAPI / dataclasses / pytest (backend), Next.js 14 / TypeScript / vitest (frontend).

## Global Constraints

- **Leagues are self-contained.** Nothing pooled, compared, ranked, or averaged across leagues. No cross-league storage, query, or surface.
- **`format` values are exactly** `"dynasty" | "keeper" | "redraft"`.
- **Weight-tree names are exactly** `"results_led" | "redraft_led"`. (`keeper_led` is deferred — do not create it.)
- **Keeper leagues score under `results_led`** in this build. Do not special-case them.
- **Never fall back to dynasty values** to fill gaps in the redraft value set. Unmatched players resolve to zero, matching existing behavior.
- **UI gating is absence, not empty state** (Agate rule). No "N/A" placeholders, no empty-state cards for unsupported sections.
- **Never render "KTC"** anywhere in `web/`. `tests/agate-rules.test.ts` enforces this.
- **No `SCHEMA_VERSION` bump.** The new cache field uses `field(default_factory=dict)` and every consumer falls back to full-dynasty capabilities on an empty dict.
- Backend tests: `pytest tests/` (engine) and `pytest api/tests/` (API) — **never bare `pytest` from root**, it breaks on the duplicate `tests` package name.
- Frontend tests: `cd web && npx vitest --config tests/vitest.config.ts run` — **never bare `npx vitest run`**, it silently uses no config and fails on JSX.

---

### Task 1: Capability derivation (pure engine module)

**Files:**
- Create: `src/sleeper_dynasty/engine/capabilities.py`
- Test: `tests/test_capabilities.py`

**Interfaces:**
- Consumes: `sleeper_dynasty.models.league.League` (field `league_type: int | None`).
- Produces: `LeagueCapabilities` dataclass (fields `format: str`, `future_picks: bool`, `roster_continuity: bool`, `multiyear_history: bool`), `derive_capabilities(league, *, chain_length, observed_pick_assets) -> LeagueCapabilities`, and `capabilities_to_dict(caps) -> dict` / `capabilities_from_dict(raw) -> LeagueCapabilities`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capabilities.py`:

```python
from sleeper_dynasty.engine.capabilities import (
    LeagueCapabilities,
    capabilities_from_dict,
    capabilities_to_dict,
    derive_capabilities,
)
from sleeper_dynasty.models.league import League


def _league(league_type):
    return League(
        league_id="L1", name="Test", season=2025, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", league_type=league_type,
    )


def test_type_2_is_dynasty():
    caps = derive_capabilities(
        _league(2), chain_length=3, observed_pick_assets=True)
    assert caps.format == "dynasty"
    assert caps.roster_continuity is True


def test_type_1_is_keeper():
    caps = derive_capabilities(
        _league(1), chain_length=2, observed_pick_assets=True)
    assert caps.format == "keeper"
    assert caps.roster_continuity is True


def test_type_0_is_redraft():
    caps = derive_capabilities(
        _league(0), chain_length=1, observed_pick_assets=False)
    assert caps.format == "redraft"
    assert caps.roster_continuity is False


def test_unknown_type_defaults_to_dynasty():
    """None/garbage must not silently demote an existing dynasty league."""
    for bad in (None, 7, -1):
        caps = derive_capabilities(
            _league(bad), chain_length=3, observed_pick_assets=True)
        assert caps.format == "dynasty"


def test_future_picks_is_evidence_based_not_type_based():
    """A dynasty league with pick trading off has no future_picks."""
    caps = derive_capabilities(
        _league(2), chain_length=3, observed_pick_assets=False)
    assert caps.format == "dynasty"
    assert caps.future_picks is False


def test_redraft_league_with_pick_trades_reports_future_picks():
    """Evidence beats the declared type in the other direction too."""
    caps = derive_capabilities(
        _league(0), chain_length=1, observed_pick_assets=True)
    assert caps.format == "redraft"
    assert caps.future_picks is True


def test_multiyear_history_needs_chain_longer_than_one():
    new_dynasty = derive_capabilities(
        _league(2), chain_length=1, observed_pick_assets=True)
    assert new_dynasty.multiyear_history is False
    old_dynasty = derive_capabilities(
        _league(2), chain_length=2, observed_pick_assets=True)
    assert old_dynasty.multiyear_history is True


def test_dict_roundtrip():
    caps = derive_capabilities(
        _league(0), chain_length=1, observed_pick_assets=False)
    assert capabilities_from_dict(capabilities_to_dict(caps)) == caps


def test_empty_dict_reads_as_full_dynasty():
    """Pre-feature cache entries must be unaffected."""
    caps = capabilities_from_dict({})
    assert caps == LeagueCapabilities(
        format="dynasty", future_picks=True,
        roster_continuity=True, multiyear_history=True,
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_capabilities.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sleeper_dynasty.engine.capabilities'`

- [ ] **Step 3: Write the implementation**

Create `src/sleeper_dynasty/engine/capabilities.py`:

```python
"""What a league supports, derived from its type plus observed evidence.

Pure — no I/O, no platform knowledge. The three booleans come from what the
data actually shows rather than what the league's declared type implies, so a
dynasty league with pick trading disabled reports no future picks and a
first-season dynasty league reports no multiyear history. That is also what
makes this portable: a non-Sleeper league can be described by asking the same
questions of its data.
"""

from __future__ import annotations

from dataclasses import dataclass

# Sleeper settings.type -> our format vocabulary. Anything else (None, an
# unknown int) falls back to dynasty: this app was dynasty-only until now, so
# an unrecognized value must never silently demote an existing league.
_TYPE_TO_FORMAT = {0: "redraft", 1: "keeper", 2: "dynasty"}
_DEFAULT_FORMAT = "dynasty"

# Formats whose rosters carry from one season to the next.
_CONTINUOUS_FORMATS = {"dynasty", "keeper"}


@dataclass(frozen=True)
class LeagueCapabilities:
    format: str              # "dynasty" | "keeper" | "redraft"
    future_picks: bool       # future draft picks are tradeable assets
    roster_continuity: bool  # rosters carry season to season
    multiyear_history: bool  # league chain is longer than one season


# What a cache entry written before this feature reads as. Full dynasty, so
# existing leagues are unaffected until their next refresh stamps the real one.
_LEGACY_DEFAULT = LeagueCapabilities(
    format=_DEFAULT_FORMAT,
    future_picks=True,
    roster_continuity=True,
    multiyear_history=True,
)


def derive_capabilities(
    league,
    *,
    chain_length: int,
    observed_pick_assets: bool,
) -> LeagueCapabilities:
    """Describe what ``league`` supports.

    ``chain_length`` is the number of seasons in the walked league chain.
    ``observed_pick_assets`` is whether any graded trade actually carried a
    draft-pick asset.
    """
    fmt = _TYPE_TO_FORMAT.get(league.league_type, _DEFAULT_FORMAT)
    return LeagueCapabilities(
        format=fmt,
        future_picks=bool(observed_pick_assets),
        roster_continuity=fmt in _CONTINUOUS_FORMATS,
        multiyear_history=chain_length > 1,
    )


def capabilities_to_dict(caps: LeagueCapabilities) -> dict:
    """Serialize for the cache entry / API layer."""
    return {
        "format": caps.format,
        "future_picks": caps.future_picks,
        "roster_continuity": caps.roster_continuity,
        "multiyear_history": caps.multiyear_history,
    }


def capabilities_from_dict(raw: dict | None) -> LeagueCapabilities:
    """Read back, falling back to full dynasty on empty/pre-feature entries."""
    if not raw:
        return _LEGACY_DEFAULT
    return LeagueCapabilities(
        format=str(raw.get("format") or _DEFAULT_FORMAT),
        future_picks=bool(raw.get("future_picks", True)),
        roster_continuity=bool(raw.get("roster_continuity", True)),
        multiyear_history=bool(raw.get("multiyear_history", True)),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_capabilities.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/engine/capabilities.py tests/test_capabilities.py
git commit -m "feat(engine): evidence-based league capability derivation"
```

---

### Task 2: Persist capabilities on the cache entry

**Files:**
- Modify: `api/app/services/chain_cache.py` (add field beside `week_recap`, ~line 99)
- Modify: `api/app/services/grader.py` (stamp beside `league_phase`, ~line 965 and ~line 1046)
- Test: `api/tests/test_capabilities_cache.py`

**Interfaces:**
- Consumes: `derive_capabilities`, `capabilities_to_dict` from Task 1.
- Produces: `ChainCacheEntry.capabilities: dict`, and the module-level helper `observed_pick_assets(resolved) -> bool` in `api/app/services/grader.py`.

**Note:** Run the `chain-cache-field` skill before starting — it owns the bump-vs-fallback rubric. The expected outcome is **no bump**: this is a value-layer field with a `default_factory` and a full-dynasty fallback, exactly like `league_phase`.

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_capabilities_cache.py`:

```python
from datetime import datetime

from app.services.chain_cache import ChainCacheEntry
from app.services.grader import observed_pick_assets
from sleeper_dynasty.engine.capabilities import capabilities_from_dict
from sleeper_dynasty.models.trade import (
    PickAsset, PlayerAsset, ResolvedTrade, Trade, TradeSide,
)


def _resolved(received):
    side = TradeSide(user_id="u1", received=received, given=[])
    trade = Trade(
        transaction_id="t1", league_id="L1", season=2025, week=3,
        traded_at=datetime(2025, 10, 1), sides={"u1": side},
    )
    return ResolvedTrade(trade=trade, sides={"u1": side})


def test_observed_pick_assets_true_when_a_pick_was_traded():
    rt = _resolved([PickAsset(season=2027, round=1, original_owner_user_id="u2")])
    assert observed_pick_assets([rt]) is True


def test_observed_pick_assets_false_for_player_only_trades():
    rt = _resolved([PlayerAsset(player_id="4034", name="Alvin Kamara")])
    assert observed_pick_assets([rt]) is False


def test_observed_pick_assets_false_for_no_trades():
    assert observed_pick_assets([]) is False


def test_observed_pick_assets_checks_given_side_too():
    """A pick only ever appears on the giving side in a 3-team leg."""
    side = TradeSide(
        user_id="u1", received=[],
        given=[PickAsset(season=2027, round=2, original_owner_user_id="u1")],
    )
    trade = Trade(
        transaction_id="t2", league_id="L1", season=2025, week=3,
        traded_at=datetime(2025, 10, 1), sides={"u1": side},
    )
    assert observed_pick_assets([ResolvedTrade(trade=trade, sides={"u1": side})]) is True


def test_entry_defaults_to_empty_capabilities():
    entry = ChainCacheEntry(league_id="L1")
    assert entry.capabilities == {}


def test_empty_capabilities_reads_as_full_dynasty():
    entry = ChainCacheEntry(league_id="L1")
    caps = capabilities_from_dict(entry.capabilities)
    assert caps.format == "dynasty"
    assert caps.future_picks is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_capabilities_cache.py -v`
Expected: FAIL — `ImportError: cannot import name 'observed_pick_assets'`

- [ ] **Step 3: Add the cache field**

In `api/app/services/chain_cache.py`, immediately after the `week_recap` field declaration (~line 99), add:

```python
    # What this league supports: {"format", "future_picks", "roster_continuity",
    # "multiyear_history"} (see engine/capabilities.py). Same tier as
    # league_phase — as-of-today value layer, always recomputed, never frozen.
    # Empty on pre-feature caches -> capabilities_from_dict returns full
    # dynasty, so existing leagues are unaffected until their next refresh.
    capabilities: dict = field(default_factory=dict)
```

Leave `SCHEMA_VERSION` at 16.

- [ ] **Step 4: Add the pick-evidence helper**

In `api/app/services/grader.py`, add at module level (near the other module-level helpers, above the `GraderService` class):

```python
def observed_pick_assets(resolved: list) -> bool:
    """Did any trade in this chain actually carry a draft-pick asset?

    Checked on the ORIGINAL trade, not the resolved sides — pick resolution
    rewrites a drafted PickAsset into a PlayerAsset, so resolved sides would
    under-report. Both received and given are checked: in a 3+ team leg a pick
    can appear on only one of them.
    """
    from sleeper_dynasty.models.trade import PickAsset
    for rt in resolved:
        for side in rt.trade.sides.values():
            for asset in (*side.received, *side.given):
                if isinstance(asset, PickAsset):
                    return True
    return False
```

- [ ] **Step 5: Stamp it during refresh**

In `api/app/services/grader.py`, immediately after the `league_phase = derive_league_phase(...)` call (~line 965-971), add:

```python
        # What this league supports (redraft/keeper/dynasty + evidence-based
        # booleans). Same value-layer tier as league_phase: always recomputed,
        # even on the incremental-reuse path.
        from sleeper_dynasty.engine.capabilities import (
            capabilities_to_dict, derive_capabilities,
        )
        _current_league = next(
            (lg for lg in chain if lg.league_id == current_league_id), None)
        capabilities = capabilities_to_dict(
            derive_capabilities(
                _current_league or chain[-1],
                chain_length=len(chain),
                observed_pick_assets=observed_pick_assets(resolved),
            )
        ) if chain else {}
```

Then in the `ChainCacheEntry(...)` construction (~line 1046), add `capabilities=capabilities,` immediately after `league_phase=league_phase,`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_capabilities_cache.py -v`
Expected: PASS — 6 passed

- [ ] **Step 7: Run the full backend suites for regressions**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS — no failures. A `SCHEMA_VERSION`-related failure here means the field was added wrong; re-check the `default_factory`.

- [ ] **Step 8: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add api/app/services/chain_cache.py api/app/services/grader.py api/tests/test_capabilities_cache.py
git commit -m "feat(api): stamp league capabilities on the chain cache entry"
```

---

### Task 3: The `redraft_led` weight tree

**Files:**
- Modify: `src/sleeper_dynasty/engine/gm_rating.py:33-48`
- Modify: `api/app/services/franchise_redesign.py:22-29,75-85`
- Test: `tests/test_gm_rating_redraft.py`

**Interfaces:**
- Consumes: `capabilities_from_dict` (Task 1), `ChainCacheEntry.capabilities` (Task 2).
- Produces: `REDRAFT_SIGNAL_WEIGHTS` and the `"redraft_led"` entry in `REDESIGN_PILLAR_WEIGHTS` (both in `gm_rating.py`); `signal_weights_for(model)` and `model_for(entry)` in `franchise_redesign.py`. `live_ratings` output gains a `"model"` key per owner alongside `"rating"` and `"pillars"`.

**Why the spread test matters:** if a tree's pillar weights sum to 0.8 instead of 1.0, every composite z is scaled by 0.8 and the whole league compresses toward 1500 — everyone drifts to C. Ratings are z-scored and 1500-centered, so the *mean* stays put and a mean-based assertion would pass while the bug shipped. Assert on spread.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gm_rating_redraft.py`:

```python
from sleeper_dynasty.engine.gm_rating import (
    REDESIGN_PILLAR_WEIGHTS,
    REDESIGN_SIGNAL_WEIGHTS,
    REDRAFT_SIGNAL_WEIGHTS,
    compute_gm_ratings,
)


def _owners():
    """Six owners with spread-out signals in every pillar."""
    out = {}
    for i in range(6):
        f = float(i)
        out[f"u{i}"] = {
            "results": {
                "championships": f, "playoff_depth": f, "made_playoffs": f,
                "final_seed": f, "points_for_rank": f,
            },
            "skill": {
                "trade_value": f, "trade_production": f,
                "draft_skill": f, "lineup_skill": f,
            },
            "outlook": {"roster_value": f, "draft_capital": f, "youth": f},
        }
    return out


def _sd(xs):
    mean = sum(xs) / len(xs)
    return (sum((x - mean) ** 2 for x in xs) / len(xs)) ** 0.5


def test_redraft_tree_exists_and_drops_outlook():
    tree = REDESIGN_PILLAR_WEIGHTS["redraft_led"]
    assert set(tree) == {"results", "skill"}


def test_every_pillar_tree_sums_to_one():
    for name, tree in REDESIGN_PILLAR_WEIGHTS.items():
        assert abs(sum(tree.values()) - 1.0) < 1e-9, name


def test_every_signal_tree_sums_to_one():
    for tree in (REDESIGN_SIGNAL_WEIGHTS, REDRAFT_SIGNAL_WEIGHTS):
        for pillar, sigs in tree.items():
            assert abs(sum(sigs.values()) - 1.0) < 1e-9, pillar


def test_redraft_signal_weights_have_no_outlook_pillar():
    assert "outlook" not in REDRAFT_SIGNAL_WEIGHTS


def test_redraft_preserves_results_to_skill_ratio():
    tree = REDESIGN_PILLAR_WEIGHTS["redraft_led"]
    dynasty = REDESIGN_PILLAR_WEIGHTS["results_led"]
    assert abs(
        tree["results"] / tree["skill"] - dynasty["results"] / dynasty["skill"]
    ) < 1e-9


def test_redraft_does_not_compress_the_grade_spread():
    """The renormalization guard. A tree summing to <1.0 would squash every
    owner toward 1500 while leaving the mean untouched."""
    owners = _owners()
    dyn = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["results_led"],
        signal_weights=REDESIGN_SIGNAL_WEIGHTS,
    )
    red = compute_gm_ratings(
        owners,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["redraft_led"],
        signal_weights=REDRAFT_SIGNAL_WEIGHTS,
    )
    dyn_sd = _sd([v["rating"] for v in dyn.values()])
    red_sd = _sd([v["rating"] for v in red.values()])
    assert dyn_sd > 0
    assert abs(red_sd - dyn_sd) / dyn_sd < 0.02


def test_redraft_output_has_no_outlook_pillar():
    red = compute_gm_ratings(
        _owners(),
        pillar_weights=REDESIGN_PILLAR_WEIGHTS["redraft_led"],
        signal_weights=REDRAFT_SIGNAL_WEIGHTS,
    )
    assert "outlook" not in red["u0"]["pillars"]
    assert set(red["u0"]["pillars"]) == {"results", "skill"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_gm_rating_redraft.py -v`
Expected: FAIL — `ImportError: cannot import name 'REDRAFT_SIGNAL_WEIGHTS'`

- [ ] **Step 3: Add the weight trees**

In `src/sleeper_dynasty/engine/gm_rating.py`, immediately after the `REDESIGN_SIGNAL_WEIGHTS` block (after line 43), add:

```python
# Redraft: no future picks and no roster carryover, so the Outlook pillar has
# nothing real to measure. Dropped entirely rather than zeroed — a zeroed
# pillar still consumes its weight and would compress every grade toward the
# 1500 base. Results and Skill are renormalized over 0.80, preserving their
# 0.50 : 0.30 ratio exactly.
REDRAFT_SIGNAL_WEIGHTS = {
    "results": {
        "championships": 0.35, "playoff_depth": 0.25, "made_playoffs": 0.15,
        "final_seed": 0.15, "points_for_rank": 0.10,
    },
    "skill": {
        "trade_value": 0.25, "trade_production": 0.20,
        "draft_skill": 0.30, "lineup_skill": 0.25,
    },
}
```

Then add to the `REDESIGN_PILLAR_WEIGHTS` dict (after the `"results_led"` entry on line 47):

```python
    "redraft_led": {"results": 0.625, "skill": 0.375},
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_gm_rating_redraft.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Wire model selection into the live read path**

In `api/app/services/franchise_redesign.py`, replace the `LIVE_MODEL` constant and `live_ratings` (lines 22-29) with:

```python
# The dynasty/keeper model. Keeper leagues intentionally score under this tree
# for now; a dedicated keeper_led tree is a deferred follow-on.
LIVE_MODEL = "results_led"
REDRAFT_MODEL = "redraft_led"


def model_for(entry: ChainCacheEntry) -> str:
    """Which weight tree this league scores under, from its capabilities.

    Pre-feature cache entries have empty capabilities, which read as full
    dynasty -> results_led. So existing leagues are unaffected.
    """
    from sleeper_dynasty.engine.capabilities import capabilities_from_dict
    caps = capabilities_from_dict(entry.capabilities)
    return REDRAFT_MODEL if caps.format == "redraft" else LIVE_MODEL


def signal_weights_for(model: str) -> dict[str, dict[str, float]]:
    """The signal tree matching a pillar tree. They must agree on which
    pillars exist — compute_gm_ratings indexes signal_weights by pillar name."""
    return REDRAFT_SIGNAL_WEIGHTS if model == REDRAFT_MODEL else REDESIGN_SIGNAL_WEIGHTS


def live_ratings(entry: ChainCacheEntry, *, year: Year = "all") -> dict[str, dict]:
    """The live Franchise Rating: full compute_gm_ratings output (pillars keyed
    results/skill/outlook, or results/skill for redraft) under this league's
    model. Single source of truth for the leaderboard, the dashboard standings,
    season ratings, and snapshots."""
    return compute_redesign_ratings(entry, model_for(entry), year=year)
```

Update the import at the top of the file to pull `REDRAFT_SIGNAL_WEIGHTS` alongside the existing `REDESIGN_PILLAR_WEIGHTS` / `REDESIGN_SIGNAL_WEIGHTS` import from `sleeper_dynasty.engine.gm_rating`.

Then replace `compute_redesign_ratings` (lines 75-85) with:

```python
def compute_redesign_ratings(
    entry: ChainCacheEntry, model: str, *, year: Year = "all"
) -> dict[str, dict]:
    """Full compute_gm_ratings output under the named redesign model.

    Each owner's row carries the model name that produced it. A rating pooled
    without knowing its tree is uninterpretable, and stamping it later would
    mean recomputing history.
    """
    trades = _filter_trades_by_year(entry, year)
    pillars = build_redesign_pillars(entry, trades)
    out = compute_gm_ratings(
        pillars,
        pillar_weights=REDESIGN_PILLAR_WEIGHTS[model],
        signal_weights=signal_weights_for(model),
    )
    for row in out.values():
        row["model"] = model
    return out
```

- [ ] **Step 6: Write the wiring test**

Create `api/tests/test_franchise_redesign_model.py`:

```python
from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import model_for, signal_weights_for


def test_pre_feature_entry_scores_as_dynasty():
    assert model_for(ChainCacheEntry(league_id="L1")) == "results_led"


def test_redraft_entry_selects_the_redraft_tree():
    entry = ChainCacheEntry(league_id="L1")
    entry.capabilities = {"format": "redraft", "future_picks": False,
                          "roster_continuity": False, "multiyear_history": False}
    assert model_for(entry) == "redraft_led"


def test_keeper_entry_scores_as_dynasty_for_now():
    entry = ChainCacheEntry(league_id="L1")
    entry.capabilities = {"format": "keeper", "future_picks": True,
                          "roster_continuity": True, "multiyear_history": True}
    assert model_for(entry) == "results_led"


def test_signal_and_pillar_trees_agree_on_pillars():
    """compute_gm_ratings indexes signal_weights[pillar]; a mismatch KeyErrors."""
    from sleeper_dynasty.engine.gm_rating import REDESIGN_PILLAR_WEIGHTS
    for model in ("results_led", "redraft_led"):
        assert set(REDESIGN_PILLAR_WEIGHTS[model]) <= set(signal_weights_for(model))
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_franchise_redesign_model.py tests/test_gm_rating_redraft.py -v`
Expected: PASS — 11 passed

- [ ] **Step 8: Run the full backend suites**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS. Any consumer asserting on `"outlook"` being present in a rating row needs updating to tolerate its absence.

- [ ] **Step 9: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/engine/gm_rating.py api/app/services/franchise_redesign.py tests/test_gm_rating_redraft.py api/tests/test_franchise_redesign_model.py
git commit -m "feat: redraft_led rating tree, selected by league capabilities"
```

---

### Task 4: Redraft trade values from FantasyCalc

**Files:**
- Modify: `src/sleeper_dynasty/api/fantasycalc.py:23-67`
- Modify: `api/app/services/grader_io.py:192-244`
- Test: `tests/test_fantasycalc_redraft.py`, `api/tests/test_redraft_values.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — this reads `League.league_type` off the chain directly, since values are pulled before capabilities are derived.
- Produces: `fetch_fantasycalc_values(*, dynasty: bool = True)` — same return shape as today (`dict[str, dict[str, int]]` mapping sleeper_player_id -> `{"superflex": int, "one_qb": int}`).

**This task is bigger than a parameter flip. Read this before starting.**

`isDynasty` is already a request parameter hardcoded to `"true"` (`fantasycalc.py:42`), and `isDynasty=false` returns the same schema with every row carrying `sleeperId`. But flipping it alone **would change almost nothing**, because of the precedence at `grader_io.py:227-244`:

```python
for pid, fc in fc_values.items():
    if pid in ktc_by_player_id:
        continue          # <-- KTC wins for every player it ranks
```

KTC is primary; FantasyCalc only fills players KTC did not rank. KTC is a dynasty valuation site with no redraft product, so for a redraft league the fix is to **invert the precedence**: FantasyCalc redraft becomes the sole player-value source and KTC is skipped entirely.

Two consequences to accept deliberately:

- **Pick value tables go empty for redraft.** `build_pick_value_table` / `build_pick_value_table_tiered` derive from the raw KTC blob, so skipping KTC leaves them empty.

  **CORRECTION (found in Task 4 review).** An earlier draft of this plan claimed redraft leagues have no draft picks and therefore nothing consumes these tables. **That is false** — Sleeper redraft leagues do trade draft picks (current-year, sometimes next-year). With the tables empty, any pick in a redraft trade prices at 0. Owner ruling: **disclose now, value later.** The coverage warning must state that draft picks are unvalued in redraft leagues; building redraft pick valuation (FantasyCalc has no pick values, so it would need ADP or a positional-tier heuristic) is a deferred follow-on with its own design.

- **The KTC snapshot store must be disabled for redraft chains.** `KtcSnapshotStore(cache_dir=cache_dir)` (`grader.py:449`) is scoped per *install*, not per league, and every dynasty league's refresh writes dynasty KTC into it. Left enabled, dynasty prices reach redraft grades through `compute_at_trade`, through `make_price_providers`/`compute_realized` (which **overwrite** `received_ktc` and the per-asset breakdown with snapshot prices), and through `value_extremes()`. Thread the redraft flag up and pass `snapshot_store = None`. Accepted cost: redraft leagues lose at-trade/aged valuation. Namespacing snapshots by valuation source and keying them per league were both considered and deferred.
- **Coverage is thinner and has no backstop.** Redraft returns ~200 players vs dynasty's ~474 (12-team, 1QB, PPR). Roughly adequate for a standard 12-team redraft roster (~192 spots); deep benches and IDP will have zero-valued players. **Do not fall back to dynasty values to fill the gap** — that reintroduces exactly the pricing this task exists to remove. Add a warning to `warnings` instead so the UI can disclose it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fantasycalc_redraft.py`:

```python
import httpx
import pytest

from sleeper_dynasty.api import fantasycalc


class _Recorder:
    """Captures the params of every GET without touching the network."""

    def __init__(self):
        self.params = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        self.params.append(params)
        return httpx.Response(
            200,
            json=[{"player": {"sleeperId": "4034"}, "value": 5000}],
            request=httpx.Request("GET", url),
        )


@pytest.mark.asyncio
async def test_defaults_to_dynasty_values(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    await fantasycalc.fetch_fantasycalc_values()
    assert all(p["isDynasty"] == "true" for p in rec.params)


@pytest.mark.asyncio
async def test_redraft_flag_flips_the_parameter(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    await fantasycalc.fetch_fantasycalc_values(dynasty=False)
    assert all(p["isDynasty"] == "false" for p in rec.params)


@pytest.mark.asyncio
async def test_return_shape_is_unchanged(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(fantasycalc.httpx, "AsyncClient", lambda **kw: rec)
    out = await fantasycalc.fetch_fantasycalc_values(dynasty=False)
    assert out == {"4034": {"superflex": 5000, "one_qb": 5000}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_fantasycalc_redraft.py -v`
Expected: FAIL — `test_redraft_flag_flips_the_parameter` errors with `TypeError: fetch_fantasycalc_values() got an unexpected keyword argument 'dynasty'`

- [ ] **Step 3: Add the parameter**

In `src/sleeper_dynasty/api/fantasycalc.py`, change the signature and docstring (lines 23-31) to:

```python
async def fetch_fantasycalc_values(
    *, dynasty: bool = True
) -> dict[str, dict[str, int]]:
    """Fetch FantasyCalc values keyed by Sleeper player_id.

    Args:
        dynasty: True for dynasty values, False for redraft. Redraft leagues
            must use redraft values — dynasty pricing carries a rookie/youth
            premium that is simply wrong when there is no next season.

    Returns:
        Dict mapping sleeper_player_id -> {"superflex": int, "one_qb": int}.
        Missing format values are absent (not None). Empty dict on network
        failure — graceful degradation matching the KTC fetcher.

    Note: the redraft set is thinner than the dynasty set (~200 players vs
    ~474). Players absent from it resolve to no value, the same as any other
    unmatched player. Do NOT fall back to dynasty values to fill the gap —
    that reintroduces exactly the pricing this exists to avoid.
    """
    log.info("Fetching FantasyCalc %s values", "dynasty" if dynasty else "redraft")
```

Then change the params dict (line 42) from `"isDynasty": "true",` to:

```python
                        "isDynasty": "true" if dynasty else "false",
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/test_fantasycalc_redraft.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Write the failing precedence test**

Create `api/tests/test_redraft_values.py`:

```python
from app.services.grader_io import is_redraft_chain
from sleeper_dynasty.models.league import League


def _league(league_type, season=2025):
    return League(
        league_id=f"L{season}", name="T", season=season, total_rosters=12,
        roster_positions=["QB"], scoring_settings={}, playoff_week_start=15,
        num_playoff_teams=6, status="in_season", league_type=league_type,
    )


def test_redraft_chain_detected():
    assert is_redraft_chain([_league(0)]) is True


def test_dynasty_chain_not_redraft():
    assert is_redraft_chain([_league(2)]) is False


def test_keeper_chain_not_redraft():
    assert is_redraft_chain([_league(1)]) is False


def test_empty_chain_defaults_to_not_redraft():
    """Never demote to redraft pricing without positive evidence."""
    assert is_redraft_chain([]) is False


def test_uses_the_latest_season_in_the_chain():
    """A league that converted formats is judged by where it is now."""
    chain = [_league(2, 2023), _league(0, 2025)]
    assert is_redraft_chain(chain) is True
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_redraft_values.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_redraft_chain'`

- [ ] **Step 7: Invert value precedence for redraft chains**

In `api/app/services/grader_io.py`, add at module level:

```python
# Mirrors engine/capabilities._TYPE_TO_FORMAT. Value sourcing happens inside
# pull_supporting_data, before capabilities are derived in grader.py, so it
# reads the league type directly rather than a cache entry.
_REDRAFT_TYPE = 0


def is_redraft_chain(chain) -> bool:
    """Is this league redraft *now*? Judged by the latest season in the chain,
    so a league that converted formats is priced by where it currently is.
    An empty chain is never redraft — never demote without positive evidence.
    """
    if not chain:
        return False
    latest = max(chain, key=lambda lg: lg.season)
    return latest.league_type == _REDRAFT_TYPE
```

Then in `pull_supporting_data`, replace the KTC + FantasyCalc block (lines 200-244) so redraft skips KTC entirely:

```python
    redraft = is_redraft_chain(chain)

    # KTC is a dynasty valuation site with no redraft product, so a redraft
    # league sources player values from FantasyCalc's redraft set alone. Pick
    # value tables come out of the raw KTC blob and stay empty — redraft has
    # no future picks, so nothing consumes them.
    ktc_values = {}
    if not redraft:
        try:
            ktc_values = await fetch_ktc_values()
        except Exception as e:
            log.warning("KTC unavailable: %s", e)
            warnings.append("KTC values unavailable")
            ktc_values = {}

    pick_value_table = build_pick_value_table(ktc_values)
    pick_value_table_tiered = build_pick_value_table_tiered(ktc_values)

    if snapshot_store is not None and ktc_values:
        from datetime import date
        snapshot_store.capture(ktc_values, date.today())

    try:
        fc_values = await fetch_fantasycalc_values(dynasty=not redraft)
    except Exception as e:
        log.warning("FantasyCalc unavailable: %s", e)
        warnings.append("FantasyCalc values unavailable")
        fc_values = {}

    raw_players = players if players is not None else await client.get_players()
    ktc_by_player_id: dict[str, KTCValue] = resolve_ktc_to_player_id(
        ktc_values, raw_players)

    fc_filled = 0
    for pid, fc in fc_values.items():
        if pid in ktc_by_player_id:
            continue
        sf = fc.get("superflex")
        one_qb = fc.get("one_qb")
        if sf is None and one_qb is None:
            continue
        p = raw_players.get(pid) if isinstance(raw_players.get(pid), dict) else None
        full = (p.get("full_name") if p else "") or pid
        ktc_by_player_id[pid] = KTCValue(
            name=full, normalized_name=full,
            position=(p.get("position") if p else "") or "",
            superflex_value=sf, one_qb_value=one_qb,
        )
        fc_filled += 1

    if redraft:
        # The redraft set is thinner than dynasty (~200 vs ~474 players) and
        # has no KTC backstop. Disclose rather than paper over it.
        log.info("Redraft chain: %d players valued from FantasyCalc", fc_filled)
        warnings.append(
            "Redraft values cover roughly the top 200 players; "
            "deep bench and IDP players are unvalued"
        )
    else:
        log.info("FantasyCalc filled %d players KTC didn't rank", fc_filled)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_redraft_values.py tests/test_fantasycalc_redraft.py -v`
Expected: PASS — 8 passed

- [ ] **Step 9: Run the full backend suites**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest tests/ -q && pytest api/tests/ -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add src/sleeper_dynasty/api/fantasycalc.py api/app/services/grader_io.py tests/test_fantasycalc_redraft.py api/tests/test_redraft_values.py
git commit -m "feat: redraft leagues price trades off FantasyCalc redraft values"
```

---

### Task 5: Surface capabilities on the API and drop the Outlook tab

**Files:**
- Modify: `api/app/models/league.py:133-155` (add `capabilities` to `DashboardResp`)
- Modify: `api/app/services/aggregations.py:657` (the only `DashboardResp(...)` construction)
- Modify: `api/app/services/owner_view.py:145-153` (omit `outlook_view` for redraft)
- Modify: `web/lib/api.ts` (type the new field)
- Test: `api/tests/test_capabilities_api.py`

**Interfaces:**
- Consumes: `capabilities_from_dict` (Task 1), `ChainCacheEntry.capabilities` (Task 2).
- Produces: `DashboardResp.capabilities: LeagueCapabilitiesResp`, and the TypeScript `LeagueCapabilities` interface in `web/lib/api.ts`.

**Key simplification:** `web/components/OwnerDeepDive.tsx:58` already renders the Outlook tab conditionally on `detail.outlook`. Omitting `outlook` from the owner response for redraft leagues drops the tab with **no frontend change** — and the component already handles a stale `?tab=outlook` deep link by falling back to `overview` (line 71).

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_capabilities_api.py`:

```python
from app.models.league import DashboardResp, LeagueCapabilitiesResp


def test_capabilities_defaults_to_full_dynasty():
    """A response built without capabilities must not demote a dynasty league."""
    caps = LeagueCapabilitiesResp()
    assert caps.format == "dynasty"
    assert caps.future_picks is True
    assert caps.roster_continuity is True
    assert caps.multiyear_history is True


def test_dashboard_resp_carries_capabilities():
    assert "capabilities" in DashboardResp.model_fields


def test_redraft_capabilities_serialize():
    caps = LeagueCapabilitiesResp(
        format="redraft", future_picks=False,
        roster_continuity=False, multiyear_history=False,
    )
    assert caps.model_dump() == {
        "format": "redraft", "future_picks": False,
        "roster_continuity": False, "multiyear_history": False,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_capabilities_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'LeagueCapabilitiesResp'`

- [ ] **Step 3: Add the response model**

In `api/app/models/league.py`, above `class DashboardResp` (line 133), add:

```python
class LeagueCapabilitiesResp(BaseModel):
    """What this league supports (see engine/capabilities.py). Drives which
    sections the UI renders at all — absence, never an empty state."""

    format: Literal["dynasty", "keeper", "redraft"] = "dynasty"
    future_picks: bool = True
    roster_continuity: bool = True
    multiyear_history: bool = True
```

Then add to `DashboardResp`, after the `week_recap` field (line 155):

```python
    # What this league supports. Defaults are full dynasty so pre-feature
    # caches and any un-populated path behave exactly as before.
    capabilities: LeagueCapabilitiesResp = Field(
        default_factory=LeagueCapabilitiesResp)
```

- [ ] **Step 4: Populate it in the dashboard response**

`api/app/services/aggregations.py:657` holds the only `DashboardResp(...)` construction. Add to it:

```python
        capabilities=LeagueCapabilitiesResp(
            **capabilities_to_dict(capabilities_from_dict(entry.capabilities))),
```

Add the imports at the top of that file: `capabilities_from_dict` and `capabilities_to_dict` from `sleeper_dynasty.engine.capabilities`, and `LeagueCapabilitiesResp` from `app.models.league` (beside the existing `DashboardResp` import).

- [ ] **Step 5: Omit the Outlook block for redraft**

`api/app/services/owner_view.py:146` declares `outlook_view: OutlookView | None = None` and line 153 assigns it inside an `if raw_ol:` guard; line 259 passes it as `outlook=outlook_view`. Add a redraft gate immediately after the assignment block ends — i.e. between the existing block and line 259:

```python
    # Redraft has no future picks and no roster carryover, so the Outlook tab
    # has nothing to say. Omitted entirely rather than empty-stated:
    # OwnerDeepDive.tsx:58 renders the tab only when detail.outlook is present,
    # and line 71 already falls back to overview on a stale ?tab=outlook link.
    from sleeper_dynasty.engine.capabilities import capabilities_from_dict
    if capabilities_from_dict(entry.capabilities).format == "redraft":
        outlook_view = None
```

- [ ] **Step 6: Type the field on the frontend**

In `web/lib/api.ts`, beside the other response interfaces, add:

```typescript
export interface LeagueCapabilities {
  format: "dynasty" | "keeper" | "redraft";
  future_picks: boolean;
  roster_continuity: boolean;
  multiyear_history: boolean;
}
```

and add `capabilities: LeagueCapabilities;` to the dashboard response interface.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_capabilities_api.py -v && pytest api/tests/ -q`
Expected: PASS

- [ ] **Step 8: Verify the frontend still builds and its guards pass**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty/web" && npx tsc --noEmit && npx vitest --config tests/vitest.config.ts run`
Expected: PASS — including `tests/agate-rules.test.ts`

- [ ] **Step 9: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add api/app/models/league.py api/app/services/aggregations.py api/app/services/owner_view.py web/lib/api.ts api/tests/test_capabilities_api.py
git commit -m "feat: surface league capabilities; redraft drops the Outlook tab"
```

---

### Task 6: Let redraft leagues in the front door

**Files:**
- Modify: `api/app/routes/me.py:32-33,60-71,89-95`
- Modify: `web/lib/api.ts:151-157` (add `format` to `SleeperLeague`)
- Modify: `web/app/leagues/add/page.tsx:144` (format chip)
- Test: `api/tests/test_discovery_formats.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — this reads `League.league_type` directly, since discovery happens before a league is ever graded.
- Produces: `SleeperLeague.format` on the discovery response and its TypeScript counterpart.

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_discovery_formats.py`:

```python
from app.routes.me import _format_for_type


def test_type_mapping_covers_all_three_formats():
    assert _format_for_type(0) == "redraft"
    assert _format_for_type(1) == "keeper"
    assert _format_for_type(2) == "dynasty"


def test_unknown_type_defaults_to_dynasty():
    for bad in (None, 9, -1):
        assert _format_for_type(bad) == "dynasty"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_discovery_formats.py -v`
Expected: FAIL — `ImportError: cannot import name '_format_for_type'`

- [ ] **Step 3: Stop filtering discovery to dynasty**

In `api/app/routes/me.py`, replace the `_DYNASTY_TYPE` constant (lines 32-33) with:

```python
# Sleeper settings.type -> our format vocabulary. Mirrors
# engine/capabilities._TYPE_TO_FORMAT; discovery runs before a league is ever
# graded, so it cannot read capabilities off a cache entry.
_TYPE_TO_FORMAT = {0: "redraft", 1: "keeper", 2: "dynasty"}


def _format_for_type(league_type) -> str:
    return _TYPE_TO_FORMAT.get(league_type, "dynasty")
```

Then replace the comprehension in `_discover_dynasty` (lines 60-69) with:

```python
        discovered = [
            {
                "league_id": lg.league_id,
                "name": lg.name,
                "season": lg.season,
                "total_rosters": lg.total_rosters,
                "format": _format_for_type(lg.league_type),
            }
            for lg in leagues
        ]
        _discovery_cache[key] = (time.monotonic(), discovered)
        return discovered
```

Rename the function from `_discover_dynasty` to `_discover_leagues` and update its call sites (`grep -n "_discover_dynasty" api/app/routes/me.py`). Update the `SleeperLeague` response model (lines 89-94) to add:

```python
    format: str = "dynasty"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty" && pytest api/tests/test_discovery_formats.py -v && pytest api/tests/ -q`
Expected: PASS

- [ ] **Step 5: Add the format chip to the add-league list**

In `web/lib/api.ts`, add `format: "dynasty" | "keeper" | "redraft";` to the `SleeperLeague` interface (line 151).

In `web/app/leagues/add/page.tsx`, beside the existing `lg.already_imported` branch (line 144), render the format so the user knows what they are adding. Match the surrounding Agate markup — no `rounded-`, no `shadow-`, uppercase mono label:

```tsx
<span className="font-mono text-[11px] uppercase tracking-wide text-[var(--ink-3)]">
  {lg.format}
</span>
```

Confirm `--ink-3` exists in `web/app/globals.css`; if not, use the muted ink token the neighboring elements already use.

- [ ] **Step 6: Verify the frontend**

Run: `cd "/Users/tomkeefe/Code Apps/public-dynasty/web" && npx tsc --noEmit && npx vitest --config tests/vitest.config.ts run`
Expected: PASS — including `tests/agate-rules.test.ts`

- [ ] **Step 7: End-to-end check against a real redraft league**

Run the app (`make dev-api` and `make dev-web`), sign in, and add a Sleeper **redraft** league. Confirm:
- it appears in discovery with a `redraft` chip
- refresh completes without error
- the dashboard renders; standings show Franchise letters
- an owner page shows **no Outlook tab**, and Overview shows two pillars
- no "KTC" appears anywhere

- [ ] **Step 8: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add api/app/routes/me.py web/lib/api.ts web/app/leagues/add/page.tsx api/tests/test_discovery_formats.py
git commit -m "feat: discover keeper and redraft leagues, labeled by format"
```

---

### Task 7: Update the project docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Document the capability model in CLAUDE.md**

Add a bullet to the "Key conventions" list, in the same voice as its neighbours:

```markdown
- **League capabilities (format gating):** `engine/capabilities.py::derive_capabilities` describes what a league supports — `format` (`dynasty`|`keeper`|`redraft`) plus three **evidence-based** booleans (`future_picks` from whether any trade actually carried a pick, `multiyear_history` from chain length, `roster_continuity` from format). Stamped at refresh and persisted as `ChainCacheEntry.capabilities` — value layer like `league_phase`, always recomputed, **no SCHEMA_VERSION bump**; empty on pre-feature caches and reads back as full dynasty. Three consumers: Franchise Rating picks a weight tree (`franchise_redesign.py::model_for` → `results_led` or `redraft_led`, the latter dropping Outlook and renormalizing Results/Skill over 0.80 — a tree summing to <1.0 silently compresses every grade toward 1500, so the guard test asserts on **spread**, not mean); the value layer picks a FantasyCalc set (`fetch_fantasycalc_values(dynasty=…)`; the redraft set is thinner, ~200 vs ~474 players, and unmatched players resolve to zero — **never fall back to dynasty values**); and `owner_view` omits `outlook` for redraft so `OwnerDeepDive.tsx` drops the tab. **Keeper leagues currently score under `results_led`**; a `keeper_led` tree is deferred. Leagues stay self-contained — nothing is pooled across them.
```

- [ ] **Step 2: Update the README's league-support description**

Find where the README describes which leagues are supported (`grep -n -i "dynasty league" README.md`) and update it to say Sleeper dynasty, keeper, and redraft leagues are supported, with redraft scored on a two-pillar Franchise Rating and redraft-priced trade values.

- [ ] **Step 3: Commit**

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
git add CLAUDE.md README.md
git commit -m "docs: league capabilities and redraft support"
```

---

## Deliberately not in this plan

Two things the spec mentions that no task implements. Both are intentional — recorded so a reviewer does not read them as gaps.

- **Lineage and became-grade stay on unconditionally.** The spec's `multiyear_history` bullet is an *exception* to the gating list, not a gate. A single-season chain renders single-hop journeys the engine already handles correctly, and an in-season flip is a real signal. No task touches lineage, which is the correct outcome. Only the cross-season *framing* would gate on `multiyear_history`, and there is nothing to change for that in a redraft league.
- **`future_picks == false` on a non-redraft league does not hide draft-capital rows.** In redraft the whole Outlook pillar is gone, so `draft_capital` disappears with it — covered. The uncovered case is a *dynasty or keeper* league whose members never trade picks: it keeps a `draft_capital` signal reading zero for everyone, which z-scores to a harmless zero contribution. Fixing it means per-league signal-tree surgery, which is disproportionate to a cosmetic row. Deferred with `keeper_led`.

## Post-merge outstanding

All 7 tasks landed and the final whole-branch review is clean. Three things survive it.

**Blocking — needs a real league.** No automated test drives a redraft league end-to-end through the running app. Discovery now returns redraft leagues to every user, so merging opens a path to production that has never been exercised live. One real Sleeper redraft league imported and refreshed closes it. Check: it appears in discovery with a `redraft` chip; refresh completes; standings render Franchise letters with no Window column; the owner page has no Outlook tab and Overview shows two pillars; the coverage warning renders; no "KTC" anywhere.

**Fixed after the final review** (`c4849db`).
- The orphaned `?sort=draft_capital_value` sort on a redraft league now routes into the existing "auto" fallback in `StandingsTable`.
- `OwnerRatingFacts.pillars` was annotated `list[dict]` while `blurb_gen.py:47` builds a mapping. Annotation and the persona's noun corrected; the packet shape is unchanged, so no `BLURB_PROMPT_VERSION` bump and no paid regen.

**Accepted, not fixed — owner decision.**
`DashboardSkeleton` uses the 9-track `FRANCHISE_GRID` unconditionally, so a redraft dashboard shifts 9→6 columns when data lands, contradicting the skeleton's own "nothing shifts when data lands" contract. It renders when `!data` (`DashboardClient.tsx:106`), before any response exists, so the client cannot know the league's format — every fix invents a new pre-load data channel for a first-paint nicety, on a component `agate-styling` lists as do-not-restyle. **Ruling: accept it.** Cosmetic, redraft-only, one frame on cold load, dynasty unaffected.

**Dropped, not deferred: redraft draft-pick valuation.** An earlier revision listed this as a follow-on. It isn't worth building. Redraft leagues trade only current-season picks pre-draft — a next-year pick means nothing once the roster resets — and `trade_history.py:238` resolves a pick into the player it drafted as soon as that draft completes. The empty pick table therefore only bites in the window before the draft, and the coverage warning now says exactly that instead of claiming picks are permanently worthless.

**Follow-on status** (updated 2026-08-11, after the four remaining items were worked):

| Item | Status |
|---|---|
| `keeper_led` weight tree | **Built** (`b7d07f8`) — Outlook keeps its 0.20, drops `youth`, survivors renormalized over 0.75 |
| Realized repricing for redraft | **Half-built** (`b7d07f8`) — snapshots namespaced by source, redraft accrues its own. Forward-only: FantasyCalc has no historical endpoint, so trades older than a league's first snapshot keep live pricing permanently |
| Cross-league owner grade | **Spec only** — `docs/superpowers/specs/2026-08-11-cross-league-owner-grade-design.md`. Recommends measuring demand before building |
| Yahoo redraft/keeper adapter | **Half-built, then blocked** (merged 2026-08-11, `767196b`) — plan at `docs/superpowers/plans/2026-08-11-yahoo-ingestion-protocol.md`. Tasks 1–5 shipped (platform protocol, Sleeper refactored onto it, id crosswalk, JSON primitives); Tasks 6–9 blocked on Yahoo granting Fantasy API access, a restricted API behind a separate application. The design spec is wrong on two counts — see the plan's corrections section |

## Verification

Before calling this done, run all of it and confirm output:

```bash
cd "/Users/tomkeefe/Code Apps/public-dynasty"
pytest tests/ -q
pytest api/tests/ -q
cd web && npx tsc --noEmit && npx vitest --config tests/vitest.config.ts run
```

Plus the manual end-to-end pass in Task 6 Step 7 — a real redraft league added, refreshed, and browsed. Unit tests cannot catch a wrong-but-plausible grade; only looking at one can.
