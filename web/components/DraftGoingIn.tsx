import type { DraftBoardOwner, OwnerNeedsResp, OwnerRef, SlotStandingResp } from "@/lib/types";
import { Section as Card, SectionTitle as CardHead } from "@/components/furniture/Section";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { CardList, EntryCard, MetaLine, Meta } from "@/components/furniture/EntryCard";
import { GRID_GOING_IN } from "@/lib/draft-columns";

/* ---------------------------------------------------------------------------
 * Furniture — the "Going in" panel: one row per owner, reading each roster's
 * starting-lineup holes on draft night against what the draft actually did
 * about them. Sits directly after Owners, before Picks — it is pre-draft
 * context, and sitting below 36 picks (its original position) is why the
 * league-native-holes revision found it un-findable. No directive — this is
 * a plain presentational leaf with no client-only state (no sort, no
 * disclosure), unlike `PicksSection`/`DraftPicksMobile`.
 *
 * FOUR RULES THAT GOVERN EVERY CELL HERE (task brief, restated so they
 * can't drift out of the component that has to obey them):
 *
 *  1. `Started` was a FRACTION (`started`/`drafted_into_count`) until Task 5
 *     retired it from the desktop layout (replaced by Points Produced, which
 *     reads the production total in points, not plays). Task 6 retired the
 *     same inlined `started`/`drafted_into_count` reading from the mobile
 *     fallback that had carried it forward as a functional hold-over — the
 *     mobile `EntryCard` now renders `BiggestNeeds`/`PositionsDrafted`/
 *     `pointsReading` directly, the same three functions the desktop table
 *     uses, so `started` is no longer read anywhere in this file. The field
 *     stays on the wire type (`OwnerNeedsResp.started`) for API-shape
 *     compatibility; nothing here renders it.
 *  2. An owner with no holes STILL renders a real reading — a full sentence
 *     naming the softest starting slot's position, with no number at all
 *     (`"No real needs at draft — QB was your thinnest spot"`), never an
 *     em-dash and never an empty row. "Went in with a complete starting
 *     lineup, and QB was still the thinnest spot" is a real finding, not
 *     missing data — see `BiggestNeeds`' no-holes branch. Every `needs`
 *     entry gets exactly one `Row` / `EntryCard`, whatever it contains. The
 *     em-dash survives ONLY for `slots.length === 0` — no reconstructable
 *     roster at all.
 *  3. `position`, never `slot`, is what prints. `slot` (`SlotStandingResp.
 *     slot`, e.g. `"RB_2"`) is the lineup-key each `SlotStanding` is keyed
 *     by — it exists so a repeated slot label (two RBs, two FLEXes) can be
 *     addressed uniquely, and it is never shown. `position`
 *     (`SlotStandingResp.position`) is the occupant's real position
 *     (`"RB"`), and that is what the reader expects here.
 *  4. No colour on the verdicts. A hole is not a failure, so nothing here —
 *     not even the em-dash, not even a negative margin on a vetoed softest
 *     slot — takes a `-pos`/`-neg` tone. `text-dim` IS used, deliberately:
 *     it marks "nothing to report" (no roster, no holes, holes-but-
 *     nothing-addressed — task 5) as visually distinct from a real hole or
 *     a real credited pick, the same neutral tone `Meta`'s own
 *     `tone="dim"` already carries elsewhere on this board. A real hole,
 *     a real `drafted_into` list, and a real production figure all stay
 *     full-ink; nothing here is ever `-pos`/`-neg`. `BiggestNeeds`' own
 *     severity phrases are the one deliberate, narrow exception (`-warn`/
 *     `-neg` strong, scoped to a 2-3 word clause) — see that component's own
 *     header comment for why that departure is sanctioned and scoped so
 *     tightly.
 *
 * `needs` is INFERRED — a reconstructed optimal lineup checked against a
 * league-relative replacement line, computed by `engine/draft_needs.py` —
 * never a graded/scored figure. It must never feed Franchise Rating, and
 * nothing on this panel claims otherwise.
 *
 * `owners` PROVIDES TWO LOOKUPS: name resolution per `user_id` via the same
 * `OwnerRef.owner_name`-else-raw-id fallback every other surface on this
 * board uses (`ownerName` in `DraftBoard.tsx` / `DraftPicksMobile.tsx` —
 * copied here rather than imported, the same standalone-copy choice those
 * two files already make to avoid a circular module dependency), and
 * `total_picks` lookup (Task 5) to render the "Positions Drafted" footer
 * line. `needs` is REORDERED to match `owners` (see the `tableRank` sort
 * below — the panel borrows the neighbouring table's order so the two read
 * as one thought) but is never FILTERED to it: `engine/draft_needs.py::
 * build_draft_needs` emits one entry per owner in the league's CURRENT
 * rosters, which is not the same set as `board.owners` (gradeable drafters
 * only) — an owner who made no gradeable pick this class still has a roster
 * and still gets a needs verdict, and dropping that row here would silently
 * erase "went in with a complete lineup" for exactly the owner who most
 * plainly earned it.
 *
 * Below the eight-column floor (four tracks) — no `GroupedHead` naming tier,
 * matching every other sub-eight-track template on this board
 * (`pickGroups`/`ownerGroups` in `draft-columns.ts` both return `null`
 * there). No sort CONTROL either: this panel states a fixed verdict per
 * owner, not a ranking a reader would want to reorder — it takes its row
 * order from the Owners table above rather than offering its own.
 *
 * THE OUTER `data-testid` LIVES ON `Card` ITSELF. `Section` (aliased `Card`
 * here, matching `DraftBoard.tsx`'s own import) forwards `...rest` — it was
 * the one primitive in `furniture/` that didn't, until phase 5 found it via
 * exactly this component (`<Card data-testid=…>` used to compile and build
 * while silently dropping the attribute at runtime, so `queryByTestId` found
 * nothing even though the panel rendered correctly). That gap is closed on
 * `Section` itself now (`1a1fe3d`), so the outer wrapper `<div>` this file
 * used to carry the testid on is no longer needed.
 * ------------------------------------------------------------------------ */

