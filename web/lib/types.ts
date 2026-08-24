export type Lens = "ktc" | "production";
export type Year = number | "all";

export interface OwnerRef {
  user_id: string;
  owner_name: string;
  team_name?: string;
  avatar_url?: string;
}

export interface LeagueSummary {
  league_id: string;
  name: string;
  season: number;
  total_rosters: number;
  status: string;
  seasons?: number[];
  last_refreshed?: string;
}

export interface HeroStat {
  value: string;
  context: string;
  label?: string;
  owner?: string;
  owner_user_id?: string;
  trade_id?: string;
  date?: string;
  counterparty?: string;
  counterparty_user_id?: string;
}

export interface HeroStats {
  top_gm: HeroStat;
  biggest_weekly_rise: HeroStat;
  best_roster: HeroStat;
  draft_ace: HeroStat;
}

export interface StandingRow {
  rank: number;
  user_id: string;
  owner: OwnerRef;
  net_ktc: number;
  net_ktc_at_trade: number;
  net_ktc_aged: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  /** Starters-only across every week — what this owner actually DEPLOYED, as
   *  opposed to what their hauls accumulated. Optional: absent from a response
   *  served before the field was added. */
  production_started?: number;
  trades: number;
  grade: string;
  /** Null for an unrated franchise — one with no completed season behind it
   *  (`franchise_redesign.rated_owners`). The API has always typed these
   *  three as nullable (`api/app/models/league.py`); TS omitted the `| null`
   *  because nothing produced one until the thin-evidence gate landed. */
  gm_rating?: number | null;
  /** Franchise Rating letter (gm_rating mapped to a letter). */
  gm_letter?: string | null;
  gm_rank?: number | null;
  gm_trend?: number;
  /** The three Outlook-derived fields. All null together in a redraft league,
   *  which has no Outlook pillar at all (aggregations.py) — StandingsTable
   *  then omits the Window / Draft cap columns entirely rather than ruling
   *  them out as em-dashes. `window` is DERIVED from `gm_rating` on this same
   *  row (rating_to_stage), so the two can never disagree. Also null for an
   *  unrated franchise. */
  window?: string | null;
  draft_capital_value?: number | null;
  /** Today's roster-value rank among the league (1 = strongest roster).
   *  Null together in a redraft league — nothing carries over between
   *  seasons there, so there is no roster to rank (same `_outlooks_apply`
   *  gate as the Outlook fields above, but tracked as its own signal since
   *  a future format could carry one without the other). Also absent on
   *  pre-feature caches and for an owner with no ranking computed yet. */
  roster_rank?: number | null;
  roster_of?: number | null;
  season_record?: string | null;
  best_finish?: string | null;
  season_wins?: number | null;
  season_rank?: number | null;
  playoff_record?: string | null;
}

export interface LatestTrade {
  trade_id: string;
  date: string;
  week: number;
  parties: OwnerRef[];
  assets_short: string;
  swing_ktc: number;
  swing_prod: number;
  /** Winner of the zero-sum Trade Value swing. Null on a pre-feature payload
   *  or a trade with fewer than two graded sides. */
  value_winner?: OwnerRef | null;
  /** Winner of the received-only production tally. Can differ from
   *  value_winner — that divergence is the lead's story. */
  production_winner?: OwnerRef | null;
  /** [value winner's received total, the other side's]. Ordered by the VALUE
   *  winner so the lead's left-hand figure is always the same person.
   *  Two-side trades only. */
  production_split?: [number, number] | null;
}

export interface Records {
  biggest_value_swing: number;
  biggest_value_swing_owner?: string;
  biggest_value_swing_owner_user_id?: string;
  biggest_production: number;
  biggest_production_owner?: string;
  biggest_production_owner_user_id?: string;
  biggest_playoff: number;
  biggest_playoff_owner?: string;
  biggest_playoff_owner_user_id?: string;
  most_trades: number;
  most_trades_owner?: string;
  most_trades_owner_user_id?: string;
}

/** League "voice" data for one owner, keyed externally by user_id.
 *  `rivals` holds the user_ids of this owner's rivals. */
