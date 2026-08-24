# Sub-Project B — Outcomes-Dominant GM Rating (Kickoff Brief)

**Date:** 2026-06-09
**Status:** Queued — start here with a `superpowers:brainstorming` session, then spec → plan → build.
**Not yet decided:** the modeling choices below are the brainstorm agenda, not conclusions.

## The goal (decided)

Evolve the GM Rating from "who produced the most points via trades" toward **"who built
the best season/franchise."** The user chose **outcomes-dominant**: season results (made
playoffs, final seed, championships) become the **primary** GM signal; trade production
becomes a **secondary** input and descriptive color.

> "Season final results are what really matters. We trade to move up the standings, build
> for the future, acquire picks — not to out-score the other trade party."

## What we already have to build on

- **Standings substrate (sub-project A):** `engine/standings.py` reconstructs as-of-week
  AND final regular-season standings (wins/losses/ties/pf/pa/rank) for the whole chain;
  persisted via `StandingsSnapshotStore`. Validated against Sleeper's authoritative record.
- **Playoff brackets:** `engine/playoff_phase.py::classify_playoff_phases` interprets
  Sleeper `winners_bracket` / `losers_bracket` — so we can derive playoff *finish* (champion,
  runner-up, round reached) and toilet-bowl outcomes per owner per season.
- **Five received-only metrics** per owner (post one-sided change): Trade Value (swing) +
  Total / Regular / Playoff / Toilet production (received-only tallies).
- **Existing rating machinery:** `engine/gm_rating.py` — z-scores each owner's metrics across
  the league, blends by `WEIGHTS`, scales to a 1500-centered rating (clamped 800–2200), pure
  + unit-tested. Currently `playoff 0.40 / regular 0.30 / value 0.22 / toilet 0.08` over the
  received-only inputs. Per-week snapshots drive the leaderboard trend.

## Brainstorm agenda (the open questions)

1. **Which season-outcome signals?** Candidates we can derive: made-playoffs (binary),
   final regular-season seed/rank, points-for rank, playoff finish (champion / runner-up /
   round reached), toilet-bowl finish. Pick the set; decide how to normalize (z-score like
   today, or fixed points per outcome).
2. **Outcomes vs. trade-production weight split.** "Dominant" ≈ outcomes 60–70%? Decide the
   blend and whether trade production stays a z-scored component or drops to display-only.
3. **The toilet sign** (the question that started thread A). With outcomes dominant, does
   toilet production matter at all? Likely **drop or negative**. Resolve here.
4. **Attribution / confounding.** Standings movement is brutally confounded (one trade vs.
   many, injuries, variance). Decision leaning: use **season-level** outcomes (not per-trade
   standings-delta attribution) as the outcome component, keeping trades as the "GM skill"
   signal — but confirm. A counterfactual sim is the heavy alternative; probably out.
5. **Season-centric vs. trade-centric identity.** The app is a trade grader; B makes the GM
   Rating season-aware. Confirm the rating becomes "how good a manager are you" (outcomes +
   trade skill), and how that reads on the `/gm` leaderboard.
6. **Injuries (future).** The user flagged wanting injury-aware analysis eventually — out of
   scope for B's first cut, but keep the outcome model extensible.

## Likely shape (to validate, not assume)

`gm_rating.py` grows an **outcomes component** (z-scored season-outcome signals per owner)
blended with the existing trade-production component, outcomes-weighted. New inputs sourced
from the standings substrate + bracket classification. Per-week snapshot trend continues.
Pure + unit-tested, same as today.

## First step next session

Run `superpowers:brainstorming` against this brief — resolve the agenda one question at a
time (start with #1 outcome signals and #3 toilet sign), then spec → plan → build.
