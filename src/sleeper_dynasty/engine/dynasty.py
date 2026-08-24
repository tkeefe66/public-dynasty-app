"""Dynasty outlook engine for long-term competitive analysis.

Analyzes each team's age profile, draft capital position and draft needs to
produce a multi-year dynasty outlook. Used by the CLI and output layers to
populate the "5-Year Dynasty Outlook" section of team reports.

There is no competitive-window stage here — see
`engine/gm_rating.py::rating_to_stage`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from sleeper_dynasty.models.league import DraftPick, Roster
from sleeper_dynasty.models.player import Player

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RB_AGING_THRESHOLD = 26
DEFAULT_AGING_THRESHOLD = 28
CORE_YOUNG_MAX_AGE = 25
OUTLOOK_SEASONS = [2027, 2028, 2029]

# Positions to skip in dynasty analysis (non-skill positions).
_SKIP_POSITIONS = {"K", "DEF"}

# Draft capital classification thresholds (net picks vs average).
_PICK_RICH_THRESHOLD = 3
_PICK_POOR_THRESHOLD = -3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AgeProfile:
    """Age analysis for a roster's skill-position players."""

    avg_age_by_position: dict[str, float]
    aging_risks: list[Player]
    core_young: list[Player]
    overall_avg_age: float


@dataclass
class DraftCapital:
    """Draft capital analysis for a roster across outlook seasons."""

    picks_by_season: dict[int, int]
    picks_by_season_round: dict[tuple[int, int], int]
    picks_traded_away: int
    picks_acquired: int
    net_vs_average: float
    status: str  # "pick-rich", "neutral", "pick-poor"


@dataclass
class DraftNeed:
    """A positional need identified from roster and age analysis.

    ``held``/``ideal`` are emitted on EVERY need, but only ``kind == "depth"``
    is a shortfall against ``ideal``, and that is the only row the UI draws
    depth pips on. The starter-quality branch fires at any count, and the
    aging-out branch is an ``elif`` reached only when
    ``current_count >= ideal_depth`` — pips there would draw a FULL room
    beside a live need.

    ``kind`` exists because ``urgency`` cannot carry this: the depth branch and
    the aging branch both emit "developing".
    """

    position: str
    urgency: str  # "immediate" or "developing"
    reason: str
    # Players at this position on the roster, and the roster-construction
    # target for it (`_IDEAL_DEPTH`).
    held: int = 0
    ideal: int = 0
    # "starters" | "quality" | "depth" | "aging" — which branch fired.
    kind: str = ""


@dataclass
class DynastyOutlook:
    """Roster-shape reading for a single roster: how old it is, what picks it
    holds, and what it is short of.

    It carries NO competitive-window stage. The stage is
    `engine/gm_rating.py::rating_to_stage`, a band on the Franchise Rating
    composite — one model, not two arithmetics over the same evidence, free to
    disagree on adjacent tabs of one page. `ktc_position_rankings` still feeds
    `assess_draft_needs`, so what is left is coherent on its own.
    """

    age_profile: AgeProfile
    draft_capital: DraftCapital
    draft_needs: list[DraftNeed]


# ---------------------------------------------------------------------------
# Age profile analysis
# ---------------------------------------------------------------------------


def analyze_age_profile(
    players: list[Player],
    as_of: date | None = None,
) -> AgeProfile:
    """Calculate age statistics for a roster's players.

    Computes average age by position, identifies aging risks (players at or
    above position-specific thresholds), and identifies core young pieces
    (players 25 or under). K and DEF positions are skipped.

    Args:
        players: List of Player objects on the roster.
        as_of: Reference date for age calculation. Defaults to today.

    Returns:
        AgeProfile with per-position averages, aging risks, and young core.
    """
    ref_date = as_of or date.today()

    ages_by_position: dict[str, list[int]] = {}
    aging_risks: list[Player] = []
    core_young: list[Player] = []
    all_ages: list[int] = []

    for player in players:
        if player.position in _SKIP_POSITIONS:
            continue

        age = player.age(as_of=ref_date)
        if age is None:
            continue

        ages_by_position.setdefault(player.position, []).append(age)
        all_ages.append(age)

        # Determine aging threshold based on position.
        threshold = (
            RB_AGING_THRESHOLD
            if player.position == "RB"
            else DEFAULT_AGING_THRESHOLD
        )

        if age >= threshold:
            aging_risks.append(player)

        if age <= CORE_YOUNG_MAX_AGE:
            core_young.append(player)

    avg_age_by_position: dict[str, float] = {}
    for pos, ages in ages_by_position.items():
        avg_age_by_position[pos] = sum(ages) / len(ages)

    overall_avg_age = sum(all_ages) / len(all_ages) if all_ages else 0.0

    logger.info(
        "Age profile: overall avg %.1f, %d aging risks, %d core young",
        overall_avg_age,
        len(aging_risks),
        len(core_young),
    )

    return AgeProfile(
        avg_age_by_position=avg_age_by_position,
        aging_risks=aging_risks,
        core_young=core_young,
        overall_avg_age=overall_avg_age,
    )


