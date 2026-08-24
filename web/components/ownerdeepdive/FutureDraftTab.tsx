"use client";

import { DraftSkillView, DraftNeedView, OutlookView } from "@/lib/types";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { CardList, EntryCard, MetaLine, Meta } from "../furniture/EntryCard";
import { Card, CardHead } from "./ui";
import { ordinal } from "./util";

const URGENCY_TONE: Record<string, string> = {
  immediate: "text-neg-strong",
  developing: "text-dim",
};

/* ---------------------------------------------------------------------------
 * §3 Draft needs and §5 Draft — two sections out of one file, because they are
 * two readings of the same draft_capital / draft_needs pair and change
 * together. §4 (the rooms chart) sits between them on the page.
 * ------------------------------------------------------------------------ */

/** Depth as filled/hollow pips — ONLY on the depth-shortfall branch.
 *
 *  `assess_draft_needs` has four branches and only `kind === "depth"` is a
 *  shortfall against `ideal`. The starter-quality branch fires at any count,
 *  and the aging branch is an `elif` reached only when held >= ideal — pips
 *  there would draw a FULL room beside a live need, which reads as a
 *  contradiction. Those rows show their reason with no depth graphic. */
function DepthPips({ held, ideal }: { held: number; ideal: number }) {
  return (
    <span className="flex items-center gap-[3px]" aria-label={`${held} of ${ideal}`}>
      {Array.from({ length: ideal }, (_, i) => (
        <span
          key={i}
          data-pip={i < held ? "filled" : "hollow"}
          className={`h-[7px] w-[7px] rounded-pill ${
            i < held ? "bg-ink" : "border border-rule-strong"
          }`}
        />
      ))}
    </span>
  );
}

function showsPips(n: DraftNeedView): boolean {
  return n.kind === "depth" && (n.ideal ?? 0) > 0;
}

