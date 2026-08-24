"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { StandingRow, Year } from "@/lib/types";
import { decodeDashboardState, encodeDashboardState, SortState } from "@/lib/url-state";
import { applyStandingsState, franchiseSortKey } from "@/lib/standings-filter";
import { InfoTooltip } from "./InfoTooltip";
import { franchiseLetterTone } from "./ownerdeepdive/util";
import { Mark as Icon } from "./furniture/Mark";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { CardList, EntryCard, Meta, MetaLine } from "./furniture/EntryCard";
import { Name } from "./furniture/Name";
import { SegmentControl } from "./SegmentControl";

interface Props {
  /** WHICH LEDGER THIS INSTANCE DRAWS.
   *
   *  The two used to render together on the dashboard, and the reason given was
   *  that they share a row order so "the reader travels down and across, never
   *  sideways". That read is real on a desktop, where both are aligned rows —
   *  but on a phone they are twelve cards apart, so the comparison it protects
   *  is one a phone reader cannot make. They now live on the tabs that own
   *  them: franchise standing under Franchises, trading under Trades, each tab
   *  answering one question.
   *
   *  Sort and URL state stay in this one component rather than being duplicated
   *  per ledger — the two are never on screen together, so one is enough. */
  sections?: "franchises" | "trades";
  /** The season control, rendered in this ledger's head. Passed in rather than
   *  built here: the seasons list and the lens live on the dashboard, and both
   *  tabs hand in the same node so they cannot drift apart. */
  yearControl?: ReactNode;
  leagueId: string;
  rows: StandingRow[];
  year: Year;
  currentSeason: number;
  youUserId?: string | null;
}

/* ---------------------------------------------------------------------------
 * Agate — Standings becomes two ruled ledgers (design_handoff_agate/DESIGN.md
 * § "Two Ledgers"). FRANCHISES is the career-wide identity ledger; TRADES is
 * year-scoped. Both share the same row order (the same sorted `visible`
 * array), so the reader travels down and across, never sideways.
 * ------------------------------------------------------------------------ */

type Col = {
  key: string;
  label: string;
  sortable?: boolean;
  align?: "right";
  tooltip?: { title: string; body: string; formula?: string; align?: "left" | "right" };
};

// Exported so DashboardSkeleton.tsx can build placeholder rows on the exact
// same column tracks — "same rules, same pitch, same column tracks, so
// nothing shifts when data lands" (DESIGN.md "The Ground Loads First").
export const FRANCHISE_COLS: Col[] = [
  { key: "gm_rank", label: "#" },
  { key: "owner_name", label: "Franchise", sortable: true },
  {
    key: "season_wins", label: "Rec", sortable: true,
    tooltip: { title: "Record", body: "Regular-season W-L record. Click to sort by total wins." },
  },
  {
    key: "best_finish", label: "Trophy",
    tooltip: { title: "Trophy", body: "🏆 per championship, 🚽 per Toilet Bowl title (career), or this season's finish when a year is selected." },
  },
  {
    key: "playoff_record", label: "Playoff",
    tooltip: { title: "Playoff Record", body: "Career playoff W-L record. Blank for a single past season." },
  },
  {
    key: "gm_rating", label: "Rating", sortable: true,
    tooltip: { title: "Franchise Rating", body: "The franchise verdict as a letter: 0.60·Results + 0.40·Assets (Results only for redraft), z-scored across the league and scaled to 1500. Weighted toward recent seasons — always as-of-now, not affected by the year filter." },
  },
  {
    key: "roster_rank", label: "Roster",
    tooltip: { title: "Roster Rank", body: "Today's roster rank by market value among the league's franchises. Not affected by the year filter." },
  },
  {
    key: "window", label: "Window",
    tooltip: {
      title: "Roster Window",
      body: "Your competitive stage, banded off the Franchise Rating on this same row — Rebuilding, Retooling, Competing, Contending, Dynasty. Not a separate model: a better rating can never land on a lower stage. Reflects today, not the year filter.",
    },
  },
  {
    key: "draft_capital_value", label: "Draft cap", sortable: true,
    tooltip: { title: "Draft Capital", body: "Trade Value of all future rookie picks currently held. Not affected by the year filter." },
  },
];

