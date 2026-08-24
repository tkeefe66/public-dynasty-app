"""Self-contained HTML report output for Sleeper dynasty league reports.

Generates a single offline-friendly HTML file (with embedded CSS) that
presents the league analysis in three sections:

  1. Projected Final Standings — a single sortable-style table with
     color-coded playoff% cells.
  2. Team Reports — one card per team showing roster, age profile,
     draft capital and draft needs.
  3. Weekly Matchup Forecasts — collapsible (``<details>``) per-week
     tables with win% color cues mirroring the standings table.

The file is written to ``~/.sleeper-dynasty/reports/`` and the resulting
path is returned. No external CSS, JS, or font dependencies — the file
is portable and can be emailed, dropped in a Slack thread, or uploaded
to a static host as-is.

Design choices worth knowing
----------------------------
- **Single Jinja2 template embedded in this module.** Keeps the package
  self-contained — no extra ``.html`` resources to ship.
- **Light theme only.** Easier to read for everyone; avoids fighting the
  user's OS dark-mode preference, which adds CSS complexity and gives
  inconsistent rendering across email clients / preview pop-ups.
- **System font stack.** Zero font requests, fast offline render.
- **Collapsible weeks via ``<details>``.** Pure HTML — no JavaScript,
  no framework. Works in every modern browser, including Safari.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, select_autoescape

if TYPE_CHECKING:
    from sleeper_dynasty.engine.dynasty import DynastyOutlook
    from sleeper_dynasty.engine.simulator import SimulationResult
    from sleeper_dynasty.models.league import League, Roster

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Where reports get written. Mirrors the location used by other
# sleeper-dynasty artifacts so users have one place to look.
REPORTS_DIR = Path.home() / ".sleeper-dynasty" / "reports"

# Thresholds for the textual outlook label shown in the per-team card.
# Same values the old Google Docs renderer used so the wording stays
# consistent between versions for anyone who saved an older report.
_CONTENDER_PLAYOFF_PCT = 60.0
_BUBBLE_PLAYOFF_PCT = 30.0


# ---------------------------------------------------------------------------
# Helpers (pure functions; easy to unit-test)
# ---------------------------------------------------------------------------


def _outlook_label(playoff_pct: float) -> str:
    """Classify a team's season outlook by playoff probability."""
    if playoff_pct >= _CONTENDER_PLAYOFF_PCT:
        return "Contender"
    if playoff_pct >= _BUBBLE_PLAYOFF_PCT:
        return "Bubble"
    return "Rebuilding"


def _probability_class(pct: float) -> str:
    """CSS class for a probability cell (playoff%, win%, etc.).

    The thresholds match the legacy Google Docs report so the visual
    language ("green = lock, yellow = bubble, red = long shot") stays
    consistent between report versions.
    """
    if pct >= 70.0:
        return "prob-high"
    if pct >= 30.0:
        return "prob-mid"
    return "prob-low"


