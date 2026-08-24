# Sleeper Dynasty Analyzer — Design Spec

## Overview

A Python CLI tool that connects to the Sleeper fantasy football API, pulls league data and player projections, simulates the full season via Monte Carlo methods, and outputs a shareable Google Doc with league analysis, projected standings, per-team dynasty outlooks, and weekly matchup forecasts.

## Goals

- Fetch current rosters, league settings, and matchup schedules from Sleeper's public API
- Blend Sleeper projections with external sources (FantasyPros) for accuracy
- Simulate the full 2026 season (default) from Week 1 using Monte Carlo methods
- Produce a 5-year dynasty outlook per team including age analysis, draft capital, and trajectory
- Output everything as a formatted, shareable Google Doc with one tab per report section

## Non-Goals (v1)

- Real-time scoring or live game tracking
- Trade recommendations or trade calculator
- AI-generated narrative summaries
- Web dashboard or hosted service *(later reversed — a hosted Trade Grader web app shipped; see `README.md` and the 2026-05-28 web-app spec)*
- Write access to Sleeper (the API is read-only anyway)

---

## Data Layer

### Sleeper API Client

Base URL: `https://api.sleeper.app/v1`

Endpoints used:

| Endpoint | Purpose |
|----------|---------|
| `/user/{username}` | Resolve username → user_id |
| `/user/{user_id}/leagues/nfl/{season}` | List user's leagues for the season |
| `/league/{league_id}` | League settings (scoring, roster slots, schedule) |
| `/league/{league_id}/rosters` | All team rosters (player IDs, wins, losses) |
| `/league/{league_id}/users` | Owner names and display names |
| `/league/{league_id}/matchups/{week}` | Matchups for a given week |
| `/league/{league_id}/traded_picks` | All traded draft picks |
| `/league/{league_id}/drafts` | Draft metadata |
| `/draft/{draft_id}/picks` | Individual draft pick details |
| `/players/nfl` | Full player database (~5MB) |
| `/projections/nfl/regular/{season}` | Season projections from Sleeper |
| `/projections/nfl/regular/{season}/{week}` | Weekly projections from Sleeper |

Rate limit: stay under 1,000 calls/minute. In practice, a single league analysis uses ~20-30 calls.

No authentication required — fully public API.

### External Projections

- **FantasyPros** rest-of-season projections: scrape the free-tier consensus rankings/projections page
- Merge strategy: average Sleeper and FantasyPros projections, weighted toward FantasyPros when available (they aggregate multiple sources)
- Normalize all projections to the league's scoring settings (PPR value, passing TD points, etc.)
- Fallback: if external source is unavailable, use Sleeper projections alone

### Caching

Location: `~/.sleeper-dynasty/cache/`

| Data | Refresh Policy |
|------|---------------|
| Player database (`players.json`) | Once per day |
| External projections | Once per day |
| League data (rosters, matchups, settings) | Every run (small payloads, always fresh) |

Cache files are timestamped. The `--no-cache` flag forces a full refresh.

---

## Simulation Engine

### Optimal Lineup Solver

For each team, for each simulated week:

1. Read the league's roster slot configuration (e.g., 1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX, 1 SF, 1 K, 1 DEF)
2. Assign players to slots to maximize total projected points
3. Handle FLEX/SF correctly — this is a constrained optimization problem, not greedy assignment
   - Use a brute-force or LP approach over the small roster sizes (typically 8-10 starters from ~15-25 rostered players)
4. Output: projected weekly score for the team

### Variance Model

Each player's projected points are treated as the mean of a normal distribution. Standard deviations by position:

| Position | CV (Coefficient of Variation) | Rationale |
|----------|------|-----------|
| QB | 0.20 | Most consistent week-to-week |
| RB | 0.30 | High variance, injury-prone |
| WR | 0.30 | Boom/bust, target variance |
| TE | 0.35 | Highly volatile outside elite tier |
| K | 0.40 | Very unpredictable |
| DEF | 0.45 | Most volatile position |

