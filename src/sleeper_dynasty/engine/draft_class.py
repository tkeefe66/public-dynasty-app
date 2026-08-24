"""Draft normalization: what each Sleeper draft *is*, decided once.

Every format question about a draft — is this a rookie class or a full
draft, can it be graded, what does it get graded against — is answered here
and nowhere else. Downstream consumers read the descriptor rather than
re-deriving the answer, which is what stops "is this dynasty?" from being
asked in five places and drifting apart.

Pure. No I/O — callers thread in the draft and pick payloads.
"""

from __future__ import annotations

from dataclasses import dataclass

from sleeper_dynasty.engine.draft_signals import DraftedPick

# Sleeper's draft setting: 1 = rookies only, 0 = all players. Verified live
# against a real dynasty rookie draft (player_type == 1).
_ROOKIE_ONLY = 1

# Formats whose graded event is the whole-league draft, every season.
_FULL_DRAFT_FORMATS = {"redraft", "keeper"}

# An auction's pick_no is chronological, not positional, so a slot delta
# would be noise. Ingested for results, never graded.
_UNGRADEABLE_TYPES = {"auction"}


@dataclass(frozen=True)
class DraftClass:
    """One completed draft, described in format-neutral terms."""

    draft_id: str
    league_id: str
    season: int
    kind: str        # "rookie" | "full"
    draft_type: str  # "snake" | "linear" | "auction"
    teams: int
    gradeable: bool  # False for auction — results only
    axis: str        # "blend" (value + production) | "production"


def build_draft_classes(
    *,
    drafts_by_league: dict[str, list[dict]],
    league_format: str,
    origin_season: int,
) -> list[DraftClass]:
    """Select and describe the drafts this league's format actually grades.

    Dynasty grades rookie classes and discards the startup. Redraft and keeper
    grade every season's full draft, *including year one* — there is no
    "startup" in a league that redrafts from scratch annually.

    ``settings.player_type`` restricts the selectable **pool**; it does not
    name the kind of draft. Dynasty selection therefore uses it as one signal,
    not the whole rule:

    - ``1`` (rookies only) — a rookie class outright, whatever the season. This
      is what lets a league that ran a startup *and* a rookie draft in the same
      origin season keep the rookie class.
    - ``0`` (open pool) or absent — not evidence of a startup. Dynasty leagues
      routinely run their annual rookie draft with the pool open so a manager
      may take a veteran free agent instead. Falls back to the question that
      actually separates the two: was this the league's first season? A startup
      drafts whole rosters, once, at the beginning.
    """
    full_draft_league = league_format in _FULL_DRAFT_FORMATS
    axis = "production" if full_draft_league else "blend"

    out: list[DraftClass] = []
    for league_id, drafts in drafts_by_league.items():
        for d in drafts:
            if d.get("status") != "complete":
                continue
            settings = d.get("settings") or {}
            season = int(d.get("season") or 0)
            player_type = settings.get("player_type")

            # `player_type` restricts the selectable POOL; it does not say what
            # kind of draft this is. 1 ("rookies only") is a positive signal and
            # is trusted outright. 0 ("open pool") is NOT evidence of a startup:
            # plenty of dynasty leagues run their annual rookie draft with the
            # pool left open so a manager may take a veteran free agent instead.
            # Observed live — a real 4-round rookie draft, 28 of 48 picks
            # rookies, sitting at player_type 0.
            #
            # So an open pool falls back to the question that actually separates
            # a startup from a rookie class: was it the league's first season? A
            # startup drafts whole rosters, once, at the beginning.
            rookies_only = (
                player_type is not None and int(player_type) == _ROOKIE_ONLY
            )
            if full_draft_league:
                kind = "full"
            elif rookies_only:
                kind = "rookie"
            elif season == origin_season:
                continue  # dynasty startup: open pool, first season
            else:
                kind = "rookie"

            draft_type = str(d.get("type") or "snake")
            out.append(DraftClass(
                draft_id=str(d["draft_id"]),
                league_id=league_id,
                season=season,
                kind=kind,
                draft_type=draft_type,
                teams=int(settings.get("teams") or 0),
                gradeable=draft_type not in _UNGRADEABLE_TYPES,
                axis=axis,
            ))
    return out


def build_draft_picks(
    *,
    classes: list[DraftClass],
    picks_by_draft_id: dict[str, list[dict]],
    roster_to_user_by_league: dict[str, dict[int, str]],
) -> list[DraftedPick]:
    """Normalize each class's picks into ``DraftedPick`` rows.

    Credits ``picked_by``, falling back to the slot roster's current owner.
    A pick with neither a player nor a resolvable drafter is dropped — there
    is nothing to grade and a placeholder would pollute the peer baseline.
    """
    out: list[DraftedPick] = []
    for cls in classes:
        r2u = roster_to_user_by_league.get(cls.league_id, {})
        teams = cls.teams or len(r2u) or 1
        for pk in picks_by_draft_id.get(cls.draft_id, []):
            player_id = pk.get("player_id")
            if not player_id:
                continue
            drafter = pk.get("picked_by") or r2u.get(pk.get("roster_id"))
            if not drafter:
                continue
            rnd = int(pk.get("round") or 1)
            slot = int(pk.get("draft_slot") or 0)
            # Sleeper sends pick_no, but derive it when absent so the overall
            # position is always available for ADP comparison.
            pick_no = int(pk.get("pick_no") or ((rnd - 1) * teams + slot))
            out.append(DraftedPick(
                draft_id=cls.draft_id,
                round=rnd,
                slot=slot,
                picks_in_round=teams,
                player_id=str(player_id),
                drafter_id=str(drafter),
                draft_season=cls.season,
                pick_no=pick_no,
                draft_kind=cls.kind,
                is_keeper=bool(pk.get("is_keeper")),
                gradeable=cls.gradeable,
            ))
    return out
