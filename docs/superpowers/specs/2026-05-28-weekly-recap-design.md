# Weekly Recap & Outlook — Design

**Date:** 2026-05-28
**Status:** Approved design, pending implementation plan

## Summary

A weekly league feature that generates a funny, rude, savage **recap** of the
games that just happened plus an **outlook** on the upcoming week — written in a
smug, ESPN-parody-analyst voice. The system computes all facts deterministically
(scores, bench regret, lucky/unlucky, byes, weather, playoff stakes) and hands a
structured "facts packet" to Claude, which does the comedy writing. The LLM never
invents numbers; it only jokes about facts the engine supplies.

This is **Approach A**: facts engine + single LLM pass. Chosen over multi-section
generation (B, more expensive, marginal gain) and raw-data-dump (C, generic jokes,
hallucinated numbers).

## Goals

- Produce a single weekly text artifact: recap of the completed week + outlook on
  the next week, in a consistent roast-comedy persona.
- Be **specifically** mean — every joke anchored to a real, engine-verified fact.
- Roast owners by name, plus the NFL players/teams who betrayed them.
- Render to an HTML/Doc report for v1, with a pluggable delivery seam so the same
  text can be posted to league chat (Telegram/Discord/GroupMe) later.

## Non-Goals (v1)

- Live posting to a chat platform (architecture leaves a seam; not built yet).
- Multi-section / per-matchup separate LLM calls (Approach B — future upgrade).
- Reading Sleeper league chat (not exposed by the public API; replaced by a
  hand-maintained `league_lore` file).
- Automated comedy-quality scoring (human eyeball test on real weeks).

## Architecture

### Data flow

```
Sleeper API ─┐
ESPN sched ──┤→ FactsBuilder ──→ facts packet (JSON) ──→ RecapWriter (Claude) ──→ recap text
Open-Meteo ──┤       ↑                                        ↑
Projections ─┘   lineup + simulator                    persona + league_lore
                                                              │
                                                  pluggable Renderer (HTML/Doc now, chat later)
```

### New modules

Following the existing `api/ engine/ output/` layout.

- **`api/nfl_schedule.py`** — Fetches ESPN's public scoreboard feed
  (`site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?week=N`) for a
  given week. Returns per-week games: teams playing, kickoff time, venue,
  indoor/outdoor flag. **Byes** are derived as the set of NFL teams not appearing
  in that week's games. Cached via existing `cache.py`. Best-effort: on failure,
  bye/schedule beats are omitted, not fatal.

- **`api/weather.py`** — Open-Meteo forecast API (free, no API key), keyed by a
  static `STADIUM_COORDS` lookup table (team/venue → lat/long). Outdoor venues
  only; domes/retractable-closed are flagged "climate-controlled, no excuses."
  Returns wind, temp, precipitation per outdoor game. Best-effort: on failure,
  weather beats are omitted.

- **`engine/recap.py`** — **FactsBuilder**: pure functions that turn raw data
  (matchups, rosters, players, projections, schedule, weather, standings) into the
  structured facts packet below. Reuses `engine/lineup.py` (optimal lineup → bench
  regret, likely bye replacements) and `engine/simulator.py` (playoff stakes). All
  comedy-relevant math lives here and is fully unit-testable.

- **`llm/recap_writer.py`** — **RecapWriter**: builds the Claude prompt (persona +
  `league_lore` + facts packet), calls the Anthropic SDK with prompt caching,
  returns recap text. Follows `claude-api` skill conventions.

- **`output/recap_render.py`** — Wraps the returned text into the existing
  HTML/Doc renderers. Exposes a `Delivery` interface (v1: `FileDelivery` /
  `HtmlDelivery`) so a future `ChatDelivery` drops in without touching the writer.

- **CLI** — new `recap` subcommand in `cli.py`.

### The facts packet (engine ↔ writer contract)

Every number the writer sees is computed here, so jokes are accurate by
construction. The writer is instructed to use only facts present in this packet.

```jsonc
{
  "week": 9,
  "league": { "name": "...", "scoring": "...", "playoff_week_start": 15 },
  "standings": [ { "owner": "...", "wins": 6, "losses": 2, "points_for": 1234.5 } ],
  "recap": {
    "matchups": [
      { "winner": "...", "loser": "...", "score": [142.3, 98.1],
        "margin": 44.2, "blowout": true, "nailbiter": false }
    ],
    "high_scorer": { "owner": "...", "points": 158.0 },
    "low_scorer":  { "owner": "...", "points": 71.2 },
    "bench_regret": [
      { "owner": "...", "points_left_on_bench": 31.5,
        "benched_hero": { "player": "...", "points": 28.0 },
        "started_dud":  { "player": "...", "points": 4.0 } }
    ],
    "lucky":   [ { "owner": "...", "note": "won with the 2nd-lowest score of the week" } ],
    "unlucky": [ { "owner": "...", "note": "highest score that still lost" } ],
    "heroes":  [ { "player": "...", "owner": "...", "points": 41.0 } ],
    "goats":   [ { "player": "...", "owner": "...", "points": 2.0 } ],
    "busts":   [ { "player": "...", "owner": "...", "projected": 22.0, "actual": 5.0 } ]
  },
  "outlook": {
    "matchups": [
      { "home": "...", "away": "...", "projected_score": [115.0, 102.0],
        "favorite": "...", "spread": 13.0 }
    ],
    "byes": [
      { "owner": "...", "players_on_bye": ["..."],
        "likely_replacement": { "player": "...", "projected": 6.0, "note": "bad" } }
    ],
    "weather": [
      { "game": "BUF @ NE", "wind_mph": 22, "temp_f": 28, "precip": "snow",
        "affected_players": ["...kicker...", "...qb..."] }
    ],
    "playoff_stakes": [
      { "owner": "...", "status": "must-win" }   // must-win | can-clinch | eliminated | spoiler
    ]
  }
}
```