export interface OwnerProfile {
  win_name?: string;
  loss_name?: string;
  archetype?: string;
  rivals?: string[];
  roast?: string;
}

/** All owner profiles for a league, keyed by user_id. */
export type ProfilesMap = Record<string, OwnerProfile>;

/** What a league supports (see engine/capabilities.py). Drives which sections
 *  the UI renders at all — absence, never an empty state. Defaults are full
 *  dynasty so pre-feature caches behave exactly as before. */
export interface LeagueCapabilities {
  format: "dynasty" | "keeper" | "redraft";
  future_picks: boolean;
  roster_continuity: boolean;
  multiyear_history: boolean;
}

/** Live title-path state during the playoffs. `top_seed` is regular-season
 *  rank (1 = best) among owners still alive, null when seeds aren't known.
 *  `playoff_points` is the trade metric — points from players an owner
 *  received in trades, scored in live title-path games. */
export interface BracketWatch {
  season: number;
  entered: number;
  alive_count: number;
  alive: OwnerRef[];
  top_seed_owner?: OwnerRef | null;
  top_seed?: number | null;
  playoff_points_leader?: OwnerRef | null;
  playoff_points?: number | null;
}

/** One pick, graded either against its own draft class (`best`/`worst`:
 *  `slot_delta` is where it was taken minus where it finished by
 *  production, so positive means it outproduced its slot) or against
 *  draft-day consensus (`best_value`/`reach`: `baseline_delta` is pick
 *  number minus consensus rank — rookie ECR, else Sleeper ADP — so
 *  positive means it fell past consensus). Never both on the same row. */
export interface DraftReviewPick {
  player_id: string;
  full_name: string;
  position: string;
  drafter_id: string;
  owner?: OwnerRef | null;
  round: number;
  slot: number;
  /** Overall pick number — round 2 slot 1 is the 13th pick, not the 1st. */
  draft_position: number;
  production_total: number | null;
  slot_delta: number | null;
  baseline_delta: number | null;
  baseline_source: string;
}

export interface DraftReview {
  season: number;
  /** False for a class that has completed but not played yet — the results
   *  (picks made, class year) are real, but `best`/`worst` are null rather
   *  than invented out of an all-zero field. */
  graded: boolean;
  best: DraftReviewPick | null;
  worst: DraftReviewPick | null;
  /** How many picks finished ahead of where they were taken. */
  beat_slot: number;
  total: number;
  /** Value vs draft-day consensus — needs no played game, so these are set
   *  even while `graded` is false (the ungraded window's actual story).
   *  Null when fewer than two scored picks matched a baseline. */
  best_value: DraftReviewPick | null;
  reach: DraftReviewPick | null;
  /** How many scored picks had a consensus baseline to compare against. */
  matched: number;
}

export interface DashboardResp {
  league: LeagueSummary;
  selected_year: Year;
  selected_lens: Lens;
  hero_stats: HeroStats;
  standings: StandingRow[];
  latest_trades: LatestTrade[];
  /** Most consequential trades in the window, ranked by Trade Value swing. */
  headline_trades: LatestTrade[];
  records: Records;
  total_trades?: number;
  warnings: string[];
  /** League-calendar phase for the dashboard lead (api/app/services/league_phase.py).
   *  "regular"/"post" during scored regular-season/bracket weeks, "draft" from a
   *  draft's buildup through its aftermath up to NFL week 1, "offseason"
   *  otherwise. Optional so older cached
   *  fixtures / tests that omit it still type-check — components treat a missing
   *  value as "offseason", matching the backend default. */
  phase?: "regular" | "post" | "draft" | "offseason";
  phase_season?: number;
  phase_week?: number | null;
  /** Most recent COMPLETED regular-season week (api/app/services/week_recap.py).
   *  Absent outside the regular season, before week 2, and on caches written
   *  before the field existed — the lead keeps its placeholder skeleton. */
  week_recap?: WeekRecap | null;
  /** How the last draft panned out (engine/draft_results.py) — any format:
   *  dynasty rookie classes and redraft/keeper full drafts alike.
   *  Only built during the draft window. A class that hasn't played yet is
   *  PRESENT with `graded: false` and null best/worst, so the lead can report
   *  the results on draft night; it is absent only when the class can't be
   *  reviewed at all (fewer than two scored picks), and the lead falls back. */
  draft_review?: DraftReview | null;
  /** Live title-path state (engine/playoff_phase.py::build_bracket_watch).
   *  Absent outside the playoffs and on caches written before the field
   *  existed — the lead keeps its placeholder skeleton. */
  bracket_watch?: BracketWatch | null;
  /** What this league supports. Optional so older cached fixtures / tests
   *  that omit it still type-check — components treat a missing value as
   *  full dynasty, matching the backend default. */
  capabilities?: LeagueCapabilities;
}

