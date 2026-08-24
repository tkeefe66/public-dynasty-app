import { Fragment, ReactNode } from "react";
import Link from "next/link";
import { AssetLine, LensMargins, LensWinners } from "@/lib/types";
import { fmtDate } from "@/lib/format-date";
import { fmtLensValue, realizedTotals, StatTotals, sumBecame } from "@/lib/trade-lens";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { CardList, EntryCard, MetaLine, Meta } from "./furniture/EntryCard";
import { TradeAssetCard, type AssetCardFact } from "./TradeAssetCard";

// realizedTotals/StatTotals now live in lib/trade-lens.ts (shared with the OG
// share card, a non-React module) — re-exported here so existing importers
// (TradeSidePanel.tsx, tests/TradeStatTable.test.tsx) don't need to change.
export { realizedTotals };
export type { StatTotals };

/* ---------------------------------------------------------------------------
 * TradeStatTable — design_handoff_agate/CLAUDE_CODE.md § Commit 4, drawn in
 * Dynasty Directions.dc.html "2a.2". One side's haul as a ruled ledger:
 * `Received · Value · Total · Reg · Playoff · Toilet`, one 26px rule per
 * asset row, closing with a `Total realized` rule.
 *
 * The closing row's per-lens colors come from `winnersByLens`/`marginsByLens`
 * — the same API fields the ruling stamp and SCOREBOARD read — never
 * recomputed here, so all three views (stamp, scoreboard, ledger) agree by
 * construction (DESIGN.md § "Figures Reconcile").
 * ------------------------------------------------------------------------ */

// Grid: label column flexes, the metric columns are fixed widths. Six of them
// now — Started joined the five, so the tracks gained one.
const COLS = "grid-cols-[minmax(0,1fr)_60px_60px_60px_56px_60px_56px]";

/**
 * The table's columns.
 *
 * `lens` is NULL for Started, and that null is the point: the five lenses are
 * the scored taxonomy the API computes `margins_by_lens` and
 * `winners_by_lens` over, and Started is not one of them. It has no margin, so
 * it has no winner and the totals row leaves it plain ink rather than inventing
 * a verdict for it. The Scoreboard still says FIVE LENSES and still means it.
 *
 * ORDER: Value · Total · Started · Reg · Playoff · Toilet. That is a narrowing
 * sequence — everything the haul scored, then the part you actually deployed,
 * then that part split by phase — so Started sits between the total it is a
 * subset of and the phases that are subsets of it.
 */
const LENS_COLS: {
  lens: keyof LensMargins | null; label: string; field: keyof StatTotals; raw: keyof AssetLine;
}[] = [
  { lens: "value", label: "Value", field: "ktc", raw: "ktc" },
  { lens: "total", label: "Total", field: "total", raw: "production_total" },
  { lens: null, label: "Started", field: "started", raw: "production_started" },
  { lens: "regular", label: "Reg", field: "regular", raw: "production_regular" },
  { lens: "playoff", label: "Playoff", field: "playoff", raw: "production_playoff" },
  { lens: "toilet", label: "Toilet", field: "toilet", raw: "production_toilet" },
];

/** A column's figure. Started formats like the production metrics it sits
 *  among; only Value is a whole number. */
function fmtCol(c: (typeof LENS_COLS)[number], v: number): string {
  return fmtLensValue(c.lens ?? "total", v);
}

interface Props {
  ownerName: string;
  userId: string;
  rows: AssetLine[];
  totals: StatTotals;
  winnersByLens: LensWinners;
  marginsByLens: LensMargins;
  /** Optional rich header (e.g. an OwnerLabel with avatar); falls back to ownerName. */
  header?: ReactNode;
  /** player_id -> the week this side dropped them (for the "DROPPED WK n" tag). */
  dropWeeks?: Record<string, number>;
}

const dash = "—";

function sortRows(rows: AssetLine[]): AssetLine[] {
  return [...rows].sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "player" ? -1 : 1;
    return a.kind === "player"
      ? b.production_total - a.production_total
      : b.ktc - a.ktc;
  });
}