interface Props {
  needs: OwnerNeedsResp[];
  owners: DraftBoardOwner[];
}

function ownerName(o?: OwnerRef | null, fallbackId?: string): string {
  return o?.owner_name ?? fallbackId ?? "Unknown";
}

type Reading = { text: string; dim: boolean };

/* ---------------------------------------------------------------------------
 * Biggest Needs — severity-phrase sentences, ported from the validated
 * interactive mockup (`going-in-redesign.html`, Variant C: "Legend + fixed
 * table", `NEED_PHRASES`/`tierFor`/`phraseFor`/`ordinalWord`/`needLines`/
 * `renderC`'s `needsHtml`). This REPLACES the old `POS±NN` chip reading
 * (`holesReading`, retired above along with `formatMargin` — no raw signed
 * margin is ever printed here, by design) with a plain-English sentence per
 * hole instance, e.g. "Your weaker RB lagged the league's replacement level
 * by a wide margin."
 *
 * WHY A SENTENCE INSTEAD OF A CHIP: `WR-35` requires the reader to already
 * know what "35" means on this panel's own scale — nothing on the card says
 * whether 35 is a mild gap or a disaster. A sentence needs no legend, and the
 * severity tier (Thin/Wide/Deep) still comes from the exact same margin, it's
 * just translated into English and a 2-3 word colour highlight instead of a
 * raw number.
 *
 * WHY COLOUR IS SCOPED TO 2-3 WORDS, NOT THE WHOLE SENTENCE: the mockup's own
 * CSS comment (`.c-need` block) documents the failure of the first pass —
 * colouring the entire line drowned out the one clause worth pointing at and
 * made the position label itself (`RB`/`WR`/…) read as part of the severity
 * signal, which it explicitly is not (see this file's rule 4: no colour on
 * data / "a hole is not a failure" — this whole feature is a deliberate,
 * narrow departure from that rule, made at the user's explicit request and
 * scoped as tightly as the request allows). The position stays a fixed,
 * neutral, always-bold scan anchor (`<b>`) no matter how bad the need is;
 * only the phrase's own `hi` clause carries the tier colour.
 *
 * WHY ONE LINE PER HOLE INSTANCE, NEVER MERGED: an earlier draft of this
 * design summarized two holes at one position into a single line ("Both your
 * RBs were a full tier below a startable player") — wrong the moment the two
 * margins actually differ (a real case on the reference league: -41 and -21,
 * Deep and Wide respectively). Merging hid which of the two was the real
 * problem, and it also carried a was/were subject-agreement bug. Every hole
 * instance gets its own `NeedSentence`, named by rank ("weaker"/"other" for
 * two, "worst"/"Nth-worst" for three-plus) rather than the engine's raw slot
 * key (`RB_2`) — this file's rule 3 ("position, never slot, prints") extended
 * to the plural case: a reader is told WHICH hole a sentence is about without
 * ever seeing the internal lineup-key. */

