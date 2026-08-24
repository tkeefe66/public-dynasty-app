from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from sleeper_dynasty.util.atomic import write_json_atomic

DEFAULT_TTL = 24 * 3600

SCHEMA_VERSION = 17  # bumped: v2 Results/Assets signals (expected_wins reads 0.0 as a real value)


@dataclass
class ChainCacheEntry:
    """Single-blob cache entry covering one league chain's full graded state.

    Stores raw dicts (not the typed dataclasses) so the cache file is
    self-describing and survives non-breaking schema changes.
    """

    league_id: str
    chain: list[dict[str, Any]]
    resolved_trades: list[dict[str, Any]]
    grades: dict[str, dict[str, Any]]
    owners: dict[str, dict[str, Any]]
    playoff_weeks_by_league: dict[str, int]
    roster_to_user_by_league: dict[str, dict[int, str]]
    league_name_by_id: dict[str, str]
    league_season_by_id: dict[str, int]
    cached_at: str
    warnings: list[str] = field(default_factory=list)
    trade_stories: dict[str, dict[str, Any]] = field(default_factory=dict)
    owner_dossiers: dict[str, dict[str, Any]] = field(default_factory=dict)
    current_holders: dict[str, str] = field(default_factory=dict)
    # trade_id -> {user_id -> BecameMetrics-dict + "terminal_hash"}; see regrade.
    became_grades: dict[str, dict[str, Any]] = field(default_factory=dict)
    # GM-rating pillar signals (uid -> {signal: value}), computed at refresh.
    outcome_signals: dict[str, dict[str, float]] = field(default_factory=dict)
    outlook_signals: dict[str, dict[str, float]] = field(default_factory=dict)
    # GM-rating Skill pillar: per-owner lineup efficiency {uid: {"lineup_skill": float}}.
    # Redesign signal; empty on pre-migration caches.
    lineup_signals: dict[str, dict[str, float]] = field(default_factory=dict)
    # uid -> serialized DynastyOutlook (see engine/outlook_build.outlook_to_dict)
    dynasty_outlooks: dict[str, dict[str, Any]] = field(default_factory=dict)
    # uid -> {"rank": int, "of": int} by current roster KTC value
    roster_ranks: dict[str, dict[str, int]] = field(default_factory=dict)
    # scope ("all"|str(year)) -> uid -> {blurb, facts_hash, generated_at}
    owner_rating_blurbs: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    # uid -> {blurb, facts_hash, generated_at}
    franchise_blurbs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # str(year) -> {uid: rating} — synthetic per-season GM ratings computed at refresh.
    # Used as historical baselines for the context-aware riser KPI card.
    season_ratings: dict[str, dict[str, int]] = field(default_factory=dict)
    # str(year) -> {uid: skill_score} — per-season rookie draft skill for Draft Ace card.
    draft_skill_by_season: dict[str, dict[str, float]] = field(default_factory=dict)
    # str(year) -> {uid -> season record dict}
    # Keys per uid: wins, losses, ties, rank (1-based), total_teams, champion, runner_up, made_playoffs
    season_records: dict[str, dict[str, dict]] = field(default_factory=dict)
    # uid -> {opponent_uid -> record dict} — all-time regular-season head-to-head
    # across the chain. Keys per record: opponent_id, wins, losses, ties,
    # points_for, points_against. Empty on pre-feature caches.
    head_to_head: dict[str, dict[str, dict]] = field(default_factory=dict)
    # Per-pick rookie-draft results for the Future & Draft tab (one dict per pick;
    # keys per engine/draft_results.build_drafted_pick_results). Includes drafter_id
    # so owner_view can group per owner. Empty on pre-feature caches.
    drafted_picks: list[dict] = field(default_factory=list)
    # Production timeline (phase 1). Mirrors the value-series fields but keyed by
    # (season, week) and per metric ("total"|"regular"|"playoff"|"toilet").
    # trade_production_series: tx -> uid -> metric -> [[season, week, points], ...]
    trade_production_series: dict = field(default_factory=dict)
    # trade_production_verdict: tx -> metric -> verdict dict
    trade_production_verdict: dict = field(default_factory=dict)
    # owner_production_series: uid -> {"received"|"given"} -> metric -> series
    owner_production_series: dict = field(default_factory=dict)
    # owner_production_verdict: uid -> metric -> verdict dict
    owner_production_verdict: dict = field(default_factory=dict)
    # production_week_axis: [[season, week], ...]
    production_week_axis: list = field(default_factory=list)
    # production_week_phases: ["regular"|"post", ...] parallel to the axis (playoff highlight)
    production_week_phases: list = field(default_factory=list)
    # drill series. trade_production_players: tx -> uid -> [{player_id, byMetric}]
    trade_production_players: dict = field(default_factory=dict)
    # owner_production_trades: uid -> [{trade_id, byMetric}]
    owner_production_trades: dict = field(default_factory=dict)
    # injury context (Phase 2a): tx -> uid -> player_id -> injury block
    trade_injury: dict = field(default_factory=dict)
    # departures: tx -> uid -> [{player_id, season, week, kind}] (dropped/traded received players)
    trade_departures: dict = field(default_factory=dict)
    # League-calendar phase as of the last refresh: {"phase", "season", "week"}
    # (see services/league_phase.py). Always recomputed (as-of-today value
    # layer, never frozen). Empty on pre-feature caches -> dashboard falls
    # back to "offseason" until the next refresh stamps it.
    league_phase: dict = field(default_factory=dict)
    # Most recent COMPLETED regular-season week's recap for the dashboard lead:
    # {"season", "week", "high_score", "blowout", "traded_points"} (see
    # services/week_recap.py). Same tier as league_phase — as-of-today value
    # layer, always recomputed, never frozen. Empty on pre-feature caches and
    # outside the regular season -> the lead keeps its placeholder skeleton.
    week_recap: dict = field(default_factory=dict)
    # What this league supports: {"format", "future_picks", "roster_continuity",
    # "multiyear_history"} (see engine/capabilities.py). Same tier as
    # league_phase — as-of-today value layer, always recomputed, never frozen.
    # Empty on pre-feature caches -> capabilities_from_dict returns full
    # dynasty, so existing leagues are unaffected until their next refresh.
    capabilities: dict = field(default_factory=dict)
    # Live title-path state for the postseason lead: {"season", "entered",
    # "alive", "alive_count", "eliminated", "top_seed_user_id", "top_seed"}
    # (see engine/playoff_phase.py::build_bracket_watch). Same tier as
    # league_phase — as-of-today value layer, always recomputed, NEVER frozen:
    # who is still alive changes every playoff week, so copying it from a
    # prior entry would stall the bracket mid-postseason. Empty on pre-feature
    # caches and outside the playoffs -> the lead keeps its placeholder.
    bracket_watch: dict = field(default_factory=dict)
    # ISO timestamp of the last LLM-regeneration pass (trade stories / blurbs).
    # Drives the cadence throttle in GraderService.run. None on pre-feature
    # caches (treated as "never generated" -> first refresh evaluates normally).
    llm_generated_at: str | None = None
    # Draft-day "needs" panel: str(season) -> [OwnerNeedsResp-shaped dict, ...]
    # (user_id, holes, drafted_into, started, drafted_into_count, slots -- no
    # starters_by_slot, see api/app/models/league.py::OwnerNeedsResp). NOT
    # the same thing as `dynasty_outlooks[uid]["draft_needs"]`
    # (`engine/dynasty.py::assess_draft_needs`, a list of
    # `DraftNeed{position, urgency, reason, held, ideal, kind}` nested inside a
    # roster's `DynastyOutlook` and surfaced via `owner_view.py`'s
    # `DraftNeedView`) -- that one is a roster-depth/aging-risk read of the
    # CURRENT roster, always-on, unrelated to any specific draft. This field
    # is a reconstructed DRAFT-DAY roster graded against what the draft
    # itself did about it. Two draft_needs concepts, no shared code, no
    # runtime conflict (different namespaces), kept apart deliberately.
    #
    # Same tier as league_phase/capabilities -- as-of-today value layer,
    # ALWAYS recomputed, never frozen: refresh_delta.py derives
    # new-transaction ids from trades only, so a completed draft would not
    # invalidate a frozen copy and the panel would be missing for the newest
    # class during exactly the draft window where it is the point.
    #
    # Populated only for the newest gradeable draft class (roster
    # reconstruction needs a real get_roster_transactions fetch -- an
    # 18-week walk per league id -- not the microsecond compute the rest of
    # this stage is; walking every season on every refresh would multiply
    # that fetch by chain length for no benefit, since only the current
    # draft window is ever the point) and only when the league's
    # capabilities pass format == "dynasty" AND roster_continuity AND
    # multiyear_history.
    #
    # format == "dynasty", NOT merely roster_continuity: keeper leagues also
    # report roster_continuity=True (`_CONTINUOUS_FORMATS =
    # {"dynasty", "keeper"}` in engine/capabilities.py) but cannot actually
    # be reconstructed -- keepers enter the new season THROUGH THE DRAFT
    # (`is_keeper` on a pick), never via a transaction, so the
    # transaction-only roster_asof reconstruction has no signal for the
    # annual release of everyone else and hands back the whole prior
    # roster as "still there": every slot full, zero holes leaguewide,
    # confidently wrong rather than absent. See GraderService.run's gate
    # comment for the full reasoning.
    #
    # This dict is REBUILT FROM SCRATCH every refresh and never merged with
    # the prior entry's draft_needs, so a season stops being "the newest" and
    # its already-computed, already-served panel is DROPPED on the very next
    # refresh -- not merely "not recomputed", but actively removed from what
    # was served before. That is deliberate, not an oversight: the panel
    # rests on this module's own hole-detection logic, which has already had
    # two Critical fixes; carrying an old season's answer forward would mean
    # serving output computed by since-corrected logic, indefinitely, with no
    # way to tell it apart from a fresh one. Correctness was chosen over
    # coverage. A future fix that wants "keep last season's panel visible
    # after this season's draft" needs BOTH per-season persistence (append
    # rather than replace) AND an invalidation signal tied to engine-logic
    # changes (something like a hole-detection version stamped alongside each
    # season's entry, so a logic change can selectively invalidate stored
    # seasons) -- neither exists today.
    #
    # Empty on pre-feature caches -> build_draft_board serves None (absent,
    # not []) so the frontend omits the panel until the next refresh stamps it.
    draft_needs: dict[str, list[dict]] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION


