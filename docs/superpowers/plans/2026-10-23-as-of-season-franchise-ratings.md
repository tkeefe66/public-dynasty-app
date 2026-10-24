# As-of-season Franchise Ratings Implementation Plan

> Implement inline using superpowers:executing-plans and test-driven-development.

**Goal:** Selected seasons use dated franchise inputs; All preserves career ratings.

**Architecture:** Refresh persists versioned season inputs. One resolver scopes the
existing model for dashboard and leaderboard. Historical assets enter through a
validated file store; missing evidence produces explicit unavailability.

**Tech Stack:** Python/FastAPI/dataclasses/Pydantic, Next.js/TypeScript, pytest/vitest.

**Spec:** ../specs/2026-10-23-as-of-season-franchise-ratings-design.md

## Global constraints

- Never substitute current assets, later results, or zeros for missing history.
- Preserve All, format-specific weights, owner-continuity gates, and paid-call behavior.
- Use additive cache defaults with explicit unavailability; no silent stale math.
- Do not deploy or regenerate prose as part of implementation.

## Review focus

- Later-season mutations cannot change a saved historical grade.
- January cutoff dates belong to the preceding fantasy season.
- Missing, malformed, mismatched-owner, or future-dated assets are unavailable.
- Historical rows cannot show today's roster rank, window, draft capital, or weekly trend.
- Existing caches and incomplete current seasons must render useful records and clear status.

## Tasks

- [x] Add failing tests in api/tests/services/test_season_rating_scope.py for
  missing-history fallback, temporal isolation, format weighting, and consistent views.
- [x] Implement season_ratings.py: refresh construction, scope resolver, metadata;
  historical_rating_assets.py: validated source facts and explicit import interface.
- [x] Add ChainCacheEntry.season_rating_inputs; prove round trip, default,
  refresh population, and view fallback without invalidating existing career data.
- [x] Route franchise_redesign, aggregations, leaderboard through the resolver;
  remove unsupported current trends/prose from historical responses.
- [x] Add rating-scope metadata to responses and a reusable UI notice; revise
  tooltips and empty states, preserve records when historical grades are unavailable.
- [x] Run focused regressions, broader relevant suites, lint/typecheck/build,
  and mutation checks; inspect rendered UI; review diff and commit logical change.

## Verification

- API: 1,884 passed, 57 skipped. Engine: 1,388 passed. Web: 1,023 passed.
- TypeScript and production build passed. Web lint has one existing hook warning.
- New Python files pass Ruff; changed existing files checked against their baseline.
- Three deliberate mutations failed their regressions; restored sources pass.
- Local Chrome: All to 2024 to All, desktop and 390px mobile, no horizontal overflow.
- Independent review verified completed-season, rollover, and cutoff protections.
- Historical imports remain operator-verified; no backfill or deployment performed.

## Production release integration

Applied the ratings change to current production main without the separate,
unreleased owner-continuity review feature. Existing production owner identity
behavior remains unchanged. Revalidated this release tree: 1,872 API tests passed
(57 skipped), 1,021 web tests passed, production build/type checking passed,
new Python lint passed, and web lint retained its existing hook warning.
