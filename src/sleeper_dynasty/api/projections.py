"""Projection data sources and the blend used by the simulator.

Two entry points matter to the rest of the pipeline:

- ``fetch_fantasypros_projections`` — scrapes stat-level season-total
  projections from FantasyPros for QB/RB/WR/TE/K/DEF. Returns a dict
  keyed by ``normalize_player_name(name)`` so the CLI can join against
  Sleeper players without exact-string-match fragility.
- ``blend_projections`` / ``normalize_projection`` — combine Sleeper +
  FantasyPros projections and convert raw stats to league-specific
  fantasy points.

The FantasyPros scraper uses BeautifulSoup. The HTML structure on
``/nfl/projections/<pos>.php`` is a sticky-column table with id="data"
and per-stat <td> cells; the final cell carries ``data-sort-value`` with
the FPTS total. We parse the column header row to know which raw stat
each column maps to, so a column reorder by FP won't silently break us.
"""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from sleeper_dynasty.models.player import FantasyProsProjection, PlayerProjection
from sleeper_dynasty.util.name_match import normalize_player_name

log = logging.getLogger(__name__)

FANTASYPROS_WEIGHT = 0.6
SLEEPER_WEIGHT = 0.4

# FantasyPros projection pages. ``week=draft`` returns season totals
# rather than the upcoming-week projection (which is the default).
_FANTASYPROS_BASE = "https://www.fantasypros.com/nfl/projections"
_FANTASYPROS_POSITIONS = ("qb", "rb", "wr", "te", "k", "dst")

# Header label -> canonical stat key. FantasyPros uses short labels in
# small caps in the second header row. The first header row groups them
# under PASSING / RUSHING / RECEIVING / MISC, which is how we
# disambiguate "ATT" (could be pass or rush) and "YDS" / "TDS".
_HEADER_GROUPS = ("PASSING", "RUSHING", "RECEIVING", "MISC")

# Mapping from (group, label) -> Sleeper-style scoring key.
# Sleeper's scoring_settings keys are e.g. pass_yd, pass_td, pass_int,
# rush_att, rush_yd, rush_td, rec, rec_yd, rec_td, fum_lost.
_STAT_KEY_BY_GROUP_LABEL: dict[tuple[str, str], str] = {
    ("PASSING", "ATT"): "pass_att",
    ("PASSING", "CMP"): "pass_cmp",
    ("PASSING", "YDS"): "pass_yd",
    ("PASSING", "TDS"): "pass_td",
    ("PASSING", "INTS"): "pass_int",
    ("RUSHING", "ATT"): "rush_att",
    ("RUSHING", "YDS"): "rush_yd",
    ("RUSHING", "TDS"): "rush_td",
    ("RECEIVING", "REC"): "rec",
    ("RECEIVING", "YDS"): "rec_yd",
    ("RECEIVING", "TDS"): "rec_td",
    ("MISC", "FL"): "fum_lost",
}

# K and DST pages don't use the grouped-header layout — they're a flat
# row of stat columns. Map the label directly.
_STAT_KEY_FLAT_K: dict[str, str] = {
    "FG": "fgm",
    "FGA": "fga",
    "XPT": "xpm",
}

_STAT_KEY_FLAT_DST: dict[str, str] = {
    "SACK": "def_sack",
    "INT": "def_int",
    "FR": "def_fr",
    "FF": "def_ff",
    "TD": "def_td",
    "SAFETY": "def_safe",
    "PA": "def_pa",
    "YDS AGN": "def_yds_allowed",
}


# ---------------------------------------------------------------------------
# Public blending / scoring helpers
# ---------------------------------------------------------------------------


def blend_projections(
    sleeper_proj: PlayerProjection,
    external_proj: PlayerProjection | None,
) -> PlayerProjection:
    """Weighted average of Sleeper and external (FantasyPros) projections.

    Sleeper alone is noisy; FantasyPros consensus is steadier. We weight
    FP higher when available but always fall back to Sleeper on its own.
    """
    if external_proj is None:
        return sleeper_proj
    blended_pts = (
        SLEEPER_WEIGHT * sleeper_proj.projected_points
        + FANTASYPROS_WEIGHT * external_proj.projected_points
    )
    return PlayerProjection(
        player_id=sleeper_proj.player_id,
        source="blended",
        season=sleeper_proj.season,
        week=sleeper_proj.week,
        projected_points=round(blended_pts, 2),
    )