export function DraftNeedsSection({ outlook }: { outlook: OutlookView }) {
  const needs = outlook.draft_needs;
  return (
    <Card>
      <CardHead title="Draft needs" />
      {needs.length === 0 ? (
        <p className="text-figure leading-snug text-dim">
          No pressing needs. A hole shows up here as soon as a room thins out.
        </p>
      ) : (
        <>
          {/* Desktop — one rule per need, four columns. The narrow variant
              that used to live on THESE SAME classes hid three of four head
              columns but only one body cell (Depth), leaving Urgency and
              Why — the row's whole payload — to wrap onto Grid's implicit
              second row under the 34px Room column and get crushed. Below
              701px this whole block is `hidden`, so the grid template here
              is desktop-only and carries no narrow variant to get wrong. */}
          <div className="hidden min-[701px]:block" data-testid="draft-needs-desktop">
            <Panel>
              <Row variant="head" className="grid-cols-[34px_58px_78px_minmax(0,1fr)] gap-2">
                <div>Room</div>
                <div>Depth</div>
                <div>Urgency</div>
                <div>Why</div>
              </Row>
              {needs.map((n, i) => (
                <Row
                  key={`${n.position}-${i}`}
                  className="grid-cols-[34px_58px_78px_minmax(0,1fr)] items-center gap-2"
                >
                  {/* Mono, not the display face: Bricolage's Q carries a long
                      baseline tail, so QB reads as underlined at label sizes. */}
                  <span className="font-mono text-figure font-semibold uppercase tracking-[0.06em] text-ink">
                    {n.position}
                  </span>
                  <span className="flex items-center">
                    {showsPips(n) ? (
                      <DepthPips held={n.held ?? 0} ideal={n.ideal ?? 0} />
                    ) : (
                      <span className="font-mono text-label text-dim">—</span>
                    )}
                  </span>
                  <span
                    className={`font-mono text-label uppercase tracking-[0.11em] ${
                      URGENCY_TONE[n.urgency] ?? "text-dim"
                    }`}
                  >
                    {n.urgency}
                  </span>
                  <span className="min-w-0 truncate text-figure text-body" title={n.reason}>
                    {n.reason}
                  </span>
                </Row>
              ))}
            </Panel>
          </div>

          {/* Below 701px — one EntryCard per need (Furniture rule 5: an
              entry becomes a CARD, never a squeezed row). Every field
              survives: position + urgency on the headline, depth as a
              held/ideal FACT rather than pip dots (the dots stay desktop-only
              on purpose — the pip-gate tests count every `[data-pip]` in the
              render, and a second dot set here would double that count).

              The reason is deliberately OUTSIDE `MetaLine`/`Meta`: `Meta`
              applies `whitespace-nowrap`, which is correct for a short fact
              like `Depth 2 / 4` but wrong for a full sentence — a long reason
              rendered as a `Meta` measured 1005px wide at a 390px viewport (a
              live-browser QA pass caught this; jsdom lays out no text and
              could not). `Meta` itself is a shared primitive with many other
              callers where `nowrap` is exactly right, so the fix belongs
              here, not there: the reason is a normal wrapping paragraph, full
              text always reachable, never truncated behind a title-only
              tooltip a touch reader can't invoke. */}
          <CardList className="min-[701px]:hidden" data-testid="draft-needs-mobile">
            {needs.map((n, i) => (
              <EntryCard key={`${n.position}-${i}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-figure font-semibold uppercase tracking-[0.06em] text-ink">
                    {n.position}
                  </span>
                  <span
                    className={`font-mono text-label uppercase tracking-[0.11em] ${
                      URGENCY_TONE[n.urgency] ?? "text-dim"
                    }`}
                  >
                    {n.urgency}
                  </span>
                </div>
                <MetaLine className="mt-2.5">
                  <Meta label="Depth">
                    {showsPips(n) ? `${n.held ?? 0} / ${n.ideal ?? 0}` : "—"}
                  </Meta>
                </MetaLine>
                <p className="mt-2 text-figure leading-snug text-body">{n.reason}</p>
              </EntryCard>
            ))}
          </CardList>
        </>
      )}
    </Card>
  );
}

function roundsForSeason(
  byRound: Record<string, number>, season: string,
): { round: number; count: number }[] {
  const out: { round: number; count: number }[] = [];
  for (const [k, c] of Object.entries(byRound)) {
    const [s, r] = k.split("-");
    if (s === season) out.push({ round: Number(r), count: c });
  }
  return out.sort((a, b) => a.round - b.round);
}

export function DraftSection({
  outlook, draftSkill,
}: {
  outlook: OutlookView;
  draftSkill?: DraftSkillView | null;
}) {
  const dc = outlook.draft_capital;
  const seasons = Object.keys(dc.picks_by_season).sort();
  const total = Object.values(dc.picks_by_season).reduce((a, b) => a + b, 0);

  return (
    <Card>
      <CardHead title="Draft" />
      {seasons.length === 0 ? (
        <p className="text-figure leading-snug text-dim">
          Future picks show up here as soon as this franchise holds one.
        </p>
      ) : (
        <>
          {/* Desktop — one rule per season plus a totals rule. This section
              had NO narrow variant at all before this round; below it's a
              card stack instead. */}
          <div className="hidden min-[701px]:block" data-testid="outlook-draft-picks-desktop">
            <Panel>
              <Row variant="head" className="grid-cols-[54px_40px_minmax(0,1fr)] gap-2">
                <div>Season</div>
                <div className="text-right">Picks</div>
                <div className="pl-3">Rounds</div>
              </Row>
              {seasons.map((s) => {
                const rounds = roundsForSeason(dc.picks_by_season_round, s);
                return (
                  <Row key={s} className="grid-cols-[54px_40px_minmax(0,1fr)] items-center gap-2">
                    <div className="font-mono text-figure tabular text-dim">{s}</div>
                    <div className="text-right font-mono text-figure font-semibold tabular">
                      {dc.picks_by_season[s]}
                    </div>
                    <div className="min-w-0 truncate pl-3 font-mono text-figure tracking-[0.06em] text-dim">
                      {rounds.length === 0
                        ? "—"
                        : rounds
                            .map((r) => `${ordinal(r.round)}${r.count > 1 ? ` ×${r.count}` : ""}`)
                            .join("  ·  ")}
                    </div>
                  </Row>
                );
              })}
              {/* Totals the VISIBLE rows, and names what it totals. */}
              <Row variant="total" className="grid-cols-[54px_40px_minmax(0,1fr)] items-center gap-2">
                <div className="font-display text-name font-bold tracking-[-0.024em]">Total</div>
                <div className="text-right font-mono text-figure font-semibold tabular">{total}</div>
                <div className="min-w-0 truncate pl-3 font-mono text-label text-dim">
                  {dc.net_vs_average >= 0
                    ? `${dc.net_vs_average.toFixed(1)} above league average`
                    : `${Math.abs(dc.net_vs_average).toFixed(1)} below league average`}
                </div>
              </Row>
            </Panel>
          </div>

          {/* Below 701px — one EntryCard per season plus a totals card,
              same TotalsCard shape TradeStatTable.tsx uses (border-t-2
              border-t-ink bg-surface-sunk) so a reader who has seen that
              pattern once recognises this as the reconciling row. */}
          <CardList className="min-[701px]:hidden" data-testid="outlook-draft-picks-mobile">
            {seasons.map((s) => {
              const rounds = roundsForSeason(dc.picks_by_season_round, s);
              return (
                <EntryCard key={s}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-figure tabular text-dim">{s}</span>
                    <span className="font-mono text-figure font-semibold tabular text-ink">
                      {dc.picks_by_season[s]} pick{dc.picks_by_season[s] === 1 ? "" : "s"}
                    </span>
                  </div>
                  <MetaLine className="mt-2.5">
                    <Meta label="Rounds">
                      {rounds.length === 0
                        ? "—"
                        : rounds
                            .map((r) => `${ordinal(r.round)}${r.count > 1 ? ` ×${r.count}` : ""}`)
                            .join("  ·  ")}
                    </Meta>
                  </MetaLine>
                </EntryCard>
              );
            })}
            <EntryCard className="border-t-2 border-t-ink bg-surface-sunk">
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-name font-bold tracking-[-0.024em] text-ink">
                  Total
                </span>
                <span className="font-mono text-figure font-semibold tabular text-ink">{total}</span>
              </div>
              <MetaLine className="mt-2.5">
                <Meta label={dc.net_vs_average >= 0 ? "Above league avg" : "Below league avg"}>
                  {Math.abs(dc.net_vs_average).toFixed(1)}
                </Meta>
              </MetaLine>
            </EntryCard>
          </CardList>
        </>
      )}
    </Card>
  );
}