def _slugify(text: str) -> str:
    """Turn a league name (or arbitrary string) into a safe filename slug.

    Lowercase, alphanumerics + dash only. Collapses runs of disallowed
    characters into a single dash and strips leading/trailing dashes.
    Falls back to ``"league"`` if the input collapses to empty.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "league"


# ---------------------------------------------------------------------------
# Embedded template
# ---------------------------------------------------------------------------

# The whole HTML page lives here as a Jinja2 template string. We embed
# rather than ship a separate ``.html`` file so the package is fully
# self-contained — no extra resource lookups, no risk of the file
# missing from a wheel install.
_TEMPLATE_SOURCE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ league_name }} - Dynasty Analysis</title>
<style>
  /* ----- Base reset & typography ----- */
  *, *::before, *::after { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      Helvetica, Arial, sans-serif;
    color: #1a1a1a;
    background: #ffffff;
    line-height: 1.5;
    font-size: 15px;
  }
  h1, h2, h3, h4 {
    color: #1a2b4a;
    margin: 0 0 0.5em 0;
    line-height: 1.25;
  }
  p { margin: 0 0 1em 0; }
  a { color: #1a2b4a; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .muted { color: #666; }

  /* ----- Hero header ----- */
  .hero {
    background: linear-gradient(135deg, #1a2b4a 0%, #2a4070 100%);
    color: #ffffff;
    padding: 48px 32px;
    text-align: center;
  }
  .hero h1 {
    color: #ffffff;
    font-size: 2.4em;
    margin: 0;
    font-weight: 700;
    letter-spacing: -0.01em;
  }
  .hero .subtitle {
    margin-top: 8px;
    font-size: 1.05em;
    color: #cfd8e8;
  }

  /* ----- Sticky nav ----- */
  nav.sticky {
    position: sticky;
    top: 0;
    background: #ffffff;
    border-bottom: 1px solid #e3e6eb;
    padding: 12px 32px;
    z-index: 10;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  }
  nav.sticky ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    gap: 24px;
    justify-content: center;
    flex-wrap: wrap;
  }
  nav.sticky a {
    color: #1a2b4a;
    font-weight: 600;
    font-size: 0.95em;
    padding: 4px 0;
    border-bottom: 2px solid transparent;
    transition: border-color 0.15s;
  }
  nav.sticky a:hover {
    text-decoration: none;
    border-bottom-color: #1a2b4a;
  }

  /* ----- Layout ----- */
  main {
    max-width: 1100px;
    margin: 0 auto;
    padding: 32px;
  }
  section { margin-bottom: 56px; }
  section > h2 {
    font-size: 1.7em;
    margin-bottom: 4px;
    padding-bottom: 8px;
    border-bottom: 2px solid #1a2b4a;
  }
  section > .section-sub {
    color: #666;
    margin-bottom: 24px;
    font-size: 0.95em;
  }

  /* ----- Tables ----- */
  table {
    width: 100%;
    border-collapse: collapse;
    background: #ffffff;
    font-size: 0.95em;
  }
  thead th {
    background: #1a2b4a;
    color: #ffffff;
    text-align: left;
    padding: 12px 14px;
    font-weight: 600;
    font-size: 0.9em;
    letter-spacing: 0.02em;
  }
  tbody td {
    padding: 12px 14px;
    border-bottom: 1px solid #ececec;
    vertical-align: middle;
  }
  tbody tr:nth-child(even) { background: #f7f8fa; }
  tbody tr:hover { background: #eef2f8; }
  td.team-name, td.bold { font-weight: 600; }
  td.right, th.right { text-align: right; }
  td.center, th.center { text-align: center; }

  /* ----- Probability color cells (playoff%, win%) ----- */
  .prob-high {
    background-color: #d4edda !important;
    color: #155724;
    font-weight: 600;
  }
  .prob-mid {
    background-color: #fff3cd !important;
    color: #856404;
    font-weight: 600;
  }
  .prob-low {
    background-color: #f8d7da !important;
    color: #721c24;
    font-weight: 600;
  }
  /* On hover the row tint would otherwise wash out the prob cells. Make
     sure the colored cells still read clearly. */
  tbody tr:hover .prob-high,
  tbody tr:hover .prob-mid,
  tbody tr:hover .prob-low { filter: brightness(0.98); }

  /* ----- Team cards ----- */
  .team-card {
    background: #ffffff;
    border: 1px solid #e3e6eb;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    padding: 24px;
    margin-bottom: 24px;
  }
  .team-card-header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #ececec;
  }
  .team-card-header h3 {
    margin: 0;
    font-size: 1.4em;
  }
  .team-card-header .meta {
    color: #666;
    font-size: 0.95em;
    margin-top: 2px;
  }
  .team-card-body {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
  }
  @media (max-width: 720px) {
    .team-card-body { grid-template-columns: 1fr; }
  }
  .team-card-col h4 {
    font-size: 1.05em;
    margin-top: 0;
    margin-bottom: 12px;
    color: #1a2b4a;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.9em;
  }
  .subblock { margin-bottom: 20px; }
  .subblock h5 {
    margin: 0 0 8px 0;
    font-size: 0.85em;
    color: #1a2b4a;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }

  /* Compact tables inside team cards. */
  .team-card table { font-size: 0.9em; }
  .team-card thead th { padding: 8px 10px; font-size: 0.8em; }
  .team-card tbody td { padding: 8px 10px; }

  .needs-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .needs-list li {
    padding: 6px 0;
    border-bottom: 1px solid #f0f0f0;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: baseline;
  }
  .needs-list li:last-child { border-bottom: none; }
  .needs-list .need-pos {
    font-weight: 600;
    min-width: 38px;
  }
  .needs-list .urgency {
    font-size: 0.75em;
    padding: 2px 8px;
    border-radius: 999px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 600;
  }
  .urgency-immediate {
    background: #f8d7da;
    color: #721c24;
  }
  .urgency-developing {
    background: #fff3cd;
    color: #856404;
  }
  .needs-list .reason { color: #666; flex: 1 1 240px; }

  /* ----- Chip base (worn by the Outlook chip below) ----- */
  .chip {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 0.8em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* ----- Outlook chip (Contender/Bubble/Rebuilding) ----- */
  .outlook-contender { background: #d4edda; color: #155724; }
  .outlook-bubble    { background: #fff3cd; color: #856404; }
  .outlook-rebuilding{ background: #f8d7da; color: #721c24; }

  /* ----- Weekly matchups (details/summary) ----- */
  details.week-block {
    border: 1px solid #e3e6eb;
    border-radius: 8px;
    margin-bottom: 12px;
    background: #ffffff;
    overflow: hidden;
  }
  details.week-block summary {
    padding: 14px 20px;
    cursor: pointer;
    font-weight: 600;
    font-size: 1.05em;
    color: #1a2b4a;
    background: #f7f8fa;
    list-style: none;
    user-select: none;
  }
  details.week-block summary::-webkit-details-marker { display: none; }
  details.week-block summary::before {
    content: "▸ ";
    display: inline-block;
    margin-right: 4px;
    transition: transform 0.15s;
  }
  details.week-block[open] summary::before {
    transform: rotate(90deg);
  }
  details.week-block summary:hover { background: #eef2f8; }
  details.week-block .week-body {
    padding: 0;
  }
  details.week-block table { border-radius: 0; }

  /* ----- Footer ----- */
  footer {
    text-align: center;
    color: #999;
    font-size: 0.85em;
    padding: 24px 32px 40px;
  }
</style>
</head>
<body>

<div class="hero">
  <h1>{{ league_name }}</h1>
  <div class="subtitle">Dynasty Analysis &middot; {{ generated_ts }}</div>
</div>

<nav class="sticky">
  <ul>
    <li><a href="#standings">Projected Standings</a></li>
    <li><a href="#teams">Team Reports</a></li>
    <li><a href="#matchups">Matchups</a></li>
  </ul>
</nav>

<main>

  <section id="standings">
    <h2>Projected Final Standings</h2>
    <p class="section-sub">
      Sorted by Monte Carlo playoff probability.
      Green = playoff lock (&ge;70%), yellow = bubble (30&ndash;70%),
      red = long shot (&lt;30%).
    </p>
    <table>
      <thead>
        <tr>
          <th>Rank</th>
          <th>Team</th>
          <th>Owner</th>
          <th>Proj W-L</th>
          <th>Win Range</th>
          <th>Playoff %</th>
          <th>Champ %</th>
        </tr>
      </thead>
      <tbody>
        {% for row in standings %}
        <tr>
          <td>{{ row.rank }}</td>
          <td class="team-name">{{ row.team_name }}</td>
          <td>{{ row.owner_name }}</td>
          <td>{{ row.proj_record }}</td>
          <td>{{ row.win_range }}</td>
          <td class="{{ row.playoff_class }}">{{ row.playoff_pct }}</td>
          <td>{{ row.champ_pct }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>

  <section id="teams">
    <h2>Team Reports</h2>
    <p class="section-sub">
      Per-team breakdown of roster, age profile, draft capital and draft
      needs. Cards ordered by projected playoff probability.
    </p>

    {% for team in team_cards %}
    <div class="team-card">
      <div class="team-card-header">
        <div>
          <h3>{{ team.owner_name }}</h3>
          <div class="meta">
            Current record: {{ team.record }} &middot;
            Projected: {{ team.proj_record }} &middot;
            Playoff odds: {{ team.playoff_pct }} &middot;
            Championship odds: {{ team.champ_pct }}
          </div>
        </div>
        <div>
          {# No Dynasty Window chip: the stage is a band on the Franchise
             Rating (engine/gm_rating.py::rating_to_stage) and the CLI's
             Monte-Carlo pipeline has no rating in scope. Giving this export
             its own second derivation would rebuild the two-models problem
             the Assets-led Outlook redesign exists to delete. #}
          <span class="chip {{ team.outlook_class }}">{{ team.outlook_label }}</span>
        </div>
      </div>

      <div class="team-card-body">
        <div class="team-card-col">
          <h4>Roster</h4>
          <div class="subblock">
            <h5>Top Projected Players</h5>
            {% if team.top_players %}
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Pos</th>
                  <th class="right">Age</th>
                  <th class="right">Proj Pts/Wk</th>
                </tr>
              </thead>
              <tbody>
                {% for p in team.top_players %}
                <tr>
                  <td>{{ p.name }}</td>
                  <td>{{ p.pos }}</td>
                  <td class="right">{{ p.age }}</td>
                  <td class="right">{{ p.proj }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
            {% else %}
            <p class="muted">No projection data for this roster.</p>
            {% endif %}
          </div>
        </div>

        <div class="team-card-col">
          <h4>Dynasty Outlook</h4>

          {% if team.age_rows %}
          <div class="subblock">
            <h5>Age Profile by Position</h5>
            <table>
              <thead>
                <tr>
                  <th>Pos</th>
                  <th class="right">Avg Age</th>
                  <th>Aging Risks</th>
                  <th>Core Young</th>
                </tr>
              </thead>
              <tbody>
                {% for row in team.age_rows %}
                <tr>
                  <td>{{ row.pos }}</td>
                  <td class="right">{{ row.avg }}</td>
                  <td>{{ row.aging }}</td>
                  <td>{{ row.young }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          {% endif %}

          <div class="subblock">
            <h5>Draft Capital</h5>
            {% if team.draft_rows %}
            <table>
              <thead>
                <tr>
                  <th>Season</th>
                  <th class="right">Picks</th>
                  <th>Breakdown</th>
                </tr>
              </thead>
              <tbody>
                {% for row in team.draft_rows %}
                <tr>
                  <td>{{ row.season }}</td>
                  <td class="right">{{ row.picks }}</td>
                  <td>{{ row.breakdown }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
            <p class="muted" style="margin-top: 8px; font-size: 0.85em;">
              Status: {{ team.draft_status }} &middot;
              Net vs avg: {{ team.draft_net }} &middot;
              Traded: {{ team.draft_traded }} &middot;
              Acquired: {{ team.draft_acquired }}
            </p>
            {% else %}
            <p class="muted">No draft capital data available.</p>
            {% endif %}
          </div>

          <div class="subblock">
            <h5>Draft Needs</h5>
            {% if team.needs %}
            <ul class="needs-list">
              {% for n in team.needs %}
              <li>
                <span class="need-pos">{{ n.pos }}</span>
                <span class="urgency urgency-{{ n.urgency }}">{{ n.urgency }}</span>
                <span class="reason">{{ n.reason }}</span>
              </li>
              {% endfor %}
            </ul>
            {% else %}
            <p class="muted">No immediate positional needs identified.</p>
            {% endif %}
          </div>
        </div>
      </div>
    </div>
    {% endfor %}
  </section>

  <section id="matchups">
    <h2>Weekly Matchup Forecasts</h2>
    <p class="section-sub">
      Per-week head-to-head forecasts. Win% reflects the favored team.
      Click a week to expand.
    </p>

    {% for week in weeks %}
    <details class="week-block" {% if loop.first %}open{% endif %}>
      <summary>Week {{ week.week }}</summary>
      <div class="week-body">
        <table>
          <thead>
            <tr>
              <th>Matchup</th>
              <th>Favored</th>
              <th class="right">Win %</th>
              <th class="right">Projected Score</th>
            </tr>
          </thead>
          <tbody>
            {% for m in week.matchups %}
            <tr>
              <td>{{ m.matchup }}</td>
              <td class="bold">{{ m.favored }}</td>
              <td class="right {{ m.win_class }}">{{ m.win_pct }}</td>
              <td class="right">{{ m.score }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </details>
    {% endfor %}
  </section>

</main>

<footer>
  Generated by sleeper-dynasty &middot; {{ generated_ts }}
</footer>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


@dataclass
class _StandingsRow:
    rank: int
    team_name: str
    owner_name: str
    proj_record: str
    win_range: str
    playoff_pct: str
    playoff_class: str
    champ_pct: str


class HTMLReport:
    """Builds and writes a self-contained HTML report for a league."""

    def __init__(self, league_name: str, season: int | None = None) -> None:
        self.league_name = league_name
        self.season = season
        # Autoescape on for ``.html`` outputs: player names, owner names,
        # and league names can contain ``<``, ``>``, or ``&`` and we don't
        # want a stray character to break the rendered DOM.
        self._env = Environment(autoescape=select_autoescape(["html"]))
        self._template = self._env.from_string(_TEMPLATE_SOURCE)

    # -- Public API -------------------------------------------------------

    def generate(
        self,
        league: League,
        rosters: list[Roster],
        sim_result: SimulationResult,
        dynasty_outlooks: dict[int, DynastyOutlook],
        player_projections: dict[str, tuple[str, float]],
        player_names: dict[str, str],
        player_ages: dict[str, int | None],
    ) -> Path:
        """Render the report and write it to ``REPORTS_DIR``.

        Returns the absolute path to the generated file. Idempotent — each
        call writes a new timestamped file so prior reports are preserved.
        """
        roster_map = {r.roster_id: r for r in rosters}

        # Pre-build all view-model dicts so the template is a thin
        # presentation layer — no business logic in Jinja.
        standings = self._build_standings(sim_result, roster_map)
        team_cards = self._build_team_cards(
            rosters,
            sim_result,
            dynasty_outlooks,
            player_projections,
            player_names,
            player_ages,
        )
        weeks = self._build_weeks(sim_result, roster_map)

        now = datetime.now()
        generated_ts = now.strftime("%Y-%m-%d %H:%M")
        html = self._template.render(
            league_name=self.league_name,
            season=self.season,
            generated_ts=generated_ts,
            standings=standings,
            team_cards=team_cards,
            weeks=weeks,
        )

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filename = (
            f"{_slugify(self.league_name)}_"
            f"{now.strftime('%Y-%m-%d')}_"
            f"{now.strftime('%H%M%S')}.html"
        )
        path = REPORTS_DIR / filename
        path.write_text(html, encoding="utf-8")
        logger.info("Wrote HTML report to %s (%d bytes)", path, len(html))
        return path

    # -- View-model builders ---------------------------------------------

    def _build_standings(
        self,
        sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> list[dict[str, Any]]:
        """Sort and format the projected-standings rows."""
        sorted_teams = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.playoff_pct,
            reverse=True,
        )
        rows: list[dict[str, Any]] = []
        for rank, t in enumerate(sorted_teams, start=1):
            roster = roster_map.get(t.roster_id)
            team_name = roster.owner_name if roster else f"Roster {t.roster_id}"
            owner_name = roster.owner_name if roster else "—"
            rows.append(
                {
                    "rank": rank,
                    "team_name": team_name,
                    "owner_name": owner_name,
                    "proj_record": f"{t.avg_wins:.1f}-{t.avg_losses:.1f}",
                    "win_range": f"{t.win_low:.0f}–{t.win_high:.0f}",
                    "playoff_pct": f"{t.playoff_pct:.1f}%",
                    "playoff_class": _probability_class(t.playoff_pct),
                    "champ_pct": f"{t.championship_pct:.1f}%",
                }
            )
        return rows

    def _build_team_cards(
        self,
        rosters: list[Roster],
        sim_result: SimulationResult,
        dynasty_outlooks: dict[int, DynastyOutlook],
        player_projections: dict[str, tuple[str, float]],
        player_names: dict[str, str],
        player_ages: dict[str, int | None],
    ) -> list[dict[str, Any]]:
        """Build one view-model dict per team card."""
        roster_map = {r.roster_id: r for r in rosters}
        sorted_team_results = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.playoff_pct,
            reverse=True,
        )

        cards: list[dict[str, Any]] = []
        for team_result in sorted_team_results:
            roster = roster_map.get(team_result.roster_id)
            if roster is None:
                continue

            outlook = dynasty_outlooks.get(team_result.roster_id)

            # Record string. Include ties only when present so the most
            # common ``W-L`` case stays clean.
            record = f"{roster.wins}-{roster.losses}"
            if roster.ties:
                record += f"-{roster.ties}"

            outlook_label = _outlook_label(team_result.playoff_pct)
            outlook_class = f"outlook-{outlook_label.lower()}"

            # Top-N projected players.
            scored: list[tuple[str, str, int | None, float]] = []
            for pid in roster.players:
                if pid in player_projections:
                    pos, proj = player_projections[pid]
                    scored.append(
                        (
                            player_names.get(pid, pid),
                            pos,
                            player_ages.get(pid),
                            proj,
                        )
                    )
            scored.sort(key=lambda x: x[3], reverse=True)
            top_players = [
                {
                    "name": name,
                    "pos": pos,
                    "age": str(age) if age is not None else "—",
                    "proj": f"{proj:.1f}",
                }
                for name, pos, age, proj in scored[:8]
            ]

            # Age-profile rows.
            age_rows: list[dict[str, str]] = []
            if outlook is not None and outlook.age_profile.avg_age_by_position:
                ap = outlook.age_profile
                young_by_pos: dict[str, list[str]] = {}
                risks_by_pos: dict[str, list[str]] = {}
                for p in ap.core_young:
                    young_by_pos.setdefault(p.position, []).append(p.full_name)
                for p in ap.aging_risks:
                    risks_by_pos.setdefault(p.position, []).append(p.full_name)
                for pos, avg in sorted(ap.avg_age_by_position.items()):
                    age_rows.append(
                        {
                            "pos": pos,
                            "avg": f"{avg:.1f}",
                            "aging": ", ".join(risks_by_pos.get(pos, [])) or "—",
                            "young": ", ".join(young_by_pos.get(pos, [])) or "—",
                        }
                    )

            # Draft capital rows.
            draft_rows: list[dict[str, str]] = []
            draft_status = "—"
            draft_net = "—"
            draft_traded = "—"
            draft_acquired = "—"
            if outlook is not None:
                dc = outlook.draft_capital
                by_season: dict[int, list[tuple[int, int]]] = {}
                for (season, rnd), count in sorted(dc.picks_by_season_round.items()):
                    by_season.setdefault(season, []).append((rnd, count))
                for season, total in sorted(dc.picks_by_season.items()):
                    breakdown = (
                        ", ".join(
                            f"R{rnd}: {count}"
                            for rnd, count in by_season.get(season, [])
                        )
                        or "—"
                    )
                    draft_rows.append(
                        {
                            "season": str(season),
                            "picks": str(total),
                            "breakdown": breakdown,
                        }
                    )
                draft_status = dc.status
                draft_net = f"{dc.net_vs_average:+.1f}"
                draft_traded = str(dc.picks_traded_away)
                draft_acquired = str(dc.picks_acquired)

            # Draft needs.
            needs = []
            if outlook is not None:
                for n in outlook.draft_needs:
                    needs.append(
                        {
                            "pos": n.position,
                            "urgency": n.urgency,
                            "reason": n.reason,
                        }
                    )

            cards.append(
                {
                    "owner_name": roster.owner_name,
                    "record": record,
                    "proj_record": (
                        f"{team_result.avg_wins:.1f}-"
                        f"{team_result.avg_losses:.1f}"
                    ),
                    "playoff_pct": f"{team_result.playoff_pct:.1f}%",
                    "champ_pct": f"{team_result.championship_pct:.1f}%",
                    "outlook_label": outlook_label,
                    "outlook_class": outlook_class,
                    "top_players": top_players,
                    "age_rows": age_rows,
                    "draft_rows": draft_rows,
                    "draft_status": draft_status,
                    "draft_net": draft_net,
                    "draft_traded": draft_traded,
                    "draft_acquired": draft_acquired,
                    "needs": needs,
                }
            )
        return cards

    def _build_weeks(
        self,
        sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> list[dict[str, Any]]:
        """Group matchup forecasts by week, sorted ascending."""
        by_week: dict[int, list[Any]] = {}
        for m in sim_result.matchup_results:
            by_week.setdefault(m.week, []).append(m)

        weeks: list[dict[str, Any]] = []
        for week in sorted(by_week.keys()):
            matchups = []
            for m in by_week[week]:
                team1 = roster_map.get(m.roster_id_1)
                team2 = roster_map.get(m.roster_id_2)
                name1 = team1.owner_name if team1 else f"Roster {m.roster_id_1}"
                name2 = team2.owner_name if team2 else f"Roster {m.roster_id_2}"
                if m.win_pct_1 >= m.win_pct_2:
                    favored = name1
                    favored_pct = m.win_pct_1
                else:
                    favored = name2
                    favored_pct = m.win_pct_2
                matchups.append(
                    {
                        "matchup": f"{name1} vs {name2}",
                        "favored": favored,
                        "win_pct": f"{favored_pct:.1f}%",
                        "win_class": _probability_class(favored_pct),
                        "score": f"{m.avg_score_1:.1f} – {m.avg_score_2:.1f}",
                    }
                )
            weeks.append({"week": week, "matchups": matchups})
        return weeks
