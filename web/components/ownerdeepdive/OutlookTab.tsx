"use client";

import { OwnerDetailResp, PillarBreakdown } from "@/lib/types";
import { DivergeBar, fmtPts } from "@/components/RatingBars";
import { StageLadder } from "../furniture/StageLadder";
import { Panel } from "../furniture/Panel";
import { Row } from "../furniture/Row";
import { CardList, EntryCard, MetaLine, Meta } from "../furniture/EntryCard";
import { Card, CardHead } from "./ui";
import { SIGNAL_LABELS, ordinal } from "./util";
import { RoomsSection } from "./RosterHealthTab";
import { DraftNeedsSection, DraftSection } from "./FutureDraftTab";

/* ---------------------------------------------------------------------------
 * The Outlook tab IS the Assets pillar's page.
 *
 * There is no second model here. The competitive-window stage is a band on the
 * Franchise Rating composite (engine/gm_rating.py::rating_to_stage) and the
 * ledger below is the same Assets breakdown the Overview tab draws for the
 * whole grade — the previous Strength x Trajectory model was a second
 * arithmetic over substantially the same evidence, on an adjacent tab of one
 * page, free to disagree.
 *
 * Five sections: hero, the Assets ledger, draft needs, the rooms chart, draft.
 * ------------------------------------------------------------------------ */

const COUNT_WORDS: Record<number, string> = { 1: "one", 2: "two", 3: "three" };

const UNRATED_COPY: Record<string, string> = {
  first_season: "This is your first season, so there is no grade to build a window from yet.",
  new_franchise: "This franchise has no completed season yet, so there is no grade to build a window from.",
};

/** U+2212 MINUS for the grade letter, never the ASCII hyphen the API sends.
 *  Same substitution the methodology page makes (`prettyLetter`) — a hyphen
 *  beside a capital A reads as a word break at display sizes. Local rather
 *  than shared: that one is private to its file and this is three characters,
 *  and hoisting it would be a shared-helper import for a string replace. */
function prettyLetter(letter: string): string {
  return letter.replace(/-/g, "−");
}

/** The reader-legible form of each Assets signal's RAW value. Distinct from
 *  `Adds`, which is the signal's rating-point contribution — the two columns
 *  answer different questions and only the Adds column has to reconcile.
 *
 *  FIGURE AND RANK MUST DESCRIBE THE SAME QUANTITY. `Rank` comes from
 *  `_stamp_signal_ranks` (`api/app/services/franchise_redesign.py`), which
 *  ranks every owner on the signal's RAW value and nothing else. `Figure`
 *  therefore renders the raw too — a reader takes two adjacent cells in one
 *  row to be two readings of one thing.
 *
 *  `draft_capital` used to substitute the pick COUNT here, which is easier to
 *  hold in the head but is a DIFFERENT quantity from the one being ranked.
 *  Live on the reference league that shipped rows reading "11 picks · 6th"
 *  above "10 picks · 1st", and two owners both on "9 picks" ranked 5th and
 *  9th — arithmetic that looks broken and is not. Keeping the count would
 *  have meant a footnote saying the neighbouring rank means something else;
 *  the raw needs none. The count is not lost: the Draft section further down
 *  this same tab carries picks by season and by round. */
function figureFor(key: string, raw: number): string {
  switch (key) {
    case "roster_value_share":
      return `${(raw * 100).toFixed(1)}%`;
    case "young_core_share":
      return `${Math.round(raw * 100)}%`;
    case "draft_capital":
      // A Trade Value total, rounded — the exact quantity `Rank` ranks.
      return Math.round(raw).toLocaleString();
    default:
      return String(raw);
  }
}

/** A z-score with an explicit sign, U+2212 MINUS and two fixed decimals.
 *  Local rather than `./util`'s `signed()` on purpose, and named apart from it
 *  so the shadowing is gone: that one renders RATING POINTS (ASCII hyphen,
 *  rounded, thousands-separated), which is right in a ledger column and wrong
 *  for the hero's z's — a z needs both decimals to say anything, and this
 *  line sits in running prose where a hyphen beside a digit reads as a dash. */
function signedZ(z: number): string {
  return `${z >= 0 ? "+" : "−"}${Math.abs(z).toFixed(2)}`;
}

