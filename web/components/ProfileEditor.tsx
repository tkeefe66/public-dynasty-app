"use client";

import { useState } from "react";
import { OwnerProfile, ProfilesMap } from "@/lib/types";
import { putProfile } from "@/lib/api";
import { Button } from "./furniture/Button";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";

interface Props {
  leagueId: string;
  userId: string;
  /** API display name, shown in the header and used as the input placeholder. */
  displayName: string;
  profile?: OwnerProfile;
  /** Every *other* owner, for the rivals picker. */
  others: { user_id: string; name: string }[];
  onSaved: (profiles: ProfilesMap) => void;
  onCancel: () => void;
}

/* Agate — a control is a rule you type on (DESIGN.md § Controls): no fill, no
 * box, no radius; `--ink` on focus, with the square focus ring for keyboard
 * users. The label above it is a whisper label. */
const INPUT =
  "w-full border-b border-rule bg-transparent py-1 text-prose text-ink " +
  "placeholder:text-dim focus:border-ink focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-[color:var(--ringfocus)]";
const LABEL = "block font-mono text-label uppercase tracking-[0.1em] text-dim";

/** Trim, and treat blanks as "unset" so a half-filled profile stays clean. */
function clean(s: string): string | undefined {
  const t = s.trim();
  return t ? t : undefined;
}

export function ProfileEditor({
  leagueId, userId, displayName, profile, others, onSaved, onCancel,
}: Props) {
  const [winNameV, setWinName] = useState(profile?.win_name ?? "");
  const [lossNameV, setLossName] = useState(profile?.loss_name ?? "");
  const [archetype, setArchetype] = useState(profile?.archetype ?? "");
  const [roast, setRoast] = useState(profile?.roast ?? "");
  const [rivals, setRivals] = useState<Set<string>>(
    new Set(profile?.rivals ?? []),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleRival(uid: string) {
    setRivals((prev) => {
      const next = new Set(prev);
      next.has(uid) ? next.delete(uid) : next.add(uid);
      return next;
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body: OwnerProfile = {
      win_name: clean(winNameV),
      loss_name: clean(lossNameV),
      archetype: clean(archetype),
      roast: clean(roast),
      rivals: [...rivals],
    };
    try {
      const updated = await putProfile(leagueId, userId, body);
      onSaved(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save profile.");
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHead title={`Edit ${displayName}`} />

      <div className="mb-4 grid grid-cols-2 gap-x-5">
        <div>
          <label className={LABEL} htmlFor={`win-${userId}`}>Win name</label>
          <input
            id={`win-${userId}`} className={INPUT} value={winNameV}
            placeholder={displayName}
            onChange={(e) => setWinName(e.target.value)}
          />
        </div>
        <div>
          <label className={LABEL} htmlFor={`loss-${userId}`}>Loss name</label>
          <input
            id={`loss-${userId}`} className={INPUT} value={lossNameV}
            placeholder={displayName}
            onChange={(e) => setLossName(e.target.value)}
          />
        </div>
      </div>

      <div className="mb-4">
        <label className={LABEL} htmlFor={`arch-${userId}`}>Archetype</label>
        <input
          id={`arch-${userId}`} className={INPUT} value={archetype}
          placeholder="The Trade Machine"
          onChange={(e) => setArchetype(e.target.value)}
        />
      </div>

      <div className="mb-4">
        <label className={LABEL} htmlFor={`roast-${userId}`}>Roast</label>
        <input
          id={`roast-${userId}`} className={INPUT} value={roast}
          placeholder="drafted a retired tight end"
          onChange={(e) => setRoast(e.target.value)}
        />
      </div>

      <div className="mb-4">
        <span className={LABEL}>Rivals</span>
        {others.length === 0 ? (
          <div className="font-mono text-label uppercase tracking-[0.1em] text-dim">
            No other franchises yet
          </div>
        ) : (
          /* Selection is a 2px ink underline, not a filled pill — the picked
             ones read as a run of marked names. */
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {others.map((o) => {
              const on = rivals.has(o.user_id);
              return (
                <button
                  key={o.user_id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleRival(o.user_id)}
                  className={
                    "pb-0.5 font-mono text-label uppercase tracking-[0.08em] transition-colors " +
                    "focus-visible:outline-none focus-visible:ring-2 " +
                    "focus-visible:ring-[color:var(--ringfocus)] " +
                    (on
                      ? "border-b-2 border-ink font-bold text-ink"
                      : "border-b-2 border-transparent text-dim hover:text-ink")
                  }
                >
                  {o.name}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {error && (
        <div className="mb-3 font-mono text-label uppercase tracking-[0.1em] text-neg-strong" role="alert">
          {error}
        </div>
      )}

      <div className="flex items-center gap-5">
        <Button
          as="button"
          onClick={save}
          disabled={saving}
          className={
            "px-3 py-1.5 disabled:bg-rule disabled:text-dim " +
            "focus-visible:outline-none focus-visible:ring-2 " +
            "focus-visible:ring-[color:var(--ringfocus)]"
          }
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className={
            "font-mono text-label uppercase tracking-[0.1em] text-dim hover:text-ink " +
            "disabled:text-rule focus-visible:outline-none focus-visible:ring-2 " +
            "focus-visible:ring-[color:var(--ringfocus)]"
          }
        >
          Cancel
        </button>
      </div>
    </Card>
  );
}
