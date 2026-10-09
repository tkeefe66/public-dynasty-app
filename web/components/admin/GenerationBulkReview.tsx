import { useEffect, useState } from "react";
import { generationRequest } from "@/lib/api";
import { GenerationPage, GenerationRecord, GenerationSeries } from "@/lib/generation";
import { Button } from "@/components/furniture/Button";
import { GenerationJob } from "./GenerationJob";
import { ActionProps, failedFreeRefresh, problemExplanation, secondary, summaryClass } from "./GenerationShared";

interface BatchPreview {
  id: string; digest: string; action: "resume" | "cancel"; remaining_calls: number;
  items: { id: string }[]; skipped: { id: string; reason: string }[];
}

export function GenerationBulkReview({ rows, leagues, busy, run, version, hasMore = false }: ActionProps & {
  rows: GenerationRecord[]; leagues: GenerationSeries[]; version: number; hasMore?: boolean;
}) {
  const [batchOpen, setBatchOpen] = useState(false);
  const [allRows, setAllRows] = useState<GenerationRecord[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [preview, setPreview] = useState<BatchPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setAllRows(null); setSelected([]); setPreview(null); setBatchOpen(false); }, [version]);
  const displayed = allRows || rows;
  const blocked = busy || loading;
  async function selectAll() {
    setLoading(true); setError(""); setPreview(null);
    try {
      const groups = await Promise.all(["needs_attention", "held"].map(async state => {
        const result: GenerationRecord[] = [];
        let offset: number | null = 0;
        while (offset !== null) {
          const page: GenerationPage<GenerationRecord> = await generationRequest(`/records/jobs?limit=100&state=${state}&offset=${offset}`);
          result.push(...page.records);
          if (result.length > 1000) throw new Error("More than 1,000 review jobs. Select a smaller batch.");
          offset = page.next_offset;
        }
        return result;
      }));
      const unique = [...new Map(groups.flat().map(row => [row.id!, row])).values()];
      if (unique.length > 1000) throw new Error("More than 1,000 review jobs. Select a smaller batch.");
      setAllRows(unique); setSelected(unique.filter(row => !failedFreeRefresh(row)).map(row => row.id!));
    } catch (err) { setError(err instanceof Error ? err.message : "Work could not be selected. Reload and try again."); }
    finally { setLoading(false); }
  }
  async function propose(action: "resume" | "cancel") {
    setLoading(true); setError(""); setPreview(null);
    try { setPreview(await generationRequest<BatchPreview>("/jobs/batch/preview", {
      job_ids: selected, action, reason: `${action === "resume" ? "Resume" : "Cancel"} selected stopped and paused work`,
    })); }
    catch (err) { setError(err instanceof Error ? err.message : "Batch preview failed. Reload and try again."); }
    finally { setLoading(false); }
  }
  const skippedGroups = preview?.skipped.reduce<Record<string, number>>((groups, item) => {
    groups[item.reason] = (groups[item.reason] || 0) + 1; return groups;
  }, {}) || {};
  return <div className="mt-3">
    {(displayed.filter(row => !failedFreeRefresh(row)).length > 1 || hasMore) && <details open={batchOpen} onToggle={e => setBatchOpen(e.currentTarget.open)}>
      <summary className={summaryClass}>Review several jobs</summary>
    <div className="flex flex-wrap items-center gap-3">
      <button className={secondary} disabled={blocked} onClick={selectAll}>Select jobs across pages</button>
      <button className={secondary} disabled={blocked || !selected.length} onClick={() => { setSelected([]); setPreview(null); }}>Clear selection</button>
      <span className="text-prose" role="status">{selected.length} selected</span>
      <button className={secondary} disabled={blocked || !selected.length} onClick={() => propose("resume")}>Preview resume selected</button>
      <button className={secondary} disabled={blocked || !selected.length} onClick={() => propose("cancel")}>Preview cancel selected</button>
    </div>
    {error && <p role="alert" className="mt-3 text-prose text-neg-strong">{error}</p>}
    {preview && <div className="mt-3 border border-rule rounded-panel p-4 text-prose">
      <h4 className="font-semibold">{preview.items.length} jobs can {preview.action === "resume" ? "resume" : "be cancelled"}</h4>
      <p className="mt-1 text-dim">{preview.action === "resume" ? `Up to ${preview.remaining_calls} remaining AI requests. Original job allowances still apply.` : "Stops future work and preserves saved records. Requests already sent may still incur charges."}</p>
      {Object.entries(skippedGroups).map(([reason, count]) => <p key={reason} className="mt-2 text-warn-strong">{count} skipped: {problemExplanation({ state: "held", reason })}</p>)}
      <Button className="mt-3 px-4 py-2" disabled={blocked || !preview.items.length} onClick={async () => {
        setError("");
        try { await run(() => generationRequest("/jobs/batch/apply", { preview_id: preview.id, digest: preview.digest,
          reason: `${preview.action === "resume" ? "Resume" : "Cancel"} selected stopped and paused work`,
        }), preview.action === "resume" ? "Selected work resumed. Blocked items were left unchanged." : "Selected work cancelled. Saved records preserved."); }
        catch (err) { setError(err instanceof Error ? err.message : "Batch action failed. Preview again."); }
      }}>Confirm {preview.action} {preview.items.length} jobs</Button>
    </div>}
    </details>}
    <ul className="mt-3 divide-y divide-rule">{displayed.map(row => <GenerationJob key={`${row.id}:${row.state}:${row.generation}`} row={row} leagues={leagues} busy={blocked} run={run} review
      selected={selected.includes(row.id!)} onSelect={batchOpen && !failedFreeRefresh(row) ? checked => { setPreview(null); setSelected(old => checked ? [...old, row.id!] : old.filter(id => id !== row.id)); } : undefined} />)}</ul>
  </div>;
}