function Hero({ detail }: { detail: OwnerDetailResp }) {
  const fr = detail.franchise_rating;
  const ol = detail.outlook!;
  const assets = fr?.pillars?.assets;

  return (
    <Card>
      <div className="font-mono text-label uppercase tracking-widest text-dim">
        {assets && fr
          ? `Assets — ${Math.round(assets.weight * 100)}% of your ${prettyLetter(fr.letter)}`
          : "Assets"}
      </div>
      {assets ? (
        <p className="mt-1 font-display text-lead font-bold leading-tight tracking-[var(--track-lead)]">
          Your forward-looking half is worth {fmtPts(assets.contribution)} rating points.
        </p>
      ) : (
        <p className="mt-1 font-display text-lead font-bold leading-tight tracking-[var(--track-lead)]">
          No Assets grade yet.
        </p>
      )}
      <p className="mt-2 max-w-[68ch] text-figure leading-relaxed text-body">
        Results answer what you have done. Assets answer what you can still do — the same
        numbers the grade is built from, not a second model that can disagree with it.
      </p>

      <div className="mt-4">
        <StageLadder stage={ol.window} />
      </div>

      {ol.window == null ? (
        <p className="mt-2 font-mono text-label text-dim">
          {UNRATED_COPY[detail.unrated_reason ?? ""] ?? "No grade yet, so no window."}
        </p>
      ) : (
        <p className="mt-2 font-mono text-label text-dim">
          Derived, not separately modelled: Results z {signedZ(ol.results_z ?? 0)}, Assets z{" "}
          {signedZ(ol.assets_z ?? 0)}.{" "}
          {(ol.tilt ?? 0) > 0
            ? "Assets ahead of Results — the roster is ahead of the trophy case."
            : (ol.tilt ?? 0) < 0
              ? "Results ahead of Assets — the trophy case is ahead of the roster."
              : "Results and Assets are level."}
        </p>
      )}
    </Card>
  );
}

type LedgerRow = {
  key: string;
  label: string;
  figure: string;
  rank?: number;
  points: number;
};

/** Tone for a signed rating-point contribution. Deliberately NOT `./util`'s
 *  `tone()`, which this file could import: that one adds `font-semibold` to
 *  the non-zero cases, because it colours figures that stand alone. Every
 *  caller here already carries `font-semibold` from the cell's own class, so
 *  reusing `tone()` would either duplicate the weight or make the zero case
 *  the only one that is lighter than its neighbours. Colour only. */
function addTone(points: number): string {
  return points > 0 ? "text-pos-strong" : points < 0 ? "text-neg-strong" : "text-dim";
}

/* The five-column contract, written once and repeated verbatim on the head row
 * and every body row — that repetition IS the contract (see `Row`).
 *
 * DESKTOP ONLY. The whole grid lives inside `hidden min-[701px]:block`, so
 * there is no narrow variant of this template to get out of step with its
 * cells. The previous slice shipped a four-column ledger whose head hid three
 * columns at ≤700px while its body hid one, leaving three in-flow children
 * against a two-track template; grid's row-major placement wrapped the row's
 * whole payload into a 34px column, and jsdom lays out no grid so nothing
 * caught it. A five-column ledger is the same hazard with more ways to be
 * wrong, so it does not get a narrow variant at all — below 701px this is a
 * CardList, per Furniture rule 5. */
const LEDGER_COLS = "grid-cols-[150px_64px_48px_minmax(0,1fr)_52px]";

