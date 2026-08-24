"use client";

import { useState } from "react";
import type { SideBetCreateBody } from "@/lib/types";
import { Button } from "@/components/furniture/Button";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";

type OwnerOption = { user_id: string; name: string };

/* Furniture — a control is a rule you type on: no fill, no border box, no
 * radius. `border-b border-rule` that goes to `--ink` on focus, under a
 * whisper label. Selects get the same treatment.
 *
 * `min-h-tap` is the phone half of that: a rule you type on is still a thing
 * you have to hit with a thumb, and `py-1.5` on 13.5px type lands around 30px
 * — under the 44px floor for every one of the five fields at once. */
const inputCls =
  "w-full min-h-tap border-b border-rule bg-transparent py-1.5 text-prose text-ink placeholder:text-dim focus:border-ink focus:outline-none";

const labelCls = "block font-mono text-label uppercase tracking-[0.1em] text-dim";

export function RecordBetForm({
  owners,
  onSave,
  onCancel,
}: {
  owners: OwnerOption[];
  onSave: (body: SideBetCreateBody) => Promise<void>;
  onCancel: () => void;
}) {
  const [sideA, setSideA] = useState("");
  const [sideB, setSideB] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [season, setSeason] = useState(String(new Date().getFullYear()));
  const [madeAt, setMadeAt] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const amountCents = Math.round(parseFloat(amount || "0") * 100);
  const valid =
    sideA !== "" &&
    sideB !== "" &&
    sideA !== sideB &&
    amountCents > 0 &&
    description.trim() !== "" &&
    /^\d{4}$/.test(season) &&
    madeAt !== "";

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave({
        description: description.trim(),
        amount_cents: amountCents,
        season: Number(season),
        side_a_owner_id: sideA,
        side_b_owner_id: sideB,
        made_at: madeAt,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the bet.");
      setSaving(false);
    }
  }

  const ownerSelect = (
    id: string,
    label: string,
    value: string,
    set: (v: string) => void,
  ) => (
    <label className="block">
      <span className={labelCls} id={`${id}-label`}>
        {label}
      </span>
      <select
        aria-labelledby={`${id}-label`}
        aria-label={label}
        className={inputCls}
        value={value}
        onChange={(e) => set(e.target.value)}
      >
        <option value="">Pick an owner…</option>
        {owners.map((o) => (
          <option key={o.user_id} value={o.user_id}>
            {o.name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <Card>
      <CardHead title="Record a bet" />
      {/* One column on a phone. The pairing breaks at 701px, not Tailwind's
          `sm`, so the form splits at the same width every other ledger on this
          screen switches from cards to rules — a 660px viewport was getting
          two-up fields beside single-column card lists. */}
      <div className="grid grid-cols-1 gap-x-5 gap-y-4 min-[701px]:grid-cols-2">
        {ownerSelect("side-a", "Side A", sideA, setSideA)}
        {ownerSelect("side-b", "Side B", sideB, setSideB)}
        <label className="block">
          <span className={labelCls}>Amount ($)</span>
          <input
            aria-label="Amount ($)"
            className={inputCls}
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label className="block">
          <span className={labelCls}>Season</span>
          <input
            aria-label="Season"
            className={inputCls}
            type="number"
            value={season}
            onChange={(e) => setSeason(e.target.value)}
          />
        </label>
        <label className="block min-[701px]:col-span-2">
          <span className={labelCls}>The bet</span>
          <input
            aria-label="The bet"
            className={inputCls}
            type="text"
            placeholder="Tom finishes the regular season above Mike"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        <label className="block">
          <span className={labelCls}>Date made</span>
          <input
            aria-label="Date made"
            className={inputCls}
            type="date"
            value={madeAt}
            onChange={(e) => setMadeAt(e.target.value)}
          />
        </label>
      </div>
      {sideA !== "" && sideA === sideB && (
        <p className="mt-4 font-mono text-label uppercase tracking-[0.1em] text-neg-strong">
          A bet needs two different owners.
        </p>
      )}
      {error && (
        <p className="mt-4 font-mono text-label uppercase tracking-[0.1em] text-neg-strong">{error}</p>
      )}
      <div className="mt-5 flex items-center gap-5">
        <Button
          as="button"
          className="px-3 py-1.5 disabled:bg-rule disabled:text-dim"
          disabled={!valid || saving}
          onClick={save}
        >
          Save bet
        </Button>
        {/* Secondary action is a mono text link — one stamp fill per form. It
            still has to be tappable, so it claims the 44px box even though it
            draws no border. */}
        <button
          type="button"
          className="inline-flex min-h-tap items-center font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </Card>
  );
}
