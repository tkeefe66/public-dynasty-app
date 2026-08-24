# Cross-league owner grade — design

**Date:** 2026-08-11
**Status:** design only. Not built, not scheduled.

## Goal

Give a user one grade for themselves as an owner, aggregated across all their
leagues **of the same format**, rather than a separate verdict per league.

## Why this is hard, stated first

Every number in this product is league-relative by construction. Franchise
Rating z-scores each signal *within* a league, centres on 1500, and maps to a
letter (`engine/gm_rating.py`). An A- in a 12-team league of casual managers and
an A- in a league of sharks are the same number and not the same achievement.
**Averaging them is meaningless.** Any honest cross-league grade has to say what
it is measuring instead.

This is why the feature has stayed deferred through two sessions, and the design
below spends most of its length on that question rather than on plumbing.

## The two hooks that already exist

Both were deliberately left in place during the redraft build and cost nothing:

- **`ChainCacheEntry.capabilities`** — persisted per league, carries `format`.
  This is the bucketing key. Without it an aggregator would have to re-derive
  each league's format, including evidence-based booleans it cannot recover
  after the fact.
- **`model` on each rating row** — `results_led` / `keeper_led` / `redraft_led`,
  stamped in `franchise_redesign.compute_redesign_ratings` and surfaced as
  `GMRow.model`. Ratings from different trees are not on a common scale, so
  pooling without this is uninterpretable.

## What it must measure — pick one

Three candidate definitions. They are not variations on a theme; they answer
different questions and produce different rankings.

**A. Average percentile.** For each league, the owner's percentile within it;
average across leagues of one format. Reads as "how consistently do you beat
your peers." Immune to league size; blind to opposition strength — beating a
weak league 90th-percentile scores the same as beating a strong one.

**B. Volume-weighted rating.** Average the 1500-centred ratings, weighted by
seasons played in each league. Rewards a long record in one league over a thin
record in five. Still inherits the strength-blindness of A, and mixes scales
across leagues of different sizes.

**C. Opposition-adjusted (the honest one).** Estimate each league's strength
from the overlap graph — owners who appear in more than one league connect them,
the way chess ratings connect pools — then adjust. Correct in principle, and
useless in practice below a threshold of shared owners. Most users' leagues share
nobody, leaving every league an isolated component with no basis for comparison.

**Recommendation: A, stated narrowly.** Call it what it is — "you finish in the
top X% of your leagues" — not a global GM rating. It is computable today,
explainable in one sentence, and does not pretend to a precision the data cannot
support. Revisit C only if the overlap graph ever gets dense, which for a
single-user tool it likely never will.

## Shape

A new read-only aggregation over leagues the **requesting user** is a member of.

```
GET /api/me/owner-grade  ->  { buckets: [ { format, leagues: n, seasons: n,
                                            percentile: float, letter: str,
                                            leagues_detail: [...] } ] }
```

- **One bucket per format.** Dynasty, keeper, and redraft never combine. A user
  in two dynasty leagues and one redraft league sees two buckets, not one grade.
- **Membership-scoped, never global.** It reads only leagues the caller belongs
  to (`api/app/repositories/memberships.py`). There is no leaderboard of all
  users; that is a different product with different privacy implications.
- **A bucket with one league is suppressed**, not shown with a confident letter.
  "Across 1 league" is just that league's grade wearing a hat.

## What this does NOT change

The per-league invariant holds exactly as before: nothing about a league's own
standings, ratings, or leaderboard consults another league. The aggregation is a
read-side view over already-computed per-league ratings. `build_leaderboard`,
`live_ratings`, and every snapshot store stay league-scoped.

That boundary is the design's load-bearing property. If implementing this ever
requires reaching into another league during a league's own refresh, the design
is wrong — stop and re-read this paragraph.

## Cost and honest assessment

Small-to-medium in code: one repository query, one pure aggregation module, one
endpoint, one screen. The engineering is not the hard part.

**The hard part is that it may not be worth building.** For the common case —
a user with one league — it renders nothing. For a user with three leagues of
different formats, it renders three near-tautological buckets. The feature earns
its place only for someone in several leagues of the *same* format, which is a
minority of a single-user tool's users.

Recommend building it only when a real user has that shape, and measuring how
many do (the `page_events` telemetry can answer this) before writing any code.
