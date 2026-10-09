import { useState } from "react";
import { generationRequest } from "@/lib/api";
import { GenerationRecord, GenerationSeries } from "@/lib/generation";
import { ActionForm, ActionProps, contentName, dateLabel, isDataRefresh, jobStatus, leagueName, money, problemExplanation, secondary, TechnicalDetails } from "./GenerationShared";

export function GenerationJob({ row, leagues, busy, run, review = false, selected, onSelect }: ActionProps & { row: GenerationRecord; leagues: GenerationSeries[]; review?: boolean; selected?: boolean; onSelect?: (checked: boolean) => void }) {
  const [opened, setOpened] = useState(false);
  const [detail, setDetail] = useState<{ job?: GenerationRecord; attempts?: GenerationRecord[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [action, setAction] = useState("");
  const stopped = ["needs_attention", "held"].includes(row.state || "");
  const dataRetry = isDataRefresh(row) && row.state === "needs_attention" && row.reason === "execution_failed";
  const resumable = dataRetry || (row.state === "held" && row.reason !== "restore_reapproval_required") || (row.state === "needs_attention" && row.reason === "provider_outcome_unknown");
  const attempts = detail?.attempts || [];
  return <li className="py-4">
    <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
      <div className="min-w-0 text-prose">
        <p className="font-semibold">{onSelect && <input type="checkbox" className="mr-3" disabled={busy} checked={selected} onChange={e => onSelect(e.target.checked)} aria-label={`Select ${contentName(row)} ${row.label || row.id}`} />}{contentName(row)}{row.label ? ` · ${row.label}` : ""}</p>
        <p className="mt-1 text-dim">{leagueName(row, leagues)}</p>
        <p className="mt-1">{stopped ? (row.reason === "execution_failed" ? (dataRetry ? "Data refresh stopped before completion" : "Writing stopped before completion") : jobStatus(row)) : jobStatus(row)}</p>
        {!review && <p className="mt-1 text-dim">{dateLabel(row.created_at)}</p>}
        {review && <p className="mt-1 max-w-2xl text-dim">{row.state === "held" ? problemExplanation(row) : row.reason === "provider_outcome_unknown" ? "The provider’s response needs to be confirmed before any retry." : "Review the problem before deciding what happens next."}</p>}
      </div>
      <button className={secondary + " shrink-0"} disabled={busy || loading} aria-expanded={opened} onClick={async () => {
        if (opened) { setOpened(false); setAction(""); return; }
        setOpened(true); setLoading(true); setError("");
        try { setDetail(await generationRequest(`/jobs/${row.id}`)); }
        catch (err) { setError(err instanceof Error ? err.message : "Job details could not load. Close and reopen to try again."); }
        finally { setLoading(false); }
      }}>{opened ? "Close details" : stopped ? "Review problem" : "View details"}</button>
    </div>
    {opened && <div className="mt-3 border-t border-rule pt-3 text-prose">
      {stopped && !(review && row.state === "held") && <p className="max-w-2xl">{problemExplanation(row)}</p>}
      {loading && <p role="status">Loading saved receipts…</p>}
      {error && <p role="alert" className="text-neg-strong">{error}</p>}
      {detail && <>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <div><dt className="text-dim">AI requests used</dt><dd>{row.calls ?? 0} of {row.max_calls ?? 0} allowed</dd></div>
          <div><dt className="text-dim">Recorded request cost</dt><dd>{money(attempts.reduce((total, a) => total + (a.cost_microusd ?? 0), 0))}{attempts.some(a => a.cost_microusd == null) ? " + unknown charges" : ""}</dd></div>
          <div><dt className="text-dim">Started</dt><dd>{dateLabel(row.created_at)}</dd></div>
        </dl>
        {resumable && <p className="mt-3 max-w-2xl text-dim">{dataRetry ? "Retry after the underlying problem is fixed. This collects league data without approving paid writing." : "Resuming may use the remaining AI request allowance. Unresolved provider receipts must be settled first in Advanced → AI requests and costs."}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {resumable && <button className={secondary} disabled={busy} onClick={() => setAction("resume")}>{dataRetry ? "Retry data refresh" : row.state === "held" ? "Resume remaining work" : "Resume after receipt review"}</button>}
          {!["succeeded", "cancelled"].includes(row.state || "") && <button className={secondary} disabled={busy} onClick={() => setAction("cancel")}>Cancel this work</button>}
        </div>
        {action && <ActionForm key={action} title={action === "cancel" ? "Cancel this work" : dataRetry ? "Retry data refresh" : "Resume remaining work"}
          description={action === "cancel" ? "Stop future steps and keep the saved records. Requests already sent may still incur charges. Cancelling does not approve replacement writing." : dataRetry ? "Retry this saved data job after fixing its cause. The server rechecks the original member’s access and provider connection. No paid writing is approved by this action." : "Continue this job within its original request allowance. The server rechecks permissions and provider receipts before continuing."}
          submitLabel={action === "cancel" ? "Confirm cancellation" : dataRetry ? "Confirm data retry" : "Confirm resume"} busy={busy} onCancel={() => setAction("")} onSubmit={reason => run(() => generationRequest(`/jobs/${row.id}`, {
            action, expected_generation: row.generation, expected_state: row.state, reason,
          }), action === "cancel" ? "Work cancelled. Saved records are retained." : dataRetry ? "Data refresh queued for another attempt." : "Remaining work approved to resume.")} />}
        <TechnicalDetails value={detail} label="Technical details and saved receipts" />
      </>}
    </div>}
  </li>;
}
