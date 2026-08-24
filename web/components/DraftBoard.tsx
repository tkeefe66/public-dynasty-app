"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import type { DraftBoardOwner, DraftBoardPick, DraftBoardResp, OwnerRef } from "@/lib/types";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { Name } from "@/components/furniture/Name";
import { SortButton, type SortDir } from "@/components/furniture/SortButton";
import { GroupedHead } from "@/components/furniture/GroupedHead";
import { InfoTooltip } from "@/components/InfoTooltip";
import { startPct } from "@/lib/start-rate";
import { pickPositionInRound } from "@/lib/draft-pick-no";
import { sortRows, nextSort, sortDirFor, type SortState } from "@/lib/draft-sort";
import { pickGrid, pickGroups, ownerGrid, ownerGroups, COLUMN_DEFS } from "@/lib/draft-columns";
import { DraftPicksMobile } from "./DraftPicksMobile";
import { DraftGoingIn } from "./DraftGoingIn";

/** A non-identity header cell: the `SortButton` (or, for `Proj`, plain text —
 *  it has no sort key) plus its `InfoTooltip` definition. Every non-identity
 *  column on either ledger goes through this so a trigger can never ship
 *  without `COLUMN_DEFS` carrying a body for it — identity columns (Round·
 *  Pick, Owner, Player, `#`) never call this at all; their names are the
 *  whole explanation.
 *
 *  `aria-sort` lives HERE, on the `role="columnheader"` div, not on the
 *  `SortButton`'s `<button>` inside it — `aria-sort` is only valid on
 *  `columnheader`/`rowheader`/`gridcell` and is dropped by the accessibility
 *  layer on `role="button"`, which is exactly how this table shipped with no
 *  sort state announced to a screen reader at all (see `SortButton.tsx`'s own
 *  note). Callers pass the SAME `sortDirFor(sort, key)` value already going
 *  into the nested `SortButton`'s `sort` prop — the two must read one state,
 *  never two. Omit `sort` entirely for a non-sortable column (`Proj`): `"none"`
 *  claims sortability the column doesn't have, so the attribute must be
 *  absent, not `"none"` — matching `StandingsTable.tsx`'s own header cell. */
