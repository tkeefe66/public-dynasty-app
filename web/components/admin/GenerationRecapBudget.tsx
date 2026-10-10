import { useEffect, useRef, useState } from "react";
import { generationRequest } from "@/lib/api";
import { RecapBalance, RecapBudgetOvercommit, RecapBudgetView, RecapCapKey, RecapCaps } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { ActionProps, controlClass, money, secondary, TechnicalDetails } from "./GenerationShared";

const labels: Record<RecapCapKey, string> = {
  video_episode_microusd: "Video per episode ($)", video_month_microusd: "Video per month ($)",
  combined_episode_microusd: "Combined recap per episode, including video ($)",
  combined_month_microusd: "Combined recap per month, including video ($)",
};
const keys = Object.keys(labels) as RecapCapKey[];
export function parseDollars(value: string): number | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null;
  const [whole, fraction = ""] = value.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  const micro = cents * 10_000;
  return Number.isSafeInteger(micro) && micro > 0 ? micro : null;
}
function draftFor(view: RecapBudgetView) {
  return Object.fromEntries(keys.map(key => [key, (view.caps[key] / 1_000_000).toFixed(2)])) as Record<RecapCapKey, string>;
}
function monthDates(month: string) {
  const [year, number] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, number - 1, 1));
  const name = first.toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });
  return `${name} 1–${new Date(Date.UTC(year, number, 0)).getUTCDate()}, ${year} · America/Denver`;
}
function Spending({ balance, label }: { balance: RecapBalance; label: string }) {
  return <div role="group" aria-label={label} className="min-w-0 rounded-sm border border-rule p-3 text-prose">
    <h5 className="font-semibold">{label}</h5>
    <p>Known: {money(balance.known_microusd)}</p><p>Reserved: {money(balance.reserved_microusd)}</p>
    <p>Carry-forward: {money(balance.carry_forward_microusd)}</p>
    <p>Remaining: {balance.remaining_microusd === null ? "unavailable — unknown cost has no defensible ceiling" : money(balance.remaining_microusd)}</p>
    {balance.unknown_count > 0 && <p className="mt-1 text-warn-strong">{balance.unknown_count} unknown costs; {money(balance.uncertain_microusd)} already included in reserved and carry-forward.{balance.unbounded_unknown_count > 0 ? ` ${balance.unbounded_unknown_count} have no defensible ceiling.` : ""}</p>}
    {balance.overcommitted && <p className="mt-1 text-warn-strong">Committed obligations exceed the saved cap. Additional requests are held.</p>}
  </div>;
}