interface StateTag { text: string; tone: "pos" | "neg" | "dim"; }

/** State tags in mono uppercase, per DESIGN.md § "The Signed Number": the
 *  word itself is metadata (never colored) except the three canonical states
 *  drawn in "2a.2", which read as outcomes, not chrome. */
function stateTag(r: AssetLine, dropWeek?: number): StateTag | null {
  if (r.flip) return { text: "FLIPPED →", tone: "dim" };
  if (r.kind === "pick") return { text: "UNRESOLVED", tone: "dim" };
  if (r.terminal_state === "on_roster") return { text: "ON ROSTER", tone: "pos" };
  if (r.terminal_state === "dropped") {
    return { text: dropWeek != null ? `DROPPED WK ${dropWeek}` : "DROPPED", tone: "neg" };
  }
  if (r.terminal_state === "undrafted") return { text: "UNRESOLVED", tone: "dim" };
  return null;
}

function StateTagView({ tag }: { tag: StateTag | null }) {
  if (!tag) return null;
  const cls = tag.tone === "pos" ? "text-pos-strong" : tag.tone === "neg" ? "text-neg-strong" : "text-dim";
  return (
    <span className={`ml-2 font-mono text-label uppercase tracking-[0.11em] align-middle ${cls}`}>
      {tag.text}
    </span>
  );
}

/** Label cell content when a player arrived via a drafted pick: "PICK → PLAYER". */
function PickToPlayerLabel({ row }: { row: AssetLine }) {
  return (
    <>
      <span className="text-dim">{row.from_pick} pick</span>
      <span className="mx-1 text-dim">→</span>
      <span className="align-middle">{row.label}</span>
    </>
  );
}

function TradedToLine({ flip }: { flip: NonNullable<AssetLine["flip"]> }) {
  const target = flip.trade_id && flip.league_id
    ? `/league/${flip.league_id}/trade/${flip.trade_id}` : null;
  const who = target
    ? <Link href={target} className="text-ink underline decoration-rule hover:decoration-ink">{flip.to_owner}</Link>
    : <span className="text-ink">{flip.to_owner}</span>;
  return (
    <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
      traded to {who}{flip.date ? ` · ${fmtDate(flip.date)}` : ""} → became
    </span>
  );
}

/** Closing-row tone: dim when the lens is unscored/tied; pos for the side
 *  that won it; plain ink otherwise. Straight off `winners_by_lens` /
 *  `margins_by_lens` — never recomputed. */
function totalTone(
  lens: keyof LensMargins | null, userId: string, winners: LensWinners, margins: LensMargins,
): string {
  // Started has no lens, so no margin and no winner — plain ink. Colouring it
  // would be claiming a verdict the API never computed.
  if (lens == null) return "text-ink";
  if (margins[lens] == null) return "text-dim";
  return winners[lens] === userId ? "text-pos-strong" : "text-ink";
}

/**
 * Has this TRADE produced anything yet?
 *
 * Read off `marginsByLens`, which the component already receives and which is
 * trade-level, not side-level — so both sides of a trade always lead with the
 * same metric. A margin is null exactly when "a lens both sides left at 0",
 * i.e. nothing has been scored on it.
 *
 * This is the same condition the ruling stamp already renders as "VALUE ONLY"
 * ("ahead by +880 value. No points on the board yet."), so the fallback below
 * is not a second rule — it is the page agreeing with itself.
 */
function hasProduced(margins: LensMargins): boolean {
  return (["total", "regular", "playoff", "toilet"] as const).some((l) => margins[l] != null);
}

/**
 * What a card leads with.
 *
 * POINTS FIRST once there are points: a trade is settled on the field, not on
 * today's market. `started` is starters-only across every week — what the owner
 * actually deployed — so a player who produced from the bench does not flatter
 * the headline.
 *
 * Before anything has played, every production figure is 0.0 and Trade Value is
 * the only thing known, so leading with "0.0 STARTED POINTS" would headline the
 * absence of information on every preseason trade. The page already calls that
 * state VALUE ONLY.
 */
