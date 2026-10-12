import { useEffect, useState } from "react";
import { generationRequest } from "@/lib/api";
import { CampaignPreview, GenerationRecord, GenerationSeries, JobResolution } from "@/lib/generation";
import { GenerationApproval } from './GenerationApproval';
import { CopyIssueDetails } from './CopyIssueDetails';
import { ActionForm, ActionProps, contentName, dateLabel, failedFreeRefresh, isDataRefresh, jobStatus, leagueName, money, problemExplanation, secondary, TechnicalDetails } from "./GenerationShared";

interface JobDetail { job?: GenerationRecord; attempts?: GenerationRecord[]; resolution?: JobResolution }

export function GenerationJob({ row, leagues, busy, run, onRecapBudget, onRecapEpisode, onWritingRules, onActivity, review = false, selected, onSelect }: ActionProps & { row: GenerationRecord; leagues: GenerationSeries[]; review?: boolean; selected?: boolean; onSelect?: (checked: boolean) => void }) {
  const [opened, setOpened] = useState(false);
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [action, setAction] = useState("");
  const [replacement, setReplacement] = useState<CampaignPreview | null>(null);
  const [replacementPrepared, setReplacementPrepared] = useState(false);
  const resolution = detail?.resolution;
  useEffect(() => {
    if (!review) return;
    let current = true;
    setLoading(true); setError('');
    generationRequest<JobDetail>(`/jobs/${row.id}`).then(value => {
      if (current) setDetail(value);
    }).catch(err => { if (current) setError(err instanceof Error ? err.message : 'Could not check this issue. Reload status to try again.'); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [row.id, row.state, row.generation, review]);
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
          throw new Error("A provider request still needs review. Open Recovery → AI requests and costs before retrying this refresh.");
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
    <div className={review ? 'flex flex-col items-start gap-3' : 'flex flex-col items-start justify-between gap-3 sm:flex-row'}>
      <div className="min-w-0 text-prose">
        <p className="font-semibold">{onSelect && <input type="checkbox" className="mr-3" disabled={blocked} checked={selected} onChange={e => onSelect(e.target.checked)} aria-label={`Select ${contentName(job)} ${job.label || job.id}`} />}{contentName(job)}{job.label ? ` · ${job.label}` : ""}</p>
        <p className="mt-1 text-dim">{leagueName(job, leagues)}</p>
        <p className="mt-1">{stopped && job.reason === "execution_failed" ? freeRefresh ? "Data refresh stopped before completion" : "Writing stopped before completion" : jobStatus(job)}</p>
        {!review && <p className="mt-1 text-dim">{dateLabel(job.created_at)}</p>}
        {review && stopped && !resolution && <p className="mt-1 max-w-2xl text-dim">{loading ? 'Checking saved work and previous requests…' : problemExplanation(job)}</p>}
        {review && resolution && !replacementPrepared && <div className="mt-3 max-w-2xl"><p className="font-semibold">{resolution.title}</p><p className="mt-1 text-dim">{resolution.explanation}</p><p className="mt-2">{resolution.cost}</p></div>}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
      {budgetHeld && onRecapBudget && budgetSeries && <button className={secondary} disabled={busy} onClick={() => onRecapBudget(budgetSeries)}>Review recap limits</button>}
      {job.feature === 'recap_video' && (onRecapEpisode || onRecapBudget) && budgetSeries && <button className={secondary} disabled={busy} onClick={() => (onRecapEpisode || onRecapBudget)?.(budgetSeries)}>Review recap episode</button>}
      {retryable && (!resolution || resolution.action === 'retry_refresh') && <button className={secondary} disabled={blocked} onClick={retryDataRefresh}>Retry data refresh</button>}
      {review && !replacementPrepared && resolution?.action === 'resume' && <button className={secondary} disabled={blocked} onClick={() => { setOpened(true); setAction('resume'); }}>Continue this work</button>}
      {review && resolution?.action === 'budget' && resumable && <button className={secondary} disabled={blocked} onClick={() => { setOpened(true); setAction('resume'); }}>Continue after reviewing limits</button>}
      {review && !replacementPrepared && resolution?.action === 'replacement' && <button className={secondary} disabled={blocked} onClick={() => { setOpened(true); setAction('replacement'); }}>Review new writing attempt</button>}
      {review && resolution?.action === 'settings' && onWritingRules && <button className={secondary} disabled={blocked} onClick={onWritingRules}>Review writing rules</button>}
      {review && resolution && ['related', 'wait', 'none'].includes(resolution.action) && onActivity && <button className={secondary} disabled={busy} onClick={onActivity}>Check progress in Activity</button>}
      {review && resolution?.action === 'retry_publication' && <button className={secondary} disabled={blocked} onClick={async () => {
        setError('');
        try { await run(() => generationRequest(`/outbox/${resolution.outbox_id}/retry`, { expected_error: resolution.expected_error, reason: 'Retry saved publication from issue review' }), 'Publication queued. No new writing was purchased.'); }
        catch (err) { setError(err instanceof Error ? err.message : 'Publication could not be queued. Reload status and try again.'); }
      }}>Publish saved content</button>}
      {review && resolution && <CopyIssueDetails report={resolution.report} busy={blocked} />}
      {review && detail?.job && stopped && !replacementPrepared && <button className={secondary} disabled={blocked} onClick={() => { setOpened(true); setAction('cancel'); }}>Cancel this work</button>}
      <button className={secondary} disabled={blocked} aria-expanded={opened} onClick={async () => {
        if (opened) { setOpened(false); setAction(""); return; }
        setOpened(true);
        if (review && detail) return;
        setLoading(true); setError("");
        try { setDetail(await generationRequest<JobDetail>(`/jobs/${row.id}`)); }
        catch (err) { setError(err instanceof Error ? err.message : "Job details could not load. Close and reopen to try again."); }
        finally { setLoading(false); }
      }}>{opened ? "Close details" : review ? "View details" : stopped ? "Review problem" : "View details"}</button>
      </div>
    </div>
    {review && error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error} Reload status to check this issue again.</p>}
    {replacementPrepared && <p role="status" className="mt-3 text-prose">The old attempt is cancelled. Replacement writing has not started; approve the reviewed request below to start it.</p>}
    {replacement && <GenerationApproval preview={replacement} leagues={leagues} busy={blocked} onBack={() => { setReplacement(null); run(async () => {}, 'Old attempt cancelled. No replacement writing was approved.').catch(err => setError(err instanceof Error ? err.message : 'Reload status to see the cancelled attempt.')); }} onApprove={async () => {
      await run(() => generationRequest('/campaigns/apply', { preview_id: replacement.id, digest: replacement.digest, reason: 'Approve reviewed replacement writing' }), 'Replacement writing queued. Follow its progress in Activity.');
      setReplacement(null); setReplacementPrepared(false); onActivity?.();
    }} />}
    {opened && <div className="mt-3 border-t border-rule pt-3 text-prose">
      {stopped && !review && !resolution && <p className="max-w-2xl">{problemExplanation(job)}</p>}
      {loading && <p role="status">{freeRefresh ? "Checking refresh status…" : "Loading saved receipts…"}</p>}
      {!review && error && <p role="alert" className="text-neg-strong">{error}</p>}
      {detail && <>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          {!freeRefresh && <>
          <div><dt className="text-dim">AI requests used</dt><dd>{job.calls ?? 0} of {job.max_calls ?? 0} allowed</dd></div>
          <div><dt className="text-dim">Recorded request cost</dt><dd>{money(attempts.reduce((total, a) => total + (a.cost_microusd ?? 0), 0))}{attempts.some(a => a.cost_microusd == null) ? " + unknown charges" : ""}</dd></div>
          </>}
          <div><dt className="text-dim">Started</dt><dd>{dateLabel(job.created_at)}</dd></div>
        </dl>
        {!review && resumable && <p className="mt-3 max-w-2xl text-dim">{freeRefresh ? "Resuming rebuilds league data using the saved account. Current league access is checked before the refresh runs." : "Resuming may use the remaining AI request allowance. Unresolved provider receipts must be settled first in Recovery → AI requests and costs."}</p>}
        {!review && <div className="mt-3 flex flex-wrap gap-2">
          {resumable && <button className={secondary} disabled={blocked} onClick={() => setAction("resume")}>{freeRefresh ? "Resume data refresh" : job.state === "held" ? "Resume remaining work" : "Resume after receipt review"}</button>}
          {!["succeeded", "cancelled"].includes(job.state || "") && <button className={secondary} disabled={blocked} onClick={() => setAction("cancel")}>Cancel this work</button>}
        </div>}
        {action === 'replacement' && <ActionForm title="Review a replacement" description="Cancel the stopped attempt and prepare a new request for the same content. This keeps the history and sends no AI request. You will review the allowance and approve paid writing separately." submitLabel="Cancel old attempt & review replacement" defaultReason="Cancel stopped attempt and review replacement" busy={blocked} onCancel={() => setAction('')} onSubmit={async reason => {
          await run(async () => { const proposed = await generationRequest<CampaignPreview>(`/jobs/${job.id}/replacement`, { expected_generation: job.generation, expected_state: job.state, reason }); setReplacement(proposed); setReplacementPrepared(true); }, 'Old attempt cancelled. Review the replacement before paying for writing.', false);
        }} />}
        {action && action !== 'replacement' && <ActionForm key={action} title={action === "cancel" ? "Cancel this work" : freeRefresh ? "Resume data refresh" : "Resume remaining work"}
          defaultReason={review ? action === 'cancel' ? 'Cancel unwanted work from issue review' : 'Continue reviewed work within its original allowance' : undefined}
          description={freeRefresh ? action === "cancel" ? "Stop this refresh and keep the league and its saved data." : "Rebuild this league's data with the saved account after the import problem has been fixed. The server rechecks the original member's access and connection. No paid writing is approved by this action." : action === "cancel" ? "Stop future steps and keep the saved records. Requests already sent may still incur charges. Cancelling does not approve replacement writing." : "Continue this job within its original request allowance. The server rechecks permissions and provider receipts before continuing."}
          submitLabel={action === "cancel" ? "Confirm cancellation" : "Confirm resume"} busy={blocked} onCancel={() => setAction("")} onSubmit={reason => run(() => generationRequest(`/jobs/${row.id}`, {
            action, expected_generation: job.generation, expected_state: job.state, reason,
          }), action === "cancel" ? "Work cancelled. Saved content and history are kept; the original issue has not been repaired." : freeRefresh ? "Data refresh queued." : "Work queued to continue within its original allowance.")} />}
        {resolution && resolution.related_jobs.length > 1 && <details className="mt-3"><summary className={secondary}>Related attempts ({resolution.related_jobs.length})</summary><ul className="mt-2 divide-y divide-rule">{resolution.related_jobs.map(related => <li key={related.id} className="py-2">{dateLabel(related.created_at)} · {jobStatus(related)}{related.id === row.id ? ' · This attempt' : ''}</li>)}</ul></details>}
        <TechnicalDetails value={detail} label={freeRefresh ? "Technical details" : "Technical details and saved receipts"} />
      </>}
    </div>}
  </li>;
}
