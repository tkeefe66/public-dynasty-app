"use client";

import { useEffect, useRef, useState } from "react";
import { generationRequest } from "@/lib/api";
import { FEATURE_LABELS, GenerationFeature, GenerationOverview, GenerationPage, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { Panel } from "@/components/furniture/Panel";
import { GenerationSettings } from "./GenerationSettings";
import { GenerationBulkReview } from "./GenerationBulkReview";
import { GenerationRecords } from "./GenerationRecords";
import { ActionForm, money, readable, RunAction, secondary, summaryClass, TechnicalDetails } from "./GenerationShared";

const emptyPage: GenerationPage<GenerationRecord> = { records: [], next_offset: null };
const pauseReasons: Record<string, string> = {
  activation_required: "AI has not completed its safety activation.",
  app_paused: "AI writing is paused in the shared settings.",
  owner_paused: "You paused AI writing.", manual_pause: "You paused AI writing.",
};

export function GenerationControl() {
  const [overview, setOverview] = useState<GenerationOverview | null>(null);
  const [leagues, setLeagues] = useState<GenerationSeries[]>([]);
  const [stopped, setStopped] = useState(emptyPage);
  const [held, setHeld] = useState(emptyPage);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [action, setAction] = useState("");
  const [feature, setFeature] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [approvalsOpen, setApprovalsOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const mutationLock = useRef(false);

  useEffect(() => {
    let current = true;
    setLoading(true); setError("");
    async function registry() {
      const result: GenerationSeries[] = [];
      let offset: number | null = 0;
      while (offset !== null) {
        const page: GenerationPage<GenerationSeries> = await generationRequest(`/leagues?limit=100&offset=${offset}`);
        if (!current) return [];
        result.push(...page.records); offset = page.next_offset;
      }
      return result;
    }
    Promise.all([
      generationRequest<GenerationOverview>(), registry(),
      generationRequest<GenerationPage<GenerationRecord>>("/records/jobs?limit=25&state=needs_attention"),
      generationRequest<GenerationPage<GenerationRecord>>("/records/jobs?limit=25&state=held"),
    ]).then(([summary, registered, failed, paused]) => {
      if (current) { setOverview(summary); setLeagues(registered); setStopped(failed); setHeld(paused); }
    }).catch(err => { if (current) setError(err.message || "AI controls could not load. Reload to try again."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [version]);

  const run: RunAction = async (callback, message, reload = true) => {
    if (mutationLock.current) throw new Error("Another change is being saved. Wait for it to finish.");
    mutationLock.current = true; setBusy(true); setNotice("");
    try { await callback(); setNotice(message); if (reload) setVersion(v => v + 1); }
    finally { mutationLock.current = false; setBusy(false); }
  };
  const blocked = busy || loading;
  const breakers = overview ? JSON.parse(overview.control.breakers_json || "{}") as Record<string, { open?: boolean }> : {};
  const eligibleLeagues = leagues.filter(l => l.lifecycle === "active" && !l.hold && !l.effective.policy.paused && !l.effective.blocked_by.length);
  const globallyPaused = !!overview && (overview.emergency_paused || !!overview.control.hold || !!overview.control.provider_hold || (overview.effective.policy.paused && !eligibleLeagues.length));
  const enabledModes = eligibleLeagues.flatMap(l => Object.entries(l.effective.policy.features).filter(([name, f]) => !f.paused && !breakers[name]?.open).map(([, f]) => f.mode));
  const automatic = enabledModes.includes("automatic"), manual = enabledModes.includes("manual");
  const heading = globallyPaused ? "AI is paused" : automatic ? "Automatic writing is enabled" : manual ? "Waiting for your approval" : "AI writing is off";
  const reviewRows = [...stopped.records, ...held.records].filter((row, index, all) => all.findIndex(r => r.id === row.id) === index);

  return <section className="mt-10" aria-labelledby="generation-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 id="generation-title" className="font-display text-section font-bold">AI writing</h2><p className="mt-1 max-w-2xl text-prose text-dim">Review problems, approve content, and manage AI across your leagues.</p></div>
      <button className={secondary} disabled={blocked} onClick={() => setVersion(v => v + 1)}>Reload status</button>
    </div>
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {notice && <p role="status" className="mt-3 text-prose text-pos-strong">{notice}</p>}
    {loading && <p role="status" className="mt-3 text-prose text-dim">Checking AI status…</p>}
    {overview && <div className="mt-4 space-y-5">
      <Panel className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0"><h3 className="font-display text-name font-bold">{heading}</h3>
            <p className="mt-1 max-w-2xl text-prose text-dim">{globallyPaused ? "New paid writing is blocked. Review the reason below before resuming." : automatic ? "Some features may write for new events. Check Settings to see which leagues and features are automatic." : manual ? "New writing needs approval. Previously approved work may still finish." : "No active league currently has an available writing feature. Check Settings to enable one."}</p>
            <p className="mt-1 text-prose text-dim">League data refreshes run separately from paid AI writing.</p>
          </div>
          <button className={secondary} disabled={blocked} onClick={() => setAction(action === "pause" ? "" : "pause")}>Pause all AI writing</button>
        </div>
        {overview.emergency_paused && <p className="mt-3 text-prose text-neg-strong">The deployment safety switch is on. Turn off the emergency pause in Railway before activating AI here.</p>}
        {globallyPaused && overview.effective.blocked_by.length > 0 && <ul className="mt-3 space-y-1 text-prose">{overview.effective.blocked_by.map(reason => <li key={reason}>{pauseReasons[reason] || `Writing is blocked: ${readable(reason)}.`}</li>)}</ul>}
        {(Object.keys(FEATURE_LABELS) as GenerationFeature[]).filter(f => breakers[f]?.open).map(f => <p key={f} className="mt-3 text-prose text-warn-strong">{FEATURE_LABELS[f]} is stopped after repeated failures. Review the failed work, then reset its safety stop under Advanced → Activation and recovery.</p>)}
        <div className="mt-4 border-t border-rule pt-3 text-prose"><p>Tracked AI spend: <strong className="font-mono">{money(overview.known_cost_microusd)}</strong></p><p className="mt-1 text-dim">Total recorded by these controls, across all leagues. Excludes earlier spending and unrecorded charges.</p>
          {overview.unknown_cost_attempts > 0 && <p className="mt-2 text-warn-strong">{overview.unknown_cost_attempts} requests still have unknown cost. Review AI requests and costs under Advanced.</p>}
        </div>
        {action === "pause" && <ActionForm title="Pause all AI writing" description="Block new paid requests across every league. Requests already sent may still finish and incur charges. Data refreshes continue separately." submitLabel="Confirm pause" busy={blocked} onCancel={() => setAction("")} onSubmit={reason => run(() => generationRequest("/control", { action: "pause", feature: "", expected_revision: overview.control.revision, reason, workers_stopped: false }), "AI writing paused across all leagues.")} />}
      </Panel>

      <Panel className="p-4 sm:p-5" role="region" aria-labelledby="generation-review-title">
        <h3 id="generation-review-title" className="font-display text-name font-bold">Needs your review</h3>
        <p className="mt-1 text-prose text-dim">{overview.jobs.needs_attention || 0} stopped · {overview.jobs.held || 0} paused. Across all leagues.</p>
        {!reviewRows.length && <p className="mt-3 text-prose">No stopped or paused work to review. Content awaiting approval is below.</p>}
        <GenerationBulkReview rows={reviewRows} leagues={leagues} busy={blocked} run={run} version={version} />
        {([["needs_attention", stopped, setStopped], ["held", held, setHeld]] as const).map(([state, page, update]) => page.next_offset !== null && <button key={state} className={secondary + " mt-3"} disabled={blocked} onClick={async () => {
          setBusy(true); setError("");
          try { const more = await generationRequest<GenerationPage<GenerationRecord>>(`/records/jobs?limit=25&state=${state}&offset=${page.next_offset}`); update(old => ({ records: [...old.records, ...more.records], next_offset: more.next_offset })); }
          catch (err) { setError(err instanceof Error ? err.message : "More review items could not load."); }
          finally { setBusy(false); }
        }}>Load more {state === "held" ? "paused" : "stopped"} work</button>)}
        <details className="mt-3 border-t border-rule pt-2" open={approvalsOpen} onToggle={e => setApprovalsOpen(e.currentTarget.open)}><summary className={summaryClass}>Approve new content</summary>{approvalsOpen && <GenerationRecords leagues={leagues} busy={blocked} run={run} version={version} initialKind="candidates" />}</details>
      </Panel>

      <Panel className="p-4 sm:p-5"><details open={settingsOpen} onToggle={e => setSettingsOpen(e.currentTarget.open)}><summary className={summaryClass}>Settings</summary><p className="text-prose text-dim">Off, ask me first, or automatic — for all leagues or individual leagues.</p>{settingsOpen && <GenerationSettings leagues={leagues} busy={blocked} run={run} version={version} />}</details></Panel>
      <Panel className="p-4 sm:p-5"><details open={activityOpen} onToggle={e => setActivityOpen(e.currentTarget.open)}><summary className={summaryClass}>Recent activity</summary><p className="text-prose text-dim">What ran, when it ran, and how it ended. Open an item to see its recorded request cost.</p>{activityOpen && <GenerationRecords leagues={leagues} busy={blocked} run={run} version={version} />}</details></Panel>
      <Panel className="p-4 sm:p-5"><details open={advancedOpen} onToggle={e => setAdvancedOpen(e.currentTarget.open)}><summary className={summaryClass}>Advanced</summary><p className="text-prose text-dim">AI request costs, saved content, change history, and recovery tools.</p>
        {advancedOpen && <>
          <details className="mt-3"><summary className={summaryClass}>Activation and recovery</summary><p className="max-w-2xl text-prose text-dim">Use after resolving a provider or deployment problem. Activation requires a configured deployment ID, stopped legacy workers, and completed receipt checks. Missed work stays held for separate approval.</p>
            {!overview.execution_epoch_configured && <p className="mt-2 text-prose text-warn-strong">Setup required in Railway: configure the generation execution epoch before activation.</p>}
            <div className="mt-3 flex flex-wrap gap-2"><button className={secondary} disabled={blocked || !overview.execution_epoch_configured || overview.emergency_paused} onClick={() => setAction("activate")}>Activate AI execution</button><button className={secondary} disabled={blocked || !overview.control.provider_hold} onClick={() => setAction("clear_provider")}>Clear provider hold</button>
              {(Object.keys(FEATURE_LABELS) as GenerationFeature[]).filter(f => breakers[f]?.open).map(f => <button key={f} className={secondary} disabled={blocked} onClick={() => { setFeature(f); setAction("reset_breaker"); }}>Reset {FEATURE_LABELS[f]} safety stop</button>)}
            </div>
            {action && action !== "pause" && <ActionForm key={action + feature} title="Update AI recovery controls" description="Confirm the underlying problem is resolved. Existing policy limits still apply after this change." submitLabel="Confirm recovery" busy={blocked} requireStopped={action === "activate"} onCancel={() => setAction("")} onSubmit={(reason, workersStopped) => run(() => generationRequest("/control", { action, feature: action === "reset_breaker" ? feature : "", expected_revision: overview.control.revision, reason, workers_stopped: workersStopped }), "Recovery controls updated. Check AI status above.")} />}
            <TechnicalDetails value={overview} label="Control state and deployment details" />
          </details>
          <GenerationRecords leagues={leagues} busy={blocked} run={run} version={version} initialKind="attempts" advanced />
        </>}
      </details></Panel>
    </div>}
  </section>;
}