export const TRADE_COLS: Col[] = [
  { key: "trade_rank", label: "#" },
  { key: "owner_name", label: "Franchise", sortable: true },
  {
    key: "net_ktc", label: "Value", sortable: true, align: "right",
    tooltip: { title: "Trade Value (realized)", body: "Realized market value of what this owner's trades brought in.", formula: "Σ realized value of received assets", align: "right" },
  },
  {
    key: "production_started", label: "Started", sortable: true, align: "right",
    tooltip: { title: "Started Points", body: "Points from starters only, across every week. NOT Reg + Playoff: playoff counts live title-path games only, so started points in a placement game or an eliminated week belong to no phase. The gap between this and a haul's total is what sat on the bench.", align: "right" },
  },
  {
    key: "production_regular", label: "Reg pts", sortable: true, align: "right",
    tooltip: { title: "Regular Season Points", body: "Started points in regular-season weeks for received players.", align: "right" },
  },
  {
    key: "production_playoff", label: "Playoff pts", sortable: true, align: "right",
    tooltip: { title: "Playoff Points", body: "Started points in real title-bracket weeks only.", align: "right" },
  },
  {
    key: "grade", label: "Gr", sortable: true, align: "right",
    tooltip: { title: "Trade Grade", body: "Trade Value grade relative to league peers.", align: "right" },
  },
];

/* ---------------------------------------------------------------------------
 * Outlook columns — Window and Draft cap. There were three: the `s/t` axis
 * scores sat between them as the receipt for the Window stage, and both the
 * column and the model behind it are retired. Window is now BANDED OFF THE
 * RATING two columns to its left (gm_rating.py::rating_to_stage), so the
 * receipt for it is the Rating cell itself; the full Assets breakdown lives on
 * the franchise page's Outlook tab. A redraft league has no Outlook data at
 * all (engine/capabilities.py; the backend leaves these fields unpopulated in
 * aggregations.py), so both columns are dropped from the ledger rather than
 * ruled out as a row of em-dashes: "absence, not an empty state". They travel
 * as one group because they read as one — a stage and the picks that will
 * move it.
 *
 * Roster is gated SEPARATELY from Outlook — same backend condition today
 * (`_outlooks_apply` in aggregations.py), but checked on its own field here
 * rather than reusing `hasOutlookColumns`'s boolean, so the two columns
 * cannot silently couple if a future format carries one without the other.
 *
 * All four grid strings below are written out in full rather than composed,
 * because Tailwind's JIT only sees class names that appear literally in the
 * source.
 * ------------------------------------------------------------------------ */
const OUTLOOK_COL_KEYS = new Set(["window", "draft_capital_value"]);

/** Column keys that no longer exist. A saved URL or restored state can still
 *  name one; it must be CLEARED, not left to sort on a field that is gone.
 *  Dropping the key from OUTLOOK_COL_KEYS is what stops it being caught by
 *  the orphan check in `effectiveSort`. */
const RETIRED_COL_KEYS = new Set(["strength_trajectory"]);
const ROSTER_COL_KEYS = new Set(["roster_rank"]);
const FRANCHISE_COLS_NO_OUTLOOK: Col[] = FRANCHISE_COLS.filter((c) => !OUTLOOK_COL_KEYS.has(c.key));
const FRANCHISE_COLS_NO_ROSTER: Col[] = FRANCHISE_COLS.filter((c) => !ROSTER_COL_KEYS.has(c.key));
const FRANCHISE_COLS_NO_OUTLOOK_NO_ROSTER: Col[] = FRANCHISE_COLS.filter(
  (c) => !OUTLOOK_COL_KEYS.has(c.key) && !ROSTER_COL_KEYS.has(c.key),
);

// #, Franchise, Rec, Trophy, Playoff, Rating, [Roster], [Window, Draft cap]
//
// The s/t track came out of the first two. The last two are UNCHANGED — they
// never carried it, because it was an Outlook column and they are the
// no-Outlook variants. A dropped column and a dropped track are two separate
// edits (Tailwind's JIT only sees literal class names, so these cannot be
// composed), and `tests/StandingsTable.test.tsx` counts tracks against columns
// in all four combinations so the two can never fall out of step again.
export const FRANCHISE_GRID = "grid-cols-[24px_1.15fr_0.5fr_0.55fr_0.5fr_0.75fr_0.55fr_0.95fr_0.75fr]";
const FRANCHISE_GRID_NO_ROSTER = "grid-cols-[24px_1.3fr_0.55fr_0.6fr_0.55fr_0.8fr_1.0fr_0.8fr]";
const FRANCHISE_GRID_NO_OUTLOOK = "grid-cols-[24px_1.3fr_0.55fr_0.6fr_0.55fr_0.8fr_0.55fr]";
const FRANCHISE_GRID_NO_OUTLOOK_NO_ROSTER = "grid-cols-[24px_1.6fr_0.6fr_0.65fr_0.6fr_0.85fr]";

/** Does any row carry an Outlook reading? One `null` owner (a franchise with
 *  no outlook computed yet) must not strip the columns for the whole league,
 *  so this asks the league, not the row. */
export function hasOutlookColumns(rows: StandingRow[]): boolean {
  return rows.some((r) => r.window != null || r.draft_capital_value != null);
}

/** Does any row carry a roster rank? Mirrors `hasOutlookColumns` above but
 *  asks its own field — a redraft league has nothing to rank between
 *  seasons, so the column is omitted outright rather than shown empty. */
