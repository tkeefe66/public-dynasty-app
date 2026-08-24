---
name: chain-cache-field
description: Use when adding, changing, or removing a field persisted on ChainCacheEntry (api/app/services/chain_cache.py), or when deciding whether a cache change needs a SCHEMA_VERSION bump.
---

# Evolving ChainCacheEntry

Wiring (dataclass field → compute in `GraderService.run` → surface in a view)
is derivable from the code. The decisions below are not — get these right.

## SCHEMA_VERSION: bump vs graceful fallback

Not every new field bumps. Decide by what a stale/default value costs:

| Situation | Call |
|---|---|
| Additive field where a briefly-empty default is acceptable (display data, selectors) | **No bump.** `field(default_factory=...)` + read-time fallback where it's surfaced. Precedent: `league_phase`. |
| Field feeds computation where empty/stale is silently wrong (rating signals, anything other math consumes) | **Bump.** Precedent: `lineup_signals` (v16). |
| Changed meaning/shape of an existing field | **Bump** — old blobs would be misread. |

Why no-bump is usually right: a bump makes `ChainCache.read` treat every prod
entry as a miss, so dashboards **409** until rebuild (the cold-start
contract). No-bump keeps serving, and `refresh_service.auto_refresh_loop`
re-warms member leagues ~2s after boot — the default-value window is
**minutes**, not the cache TTL.

Common mistakes: "the convention is bump on every new field" (it isn't — it's
the cost table above) and "without a bump the field stays empty for up to the
24h TTL" (wrong — the startup re-warm closes it in minutes).

## Placement in GraderService.run

Two tiers — pick by predicate, not by neighborhood:

- **Frozen rollups** (copied from `_reuse_prior` when offseason + no new
  trades): expensive recomputation over unchanged history. Adding here means
  also adding to the reuse-copy block *and* its empty else-branch.
- **As-of-today value layer** (always recomputed): cheap, derived from data
  `_pull_supporting_data` fetches every run anyway (`grades`,
  `dynasty_outlooks`, `roster_ranks`, `league_phase`). New fields usually go
  here.

Wrong placement silently freezes live data or wastes rebuild cost. Compute
best-effort (`try/except` + `log.exception`) so refresh never fails on the
new field.

## Test quartet (all four, every field)

1. **Round-trip** through `ChainCache` write/read (`tests.helpers.minimal_chain_cache_entry`).
2. **Pre-feature default**: entry constructed without the field → default.
3. **Grader stamps it**: extend `test_grader_service.py` fakes; prove the
   test bites by mutating the wiring out (set `PYTHONPYCACHEPREFIX` — macOS
   pycache gotcha in `~/.claude/CLAUDE.md`).
4. **Surface fallback**: the view/aggregation serves the fallback on a
   pre-feature entry.

Heads-up: `test_grader_service.py` tests run ~30s each (MagicMock clients
fall into real retry/backoff), so scope pytest to the tests you're adding
while iterating.
