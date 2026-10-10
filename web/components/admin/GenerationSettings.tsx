import { useEffect, useState } from "react";
import { generationRequest } from "@/lib/api";
import { FEATURE_LABELS, FeatureSettings, GenerationFeature, GenerationSeries, PolicyView } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { ActionForm, ActionProps, controlClass, readable, secondary, TechnicalDetails } from "./GenerationShared";

const models = ["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-6"];
const modes = { disabled: "Off", manual: "Ask me first", automatic: "Automatic" };
const bulkAutomaticFeatures: GenerationFeature[] = ["trade_story", "gm_rating_blurb", "franchise_blurb", "analyst"];

export function GenerationSettings({ leagues, busy, run, version }: ActionProps & { leagues: GenerationSeries[]; version: number }) {
  const [scope, setScope] = useState("app");
  const [policy, setPolicy] = useState<PolicyView | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [leagueAction, setLeagueAction] = useState("");
  const [profile, setProfile] = useState("dynasty");
  const selectedLeague = leagues.find(l => scope === "series:" + l.id);
  useEffect(() => {
    let current = true;
    setLoading(true); setError(""); setPolicy(null); setLeagueAction("");
    generationRequest<PolicyView>(`/policy/${encodeURIComponent(scope)}`).then(value => {
      if (current) { setPolicy(value); setDraft(value.value); setReason(""); }
    }).catch(err => { if (current) setError(err.message || "Settings could not load. Try reloading."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [scope, version]);
  const blocked = busy || loading;
  function field(key: string, value: unknown) {
    setDraft(old => { const next = { ...old }; if (value === undefined) delete next[key]; else next[key] = value; return next; });
  }
  function overrides(feature: GenerationFeature) {
    return ((draft.features as Partial<Record<GenerationFeature, Partial<FeatureSettings>>>) || {})[feature] || {};
  }
  function featureField(feature: GenerationFeature, key: keyof FeatureSettings, value: unknown) {
    const entry = { ...overrides(feature) };
    if (value === undefined) delete entry[key]; else Object.assign(entry, { [key]: value });
    field("features", { ...(draft.features as object || {}), [feature]: entry });
  }
  return <div className="mt-3">
    <p className="max-w-2xl text-prose text-dim">Choose when AI may write. League settings can customize shared defaults; an app-wide pause always takes priority.</p>
    <label className="mt-3 block text-prose">Apply settings to
      <select className={controlClass + " mt-1"} disabled={busy} value={scope} onChange={e => setScope(e.target.value)}>
        <option value="app">All leagues — shared defaults</option>
        {["dynasty", "keeper", "redraft"].map(p => <option key={p} value={"profile:" + p}>{readable(p)} leagues — shared defaults</option>)}
        {leagues.map(l => <option key={l.id} value={"series:" + l.id}>{l.name || "Unnamed league"}</option>)}
      </select>
    </label>
    {loading && <p role="status" className="mt-3 text-prose">Loading settings…</p>}
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {policy && <form className="mt-4" onSubmit={async e => {
      e.preventDefault(); if (blocked || !reason.trim()) return;
      setError("");
      try { await run(() => generationRequest(`/policy/${encodeURIComponent(scope)}`, { expected_revision: policy.revision, value: draft, reason: reason.trim() }, "PUT"), "Configuration saved. Older work still needs separate approval."); }
      catch (err) { setError(err instanceof Error ? err.message : "Settings were not saved. Reload and try again."); }
    }}>
      <fieldset disabled={blocked}>
        {scope === "app" && <div className="mb-4 rounded-lg border border-rule p-4">
          <h4 className="font-display text-name font-bold">Automatic writing across leagues</h4>
          <p className="mt-1 text-prose text-dim">Set trade stories, GM profiles, franchise outlooks, and Weekly Analyst together. New eligible events will run automatically after you save. Existing league overrides and safety pauses still apply.</p>
          <button type="button" className={secondary + " mt-3"} onClick={() => {
            setDraft(old => ({ ...old, features: { ...(old.features as object || {}), ...Object.fromEntries(bulkAutomaticFeatures.map(feature => [feature, {
              ...((old.features as Partial<Record<GenerationFeature, Partial<FeatureSettings>>>)?.[feature] || {}), mode: "automatic",
            }])) } }));
            setReason("Enable automatic writing for all four content types across leagues");
          }}>Set all four to Automatic</button>
        </div>}
        {(Object.keys(FEATURE_LABELS) as GenerationFeature[]).map(feature => {
          const current = policy.effective.policy.features[feature], edited = overrides(feature);
          if (!current) return null;
          const saved = (policy.value.features as Partial<Record<GenerationFeature, Partial<FeatureSettings>>>)?.[feature];
          const inherited = !saved?.mode;
          const source = policy.effective.sources[`features.${feature}.mode`];
          const sourceName = source?.startsWith("profile:") ? `${source.slice(8)} defaults` : source?.startsWith("series:") ? "this league’s settings" : source === "app" ? "app defaults" : "built-in defaults";
          return <div key={feature} className="border-t border-rule py-4">
            <div className="grid items-start gap-3 sm:grid-cols-2">
              <div><h4 className="font-display text-name font-bold">{FEATURE_LABELS[feature]}</h4>
                <p className="mt-1 text-prose text-dim">{current.paused ? "Currently paused" : `Saved setting: ${modes[current.mode]}`}{inherited ? ` · Uses ${sourceName}` : ""}</p>

              </div>
              <label className="text-prose">When to write
                <select className={controlClass + " mt-1"} aria-label={FEATURE_LABELS[feature] + " mode"} value={edited.mode || ""} onChange={e => featureField(feature, "mode", e.target.value || undefined)}>
                  <option value="">Use shared default</option>
                  {Object.entries(modes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
            </div>
            {!edited.mode && saved?.mode && <p className="mt-2 text-prose text-warn-strong">Removing this override uses the shared defaults, which may allow automatic writing. Review the shared settings before saving.</p>}
            {(edited.mode || current.mode) === "automatic" && <p className="mt-2 text-prose text-dim">Writes for new eligible events. Older content still needs your approval.</p>}
            <details className="mt-2"><summary className="min-h-tap cursor-pointer py-2 text-prose text-dim">Advanced {FEATURE_LABELS[feature].toLowerCase()} settings</summary>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-prose">Writer model<select className={controlClass} value={edited.model || ""} onChange={e => featureField(feature, "model", e.target.value || undefined)}><option value="">Use shared default</option>{models.map(m => <option key={m}>{m}</option>)}</select></label>
                <label className="text-prose">Maximum AI requests per item<select className={controlClass} value={edited.max_calls ?? ""} onChange={e => featureField(feature, "max_calls", e.target.value ? Number(e.target.value) : undefined)}><option value="">Use shared default</option>{(["analyst", "recap_video"].includes(feature) ? [2, 4] : [1, 2]).map(n => <option key={n} value={n}>{n} requests</option>)}</select></label>
                <label className="text-prose">Pause this feature<select className={controlClass} value={typeof edited.paused === "boolean" ? String(edited.paused) : ""} onChange={e => featureField(feature, "paused", e.target.value === "" ? undefined : e.target.value === "true")}><option value="">Use shared default</option><option value="true">Paused</option><option value="false">Allowed</option></select></label>
                <label className="text-prose">Maximum output tokens<input className={controlClass} type="number" min={64} max={8192} value={edited.max_tokens ?? ""} placeholder="Use shared default" onChange={e => featureField(feature, "max_tokens", e.target.value ? Number(e.target.value) : undefined)} /></label>
                {["analyst", "recap_video"].includes(feature) && <label className="text-prose">Review model<select className={controlClass} value={edited.review_model || ""} onChange={e => featureField(feature, "review_model", e.target.value || undefined)}><option value="">Use shared default</option>{models.map(m => <option key={m}>{m}</option>)}</select></label>}
              </div>
            </details>
          </div>;
        })}
        <details className="border-t border-rule py-2"><summary className="min-h-tap cursor-pointer py-2 text-prose text-dim">Advanced shared settings</summary>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-prose">AI writing permission<select className={controlClass} value={typeof draft.paused === "boolean" ? String(draft.paused) : ""} onChange={e => field("paused", e.target.value === "" ? undefined : e.target.value === "true")}><option value="">Use shared default</option><option value="true">Paused</option><option value="false">Allowed</option></select></label>
            <label className="text-prose">Data refresh interval (minutes)<input className={controlClass} type="number" min={15} max={10080} step={15} value={typeof draft.refresh_interval_seconds === "number" ? draft.refresh_interval_seconds / 60 : ""} placeholder="Use shared default" onChange={e => field("refresh_interval_seconds", e.target.value ? Number(e.target.value) * 60 : undefined)} /></label>
            <label className="text-prose">Simultaneous AI requests<input className={controlClass} type="number" min={1} max={4} value={typeof draft.max_concurrency === "number" ? draft.max_concurrency : ""} placeholder="Use shared default" onChange={e => field("max_concurrency", e.target.value ? Number(e.target.value) : undefined)} /></label>
          </div>
          <TechnicalDetails value={policy} label="Saved settings and where defaults come from" />
        </details>
        <label className="mt-3 block text-prose">Reason for this change (required)<input aria-label="Reason for this change" aria-describedby="generation-settings-reason-help" className={controlClass + " mt-1"} value={reason} maxLength={1000} required onChange={e => setReason(e.target.value)} placeholder="For example: Enable automatic weekly recap scripts." /></label>
        <p id="generation-settings-reason-help" className="mt-2 text-sm text-dim">{reason.trim() ? "This reason will be saved with your settings change." : "Enter a reason to enable Save configuration."}</p>
        <Button type="submit" className="mt-3 px-4 py-2" disabled={blocked || !reason.trim()}>Save configuration</Button>
      </fieldset>
    </form>}
    {selectedLeague && <details className="mt-4 border-t border-rule pt-3"><summary className="min-h-tap cursor-pointer py-2 text-prose text-dim">League setup and activation</summary>
      <p className="text-prose">{readable(selectedLeague.lifecycle)} · {selectedLeague.members} memberships · {selectedLeague.profile} defaults</p>
      <p className="text-prose text-dim">{selectedLeague.seasons.map(s => `${s.season}: ${s.verified_at ? "verified" : "needs verification"}`).join("; ")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className={secondary} disabled={blocked} onClick={() => setLeagueAction("activate")}>Activate future events</button>
        <button className={secondary} disabled={blocked || selectedLeague.lifecycle === "retired"} onClick={() => setLeagueAction("retire")}>Retire league</button>
        <button className={secondary} disabled={blocked} onClick={() => { setProfile(selectedLeague.profile); setLeagueAction("profile"); }}>Change league type</button>
      </div>
      {leagueAction === "profile" && <label className="mt-3 block text-prose">League type<select className={controlClass} value={profile} onChange={e => setProfile(e.target.value)}>{["dynasty", "keeper", "redraft"].map(p => <option key={p}>{p}</option>)}</select></label>}
      {leagueAction && <ActionForm key={leagueAction} title="Update league setup" description="This changes which future work is eligible. Older content still needs separate approval." submitLabel="Confirm league change" busy={blocked} onCancel={() => setLeagueAction("")} onSubmit={reason => run(() => generationRequest(`/leagues/${selectedLeague.id}`, {
        expected_revision: selectedLeague.revision, lifecycle: leagueAction === "retire" ? "retired" : leagueAction === "activate" ? "active" : selectedLeague.lifecycle,
        profile: leagueAction === "profile" ? profile : selectedLeague.profile, reason, activate: leagueAction === "activate",
      }, "PUT"), "League setup updated.")} />}
    </details>}
  </div>;
}