export interface WeekRecapFigure {
  user_id: string;
  owner?: OwnerRef | null;
  points: number;
}

export interface WeekRecap {
  season: string;
  week: number;
  high_score: WeekRecapFigure;
  blowout: {
    winner_user_id: string;
    winner?: OwnerRef | null;
    loser_user_id: string;
    loser?: OwnerRef | null;
    margin: number;
  };
  /** Null when nobody started a trade-acquired player for points that week. */
  traded_points?: WeekRecapFigure | null;
}

export interface SignalBreakdown {
  raw: number;
  z: number;
  weight: number;
  contribution: number;
}

export interface PillarBreakdown {
  weight: number;
  z: number;
  contribution: number;
  signals: Record<string, SignalBreakdown>;
  signal_ranks?: Record<string, number>;
}

export interface GMRow {
  rank: number;
  user_id: string;
  owner: OwnerRef;
  rating: number;
  /** Franchise Rating letter (rating mapped to a letter grade). */
  letter: string;
  /** Which weight tree produced this rating ("v2_dynasty" | "v2_keeper" |
   *  "v2_redraft"; api/app/services/franchise_redesign.py::model_for). A
   *  rating read without knowing its tree is uninterpretable. */
  model?: string;
  pillars: Record<string, PillarBreakdown>;   // v2: results / assets (results only for redraft)
  /** prev_rank - rank: positive = moved up, negative = moved down, 0 = flat/new. */
  trend: number;
  trades: number;
  net_ktc: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  blurb?: string | null;
  /** Same roster-value rank as `StandingRow.roster_rank`/`roster_of`
   *  (`api/app/services/leaderboard.py`, same `entry.roster_ranks` source
   *  and redraft gate as the standings row). Still optional: a cached
   *  response served before the field existed, or a redraft league, omits
   *  it, and the leaderboard's receipt panel drops the line rather than
   *  rendering a blank one. */
  roster_rank?: number | null;
  roster_of?: number | null;
}

export interface LeaderboardResp {
  league_id: string;
  /** "all" or the season as a string. */
  scope: string;
  rows: GMRow[];
  generated_at: string;
}

export interface SeasonArc {
  season: number;
  net_ktc: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  /** Starters-only, all weeks. The gap between this and `production_total` is
   *  the bench — what the franchise accumulated but never deployed. Optional:
   *  absent from a response served before the field was added. */
  production_started?: number;
  trades: number;
}

/** One trade from a single owner's perspective. Swings are this owner's share. */
export interface OwnerTradeRow {
  trade_id: string;
  date: string;
  season: number;
  week: number | null;
  counterparties: OwnerRef[];
  assets_short: string;
  swing_ktc: number;
  swing_prod: number;
  swing_regular: number;
  swing_playoff: number;
  swing_toilet: number;
  /** Starters-only, ALL weeks. NOT `regular + playoff + toilet`: playoff counts
   *  live title-path games only, so started points in a placement game or an
   *  eliminated week fall in no phase. Optional — a cache written before the
   *  field was surfaced omits it. */
  swing_started?: number;
  /** Share of this haul's points that were actually started — the bench-miss
   *  reading. `null` for a haul that has not played; never 0 in that case. */
  start_pct?: number | null;
}