class ChainCache:
    """Single-blob cache for one league chain's full graded state."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        # League IDs are numeric strings; safe filename.
        return self.cache_dir / f"chain_{league_id}.json"

    def read(
        self, league_id: str, max_age_seconds: int = DEFAULT_TTL
    ) -> ChainCacheEntry | None:
        path = self._path(league_id)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > max_age_seconds:
            return None
        with open(path) as f:
            raw = json.load(f)
        # Stale schema (e.g. pre-bracket grades) -> re-grade.
        if raw.get("schema_version") != SCHEMA_VERSION:
            return None
        # Pre-migration entries lack `owners`; treat as a miss so the
        # cold-start flow re-pulls and re-grades them.
        if "owners" not in raw:
            return None
        # roster_to_user_by_league keys come back as strings from JSON; coerce.
        rmap = raw.get("roster_to_user_by_league") or {}
        coerced = {
            lg: {int(k): v for k, v in (m or {}).items()}
            for lg, m in rmap.items()
        }
        raw["roster_to_user_by_league"] = coerced
        # Drop any since-removed fields so an evolving schema can't 500 the
        # read path (e.g. the retired `trade_value_series`). New fields absent
        # from older entries fall back to their dataclass defaults.
        known = {f.name for f in fields(ChainCacheEntry)}
        raw = {k: v for k, v in raw.items() if k in known}
        return ChainCacheEntry(**raw)

    def write(self, league_id: str, entry: ChainCacheEntry) -> None:
        write_json_atomic(self._path(league_id), asdict(entry))

    def invalidate(self, league_id: str) -> None:
        path = self._path(league_id)
        if path.exists():
            path.unlink()