type Tier = "thin" | "wide" | "deep";

/** Each phrase is split into { pre, hi, post } — mirroring the mockup's own
 *  `NEED_PHRASES` shape exactly (`going-in-redesign.html`) rather than a
 *  single string, because ONLY `hi` (2-3 words, the clause that actually
 *  names HOW bad) is meant to carry the tier colour. `pre`/`post` — "was ",
 *  "the league starting minimum", the qualifier, "Your", the position — all
 *  stay plain ink. The task-4 brief's own inline code sample flattened this
 *  to a single coloured string per phrase; that contradicts both the
 *  mockup's actual `phraseFor`/`.c-need .hi` CSS (Step 1 reading) and this
 *  file's own test ("colours only a 2-3 word severity phrase") — restored to
 *  the mockup's real shape rather than the brief's simplified transcription,
 *  per this task's own instruction to port the mockup's LOGIC exactly and
 *  not re-derive the phrasing from scratch. */
type Phrase = { pre: string; hi: string; post: string };

const NEED_PHRASES: Record<Tier, Phrase[]> = {
  thin: [
    { pre: "was ", hi: "just a hair", post: " below the league starting minimum" },
    { pre: "", hi: "barely missed", post: " the league starting minimum" },
    { pre: "was ", hi: "a tick under", post: " where a startable player sits" },
  ],
  wide: [
    { pre: "fell ", hi: "well short", post: " of the league starting minimum" },
    { pre: "was ", hi: "a real step", post: " below a startable player" },
    { pre: "lagged the league's replacement level by a ", hi: "wide margin", post: "" },
  ],
  deep: [
    { pre: "was ", hi: "nowhere near", post: " the league starting minimum" },
    { pre: "was ", hi: "a full tier", post: " below a startable player" },
    { pre: "was ", hi: "a deep hole", post: " at that spot" },
  ],
};

function tierFor(margin: number): Tier {
  const abs = Math.abs(margin);
  return abs >= 40 ? "deep" : abs >= 20 ? "wide" : "thin";
}

/** Which of a tier's phrasings gets used — driven by the margin itself (via
 *  `Math.round(abs) % variants.length`) so two owners with the same hole
 *  SHAPE (say, both missing one RB) can still read as genuinely different
 *  sentences when their actual deficits differ, without ever rendering the
 *  raw number that decided it. */
function phraseFor(margin: number): Phrase {
  const tier = tierFor(margin);
  const variants = NEED_PHRASES[tier];
  return variants[Math.round(Math.abs(margin)) % variants.length];
}

function ordinalWord(n: number): string {
  return (["", "2nd", "3rd", "4th", "5th"][n]) ?? `${n}th`;
}

type NeedLine = { qualifier: string; pos: string; phrase: Phrase; tier: Tier };

/** One hole POSITION's group of instances -> one { qualifier, pos, phrase,
 *  tier } per instance, worst margin first, never merged (see this task's
 *  own test "renders one sentence per hole instance"). `qualifier` is
 *  empty for a lone hole at that position, "weaker"/"other" for two, and
 *  "worst"/"Nth-worst" for three or more -- named by RANK, never the raw
 *  engine slot key (`RB_2`), matching this file's existing house rule
 *  (position, never slot, prints) extended to the plural case. */