def normalize_projection(stats: dict[str, float], scoring: dict[str, float]) -> float:
    """Convert raw stat projections to fantasy points using league scoring.

    Multiplies each stat by the league's scoring multiplier and sums.
    Missing multipliers default to 0 (so a stat the league doesn't score
    contributes nothing).
    """
    total = 0.0
    for stat_key, value in stats.items():
        multiplier = scoring.get(stat_key, 0.0)
        total += value * multiplier
    return round(total, 2)


# ---------------------------------------------------------------------------
# FantasyPros scraper
# ---------------------------------------------------------------------------


async def fetch_fantasypros_projections(
    season: int,
) -> dict[str, FantasyProsProjection]:
    """Fetch FantasyPros season-total projections for all skill positions.

    Returns:
        Dict keyed by ``normalize_player_name(player.name)``. Empty on
        network failure or parse error — callers should treat empty as a
        graceful degradation, not a hard failure.
    """
    log.info("Fetching FantasyPros projections for %d", season)
    projections: dict[str, FantasyProsProjection] = {}

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        for pos in _FANTASYPROS_POSITIONS:
            url = f"{_FANTASYPROS_BASE}/{pos}.php?week=draft&scoring=PPR"
            try:
                resp = await client.get(
                    url,
                    headers={
                        # FP rejects/empties responses for stripped-down UAs.
                        "User-Agent": (
                            "Mozilla/5.0 (compatible; sleeper-dynasty/0.1)"
                        ),
                    },
                )
            except httpx.HTTPError as e:
                log.warning("FantasyPros fetch failed for %s: %s", pos, e)
                continue

            if resp.status_code != 200:
                log.warning(
                    "FantasyPros returned %d for %s", resp.status_code, pos
                )
                continue

            parsed = parse_fantasypros_html(resp.text, pos.upper())
            if not parsed:
                log.warning(
                    "FantasyPros %s page parsed 0 players — page structure "
                    "may have changed",
                    pos,
                )
            projections.update(parsed)

    log.info("FantasyPros: %d projections parsed", len(projections))
    return projections