Sources that fail (ESPN, weather) simply omit their sub-section; the recap still
generates from whatever facts are available.

## Generation

**RecapWriter prompt structure** (Anthropic SDK + prompt caching):

- **System prompt** (static → cached): the persona definition (smug ESPN-parody
  analyst), tone rules, and required output structure. Persona is loaded from a
  swappable file (`--persona`), defaulting to the built-in analyst persona.
- **User content**: the `league_lore` file (owner nicknames, rivalries, running
  bits) + the week's facts packet (JSON).
- **Output structure** the model is asked to produce:
  1. Cold-open zinger
  2. Game-by-game recap hitting the juicy beats (blowouts, nailbiters, bench
     regret, lucky/unlucky)
  3. Hero & Goat of the Week
  4. Upcoming-week outlook: matchup previews, bye-week chaos + guessed (bad)
     replacement starters, weather impacts, playoff stakes
  5. Sign-off
- **Hard rule in the prompt:** only use facts from the packet; never fabricate
  scores, players, or outcomes.

**Model:** defaults to `claude-opus-4-8` (weekly cadence makes top-tier cost
trivial; comedy quality is worth it). Configurable down to Sonnet via `--model`.

### Tone & boundaries

Output is intentionally savage, profane, hard-R roast comedy aimed at owners'
decisions/scores and the NFL players/teams who let them down. The one real
boundary: no hateful content targeting protected classes — which is not where
league-roast comedy lives anyway (the funny is in "you started a kicker on bye and
still would've lost"). Intensity is tuned via the persona prompt, which is exposed
as a knob.

## League lore

A hand-maintained markdown file passed via `--lore`, fully under the user's
control and grown over the season. v1 ships a **starter template** scaffolding
structured sections to make it easy to fill in:

```markdown
# League Lore

## Owners & Nicknames
- <owner display name> — <nickname>, <one-line characterization>

## Rivalries
- <owner A> vs <owner B> — <the beef>

## Past Humiliations
- <memorable collapse, blown lead, infamous trade>

## Running Bits / Inside Jokes
- <recurring joke the recap should reference>
```

Lore is optional — without it, jokes come purely from the data.

## CLI

```
sleeper-dynasty recap <username|league_id>
    [--week N]            # default: last completed week (recap) + next week (outlook)
    [--lore PATH]         # optional league_lore markdown
    [--persona PATH]      # optional persona override
    [--model MODEL]       # default claude-opus-4-8
    [--out report.html]   # default HTML output
```

- **Week defaults**: derived from Sleeper's NFL-state endpoint — recap = last
  completed week, outlook = next week. Overridable with `--week`.
- **League selection**: same mechanism as the existing `analyze` command.

## Error handling

- ESPN schedule and weather are **best-effort**: a failure omits that beat
  (e.g., no weather data ⇒ no weather jokes) and is logged; the recap still
  generates.
- Sleeper API failures are **hard errors** (no recap without the core data).
- Anthropic API failures surface an actionable error (auth/rate-limit/timeout),
  per project error-handling conventions.

## Testing (TDD)

- **`FactsBuilder`** — the bulk of testing. Pure unit tests against **real
  past-week data** (full season history available via per-season `league_id`).
  Assert blowouts, bench regret, lucky/unlucky, heroes/goats, busts are computed
  correctly.
- **`api/nfl_schedule.py` / `api/weather.py`** — tested against recorded fixture
  responses; no live network calls in tests.
- **`RecapWriter`** — tested with a mocked Anthropic client: assert the prompt
  contains the right facts + persona + lore and that the writer passes through
  only packet facts. Comedy quality is not unit-tested.
- **End-to-end smoke** — a manually triggered run on a real past week to read the
  actual output.

## Dependencies

- New: `anthropic` (Anthropic SDK).
- Reuses existing: `httpx` (ESPN/Open-Meteo), `jinja2` (HTML), Google Docs output,
  `cache.py`, `engine/lineup.py`, `engine/simulator.py`.

## Future work

- `ChatDelivery` to auto-post to league chat (Telegram already configured).
- Approach B per-matchup generation for a longer newsletter format.
- Historical-weather support to make outlook beats testable on past weeks.
