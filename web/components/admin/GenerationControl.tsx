"use client";

import { useEffect, useRef, useState } from "react";
import { generationRequest } from "@/lib/api";
import {
  FEATURE_LABELS, CampaignPreview, FeatureSettings, GenerationFeature, GenerationOverview,
  GenerationPage, GenerationRecord, GenerationSeries, PolicyView,
} from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { Panel } from "@/components/furniture/Panel";

const controlClass = "min-h-tap w-full rounded-sm border border-rule-strong bg-surface px-3 py-2 text-prose text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-ringfocus";
const secondary = "min-h-tap rounded-sm border border-rule-strong px-3 py-2 text-prose hover:bg-surface-sunk disabled:cursor-not-allowed disabled:text-dim";
const models = ["claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-sonnet-4-6"];
const readable = (value?: string) => value ? value.replaceAll("_", " ") : "None";
const features = Object.keys(FEATURE_LABELS) as GenerationFeature[];
const availableHold = (hold?: string) => !hold || ["historical_approval_required", "missed_event_approval_required"].includes(hold);

export function GenerationControl() {
  const [overview, setOverview] = useState<GenerationOverview | null>(null);
  const [leagues, setLeagues] = useState<GenerationSeries[]>([]);
  const [nextLeague, setNextLeague] = useState<number | null>(null);
  const [scope, setScope] = useState("app");
  const [policy, setPolicy] = useState<PolicyView | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState("");
  const [workersStopped, setWorkersStopped] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [kind, setKind] = useState("jobs");
  const [page, setPage] = useState<GenerationPage<GenerationRecord>>({ records: [], next_offset: null });
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [detail, setDetail] = useState<unknown>(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const loadedPolicy = useRef("");
  const selectedLeague = leagues.find(l => scope === "series:" + l.id);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    const filter = scope.startsWith("series:") ? `&series_id=${encodeURIComponent(scope.slice(7))}` : "";
    void Promise.all([
      generationRequest<GenerationOverview>(),
      generationRequest<GenerationPage<GenerationSeries>>("/leagues?limit=100"),
      generationRequest<PolicyView>(`/policy/${encodeURIComponent(scope)}`),
      generationRequest<GenerationPage<GenerationRecord>>(`/records/${kind}?limit=25&offset=${offset}${filter}`),
    ]).then(([summary, registry, config, records]) => {
      if (!current) return;
      setOverview(summary); setLeagues(old => [...new Map([...old, ...registry.records].map(l => [l.id, l])).values()]);
      setNextLeague(registry.next_offset);
      if (loadedPolicy.current !== `${scope}:${version}`) {
        loadedPolicy.current = `${scope}:${version}`;
        setPolicy(config); setDraft(config.value);
      }
      setPage(records);
    }).catch((e: Error) => { if (current) setError(e.message || "Controls could not load. Refresh to try again."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [scope, kind, offset, version]);

  async function act(action: () => Promise<unknown>, success: string, reload = true) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      setNotice(success);
      if (reload) { setVersion(v => v + 1); setPreview(null); setSelected([]); }
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed. Reload the current state before trying again."); }
    finally { setBusy(false); }
  }
  const blocked = busy || loading || !reason.trim();
  function field(key: string, value: unknown) {
    setDraft(old => {
      const next = { ...old };
      if (value === undefined) delete next[key]; else next[key] = value;
      return next;
    });
  }
  function overrides(feature: GenerationFeature): Partial<FeatureSettings> {
    return ((draft.features as Partial<Record<GenerationFeature, Partial<FeatureSettings>>>) || {})[feature] || {};
  }
  function featureField(feature: GenerationFeature, key: keyof FeatureSettings, value: unknown) {
    const entry = { ...overrides(feature) };
    if (value === undefined) delete entry[key]; else Object.assign(entry, { [key]: value });
    field("features", { ...(draft.features as object || {}), [feature]: entry });
  }
  function control(action: string, feature = "") {
    return act(() => generationRequest("/control", {
      action, feature, expected_revision: overview!.control.revision,
      reason, workers_stopped: workersStopped,
    }), "Execution controls updated.");
  }
  function changeLeague(lifecycle: string, activate: boolean) {
    if (!selectedLeague) return;
    return act(() => generationRequest(`/leagues/${selectedLeague.id}`, {
      expected_revision: selectedLeague.revision, lifecycle, profile: selectedLeague.profile,
      reason, activate,
    }, "PUT"), "League lifecycle updated.");
  }
  function jobAction(row: GenerationRecord, action: string) {
    return act(() => generationRequest(`/jobs/${row.id}`, {
      action, expected_generation: row.generation, expected_state: row.state, reason,
    }), action === "cancel" ? "Job cancelled. Attempt records are retained." : "Job resumed with its remaining allowance.");
  }

  return <section className="mt-10" aria-labelledby="generation-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 id="generation-title" className="font-display text-section font-bold">Generation controls</h2>
        <p className="mt-1 max-w-2xl text-prose text-dim">Manage every league from one policy. Data refreshes run separately from paid writing.</p>
      </div>
      <button className={secondary} disabled={busy} onClick={() => setVersion(v => v + 1)}>Reload controls</button>
    </div>
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {notice && <p role="status" className="mt-3 text-prose text-pos-strong">{notice}</p>}
    {loading && <p role="status" className="mt-3 text-prose text-dim">Loading current controls…</p>}
    {overview && <div className="mt-4 space-y-5">
      <Panel className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-display text-name font-bold">{overview.control.hold || overview.effective.policy.paused ? "Paid generation is paused" : "Paid generation is enabled"}</h3>
            <p className="mt-1 text-prose text-dim">
              {overview.effective.blocked_by.length ? overview.effective.blocked_by.map(readable).join("; ") : "Each job still checks its league, feature, permission, and remaining calls."}
            </p>
            <p className="mt-2 text-prose">
              Recorded cost: <span className="font-mono">${(overview.known_cost_microusd / 1_000_000).toFixed(4)}</span>
              {" · "}{overview.unknown_cost_attempts} request(s) with unknown cost
            </p>
            {overview.emergency_paused && <p className="text-prose text-neg-strong">The deployment emergency pause is active.</p>}
          </div>
          <button className={secondary} disabled={blocked} onClick={() => control("pause")}>Pause all paid work</button>
        </div>
        <label className="mt-4 block text-prose">Reason for this change
          <input className={controlClass + " mt-1"} value={reason} onChange={e => setReason(e.target.value)} maxLength={1000}
            placeholder="What are you changing, and why?" />
        </label>
        <details className="mt-4">
          <summary className="min-h-tap cursor-pointer py-2 text-prose">Activation and provider recovery</summary>
          <p className="max-w-2xl text-prose text-dim">Activation requires a configured deployment epoch, stopped legacy workers, and completed reconciliation. It holds missed work for a separate preview.</p>
          <label className="mt-3 flex min-h-tap items-center gap-2 text-prose">
            <input type="checkbox" checked={workersStopped} onChange={e => setWorkersStopped(e.target.checked)} />
            I confirmed the original sending processes and legacy workers are stopped.
          </label>
          {!overview.execution_epoch_configured && <p className="text-prose text-warn-strong">Configure the deployment execution epoch before activation.</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            <button className={secondary} disabled={blocked || !workersStopped || !overview.execution_epoch_configured} onClick={() => control("activate")}>Activate execution</button>
            <button className={secondary} disabled={blocked || !overview.control.provider_hold} onClick={() => control("clear_provider")}>Clear provider hold</button>
            {features.map(feature => {
              const breaker = JSON.parse(overview.control.breakers_json || "{}")[feature];
              return breaker?.open ? <button key={feature} className={secondary} disabled={blocked}
                onClick={() => control("reset_breaker", feature)}>Reset {FEATURE_LABELS[feature]} breaker</button> : null;
            })}
          </div>
        </details>
      </Panel>

      <Panel className="p-4">
        <label className="block text-prose">Configuration scope
          <select className={controlClass + " mt-1"} disabled={busy} value={scope} onChange={e => {
            setScope(e.target.value); setOffset(0); setSelected([]); setPreview(null); setDetail(null);
          }}>
            <option value="app">All leagues: app defaults</option>
            {["dynasty", "keeper", "redraft"].map(profile => <option key={profile} value={"profile:" + profile}>{readable(profile)} profile</option>)}
            {leagues.map(league => <option key={league.id} value={"series:" + league.id}>{league.name || league.id} ({league.lifecycle})</option>)}
          </select>
        </label>
        {nextLeague !== null && <button className={secondary + " mt-2"} disabled={busy} onClick={() => act(async () => {
          const more = await generationRequest<GenerationPage<GenerationSeries>>(`/leagues?limit=100&offset=${nextLeague}`);
          setLeagues(old => [...new Map([...old, ...more.records].map(l => [l.id, l])).values()]); setNextLeague(more.next_offset);
        }, "More leagues loaded.", false)}>Load more leagues</button>}
        {selectedLeague && <div className="mt-3 text-prose">
          <p>{readable(selectedLeague.lifecycle)} · {selectedLeague.members} membership(s) · {readable(selectedLeague.hold)}</p>
          <p className="text-dim">{selectedLeague.seasons.map(s => `${s.season}: ${s.verified_at ? "verified" : "needs verification"}`).join("; ")}</p>
          <label className="mt-2 block">Assigned profile
            <select className={controlClass} disabled={blocked} value={selectedLeague.profile || "dynasty"} onChange={e => {
              const profile = e.target.value;
              void act(() => generationRequest(`/leagues/${selectedLeague.id}`, {
                expected_revision: selectedLeague.revision, lifecycle: selectedLeague.lifecycle,
                profile, reason, activate: false,
              }, "PUT"), "Profile assigned.");
            }} aria-label="Assigned profile">
              {["dynasty", "keeper", "redraft"].map(p => <option key={p}>{p}</option>)}
            </select>
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            <button className={secondary} disabled={blocked} onClick={() => changeLeague("active", true)}>Activate future events</button>
            <button className={secondary} disabled={blocked || selectedLeague.lifecycle === "retired"} onClick={() => changeLeague("retired", false)}>Retire league</button>
          </div>
        </div>}
        {policy && <form className="mt-4" onSubmit={e => {
          e.preventDefault();
          void act(() => generationRequest(`/policy/${encodeURIComponent(scope)}`, {
            expected_revision: policy.revision, value: draft, reason,
          }, "PUT"), "Configuration saved. Missed work will require a preview.");
        }}>
          <p className="text-prose text-dim">Revision {policy.revision}. Empty fields inherit. Broader pauses and process limits still apply.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <label className="text-prose">Generation
              <select className={controlClass} value={typeof draft.paused === "boolean" ? String(draft.paused) : ""} onChange={e => field("paused", e.target.value === "" ? undefined : e.target.value === "true")}>
                <option value="">Inherit ({policy.effective.policy.paused ? "paused" : "allowed"})</option>
                <option value="true">Paused</option><option value="false">Allowed</option>
              </select>
            </label>
            <label className="text-prose">Refresh interval (minutes)
              <input className={controlClass} type="number" min={15} max={10080} step={15}
                value={typeof draft.refresh_interval_seconds === "number" ? draft.refresh_interval_seconds / 60 : ""}
                placeholder={String(policy.effective.policy.refresh_interval_seconds / 60)}
                onChange={e => field("refresh_interval_seconds", e.target.value ? Number(e.target.value) * 60 : undefined)} />
            </label>
            <label className="text-prose">Maximum concurrent calls
              <input className={controlClass} type="number" min={1} max={4} step={1}
                value={typeof draft.max_concurrency === "number" ? draft.max_concurrency : ""}
                placeholder={String(policy.effective.policy.max_concurrency)}
                onChange={e => field("max_concurrency", e.target.value ? Number(e.target.value) : undefined)} />
            </label>
          </div>
          {features.map(feature => {
            const current = policy.effective.policy.features[feature], edited = overrides(feature);
            return <fieldset key={feature} className="mt-5 border-t border-rule pt-3">
              <legend className="px-1 font-display text-name font-bold">{FEATURE_LABELS[feature]}</legend>
              <p className="text-prose text-dim">{current.paused ? "Paused" : readable(current.mode)} · {current.max_calls} calls maximum · from {policy.effective.sources[`features.${feature}.mode`]}</p>
              <div className="mt-2 grid gap-3 sm:grid-cols-3">
                <label className="text-prose">Mode
                  <select className={controlClass} aria-label={FEATURE_LABELS[feature] + " mode"} value={edited.mode || ""} onChange={e => featureField(feature, "mode", e.target.value || undefined)}>
                    <option value="">Inherit</option><option value="disabled">Disabled</option><option value="manual">Owner approval</option><option value="automatic">New events automatically</option>
                  </select>
                </label>
                <label className="text-prose">Writer model
                  <select className={controlClass} value={edited.model || ""} onChange={e => featureField(feature, "model", e.target.value || undefined)}>
                    <option value="">Inherit ({current.model})</option>{models.map(model => <option key={model}>{model}</option>)}
                  </select>
                </label>
                <label className="text-prose">Call allowance
                  <select className={controlClass} value={edited.max_calls ?? ""} onChange={e => featureField(feature, "max_calls", e.target.value ? Number(e.target.value) : undefined)}>
                    <option value="">Inherit ({current.max_calls})</option>{(feature === "analyst" ? [2, 4] : [1, 2]).map(n => <option key={n} value={n}>{n} calls</option>)}
                  </select>
                </label>
              </div>
              <details className="mt-2">
                <summary className="min-h-tap cursor-pointer py-2 text-prose">Feature pause and response limits</summary>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-prose">Feature pause
                    <select className={controlClass} value={typeof edited.paused === "boolean" ? String(edited.paused) : ""} onChange={e => featureField(feature, "paused", e.target.value === "" ? undefined : e.target.value === "true")}>
                      <option value="">Inherit</option><option value="true">Paused</option><option value="false">Allowed</option>
                    </select>
                  </label>
                  <label className="text-prose">Maximum output tokens
                    <input className={controlClass} type="number" min={64} max={8192} value={edited.max_tokens ?? ""} placeholder={String(current.max_tokens)}
                      onChange={e => featureField(feature, "max_tokens", e.target.value ? Number(e.target.value) : undefined)} />
                  </label>
                  {feature === "analyst" && <label className="text-prose">Review and correction model
                    <select className={controlClass} value={edited.review_model || ""} onChange={e => featureField(feature, "review_model", e.target.value || undefined)}>
                      <option value="">Inherit ({current.review_model})</option>{models.map(model => <option key={model}>{model}</option>)}
                    </select>
                  </label>}
                </div>
              </details>
            </fieldset>;
          })}
          <Button type="submit" className="mt-4 px-4 py-2" disabled={blocked}>Save configuration</Button>
          <details className="mt-3"><summary className="min-h-tap cursor-pointer py-2 text-prose">Effective values and their sources</summary>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-label">{JSON.stringify(policy.effective, null, 2)}</pre>
          </details>
        </form>}
      </Panel>

      <Panel className="p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="text-prose">Activity
            <select className={controlClass} value={kind} disabled={busy} onChange={e => { setKind(e.target.value); setOffset(0); setDetail(null); }}>
              {["jobs", "candidates", "attempts", "artifacts", "audit", "outbox"].map(k => <option key={k}>{k}</option>)}
            </select>
          </label>
          {kind === "candidates" && <Button className="px-4 py-2" disabled={blocked || selected.length === 0} onClick={() => act(async () => {
            setPreview(await generationRequest<CampaignPreview>("/campaigns/preview", { candidates: selected, reason }));
          }, "Review the exact campaign below.", false)}>Preview {selected.length} selected</Button>}
        </div>
        {page.records.length === 0 && <p className="mt-4 text-prose text-dim">No {kind} in this scope. Refresh a league to collect verified facts and candidate content.</p>}
        <ul className="mt-3 divide-y divide-rule">
          {page.records.map(row => <li key={row.id || row.key} className="py-3">
            <div className="flex flex-col items-stretch justify-between gap-2 sm:flex-row sm:items-start">
              <div className="min-w-0 flex-1">
                <label className="flex items-start gap-2 text-prose">
                  {kind === "candidates" && <input className="mt-1" type="checkbox" checked={selected.includes(row.key!)}
                    disabled={busy || !availableHold(row.hold)} aria-label={"Select " + row.label}
                    onChange={e => { setPreview(null); setSelected(old => e.target.checked ? [...old, row.key!].slice(0, 100) : old.filter(k => k !== row.key)); }} />}
                  <span className="break-words font-semibold">{row.label || row.action || row.subject || row.id}
                    {row.feature && <span className="font-normal text-dim"> · {FEATURE_LABELS[row.feature]}</span>}
                  </span>
                </label>
                <p className="mt-1 break-words text-prose text-dim">{row.league_id || row.actor_id} {row.event || ""}
                  {" · "}{readable(row.state || row.hold || row.error || row.provenance as string)}
                  {row.reason ? " · " + readable(row.reason) : ""}
                  {row.calls !== undefined ? ` · ${row.calls}/${row.max_calls} calls` : ""}
                </p>
                {kind === "attempts" && <p className="font-mono text-label">{row.cost_microusd == null ? "Cost unknown" : `$${(row.cost_microusd / 1_000_000).toFixed(6)}`} · {row.model}</p>}
                <details className="mt-1"><summary className="min-h-tap cursor-pointer py-2 text-prose">Record details</summary>
                  <pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all text-label">{JSON.stringify(row, null, 2)}</pre>
                </details>
              </div>
              {kind === "jobs" && <div className="flex flex-wrap gap-2">
                <button className={secondary} disabled={busy} onClick={() => act(async () => {
                  setDetail(await generationRequest(`/jobs/${row.id}`));
                }, "Job evidence loaded.", false)}>Inspect</button>
                {row.state === "held" && <button className={secondary} disabled={blocked} onClick={() => jobAction(row, "resume")}>Resume remaining steps</button>}
                {row.state === "needs_attention" && row.reason === "provider_outcome_unknown" && <button className={secondary} disabled={blocked} onClick={() => jobAction(row, "resume")}>Resume settled work</button>}
                {!["succeeded", "cancelled"].includes(row.state || "") && <button className={secondary} disabled={blocked} onClick={() => jobAction(row, "cancel")}>Cancel</button>}
              </div>}
              {kind === "outbox" && !!row.error && <button className={secondary} disabled={blocked} onClick={() => act(
                () => generationRequest(`/outbox/${row.id}/retry`, { expected_error: row.error, reason }),
                "Saved publication queued again. No new writing was authorized.")}>Retry saved publication</button>}
              {kind === "artifacts" && <button className={secondary} disabled={blocked} onClick={() => act(async () => {
                const proposed = await generationRequest<GenerationRecord>(`/artifacts/${row.id}/correction`, { expected_artifact: row.id, reason });
                setSelected([proposed.key!]); setKind("candidates"); setOffset(0);
                setPreview(await generationRequest<CampaignPreview>("/campaigns/preview", { candidates: [proposed.key], reason }));
              }, "Correction proposed. Review the exact campaign before approving.", false)}>Propose correction</button>}
              {kind === "attempts" && row.cost_microusd == null && <div className="flex flex-wrap gap-2">
                <button className={secondary} disabled={blocked || !workersStopped || !evidence.trim()} onClick={() => act(() => generationRequest(
                  `/attempts/${row.id}/resolve`, { action: "abandon_unknown", expected_state: row.state, workers_stopped: workersStopped, evidence, reason }),
                "Attempt abandoned with its cost still unknown. Replacement work needs a new campaign approval.")}>Abandon uncertain attempt</button>
                <button className={secondary} disabled={blocked || !workersStopped || !evidence.trim()} onClick={() => act(() => generationRequest(
                  `/attempts/${row.id}/resolve`, { action: "not_sent", expected_state: row.state, workers_stopped: workersStopped, evidence, reason }),
                "Non-submission evidence recorded. No replacement job was authorized.")}>Record proof it was not sent</button>
              </div>}
            </div>
          </li>)}
        </ul>
        {kind === "attempts" && <label className="mt-3 block text-prose">Recovery evidence
          <textarea className={controlClass + " mt-1"} value={evidence} onChange={e => setEvidence(e.target.value)} maxLength={4000}
            placeholder="Record provider evidence and how you verified the sending process is stopped. Elapsed time alone is not proof." />
        </label>}
        <div className="mt-3 flex gap-2">
          <button className={secondary} disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button>
          <button className={secondary} disabled={busy || page.next_offset === null} onClick={() => setOffset(page.next_offset!)}>Next</button>
        </div>
        {detail !== null && <details open className="mt-4"><summary className="min-h-tap cursor-pointer py-2 text-prose">Job facts, settings, and provider receipts</summary>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-label">{JSON.stringify(detail, null, 2)}</pre>
        </details>}
        {preview && <div className="mt-5 border-t border-rule pt-4">
          <h3 className="font-display text-name font-bold">Campaign preview</h3>
          <p className="mt-1 text-prose">{preview.items.length} exact subject(s), at most {preview.max_calls} provider calls. Approval expires at {new Date(preview.expires_at * 1000).toLocaleTimeString()}.</p>
          <ul className="mt-3 space-y-2 text-prose">{preview.items.map(item => <li key={item.key}>
            <strong>{item.label}</strong> · {item.league_id} · {FEATURE_LABELS[item.feature]} · {item.event}
            <p className="text-dim">{item.model}; maximum {item.max_calls} calls and {item.max_tokens_per_call} output tokens per call. {readable(item.hold)}</p>
            {!!item.blocked_by.length && <p className="text-neg-strong">{item.blocked_by.map(readable).join("; ")}</p>}
          </li>)}</ul>
          <Button className="mt-4 px-4 py-2" disabled={blocked || preview.items.some(i => i.blocked_by.length > 0)} onClick={() => act(() => generationRequest("/campaigns/apply", {
            preview_id: preview.id, digest: preview.digest, reason,
          }), "Exact campaign approved. Jobs are queued.")}>Approve this exact campaign</Button>
        </div>}
      </Panel>
    </div>}
  </section>;
}
