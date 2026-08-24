"use client";

import { useState } from "react";
import { OwnerNameEntry } from "@/lib/types";
import { putOwnerNames } from "@/lib/api";
import { Button } from "./furniture/Button";
import { CardList, EntryCard } from "./furniture/EntryCard";
import { SectionHead } from "./furniture/SectionHead";

interface Props {
  leagueId: string;
  initial: OwnerNameEntry[];
}

/**
 * One card per owner — the Furniture answer to a narrow form.
 *
 * This was a two-column `label | input` grid with the handle pinned to a `w-32`
 * column. At 390px that left the input roughly 150px wide, so the very field
 * the page exists to edit was the smallest thing on it. The fix is the same one
 * every ledger on a phone gets (`furniture/EntryCard`): the entry becomes a
 * CARD, its edge is the boundary, and nothing inside it competes for width.
 *
 * The Sleeper handle is the card's label — mono, uppercase, dim, and a real
 * `<label htmlFor>` rather than an `aria-label`, so tapping the handle focuses
 * the field. The editable display name is a full-width 44px input beneath it,
 * in the one sanctioned input treatment (`.design/components/controls/Field.jsx`:
 * `--surface` ground, `--rule-strong` edge, `--radius-sm`, 44px floor, no
 * underlined variant).
 *
 * One primary button below the list — the list is one form, not N forms, and
 * `putOwnerNames` still submits the whole map exactly as before.
 */
export function OwnerNamesForm({ leagueId, initial }: Props) {
  const [names, setNames] = useState<Record<string, string>>(
    Object.fromEntries(initial.map((o) => [o.user_id, o.display_name ?? ""])),
  );
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );

  async function save() {
    setStatus("saving");
    try {
      await putOwnerNames(leagueId, names);
      setStatus("saved");
      setTimeout(() => setStatus("idle"), 2000);
    } catch {
      setStatus("error");
    }
  }

  return (
    <section>
      {/* No `meta` count here: the page kicker above already reads
          "<league> · N owners", and on a phone the two sat ~30px apart saying
          the same thing — byte-identical when the league name is unavailable. */}
      <SectionHead id="owner-names-head" title="Owner display names" />

      {/* The group is NAMED by that heading. Each field's own label is just the
          Sleeper handle, so without this a screen-reader user tabbing into the
          eighth field hears a bare username and no statement of what the field
          does — the accessible name this replaced was "Display name for X". */}
      <CardList role="group" aria-labelledby="owner-names-head">
        {initial.map((o) => {
          /* A plain, stable id rather than `useId()`: user_id is already unique
             within the league, and React's generated ids contain colons, which
             are legal in the attribute but awkward in every selector that ever
             has to find this field again. */
          const id = `owner-name-${o.user_id}`;
          return (
            <EntryCard key={o.user_id}>
              <label
                htmlFor={id}
                className="block font-mono text-label uppercase tracking-[0.11em] text-dim"
              >
                {o.sleeper_name}
              </label>
              <input
                id={id}
                type="text"
                /* The Field treatment: full width, 44px floor, one radius, a
                   --rule-strong edge. The focus ring is the global
                   `:focus-visible` cobalt ring from globals.css — never
                   `outline-none` here, which is what the old underlined input
                   did. */
                className="mt-2 block w-full min-h-tap rounded-sm border border-rule-strong bg-surface px-3 py-2.5 font-sans text-prose text-ink placeholder:text-dim"
                placeholder={o.sleeper_name}
                value={names[o.user_id] ?? ""}
                onChange={(e) =>
                  setNames((prev) => ({ ...prev, [o.user_id]: e.target.value }))
                }
              />
            </EntryCard>
          );
        })}
      </CardList>

      {/* Full width on a phone so the tap target spans the column; auto width
          from 701px up, where a button the width of the page reads as a banner. */}
      <Button
        as="button"
        onClick={save}
        disabled={status === "saving"}
        className="mt-4 w-full justify-center px-4 min-[701px]:w-auto"
      >
        {status === "saving"
          ? "Saving…"
          : status === "saved"
            ? "Saved"
            : "Save names"}
      </Button>

      <p aria-live="polite" className="sr-only">
        {status === "saved" ? "Names saved." : ""}
      </p>
      {status === "error" && (
        <p
          role="alert"
          /* -strong, not the base pair: this line sits on `--bg`, the page
             ground, where the base tone drops below AA. */
          className="mt-2 font-mono text-label uppercase tracking-[0.11em] text-neg-strong"
        >
          Save failed. Try again.
        </p>
      )}
    </section>
  );
}
