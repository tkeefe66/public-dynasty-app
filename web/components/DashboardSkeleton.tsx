// Shown while the dashboard JSON is being (re)fetched. Without it,
// DashboardClient rendered nothing during the load window, blank-flashing the
// whole view on initial load and on year/lens/sort changes.
//
// Furniture — "The Ground Loads First": the skeleton IS the real layout with
// its cells empty — same nameplate band, same year-line row, same lead
// layout, and the same FRANCHISE_GRID/TRADE_GRID column tracks the real
// StandingsTable renders — imported from there rather than duplicated, so a
// column can never drift between the skeleton and the loaded table. The two
// ledgers mirror StandingsTable's own shape exactly: a Panel around the
// header row only, then bare entry Rows on the page ground, each drawing its
// own `--rule` hairline (a solid Panel has no stripe to divide rows for it).
// Square `--rule` placeholder bars, never rounded. The view-wide pulse
// animation stays retired: the only motion left is the single indeterminate
// segment at the foot (IndeterminateBar — "One Thing Moves", one per view).
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { IndeterminateBar } from "./furniture/IndeterminateBar";
import { FRANCHISE_COLS, TRADE_COLS, FRANCHISE_GRID, TRADE_GRID } from "./StandingsTable";

function Bar({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`bg-rule ${className}`} style={style} />;
}

function LedgerSkeleton({ grid, cols, rows }: { grid: string; cols: number; rows: number }) {
  return (
    <>
      {/* Section header stand-in — same 44px tap height as the real toggle, and
          the same shape: title, then the year control beside it. Nothing at the
          right margin, because the real head's scope note is gone. */}
      <div className="tap flex items-baseline gap-3 border-b border-rule pt-5 pb-1.5">
        <Bar className="h-[11px] w-24" />
        <Bar className="h-[9px] w-20" />
      </div>
      {/* ONE Panel around the whole ledger — head row and entries together, on
          the real column tracks. This previously wrapped only the header and
          left the entries loose beneath it, faithfully reproducing a bug in
          StandingsTable that the comment here cited as the reason. A skeleton
          must match the shape of the thing that replaces it, so it inherits the
          fix rather than the mistake. */}
      <Panel>
        <Row variant="head" className={`items-center ${grid}`}>
          {Array.from({ length: cols }).map((_, i) => (
            <Bar key={i} className="h-[8px] w-full max-w-[48px]" />
          ))}
        </Row>
        {Array.from({ length: rows }).map((_, r) => (
          <Row key={r} className={`items-center ${grid}`}>
            {Array.from({ length: cols }).map((_, i) => (
              <Bar key={i} className="h-[9px] w-full max-w-[64px]" />
            ))}
          </Row>
        ))}
      </Panel>
    </>
  );
}

export function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading dashboard…</span>

      {/* Nameplate band — the SAME rounded cobalt panel `LeagueHeader` draws,
          at the same padding and min-height, so nothing shifts when data lands.
          It is filled here too: an empty outline where a solid panel is about to
          appear is a bigger jump than a panel that simply gains its type. */}
      <div className="mb-6 rounded-panel bg-stamp px-4 pb-5 pt-4 shadow-panel sm:px-6 sm:pb-6 sm:pt-5">
        <div className="flex min-h-[40px] items-end min-[701px]:min-h-[58px]">
          <Bar className="h-[30px] w-[62%] max-w-[420px] min-[701px]:h-[40px]" />
        </div>
        <Bar className="mt-2.5 h-[9px] w-44" />
      </div>

      {/* NO YEAR ROW. The season control used to be a full-width row of its own
          here; it now rides the ledger head it filters, so reserving a row for
          it would shift every screen down by ~47px the moment data landed —
          the exact fault this skeleton exists to prevent. */}

      {/* The lead — kicker/phase row, headline + body, three-cell figure strip
          on the same 620px measure the live lead uses (HeadlineMoves). */}
      <div className="mb-8">
        <div className="tap flex items-baseline justify-between border-b border-rule pt-4 pb-1.5">
          <Bar className="h-[9px] w-28" />
          <Bar className="h-[9px] w-16" />
        </div>
        <div className="mt-3">
          <Bar className="h-[22px] w-[62%]" />
          <Bar className="mt-2 h-[22px] w-[38%]" />
          <Bar className="mt-3 h-[10px] w-[46%]" />
        </div>
        {/* Same shape as HeadlineMoves' FigureStrip: one Panel holding the
            head Row and the body Row, cols="repeat(3, minmax(0,1fr))". */}
        <Panel className="mt-4 max-w-[620px]">
          <Row variant="head" cols="repeat(3, minmax(0,1fr))" className="gap-4">
            {Array.from({ length: 3 }).map((_, c) => (
              <Bar key={c} className="h-[8px] w-10" />
            ))}
          </Row>
          <Row cols="repeat(3, minmax(0,1fr))" className="gap-4">
            {Array.from({ length: 3 }).map((_, c) => (
              <Bar key={c} className="h-[10px] w-16" />
            ))}
          </Row>
        </Panel>
        {/* The lead's "Read the trade →" row — a 9px link on the same 620px
            measure, right-aligned. Omitting it shifted both ledgers up ~21px
            the moment data landed. */}
        <div className="flex justify-end max-w-[620px] mt-2">
          <Bar className="h-[9px] w-24" />
        </div>
      </div>

      {/* Franchises + Trades — the two ledgers, same column tracks the real
          StandingsTable renders. */}
      <LedgerSkeleton grid={FRANCHISE_GRID} cols={FRANCHISE_COLS.length} rows={6} />
      <LedgerSkeleton grid={TRADE_GRID} cols={TRADE_COLS.length} rows={6} />

      {/* The one animated element in this view. */}
      <div className="mt-6">
        <IndeterminateBar label="Loading league history" />
      </div>
    </div>
  );
}