function leadFor(margins: LensMargins) {
  return hasProduced(margins)
    ? { field: "started" as const, raw: "production_started" as const, label: "Started Points", decimals: 1 as const }
    : { field: "ktc" as const, raw: "ktc" as const, label: "Trade value", decimals: 0 as const };
}

/** One asset's figure for whichever metric leads. */
function leadValue(row: AssetLine, lead: ReturnType<typeof leadFor>): string {
  return lead.field === "ktc"
    ? fmtLensValue("value", row.ktc)
    : (row[lead.raw] as number).toFixed(lead.decimals);
}

/** Everything the headline is not, for a card's meta line. */
function metaColsFor(lead: ReturnType<typeof leadFor>) {
  // Trade Value is dropped from the meta only when it IS the headline.
  return LENS_COLS.filter((c) => c.field !== lead.field);
}

/**
 * One `AssetLine` as a phone card.
 *
 * The two shapes here are the whole of the mobile reading:
 *
 *  - a **flipped** asset has no figures of its own — its value moved to what it
 *    became — so it passes NO facts. `TradeAssetCard` then draws no chevron and
 *    no body, because there is nothing to open, and its `traded to … → became`
 *    line is the card's entire content. The assets it became follow as nested
 *    cards.
 *  - everything else passes Trade Value as the headline and the other four as
 *    meta. An unresolved **pick** has no production, so those four are dashes —
 *    `dim`, never a fabricated 0.0.
 *
 * Provenance (`2026 1st pick → Makai Lemon` on desktop) moves OUT of the name
 * and into the body. At 390px a name plus a state tag plus a five-figure number
 * already fills the line; prefixing the pick it came from truncated the player,
 * which is the one word the row exists to say.
 */
function AssetCard({
  row, dropWeeks, lead, nested = false,
}: {
  row: AssetLine; dropWeeks?: Record<string, number>;
  lead: ReturnType<typeof leadFor>; nested?: boolean;
}) {
  const flip = row.flip ?? null;
  const isPick = row.kind === "pick";
  const tag = stateTag(row, row.player_id ? dropWeeks?.[row.player_id] : undefined);
  const noFigures = flip != null;

  const facts: AssetCardFact[] = noFigures
    ? []
    : metaColsFor(lead).map((c) => ({
        label: c.label,
        value: c.field === "ktc"
          ? fmtLensValue("value", row.ktc)
          : isPick ? dash : fmtCol(c, row[c.raw] as number),
        tone: c.field !== "ktc" && isPick ? ("dim" as const) : undefined,
      }));

  const journey = flip ? (
    <TradedToLine flip={flip} />
  ) : row.from_pick ? (
    <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
      from {row.from_pick} pick
    </span>
  ) : undefined;

  return (
    <TradeAssetCard
      nested={nested}
      name={row.label}
      tag={<StateTagView tag={tag} />}
      headline={noFigures ? dash : leadValue(row, lead)}
      headlineLabel={lead.label}
      headlineTone={noFigures || (row[lead.raw] as number) === 0 ? "dim" : "pos"}
      facts={facts}
      journey={journey}
    />
  );
}

/**
 * A totals card — the became-subtotal and the closing `Total realized`.
 *
 * Always open, never a disclosure: see the call site. All five metrics show,
 * headline plus meta, so the card reconciles against the cards above it
 * without a tap.
 */
function TotalsCard({
  label, value, tone, lead, nested = false,
}: {
  label: string;
  value: (c: (typeof LENS_COLS)[number]) => string;
  tone?: (c: (typeof LENS_COLS)[number]) => string;
  lead: ReturnType<typeof leadFor>;
  nested?: boolean;
}) {
  const leadCol = LENS_COLS.find((c) => c.field === lead.field) ?? LENS_COLS[0];
  return (
    <EntryCard
      className={`border-t-2 border-t-ink bg-surface-sunk ${nested ? "ml-4" : ""}`}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[-0.01em] text-ink">
          {label}
        </span>
        <span className="grid shrink-0 justify-items-end text-right">
          <b className={`font-mono text-name font-semibold tabular leading-none ${tone ? tone(leadCol) : "text-ink"}`}>
            {value(leadCol)}
          </b>
          <span className="mt-0.5 font-mono text-label uppercase tracking-[0.12em] text-dim">
            {lead.label}
          </span>
        </span>
      </div>
      <MetaLine className="mt-2.5">
        {metaColsFor(lead).map((c) => (
          <Meta key={c.label} label={c.label}>
            {value(c)}
          </Meta>
        ))}
      </MetaLine>
    </EntryCard>
  );
}