def parse_fantasypros_html(
    html: str,
    position: str,
) -> dict[str, FantasyProsProjection]:
    """Parse one FantasyPros projection page into a dict of projections.

    Args:
        html: Full page HTML.
        position: Uppercase position string (QB, RB, WR, TE, K, DST).

    Returns:
        Dict keyed by normalized name. Empty if the table or rows can't
        be found — we log a warning rather than raising so a transient
        FP outage doesn't kill the whole report.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="data")
    if table is None:
        log.warning(
            "FantasyPros %s: <table id='data'> not found; layout changed?",
            position,
        )
        return {}

    # Build column->stat_key mapping from the header.
    if position in {"K", "DST"}:
        column_keys = _flat_column_keys(table, position)
    else:
        column_keys = _grouped_column_keys(table)

    if not column_keys:
        log.warning(
            "FantasyPros %s: could not derive column headers; "
            "layout changed?",
            position,
        )
        return {}

    out: dict[str, FantasyProsProjection] = {}
    tbody = table.find("tbody")
    if tbody is None:
        return {}

    for tr in tbody.find_all("tr"):
        row = _parse_row(tr, position, column_keys)
        if row is None:
            continue
        out[row.normalized_name] = row

    return out


def _grouped_column_keys(table) -> list[str | None]:
    """Map columns -> stat key for the grouped-header layout (QB/RB/WR/TE).

    The thead has two rows:
      Row 1: blank cell, then group labels (PASSING/RUSHING/...) with
             colspan covering the columns in that group.
      Row 2: "Player" + a label per stat column.

    We walk row 1 to assign each column a group, then look up
    (group, label) for each row-2 cell. Returns a list aligned with the
    data <td> columns AFTER the Player cell — i.e. one entry per stat
    column (the last of which is FPTS, mapped to ``None``).
    """
    thead = table.find("thead")
    if thead is None:
        return []
    header_rows = thead.find_all("tr")
    if len(header_rows) < 2:
        return []

    # Row 1: assign a group label to each stat column index.
    groups: list[str] = []
    for cell in header_rows[0].find_all(["td", "th"]):
        text = cell.get_text(strip=True)
        # Skip leading blank/nbsp cell aligned with Player column.
        if not text or text in {"\xa0", "&nbsp;"}:
            continue
        if text not in _HEADER_GROUPS:
            # Unexpected header — bail rather than guess.
            return []
        colspan = int(cell.get("colspan", "1"))
        groups.extend([text] * colspan)

    # Row 2: stat label per column. First cell is "Player" — skip it.
    labels: list[str] = []
    for cell in header_rows[1].find_all(["th", "td"]):
        text = cell.get_text(strip=True)
        if text.lower() == "player":
            continue
        labels.append(text.upper())

    # The final label is "FPTS"; we extract it separately and don't need
    # to look it up in the stat map.
    column_keys: list[str | None] = []
    for i, label in enumerate(labels):
        if label == "FPTS":
            column_keys.append(None)  # sentinel; handled specially
            continue
        if i >= len(groups):
            return []
        column_keys.append(_STAT_KEY_BY_GROUP_LABEL.get((groups[i], label)))

    return column_keys


def _flat_column_keys(table, position: str) -> list[str | None]:
    """Map columns -> stat key for the flat K / DST layout.

    These pages don't have a group row — the thead has a single row of
    labels. Player + stat columns + FPTS.
    """
    thead = table.find("thead")
    if thead is None:
        return []
    rows = thead.find_all("tr")
    if not rows:
        return []
    # Use last header row (some pages still emit a single row).
    label_row = rows[-1]
    labels: list[str] = []
    for cell in label_row.find_all(["th", "td"]):
        text = cell.get_text(strip=True)
        if text.lower() == "player":
            continue
        labels.append(text.upper())

    table_map = _STAT_KEY_FLAT_K if position == "K" else _STAT_KEY_FLAT_DST

    column_keys: list[str | None] = []
    for label in labels:
        if label == "FPTS":
            column_keys.append(None)
            continue
        column_keys.append(table_map.get(label))
    return column_keys


def _parse_row(
    tr,
    position: str,
    column_keys: list[str | None],
) -> FantasyProsProjection | None:
    """Parse a single <tr> into a FantasyProsProjection, or None on bad row."""
    cells = tr.find_all("td")
    if not cells:
        return None

    # First cell holds the player anchor and a trailing team abbreviation.
    name_cell = cells[0]
    anchor = name_cell.find("a", class_="player-name")
    if anchor is None:
        return None
    name = anchor.get_text(strip=True)
    if not name:
        return None

    # Team: trailing text after the anchor, e.g. "Jalen Hurts PHI".
    # For DST the cell can just contain the team name with no trailing
    # abbreviation, so team may be None.
    full_text = name_cell.get_text(" ", strip=True)
    team: str | None = None
    if full_text.startswith(name):
        tail = full_text[len(name):].strip()
        if tail:
            # The team abbreviation should be the last whitespace token.
            team = tail.split()[-1].upper()

    stat_cells = cells[1:]
    # Defensive: if column count drifted, take the min so we don't index
    # off the end. We still extract FPTS from whichever cell has the
    # data-sort-value attribute.
    n = min(len(stat_cells), len(column_keys))

    stats: dict[str, float] = {}
    projected_points_ppr = 0.0

    for i in range(n):
        key = column_keys[i]
        cell = stat_cells[i]
        # FPTS column: prefer data-sort-value (more precision than the
        # display text, which is rounded to 1 decimal).
        if key is None:
            sort_val = cell.get("data-sort-value")
            raw = sort_val if sort_val is not None else cell.get_text(strip=True)
            try:
                projected_points_ppr = float(raw.replace(",", ""))
            except (ValueError, AttributeError):
                projected_points_ppr = 0.0
            continue

        raw_text = cell.get_text(strip=True).replace(",", "")
        try:
            stats[key] = float(raw_text)
        except ValueError:
            # Cell wasn't a number — skip silently for that stat.
            continue

    return FantasyProsProjection(
        name=name,
        normalized_name=normalize_player_name(name),
        team=team,
        position=position if position != "DST" else "DEF",
        stats=stats,
        projected_points_ppr=round(projected_points_ppr, 2),
    )