export function GenerationRecapBudget({ seriesId, episodeId, episodeLabel, busy, version, run }: ActionProps & { seriesId: string; episodeId?: string; episodeLabel?: string; version: number }) {
  const [view, setView] = useState<RecapBudgetView | null>(null);
  const [draft, setDraft] = useState<Record<RecapCapKey, string> | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [conflict, setConflict] = useState<RecapBudgetOvercommit | null>(null);
  const [reload, setReload] = useState(0);
  const sequence = useRef(0);
  const dirty = useRef(false);
  const lastVersion = useRef(version);
  const path = `/recap-budgets/${encodeURIComponent(seriesId)}${episodeId ? `?episode_id=${encodeURIComponent(episodeId)}` : ""}`;
  useEffect(() => {
    if (lastVersion.current !== version && !dirty.current) setReload(old => old + 1);
    lastVersion.current = version;
  }, [version]);
  useEffect(() => {
    const requestId = ++sequence.current;
    dirty.current = false;
    setLoading(true); setSending(false); setView(null); setDraft(null); setError(""); setNotice(""); setReason(""); setConflict(null); setAcknowledged(false);
    generationRequest<RecapBudgetView>(path).then(value => {
      if (sequence.current === requestId) { setView(value); setDraft(draftFor(value)); }
    }).catch(err => { if (sequence.current === requestId) setError(err instanceof Error ? err.message : "Recap limits could not load. Reload limits to try again."); })
      .finally(() => { if (sequence.current === requestId) setLoading(false); });
    return () => { sequence.current = requestId + 1; };
  }, [path, reload]);
  const blocked = busy || loading || sending;
  const parsed = draft ? Object.fromEntries(keys.map(key => [key, parseDollars(draft[key])])) as Record<RecapCapKey, number | null> : null;
  const invalid = !!parsed && keys.some(key => parsed[key] === null);
  const below = view && parsed ? keys.filter(key => {
    const balance = view.balances[key];
    return balance && parsed[key] !== null && parsed[key]! < balance.known_microusd + balance.reserved_microusd + balance.carry_forward_microusd;
  }) : [];
  const needsAcknowledgment = !!below.length || !!conflict;
  function change(key: RecapCapKey, value: string) {
    dirty.current = true;
    setDraft(old => old && ({ ...old, [key]: value })); setAcknowledged(false); setConflict(null); setNotice("");
  }
  return <section id="generation-recap-budgets" tabIndex={-1} aria-labelledby="recap-budget-title" className="mt-4 border-t border-rule pt-4">
    <h4 id="recap-budget-title" className="font-display text-name font-bold">Weekly Analyst recap limits</h4>
    <p className="mt-1 text-prose text-dim">Limits for this league’s recap episodes and monthly recap spending. Combined limits include writing and video.</p>
    {loading && <p role="status" className="mt-3 text-prose">Loading recap limits…</p>}
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {notice && <p role="status" className="mt-3 text-prose text-pos-strong">{notice}</p>}
    {view && draft && <>
      <p className="mt-2 text-prose">Recap month: {monthDates(view.month_key)}</p>
      <p className="mt-1 text-prose">{view.episode_id ? `Episode: ${episodeLabel || 'Selected episode'}` : "Select an episode to see episode spending. Episode balances are unavailable until an episode is selected."}</p>
      {view.episode_id && <TechnicalDetails value={{episode_id:view.episode_id}} label="Technical episode identity" />}
      <p className="mt-1 text-prose text-dim">{view.enforcement_state.active ? "Budget enforcement is active." : "Budget enforcement is inactive."} {view.media_automation_enabled ? "Media automation is enabled." : "Media automation is not enabled. Saving limits does not enable it."}</p>
      {view.enforcement_state.reason === "historical_accounting_attention" && <p className="mt-1 text-prose text-warn-strong">Earlier accounting needs review. Outstanding obligations still count toward limits.</p>}
      <form className="mt-3" onSubmit={async event => {
        event.preventDefault();
        if (blocked || invalid || !parsed || !reason.trim() || (needsAcknowledgment && !acknowledged)) return;
        const requestId = sequence.current;
        setSending(true); setError(""); setNotice("");
        let saved = false;
        try {
          await run(async () => {
            await generationRequest(`/recap-budgets/${encodeURIComponent(seriesId)}`, {
              expected_revision: view.revision, caps: parsed as RecapCaps, reason: reason.trim(), acknowledge_overcommitted: acknowledged,
            }, "PUT");
            saved = true;
            const latest = await generationRequest<RecapBudgetView>(path);
            if (sequence.current === requestId) { dirty.current = false; setView(latest); setDraft(draftFor(latest)); setReason(""); setConflict(null); setAcknowledged(false); }
          }, "Recap limits saved and reloaded.", false);
          if (sequence.current === requestId) setNotice("Recap limits saved and reloaded.");
        } catch (err) {
          if (sequence.current !== requestId) return;
          const api = err as { status?: number; detail?: RecapBudgetOvercommit };
          if (api.status === 409 && api.detail?.code === "recap_budget_overcommitted" && api.detail.acknowledgment_required === true) {
            setConflict(api.detail); setAcknowledged(false);
          }
          setError(saved ? "Limits were saved, but reloading failed. Your draft is preserved. Reload limits before another change." : err instanceof Error ? err.message : "Recap limits were not saved. Try again or reload limits.");
        } finally { if (sequence.current === requestId) setSending(false); }
      }}>
        <fieldset disabled={blocked}>
          <div className="grid gap-3 sm:grid-cols-2">{keys.map(key => <label key={key} className="text-prose">{labels[key]}
            <input className={controlClass + " mt-1"} type="text" inputMode="decimal" aria-label={labels[key]} value={draft[key]} aria-invalid={parsed?.[key] === null} onChange={event => change(key, event.target.value)} />
            <span className="mt-1 block text-dim">Saved limit: {money(view.caps[key])}</span>
          </label>)}</div>
          {invalid && <p className="mt-2 text-prose text-neg-strong">Enter a positive dollar amount with at most two decimal places for every limit.</p>}
          {needsAcknowledgment && <div className="mt-3 text-prose text-warn-strong">
            <p>These limits are below committed obligations. Saving them holds additional requests; existing charges and unknown outcomes remain owed.</p>
            {below.map(key => <p key={key}>{labels[key]}: committed {money(view.balances[key]!.known_microusd + view.balances[key]!.reserved_microusd + view.balances[key]!.carry_forward_microusd)}.</p>)}
            {conflict?.affected.map((item, index) => <p key={index}>{item.scope}{item.episode_id ? ` · ${item.episode_id}` : ""}: committed {money(item.known_microusd + item.reserved_microusd + item.carry_forward_microusd)}.</p>)}
            <label className="mt-2 flex min-h-tap items-center gap-2"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} />I acknowledge these limits are below committed obligations.</label>
          </div>}
          <label className="mt-3 block text-prose">Reason for budget change<input className={controlClass + " mt-1"} required maxLength={1000} value={reason} onChange={event => { dirty.current = true; setReason(event.target.value); setAcknowledged(false); }} /></label>
          <Button type="submit" className="mt-3 px-4 py-2" disabled={blocked || invalid || !reason.trim() || (needsAcknowledgment && !acknowledged)}>{sending ? "Saving recap limits…" : "Save recap limits"}</Button>
        </fieldset>
      </form>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">{keys.map(key => view.balances[key] && <Spending key={key} balance={view.balances[key]!} label={`${key.startsWith("video") ? "Video" : "Combined recap, including video"} ${key.includes("episode") ? "episode" : "month"} spending`} />)}</div>
      <div className="mt-3 text-prose"><p>App-wide monthly AI cap: {view.app_limit.month_microusd === null ? "uncapped" : money(view.app_limit.month_microusd)}. This shared cap can hold recap work even when league limits have room.</p>
        <p className="mt-1 text-dim">App spending uses the UTC calendar month; recap limits use America/Denver month dates. Other leagues and AI features share the app cap.</p>
        <p>Known: {money(view.app_limit.balance.known_microusd)} · Reserved: {money(view.app_limit.balance.reserved_microusd)} · Carry-forward: {money(view.app_limit.balance.carry_forward_microusd)} · Remaining: {view.app_limit.month_microusd === null ? "uncapped" : view.app_limit.balance.remaining_microusd === null ? "unavailable" : money(view.app_limit.balance.remaining_microusd)}</p>
      </div>
    </>}
    <button type="button" className={secondary + " mt-3"} disabled={blocked} onClick={() => setReload(old => old + 1)}>Reload limits</button>
  </section>;
}