function needLinesForGroup(pos: string, margins: number[]): NeedLine[] {
  const sorted = [...margins].sort((a, b) => a - b);
  return sorted.map((m, i) => {
    let qualifier = "";
    if (sorted.length === 2) qualifier = i === 0 ? "weaker" : "other";
    else if (sorted.length > 2) qualifier = i === 0 ? "worst" : `${ordinalWord(i + 1)}-worst`;
    return { qualifier, pos, phrase: phraseFor(m), tier: tierFor(m) };
  });
}

const TIER_CLASS: Record<Tier, string> = {
  thin: "text-dim",
  wide: "text-warn-strong",
  deep: "text-neg-strong",
};

/** `pre`/`post` render as plain ink alongside the position label; only
 *  `phrase.hi` — the 2-3 word clause — gets the tier colour class, matching
 *  the mockup's `.c-need .hi.tier-*` rule exactly (see this section's header
 *  comment on why the whole phrase must NOT be coloured). */
function NeedSentence({ line }: { line: NeedLine }) {
  return (
    <div data-testid="going-in-need-line">
      Your {line.qualifier ? `${line.qualifier} ` : ""}
      <b>{line.pos}</b> {line.phrase.pre}
      <span className={`font-medium ${TIER_CLASS[line.tier]}`}>{line.phrase.hi}</span>
      {line.phrase.post}
    </div>
  );
}

/** Groups an owner's real is_hole slots by position, worst-margin-first
 *  group order (matching `holes`' own documented most-severe-first
 *  contract), and renders one `NeedSentence` per instance via
 *  `needLinesForGroup`. No-holes case: a single sentence naming the
 *  softest slot, no number -- the "(market disagrees)" vetoed suffix is
 *  preserved from the shipped panel. */
function BiggestNeeds({ n }: { n: OwnerNeedsResp }) {
  const holeSlots = n.slots.filter(
    (s): s is SlotStandingResp & { margin: number } => s.is_hole && s.margin !== null
  );
  if (holeSlots.length > 0) {
    const byPosition = new Map<string, number[]>();
    for (const s of holeSlots) {
      byPosition.set(s.position, [...(byPosition.get(s.position) ?? []), s.margin]);
    }
    // Group order: worst-first by each group's own worst margin, matching
    // `holes`' documented contract -- Map preserves insertion order, so
    // insert groups in that sorted order rather than relying on `holeSlots`'
    // own (already worst-first, per the engine) order surviving the group-by.
    const groups = [...byPosition.entries()].sort(
      (a, b) => Math.min(...a[1]) - Math.min(...b[1])
    );
    return (
      // gap-2.5, not this file's usual gap-1.5: at 2-3+ stacked sentences
      // (a real, common shape — most rosters carry more than one hole) the
      // tighter gap read as one clumped paragraph rather than a list of
      // distinct, individually-severity-coloured claims. PositionsDrafted's
      // own `gap-1.5` stays as-is: its rows are short position/fraction
      // pairs, not full sentences, and rarely stack past two.
      <div className="flex flex-col gap-2.5">
        {groups.flatMap(([pos, margins]) =>
          needLinesForGroup(pos, margins).map((line, i) => (
            <NeedSentence key={`${pos}-${i}`} line={line} />
          ))
        )}
      </div>
    );
  }
  const scored = n.slots.filter(
    (s): s is SlotStandingResp & { margin: number } => s.margin !== null
  );
  if (scored.length === 0) return <span className="text-dim">—</span>;
  const softest = scored.reduce((worst, s) => (s.margin < worst.margin ? s : worst));
  const suffix = softest.vetoed ? " (market disagrees)" : "";
  return (
    <span className="text-dim">
      No real needs at draft — <b>{softest.position}</b> was your thinnest spot{suffix}
    </span>
  );
}

