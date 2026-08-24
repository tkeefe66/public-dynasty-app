---
name: franchise-rating-calibration
description: Use when changing anything that feeds a Franchise Rating — weight trees or LETTER_BANDS in src/sleeper_dynasty/engine/gm_rating.py, signals in engine/gm_signals.py, engine/skill_signals.py or engine/draft_signals.py, or assembly in api/app/services/franchise_redesign.py. Also when adding or removing a signal from a pillar, adding a weight tree for a new league format, splitting or renaming pillars, tuning letter bands or SCALE/CLAMP, or when someone disputes a grade as too harsh, too generous, or wrong about an owner.
---

# Calibrating the Franchise Rating

Every signal is z-scored across the league before it is weighted, so **the
numbers in the weight dict are not the numbers that reach the screen.** A
weight change reasoned about on paper is a guess. Measure it against a real
league first — the harness below needs no API, no refresh, and no network.

Applies to whatever the current tree is (today: Results / Skill / Outlook via
`REDESIGN_PILLAR_WEIGHTS`). A split into Manager Grade + Roster Grade changes
the pillars, not one word of this.

## The offline harness

Local cache: `~/.sleeper-dynasty/cache/`.

| File | Holds |
|---|---|
| `chain_<league_id>.json` | serialized `ChainCacheEntry` — every persisted signal (`outcome_signals`, `outlook_signals`, `lineup_signals`, `grades`, `season_records`, `drafted_picks`) |
| `raw_<league_id>.json` | per-season `matchup_bundle`: `matchups` (list of `{week, roster_id, entry}`, `entry` carrying `team_points`/`opponent_points`/`starters`/`players`/`players_points`), `playoff_week_start`, `roster_to_user`, `roster_positions`, `winners_bracket`, `losers_bracket` |

One `chain_` file per entry-point league; the `raw_` files are the other
seasons in that chain. Week-level scores only exist in `raw_`.

Run with the repo venv from the repo root: `.venv/bin/python scratch.py`.
Scratch scripts go in the session scratchpad, never in the repo.

```python
import json, statistics, sys
from pathlib import Path

sys.path.insert(0, "api")
from app.services.aggregations import _filter_trades_by_year
from app.services.chain_cache import ChainCacheEntry
from app.services.franchise_redesign import build_redesign_pillars, live_ratings, model_for
from sleeper_dynasty.engine.gm_rating import (
    REDESIGN_PILLAR_WEIGHTS, REDESIGN_SIGNAL_WEIGHTS, compute_gm_ratings, rating_to_letter,
)

LEAGUE = "9000000000000000001"
blob = json.loads((Path.home() / f".sleeper-dynasty/cache/chain_{LEAGUE}.json").read_text())
# Filter the blob: it can carry keys the dataclass does not.
entry = ChainCacheEntry(**{k: v for k, v in blob.items()
                           if k in ChainCacheEntry.__dataclass_fields__})
name = {u: entry.owners[u].get("owner_name", u) for u in entry.owners}   # NOT display_name

def report(label, ratings):
    print(f"\n== {label} ==")
    for u, row in sorted(ratings.items(), key=lambda kv: -kv[1]["rating"]):
        zs = " ".join(f"{p}={d['z']:+.2f}" for p, d in row["pillars"].items())
        print(f"{name[u][:20]:22}{row['rating']:>6} {rating_to_letter(row['rating']):>3}  {zs}")
    for p in next(iter(ratings.values()))["pillars"]:
        sd = statistics.pstdev([r["pillars"][p]["z"] for r in ratings.values()])
        w = next(iter(ratings.values()))["pillars"][p]["weight"]
        print(f"  realized {p:9} sd={sd:.3f}  stated_w={w:.2f}  share_of_spread≈{w*sd:.3f}")

report(f"current ({model_for(entry)})", live_ratings(entry))

pillars = build_redesign_pillars(entry, _filter_trades_by_year(entry, "all"))
report("candidate", compute_gm_ratings(
    pillars,
    pillar_weights={"results": 0.45, "skill": 0.35, "outlook": 0.20},
    signal_weights={**REDESIGN_SIGNAL_WEIGHTS,
                    "skill": {"trade_value": 0.30, "trade_production": 0.25,
                              "draft_skill": 0.35, "lineup_skill": 0.10}}))
```

`live_ratings(entry)` is the production read path (`uid -> {"rating", "model",
"pillars"}`, each signal carrying `raw`/`z`/`weight`/`contribution`).
`compute_gm_ratings` on `build_redesign_pillars` output is how you score a tree
that has no name in `REDESIGN_PILLAR_WEIGHTS` yet. **Also print each signal's
raw league min/max/sd** from `pillars` — rule (c) needs it.

The reviewable artifact is the two tables side by side: full-league
rating/letter/per-pillar z under current vs candidate, plus realized pillar sd.

## Three rules, with the measured evidence

### (a) Stated weights are not realized weights

A pillar's z is a weighted **sum** of its signal z-scores. Independent signals
partly cancel, so the pillar's realized league sd falls well below 1; collinear
signals reinforce, so it approaches 1. A pillar's true share of rating spread is
`weight × realized_sd`, not `weight`.

Measured on the live 12-team dynasty league under `results_led`:

| Pillar | Signals | Realized z sd | Stated w | Actual share of spread |
|---|---|---|---|---|
| Results | 5, pairwise r **+0.61 … +0.91** (all encode "did you win") | **0.906** | 0.50 | **58.5%** |
| Skill | 4, pairwise r **−0.29 … +0.48** | **0.544** | 0.30 | **21.1%** |
| Outlook | 3 | **0.793** | 0.20 | 20.5% |

Results was overweighted by ~8 points and Skill underweighted by ~9 against
their stated split, purely from signal correlation structure. **Never judge a
weight change by the dict — measure realized pillar sd across the league.**
Adding a signal to a pillar changes that pillar's realized sd, which silently
re-weights *every other pillar's* share too.

### (b) Normalization and shrinkage are one decision, never two

Re-standardizing a pillar's z to unit sd makes stated weights honest — and
multiplies whatever noise that pillar holds by the same factor. Measured: at
Skill's realized sd of 0.544, re-standardizing alone moves one owner from
z −1.06 to **−1.95** and another from +1.10 to +2.02. A re-standardization
that ships without sample-size shrinkage just amplifies small samples.

**Order trap — get this right or the shrinkage does nothing.**
z-score across the league **first**, then multiply each z by a reliability
factor `n/(n+k)`, then blend. Shrinking *raw* values toward the mean before
z-scoring silently undoes itself: the sd shrinks with the values and re-scoring
re-inflates the spread. Measured on `trade_skill_signals`, varying `k`:

| k | raw sd | z sd after league scoring |
|---|---|---|
| 0 | 1464.9 | **1.000** |
| 2 (live) | 826.1 | **1.000** |
| 10 | 407.4 | **1.000** |

Raw spread collapses 3.6×; the signal's contribution to the rating is
unchanged. What survives is only a *relative reordering* (the z extreme moves
from −2.43 to −1.56 as high-volume owners displace low-volume ones) — useful,
but it is not damping, and it is not what the docstring promises. Two live
instances shrink in raw space today: `skill_signals.trade_skill_signals`
(`k=2.0`) and `draft_signals.draft_skill` (`tot/(cnt + shrink_k)`). Anything
downstream that re-standardizes a pillar must move its shrinkage to z-space.

**Census facts get no shrinkage.** Current roster value, share of roster value
under 25, draft capital — these are measured, not estimated, so there is no
sampling error to shrink. Only signals averaged over a countable sample
(trades, picks, weeks) take a reliability factor.

### (c) Check a signal's raw league spread before assigning it a weight

z-scoring stretches whatever spread exists to fill the same ±2-ish range. A
near-uniform signal becomes a full-strength grade driver on noise. Measured:

| Signal | Raw league range | z range produced | Weight |
|---|---|---|---|
| `lineup_skill` | .804 – .875 (a ~1.6pp gap from mean ≈ half a win per season) | −1.92 … +1.76 | **25% of Skill** |
| `youth` (negated mean roster age) | 24.33 – 26.39 across all twelve teams | −1.30 … +2.35 | 25% of Outlook |
| `championships` | 0 – 2 | wide, and genuinely discriminating | 35% of Results |

A 2.06-year spread in mean age and a 7.1-point spread in lineup efficiency each
buy a signal the same grade authority as a title count. Weight should track how
much real separation the raw signal carries, not how important the concept
sounds.

**Prefer value-weighted or share-of-value formulations over straight means.** A
mean over a roster is dominated by roster filler: mean age ranked one owner 10th
of 12 on youth while that same roster's young core (Stroud, Harrison, Jameson
Williams) was its most valuable asset. "Share of roster value under 25" answers
the question mean age was asked.

## Letter bands are a separate calibration from weights

`LETTER_BANDS` keys on `rating - BASE`, and the composite is mean-zero **by
construction** — the league average is always exactly 1500. So a fixed band
table hands out a fixed share of every letter in every league, however strong
the league is.

Measured on the live league: rating sd **192** (composite z sd 0.70, not 1.0,
for the reason in rule (a) — `SCALE = 275` assumes unit sd). The `C` band spans
just ±20 rating points = ±0.10 sd, so almost nobody lands in it; `D+` starts at
−100 = −0.52 sd, so **~30% of any league is D+ or worse by construction.** The
live twelve came out A+, A−, B, C, C−, C−, C−, D+, D, D, D, F.

When a grade is disputed as too harsh: check band widths against the measured
rating sd **before** touching a signal. "This owner is not an F" is usually a
band-width complaint (F begins at −210 = −1.09 sd) rather than evidence a signal
is wrong. Widening `C` or narrowing the tails is a band edit; it does not
re-rank anyone.

## Checklist

1. Name exactly what is changing: pillar weight, signal weight, new/removed
   signal, new format tree, or bands.
2. Run the harness on the **current** tree. Keep the output.
3. Run it on the candidate.
4. Compare: letter distribution, who moved and by how much, and realized pillar
   sd vs stated weight for both trees.
5. Confirm no signal's weight outruns its raw league spread (c) or its sample
   size (b) — and that any shrinkage sits *after* the z-score.
6. New format tree: confirm the pillar weights sum to 1.0 and that
   `signal_weights_for` returns a tree with matching pillar keys (a tree summing
   below 1.0 compresses every grade toward 1500).
7. Only then write tests (`tests/test_gm_rating.py`, `test_gm_signals.py`,
   `test_skill_signals.py`, `test_draft_signals.py`,
   `api/tests/test_franchise_redesign*.py`) and the code.