function AssetsLedger({ detail }: { detail: OwnerDetailResp }) {
  const assets: PillarBreakdown | undefined = detail.franchise_rating?.pillars?.assets;
  if (!assets) return null;

  const ranks = detail.outlook?.assets_signal_ranks ?? assets.signal_ranks ?? {};

  /* EVERY signal, unfiltered. The Overview tab drops signals under a 1-point
     noise floor; doing that here would break the sum the total row asserts. */
  const rows: LedgerRow[] = Object.entries(assets.signals).map(([k, s]) => ({
    key: k,
    label: SIGNAL_LABELS[k] ?? k,
    figure: figureFor(k, s.raw),
    rank: ranks[k],
    points: s.contribution,
  }));

  const scale = Math.max(1, ...rows.map((r) => Math.abs(r.points)));
  /* The total sums what is ON SCREEN, so the rows and the figure above them
     cannot disagree. gm_rating.py rounds each contribution independently, so
     that sum can land a point off the pillar's own figure — said out loud
     rather than papered over, exactly as OverviewTab's TotalRow does. */
  const sum = rows.reduce((a, r) => a + r.points, 0);
  const gap = assets.contribution - sum;
  const totalLabel = `Assets — ${COUNT_WORDS[rows.length] ?? String(rows.length)} signal${
    rows.length === 1 ? "" : "s"
  } × ${Math.round(assets.weight * 100)}% weight`;
  const roundingNote = `pillar above rounds to ${fmtPts(assets.contribution)}`;

  return (
    <Card>
      <CardHead title="What the Assets pillar is made of" />

      {/* Desktop — Signal · Figure · Rank · vs average · Adds. Five head
          children, five body children, five tracks, at the one width this
          block is visible. */}
      <div className="hidden min-[701px]:block">
        <Panel>
          <Row
            variant="head"
            data-testid="assets-ledger-head"
            className={`${LEDGER_COLS} items-center gap-2`}
          >
            <div>Signal</div>
            <div className="text-right">Figure</div>
            <div className="text-right">Rank</div>
            {/* `pl-3`, not renamed: at desktop, `Rank` (right-aligned) and
                `vs average` (left-aligned) sit 8px apart in identical
                mono-uppercase-dim styling and read as one run-on header,
                "RANK VS AVERAGE" — a live-browser QA pass caught this, since
                the data itself lands in the right columns and nothing in the
                test suite reads header spacing. The extra inset is scoped to
                this cell's own text, not the grid track, so body rows (the
                `DivergeBar`) keep their existing left edge. */}
            <div className="pl-3">vs average</div>
            <div className="text-right">Adds</div>
          </Row>
          {rows.map((r) => (
            <Row key={r.key} className={`${LEDGER_COLS} items-center gap-2`}>
              <span className="min-w-0 truncate font-display text-name font-bold tracking-[-0.024em] text-ink">
                {r.label}
              </span>
              <span className="text-right font-mono text-figure tabular text-dim">{r.figure}</span>
              <span className="text-right font-mono text-figure tabular text-dim">
                {r.rank != null ? ordinal(r.rank) : "—"}
              </span>
              <div>
                <DivergeBar points={r.points} scale={scale} />
              </div>
              <span
                data-testid="assets-add"
                className={`text-right font-mono text-figure font-semibold tabular ${addTone(r.points)}`}
              >
                {fmtPts(r.points)}
              </span>
            </Row>
          ))}
          {/* TWO columns, not five: a total has no figure, rank or bar of its
              own, so the label spans everything left of the sum. Copying the
              150px label track would put a sentence plus a rounding note into
              150px — the failure OverviewTab's TotalRow already paid for. */}
          <Row variant="total" cols="minmax(0,1fr) auto" className="py-2">
            <span className="min-w-0">
              <span className="font-display text-name font-bold tracking-[-0.024em] text-ink">
                {totalLabel}
              </span>
              {gap !== 0 && (
                <span className="mt-0.5 block font-mono text-label font-normal normal-case tracking-normal text-dim">
                  {roundingNote}
                </span>
              )}
            </span>
            <span
              data-testid="assets-total"
              className="whitespace-nowrap text-right font-mono text-figure font-semibold tabular text-ink"
            >
              {fmtPts(sum)}
            </span>
          </Row>
        </Panel>
      </div>

      {/* Below 701px — one EntryCard per signal plus a totals card, the same
          shape DraftSection and TradeStatTable use. Every column survives: the
          Adds figure is the headline, Figure and Rank become facts. The bar
          does not: it is a comparison across the rows of one grid, and a stack
          of cards has no shared axis to compare along — the figure it
          annotates is right there and carries the same sign.

          Its own testids, so a count assertion on the desktop ledger is not
          silently doubled by this render (jsdom applies no stylesheet, so both
          branches are in the tree). */}
      <CardList className="min-[701px]:hidden">
        {rows.map((r) => (
          <EntryCard key={r.key}>
            <div className="flex items-center justify-between gap-2">
              <span className="min-w-0 font-display text-name font-bold tracking-[-0.024em] text-ink">
                {r.label}
              </span>
              <span
                data-testid="assets-add-narrow"
                className={`whitespace-nowrap font-mono text-figure font-semibold tabular ${addTone(r.points)}`}
              >
                {fmtPts(r.points)}
              </span>
            </div>
            <MetaLine className="mt-2.5">
              <Meta label="Figure">{r.figure}</Meta>
              <Meta label="Rank">{r.rank != null ? ordinal(r.rank) : "—"}</Meta>
            </MetaLine>
          </EntryCard>
        ))}
        <EntryCard className="border-t-2 border-t-ink bg-surface-sunk">
          <div className="flex items-baseline justify-between gap-2">
            <span className="min-w-0 font-display text-name font-bold tracking-[-0.024em] text-ink">
              {totalLabel}
            </span>
            <span
              data-testid="assets-total-narrow"
              className="whitespace-nowrap font-mono text-figure font-semibold tabular text-ink"
            >
              {fmtPts(sum)}
            </span>
          </div>
          {gap !== 0 && (
            <p className="mt-1.5 font-mono text-label text-dim">{roundingNote}</p>
          )}
        </EntryCard>
      </CardList>
    </Card>
  );
}

export function OutlookTab({ detail }: { detail: OwnerDetailResp }) {
  if (!detail.outlook) return null;
  return (
    <div>
      <Hero detail={detail} />
      <AssetsLedger detail={detail} />
      <DraftNeedsSection outlook={detail.outlook} />
      <RoomsSection outlook={detail.outlook} />
      <DraftSection outlook={detail.outlook} draftSkill={detail.draft_skill} />
    </div>
  );
}
