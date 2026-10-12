import { useEffect, useState } from "react";
import { generationRequest } from "@/lib/api";
import { FEATURE_LABELS, CampaignPreview, GenerationFeature, GenerationPage, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { GenerationApproval } from "./GenerationApproval";
import { CopyIssueDetails } from './CopyIssueDetails';
import { GenerationJob } from "./GenerationJob";
import { ActionForm, ActionProps, contentName, controlClass, dateLabel, leagueName, money, readable, secondary, TechnicalDetails } from "./GenerationShared";

const available = (row: GenerationRecord) => !!row.key && row.availability === "available"
  && row.reviewable === true && !row.blocked_by?.length;
const reviewReasons: Record<string, string> = {
  manual_approval_required: "Awaiting manual approval",
  historical_approval_required: "Optional historical content",
  missed_event_approval_required: "Optional missed-event content",
  correction_approval_required: "Requested correction",
};
const recordKinds = { attempts: "AI requests and costs", artifacts: "Saved content", audit: "Change history", outbox: "Publication delivery" };

export function GenerationRecords({ leagues, busy, run, onRecapBudget, onRecapEpisode, onActivity, version, initialKind = "jobs", advanced = false, featureFilter, scopeSeries, reviewOnly = false }: ActionProps & {
  leagues: GenerationSeries[]; version: number; initialKind?: string; advanced?: boolean; featureFilter?: GenerationFeature; scopeSeries?: string; reviewOnly?: boolean;
}) {
  const [kind, setKind] = useState(initialKind);
  const [localSeries, setSeries] = useState("");
  const series = scopeSeries ?? localSeries;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<GenerationPage<GenerationRecord>>({ records: [], next_offset: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("Approve selected available content across leagues");
  const [queued, setQueued] = useState(false);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [pendingPreview, setPendingPreview] = useState(false);
  const [action, setAction] = useState<{ row: GenerationRecord; name: string } | null>(null);
  const supportsLeagueFilter = ["jobs", "candidates", "artifacts"].includes(kind) || (reviewOnly && kind === 'outbox');
  const featureQuery = featureFilter && supportsLeagueFilter ? `&feature=${featureFilter}` : "";
  useEffect(() => {
    let current = true;
    setLoading(true); setError(""); setPage({ records: [], next_offset: null });
    setSelected([]); setPreview(null); setAction(null);
    generationRequest<GenerationPage<GenerationRecord>>(`/records/${kind}?limit=25&offset=${offset}${series && supportsLeagueFilter ? `&series_id=${encodeURIComponent(series)}` : ""}${kind === "candidates" || reviewOnly ? "&view=review" : ""}${featureQuery}`)
      .then(value => { if (current) setPage(value); })
      .catch(err => { if (current) setError(err.message || "Activity could not load. Try reloading."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [kind, series, offset, version, supportsLeagueFilter, featureQuery, reviewOnly]);
  const blocked = busy || loading || pendingPreview;
  const visibleRecords = kind === "candidates" ? page.records.filter(available) : page.records;
  async function selectAll() {
    setPendingPreview(true); setError(""); setPreview(null);
    try {
      const keys: string[] = [];
      let next: number | null = 0;
      while (next !== null) {
        const result: GenerationPage<GenerationRecord> = await generationRequest(`/records/candidates?limit=100&offset=${next}${series ? `&series_id=${encodeURIComponent(series)}` : ""}&view=review${featureQuery}`);
        keys.push(...result.records.filter(available).map(row => row.key!));
        if (keys.length > 1000) throw new Error("More than 1,000 items are available. Select a league and try again.");
        next = result.next_offset;
      }
      setSelected([...new Set(keys)]);
      setReason("Approve selected available content across leagues");
    } catch (err) { setError(err instanceof Error ? err.message : "Selection failed. Try again."); }
    finally { setPendingPreview(false); }
  }
  async function makePreview(keys: string[]) {
    setPendingPreview(true); setError(""); setPreview(null);
    try { setPreview(await generationRequest<CampaignPreview>("/campaigns/preview", { candidates: keys, reason: reason.trim() })); }
    catch (err) { setError(err instanceof Error ? err.message : "Preview could not load. Try again."); }
    finally { setPendingPreview(false); }
  }
  async function previewCatchup() {
    const explanation = "One-time catch-up of missing current content across leagues";
    setPendingPreview(true); setError(""); setPreview(null); setReason(explanation);
    try { setPreview(await generationRequest<CampaignPreview>("/campaigns/catch-up/preview", { series_id: series, reason: explanation })); }
    catch (err) { setError(err instanceof Error ? err.message : "Catch-up preview failed. Reload and try again."); }
    finally { setPendingPreview(false); }
  }
  if (reviewOnly && !loading && !error && !visibleRecords.length) return null;
  return <div className="mt-3">
    {reviewOnly && <h4 className="font-display text-name font-bold">Publication problems</h4>}
    <div className="grid gap-3 sm:grid-cols-2">
      {supportsLeagueFilter && scopeSeries === undefined && <label className="text-prose">{advanced ? "Records for league" : kind === "candidates" ? "Content for league" : "Activity for league"}
        <select className={controlClass + " mt-1"} disabled={blocked} value={series} onChange={e => { setSeries(e.target.value); setOffset(0); }}><option value="">All leagues</option>{leagues.map(l => <option key={l.id} value={l.id}>{l.name || "Unnamed league"}</option>)}</select>
      </label>}
      {advanced && <label className="text-prose">Record type<select className={controlClass + " mt-1"} disabled={blocked} value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}>{Object.entries(recordKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
    </div>
    {!supportsLeagueFilter && <p className="mt-2 text-prose text-dim">Records across all leagues.</p>}
    {kind === "candidates" && <p className="mt-3 max-w-2xl text-prose text-dim">Choose the content you want written. Review the request and spending allowance before you approve. Selecting content does not start writing.</p>}
    {kind === "candidates" && !featureFilter && <details className="mt-4 border-y border-rule py-3"><summary className="min-h-tap cursor-pointer py-2 text-prose font-semibold">Historical catch-up across content types</summary><div className="pb-3">
      <h4 className="font-display text-name font-bold">One-time catch-up</h4>
      <p className="mt-1 max-w-2xl text-prose text-dim">Gather missing completed-week Analyst roasts, current GM profiles and franchise outlooks, and trade stories from the last seven days. Completed content and work already running or needing repair are skipped.</p>
      <button className={secondary + " mt-3"} disabled={blocked} onClick={previewCatchup}>{series ? "Preview catch-up for this league" : "Preview catch-up across all leagues"}</button>
    </div></details>}
    {kind === "candidates" && <ol aria-label="Writing approval steps" className="mt-4 flex flex-wrap gap-4 text-prose">
      <li aria-current={!preview && !queued ? 'step' : undefined}>1. Select content</li>
      <li aria-current={preview ? 'step' : undefined}>2. Review request</li>
      <li aria-current={queued ? 'step' : undefined}>3. Approve & start</li>
    </ol>}
    {queued && <div role="status" className="mt-4 text-prose"><p>Writing queued. You can follow its progress in Activity.</p>{onActivity && <button className={secondary + " mt-2"} onClick={onActivity}>Follow writing progress</button>}</div>}
    {kind === "candidates" && !preview && <div className="sticky top-0 z-10 mt-3 flex flex-wrap items-center gap-3 border-y border-rule bg-surface py-3">
      <span role="status">{selected.length} selected across {series ? "this league" : "all leagues"}</span>
      <Button className="px-4 py-2" disabled={blocked || !selected.length} onClick={() => { setQueued(false); makePreview(selected); }}>{pendingPreview ? "Checking request…" : `Review & approve ${selected.length} ${selected.length === 1 ? 'item' : 'items'}`}</Button>
      <button className={secondary} disabled={blocked} onClick={selectAll}>Select all available content</button>
      <button className={secondary} disabled={blocked || !selected.length} onClick={() => { setSelected([]); setPreview(null); }}>Clear selection</button>
    </div>}
    {preview && <GenerationApproval preview={preview} leagues={leagues} busy={blocked} onBack={() => setPreview(null)} onApprove={async () => {
      await run(() => generationRequest("/campaigns/apply", { preview_id: preview.id, digest: preview.digest, reason }), "Writing queued. Follow its progress in Activity.");
      setPreview(null); setSelected([]); setQueued(true);
    }} />}
    {loading && <p role="status" className="mt-3 text-prose">Loading records…</p>}
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {!loading && !error && !visibleRecords.length && <p className="mt-3 text-prose text-dim">{kind === "candidates" ? "Available manual and historical content will appear here after a league data refresh." : "Records will appear here as work runs for these leagues."}</p>}
    <ul hidden={kind === "candidates" && !!preview} className="mt-3 divide-y divide-rule">
      {visibleRecords.map(row => kind === "jobs" ? <GenerationJob key={`${row.id}:${row.state}:${row.generation}`} row={row} leagues={leagues} busy={blocked} run={run} onRecapBudget={onRecapBudget} onRecapEpisode={onRecapEpisode} /> : <li key={row.id || row.key} className="py-4 text-prose">
        <div className={reviewOnly ? 'flex flex-col items-start gap-3' : 'flex flex-col items-start justify-between gap-3 sm:flex-row'}>
          <div className="min-w-0">
            <label className="flex items-start gap-3 font-semibold">
              {kind === "candidates" && <input type="checkbox" className="mt-1" checked={selected.includes(row.key!)} disabled={blocked || !available(row)} aria-label={"Select " + row.label} onChange={e => { setPreview(null); setReason(old => old || "Approve selected available content across leagues"); setSelected(old => e.target.checked ? [...old, row.key!].slice(0, 1000) : old.filter(k => k !== row.key)); }} />}
              <span>{row.label || (kind === "audit" ? readable(row.action) : kind === "attempts" ? "AI request" : kind === "outbox" ? "Content publication" : contentName(row))}{row.label && row.feature ? ` · ${FEATURE_LABELS[row.feature]}` : ""}</span>
            </label>
            {supportsLeagueFilter && <p className="mt-1 text-dim">{leagueName(row, leagues)}</p>}
            <p className="mt-1 text-dim">{dateLabel(row.created_at || row.observed_at)}</p>
            {kind === "attempts" && <p className="mt-1">{money(row.cost_microusd)} · {row.model} · {readable(row.state)}</p>}
            {kind === "candidates" && <p className="mt-1 text-dim">{reviewReasons[row.review_reason || ""] || "Available to preview"} · {readable(row.event)}</p>}
            {kind === "outbox" && <p className="mt-1">{row.error ? "Saved content could not be delivered. Retry delivery without buying new writing." : row.delivered ? "Delivered" : "Waiting for delivery"}</p>}
            {kind === "audit" && <p className="mt-1 break-words">{row.reason}</p>}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {kind === "outbox" && !!row.error && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "retry" })}>{reviewOnly ? 'Publish saved content' : 'Retry saved publication'}</button>}
            {reviewOnly && kind === 'outbox' && <CopyIssueDetails busy={blocked} report={`Publication issue — please investigate the saved content delivery.\nDelivery: ${row.id}\nArtifact reference: ${row.key}\nLeague: ${row.league_id || 'not recorded'}\nFailure: ${row.error || 'not recorded'}\nRetrying publication makes no new AI request.\nDo not generate replacement writing before checking the saved content.`} />}
            {kind === "artifacts" && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "correction" })}>Propose correction</button>}
            {kind === "attempts" && row.cost_microusd == null && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "recovery" })}>Review uncertain request</button>}
          </div>
        </div>
        {action?.row.id === row.id && action && <>
          {action.name === "recovery" && <div className="mt-3 flex flex-wrap gap-2"><button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "abandon_unknown" })}>Keep cost unknown and close request</button><button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "not_sent" })}>Record proof it was not sent</button></div>}
          {action.name !== "recovery" && <ActionForm key={`${row.id}:${action.name}`} title={action.name === "retry" ? "Retry saved publication" : action.name === "correction" ? "Propose a correction" : "Resolve uncertain request"}
            defaultReason={reviewOnly && action.name === 'retry' ? 'Retry saved publication from issue review' : undefined}
            description={action.name === "correction" ? "Creates a proposal for replacement content. Review and separately approve its AI request allowance before any paid writing." : action.name === "retry" ? "Deliver the content already saved. This makes no new AI request." : "Record provider evidence and verify the original sender has stopped. Closing this request does not authorize replacement work."}
            submitLabel={action.name === "correction" ? "Create correction proposal" : "Confirm action"} busy={blocked} onCancel={() => setAction(null)}
            requireStopped={["abandon_unknown", "not_sent"].includes(action.name)} requireEvidence={["abandon_unknown", "not_sent"].includes(action.name)}
            onSubmit={async (reason, workersStopped, evidence) => {
              if (action.name === "retry") await run(() => generationRequest(`/outbox/${row.id}/retry`, { expected_error: row.error, reason }), "Saved publication queued. No new writing was purchased.");
              else if (action.name === "correction") {
                // Keep the exact proposal local: never substitute a different candidate after refresh.
                await run(async () => {
                  const proposed = await generationRequest<GenerationRecord>(`/artifacts/${row.id}/correction`, { expected_artifact: row.id, reason });
                  const manifest = await generationRequest<CampaignPreview>("/campaigns/preview", { candidates: [proposed.key], reason });
                  setReason(reason); setPreview(manifest);
                }, "Correction proposed. Review its allowance before approving paid writing.", false);
              } else await run(() => generationRequest(`/attempts/${row.id}/resolve`, { action: action.name, expected_state: row.state, workers_stopped: workersStopped, evidence, reason }), "Provider evidence saved. No replacement work was approved.");
            }} />}
        </>}
        <TechnicalDetails value={row} />
      </li>)}
    </ul>
    {!preview && (offset > 0 || page.next_offset !== null) && <div className="mt-3 flex flex-wrap items-center gap-3 text-prose"><button className={secondary} disabled={blocked || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><span>{visibleRecords.length ? `Showing ${offset + 1}–${offset + visibleRecords.length}` : "No available items on this page"}</span><button className={secondary} disabled={blocked || page.next_offset === null} onClick={() => setOffset(page.next_offset!)}>Next</button></div>}

  </div>;
}