# ---------------------------------------------------------------------------
# Draft capital analysis
# ---------------------------------------------------------------------------


def analyze_draft_capital(
    roster_id: int,
    traded_picks: list[DraftPick],
    total_rosters: int,
    num_rounds: int = 4,
) -> DraftCapital:
    """Analyze a roster's draft capital across outlook seasons.

    For each outlook season, starts with the default allotment (num_rounds
    picks) and then adjusts based on traded picks: subtract picks whose
    original owner is this roster but current owner differs (traded away),
    and add picks whose current owner is this roster but original owner
    differs (acquired).

    Args:
        roster_id: The roster ID to analyze.
        traded_picks: All traded/draft pick records across the league.
        total_rosters: Number of rosters in the league.
        num_rounds: Number of draft rounds per season.

    Returns:
        DraftCapital with per-season counts, trade tracking, and classification.
    """
    picks_by_season: dict[int, int] = {}
    picks_by_season_round: dict[tuple[int, int], int] = {}
    picks_traded_away = 0
    picks_acquired = 0

    for season in OUTLOOK_SEASONS:
        # Start with default allotment: one pick per round.
        season_picks = num_rounds

        # Filter traded picks for this season.
        season_traded = [p for p in traded_picks if p.season == season]

        for pick in season_traded:
            if (
                pick.original_owner_id == roster_id
                and pick.current_owner_id != roster_id
            ):
                # This roster's pick was traded away.
                season_picks -= 1
                picks_traded_away += 1
            elif (
                pick.current_owner_id == roster_id
                and pick.original_owner_id != roster_id
            ):
                # This roster acquired someone else's pick.
                season_picks += 1
                picks_acquired += 1

        picks_by_season[season] = season_picks

        # Track by round within season.
        for pick in season_traded:
            if pick.current_owner_id == roster_id:
                key = (season, pick.round)
                picks_by_season_round[key] = (
                    picks_by_season_round.get(key, 0) + 1
                )

        # Also count own picks that were NOT traded away, by round.
        own_rounds_traded = set()
        for pick in season_traded:
            if (
                pick.original_owner_id == roster_id
                and pick.current_owner_id != roster_id
            ):
                own_rounds_traded.add(pick.round)

        for rd in range(1, num_rounds + 1):
            if rd not in own_rounds_traded:
                key = (season, rd)
                picks_by_season_round[key] = (
                    picks_by_season_round.get(key, 0) + 1
                )

    # Compute net vs average.
    # Average picks per team across all outlook seasons = num_rounds * len(OUTLOOK_SEASONS).
    total_picks = sum(picks_by_season.values())
    expected_total = num_rounds * len(OUTLOOK_SEASONS)
    net_vs_average = total_picks - expected_total

    # Classify capital status.
    if net_vs_average >= _PICK_RICH_THRESHOLD:
        status = "pick-rich"
    elif net_vs_average <= _PICK_POOR_THRESHOLD:
        status = "pick-poor"
    else:
        status = "neutral"

    logger.info(
        "Draft capital for roster %d: %d total picks, net %+.0f vs avg (%s)",
        roster_id,
        total_picks,
        net_vs_average,
        status,
    )

    return DraftCapital(
        picks_by_season=picks_by_season,
        picks_by_season_round=picks_by_season_round,
        picks_traded_away=picks_traded_away,
        picks_acquired=picks_acquired,
        net_vs_average=net_vs_average,
        status=status,
    )


# ---------------------------------------------------------------------------
# Draft needs assessment
# ---------------------------------------------------------------------------

# Minimum starters by position for a competitive dynasty roster.
_MIN_STARTERS: dict[str, int] = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 1,
}

# Ideal depth by position (starters + backups).
_IDEAL_DEPTH: dict[str, int] = {
    "QB": 2,
    "RB": 4,
    "WR": 5,
    "TE": 2,
}