export interface PlayerLite {
  player_id: string;
  full_name: string;
  position: string;
  age: number | null;
}

export interface AgeProfileView {
  avg_age_by_position: Record<string, number>;
  overall_avg_age: number;
  aging_risks: PlayerLite[];
  core_young: PlayerLite[];
  league_avg_age_by_position?: Record<string, number>;
}

export interface DraftCapitalView {
  picks_by_season: Record<string, number>;
  picks_by_season_round: Record<string, number>;
  net_vs_average: number;
  status: string;
  total_value: number;
}

export interface DraftNeedView {
  position: string;
  urgency: string;
  reason: string;
  /** Depth pips render ONLY when kind === "depth". The aging branch is reached
   *  only when held >= ideal, so pips there would draw a full room beside a
   *  live need. 0/0/"" on a pre-feature blob. */
  held?: number;
  ideal?: number;
  kind?: string;
}

export interface OutlookView {
  /** Derived from the Franchise Rating (gm_rating.py::rating_to_stage) — not a
   *  second model. Null for an unrated owner: no rating, so no stage. The
   *  retired classify_window always returned a label; this deliberately does
   *  not, and the ladder renders as an absence captioned by unrated_reason. */
  window?: string | null;
  results_z?: number | null;
  assets_z?: number | null;
  /** assets_z − results_z. A signed readout ("the roster is ahead of the
   *  trophy case"), never the rung selector. */
  tilt?: number | null;
  assets_signal_ranks?: Record<string, number>;
  age_profile: AgeProfileView;
  draft_capital: DraftCapitalView;
  draft_needs: DraftNeedView[];
}

export interface RankView { rank: number; of: number; }
export interface DraftSkillView { score: number; rank: number; of: number; }

export interface DraftPickResult {
  player_id: string;
  full_name: string;
  position: string;
  round: number;
  slot: number;
  picks_in_round: number;
  draft_season: number;
  acquired_via_trade: boolean;
  current_value: number;
  lowest_value: number;
  highest_value: number;
  avg_slot_value: number;
  production_total: number;
  /** Started points across EVERY week — phase-blind. Regular + Playoff +
   *  Toilet is LESS than this; a bye or placement week belongs to no phase.
   *  Never present those three as summing to anything. */
  production_started?: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  games_started: number;
  roster_status: "rostered" | "traded" | "dropped";
  is_keeper?: boolean;
  pick_no?: number;
  adp?: number | null;
  adp_delta?: number | null;
  projected_points?: number | null;
  /** "hit" | "average" | "bust" | "" — empty when unranked, keeper, auction,
   *  or the cohort cell has too few players. Never a guess. */
  verdict?: string;
}

/** The platform verdict on an owner: the v2 Results/Assets composite as a
 *  letter (Results only for redraft), with the number/rank/trend as the
 *  receipt. */
export interface FranchiseRating {
  letter: string;
  rating: number;
  rank: number;
  of: number;
  /** prev_rank - rank: positive = up, negative = down, 0 = flat/new. */
  trend: number;
  pillars: Record<string, PillarBreakdown>;
  /** LLM-written one-line highlight per pillar key (v2: results/assets). */
  pillar_highlights?: Record<string, string>;
}

/** One season's finish + bracket result for the Track Record chapter. */
export interface SeasonResult {
  season: number;
  rank: number;
  of: number;
  wins: number;
  losses: number;
  ties: number;
  made_playoffs: boolean;
  champion: boolean;
  runner_up: boolean;
  rounds_won: number;
  playoff_place: number | null;
  made_toilet: boolean;
  toilet_place: number | null;
}

export interface TrackRecord {
  seasons: SeasonResult[];
  titles: number;
  runner_ups: number;
  playoff_appearances: number;
  seasons_played: number;
  best_finish: number | null;
  career_wins: number;
  career_losses: number;
  career_ties: number;
}

/** This owner's all-time regular-season record vs one league-mate. */
export interface H2H {
  opponent: OwnerRef;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
}