Standard deviation = projected points × CV. Players projected under 5 points get a floor CV to avoid degenerate distributions.

### Monte Carlo Season Simulation

- **Iterations:** 10,000 (configurable via `--sims`)
- **Per iteration:**
  1. For each remaining week in the regular season:
     - Sample each player's weekly points from N(projection, σ)
     - Set optimal lineups for each team
     - Determine matchup winners
  2. After regular season: rank teams by W-L (tiebreak by total points)
  3. Simulate playoffs using the league's bracket configuration
- **Tracked across all iterations:**
  - Per-team: total wins distribution, playoff appearances, championship wins
  - Per-matchup: win count for each side

**Outputs:**

| Metric | Calculation |
|--------|-------------|
| Projected W-L | Mean wins/losses across iterations |
| Win range | 5th–95th percentile of wins |
| Playoff probability | % of iterations where team makes playoffs |
| Championship probability | % of iterations where team wins the final |
| Matchup win probability | % of iterations where Team A beats Team B in week X |

---

## Dynasty Outlook Engine

For each team, produce a 5-year outlook based on current roster composition and draft capital.

### Age Profile Analysis

- Pull player birth dates from the Sleeper player database
- Calculate average age by position group (QB, RB, WR, TE)
- Flag players 28+ as aging risks (26+ for RB)
- Identify core young pieces (starters under 25)

### Draft Capital Analysis

- Fetch traded picks via `/league/{league_id}/traded_picks`
- For each team, calculate:
  - Number of picks owned by round for the next 2-3 drafts
  - Number of picks traded away
  - Net draft capital vs. league average (e.g., "+3 picks above average" or "-2 picks below average")
- Classify: **pick-rich** (above average), **neutral**, or **pick-poor** (below average)

### Draft Needs Assessment

- Identify weak position groups based on current roster strength
- Cross-reference with aging risks (if your top RB is 29, RB is a need even if current production is good)
- Prioritize needs: immediate (this draft) vs. developing (2-3 years out)

### Window & Trajectory Classification

| Classification | Criteria |
|---------------|----------|
| **Competing now** | Top-third projected points, young-to-mid core, adequate draft capital |
| **Ascending** | Young roster, strong draft capital, projected mid-pack or better |
| **Peaking** | High projected points but aging core, limited draft capital |
| **Descending** | Aging roster, declining projections, pick-poor |
| **Rebuilding** | Bottom-third projected points, pick-rich, young unproven roster |

---

## Output: Google Doc

### Authentication

- OAuth 2.0 flow using Google's `google-auth-oauthlib`
- First run opens a browser for Google account authorization
- Credentials stored in `~/.sleeper-dynasty/google_credentials.json`
- Refresh tokens used for subsequent runs (no re-auth needed unless revoked)
- Required OAuth scopes: `https://www.googleapis.com/auth/documents`, `https://www.googleapis.com/auth/drive.file`

### Document Structure

**Title:** `{League Name} - Dynasty Analysis - {YYYY-MM-DD}`

**Sharing:** "Anyone with the link can view" by default. Use `--private` to skip this.

Every run creates a new document. The Google Doc link is printed to the terminal.

#### Tab 1: League Overview

- League name, sport, season
- Scoring format (PPR/half/standard + custom details)
- Roster slot configuration
- Number of teams
- Current standings table (Team | W | L | PF | PA)
- Generated timestamp

#### Tab 2: Projected Final Standings

Table sorted by playoff probability:

| Rank | Team | Current W-L | Proj W-L | Win Range (5th-95th) | Playoff % | Championship % |
|------|------|-------------|----------|----------------------|-----------|----------------|

Color coding: green for >70% playoff odds, yellow for 30-70%, red for <30%.

#### Tab 3: Team Reports

One section per team (separated by page breaks), containing:

**Header:** Team name, owner, current record

**Roster Analysis:**
- Strengths (top position groups relative to league)
- Weaknesses (bottom position groups relative to league)
- Top 5 projected players table (Player | Pos | Age | Proj Pts)

