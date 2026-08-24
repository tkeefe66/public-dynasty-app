"use client";

import { useId, useState, type ReactNode } from "react";
import { EntryCard, MetaLine, Meta } from "./furniture/EntryCard";
import { Mark } from "./furniture/Mark";

/**
 * One received asset, on a phone: a headline figure and a tap.
 *
 * WHY THIS REPLACED A STACK OF ROWS. The mobile branch used to render a name
 * row plus ONE ROW PER METRIC for every asset, and repeat the whole block for
 * each asset a flip became. A single flipped asset cost 19 rules (~490px), and
 * the real trade page measured **2,340px** at 390px — three screens to read one
 * side of one trade. That was followup C9.
 *
 * This is `.design/templates/mobile/Mobile.dc.html`'s own shape: an entry on a
 * phone is an `EntryCard` — name, ONE headline figure with its label under it,
 * then a wrapping `MetaLine` of the rest. The dashboard cards already read that
 * way; the trade table was the last screen still stacking rows.
 *
 * COLLAPSED BY DEFAULT, and deliberately not "first one open". Assets are
 * sorted by value, so pre-opening the first card would always expand the
 * biggest one — "the most valuable asset gets its stats shown" is a claim the
 * design would be making by accident. A chevron on a 44px target needs no
 * demonstration.
 *
 * The four hidden metrics stay IN THE DOM, hidden with CSS rather than
 * unmounted: find-in-page still reaches them, and the collapse is a display
 * concern, not a data one.
 */
export interface AssetCardFact {
  label: string;
  value: string;
  /** `dim` is a real tone — a zero or absent figure must not read as a result. */
  tone?: "pos" | "neg" | "dim";
}

export function TradeAssetCard({
  name,
  tag,
  headline,
  headlineLabel,
  headlineTone,
  facts,
  journey,
  nested = false,
}: {
  /** The asset's own label. Kept SHORT — provenance goes in `journey`. */
  name: ReactNode;
  /** "ON ROSTER" / "DROPPED WK 6" / "FLIPPED →" etc. */
  tag?: ReactNode;
  /** The one figure that stays visible collapsed. */
  headline: string;
  /** What that figure IS. Not hardcoded: the trade page leads with Started
   *  Points once a trade has produced, and with Trade Value before it has. */
  headlineLabel: string;
  headlineTone?: "pos" | "neg" | "dim";
  /**
   * The other four metrics. EMPTY means the asset has no figures of its own —
   * a flipped player, whose value moved to what it became. Such a card gets NO
   * chevron and no body: there is nothing to open, and a chevron would promise
   * detail that does not exist. Its `journey` is the whole content and stays
   * visible.
   */
  facts: AssetCardFact[];
  /** "traded to X · date → became", or "from 2026 1st pick". */
  journey?: ReactNode;
  /** A `became` asset — carries the stamp edge that says it came from above. */
  nested?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const expandable = facts.length > 0;

  const head = (
    <div className="flex min-w-0 items-center gap-2.5">
      <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[-0.01em] text-ink">
        {name}
        {tag}
      </span>
      <span className="grid shrink-0 justify-items-end text-right">
        <b className={`font-mono text-name font-semibold tabular leading-none ${toneClass(headlineTone)}`}>
          {headline}
        </b>
        <span className="mt-0.5 font-mono text-label uppercase tracking-[0.12em] text-dim">
          {headlineLabel}
        </span>
      </span>
      {/* The SAME pair `SectionHeader` uses for its collapse, not a rotating
          chevron of its own. Two disclosure idioms on one screen is two
          languages for one idea, and `open`/`closed` are what this app has
          already taught. Near data a mark stays `--dim`. */}
      {expandable && (
        <Mark name={open ? "open" : "closed"} size={13} className="shrink-0 text-dim" />
      )}
    </div>
  );

  return (
    <EntryCard
      className={`p-0 ${nested ? "ml-4 border-l-[3px] border-l-stamp" : ""}`}
    >
      {expandable ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="tap flex w-full min-h-tap items-center px-3.5 py-3 text-left"
        >
          {head}
        </button>
      ) : (
        <div className="px-3.5 py-3">{head}</div>
      )}

      {expandable ? (
        <div id={bodyId} hidden={!open} className="px-3.5 pb-3">
          <MetaLine>
            {facts.map((f) => (
              <Meta key={f.label} label={f.label} tone={f.tone}>
                {f.value}
              </Meta>
            ))}
          </MetaLine>
          {journey && <div className="mt-2">{journey}</div>}
        </div>
      ) : (
        journey && <div className="px-3.5 pb-3">{journey}</div>
      )}
    </EntryCard>
  );
}

function toneClass(tone?: "pos" | "neg" | "dim"): string {
  return tone === "pos"
    ? "text-pos-strong"
    : tone === "neg"
      ? "text-neg-strong"
      : tone === "dim"
        ? "text-dim"
        : "text-ink";
}