export function TradeStatTable({
  ownerName, userId, rows, totals, winnersByLens, marginsByLens, header, dropWeeks,
}: Props) {
  const sorted = sortRows(rows);
  // Trade-wide, so both sides lead with the same metric.
  const lead = leadFor(marginsByLens);
  // When a side received a single asset that it flipped, the per-flip
  // "became" subtotal is numerically identical to the Total-realized row
  // below it — two stacked total rows read like a bug. Suppress it then.
  const lone = sorted.length === 1;

  /** A subtotal is only a subtotal when it sums more than one thing.
   *
   *  Two ways this row can be pure restatement, and the original guard caught
   *  only the second:
   *
   *   1. The flip resolved to ONE terminal asset. Then "total" prints the
   *      identical figures to the single became row directly above it — which
   *      is what a real trade showed: Chris Olave → 2026 1st → Emmett Johnson,
   *      2,559 stated twice, back to back. This happens regardless of how many
   *      assets the SIDE received, so `sorted.length` cannot see it.
   *   2. The side received one asset overall, so the flip subtotal also equals
   *      the Total-realized row at the foot of the panel.
   *
   *  With two or more terminal assets the subtotal earns its place: it is the
   *  only figure telling you what that one flipped asset became in aggregate,
   *  and it is not repeated anywhere else. */
  const showBecameSubtotal = (became: unknown[]) => became.length > 1 && !lone;

  return (
    <div>
      <div className="pb-2">
        {header ?? <span className="font-display text-section font-bold tracking-[-0.024em]">{ownerName}</span>}
      </div>

      {/* Desktop — one ruled ledger, five metric columns on fixed tracks. */}
      <div className="hidden min-[701px]:block">
        <Panel>
          <Row variant="head" data-testid="stat-head" className={`items-center ${COLS}`}>
            <div>Received</div>
            {LENS_COLS.map((c) => (
              <div key={c.label} className="text-right whitespace-nowrap">{c.label}</div>
            ))}
          </Row>

          {sorted.map((r, i) => {
            const isPick = r.kind === "pick";
            const flip = r.flip ?? null;
            const became = flip?.became ?? [];
            const sub = flip ? sumBecame(became) : null;
            const tag = stateTag(r, r.player_id ? dropWeeks?.[r.player_id] : undefined);
            return (
              <Fragment key={r.player_id ?? `${r.label}-${i}`}>
                <Row className={`items-center ${COLS}`}>
                  <div className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-ink">
                    {r.from_pick
                      ? <PickToPlayerLabel row={r} />
                      : <span className="align-middle">{r.label}</span>}
                    <StateTagView tag={tag} />
                  </div>
                  {flip ? (
                    LENS_COLS.map((c) => (
                      <div key={c.label} className="text-right tabular whitespace-nowrap text-dim">{dash}</div>
                    ))
                  ) : (
                    LENS_COLS.map((c) => (
                      <div key={c.label} className="text-right tabular whitespace-nowrap text-body">
                        {isPick ? dash : fmtCol(c, r[c.raw] as number)}
                      </div>
                    ))
                  )}
                </Row>

                {flip && (
                  <>
                    <Row className="px-2">
                      <div className="pl-6 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                        <TradedToLine flip={flip} />
                      </div>
                    </Row>
                    {became.map((b, j) => {
                      const bPick = b.kind === "pick";
                      const bTag = stateTag(b, b.player_id ? dropWeeks?.[b.player_id] : undefined);
                      return (
                        <Row key={b.player_id ?? `${b.label}-${j}`} className={`items-center ${COLS}`}>
                          <div className="pl-6 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-ink">
                            {b.from_pick ? <PickToPlayerLabel row={b} /> : b.label}
                            <StateTagView tag={bTag} />
                          </div>
                          {LENS_COLS.map((c) => (
                            <div key={c.label} className="text-right tabular whitespace-nowrap text-body">
                              {bPick ? dash : fmtCol(c, b[c.raw] as number)}
                            </div>
                          ))}
                        </Row>
                      );
                    })}
                    {sub && showBecameSubtotal(became) && (
                      <Row className={`items-center ${COLS} font-mono text-figure uppercase tracking-[0.06em] text-dim`}>
                        <div className="pl-6">total</div>
                        {LENS_COLS.map((c) => (
                          <div key={c.label} className="text-right tabular whitespace-nowrap text-ink font-semibold">
                            {fmtCol(c, sub[c.field])}
                          </div>
                        ))}
                      </Row>
                    )}
                  </>
                )}
              </Fragment>
            );
          })}

          <Row className={`items-center ${COLS} font-semibold`}>
            <div className="font-mono text-label uppercase tracking-[0.11em] text-dim">Total realized</div>
            {LENS_COLS.map((c) => (
              <div key={c.label} className={`text-right tabular whitespace-nowrap ${totalTone(c.lens, userId, winnersByLens, marginsByLens)}`}>
                {fmtCol(c, totals[c.field])}
              </div>
            ))}
          </Row>
        </Panel>
      </div>

      {/* Mobile ≤700px — the fixed five-column grid has no room at 390px
          (label + gaps alone eat the player-name column). Each asset entry
          becomes multi-rule instead: identity (name + state tag) on its own
          rule, then the five lens figures folded into their own labelled
          rules beneath it — the same fold TradeScoreboard.tsx uses for its
          five margins, applied per asset (DESIGN.md § Responsive). Every
          column survives; nothing drops, nothing scrolls horizontally. */}
      {/* Phone — one CARD per asset, headline figure visible, the rest a tap
          away. See `TradeAssetCard` for why (followup C9: this branch used to
          render a row PER METRIC and the page came to 2,340px at 390px). */}
      <div className="min-[701px]:hidden">
        {/* Named for tests: jsdom has no media queries, so BOTH branches render
            and an unscoped query silently reads the desktop ledger — which is
            what made the first version of the totals test pass against the
            wrong element. `CardList` forwards `...rest` for exactly this. */}
        <CardList data-testid="stat-cards">
          {sorted.map((r, i) => {
            const flip = r.flip ?? null;
            const became = flip?.became ?? [];
            const sub = flip ? sumBecame(became) : null;
            return (
              <Fragment key={`m-${r.player_id ?? `${r.label}-${i}`}`}>
                <AssetCard row={r} dropWeeks={dropWeeks} lead={lead} />
                {flip && (
                  <>
                    {became.map((b, j) => (
                      <AssetCard
                        key={`m-b-${b.player_id ?? `${b.label}-${j}`}`}
                        row={b}
                        dropWeeks={dropWeeks}
                        lead={lead}
                        nested
                      />
                    ))}
                    {sub && showBecameSubtotal(became) && (
                      <TotalsCard
                        nested
                        lead={lead}
                        label="Total"
                        value={(c) => fmtCol(c, sub[c.field])}
                      />
                    )}
                  </>
                )}
              </Fragment>
            );
          })}

          {/* NEVER collapsible. "Figures reconcile" is one of the four rules
              that survived Agate — a headline figure must equal the rows
              beneath it, and a total behind a tap is a total you cannot
              check against the cards you can see. */}
          <TotalsCard
            lead={lead}
            label="Total realized"
            value={(c) => fmtCol(c, totals[c.field])}
            tone={(c) => totalTone(c.lens, userId, winnersByLens, marginsByLens)}
          />
        </CardList>
      </div>

    </div>
  );
}
