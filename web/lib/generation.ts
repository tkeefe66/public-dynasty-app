export type GenerationFeature = "trade_story" | "gm_rating_blurb" | "franchise_blurb" | "analyst";
export interface FeatureSettings {
  mode: "disabled" | "manual" | "automatic";
  paused: boolean;
  model: string;
  review_model: string;
  max_calls: number;
  max_tokens: number;
  max_prompt_chars: number;
}
export interface GenerationPolicy {
  paused: boolean;
  max_concurrency: number;
  series_concurrency: number;
  breaker_failures: number;
  refresh_interval_seconds: number;
  features: Record<GenerationFeature, FeatureSettings>;
}
export interface EffectivePolicy {
  policy: GenerationPolicy;
  sources: Record<string, string>;
  revisions: Record<string, number>;
  blocked_by: string[];
}
export interface PolicyView {
  scope: string;
  revision: number;
  value: Record<string, unknown>;
  effective: EffectivePolicy;
}
export interface ControlState {
  revision: number;
  hold: string;
  epoch: string;
  provider_hold: string;
  breakers_json: string;
}
export interface GenerationOverview {
  control: ControlState;
  effective: EffectivePolicy;
  jobs: Record<string, number>;
  known_cost_microusd: number;
  unknown_cost_attempts: number;
  execution_epoch_configured: boolean;
  emergency_paused: boolean;
}
export interface GenerationSeries {
  id: string; name: string; profile: string; lifecycle: string; revision: number; hold: string;
  members: number;
  seasons: { league_id: string; season: number; verified_at: number; capabilities_json: string }[];
  effective: EffectivePolicy;
}
export interface GenerationRecord {
  id?: string; key?: string; label?: string; league_id?: string; series_id?: string;
  state?: string; feature?: GenerationFeature; subject?: string; event?: string; reason?: string;
  hold?: string; generation?: number; calls?: number; max_calls?: number; model?: string;
  cost_microusd?: number | null; usage_state?: string; action?: string; actor_id?: string;
  target?: string; error?: string; created_at?: number; observed_at?: number;
  before_json?: string; after_json?: string;
  [key: string]: unknown;
}
export interface GenerationPage<T> { records: T[]; next_offset: number | null }
export interface CampaignPreview {
  id: string; digest: string; max_calls: number; expires_at: number;
  items: { key: string; label: string; league_id: string; feature: GenerationFeature; event: string;
    max_calls: number; max_tokens_per_call: number; model: string; hold: string; blocked_by: string[] }[];
}
export const FEATURE_LABELS: Record<GenerationFeature, string> = {
  trade_story: "Trade stories", gm_rating_blurb: "GM profiles",
  franchise_blurb: "Franchise outlooks", analyst: "Weekly Analyst",
};