/** One run of the franchise blurb's body plus its emphasis mark.
 *
 *  `mark` is a plain string, not the `EmphasisKind` union, on purpose: it comes
 *  off a cache blob written by an older build, so the component narrows it at
 *  the boundary and anything unrecognised renders as prose. Typing it as the
 *  union here would assert a guarantee the wire does not make. */
export interface ProseSegment {
  text: string;
  mark?: string | null;
}

export interface OwnerDetailResp {
  league_id: string;
  user_id: string;
  owner: OwnerRef;
  /** "dynasty" | "keeper" | "redraft". Ask the format before rendering a
   *  format-specific column; never infer it from all-zero data. */
  format?: string;
  totals_by_lens: {
    ktc: number; production: number; regular: number; playoff: number; toilet: number;
    /** Starters-only across every week — see `OwnerTradeRow.swing_started`.
     *  Optional: absent from a response served before the field was added. */
    started?: number;
    /** Career start rate. Absent when nothing has played. */
    start_pct?: number;
  };
  career_arc: SeasonArc[];
  trades: OwnerTradeRow[];
  best_trade_id: string | null;
  worst_trade_id: string | null;
  outlook?: OutlookView | null;
  roster_rank?: RankView | null;
  draft_skill?: DraftSkillView | null;
  /** The blurb body as PLAIN text. Always present when there is a blurb, and
   *  the fallback an older cached entry renders through. */
  franchise_blurb?: string | null;
  /** The opening claim, set large above the body. Absent on a pre-marks blurb. */
  franchise_lead?: string | null;
  /** The body split into emphasis runs. Absent on a pre-marks blurb, in which
   *  case `franchise_blurb` is rendered as prose. Never HTML — each segment
   *  becomes an element and React escapes its text. */
  franchise_segments?: ProseSegment[] | null;
  draft_picks_by_season?: Record<string, DraftPickResult[]>;
  production_series?: OwnerProductionSeries;
  production_verdict?: Record<string, ProductionVerdict>;
  production_week_axis?: [number, number][];
  production_week_phases?: string[];
  production_trades?: TradeProduction[];
  // Franchise page (owner-redesign).
  franchise_rating?: FranchiseRating | null;
  /** Why there is no letter, when `franchise_rating` is absent.
   *  `"first_season"` — the league has completed no season, so nobody is
   *  rated. `"new_franchise"` — the league has, this owner has not. Null
   *  when rated. The caption copy lives in HeroBand, not here. */
  unrated_reason?: "first_season" | "new_franchise" | null;
  track_record?: TrackRecord;
  head_to_head?: H2H[];
}

export interface AssetFlip {
  to_owner: string;
  trade_id: string | null;
  league_id: string | null;
  date: string | null;
  became: AssetLine[];
}

export interface AssetLine {
  label: string;
  kind: "player" | "pick";
  player_id: string | null;
  ktc: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  production_started: number;
  production_after_drop?: number;
  from_pick?: string | null;
  from_pick_owner?: string | null;
  terminal_state?: "on_roster" | "dropped" | "undrafted" | null;
  flip?: AssetFlip | null;
}

export interface StandingAtTrade {
  rank: number;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  total_teams: number;
}

export interface TradeSideView {
  user_id: string;
  owner_name: string;
  team_name?: string;
  avatar_url?: string;
  received: { kind?: string; name?: string; player_id?: string;
              season?: number; round?: number; via_pick?: any;
              original_owner_user_id?: string }[];
  given: { kind?: string; name?: string; player_id?: string;
           season?: number; round?: number; via_pick?: any;
           original_owner_user_id?: string }[];
  snapshot_ktc_swing: number;
  received_ktc: number;
  production_total: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  breakdown: AssetLine[];
  production_started: number;
  start_pct: number | null;
  at_trade_ktc_swing: number | null;
  aged_ktc_swing: number | null;
  at_trade_approx: boolean;
  at_trade_snapshot_date: string | null;
  at_trade_standing: StandingAtTrade | null;
}

export interface TradeStory {
  verdict: string;
  lede?: string;
  beats?: string[];
  body: string;
  generated_at?: string | null;
}