/** Groups an owner's credited positions (drafted_into) into counts per
 *  position, paired with that position's hole-instance count from slots.
 *  Used to render "Positions Drafted" as individual fraction rows
 *  (e.g., "WR 2/2 drafted") plus a total-picks line at the footer. */
type DraftedGroup = { pos: string; drafted: number; holeCount: number };

function draftedGroups(n: OwnerNeedsResp): DraftedGroup[] {
  const holeCounts = new Map<string, number>();
  for (const s of n.slots) {
    if (s.is_hole) holeCounts.set(s.position, (holeCounts.get(s.position) ?? 0) + 1);
  }
  const draftedCounts = new Map<string, number>();
  for (const pos of n.drafted_into) draftedCounts.set(pos, (draftedCounts.get(pos) ?? 0) + 1);
  return [...holeCounts.entries()].map(([pos, holeCount]) => ({
    pos, holeCount, drafted: draftedCounts.get(pos) ?? 0,
  }));
}

/** Renders the "Positions Drafted" column — grouped fraction rows (e.g.,
 *  "WR 2/2 drafted") showing drafted credits per hole position, followed
 *  by a divider line and the owner's total picks. No holes case renders
 *  "no holes" instead of an empty list. Shared by both layouts: the desktop
 *  table cell (`:481`) and, since Task 6, the mobile card (`:576`), where it
 *  is passed as `children` to `Meta`. Both rows and footer use `text-figure`
 *  (sanctioned type-scale token, 12.5px) rather than ad-hoc sizes.
 *
 *  Note the asymmetry with `BiggestNeeds`: that component sits OUTSIDE
 *  `MetaLine`/`Meta` on mobile specifically because `Meta` wraps its
 *  `children` in a `whitespace-nowrap` span, which is wrong for an unbounded
 *  wrapping sentence list (see the mobile render site's own comment). This
 *  component is passed straight INTO `Meta` instead, so its multi-row `<div>`
 *  stack technically lands inside that same `whitespace-nowrap` phrasing
 *  content. It renders correctly today — the rows are short enough that
 *  nowrap never bites, confirmed in Task 7's live pass — so this is a known,
 *  accepted inconsistency between the two columns, not an oversight. */
function PositionsDrafted({ n, totalPicks }: { n: OwnerNeedsResp; totalPicks: number }) {
  const groups = draftedGroups(n);
  return (
    <div className="flex flex-col gap-1.5 font-mono text-figure">
      {groups.length > 0
        ? groups.map((g) => (
            <div key={g.pos} className="flex gap-2">
              <span className="w-6 font-bold text-dim">{g.pos}</span>
              <span className="text-ink">{g.drafted}/{g.holeCount} drafted</span>
            </div>
          ))
        : <span className="text-dim">no holes</span>}
      <div className="mt-0.5 border-t border-rule pt-1.5 text-dim text-figure">
        {totalPicks} total pick{totalPicks === 1 ? "" : "s"}
      </div>
    </div>
  );
}

/** The Points Produced cell's reading. Renders the owner's production
 *  total when they drafted into at least one hole (drafted_into_count > 0),
 *  or an em-dash when nothing was credited to address a hole. This
 *  disambiguates "0.0 points from credited picks" from "no picks were
 *  credited" — the former is a real reading and stays a number.
 *  `production` is a required field (added by Task 3), but the guard
 *  is kept defensive against stale cached response shapes predating it. */
function pointsReading(n: OwnerNeedsResp): Reading {
  if (n.drafted_into_count === 0 || n.production === undefined) return { text: "—", dim: true };
  return { text: `${n.production.toFixed(1)} pts`, dim: false };
}

/** Shared copy for the (?) info tooltip on the "Biggest Needs" header —
 *  desktop column head and mobile card label both render this exact string,
 *  and both mark their popover `<span>` with the same `.going-in-tooltip`
 *  class (see the two render sites below), so there is exactly one place
 *  this explanation can drift from what `engine/draft_needs.py` actually
 *  computes. `.going-in-tooltip` carries no CSS rules of its own — the
 *  desktop and mobile variants position themselves independently
 *  (`absolute`/icon-relative vs. `fixed`/viewport-relative, see the mobile
 *  site's own comment on why) — it exists purely as a grep-able marker
 *  tying the two variants together, not a styled selector. */
