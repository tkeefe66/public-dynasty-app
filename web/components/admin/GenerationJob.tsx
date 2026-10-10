import { useState } from "react";
import { generationRequest } from "@/lib/api";
import { GenerationRecord, GenerationSeries } from "@/lib/generation";
import { ActionForm, ActionProps, contentName, dateLabel, failedFreeRefresh, isDataRefresh, jobStatus, leagueName, money, problemExplanation, secondary, TechnicalDetails } from "./GenerationShared";

interface JobDetail { job?: GenerationRecord; attempts?: GenerationRecord[] }

export function GenerationJob({ row, leagues, busy, run, onRecapBudget, review = false, selected, onSelect }: ActionProps & { row: GenerationRecord; leagues: GenerationSeries[]; review?: boolean; selected?: boolean; onSelect?: (checked: boolean) => void }) {
  const [opened, setOpened] = useState(false);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [action, setAction] = useState("");
  // Keep display labels from the list while actions use the fetched job state.
  const job = detail?.job ? { ...row, ...detail.job } : row;
  const stopped = ["needs_attention", "held"].includes(job.state || "");
  const freeRefresh = isDataRefresh(job);
  const retryable = failedFreeRefresh(job);
  const resumable = job.feature !== 'recap_video' && ((job.state === "held" && job.reason !== "restore_reapproval_required") || (job.state === "needs_attention" && job.reason === "provider_outcome_unknown"));
  const attempts = detail?.attempts || [];
  const blocked = busy || loading;
  const budgetHeld = job.reason?.startsWith("recap_budget_") || job.reason === "legacy_budget_reached";
  const budgetSeries = job.series_id || leagues.find(league => league.seasons.some(season => season.league_id === job.league_id))?.id;

  async function retryDataRefresh() {
    if (blocked) return;
    setOpened(true); setLoading(true); setError(""); setAction("");
    try {
      await run(async () => {
        const latest = await generationRequest<JobDetail>(`/jobs/${row.id}`);
        setDetail(latest);
        if (!latest.job || latest.job.id !== row.id || !Array.isArray(latest.attempts)) {
          throw new Error("The refresh details could not be verified. Reload status and try again.");
        }
        if (!failedFreeRefresh(latest.job)) {
          throw new Error("This refresh changed and no longer needs this retry. Its current status is shown on this row.");
        }
        if (latest.attempts.some(attempt => ["dispatching", "unknown"].includes(attempt.state || ""))) {
          throw new Error("A provider request still needs review. Open Advanced → AI requests and costs before retrying this refresh.");
        }
        if (latest.job.calls || latest.job.max_calls || latest.attempts.length) {
          throw new Error(problemExplanation({ reason: "data_refresh_has_provider_activity" }));
        }
        await generationRequest(`/jobs/${row.id}`, {
          action: "resume", expected_generation: latest.job.generation, expected_state: latest.job.state,
          reason: "Retry failed data refresh from administration",
        });
      }, "Data refresh queued.");
      setOpened(false);
    } catch (err) {
      // Observe a conflicting update without automatically repeating the mutation.
      if ((err as { status?: number })?.status === 409) {
        try { setDetail(await generationRequest<JobDetail>(`/jobs/${row.id}`)); }
        catch { /* Preserve the action error if its status check also fails. */ }
      }
      setError(err instanceof Error ? err.message : "The refresh could not restart. Reload status and try again.");
    } finally { setLoading(false); }
  }
  return <li className="py-4">
    <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
      <div className="min-w-0 text-prose">
        <p className="font-semibold">{onSelect && <input type="checkbox" className="mr-3" disabled={blocked} checked={selected} onChange={e => onSelect(e.target.checked)} aria-label={`Select ${contentName(job)} ${job.label || job.id}`} />}{contentName(job)}{job.label ? ` · ${job.label}` : ""}</p>
        <p className="mt-1 text-dim">{leagueName(job, leagues)}</p>
        <p className="mt-1">{stopped && job.reason === "execution_failed" ? freeRefresh ? "Data refresh stopped before completion" : "Writing stopped before completion" : jobStatus(job)}</p>
        {!review && <p className="mt-1 text-dim">{dateLabel(job.created_at)}</p>}
        {review && stopped && <p className="mt-1 max-w-2xl text-dim">{retryable ? "Retry this league's data import with the original account after the problem is fixed. This makes no paid AI request." : job.state === "held" ? problemExplanation(job) : job.reason === "provider_outcome_unknown" ? "The provider’s response needs to be confirmed before any retry." : "Review the problem before deciding what happens next."}</p>}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
      {budgetHeld && onRecapBudget && budgetSeries && <button className={secondary} disabled={blocked} onClick={() => onRecapBudget(budgetSeries)}>Review recap limits</button>}
      {job.feature === 'recap_video' && onRecapBudget && budgetSeries && <button className={secondary} disabled={blocked} onClick={() => onRecapBudget(budgetSeries)}>Review recap episode</button>}
      {retryable && <button className={secondary} disabled={blocked} onClick={retryDataRefresh}>Retry data refresh</button>}
      <button className={secondary} disabled={blocked} aria-expanded={opened} onClick={async () => {
        if (opened) { setOpened(false); setAction(""); return; }
        setOpened(true); setLoading(true); setError("");
        try { setDetail(await generationRequest<JobDetail>(`/jobs/${row.id}`)); }
        catch (err) { setError(err instanceof Error ? err.message : "Job details could not load. Close and reopen to try again."); }
        finally { setLoading(false); }
      }}>{opened ? "Close details" : stopped ? "Review problem" : "View details"}</button>
      </div>
    </div>
    {opened && <div className="mt-3 border-t border-rule pt-3 text-prose">
      {stopped && !(review && job.state === "held") && <p className="max-w-2xl">{problemExplanation(job)}</p>}
      {loading && <p role="status">{freeRefresh ? "Checking refresh status…" : "Loading saved receipts…"}</p>}
      {error && <p role="alert" className="text-neg-strong">{error}</p>}
      {detail && <>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          {!freeRefresh && <>
          <div><dt className="text-dim">AI requests used</dt><dd>{job.calls ?? 0} of {job.max_calls ?? 0} allowed</dd></div>
          <div><dt className="text-dim">Recorded request cost</dt><dd>{money(attempts.reduce((total, a) => total + (a.cost_microusd ?? 0), 0))}{attempts.some(a => a.cost_microusd == null) ? " + unknown charges" : ""}</dd></div>
          </>}
          <div><dt className="text-dim">Started</dt><dd>{dateLabel(job.created_at)}</dd></div>
        </dl>
        {resumable && <p className="mt-3 max-w-2xl text-dim">{freeRefresh ? "Resuming rebuilds league data using the saved account. Current league access is checked before the refresh runs." : "Resuming may use the remaining AI request allowance. Unresolved provider receipts must be settled first in Advanced → AI requests and costs."}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {resumable && <button className={secondary} disabled={blocked} onClick={() => setAction("resume")}>{freeRefresh ? "Resume data refresh" : job.state === "held" ? "Resume remaining work" : "Resume after receipt review"}</button>}
          {!["succeeded", "cancelled"].includes(job.state || "") && <button className={secondary} disabled={blocked} onClick={() => setAction("cancel")}>Cancel this work</button>}
        </div>
        {action && <ActionForm key={action} title={action === "cancel" ? "Cancel this work" : freeRefresh ? "Resume data refresh" : "Resume remaining work"}
          description={freeRefresh ? action === "cancel" ? "Stop this refresh and keep the league and its saved data." : "Rebuild this league's data with the saved account after the import problem has been fixed. The server rechecks the original member's access and connection. No paid writing is approved by this action." : action === "cancel" ? "Stop future steps and keep the saved records. Requests already sent may still incur charges. Cancelling does not approve replacement writing." : "Continue this job within its original request allowance. The server rechecks permissions and provider receipts before continuing."}
          submitLabel={action === "cancel" ? "Confirm cancellation" : "Confirm resume"} busy={blocked} onCancel={() => setAction("")} onSubmit={reason => run(() => generationRequest(`/jobs/${row.id}`, {
            action, expected_generation: job.generation, expected_state: job.state, reason,
          }), action === "cancel" ? "Work cancelled. Saved records are retained." : freeRefresh ? "Data refresh queued." : "Remaining work approved to resume.")} />}
        <TechnicalDetails value={detail} label={freeRefresh ? "Technical details" : "Technical details and saved receipts"} />
      </>}
    </div>}
  </li>;
}