export interface LineageNode {
  label: string;
  kind: "player" | "pick";
  flipped_at?: string | null;
  terminal_state?: "on_roster" | "dropped" | "undrafted" | null;
  became_player?: string | null;
  children: LineageNode[];
}

export interface BecameMetrics {
  ktc: number;
  production: number;
  regular: number;
  playoff: number;
  toilet: number;
  terminal_labels: string[];
  breakdown: AssetLine[];
}

export interface ProductionPoint {
  season: number;
  week: number;
  value: number;
}

export type ProductionMetric = "started" | "total" | "regular" | "playoff" | "toilet";

export interface ProductionVerdict {
  label: string;
  sentence: string;
  tone: "good" | "bad" | "neutral";
  winner_uid?: string | null;
  totals?: Record<string, number>;
}

// per-trade: uid -> metric -> points
export type TradeProductionSeries = Record<string, Record<ProductionMetric, ProductionPoint[]>>;
// owner: side -> metric -> points
export type OwnerProductionSeries = Record<"received" | "given", Record<ProductionMetric, ProductionPoint[]>>;

export interface PlayerProduction {
  player_id: string;
  series: Record<ProductionMetric, ProductionPoint[]>;
}

export interface TradeProduction {
  trade_id: string;
  series: Record<ProductionMetric, ProductionPoint[]>;
}

export interface PlayerInjury {
  games_missed: { regular: number; playoff: number; toilet: number };
  missed_weeks: [number, number, "high" | "soft"][];  // [season, week, confidence]
  currently_out: boolean;
  out_detail?: string | null;
}

export interface Departure { player_id: string; season: number; week: number; kind: "dropped" | "traded"; }

/** Winning user_id per lens (Trade Value / Total / Regular Season / Playoff /
 *  Toilet Bowl); null when the lens is tied or unscored (api/app/models/trade.py
 *  LensWinners). */
export interface LensWinners {
  value: string | null;
  total: string | null;
  regular: string | null;
  playoff: string | null;
  toilet: string | null;
}

/** Winning side's realized figure minus the runner-up's, per lens — the same
 *  rows-plus-became totals the side ledgers render, so summing the visible
 *  rows reproduces each margin (LensMargins). Null when tied or unscored. */
export interface LensMargins {
  value: number | null;
  total: number | null;
  regular: number | null;
  playoff: number | null;
  toilet: number | null;
}

export type TradeCall = "unanimous" | "split" | "none";

export interface TradeDetailResp {
  league_id: string;
  trade_id: string;
  date: string;
  week: number;
  season: number;
  league_name: string;
  sides: TradeSideView[];
  story?: TradeStory | null;
  lineage?: Record<string, LineageNode[]>;
  became?: Record<string, BecameMetrics>;
  owner_names?: Record<string, string>;
  production_series?: TradeProductionSeries;
  production_verdict?: Record<string, ProductionVerdict>;
  production_week_axis?: [number, number][];
  production_week_phases?: string[];                       // "regular"|"post", parallel to axis
  production_players?: Record<string, PlayerProduction[]>;
  injury?: Record<string, Record<string, PlayerInjury>>;  // uid -> player_id -> injury
  departures?: Record<string, Departure[]>;                // uid -> dropped/traded received players
  twist?: { kind: string; owner: string; label: string; detail: string } | null;
  winner_user_id?: string | null;
  lopsidedness?: number;
  // Per-lens verdicts over each side's realized totals — see LensMargins.
  // Optional: pre-existing cache entries built before this field shipped
  // won't carry it until the next refresh.
  winners_by_lens?: LensWinners;
  margins_by_lens?: LensMargins;
  // "unanimous": every decided lens went one way; "split": more than one
  // winner across decided lenses; "none": nothing decided (tied/unscored).
  call?: TradeCall;
  // Lenses won per side, most-won first, e.g. "4-1" (ties count for nobody).
  lens_tally?: string;
}

export interface OwnerNameEntry {
  user_id: string;
  sleeper_name: string;
  display_name: string | null;
}