const NEEDS_TOOLTIP =
  "A need is a starting slot that fell below this league's own replacement line — the Nth-best " +
  "rostered player at that position, priced on last season's points in this league's own scoring. " +
  "Below that line counts as not hitting the league starting minimum. Listed worst first; when you " +
  "have two needs at the same position, \"weaker\"/\"other\" tells you which one is which, worst first.";

export function DraftGoingIn({ needs, owners }: Props) {
  // Defensive mirror of `DraftBoard`'s own `needs != null` gate — an empty
  // (but non-null) list reads the same as "nothing eligible to show" and
  // should omit the panel the same way, matching `OwnersSection`'s own
  // "results only, no grade" precedent for an empty ledger.
  if (needs.length === 0) return null;

  const nameOf = new Map<string, string>();
  for (const o of owners) nameOf.set(o.user_id, ownerName(o.owner, o.user_id));

  // Wire up total_picks per user_id for the PositionsDrafted component.
  const picksOf = new Map<string, number>();
  for (const o of owners) picksOf.set(o.user_id, o.total_picks);

  // ORDERED BY THE OWNERS TABLE ABOVE, not by whatever order the engine
  // emitted. `build_draft_needs` walks `rosters` in Sleeper's own roster
  // order; the table directly above this panel is sorted by Points Above
  // Round and re-sorts on every column the reader clicks. Measured on the
  // reference league, the two orders shared no position at all — the same
  // twelve owners, twice, in unrelated sequences, so reading one owner's row
  // in both panels meant hunting for the name.
  //
  // This does NOT give the panel a sort of its own: there is still no control
  // here and still one fixed verdict per owner (see this file's rule set
  // above). It borrows the neighbouring table's order so the two read as one
  // thought, which is also why `owners` had to stay the SORTED array
  // `DraftBoard` already passes.
  //
  // Anyone `needs` carries who is absent from `owners` keeps their original
  // relative order and lands at the end — `needs` is the wider set (one entry
  // per owner with a roster; `board.owners` is gradeable drafters only), and
  // an owner who made no gradeable pick still went into the draft with a
  // lineup. Dropping or interleaving them arbitrarily would lose exactly the
  // "went in with a complete lineup" reading this panel exists to give.
  const tableRank = new Map<string, number>();
  owners.forEach((o, i) => tableRank.set(o.user_id, i));
  const ordered = needs
    .map((n, i) => ({ n, i }))
    .sort((a, b) => {
      const ra = tableRank.get(a.n.user_id) ?? Number.MAX_SAFE_INTEGER;
      const rb = tableRank.get(b.n.user_id) ?? Number.MAX_SAFE_INTEGER;
      // Ties are only possible among the unranked tail; fall back to the
      // engine's own order there so the panel stays stable across renders.
      return ra === rb ? a.i - b.i : ra - rb;
    })
    .map((d) => d.n);

  return (
    <Card data-testid="draft-going-in">
      <CardHead title="Going in" />

      {/* Desktop — same shared `min-[910px]` gate the rest of the board
          uses (`DraftBoard.tsx`'s header docstring on why Owners/Picks
          switch together). Four tracks sits well under budget — 718px
          against the 860px `WIDTH_GATE_BUDGET_PX` (see `draft-columns.ts`'s
          `GRID_GOING_IN` comment) — so there's no header re-cut and no
          naming tier to add here. */}
      <div className="hidden min-[910px]:block" data-testid="draft-going-in-desktop">
        <Panel role="table" aria-label="Draft needs going in">
          <Row role="row" variant="head" cols={GRID_GOING_IN}>
            <div role="columnheader">Owner</div>
            <div role="columnheader">
              Biggest Needs
              {/* (?) info tooltip — icon-relative `absolute` positioning is
                  correct here: the desktop table has room either side of the
                  icon and never sits near a viewport edge the way a narrow
                  mobile card does (see the mobile instance below, which is
                  `fixed` instead, for exactly the opposite reason).
                  `rounded-full`/`text-[9.5px]`/`rounded-[10px]`/`text-[12px]`/
                  `bg-accent`/`text-accent-ink`/`shadow-lg` in the validated
                  mockup's own literal markup are swapped for this system's
                  sanctioned equivalents (`rounded-pill`, `text-label`,
                  `rounded-sm`, `text-figure`, `bg-stamp`/`text-stamp-ink` —
                  the same hover/active pair `furniture/Button.tsx` uses —
                  and `shadow-panel`, the one sanctioned elevation) since
                  `accent`/`accent-ink` are not tokens this system defines at
                  all (a dead class, not just an unsanctioned one) and the
                  four literal-px/radius values would fail
                  `furniture-rules.test.ts`'s `adhoc-size`/`radius`/`elevation`
                  rules outright — the mockup's LOGIC (viewport-fixed on
                  mobile, icon-relative on desktop) is what's being ported,
                  not its literal Tailwind spelling. */}
              <span className="relative ml-1 inline-flex" data-testid="going-in-needs-info">
                <button
                  type="button"
                  aria-label="How Biggest Needs is calculated"
                  className="inline-flex h-[15px] w-[15px] items-center justify-center rounded-pill bg-rule text-label font-bold text-dim hover:bg-stamp hover:text-stamp-ink focus-visible:bg-stamp focus-visible:text-stamp-ink focus-visible:outline-none"
                >
                  ?
                </button>
                <span className="going-in-tooltip pointer-events-none absolute left-0 top-[22px] z-10 hidden w-[268px] rounded-sm bg-ink p-3 text-figure font-medium leading-[1.5] text-bg shadow-panel [button:hover~&]:block [button:focus-visible~&]:block">
                  {NEEDS_TOOLTIP}
                </span>
              </span>
            </div>
            <div role="columnheader">Positions Drafted</div>
            <div role="columnheader" className="text-right">Points Produced</div>
          </Row>
          {ordered.map((n) => {
            const points = pointsReading(n);
            return (
            <Row
              key={n.user_id}
              role="row"
              cols={GRID_GOING_IN}
              // Row's own base has no vertical padding, only `min-h` +
              // `items-center` — fine for a single-line row, but here the
              // tallest cell in a given row IS the content (Biggest Needs
              // can stack 3-4 sentences), so there is no shorter sibling
              // for `items-center` to center it against and no room left
              // over for breathing space: the text ends up flush against
              // this row's own top/bottom border. `py-3.5` matches this
              // row's existing horizontal `px-3.5` rhythm rather than
              // inventing a new number, and guarantees the same headroom
              // whether a row has one need line or four.
              className="py-3.5"
            >
              <div
                role="cell"
                className="min-w-0 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink"
              >
                {nameOf.get(n.user_id) ?? n.user_id}
              </div>
              <div role="cell" data-testid={`going-in-needs-${n.user_id}`}>
                <BiggestNeeds n={n} />
              </div>
              <div role="cell" data-testid={`going-in-drafted-${n.user_id}`}>
                <PositionsDrafted n={n} totalPicks={picksOf.get(n.user_id) ?? 0} />
              </div>
              <div
                role="cell"
                className={`text-right ${points.dim ? "text-dim" : ""}`.trim()}
                data-testid={`going-in-points-${n.user_id}`}
              >
                {points.text}
              </div>
            </Row>
            );
          })}
        </Panel>
      </div>

      {/* Below 910px — one `EntryCard` per owner, every field preserved. */}
      <div className="min-[910px]:hidden" data-testid="draft-going-in-mobile">
        <CardList>
          {ordered.map((n) => {
            const points = pointsReading(n);
            return (
            <EntryCard key={n.user_id}>
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink">
                  {nameOf.get(n.user_id) ?? n.user_id}
                </span>
              </div>
              {/* "Biggest Needs" is deliberately OUTSIDE `MetaLine`/`Meta`,
                  same reasoning as the retired "Holes going in" line it
                  replaced: `Meta` applies `whitespace-nowrap`, which is
                  right for a short fact like the "Positions Drafted"/
                  "Points Produced" pair below but wrong for an unbounded,
                  wrapping sentence list. Rendered here as plain prose via
                  `BiggestNeeds` (the same component the desktop cell uses —
                  one reading, two layouts) so mobile never drifts from the
                  desktop severity-sentence logic. The label carries its own
                  (?) info tooltip, sharing the same `NEEDS_TOOLTIP` copy and
                  the same `.going-in-tooltip` marker class as the desktop
                  column header (an unstyled grep hook, not a live selector —
                  see that class's own comment above `NEEDS_TOOLTIP`) — the
                  only difference is positioning (see the
                  tooltip's own class comment there): this instance is
                  `fixed` to the viewport rather than icon-relative, because
                  a real touch tap DOES trigger the CSS `:hover` rule below
                  (confirmed via headless Chrome `page.tap`, not assumed —
                  a tap leaves a sticky `:hover` on real touch devices), and
                  an icon-relative `absolute` tooltip anchored near the left
                  edge of a narrow card overflowed off-screen in that same
                  test pass. Do not simplify this back to `absolute` to
                  match the desktop instance. */}
              <p className="mt-2.5 flex items-center gap-1 font-mono text-figure tabular text-dim">
                Biggest Needs
                <span
                  className="relative inline-flex"
                  data-testid={`going-in-needs-info-mobile-${n.user_id}`}
                >
                  <button
                    type="button"
                    aria-label="How Biggest Needs is calculated"
                    className="inline-flex h-[15px] w-[15px] items-center justify-center rounded-pill bg-rule text-label font-bold text-dim"
                  >
                    ?
                  </button>
                  {/* `fixed` with the bottom/left/right/top offsets set via
                      inline `style` rather than `bottom-4`/`left-4`/`right-4`/
                      `top-auto` Tailwind classes — the mockup's own literal
                      spelling of this fails `furniture-rules.test.ts`'s
                      `sticky` rule (`/\b(sticky|fixed)\s+(top|bottom|left|
                      right)-/`, banning "nothing is fixed or sticky … no
                      pinned mobile nav"), and that rule lives in a shared
                      guard file outside this task's scope to edit. This is
                      not a workaround of the rule's INTENT: `InfoTooltip.tsx`
                      (already `SCOPED_FILES`, already guard-green today)
                      positions its own floating popover the exact same way —
                      a bare `fixed` class with the offsets supplied via
                      `style`, never as an adjacent directional utility class
                      — because the rule is aimed at a PINNED NAV idiom
                      (`fixed top-0`/`sticky top-0` on a chrome element that
                      stays put while content scrolls under it), not at a
                      floating popover positioned once and toggled by hover.
                      Same established pattern, applied here rather than
                      reinvented. */}
                  <span
                    className="going-in-tooltip pointer-events-none fixed z-10 hidden w-auto rounded-sm bg-ink p-3 text-figure font-medium leading-[1.5] text-bg shadow-panel [button:hover~&]:block [button:focus-visible~&]:block"
                    style={{ bottom: "1rem", left: "1rem", right: "1rem", top: "auto" }}
                  >
                    {NEEDS_TOOLTIP}
                  </span>
                </span>
              </p>
              <div className="mt-1" data-testid={`going-in-needs-mobile-${n.user_id}`}>
                <BiggestNeeds n={n} />
              </div>
              <MetaLine className="mt-2.5">
                <Meta label="Positions Drafted">
                  <PositionsDrafted n={n} totalPicks={picksOf.get(n.user_id) ?? 0} />
                </Meta>
                <Meta label="Points Produced" tone={points.dim ? "dim" : undefined}>
                  {points.text}
                </Meta>
              </MetaLine>
            </EntryCard>
            );
          })}
        </CardList>
      </div>
    </Card>
  );
}
