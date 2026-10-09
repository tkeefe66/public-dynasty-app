import { useState } from "react";
import { FEATURE_LABELS, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";

export const controlClass = "min-h-tap w-full rounded-sm border border-rule-strong bg-surface px-3 py-2 text-prose text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-ringfocus";
export const secondary = "min-h-tap rounded-sm border border-rule-strong px-3 py-2 text-prose hover:bg-surface-sunk focus-visible:outline focus-visible:outline-2 focus-visible:outline-ringfocus disabled:cursor-not-allowed disabled:text-dim";
export const summaryClass = "min-h-tap cursor-pointer py-2 font-display text-name font-bold";
export const readable = (value?: string) => value ? value.replaceAll("_", " ") : "None";
export const money = (value?: number | null) => value == null ? "Cost unknown" : `$${(value / 1_000_000).toFixed(4)}`;
export const dateLabel = (value?: number) => value ? new Date(value * 1000).toLocaleString() : "Time not recorded";
export type RunAction = (action: () => Promise<unknown>, notice: string, reload?: boolean) => Promise<void>;
export interface ActionProps { busy: boolean; run: RunAction }
export function leagueName(row: GenerationRecord, leagues: GenerationSeries[]) {
  return leagues.find(l => l.id === row.series_id || l.seasons.some(s => s.league_id === row.league_id))?.name || "League name unavailable";
}
export function contentName(row: GenerationRecord) {
  return row.feature && FEATURE_LABELS[row.feature] || (row.kind === "refresh" ? "League data refresh" : row.kind === "analyst_refresh" ? "Weekly Analyst data refresh" : "Background work");
}
export function jobStatus(row: GenerationRecord) {
  return ({ needs_attention: "Stopped — review required", held: "Paused — review required", queued: "Waiting to start", running: "In progress", succeeded: "Completed", cancelled: "Cancelled" } as Record<string, string>)[row.state || ""] || readable(row.state);
}
export function problemExplanation(row: GenerationRecord) {
  if (["refresh", "analyst_refresh"].includes(row.kind || "") && row.reason === "execution_failed") {
    return "The data refresh stopped before completion. After fixing the import problem, resume this saved refresh. Its league access and connection will be checked again.";
  }
  if (row.reason === "provider_outcome_unknown") return "We could not confirm whether the AI provider completed this request. Check the saved receipts before resuming; its cost may still be unknown.";
  const reasons: Record<string, string> = {
    restore_reapproval_required: "This work was restored from a backup and cannot resume. Cancel it, check provider activity, then preview and approve a replacement separately.",
    feature_breaker_open: "Repeated failures triggered a safety stop for this feature. Review the failures before resetting the stop under Advanced → Activation and recovery.",
    feature_paused: "This feature is paused or turned off. Review its shared and league settings before resuming.",
    worker_shutdown: "The worker stopped during this job. Review its saved receipts before resuming the remaining work.",
    resume_review_required: "This work was held when AI settings changed. Review it before approving the remaining steps.",
    emergency_pause: "The deployment safety switch blocked this work. Resolve the deployment pause in Railway before resuming.",
    attempt_allowance_exhausted: "This job has used its AI request allowance. Review its receipts before cancelling and separately approving any replacement.",
    legacy_budget_reached: "The existing AI budget has been reached. Review spending and the budget setting before resuming.",
    feature_unsupported: "This feature is not supported for this league. Cancel this work and choose a supported feature.",
    capability_unknown: "The league’s capabilities could not be verified. Refresh its data and verify the league setup before resuming.",
    manual_only: "This feature now requires your approval. Review this work before deciding whether to resume it.",
    failed_job_requires_replacement_review: "These jobs failed and need a separately reviewed replacement; resuming would repeat the failure or exceed their allowance.",
    free_refresh_requires_individual_review: "Review this failed data refresh individually. After fixing the import problem, resume it from Review problem.",
    writing_paused: "AI writing is paused. Resolve the pause before resuming.",
    job_no_longer_stopped: "These jobs changed state and no longer need this action. Reload status.",
    provider_cooldown: "The AI provider is temporarily unavailable or rate limited. Review the provider status before resuming.",
    membership_removed: "The membership that authorized this work was removed. Review league access before approving any replacement.",
  };
  if (row.reason && reasons[row.reason]) return reasons[row.reason];
  if (row.state === "held") return "This work is paused. Review the saved details and current settings before resuming its remaining steps.";
  if (row.reason === "execution_failed") return "Writing stopped before completion. The exact cause was not recorded in this job. Check the saved receipts and server logs before approving a replacement. A replacement requires a separate paid approval.";
  return "This work stopped and needs review. Check the saved details and current settings before deciding whether to cancel or resume it.";
}
export function TechnicalDetails({ value, label = "Technical details" }: { value: unknown; label?: string }) {
  return <details className="mt-3"><summary className="min-h-tap cursor-pointer py-2 text-prose text-dim">{label}</summary>
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-label">{JSON.stringify(value, null, 2)}</pre>
  </details>;
}

/** Reason and recovery evidence belong to the action, not a page-wide unlock field. */
export function ActionForm({ title, description, submitLabel, busy, onSubmit, onCancel, requireStopped = false, requireEvidence = false }: {
  title: string; description: string; submitLabel: string; busy: boolean;
  onSubmit: (reason: string, workersStopped: boolean, evidence: string) => Promise<void>;
  onCancel: () => void; requireStopped?: boolean; requireEvidence?: boolean;
}) {
  const [reason, setReason] = useState("");
  const [stopped, setStopped] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  return <form className="mt-3 space-y-3 border-t border-rule pt-3" onSubmit={async e => {
    e.preventDefault();
    if (busy || sending || !reason.trim() || (requireStopped && !stopped) || (requireEvidence && !evidence.trim())) return;
    setError(""); setSending(true);
    try { await onSubmit(reason.trim(), stopped, evidence.trim()); onCancel(); }
    catch (err) { setError(err instanceof Error ? err.message : "Action failed. Reload and try again."); }
    finally { setSending(false); }
  }}>
    <h4 className="font-semibold text-prose">{title}</h4>
    <p className="max-w-2xl text-prose text-dim">{description}</p>
    <label className="block text-prose">Reason for this action
      <input autoFocus className={controlClass + " mt-1"} value={reason} onChange={e => setReason(e.target.value)} required maxLength={1000} placeholder="Briefly explain this decision for the change history." />
    </label>
    {requireStopped && <label className="flex min-h-tap items-center gap-2 text-prose"><input type="checkbox" checked={stopped} onChange={e => setStopped(e.target.checked)} />I verified that the original sending processes and legacy workers are stopped.</label>}
    {requireEvidence && <label className="block text-prose">Recovery evidence<textarea className={controlClass} value={evidence} onChange={e => setEvidence(e.target.value)} maxLength={4000} placeholder="Provider evidence and how you verified the sending process is stopped. Time elapsed is not proof." /></label>}
    {error && <p role="alert" className="text-prose text-neg-strong">{error}</p>}
    <div className="flex flex-wrap gap-2"><Button type="submit" className="px-4 py-2" disabled={busy || sending || !reason.trim() || (requireStopped && !stopped) || (requireEvidence && !evidence.trim())}>{sending ? "Saving…" : submitLabel}</Button>
      <button type="button" className={secondary} disabled={busy || sending} onClick={onCancel}>Keep unchanged</button></div>
  </form>;
}
