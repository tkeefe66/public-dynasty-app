import { useEffect, useState } from "react";
import { generationRequest } from "@/lib/api";
import { FEATURE_LABELS, CampaignPreview, GenerationPage, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { GenerationJob } from "./GenerationJob";
import { ActionForm, ActionProps, contentName, controlClass, dateLabel, leagueName, money, readable, secondary, TechnicalDetails } from "./GenerationShared";

const availableHold = (hold?: string) => !hold || ["historical_approval_required", "missed_event_approval_required"].includes(hold);
const recordKinds = { attempts: "AI requests and costs", artifacts: "Saved content", audit: "Change history", outbox: "Publication delivery" };

export function GenerationRecords({ leagues, busy, run, version, initialKind = "jobs", advanced = false }: ActionProps & {
  leagues: GenerationSeries[]; version: number; initialKind?: string; advanced?: boolean;
}) {
  const [kind, setKind] = useState(initialKind);
  const [series, setSeries] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<GenerationPage<GenerationRecord>>({ records: [], next_offset: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [pendingPreview, setPendingPreview] = useState(false);
  const [action, setAction] = useState<{ row: GenerationRecord; name: string } | null>(null);
  const supportsLeagueFilter = ["jobs", "candidates", "artifacts"].includes(kind);
  useEffect(() => {
    let current = true;
    setLoading(true); setError(""); setPage({ records: [], next_offset: null });
    setSelected([]); setPreview(null); setAction(null);
    generationRequest<GenerationPage<GenerationRecord>>(`/records/${kind}?limit=25&offset=${offset}${series && supportsLeagueFilter ? `&series_id=${encodeURIComponent(series)}` : ""}`)
      .then(value => { if (current) setPage(value); })
      .catch(err => { if (current) setError(err.message || "Activity could not load. Try reloading."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [kind, series, offset, version, supportsLeagueFilter]);
  const blocked = busy || loading || pendingPreview;
  async function makePreview(keys: string[]) {
    setPendingPreview(true); setError(""); setPreview(null);
    try { setPreview(await generationRequest<CampaignPreview>("/campaigns/preview", { candidates: keys, reason: reason.trim() })); }
    catch (err) { setError(err instanceof Error ? err.message : "Preview could not load. Try again."); }
    finally { setPendingPreview(false); }
  }
  return <div className="mt-3">
    <div className="grid gap-3 sm:grid-cols-2">
      {supportsLeagueFilter && <label className="text-prose">{advanced ? "Records for league" : kind === "candidates" ? "Content for league" : "Activity for league"}
        <select className={controlClass + " mt-1"} disabled={blocked} value={series} onChange={e => { setSeries(e.target.value); setOffset(0); }}><option value="">All leagues</option>{leagues.map(l => <option key={l.id} value={l.id}>{l.name || "Unnamed league"}</option>)}</select>
      </label>}
      {advanced && <label className="text-prose">Record type<select className={controlClass + " mt-1"} disabled={blocked} value={kind} onChange={e => { setKind(e.target.value); setOffset(0); }}>{Object.entries(recordKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
    </div>
    {!supportsLeagueFilter && <p className="mt-2 text-prose text-dim">Records across all leagues.</p>}
    {kind === "candidates" && <p className="mt-3 max-w-2xl text-prose text-dim">Select content, review its request allowance, then approve paid writing. Selection and preview do not call the AI provider. Already completed or otherwise ineligible items will be rejected by the preview.</p>}
    {loading && <p role="status" className="mt-3 text-prose">Loading records…</p>}
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {!loading && !error && !page.records.length && <p className="mt-3 text-prose text-dim">{kind === "candidates" ? "Content ready for approval will appear here after a league data refresh." : "Records will appear here as work runs for these leagues."}</p>}
    <ul className="mt-3 divide-y divide-rule">
      {page.records.map(row => kind === "jobs" ? <GenerationJob key={`${row.id}:${row.state}:${row.generation}`} row={row} leagues={leagues} busy={blocked} run={run} /> : <li key={row.id || row.key} className="py-4 text-prose">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
          <div className="min-w-0">
            <label className="flex items-start gap-3 font-semibold">
              {kind === "candidates" && <input type="checkbox" className="mt-1" checked={selected.includes(row.key!)} disabled={blocked || !availableHold(row.hold)} aria-label={"Select " + row.label} onChange={e => { setPreview(null); setSelected(old => e.target.checked ? [...old, row.key!].slice(0, 100) : old.filter(k => k !== row.key)); }} />}
              <span>{row.label || (kind === "audit" ? readable(row.action) : kind === "attempts" ? "AI request" : kind === "outbox" ? "Content publication" : contentName(row))}{row.label && row.feature ? ` · ${FEATURE_LABELS[row.feature]}` : ""}</span>
            </label>
            {supportsLeagueFilter && <p className="mt-1 text-dim">{leagueName(row, leagues)}</p>}
            <p className="mt-1 text-dim">{dateLabel(row.created_at || row.observed_at)}</p>
            {kind === "attempts" && <p className="mt-1">{money(row.cost_microusd)} · {row.model} · {readable(row.state)}</p>}
            {kind === "candidates" && <p className="mt-1 text-dim">{availableHold(row.hold) ? "Available to preview" : `Blocked: ${readable(row.hold)}`} · {readable(row.event)}</p>}
            {kind === "outbox" && <p className="mt-1">{row.error ? "Saved content could not be delivered. Retry delivery without buying new writing." : row.delivered ? "Delivered" : "Waiting for delivery"}</p>}
            {kind === "audit" && <p className="mt-1 break-words">{row.reason}</p>}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {kind === "outbox" && !!row.error && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "retry" })}>Retry saved publication</button>}
            {kind === "artifacts" && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "correction" })}>Propose correction</button>}
            {kind === "attempts" && row.cost_microusd == null && <button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "recovery" })}>Review uncertain request</button>}
          </div>
        </div>
        {action?.row.id === row.id && action && <>
          {action.name === "recovery" && <div className="mt-3 flex flex-wrap gap-2"><button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "abandon_unknown" })}>Keep cost unknown and close request</button><button className={secondary} disabled={blocked} onClick={() => setAction({ row, name: "not_sent" })}>Record proof it was not sent</button></div>}
          {action.name !== "recovery" && <ActionForm key={`${row.id}:${action.name}`} title={action.name === "retry" ? "Retry saved publication" : action.name === "correction" ? "Propose a correction" : "Resolve uncertain request"}
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
    {kind === "candidates" && <div className="mt-3 border-t border-rule pt-3">
      <label className="block text-prose">Reason for this approval<input className={controlClass + " mt-1"} value={reason} maxLength={1000} disabled={blocked} onChange={e => { setReason(e.target.value); setPreview(null); }} placeholder="Why should this content be written?" /></label>
      <button className={secondary + " mt-3"} disabled={blocked || !selected.length || !reason.trim()} onClick={() => makePreview(selected)}>Preview {selected.length} selected</button>
    </div>}
    {(offset > 0 || page.next_offset !== null) && <div className="mt-3 flex flex-wrap items-center gap-3 text-prose"><button className={secondary} disabled={blocked || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button><span>Showing {offset + 1}–{offset + page.records.length}</span><button className={secondary} disabled={blocked || page.next_offset === null} onClick={() => setOffset(page.next_offset!)}>Next</button></div>}
    {preview && <div className="mt-5 border-t border-rule pt-4 text-prose">
      <h4 className="font-display text-name font-bold">Review before paying for AI writing</h4>
      <p className="mt-2">{preview.items.length} content items · At most {preview.max_calls} AI requests.</p>
      <p className="mt-1 text-dim">This is a request limit, not a dollar quote. Review expires at {new Date(preview.expires_at * 1000).toLocaleTimeString()}.</p>
      <ul className="mt-3 space-y-3">{preview.items.map(item => <li key={item.key}><strong>{item.label} · {FEATURE_LABELS[item.feature]}</strong><p>{leagueName(item, leagues)} · {readable(item.event)}</p><p className="text-dim">{item.model} · up to {item.max_calls} requests</p>{item.blocked_by.length > 0 && <p className="text-neg-strong">Blocked: {item.blocked_by.map(readable).join("; ")}</p>}</li>)}</ul>
      <Button className="mt-3 px-4 py-2" disabled={blocked || !reason.trim() || preview.items.some(i => i.blocked_by.length > 0)} onClick={async () => {
        setError("");
        try { await run(() => generationRequest("/campaigns/apply", { preview_id: preview.id, digest: preview.digest, reason }), "Paid writing approved for the reviewed content."); setPreview(null); }
        catch (err) { setError(err instanceof Error ? err.message : "Approval failed. Reload and preview again."); }
      }}>Approve paid writing</Button>
    </div>}
  </div>;
}
