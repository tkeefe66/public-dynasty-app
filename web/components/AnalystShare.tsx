"use client";

import { useState } from "react";

export function AnalystShare({ leagueId, season, week }: { leagueId: string; season: number; week: number }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const endpoint = `/api/league/${encodeURIComponent(leagueId)}/analyst/${season}/${week}/share`;
  const button = "inline-flex min-h-tap items-center justify-center rounded-pill border border-rule px-4 py-2 text-sm font-semibold text-ink disabled:opacity-50";

  async function manage(method: "POST" | "DELETE") {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(endpoint, { method, cache: "no-store" });
      if (!response.ok) throw new Error(response.status === 403 ? "Only league members can manage sharing." : "Could not update sharing. Please try again.");
      const data = await response.json();
      setUrl(data.token ? `${window.location.origin}/share/analyst/${data.token}` : "");
      if (method === "DELETE") setMessage("Share link disabled. Previously sent links no longer open this recap.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not update sharing."); }
    finally { setBusy(false); }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(url); setMessage("Link copied. Anyone with it can read this recap."); }
    catch { setMessage("Select and copy the link below."); }
  }

  async function send() {
    if (!navigator.share) { await copy(); return; }
    try { await navigator.share({ title: `The Analyst · Week ${week}`, text: `Read the Week ${week} recap`, url }); }
    catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setMessage("Could not open sharing. Use Copy link instead.");
    }
  }

  return <div className="mt-4 space-y-3">
    {!url ? <button type="button" className={button} disabled={busy} onClick={() => manage("POST")}>{busy ? "Preparing link…" : "Share recap"}</button> : <>
      <p className="text-sm text-dim">Anyone with this link can read this edition, including any bet amounts in the article. No sign-in needed.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={button} onClick={send}>Send link</button>
        <button type="button" className={button} onClick={copy}>Copy link</button>
        <button type="button" className={button} disabled={busy} onClick={() => manage("DELETE")}>Disable link</button>
      </div>
      <input aria-label="Recap share link" readOnly value={url} onFocus={(event) => event.target.select()} className="w-full min-w-0 rounded-lg border border-rule bg-surface px-3 py-3 text-sm text-body" />
    </>}
    {message && <p role="status" className="text-sm text-body">{message}</p>}
  </div>;
}