export interface OwnerNamesResp {
  owners: OwnerNameEntry[];
}

// ---- Side bets ------------------------------------------------------------

export type SideBetStatus = "open" | "settled" | "push" | "void";

export interface SideBetView {
  id: string;
  season: number;
  description: string;
  amount_cents: number;
  side_a: OwnerRef;
  side_b: OwnerRef;
  status: SideBetStatus;
  winner_owner_id: string | null;
  made_at: string;
  settled_at: string | null;
}

export interface SideBetListResp {
  bets: SideBetView[];
}

export interface SideBetCreateBody {
  description: string;
  amount_cents: number;
  season: number;
  side_a_owner_id: string;
  side_b_owner_id: string;
  made_at: string;
}

export interface SideBetUpdateBody {
  description?: string;
  amount_cents?: number;
  season?: number;
  side_a_owner_id?: string;
  side_b_owner_id?: string;
  made_at?: string;
  status?: SideBetStatus;
  winner_owner_id?: string;
  settled_at?: string;
}

export interface OwnerBetSummary {
  owner: OwnerRef;
  won: number;
  lost: number;
  pushed: number;
  cents_won: number;
  cents_lost: number;
  net_cents: number;
  cents_at_stake: number;
  biggest_win_cents: number;
  worst_loss_cents: number;
}

export interface BetsSummaryResp {
  owners: OwnerBetSummary[];
}

// ── League-wide draft board ────────────────────────────────────────────────

export interface DraftBoardPick {
  player_id: string;
  full_name: string;
  position: string;
  drafter_id: string;
  owner?: OwnerRef | null;
  round: number;
  slot: number;
  /** Picks per round in this class (usually the roster count) — used to
   *  derive a pick's position WITHIN its round (`lib/draft-pick-no.ts`),
   *  since `slot` alone reverses in every even round of a snake draft.
   *  Optional only for pre-feature cache tolerance; the API always sends
   *  one. */
  picks_in_round?: number;
  pick_no: number;
  is_keeper: boolean;
  production_total: number;
  /** Started points across EVERY week — phase-blind. Regular + Playoff +
   *  Toilet is LESS than this; a bye or placement week belongs to no phase.
   *  Never present those three as summing to anything. */
  production_started?: number;
  production_regular?: number;
  production_playoff?: number;
  production_toilet?: number;
  games_started?: number;
  adp?: number | null;
  adp_delta?: number | null;
  projected_points?: number | null;
  baseline?: number | null;
  baseline_delta?: number | null;
  baseline_source?: string;
  /** "hit" | "average" | "bust" | "" — empty when unranked, keeper, auction,
   *  or the cohort cell has too few players. Never a guess. */
  verdict?: string;
  /** The pick's current standing with the drafting owner — mirrors
   *  `DraftPickResult["roster_status"]`. Optional only for pre-feature
   *  cache tolerance; the API always sends one. */
  roster_status?: "rostered" | "traded" | "dropped";
}

export interface DraftBoardOwner {
  user_id: string;
  owner?: OwnerRef | null;
  adp_total_delta?: number | null;
  graded_picks: number;
  total_picks: number;
  production_total: number;
  production_started?: number;
  production_regular?: number;
  production_playoff?: number;
  production_toilet?: number;
  /** Summed pick production minus each pick's round average — zero-sum across
   *  the class, so it rewards drafting well from a bad slot rather than
   *  picking early. Null when the class has nothing scorable. */
  points_above_round?: number | null;
  /** Hit / Average / Bust counted from THIS owner's pick verdicts — the same
   *  strings the Picks ledger renders, never judged again. All three are 0
   *  when nothing in the owner's class could be judged, which the UI shows as
   *  an em-dash rather than "0 / 0": unjudged is not "hit nothing". */
  hit?: number;
  average?: number;
  bust?: number;
  /** Every pick the owner MADE in this class, keepers and auction bids
   *  included — the count of rows the Picks ledger shows for them. Distinct
   *  from `total_picks`, which counts only the scored subset. */
  picks_made?: number;
}