export function hasRosterColumn(rows: StandingRow[]): boolean {
  return rows.some((r) => r.roster_rank != null);
}
export const TRADE_GRID = "grid-cols-[24px_1.15fr_0.7fr_0.75fr_0.75fr_0.8fr_0.4fr]";

/* ---------------------------------------------------------------------------
 * Figure formatting — The Signed Number. Sign is always rendered; zero or an
 * absent value is --dim. Never invent a sign for zero.
 * ------------------------------------------------------------------------ */

function signColor(n: number): string {
  return n > 0 ? "text-pos-strong" : n < 0 ? "text-neg-strong" : "text-dim";
}

/** `signColor`'s rule as a `Meta` tone: positive, negative, or DIM at zero.
 *  Zero is dim rather than untoned — an untoned value renders full-weight ink
 *  and reads as a result. */
function signTone(n: number): "pos" | "neg" | "dim" {
  return n > 0 ? "pos" : n < 0 ? "neg" : "dim";
}

function fmtSigned(n: number, decimals: 0 | 1 = 0): string {
  const mag = decimals === 1 ? n.toFixed(1) : Math.round(n).toLocaleString();
  return n > 0 ? `+${mag}` : mag; // negatives already carry "-" from toFixed/toLocaleString
}

/* ---------------------------------------------------------------------------
 * Franchise Rating tone — 1500 IS THE BASELINE.
 *
 * `engine/gm_rating.py` scales every rating to a 1500-centred number, so the
 * figure is signed in substance even though it carries no sign character:
 * above 1500 is an above-average GM, below is below. Colouring it is therefore
 * "The Signed Number", not decoration — the tone says nothing the figure does
 * not already say, which is the rule colour has to satisfy.
 *
 * THE `-strong` PAIR. `--text-name` is 15px — normal text under WCAG, so the
 * bar is 4.5:1, and on a card's `--surface` the base pair measures --pos 3.22:1
 * (fails) against --pos-strong 5.48:1. `colors.css`'s "large glyphs ONLY" note
 * over-claims; see `furniture/EntryCard.tsx`'s `Meta` for the full measurement.
 * ------------------------------------------------------------------------ */
const RATING_BASELINE = 1500;

function ratingTone(rating: number | null | undefined): string {
  if (rating == null) return "text-dim";
  if (rating > RATING_BASELINE) return "text-pos-strong";
  if (rating < RATING_BASELINE) return "text-neg-strong";
  return "text-ink";  // exactly average — no sign to carry.
}

/** The grade as a `Meta` fact tone. A/B read positive, D/F negative, C is the
 *  league-average band and stays plain ink. Mirrors `franchiseLetterTone`'s
 *  bands without its large-glyph sizing. */
function letterMetaTone(letter: string | null | undefined): "pos" | "neg" | undefined {
  const head = (letter ?? "").charAt(0).toUpperCase();
  if (head === "A" || head === "B") return "pos";
  if (head === "D" || head === "F") return "neg";
  return undefined;
}

function rankOf(r: StandingRow): number {
  return r.gm_rank ?? r.rank;
}

/* ---------------------------------------------------------------------------
 * Franchise column label — the two dashboard ledgers are the one place the
 * *franchise* is the subject, so they read the Sleeper team name. Everywhere
 * else (owner pages, trade pages, the leaderboard, the Owners tab) the subject
 * is the person and the owner name wins. A franchise with no team name set on
 * Sleeper falls back silently to the owner name — never a raw handle. Sorting
 * uses the same key (lib/standings-filter.ts) so A→Z matches what's rendered.
 * ------------------------------------------------------------------------ */

const franchiseLabel = franchiseSortKey;

/**
 * The phone's sort keys — deliberately three, and deliberately these three.
 *
 * Each one is a figure the franchise CARD renders: `gm_rating` is its headline,
 * `season_wins` is its Rec fact, `net_ktc` is its Trade value fact. That is the
 * rule, not the count — a key for a column the card does not show would reorder
 * the list on evidence the reader cannot see.
 *
 * `season_wins` (not `season_record`) because the record is a "31-11" string;
 * the desktop header sorts on total wins for the same reason.
 */
const MOBILE_SORTS: { key: string; label: string }[] = [
  { key: "gm_rating", label: "Rating" },
  { key: "season_wins", label: "Rec" },
  { key: "net_ktc", label: "Value" },
];

/* ---------------------------------------------------------------------------
 * Labelled cell — mobile overflow figures. "Prose Never Shares A Rule": the
 * value never truncates (flex: 0 0 auto, nowrap); the label degrades with
 * ellipsis instead.
 * ------------------------------------------------------------------------ */