function DefinedHeader({
  defKey, children, sort,
}: { defKey: keyof typeof COLUMN_DEFS; children: ReactNode; sort?: SortDir }) {
  const def = COLUMN_DEFS[defKey];
  return (
    <div role="columnheader" aria-sort={sort} className="text-right">
      <span className="inline-flex items-center gap-1">
        {children}
        <InfoTooltip title={def.title} body={def.body} formula={def.formula} align="right" />
      </span>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Furniture — the league-wide draft board. Ledgers are `Panel`/`Row` (a solid
 * panel, so every row draws its own `--rule` top border — there's no striped
 * ground doing it for you anymore). This is what a redraft league sees on
 * draft night, when every pick sits at 0.0 production — so results and
 * grades are kept apart deliberately: picks always render (pick order,
 * owner, player, the ADP baseline), and the Total Points column only joins
 * once the class has actually played (`board.graded`). Showing a column of
 * zeros pre-production would read as a verdict on an unplayed class, which
 * is exactly the "null is not 0" contract this whole feature exists to
 * protect.
 *
 * Below 910px both the Owners table (`OwnersSection`) and the desktop Picks
 * table are replaced by `DraftPicksMobile` — cards grouped by owner, with the
 * flat pick order one tap away, and the owner card's `MetaLine` carrying the
 * whole graded owner run (rank, Points Above Round, Total, Start %, Regular,
 * Playoff, Toilet, Picks/Coverage, ADP +/-). It replaced a reflow that put
 * each pick's identity on its own rule and chunked the remaining stats
 * three-to-a-rule: ~108 rules for 36 picks, 3,880px at 390px, with the
 * OWNER reduced to a stat cell of equal weight to the baseline column on the
 * page whose whole question is who drafted what.
 *
 * The rule that survived that change, and constrains any future one: the
 * class's baseline (ECR or ADP, whichever it actually has), its signed delta,
 * Projected and Total Points are each a real column on desktop and must each
 * survive on a phone. Nothing is `display:none` with no alternate rendering.
 * This is the one screen on the whole site where a phone reader is the
 * primary audience (draft night), so losing a column below the breakpoint
 * isn't an acceptable tradeoff — see the report's fix-round-1 note. The
 * grouping buys its height back by DEFERRING picks behind a disclosure,
 * never by dropping a field from them.
 *
 * ONE BREAKPOINT, DELIBERATELY SHARED — NOT THE APP'S USUAL 701px. Both
 * `OwnersSection` and `PicksSection`'s desktop table gate at `min-[910px]`
 * (see `PicksSection`'s own docstring for the arithmetic that requires 910
 * rather than the app's usual 701px). They used to gate independently —
 * Owners at 701px, Picks at 870px — which opened a 701–869px band where the
 * Owners desktop table AND `DraftPicksMobile`'s `OwnerGroup` cards (which
 * carry the identical owner rollup) were both visible at once: every owner
 * figure rendered twice, in two different formats, on the same page. No data
 * was lost and nothing crashed — it just looked broken. The fix is not "pick
 * whichever gate is right" but "make both sections switch at the same width,
 * on purpose", so a phone reader always gets exactly one rendering of the
 * owner rollup. Do not lower either gate back to 701px without re-deriving
 * both breakpoints together — that is what caused this.
 * ------------------------------------------------------------------------ */

interface Props {
  leagueId: string;
  board: DraftBoardResp;
}

function ownerName(o?: OwnerRef | null, fallbackId?: string): string {
  return o?.owner_name ?? fallbackId ?? "Unknown";
}

/** PAR is `total − mean`, so a value can land in `(-0.05, 0)` — arithmetically
 *  zero once rounded to the one decimal these figures render at, but still
 *  negative as a float. Below this magnitude a value is treated as zero, per
 *  `EntryCard.tsx`'s house rule: "zero or an absent value is `--dim`, never
 *  invent a sign for zero." Without the clamp a `-0.0…` figure rendered a red
 *  "-0.0" — a sign on a number that reads, and is, zero. */
const ZERO_EPSILON = 0.05;

function signColor(n: number): string {
  if (Math.abs(n) < ZERO_EPSILON) return "text-dim";
  return n > 0 ? "text-pos-strong" : "text-neg-strong";
}

function fmtSigned(n: number, decimals: 0 | 1 = 0): string {
  if (Math.abs(n) < ZERO_EPSILON) return decimals === 1 ? "0.0" : "0";
  const mag = decimals === 1 ? n.toFixed(1) : Math.round(n).toLocaleString();
  return n > 0 ? `+${mag}` : mag;
}

/** A signed figure. Null survives as an em-dash — an owner/pick with no
 *  matched ADP is ungraded on this baseline, never a zero. */
function Signed({ value, decimals = 0 }: { value: number | null | undefined; decimals?: 0 | 1 }) {
  if (value == null) return <span className="text-dim">—</span>;
  return <span className={signColor(value)}>{fmtSigned(value, decimals)}</span>;
}

const VERDICT_META: Record<string, { label: string; cls: string }> = {
  hit: { label: "Hit", cls: "text-pos-strong" },
  average: { label: "Average", cls: "text-dim" },
  bust: { label: "Bust", cls: "text-neg-strong" },
};

/** Hit/Average/Bust, coloured mono text — never a chip. The word carries the
 *  meaning; the colour only restates it (the same licence `PastPicksTable`'s
 *  `Status` column runs on). An em-dash for a pick that carries no verdict
 *  (unranked, keeper, auction, or too-thin a cohort cell) even though the
 *  column itself is showing — a blank verdict is never a guess. */
function Verdict({ value }: { value?: string }) {
  const m = value ? VERDICT_META[value] : undefined;
  if (!m) return <span className="text-dim">—</span>;
  return <span className={`font-mono text-label uppercase tracking-[0.11em] ${m.cls}`}>{m.label}</span>;
}

/** `pick_no`, as round·position-within-round — `1.01`, `2.03` — not the
 *  flattened overall order, and NOT `round.slot`: `slot` is the team's draft
 *  seed, which only equals within-round position in odd rounds of a snake
 *  draft (`lib/draft-pick-no.ts::pickPositionInRound`). Two-tone: the round
 *  dim, the position in ink, so the halves separate without a second column.
 *  Tone, not hue, so this doesn't touch the no-colour-on-data rule.
 *  Zero-padded to two digits so a run of positions lines up. Shared with
 *  `DraftPicksMobile.tsx`'s own `PickNo` via the one exported helper, so the
 *  two surfaces cannot drift apart on the derivation. */
function PickNo({ round, slot, pick_no, picks_in_round }: {
  round: number; slot: number; pick_no: number; picks_in_round?: number;
}) {
  const within = pickPositionInRound(pick_no, round, slot, picks_in_round);
  return (
    <>
      <span className="text-dim">{round}.</span>
      <span className="text-ink">{String(within).padStart(2, "0")}</span>
    </>
  );
}

/** The pick's current standing with the drafting owner — coloured mono text,
 *  never a chip, matching `PastPicksTable.tsx`'s `Status` column exactly:
 *  the word carries the meaning, the colour only restates it. Trading a
 *  player away is a decision, not a failure, so Traded reads neutral, same
 *  tone as an unknown/pre-feature-cache status — never a guess, matching
 *  `Verdict`'s own em-dash fallback above. */
const STATUS_META: Record<string, { label: string; cls: string }> = {
  rostered: { label: "Rostered", cls: "text-pos-strong" },
  traded: { label: "Traded", cls: "text-dim" },
  dropped: { label: "Dropped", cls: "text-neg-strong" },
};

function Status({ status }: { status?: string }) {
  const m = status ? STATUS_META[status] : undefined;
  if (!m) return <span className="text-dim">—</span>;
  return <span className={`font-mono text-label uppercase tracking-[0.11em] ${m.cls}`}>{m.label}</span>;
}

/** Share of Total Points that came from the starting lineup.
 *
 *  Null — an em-dash — when nothing was scored, or when `total` is negative
 *  (a K/DEF pick can score negative in a started week; a ratio over a
 *  negative denominator is meaningless, not merely unknown). Shared with
 *  `DraftPicksMobile.tsx` and `ownerdeepdive/PastPicksTable.tsx` via
 *  `web/lib/start-rate.ts`, mirroring `start_rate.py`'s `total > 0` gate. */
function StartPct({ started, total }: { started?: number; total?: number }) {
  const pct = startPct(started, total);
  if (pct == null) return <span className="text-dim">—</span>;
  return <span>{pct}</span>;
}

/* ---------------------------------------------------------------------------
 * Sorting — accessors for `web/lib/draft-sort.ts::sortRows`.
 *
 * `startPct` above returns a formatted string ("62%") for display; sorting
 * needs the raw ratio, so `startRatio` mirrors its own `total > 0` gate
 * (`start_rate.py`) without going through string formatting.
 *
 * `Verdict` and `Status` are ORDINAL, not alphabetical — ranking each one as
 * a number lets `sortRows`'s existing numeric comparator (and its "nulls
 * last in both directions" rule) do the work, rather than a bespoke
 * comparator per column. An unlabelled verdict or a missing roster status
 * returns `null` — same "never guess" reading `Verdict`/`Status` already
 * render as an em-dash — which is exactly what pins it last regardless of
 * direction: "Inactive"/unlabelled is never the answer to "best" OR "worst".
 * ------------------------------------------------------------------------ */
function startRatio(started: number | undefined, total: number | undefined): number | null {
  if (total == null || total <= 0) return null;
  return (started ?? 0) / total;
}

const VERDICT_RANK: Record<string, number> = { hit: 3, average: 2, bust: 1 };
const STATUS_RANK: Record<string, number> = { rostered: 3, traded: 2, dropped: 1 };

/** `web/lib/draft-sort.ts`'s `SortState.key` for each sortable Picks column —
 *  `pick` is the flat draft order (`pick_no`), not the round·slot label. */
function pickSortValue(p: DraftBoardPick, key: string): string | number | null | undefined {
  switch (key) {
    case "pick": return p.pick_no;
    case "owner": return ownerName(p.owner, p.drafter_id);
    case "player": return p.full_name;
    case "ecr": return p.baseline;
    case "slot_delta": return p.baseline_delta;
    case "verdict": return p.verdict ? VERDICT_RANK[p.verdict] ?? null : null;
    case "total": return p.production_total;
    case "start_pct": return startRatio(p.production_started, p.production_total);
    case "gs": return p.games_started ?? 0;
    case "now": return p.roster_status ? STATUS_RANK[p.roster_status] ?? null : null;
    default: return null;
  }
}

/** `web/lib/draft-sort.ts`'s `SortState.key` for each sortable Owners
 *  column. `rank` reads a STATIC rank map, not the row's current on-screen
 *  position — the "#" badge is a fact about the owner (the backend's
 *  PAR/ADP-delta order), not a live index that should renumber as some other
 *  column gets sorted. Sorting ascending by `rank` reproduces that original
 *  order exactly.
 *
 *  `hit_bust` DOES now exist (the brief's original ninth column, shipped
 *  once the per-pick verdict was rolled up per owner) and sorts on `hit` —
 *  the leading figure the cell renders, per this table's own rule that the
 *  figure sorted by is one the board shows. `picks` never became a column of
 *  its own: it rides in the Owner cell, so there is nothing to sort it by
 *  independently. `adp`/`coverage` read `adp_total_delta` and
 *  `graded_picks`/`total_picks`, and are named for the data rather than the
 *  brief's literal names. */
/** How many of an owner's picks carry a verdict at all. Zero means the class
 *  is UNJUDGED, which is not the same as "hit nothing" — every surface that
 *  reads these counts branches on this rather than on `hit === 0`. */
function judgedCount(o: DraftBoardOwner): number {
  return (o.hit ?? 0) + (o.average ?? 0) + (o.bust ?? 0);
}

function ownerSortValue(
  o: DraftBoardOwner, key: string, rankOf: Map<string, number>,
): string | number | null | undefined {
  switch (key) {
    case "rank": return rankOf.get(o.user_id) ?? null;
    case "owner": return ownerName(o.owner, o.user_id);
    case "par": return o.points_above_round;
    case "total": return o.production_total;
    case "start_pct": return startRatio(o.production_started, o.production_total);
    case "regular": return o.production_regular ?? 0;
    case "playoff": return o.production_playoff ?? 0;
    case "toilet": return o.production_toilet ?? 0;
    // Null, not 0, when nothing this owner drafted could be judged — a class
    // with no verdicts is ungraded, and 0 would sort it among the owners who
    // genuinely hit nothing.
    case "hit_bust":
      return judgedCount(o) > 0 ? (o.hit ?? 0) : null;
    case "adp": return o.adp_total_delta;
    case "coverage": return o.total_picks > 0 ? o.graded_picks / o.total_picks : null;
    default: return null;
  }
}

/* ---------------------------------------------------------------------------
 * Season selector — the underline run (`SegmentControl.tsx`), scoped to this
 * board's own `seasons` list rather than the league's full year line.
 *
 * It used to carry the app's last sanctioned `overflow-x-auto`, because a long
 * dynasty chain's run of seasons pushed the whole document sideways on a phone
 * and nothing sets `overflow-x: hidden` globally. The run WRAPS, so that
 * reason expired and the guard's exception list is now empty.
 *
 * THIS IS A COPY OF THE CONTROL'S PAINT, AND THAT IS DELIBERATE — but it is
 * the copy that goes stale, so it is drawn from the same tokens and kept
 * visually identical on purpose. These stay `<Link>`s with `aria-current`:
 * each season is a URL, so this is NAVIGATION, not a toggle group, and
 * adopting SegmentControl's button/onChange contract would cost open-in-new-tab
 * and middle-click for no design gain. The "Season" whisper label is gone with
 * every other kicker — a run of four years does not need to be told it is
 * seasons.
 * ------------------------------------------------------------------------ */
function SeasonSelector({
  leagueId, seasons, current,
}: { leagueId: string; seasons: number[]; current: number }) {
  if (seasons.length <= 1) return null;
  return (
    <div className="mb-5 inline-flex flex-wrap items-center gap-x-4 gap-y-2">
      {seasons.map((s) => {
        const active = s === current;
        return (
          <Link
            key={s}
            href={`/league/${leagueId}/draft/${s}`}
            aria-current={active ? "true" : undefined}
            className={
              "relative whitespace-nowrap py-[3px] font-mono text-label uppercase tracking-[0.08em] no-underline " +
              "before:absolute before:-inset-x-[8px] before:-inset-y-[11px] before:content-[''] " +
              "after:absolute after:inset-x-0 after:-bottom-[3px] after:h-[2px] after:content-[''] " +
              (active
                ? "font-bold text-ink after:bg-stamp"
                : "font-normal text-dim after:bg-transparent hover:text-ink")
            }
          >
            {s}
          </Link>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Owners section — one line per owner: rank (in the order the backend already
 * sorted — Points Above Round first once graded, ADP total delta otherwise),
 * owner, then the graded production run, then ADP total delta and coverage
 * stated literally as "N of M" so a reader knows exactly what the number
 * covers rather than assuming every pick counted.
 *
 * Points Above Round leads the graded run because it's the figure the backend
 * sorts by (`engine/draft_par.py`): raw Total Points ranks draft POSITION —
 * whoever picked first tends to win — so showing only that beside the rank
 * put #1 above #3 on a worse-looking figure and read as a broken sort. PAR is
 * zero-sum within the class and rewards drafting well from a bad slot. The
 * rest of the five-metric run (Total Points, Start %, Regular, Playoff,
 * Toilet) rides alongside it, gated on the same `graded` flag the picks
 * ledger uses.
 *
 * Keepers and auction picks are shown in the ledger below but are not in any
 * figure here: they are not draft decisions to grade. An all-auction class
 * therefore has no owner rows at all, and this whole section is omitted
 * rather than rendered as an empty ledger — "results only, no grade".
 *
 * ADP +/- and Coverage are themselves conditional on `hasAdpColumns` — both
 * read off `adp_total_delta`, which is always null on a dynasty class (no
 * Sleeper market baseline for rookies; see the rookie-ECR fork in
 * `grader.py`). Rendering them unconditionally used to print "Coverage 0 of
 * 48" directly above the Picks ledger's 48 real ECR-graded rows — the
 * headline-equals-rows-beneath-it rule broken by two dead columns nobody
 * populates for dynasty. Four literal grid templates (graded × hasAdpColumns)
 * — Tailwind's JIT scanner needs each arbitrary-value class as literal text,
 * not string-built, the same idiom `PastPicksTable.tsx` uses for its own
 * conditional columns.
 *
 * DESKTOP ONLY (`hidden min-[910px]:block` — shared with `PicksSection`'s own
 * desktop table, not the app's usual 701px; see `DraftBoard`'s header
 * docstring for why the two sections deliberately switch together). Phase
 * 2 grew this table from 3 tracks to 8 with no breakpoint gate at all: on a
 * 390px phone the fixed columns alone (before the owner name gets anything)
 * outweigh the panel, `minmax(0,1fr)` collapses the name to 0px, and
 * `Panel`'s `overflow-hidden` then clips Playoff/Toilet and their headers
 * entirely — a manager opening this on draft night saw rank, an empty name
 * cell, and a truncated run, with no scroll affordance (the design system
 * retired `overflow-x-auto`). Below 910px this whole section is hidden, and
 * every figure it carries (rank, PAR, Total, Start %, Regular, Playoff,
 * Toilet, Picks/Coverage, ADP +/-) reappears in `DraftPicksMobile`'s
 * `OwnerGroup` card instead — see that component's docstring. Nothing here is
 * `display:none` with no alternate rendering; the alternate rendering is a
 * sibling component, not a sibling element, which is why it's DraftBoard's
 * job to omit the desktop table rather than OwnersSection's own CSS to hide
 * it invisibly.
 * ------------------------------------------------------------------------ */
/** `owners` arrives PRE-SORTED (`DraftBoard`'s `sortedOwners`) — this
 *  component renders it, it does not sort it itself. The sort STATE is owned
 *  by `DraftBoard`, not here, because the Owners ledger's mobile body
 *  (`DraftPicksMobile`'s `OwnerGroup` "By owner" view — see that file's own
 *  "THIS IS ALSO THE OWNERS SECTION NOW" docstring: below 910px it is the
 *  ONLY place the owner rollup is reachable, same breakpoint this desktop
 *  table hides at) is rendered by the sibling `PicksSection`, not by
 *  `OwnersSection`. One sorted array has to reach both, so the state that
 *  produces it has to live above both — same "one array feeds both bodies"
 *  rule already applied to the Picks ledger, just lifted one level because
 *  the two renderers here live in different components. `rankOf` is passed
 *  in too: it must be built from the ORIGINAL (pre-sort) order, so the "#"
 *  badge stays a fact about the owner rather than a live index that
 *  renumbers when some other column gets sorted. */
function OwnersSection({
  owners, graded, hasVerdicts, rankOf, sort, onSort,
}: {
  owners: DraftBoardOwner[];
  graded: boolean;
  hasVerdicts: boolean;
  rankOf: Map<string, number>;
  sort: SortState | null;
  onSort: (key: string, numeric: boolean) => void;
}) {
  if (owners.length === 0) return null;
  const hasAdpColumns = owners.some((o) => o.adp_total_delta != null);
  // Read off the board's own `has_verdicts` flag rather than re-derived from
  // these rows: it is the same gate the Picks ledger renders its Verdict
  // column behind, so the rollup column and the rows it counts appear and
  // disappear together. `hasAdpColumns` wins the template race — see
  // `OWNER_GRID_GRADED_VERDICT`.
  const showVerdicts = hasVerdicts && !hasAdpColumns;
  const gridArgs = { graded, hasAdpColumns, hasVerdicts };
  const grid = ownerGrid(gridArgs);
  const groups = ownerGroups(gridArgs);
  const headerCells = (
    <>
      <div role="columnheader" aria-sort={sortDirFor(sort, "rank")}>
        <SortButton sort={sortDirFor(sort, "rank")} onClick={() => onSort("rank", true)}>#</SortButton>
      </div>
      <div role="columnheader" aria-sort={sortDirFor(sort, "owner")}>
        <SortButton sort={sortDirFor(sort, "owner")} onClick={() => onSort("owner", false)}>Owner</SortButton>
      </div>
      {graded && (
        <>
          <DefinedHeader defKey="par" sort={sortDirFor(sort, "par")}>
            <SortButton sort={sortDirFor(sort, "par")} align="right" onClick={() => onSort("par", true)}>
              PAR
            </SortButton>
          </DefinedHeader>
          <DefinedHeader defKey="total" sort={sortDirFor(sort, "total")}>
            <SortButton sort={sortDirFor(sort, "total")} align="right" onClick={() => onSort("total", true)}>
              Total Points
            </SortButton>
          </DefinedHeader>
          <DefinedHeader defKey="start_pct" sort={sortDirFor(sort, "start_pct")}>
            <SortButton sort={sortDirFor(sort, "start_pct")} align="right" onClick={() => onSort("start_pct", true)}>
              Start
            </SortButton>
          </DefinedHeader>
          <DefinedHeader defKey="regular" sort={sortDirFor(sort, "regular")}>
            <SortButton sort={sortDirFor(sort, "regular")} align="right" onClick={() => onSort("regular", true)}>
              Regular
            </SortButton>
          </DefinedHeader>
          <DefinedHeader defKey="playoff" sort={sortDirFor(sort, "playoff")}>
            <SortButton sort={sortDirFor(sort, "playoff")} align="right" onClick={() => onSort("playoff", true)}>
              Playoff
            </SortButton>
          </DefinedHeader>
          <DefinedHeader defKey="toilet" sort={sortDirFor(sort, "toilet")}>
            <SortButton sort={sortDirFor(sort, "toilet")} align="right" onClick={() => onSort("toilet", true)}>
              Toilet
            </SortButton>
          </DefinedHeader>
        </>
      )}
      {graded && showVerdicts && (
        <DefinedHeader defKey="hit_bust" sort={sortDirFor(sort, "hit_bust")}>
          <SortButton sort={sortDirFor(sort, "hit_bust")} align="right" onClick={() => onSort("hit_bust", true)}>
            Hit/Bust
          </SortButton>
        </DefinedHeader>
      )}
      {hasAdpColumns && (
        <DefinedHeader defKey="adp" sort={sortDirFor(sort, "adp")}>
          <SortButton sort={sortDirFor(sort, "adp")} align="right" onClick={() => onSort("adp", true)}>
            ADP
          </SortButton>
        </DefinedHeader>
      )}
      {hasAdpColumns && (
        <DefinedHeader defKey="coverage" sort={sortDirFor(sort, "coverage")}>
          <SortButton sort={sortDirFor(sort, "coverage")} align="right" onClick={() => onSort("coverage", true)}>
            Cov
          </SortButton>
        </DefinedHeader>
      )}
    </>
  );
  return (
    <div className="hidden min-[910px]:block" data-testid="draft-owners-desktop">
      <Card>
        <CardHead title="Owners" />
        <Panel role="table" aria-label="Draft board owners">
          {groups ? (
            <GroupedHead cols={grid} groups={groups}>{headerCells}</GroupedHead>
          ) : (
            <Row role="row" variant="head" cols={grid}>{headerCells}</Row>
          )}
          {owners.map((o) => (
            <Row key={o.user_id} role="row" cols={grid}>
              <div role="cell" className="text-dim">{rankOf.get(o.user_id)}</div>
              {/* Picks rides HERE rather than in a column of its own. The
                  widest owners template already sits 2px under budget, and a
                  sixth figure could only be bought by trimming one that earns
                  its track or by raising the gate past 1024px viewports. As a
                  suffix it costs no track at all, and it says the same thing:
                  how big was this owner's class. Counted over every pick they
                  MADE, keepers included, so it equals the number of rows the
                  Picks ledger shows for them (and the mobile card's own
                  "Picks" Meta, which counts those rows directly). */}
              <div role="cell" className="flex min-w-0 items-baseline gap-2">
                <span className="min-w-0 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink">
                  {ownerName(o.owner, o.user_id)}
                </span>
                {(o.picks_made ?? 0) > 0 && (
                  <span className="shrink-0 font-mono text-label uppercase tracking-[var(--track-label)] text-dim">
                    {o.picks_made} {o.picks_made === 1 ? "pick" : "picks"}
                  </span>
                )}
              </div>
              {graded && (
                <>
                  <div role="cell" className="text-right font-semibold">
                    <Signed value={o.points_above_round} decimals={1} />
                  </div>
                  <div role="cell" className="text-right">{o.production_total.toFixed(1)}</div>
                  <div role="cell" className="text-right">
                    <StartPct started={o.production_started} total={o.production_total} />
                  </div>
                  <div role="cell" className="text-right">{(o.production_regular ?? 0).toFixed(1)}</div>
                  <div role="cell" className="text-right">{(o.production_playoff ?? 0).toFixed(1)}</div>
                  <div role="cell" className="text-right">{(o.production_toilet ?? 0).toFixed(1)}</div>
                </>
              )}
              {graded && showVerdicts && (
                <div role="cell" className="text-right tabular-nums">
                  {judgedCount(o) > 0 ? `${o.hit ?? 0} / ${o.bust ?? 0}` : "—"}
                </div>
              )}
              {hasAdpColumns && (
                <div role="cell" className="text-right"><Signed value={o.adp_total_delta} decimals={1} /></div>
              )}
              {hasAdpColumns && (
                <div role="cell" className="text-right">{o.graded_picks} of {o.total_picks}</div>
              )}
            </Row>
          ))}
        </Panel>
      </Card>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Picks ledger — pick order, owner, player + position, then the class's
 * baseline (ECR for a dynasty rookie class, ADP for redraft/keeper — whatever
 * `board.baseline_label` names it — plus its signed delta) when any pick
 * carries one, then Projected Points (only while the class is unplayed — see
 * below), then Total Points / Start % / GS once the class has played.
 *
 * PHASE 2.5 TRIM: Regular / Playoff / Toilet moved OFF the pick rows. The
 * board answers "who drafted well" — a per-manager question that belongs on
 * `OwnersSection`'s desktop table and `DraftPicksMobile`'s `OwnerGroup` card
 * (both keep the full five-metric run), not spread across dozens of pick rows
 * nobody scans. Projected Points is now gated `hasProjected && !board.graded`
 * — the two never coexist on a row: a preseason estimate is superseded the
 * moment the class has actually played, so it drops the instant Total Points
 * arrives rather than sitting stale beside it.
 *
 * Desktop (≥910px): one grid row per pick, every applicable column on it —
 * six literal templates covering hasBaseline × (graded | hasProjected |
 * neither), the "spell out every combination" idiom `PastPicksTable.tsx`
 * uses (Tailwind's JIT scanner needs the whole arbitrary-value class as
 * literal text, not string-built).
 *
 * Below 910px: identity (pick/player/position/keeper) on its own rule, then
 * the same baseline/delta/projected/production values reflow onto labelled
 * `Meta` cells — `PastPicksTable.tsx`'s technique verbatim. Owner isn't a
 * fixed desktop column width away from overflowing on its own, but it's
 * included in the mobile reflow too so the entry reads standalone without
 * needing the desktop row for context.
 *
 * A SECOND, HIGHER BREAKPOINT (`min-[910px]`, literal at both use sites
 * below), not the app's usual 701px. Panel content width is the viewport
 * minus `Shell`'s own horizontal padding (`px-3 sm:px-6 lg:px-8` — 48px at
 * this width: `sm` applies, `lg` does not, and `tailwind.config.ts` carries
 * no `screens` override) minus `Panel`'s 1px border on each side (2px). So
 * the REAL budget the templates below are checked against is `viewport −
 * 50px`, not the viewport itself — at the 910px gate that's 860px, not 910.
 * `DraftPicksMobile` covers every width below 910px and loses no field, so
 * nothing is lost by keeping this range wider than the app's other 701px
 * gates.
 *
 * `min-[910px]` is written as a literal, complete class string at both use
 * sites below rather than composed from a shared constant — Tailwind's JIT
 * scanner needs each arbitrary-value class as literal source text (the same
 * rule the six grid templates above follow), so a variable holding half a
 * class name would silently produce no CSS at all.
 *
 * WIDTH BUDGET: the gate was raised from 870 to 910 rather than trimming the
 * templates further, because the header re-cut (Treatment C, see
 * `draft-columns.ts`) had already pushed the two widest templates —
 * `GRID_PB_VERDICT` (854px minimum: 566px fixed tracks + 170px Player floor +
 * 90px of 9 gaps + 28px cell padding) and `OWNER_GRID_GRADED_ADP` (858px
 * minimum, same formula) — past the real 820px budget the OLD 870px gate
 * actually offered (`870 − 50`), both silently overflowing with Player
 * pinned at its 170px floor and no scroll affordance. Trimming another ~40px
 * out of seven numeric tracks would walk straight back into the header-
 * wrapping problem that re-cut had just fixed, so the gate moved instead: at
 * 910px the budget is 860px, which clears `GRID_PB_VERDICT` (854 ≤ 860, and
 * needs viewport ≥ 904 to fit at all) and `OWNER_GRID_GRADED_ADP` (858 ≤ 860,
 * needs viewport ≥ 908) with a few px of slack apiece. At exactly 910px,
 * `GRID_PB_VERDICT`'s Player track renders at 860 − 566 − 90 − 28 = 176px —
 * 6px above its own 170px floor and 12px clear of the live 2025 rookie
 * class's longest name+position row ("TreVeyon HendersonRB", 164px).
 * Verified by `web/tests/draft-columns.test.ts`'s width-gate suite, which
 * pins both widest-template numbers and asserts every template's minimum
 * fits the real 860px budget — not by a live preview route (there is no
 * `/preview` page in this repo).
 * ------------------------------------------------------------------------ */
/* Seven literals: hasBaseline × (graded | hasProjected | neither), plus one
   verdict variant. `graded` implies no Projected — a preseason estimate is
   superseded by what actually happened — so the two never coexist. A verdict
   requires production to judge (implies `graded`) AND a rookie-ECR baseline
   to judge it against (implies `hasBaseline`), so there is no
   no-baseline-with-verdict or unplayed-with-verdict template — the count goes
   six to seven, not eight. Spelled out because Tailwind's JIT scanner needs
   each complete arbitrary-value class as literal source text; an interpolated
   template silently loses its columns in a production build while every test
   passes. */
function PicksSection({
  board, owners, rankOf,
}: {
  board: DraftBoardResp;
  owners: DraftBoardOwner[];
  /** Threaded straight through to `DraftPicksMobile` — see its own
   *  docstring: rank is a fixed fact about the owner (`DraftBoard.tsx`'s
   *  `rankOf`, built from the pre-sort order), never the card's position in
   *  `owners`' current sort. */
  rankOf: Map<string, number>;
}) {
  const label = board.baseline_label ?? "";
  const hasBaseline = label !== "" && board.picks.some((p) => p.baseline != null);
  const hasProjected = board.picks.some((p) => p.projected_points != null);
  const hasVerdicts = board.has_verdicts ?? false;
  const gridArgs = { hasBaseline, hasProjections: hasProjected, graded: board.graded, hasVerdicts };
  const grid = pickGrid(gridArgs);
  const groups = pickGroups(gridArgs);
  const picks = board.picks;

  // Default sort is the natural draft order (`null` state) — the table never
  // opens pre-sorted on a metric. ONE sorted array feeds both the desktop
  // rows below and `DraftPicksMobile` — reordering only the desktop rows
  // would desynchronise the two, invisibly on desktop and wrong on a phone
  // (`SortButton.prompt.md`).
  const [sort, setSort] = useState<SortState | null>(null);
  const sorted = useMemo(() => sortRows(picks, sort, pickSortValue), [picks, sort]);

  function onSort(key: string, numeric: boolean) {
    setSort((cur) => nextSort(cur, key, numeric));
  }

  return (
    <Card>
      <CardHead title="Picks" />

      {/* Desktop — one rule per pick, every applicable column on it. Gated at
          910px, not the app's usual 701px — see the docstring above `pickGrid`
          for the arithmetic that requires it. */}
      <div className="hidden min-[910px]:block" data-testid="draft-picks-desktop">
        <Panel role="table" aria-label="Draft picks">
          {(() => {
            const headerCells = (
              <>
                <div role="columnheader" aria-sort={sortDirFor(sort, "pick")}>
                  <SortButton sort={sortDirFor(sort, "pick")} onClick={() => onSort("pick", true)}>Pick</SortButton>
                </div>
                <div role="columnheader" aria-sort={sortDirFor(sort, "owner")}>
                  <SortButton sort={sortDirFor(sort, "owner")} onClick={() => onSort("owner", false)}>Owner</SortButton>
                </div>
                <div role="columnheader" aria-sort={sortDirFor(sort, "player")}>
                  <SortButton sort={sortDirFor(sort, "player")} onClick={() => onSort("player", false)}>Player</SortButton>
                </div>
                {hasBaseline && (
                  <>
                    <DefinedHeader defKey="ecr" sort={sortDirFor(sort, "ecr")}>
                      <SortButton sort={sortDirFor(sort, "ecr")} align="right" onClick={() => onSort("ecr", true)}>
                        {label}
                      </SortButton>
                    </DefinedHeader>
                    <DefinedHeader defKey="slot_delta" sort={sortDirFor(sort, "slot_delta")}>
                      <SortButton sort={sortDirFor(sort, "slot_delta")} align="right" onClick={() => onSort("slot_delta", true)}>
                        Slot
                      </SortButton>
                    </DefinedHeader>
                  </>
                )}
                {hasVerdicts && (
                  <DefinedHeader defKey="verdict" sort={sortDirFor(sort, "verdict")}>
                    <SortButton sort={sortDirFor(sort, "verdict")} align="right" onClick={() => onSort("verdict", true)}>
                      Verdict
                    </SortButton>
                  </DefinedHeader>
                )}
                {hasProjected && !board.graded && (
                  // No `sort` passed — Proj has no sort key, so `DefinedHeader`
                  // leaves `aria-sort` off entirely rather than claiming
                  // sortability with `"none"`.
                  <DefinedHeader defKey="proj">Proj</DefinedHeader>
                )}
                {board.graded && (
                  <>
                    {/* "Total" — abbreviated so it fits its 66px column on one
                        line (Treatment C's `label + 33px chrome` re-cut, see
                        `draft-columns.ts`). "Total Points" wrapped here and left a
                        ragged baseline against ECR/Slot/Verdict/Start/GS's
                        single-line headers; the five-metric vocabulary permits
                        abbreviation, never renaming or reordering, and
                        `DraftPicksMobile.tsx`'s own mobile fact already uses this
                        exact abbreviation. The Owners table keeps the full
                        "Total Points" — its column is wider (108px) and never
                        wraps. */}
                    <DefinedHeader defKey="total" sort={sortDirFor(sort, "total")}>
                      <SortButton sort={sortDirFor(sort, "total")} align="right" onClick={() => onSort("total", true)}>
                        Total
                      </SortButton>
                    </DefinedHeader>
                    <DefinedHeader defKey="start_pct" sort={sortDirFor(sort, "start_pct")}>
                      <SortButton sort={sortDirFor(sort, "start_pct")} align="right" onClick={() => onSort("start_pct", true)}>
                        Start
                      </SortButton>
                    </DefinedHeader>
                    <DefinedHeader defKey="gs" sort={sortDirFor(sort, "gs")}>
                      <SortButton sort={sortDirFor(sort, "gs")} align="right" onClick={() => onSort("gs", true)}>
                        GS
                      </SortButton>
                    </DefinedHeader>
                  </>
                )}
                <DefinedHeader defKey="now" sort={sortDirFor(sort, "now")}>
                  <SortButton sort={sortDirFor(sort, "now")} align="right" onClick={() => onSort("now", true)}>
                    Now
                  </SortButton>
                </DefinedHeader>
              </>
            );
            return groups ? (
              <GroupedHead cols={grid} groups={groups}>{headerCells}</GroupedHead>
            ) : (
              <Row role="row" variant="head" cols={grid}>{headerCells}</Row>
            );
          })()}

          {sorted.map((p: DraftBoardPick) => (
            <Row key={`d-${p.pick_no}-${p.player_id}`} role="row" cols={grid}>
              <div role="cell" className="tabular-nums" data-testid="pick-no">
                <PickNo round={p.round} slot={p.slot} pick_no={p.pick_no} picks_in_round={p.picks_in_round} />
              </div>
              <div role="cell" className="min-w-0 truncate">{ownerName(p.owner, p.drafter_id)}</div>
              <div role="cell" className="min-w-0 truncate">
                <Name>{p.full_name}</Name>
                <span className="ml-1.5 font-mono text-label uppercase tracking-[0.1em] text-dim">{p.position}</span>
                {p.is_keeper && (
                  <span className="ml-1.5 font-mono text-label uppercase tracking-[0.1em] text-dim">· Keeper</span>
                )}
              </div>
              {hasBaseline && (
                <>
                  <div role="cell" className="text-right">
                    {p.baseline != null ? p.baseline.toFixed(1) : <span className="text-dim">—</span>}
                  </div>
                  <div role="cell" className="text-right"><Signed value={p.baseline_delta} decimals={1} /></div>
                </>
              )}
              {hasVerdicts && (
                <div role="cell" className="text-right"><Verdict value={p.verdict} /></div>
              )}
              {hasProjected && !board.graded && (
                <div role="cell" className="text-right">
                  {p.projected_points != null ? p.projected_points.toFixed(1) : <span className="text-dim">—</span>}
                </div>
              )}
              {board.graded && (
                <>
                  <div role="cell" className="text-right font-semibold">{p.production_total.toFixed(1)}</div>
                  <div role="cell" className="text-right">
                    <StartPct started={p.production_started} total={p.production_total} />
                  </div>
                  <div role="cell" className="text-right">{p.games_started ?? 0}</div>
                </>
              )}
              <div role="cell" className="text-right"><Status status={p.roster_status} /></div>
            </Row>
          ))}
        </Panel>
      </div>

      {/* Below 910px — grouped by owner, every field preserved. See
          `DraftPicksMobile` for why the grouping (and why the owner figure is
          a sum with a Coverage denominator, not an invented average), and the
          docstring above `pickGrid` for why this mirrors 910px, not the app's
          usual 701px. */}
      <div className="min-[910px]:hidden" data-testid="draft-picks-mobile">
        <DraftPicksMobile
          picks={sorted}
          owners={owners}
          rankOf={rankOf}
          graded={board.graded}
          hasBaseline={hasBaseline}
          baselineLabel={label}
          hasProjected={hasProjected}
          hasVerdicts={hasVerdicts}
        />
      </div>
    </Card>
  );
}

export function DraftBoard({ leagueId, board }: Props) {
  const owners = board.owners;
  // ONE gate for both ledgers: the Picks column and the Owners rollup that
  // counts it must appear and disappear together, so the flag is read here
  // and passed down rather than derived twice.
  const hasVerdicts = board.has_verdicts ?? false;

  // The "#" badge is a fact about the owner (the backend's PAR/ADP-delta
  // order), computed from the INCOMING order once, before any sort the user
  // applies — sorting by "Total", say, must not renumber it.
  const rankOf = useMemo(() => {
    const m = new Map<string, number>();
    owners.forEach((o, i) => m.set(o.user_id, i + 1));
    return m;
  }, [owners]);

  // ONE sorted Owners array, held HERE rather than inside `OwnersSection`,
  // because it has to feed two components that are siblings, not parent and
  // child: `OwnersSection`'s desktop table AND `PicksSection`'s
  // `DraftPicksMobile`, whose default "By owner" view is the owner rollup's
  // ONLY reachable form below 910px (`DraftPicksMobile.tsx`'s own "THIS IS
  // ALSO THE OWNERS SECTION NOW" docstring). Feeding `DraftPicksMobile` the
  // raw unsorted `board.owners` while `OwnersSection` sorted its own copy
  // desynchronised the two — invisible above 910px, permanently unsorted
  // below it. Same one-array rule already applied to the Picks ledger,
  // lifted one level because these two renderers don't share a parent any
  // lower than this.
  const [ownerSort, setOwnerSort] = useState<SortState | null>(null);
  const sortedOwners = useMemo(
    () => sortRows(owners, ownerSort, (o, key) => ownerSortValue(o, key, rankOf)),
    [owners, ownerSort, rankOf],
  );
  function onOwnerSort(key: string, numeric: boolean) {
    setOwnerSort((cur) => nextSort(cur, key, numeric));
  }

  return (
    <div>
      <SeasonSelector leagueId={leagueId} seasons={board.seasons} current={board.season} />
      <OwnersSection
        owners={sortedOwners}
        hasVerdicts={hasVerdicts}
        graded={board.graded}
        rankOf={rankOf}
        sort={ownerSort}
        onSort={onOwnerSort}
      />
      {/* `needs` is None (not []) whenever the league is ineligible for the
          roster reconstruction (redraft, first-season startup dynasty, or
          any season that isn't the newest gradeable class) — omit the panel
          entirely rather than rendering an empty one. `DraftGoingIn` itself
          repeats the empty-list half of this guard defensively. Rendered
          here, directly after Owners and before Picks — it is pre-draft
          context, and sat below 36 picks (unfindable) before the
          league-native-holes revision moved it. */}
      {board.needs != null && <DraftGoingIn needs={board.needs} owners={sortedOwners} />}
      <PicksSection board={board} owners={sortedOwners} rankOf={rankOf} />
    </div>
  );
}