/** One starting slot INSTANCE's standing against the league-native
 *  replacement line — the ONE keyspace both `holes` and "the softest slot"
 *  derive from (2026-08-17 keyspace-fix revision; superseded the earlier,
 *  differently-keyed `hole_margins`/`softest_slot` pair, which disagreed
 *  with each other and with `holes` the moment a position had more than one
 *  starting slot). Mirrors `api/app/models/league.py::SlotStandingResp`. */
export interface SlotStandingResp {
  /** The slot-instance key, e.g. "RB_2" — not for display. */
  slot: string;
  /** The occupant's real position, e.g. "RB" — print THIS, never `slot`. */
  position: string;
  /** Points vs that position's replacement line; negative = below it.
   *  `null` — never a non-finite number — when there's nothing to compare:
   *  no occupant in the slot, or the slot's label has no replacement line
   *  at all (a raw FLEX-type label a fallback filler landed in). C1 fix
   *  (2026-08-17): `-Infinity`/`Infinity` here used to 500 the whole draft
   *  board on the wire (Starlette's `JSONResponse.render` uses
   *  `allow_nan=False`). Render a `null`-margin slot as empty, never as the
   *  literal string "null"/"Infinity". */
  margin: number | null;
  /** Below the line AND not vetoed. */
  is_hole: boolean;
  /** Below the line, but ECR rates the player above its own line — rescued. */
  vetoed: boolean;
}

/** One owner's draft-day picture: which starting slots were holes against a
 *  league-relative replacement line, and whether the draft addressed them.
 *  Display-only, inferred from a roster reconstruction — must NEVER feed
 *  Franchise Rating. Mirrors `api/app/models/league.py::OwnerNeedsResp`. */
export interface OwnerNeedsResp {
  user_id: string;
  /** Positions, most-severe hole first. Derived from `slots` (the `is_hole`
   *  entries) server-side — the two can never disagree. Retained on the wire
   *  but no longer the panel's rendering source; see `slots`. */
  holes: string[];
  /** The owner's picks whose position matched an open hole. */
  drafted_into: string[];
  /** Of `drafted_into`, how many ever recorded a start. Retained on the wire
   *  for API-shape compatibility but no longer rendered anywhere in the UI —
   *  `production` replaced it as the panel's trailing figure (Biggest Needs
   *  redesign, 2026-08-19); see `DraftGoingIn.tsx`'s file-header rule 1 for
   *  why. */
  started: number;
  drafted_into_count: number;
  /** Combined production the credited picks put up, regardless of whether
   *  they ever started. Real, including a real 0 — distinct from the panel
   *  omitting the figure for an owner with no credited picks at all. */
  production: number;
  /** One entry per starting slot, in `roster_positions` order. The ONE
   *  keyspace the panel renders from: holes read straight off `is_hole`
   *  entries, and "the softest slot" is `min(slots, key=(s) => s.margin)`.
   *  Empty when there is no reconstructable roster. */
  slots: SlotStandingResp[];
}

export interface DraftBoardResp {
  league_id: string;
  season: number;
  seasons: number[];
  graded: boolean;
  format: string;
  picks: DraftBoardPick[];
  owners: DraftBoardOwner[];
  baseline_label?: string;
  /** True when at least one pick carries a non-empty verdict. The UI drops
   *  the Verdict column entirely rather than showing a header over dashes. */
  has_verdicts?: boolean;
  /** None (absent/null), not [], when the league is ineligible for the
   *  reconstruction (redraft, a first-season startup dynasty, or any season
   *  that isn't the newest gradeable draft class) — the frontend (`DraftBoard`)
   *  omits the "Going in" panel entirely rather than rendering an empty one.
   *  See `api/app/models/league.py::DraftBoardResp.needs`. */
  needs?: OwnerNeedsResp[] | null;
}

/** Every draft season on the chain, newest first — feeds the `/draft`
 *  redirect route, which needs a season before it can fetch a board. */
export interface DraftSeasonsResp {
  seasons: number[];
}
