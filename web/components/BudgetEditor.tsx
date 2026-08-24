"use client";

import { useState } from "react";
import { setBudget, type BudgetStatus } from "@/lib/api";
import { Button } from "./furniture/Button";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";

function usd(n: number) {
  return `$${n.toFixed(2)}`;
}

export function BudgetEditor({ initial }: { initial: BudgetStatus }) {
  const [status, setStatus] = useState<BudgetStatus>(initial);
  const [value, setValue] = useState(String(initial.monthly_budget_usd));
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const n = parseFloat(value);
    if (Number.isNaN(n) || n < 0) {
      setMsg("Enter a non-negative number (0 = no cap).");
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const next = await setBudget(n);
      setStatus(next);
      setValue(String(next.monthly_budget_usd));
      setMsg("Saved.");
      setTimeout(() => setMsg(null), 2500);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  const over =
    status.budget_remaining_usd !== null && status.budget_remaining_usd <= 0;

  return (
    <Card>
      <CardHead title="Monthly LLM budget" />
      <div className="mb-1 flex items-baseline gap-2">
        <span className="font-mono text-2xl font-semibold tabular tracking-[-0.02em]">
          {usd(status.month_to_date_usd)}
        </span>
        <span className="text-prose text-body">
          spent this month
          {status.monthly_budget_usd > 0
            ? ` / ${usd(status.monthly_budget_usd)} budget`
            : " · no cap set"}
        </span>
      </div>
      {status.budget_remaining_usd !== null && (
        <p className={`mb-4 text-prose ${over ? "text-neg-strong" : "text-dim"}`}>
          {over
            ? "Budget reached — LLM generation is paused (graded data still updates)."
            : `${usd(status.budget_remaining_usd)} remaining this month`}
        </p>
      )}

      <form onSubmit={save} className="flex items-center gap-2">
        <span className="font-mono text-figure text-dim">$</span>
        <input
          type="number"
          min="0"
          step="0.01"
          aria-label="Monthly budget in dollars"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-32 border-b border-rule bg-transparent py-1 font-mono text-figure tabular text-ink focus:border-ink focus:outline-none"
        />
        <span className="font-mono text-label uppercase tracking-[0.1em] text-dim">/ month</span>
        <Button
          as="button"
          type="submit"
          disabled={saving}
          className="ml-2 px-3 py-1.5 disabled:bg-rule disabled:text-dim"
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        {msg && (
          <span className="ml-2 font-mono text-label uppercase tracking-[0.1em] text-dim">
            {msg}
          </span>
        )}
      </form>
      <p className="mt-2 max-w-[68ch] text-prose leading-relaxed text-body">
        Set 0 to disable the cap. When spend reaches the budget, refreshes still
        run but skip AI prose.
      </p>
    </Card>
  );
}
