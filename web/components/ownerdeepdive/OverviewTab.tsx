"use client";

import { Fragment } from "react";
import { FranchiseRating, OwnerDetailResp, PillarBreakdown } from "@/lib/types";
import { ContributionRow } from "@/components/RatingBars";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { Card, CardHead } from "./ui";
import { ratingDrivers, SIGNAL_LABELS } from "./util";

export type TabKey = "overview" | "record" | "trades" | "draft" | "outlook";

// v2: Results + Assets (src/sleeper_dynasty/engine/gm_rating.py
// ::V2_SIGNAL_WEIGHTS). `.filter((p) => p.data)` below already drops a key
// this owner's league doesn't score under (redraft has no Assets pillar), so
// this list only needs to name every key v2 can send, not gate on format.
const PILLARS: { key: string; label: string }[] = [
  { key: "results", label: "Results" },
  { key: "assets", label: "Assets" },
];

/** The rating's base before any pillar is applied — `gm_rating.py::BASE`. Each
 *  pillar's `contribution` is already `SCALE * weight * z` (confirmed in
 *  `engine/gm_rating.py`), so the total below sums the contributions AS
 *  RENDERED with no further weighting. */
const RATING_BASE = 1500;

// v2 tops out at two pillars (Results + Assets; redraft is Results alone) --
// no 3-pillar tree is reachable, so there is no "three" entry to keep in sync.
const PILLAR_COUNT_WORDS: Record<number, string> = { 1: "one", 2: "two" };

/** Closes the "Why this grade" ledger — Base 1,500 + every rendered pillar's
 *  contribution, which must equal the headline rating. `gm_rating.py` rounds
 *  each pillar's contribution independently, so the sum can land a point or
 *  two off the headline; rather than paper over that, this row sums exactly
 *  what is on screen and, when it disagrees with the headline, says so instead
 *  of silently picking one number. */
function TotalRow({
  fr,
  pillars,
}: {
  fr: FranchiseRating;
  pillars: { key: string; label: string; data: PillarBreakdown | undefined }[];
}) {
  const sum = pillars.reduce((acc, p) => acc + (p.data?.contribution ?? 0), 0);
  const computed = RATING_BASE + sum;
  const gap = fr.rating - computed;
  const countWord = PILLAR_COUNT_WORDS[pillars.length] ?? String(pillars.length);
  return (
    /* TWO columns, not the ContributionRow's three. A total has no bar, so the
     * label spans the label AND bar tracks — copying the 168px label track put
     * a sentence plus a rounding note into 168px with `truncate`, and it
     * shipped as "Base 1,500 + three pill…" with the note cut mid-number. A
     * total row that cannot show what it totals fails the rule it exists to
     * satisfy. No truncate: the note wraps instead. */
    <Row variant="total" cols="minmax(0,1fr) auto" className="py-2">
      <span className="min-w-0">
        <span className="font-display text-name font-bold tracking-[-0.024em] text-ink">
          Base 1,500 + {countWord} pillar{pillars.length === 1 ? "" : "s"}
        </span>
        {gap !== 0 && (
          <span className="mt-0.5 block font-mono text-label font-normal normal-case tracking-normal text-dim">
            rating shown above rounds to {fr.rating.toLocaleString()}
          </span>
        )}
      </span>
      <span className="whitespace-nowrap text-right font-mono text-figure font-semibold tabular text-ink">
        {computed.toLocaleString()}
      </span>
    </Row>
  );
}

/* ---------------------------------------------------------------------------
 * "Why this grade" (`.design/templates/franchise/Franchise.dc.html`). One
 * continuous ruled ledger: each pillar's ContributionRow, then its
 * `pillar_highlights` line as a second rule in italic, then its signal rows
 * indented 14px in mono --dim, closed by a `Row variant="total"` reading
 * "Base 1,500 + N pillars" — see `TotalRow` above. Figures Reconcile is
 * shown, not asserted: the total sums the SAME `contribution` values the
 * `ContributionRow`s above it render, on screen, rather than claiming by
 * comment that they add up to the headline `fr.rating`.
 * ------------------------------------------------------------------------ */

function RatingDrivers({ fr }: { fr: FranchiseRating }) {
  const pillars = PILLARS.map((p) => ({ ...p, data: fr.pillars[p.key] })).filter((p) => p.data);

  // Shared bar scale across every pillar + signal contribution — the max,
  // not the largest signal (DESIGN.md § "Ink Bars").
  const mags = [1];
  for (const p of pillars) {
    mags.push(Math.abs(p.data!.contribution));
    for (const s of Object.values(p.data!.signals)) {
      mags.push(Math.abs(s.contribution));
    }
  }
  const scale = Math.max(...mags);
  const { driver, drag } = ratingDrivers(fr);

  return (
    <Card>
      <div className="flex items-baseline justify-between border-b border-rule pb-1.5 mb-2">
        <h2 className="font-display text-section font-bold tracking-[-0.024em]">Why this grade</h2>
        <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
          {/* `of` is the RATED population (franchise_redesign.rated_owners),
              not the full league roster — an owner with no completed season
              is excluded from ranking, not merely hidden. Saying "rated"
              keeps this number from silently disagreeing with the standings
              table's franchise count, which counts everyone. */}
          {fr.rating.toLocaleString()} · #{fr.rank} of {fr.of} rated
        </span>
      </div>
      {driver && (
        <p className="text-figure leading-snug text-body mb-2.5">
          <span className="font-semibold text-ink">{driver}</span> carries the grade
          {drag ? (
            <> — <span className="font-semibold text-ink">{drag}</span> is the biggest drag.</>
          ) : "."}
        </p>
      )}
      <Panel>
        {pillars.map((p) => {
          const sigs = Object.entries(p.data!.signals)
            .map(([k, s]) => ({ k, label: SIGNAL_LABELS[k] ?? k, points: s.contribution }))
            .filter((s) => Math.abs(s.points) >= 1)
            .sort((a, b) => Math.abs(b.points) - Math.abs(a.points));
          const highlight = fr.pillar_highlights?.[p.key];
          return (
            <Fragment key={p.key}>
              <ContributionRow label={p.label} weight={p.data!.weight} points={p.data!.contribution} scale={scale} />
              {highlight && (
                <Row className="grid-cols-[14px_minmax(0,1fr)] gap-3 items-center">
                  <span />
                  <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-sans text-figure italic text-dim">
                    {highlight}
                  </span>
                </Row>
              )}
              {sigs.map((s) => (
                <ContributionRow key={s.k} label={s.label} points={s.points} scale={scale} signal />
              ))}
            </Fragment>
          );
        })}
        <TotalRow fr={fr} pillars={pillars} />
      </Panel>
      <p className="mt-2 text-figure leading-snug text-dim">
        Every signal is scored against your league and centered on a C (average) GM. The bar shows
        direction and size; the figure carries the sign.
      </p>
    </Card>
  );
}

export function OverviewTab({ detail }: { detail: OwnerDetailResp }) {
  const fr = detail.franchise_rating;
  if (!fr) {
    return (
      <Card>
        <CardHead title="Why this grade" />
        <p className="text-figure text-dim">Rating breakdown isn&apos;t available yet.</p>
      </Card>
    );
  }
  return <RatingDrivers fr={fr} />;
}