function LabelledCell({ label, value, valueClassName = "" }: { label: string; value: ReactNode; valueClassName?: string }) {
  return (
    <div className="flex items-baseline gap-1 min-w-0">
      <span className="flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-label uppercase tracking-[0.11em] text-dim">
        {label}
      </span>
      <span className={`flex-none whitespace-nowrap font-mono text-figure tabular ${valueClassName}`}>
        {value}
      </span>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Section header — role="button", 44px tap target, open/closed mark, row
 * count + scope note. Toggles collapse; state persists per DESIGN.md
 * "Sections Remember".
 * ------------------------------------------------------------------------ */

/**
 * A ledger's head: the collapse trigger, and on the right either the scope note
 * or a control that filters this section.
 *
 * THE TRIGGER IS A REAL `<button>`, and only the trigger. The whole row used to
 * be one `role="button"` div with a hand-rolled Enter/Space handler — which was
 * fine while the right side was inert text, and is not once it holds the year
 * control: an interactive element inside another interactive element is invalid,
 * unreachable by keyboard in the order a reader expects, and announced as one
 * control by a screen reader. A native button also brings Enter/Space for free,
 * so the key handler goes with it.
 */
function SectionHeader({
  title, open, onToggle, action,
}: {
  title: string;
  open: boolean;
  onToggle: () => void;
  /**
   * A control that filters THIS section, drawn beside the title.
   *
   * THE SCOPE NOTE IS GONE. The head used to carry a mono line at the right
   * margin — "Career-wide" on Franchises, the selected season on Trade Grades.
   * The season one repeated the year control sitting a few inches to its left,
   * and both floated so far from the heading at desktop width that they read as
   * unrelated page furniture. What the columns mean now lives with the columns:
   * REC's own header tooltip says career record. (History: this used to be
   * `{action ?? <scopeNote/>}`, which silently deleted the note whenever a
   * control was passed — a different bug, and not the reason it is gone now.)
   */
  action?: ReactNode;
}) {
  return (
    /* BASELINE, not centre. The title is `--text-section` and the control's
       segments are `--text-label` — 8.5px — so centring their boxes leaves two
       runs of type on two different baselines, which is what the head looked
       like: the year run sitting a few pixels low against "Trade Grades".
       Aligning the baselines is what makes the control read as part of the
       heading line rather than a second object parked next to it. */
    <div className="flex items-baseline gap-3 border-b border-rule pt-5 pb-1.5">
      {/* The trigger holds the TITLE AND NOTHING ELSE, and that is a contract,
          not tidiness: whatever sits inside a <button> becomes part of its
          accessible name. The note lived in here for one commit and renamed the
          control to "Franchises Career-wide" — which a screen reader announces
          on every toggle, and which broke `getByRole("button", {name:
          /^Franchises$/})` at every width where the note is visible. */}
      <button
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="tap flex min-w-0 items-baseline gap-2 select-none text-left"
      >
        <Icon name={open ? "open" : "closed"} size={12} className="text-dim" />
        <span className="font-display text-section font-bold tracking-[-0.024em]">{title}</span>
      </button>
      {/* THE CONTROL SITS NEXT TO THE TITLE, not at the far margin. It used to
          take the right end (`ml-auto`), which on a wide viewport put the year
          filter a foot from the heading it filters — far enough that the link
          between them stops being positional, which was the entire argument for
          moving it onto the head in the first place. Nothing takes the right
          end now — the scope note that used to is gone. */}
      {action}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Collapse persistence — dr:collapse:<section>. Default open on desktop,
 * closed on mobile (≤700px) on first visit; an explicit choice wins after
 * that. Initializes after mount to avoid SSR/hydration mismatches.
 * ------------------------------------------------------------------------ */

function useSectionCollapse(section: string) {
  const key = `dr:collapse:${section}`;
  const [open, setOpen] = useState(true); // SSR + first paint: desktop default

  useEffect(() => {
    let initial = true;
    try {
      const stored = window.localStorage.getItem(key);
      if (stored === "open") initial = true;
      else if (stored === "closed") initial = false;
      else initial = !window.matchMedia("(max-width: 700px)").matches;
    } catch {
      // localStorage unavailable — keep the desktop default.
    }
    setOpen(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(key, next ? "open" : "closed");
      } catch {
        // ignore — private mode etc.
      }
      return next;
    });
  };

  return { open, toggle };
}

/* ---------------------------------------------------------------------------
 * Header row — column labels on the ruled ground's first rule.
 * ------------------------------------------------------------------------ */

function HeaderRow({
  cols, grid, sort, onSort, testId,
}: {
  cols: Col[]; grid: string; sort: SortState; onSort: (col: string) => void;
  /** Names the head row so a test can assert on the COLUMNS specifically.
   *  Without it the nearest queryable ancestor is a region wide enough to
   *  include the phone cards, and a column-label assertion silently passes on
   *  a card fact instead — which is how a renamed column stayed green. */
  testId?: string;
}) {
  /* Deliberately NOT wrapped in a Panel. A Panel is the whole LEDGER — head row,
   * body rows and total together (.design/components/ledger/Panel.prompt.md).
   * Wrapping only the header rendered a floating rounded box with the entries
   * spilling loose beneath it, which is how four screens shipped. The CALLER
   * wraps the ledger; this returns a row. */
  return (
    <>
      {/* variant="head" supplies the sunk ground, the 44px height a SortButton
          needs, and the mono uppercase label type. Without it the column labels
          render exactly as authored — "REC" beside "Trophy" — because their
          source strings are inconsistently cased and nothing was normalising
          them. Caps belong to mono labels; headings are the thing that stopped
          shouting, not these. */}
      <Row
        role="row"
        variant="head"
        data-testid={testId}
        className={`items-center ${grid} `}
      >
        {cols.map((c) => {
          const sorted = sort.column === c.key;
          const dir = sort.direction;
          return (
            <div
              key={c.key}
              role="columnheader"
              aria-sort={sorted ? (dir === "desc" ? "descending" : "ascending") : "none"}
              className={`flex items-center gap-1 min-w-0 ${c.align === "right" ? "justify-end text-right" : ""}`}
            >
              {c.sortable ? (
                <button
                  type="button"
                  onClick={() => onSort(c.key)}
                  aria-label={`Sort by ${c.label}${sorted ? `, currently ${dir === "desc" ? "descending" : "ascending"}` : ""}`}
                  /* `uppercase` is NOT redundant with the head Row's, and
                   * removing it split the header: Tailwind's preflight sets
                   * `button, select { text-transform: none }` (to drop an
                   * Edge/Firefox inheritance quirk), so a sortable header in a
                   * <button> ignores the row's casing while a non-sortable one
                   * in a <span> inherits it. The labels' own strings are
                   * inconsistently cased, so the result was "REC" beside
                   * "Trophy" in the same row. Any interactive element inside a
                   * head Row needs this. */
                  className="flex items-center gap-1 uppercase hover:text-ink"
                >
                  {c.label}
                  {sorted && <Icon name={dir === "desc" ? "sort-desc" : "sort-asc"} size={11} />}
                </button>
              ) : (
                <span>{c.label}</span>
              )}
              {c.tooltip && <InfoTooltip {...c.tooltip} />}
            </div>
          );
        })}
      </Row>
    </>
  );
}

/* ---------------------------------------------------------------------------
 * Ledger entry — one franchise, one link. On mobile it spans two or three
 * rules; the Link itself carries the ruled background at its own natural
 * height (never a direct child of a shared Ruled ground, which would clamp
 * it to a single 26px rule) so a multi-rule entry stays one tap target.
 * ------------------------------------------------------------------------ */

function LedgerEntry({ href, isYou, children }: { href: string; isYou: boolean; children: ReactNode }) {
  /* An entry is still ONE link across all of its rules, so tapping any part of
   * it opens that franchise. What changed is what supplies the divider: the
   * entry used to carry the striped ground itself at its own height, because a
   * direct child of a shared ground got clamped to a single 26px rule. Rows set
   * min-height now, so the entry is a plain link and the first Row inside it
   * draws the `--rule` hairline. The "you" marker moves to a border on the
   * entry — a drawn line, never an elevation. */
  return (
    <Link
      href={href}
      className={`block border-t border-rule hover:bg-surface-sunk ${
        isYou ? "border-l-[3px] border-l-stamp bg-stamp-wash" : ""
      }`}
    >
      {children}
    </Link>
  );
}

export function StandingsTable({ sections = "franchises", yearControl, leagueId, rows, year, youUserId }: Props) {
  const showFranchises = sections === "franchises";
  const showTrades = sections === "trades";
  const router = useRouter();
  const sp = useSearchParams();
  const state = useMemo(() => decodeDashboardState(sp), [sp]);

  // Redraft leagues carry no Outlook layer, so the three outlook columns are
  // omitted outright (see OUTLOOK_COL_KEYS above). Roster is gated on its own
  // field, independently — see hasRosterColumn's comment.
  const showOutlook = useMemo(() => hasOutlookColumns(rows), [rows]);
  const showRoster = useMemo(() => hasRosterColumn(rows), [rows]);
  const franchiseCols = showOutlook
    ? (showRoster ? FRANCHISE_COLS : FRANCHISE_COLS_NO_ROSTER)
    : (showRoster ? FRANCHISE_COLS_NO_OUTLOOK : FRANCHISE_COLS_NO_OUTLOOK_NO_ROSTER);
  const franchiseGrid = showOutlook
    ? (showRoster ? FRANCHISE_GRID : FRANCHISE_GRID_NO_ROSTER)
    : (showRoster ? FRANCHISE_GRID_NO_OUTLOOK : FRANCHISE_GRID_NO_OUTLOOK_NO_ROSTER);

  // "auto" is the sentinel for "no explicit choice yet" — default to Franchise
  // Rating desc, matching the gm_rank shown in the leftmost column.
  //
  // A saved URL can also name an outlook column this league doesn't render —
  // a dynasty link opened against a redraft league. Every value there is null,
  // so the sort is inert *and* invisible: no header to see it on or clear it
  // from. Treat an orphaned column as no choice at all.
  const effectiveSort = useMemo(() => {
    const orphaned =
      RETIRED_COL_KEYS.has(state.sort.column) ||
      (!showOutlook && OUTLOOK_COL_KEYS.has(state.sort.column));
    if (state.sort.column !== "auto" && !orphaned) return state.sort;
    return { column: "gm_rating", direction: "desc" as const };
  }, [state.sort, showOutlook]);

  const visible = useMemo(
    () => applyStandingsState(rows, { sort: effectiveSort, filters: {} }),
    [rows, effectiveSort],
  );

  function updateState(next: typeof state) {
    const qs = encodeDashboardState(next);
    router.push(`/league/${leagueId}${qs ? `?${qs}` : ""}`);
  }

  /**
   * Compares against `effectiveSort`, NOT `state.sort`.
   *
   * They differ exactly once and it matters: before any explicit choice
   * `state.sort.column` is the sentinel `"auto"` while `effectiveSort` resolves
   * to `gm_rating desc` — and `effectiveSort` is what the header arrow and the
   * mobile pill DISPLAY. Comparing against the raw state meant the first click
   * on the column already shown as active fell into the "different column"
   * branch and re-applied `desc`, so the control looked sorted, said it was
   * sorted, and ignored the first tap. Two taps to flip a direction the arrow
   * already claimed.
   *
   * Same fix serves both widths, because both read `effectiveSort`.
   */
  function toggleSort(col: string) {
    const flip = effectiveSort.column === col && effectiveSort.direction === "desc";
    updateState({ ...state, sort: { column: col, direction: flip ? "asc" : "desc" } });
  }

  const franchises = useSectionCollapse("franchises");
  const trades = useSectionCollapse("trades");

  return (
    <div className="mt-8">
      {showFranchises && (
      <>
      {/* The year control RIDES THE HEAD IT FILTERS. It used to sit above
          everything as a full-width row of its own, which cost a row and left
          the reader to remember which sections it applied to. Beside the
          heading, that link is positional — and on the Trades tab the same
          control governs two sections, which is exactly when "which does this
          filter?" stops being obvious. */}
      <SectionHeader
        title="Franchises"
        open={franchises.open}
        onToggle={franchises.toggle}
        action={yearControl}
      />
      {franchises.open && (
        <>
          {/* Desktop — one rule per entry. */}
          <Panel className="hidden min-[701px]:block">
            <HeaderRow cols={franchiseCols} grid={franchiseGrid} sort={effectiveSort} onSort={toggleSort} testId="franchise-head" />
            {visible.map((r) => {
              const isYou = !!youUserId && r.user_id === youUserId;
              return (
                <LedgerEntry key={`f-d-${r.user_id}`} href={`/league/${leagueId}/owner/${r.user_id}`} isYou={isYou}>
                  <Row className={`items-center ${franchiseGrid} `}>
                    <div className="text-dim">{rankOf(r)}</div>
                    <div className="min-w-0 flex items-baseline gap-1">
                      <Name title={franchiseLabel(r)}>{franchiseLabel(r)}</Name>
                      {isYou && <span className="font-mono text-label tracking-[0.11em] text-dim shrink-0">YOU</span>}
                    </div>
                    <div>{r.season_record ?? <span className="text-dim">—</span>}</div>
                    <div>{r.best_finish ?? <span className="text-dim">—</span>}</div>
                    <div>{r.playoff_record ?? <span className="text-dim">—</span>}</div>
                    <div className="flex items-baseline gap-1.5">
                      {/* An unrated franchise (no completed season) is an em
                          dash in dim ink, not a letter. It used to tone the
                          absence as if it were a "C", which reads as an
                          explicit league-average verdict — the one claim we
                          have no evidence for. */}
                      <span
                        className={`font-display text-name font-bold ${
                          r.gm_letter ? franchiseLetterTone(r.gm_letter) : "text-dim"
                        }`}
                      >
                        {r.gm_letter ?? "—"}
                      </span>
                      <span className="text-dim">{r.gm_rating != null ? r.gm_rating.toLocaleString() : ""}</span>
                    </div>
                    {showRoster && (
                      <div>
                        {r.roster_rank != null ? `#${r.roster_rank}` : <span className="text-dim">—</span>}
                      </div>
                    )}
                    {showOutlook && (
                      <>
                        <div className="uppercase truncate">
                          {r.window ? r.window.toUpperCase() : <span className="text-dim">—</span>}
                        </div>
                        <div>
                          {r.draft_capital_value
                            ? Math.round(r.draft_capital_value).toLocaleString()
                            : <span className="text-dim">—</span>}
                        </div>
                      </>
                    )}
                  </Row>
                </LedgerEntry>
              );
            })}
          </Panel>

          {/* Mobile — ONE CARD per franchise, the shape `templates/mobile`
              draws: identity on top with a single headline figure, then four
              labelled facts on one line.

              It was three stacked `Row`s in a `Panel`. `Row` draws its own
              `border-top` and `LedgerEntry` drew another, so each franchise was
              cut by two internal hairlines at exactly the weight that separates
              one franchise from the next — you could not see where an entry
              ended. `EntryCard.prompt.md` names it: "any divider drawn between
              children cut a franchise in half. A card's edge IS the entry
              boundary."

              THE RATING IS THE HEADLINE and the grade is a fact, which inverts
              what this first shipped as. That is the drawn card
              (`Mobile.dc.html`'s STANDINGS: headline `rating`, facts Rank / Rec
              / Grade / Trade value), and it is the reason the card fits four
              facts on one line instead of six on two.

              FIVE COLUMNS DO NOT COME TO THE PHONE — Playoffs, Titles, Roster,
              Window and Draft cap. That is a deliberate departure from
              "every column survives": the spec's card carries every one of ITS
              columns because its desktop table has six, and ours has nine.
              All five live on the franchise page this card links to — the
              Outlook pair with the full Assets breakdown that Window is banded
              off. (It was Playoffs, Titles, Window, s/t and Draft cap; s/t is
              retired and Roster took the fifth slot.) */}

          {/* SORT, ON A PHONE (followup C3). Below 701px there is no HeaderRow,
              so sorting was desktop-only and the cards sat in whatever order
              the server sent — a phone could not ask "who has the best record?"
              at all.

              THREE KEYS, AND THEY ARE THE CARD'S OWN FIGURES. Desktop offers
              eight sortable columns, which no segmented control holds at 390px,
              so the subset needs a principle rather than a budget: you may sort
              by what the card shows you. Rating is its headline; Rec and Trade
              value are two of its four facts. Sorting by a column the card does
              not render would reorder the list on evidence the reader cannot
              see — the same defect as a hidden column, wearing a control.

              `SegmentControl` is the one single-select dialect in the system
              and is already on this screen as the year selector, so this adds
              no new pattern. Tapping the ACTIVE key flips direction, exactly as
              a desktop header does — `toggleSort` already has that behaviour,
              and the arrow says which way. */}
          <div className="mb-3 min-[701px]:hidden">
            <SegmentControl<string>
              aria-label="Sort franchises"
              options={MOBILE_SORTS.map((s) => ({
                key: s.key,
                label:
                  effectiveSort.column === s.key
                    ? `${s.label} ${effectiveSort.direction === "desc" ? "▾" : "▴"}`
                    : s.label,
              }))}
              value={effectiveSort.column}
              onChange={toggleSort}
            />
          </div>

          <CardList className="min-[701px]:hidden">
            {visible.map((r) => {
              const isYou = !!youUserId && r.user_id === youUserId;
              return (
                <EntryCard
                  key={`f-m-${r.user_id}`}
                  href={`/league/${leagueId}/owner/${r.user_id}`}
                  variant={isYou ? "mine" : "body"}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="shrink-0 font-mono text-figure tabular text-dim">{rankOf(r)}</span>
                    <span className="min-w-0 flex-1 flex items-baseline gap-1">
                      <Name title={franchiseLabel(r)}>{franchiseLabel(r)}</Name>
                      {isYou && (
                        <span className="shrink-0 font-mono text-label tracking-[0.11em] text-stamp">YOU</span>
                      )}
                    </span>
                    <span className="shrink-0 grid justify-items-end">
                      <span className={`font-mono text-name font-semibold tabular leading-tight ${ratingTone(r.gm_rating)}`}>
                        {r.gm_rating != null ? r.gm_rating.toLocaleString() : "—"}
                      </span>
                      <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
                        Rating
                      </span>
                    </span>
                  </div>

                  <MetaLine>
                    <Meta label="Rank">{`${rankOf(r)} of ${rows.length}`}</Meta>
                    <Meta label="Rec">{r.season_record ?? "—"}</Meta>
                    <Meta label="Grade" tone={letterMetaTone(r.gm_letter)}>
                      {r.gm_letter ?? "—"}
                    </Meta>
                    <Meta label="Trade value" tone={signTone(r.net_ktc)}>
                      {fmtSigned(r.net_ktc)}
                    </Meta>
                  </MetaLine>
                </EntryCard>
              );
            })}
          </CardList>
        </>
      )}

      </>
      )}

      {showTrades && (
      <>
      {/* TRADE GRADES, not "Trades". A per-owner trading leaderboard and the
          trade history were both called "Trades" — one name for two different
          things, on two tabs. No row count: the figure that matters here is
          each owner's, not how many owners there are. */}
      <SectionHeader
        title="Trade Grades"
        open={trades.open}
        onToggle={trades.toggle}
        action={yearControl}
      />
      {trades.open && (
        <>
          {/* Desktop */}
          <Panel className="hidden min-[701px]:block">
            <HeaderRow cols={TRADE_COLS} grid={TRADE_GRID} sort={effectiveSort} onSort={toggleSort} testId="trade-head" />
            {visible.map((r) => {
              const isYou = !!youUserId && r.user_id === youUserId;
              return (
                <LedgerEntry key={`t-d-${r.user_id}`} href={`/league/${leagueId}/owner/${r.user_id}`} isYou={isYou}>
                  <Row className={`items-center ${TRADE_GRID} `}>
                    <div className="text-dim">{rankOf(r)}</div>
                    <div className="min-w-0 flex items-baseline gap-1">
                      <Name title={franchiseLabel(r)}>{franchiseLabel(r)}</Name>
                      {isYou && <span className="font-mono text-label tracking-[0.11em] text-dim shrink-0">YOU</span>}
                    </div>
                    <div className={`text-right font-semibold ${signColor(r.net_ktc)}`}>{fmtSigned(r.net_ktc)}</div>
                    <div className={`text-right font-semibold ${signColor(r.production_started ?? 0)}`}>
                      {r.production_started != null
                        ? fmtSigned(r.production_started, 1)
                        : <span className="text-dim">—</span>}
                    </div>
                    <div className={`text-right font-semibold ${signColor(r.production_regular)}`}>
                      {fmtSigned(r.production_regular, 1)}
                    </div>
                    <div className={`text-right font-semibold ${signColor(r.production_playoff)}`}>
                      {fmtSigned(r.production_playoff, 1)}
                    </div>
                    <div className={`text-right font-bold ${franchiseLetterTone(r.grade)}`}>{r.grade}</div>
                  </Row>
                </LedgerEntry>
              );
            })}
          </Panel>

          {/* Mobile — cards, matching the Franchises ledger above. Same
              reason: a `Panel` of `Row`s drew an internal hairline through each
              entry at the weight that separates one entry from the next.

              Its own four facts. The headline is the realized Trade Value —
              this ledger's subject — with the points breakdown and the Trade
              Grade beneath. NB that grade is the trade-scoped one, NOT the
              Franchise Rating letter on the card above; they are different
              verdicts and the labels have to keep them apart. */}
          <CardList className="min-[701px]:hidden">
            {visible.map((r) => {
              const isYou = !!youUserId && r.user_id === youUserId;
              return (
                <EntryCard
                  key={`t-m-${r.user_id}`}
                  href={`/league/${leagueId}/owner/${r.user_id}`}
                  variant={isYou ? "mine" : "body"}
                >
                  <div className="flex items-center gap-2.5">
                    <span className="shrink-0 font-mono text-figure tabular text-dim">{rankOf(r)}</span>
                    <span className="min-w-0 flex-1 flex items-baseline gap-1">
                      <Name title={franchiseLabel(r)}>{franchiseLabel(r)}</Name>
                      {isYou && (
                        <span className="shrink-0 font-mono text-label tracking-[0.11em] text-stamp">YOU</span>
                      )}
                    </span>
                    <span className="shrink-0 grid justify-items-end">
                      <span className={`font-mono text-name font-semibold tabular leading-tight ${signColor(r.net_ktc)}`}>
                        {fmtSigned(r.net_ktc)}
                      </span>
                      <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">
                        Trade value
                      </span>
                    </span>
                  </div>

                  <MetaLine>
                    <Meta label="Rank">{`${rankOf(r)} of ${rows.length}`}</Meta>
                    {r.production_started != null && (
                      <Meta label="Started" tone={signTone(r.production_started)}>
                        {fmtSigned(r.production_started, 1)}
                      </Meta>
                    )}
                    <Meta
                      label="Reg pts"
                      tone={signTone(r.production_regular)}
                    >
                      {fmtSigned(r.production_regular, 1)}
                    </Meta>
                    <Meta
                      label="Playoff pts"
                      tone={signTone(r.production_playoff)}
                    >
                      {fmtSigned(r.production_playoff, 1)}
                    </Meta>
                    <Meta label="Trade grade" tone={letterMetaTone(r.grade)}>{r.grade}</Meta>
                  </MetaLine>
                </EntryCard>
              );
            })}
          </CardList>
        </>
      )}
      </>
      )}
    </div>
  );
}