def assess_draft_needs(
    roster_players: list[Player],
    position_rankings: dict[str, list[str]],
    age_profile: AgeProfile,
    total_rosters: int,
) -> list[DraftNeed]:
    """Identify positional needs based on roster composition and aging risks.

    Cross-references current roster depth, player quality rankings, and
    aging risks to produce a prioritized list of draft needs.

    Args:
        roster_players: Players on the roster.
        position_rankings: position -> ordered list of player_ids (best first).
        age_profile: Pre-computed AgeProfile for the roster.
        total_rosters: Number of teams in the league (for starter thresholds).

    Returns:
        List of DraftNeed objects sorted by urgency.
    """
    needs: list[DraftNeed] = []

    # Count skill-position players by position.
    pos_counts: dict[str, int] = {}
    pos_players: dict[str, list[Player]] = {}
    for player in roster_players:
        if player.position in _SKIP_POSITIONS:
            continue
        pos_counts[player.position] = pos_counts.get(player.position, 0) + 1
        pos_players.setdefault(player.position, []).append(player)

    # Check each position for needs.
    for pos, ideal_depth in _IDEAL_DEPTH.items():
        current_count = pos_counts.get(pos, 0)

        # Immediate need: below minimum starters.
        if current_count < _MIN_STARTERS.get(pos, 1):
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="immediate",
                    reason=f"Only {current_count} {pos}(s) on roster, "
                    f"need at least {_MIN_STARTERS[pos]}",
                    held=current_count, ideal=ideal_depth, kind="starters",
                )
            )
            continue

        # Check quality: are our starters ranked poorly league-wide?
        if pos in position_rankings:
            rankings = position_rankings[pos]
            starter_threshold = _MIN_STARTERS.get(pos, 1) * total_rosters
            our_players = pos_players.get(pos, [])

            # Count how many of our players are ranked in the starter tier.
            starters_ranked = sum(
                1
                for p in our_players
                if p.player_id in rankings[:starter_threshold]
            )

            if starters_ranked < _MIN_STARTERS.get(pos, 1):
                needs.append(
                    DraftNeed(
                        position=pos,
                        urgency="immediate",
                        reason=f"No {pos} ranked in starter tier "
                        f"(top {starter_threshold})",
                        held=current_count, ideal=ideal_depth, kind="quality",
                    )
                )
                continue

        # Developing need: below ideal depth OR aging risk at position.
        aging_at_pos = [
            p for p in age_profile.aging_risks if p.position == pos
        ]
        if current_count < ideal_depth:
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="developing",
                    reason=f"{current_count}/{ideal_depth} {pos}(s) on roster",
                    held=current_count, ideal=ideal_depth, kind="depth",
                )
            )
        elif aging_at_pos:
            needs.append(
                DraftNeed(
                    position=pos,
                    urgency="developing",
                    reason=f"{len(aging_at_pos)} {pos}(s) aging out "
                    f"({', '.join(p.full_name for p in aging_at_pos)})",
                    held=current_count, ideal=ideal_depth, kind="aging",
                )
            )

    # Sort: immediate needs first, then developing.
    urgency_order = {"immediate": 0, "developing": 1}
    needs.sort(key=lambda n: urgency_order.get(n.urgency, 2))

    logger.info("Identified %d draft needs", len(needs))
    return needs


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def build_dynasty_outlook(
    roster: Roster,
    roster_players: list[Player],
    traded_picks: list[DraftPick],
    position_rankings: dict[str, list[str]],
    total_rosters: int,
    num_rounds: int = 4,
) -> DynastyOutlook:
    """Build the roster-shape reading for a single roster.

    Six parameters died with the window model — `projected_rank_pct`,
    `ktc_value_by_player`, `draft_skill`, `playoff_rate`, `yoy_rating_delta`
    and `draft_capital_pct_rank`. They are gone rather than defaulted: a
    signature that still names an input nothing reads is a signature that
    lies about what the function needs.

    Args:
        roster: The roster to analyze.
        roster_players: Player objects for all players on the roster.
        traded_picks: All traded pick records across the league.
        position_rankings: position -> ordered list of player_ids (best first).
        total_rosters: Number of teams in the league.
        num_rounds: Number of draft rounds per season.

    Returns:
        DynastyOutlook for the roster.
    """
    logger.info("Building dynasty outlook for roster %d", roster.roster_id)

    age_profile = analyze_age_profile(roster_players)

    draft_capital = analyze_draft_capital(
        roster_id=roster.roster_id,
        traded_picks=traded_picks,
        total_rosters=total_rosters,
        num_rounds=num_rounds,
    )

    draft_needs = assess_draft_needs(
        roster_players=roster_players,
        position_rankings=position_rankings,
        age_profile=age_profile,
        total_rosters=total_rosters,
    )

    logger.info(
        "Dynasty outlook for roster %d: %d needs, capital %s",
        roster.roster_id, len(draft_needs), draft_capital.status,
    )
    return DynastyOutlook(
        age_profile=age_profile,
        draft_capital=draft_capital,
        draft_needs=draft_needs,
    )