**2026 Season Projection:**
- Projected W-L and playoff probability
- Season outlook label (Contender / Bubble / Rebuilding)

**5-Year Dynasty Outlook:**
- Window status (Competing / Ascending / Peaking / Descending / Rebuilding)
- Age profile table by position group (Pos Group | Avg Age | # Players 28+ | Key Ages)
- Core dynasty pieces (young high-value players)
- Aging risks (players likely to decline within 1-3 years)
- Draft capital summary:
  - Picks owned by round for next 2-3 drafts
  - Picks vs. league average (+/- picks)
  - Notable traded picks (given away or acquired)
- Draft needs (prioritized position needs for upcoming drafts)
- Overall trajectory (1-2 sentence summary)

#### Tab 4: Weekly Matchup Forecasts

One section per week:

**Week X**

| Matchup | Favored | Win % | Projected Score |
|---------|---------|-------|-----------------|

---

## CLI Interface

### Installation

```bash
pip install -e .
```

### Usage

```bash
sleeper-dynasty analyze <sleeper_username>
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--season` | `2026` | NFL season year |
| `--week` | `1` | Start projections from this week |
| `--sims` | `10000` | Number of Monte Carlo simulation iterations |
| `--no-cache` | `false` | Force refresh all cached data |
| `--private` | `false` | Don't auto-set "anyone with link can view" |

### Output

Prints progress to terminal:
```
Fetching league data for user: tomkeefe...
Found 2 dynasty leagues. Select one:
  [1] Best Ball Dynasty (12 teams, SF, PPR)
  [2] Redraft League (10 teams) — skipped, not dynasty
Using: Best Ball Dynasty

Fetching rosters and matchups...
Fetching player projections...
Running season simulation (10,000 iterations)...
Building dynasty outlooks...
Creating Google Doc...

Done! View your report:
https://docs.google.com/document/d/1abc.../edit
```

---

## Project Structure

```
sleeper-dynasty/
├── pyproject.toml
├── src/
│   └── sleeper_dynasty/
│       ├── __init__.py
│       ├── __main__.py          # Entry point: `python -m sleeper_dynasty`
│       ├── cli.py               # Argument parsing, orchestration flow
│       ├── api/
│       │   ├── __init__.py
│       │   ├── sleeper.py       # Sleeper API client (all endpoints)
│       │   └── projections.py   # FantasyPros + external projection fetching
│       ├── models/
│       │   ├── __init__.py
│       │   ├── league.py        # League, Roster, Matchup, DraftPick dataclasses
│       │   └── player.py        # Player, PlayerProjection dataclasses
│       ├── engine/
│       │   ├── __init__.py
│       │   ├── lineup.py        # Optimal lineup solver
│       │   ├── simulator.py     # Monte Carlo season simulation
│       │   └── dynasty.py       # 5-year outlook (age, capital, trajectory)
│       ├── output/
│       │   ├── __init__.py
│       │   └── google_docs.py   # Google Docs API: create doc, tabs, tables
│       └── cache.py             # File-based caching in ~/.sleeper-dynasty/cache/
└── tests/
    ├── test_sleeper_api.py
    ├── test_lineup.py
    ├── test_simulator.py
    ├── test_dynasty.py
    └── test_projections.py
```

## Dependencies

```
httpx           # Async HTTP client
numpy           # Random sampling for Monte Carlo
google-api-python-client  # Google Docs/Drive API
google-auth-oauthlib      # OAuth 2.0 authentication
google-auth-httplib2      # Auth transport
```

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| FantasyPros blocks scraping | Graceful fallback to Sleeper-only projections; user sees a warning |
| Sleeper API changes/breaks | Pin to v1 endpoints; the API has been stable for years |
| Google OAuth complexity | One-time browser flow; credentials persist across runs |
| Simulation too slow | 10K sims × 17 weeks × 12 teams is ~2M lineup solves; numpy vectorization keeps it under 30 seconds |
| Player database is 5MB | Cache locally, refresh daily |
