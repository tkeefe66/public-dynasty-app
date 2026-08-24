import type { ReactNode } from "react";
import Link from "next/link";
import { DashboardResp, LatestTrade } from "@/lib/types";
import { fmtDate, fmtDateShort } from "@/lib/format-date";
import { tradeHeadline, pointsReading, type PointsReading } from "@/lib/trade-lead";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";

interface Props {
  data: DashboardResp;
  leagueId: string;
}

/* ---------------------------------------------------------------------------
 * Agate — the lead (design_handoff_agate/DESIGN.md § "Named rules" —
 * "The Lead Is Rules, Not A Box"; README § "League dashboard"; Dynasty Directions.dc.html
 * Fig. 2a.1 + Fig. 2a.4). ONE component, a fixed skeleton — kicker left,
 * phase note right, headline, body, a three-cell ruled figure strip below —
 * and only the *source* changes with the league's calendar phase, so the
 * page never reflows across the season. Never collapsible.
 * ------------------------------------------------------------------------ */

interface LeadContent {
  kicker: string;
  phaseNote: string;
  headline: string;
  body: ReactNode;
  href?: string;
  /** Failure Is A Headline / empty-state action — a separate ink button
   *  below the body, not a link folded into the prose (DESIGN.md §
   *  "Named rules"; `Agate System.dc.html` §07 Fig. 7.4). */
  actionHref?: string;
  actionLabel?: string;
  cells: FigureCell[];
}

function fmtSigned(n: number, decimals: 0 | 1 = 0): string {
  const mag = decimals === 1 ? n.toFixed(1) : Math.round(n).toLocaleString();
  return n > 0 ? `+${mag}` : mag; // negatives already carry "-" from toFixed/toLocaleString
}

/** A cell with nothing to print yet. `text` is what the cell's aria-label
 *  says — an em dash announces as nothing (or as "em dash"), which is worse
 *  than silence. */
const NO_FIGURE = <span className="text-dim">—</span>;
const NO_FIGURE_TEXT = "not available";

/** The POINTS cell's figure as a plain string, for the aria-label. */
function pointsText(reading: PointsReading): string {
  return reading.kind === "unscored"
    ? NO_FIGURE_TEXT
    : `${reading.left} vs ${reading.right}`;
}

/* ---------------------------------------------------------------------------
 * Trade of the week — the offseason source, and the draft-phase fallback
 * (see the work order: no drafted-picks payload exists yet on the dashboard,
 * so the draft phase reuses this source with a draft-scoped kicker/phase
 * note rather than inventing pick data). Reuses the existing headline-trade
 * selection (biggest Trade Value swing in the window) that the pre-Agate
 * HeadlineMoves already surfaced.
 * ------------------------------------------------------------------------ */
function tradeOfWeekContent(
  data: DashboardResp,
  leagueId: string,
  kicker: string,
  phaseNote: string,
): LeadContent {
  const trade: LatestTrade | undefined = (data.headline_trades ?? [])[0];

  if (!trade) {
    const yearParam = data.selected_year == null ? "all" : String(data.selected_year);
    const allTradesHref = `/league/${leagueId}?tab=trades&year=${yearParam}&lens=${data.selected_lens}`;
    return {
      kicker,
      phaseNote,
      headline:
        data.selected_year === "all" || data.selected_year == null
          ? "No trades yet."
          : `No trades in ${data.selected_year}.`,
      body: "When a trade lands, its swing shows up here first.",
      actionHref: allTradesHref,
      actionLabel: "Browse trades",
      cells: [
        { label: "Value", value: NO_FIGURE, text: NO_FIGURE_TEXT },
        { label: "Points", value: NO_FIGURE, text: NO_FIGURE_TEXT, testId: "lead-points" },
        { label: "Since", value: NO_FIGURE, text: NO_FIGURE_TEXT },
      ],
    };
  }

  const points = pointsReading(trade);
  return {
    kicker,
    phaseNote,
    headline: tradeHeadline(trade),
    body: `${trade.assets_short}, traded ${fmtDate(trade.date)}.`,
    href: `/league/${leagueId}/trade/${trade.trade_id}`,
    cells: [
      {
        label: "Value",
        value: <span className={signColor(trade.swing_ktc)}>{fmtSigned(trade.swing_ktc)}</span>,
        text: fmtSigned(trade.swing_ktc),
      },
      {
        label: "Points",
        value: <PointsCell reading={points} />,
        text: pointsText(points),
        testId: "lead-points",
      },
      // Short form here, not fmtDate. The old reason was width — a 106px track
      // when the strip was capped at 620px — and that cap is gone, so the track
      // is now wide enough for "September 15, 2025". The form stays short for
      // the reason that outlived the cap: this is a figure in a mono strip, and
      // the body sentence directly above already states the date in full.
      {
        label: "Since",
        value: <span className="text-dim">{fmtDateShort(trade.date)}</span>,
        text: fmtDateShort(trade.date),
      },
    ],
  };
}

/* ---------------------------------------------------------------------------
 * Week recap — the in-season source (A2). `week_recap` carries the most recent
 * COMPLETED regular-season week, so the lead never prints a partial Sunday
 * score. Its absence (outside the regular season, week 1, or a cache written
 * before the field existed) keeps the placeholder skeleton below rather than
 * fabricating figures.
 * ------------------------------------------------------------------------ */
function weekRecapContent(data: DashboardResp): LeadContent {
  const recap = data.week_recap;

  if (!recap) {
    const week = data.phase_week;
    return {
      kicker: week ? `Week ${week} recap` : "Week recap",
      phaseNote: "In season",
      headline: "This week's results land once the week is final.",
      body: "High score, biggest blowout, and points from trade-acquired starters appear here after the last game of the week is scored.",
      cells: [
        { label: "High", value: NO_FIGURE, text: NO_FIGURE_TEXT },
        { label: "Blowout", value: NO_FIGURE, text: NO_FIGURE_TEXT },
        { label: "Traded", value: NO_FIGURE, text: NO_FIGURE_TEXT },
      ],
    };
  }

  const who = (f: { owner?: { owner_name: string } | null; user_id: string }) =>
    f.owner?.owner_name ?? f.user_id;
  const high = who(recap.high_score);
  const winner = recap.blowout.winner
    ? recap.blowout.winner.owner_name
    : recap.blowout.winner_user_id;
  const loser = recap.blowout.loser
    ? recap.blowout.loser.owner_name
    : recap.blowout.loser_user_id;
  const traded = recap.traded_points;

  return {
    kicker: `Week ${recap.week} recap`,
    phaseNote: "In season",
    headline: `${high} put up ${recap.high_score.points.toFixed(1)}.`,
    body: (
      <>
        {winner} beat {loser} by {recap.blowout.margin.toFixed(1)} — the week&rsquo;s
        widest margin.
        {traded
          ? ` ${who(traded)} got ${traded.points.toFixed(1)} of it from players acquired in trades.`
          : " Nobody started a trade-acquired player for points."}
      </>
    ),
    cells: [
      {
        label: "High",
        value: <NamedFigureCell name={high} figure={recap.high_score.points.toFixed(1)} />,
        text: `${high} ${recap.high_score.points.toFixed(1)}`,
      },
      {
        label: "Blowout",
        value: <NamedFigureCell name={winner} figure={fmtSigned(recap.blowout.margin, 1)} />,
        text: `${winner} ${fmtSigned(recap.blowout.margin, 1)}`,
      },
      {
        label: "Traded",
        value: traded
          ? <NamedFigureCell name={who(traded)} figure={traded.points.toFixed(1)} />
          : NO_FIGURE,
        text: traded ? `${who(traded)} ${traded.points.toFixed(1)}` : NO_FIGURE_TEXT,
      },
    ],
  };
}

/** The draft-window lead: how the last draft actually panned out. Dynasty
 *  leagues grade a rookie class here; redraft and keeper grade the whole
 *  board.
 *
 *  Retrospective rather than live-draft coverage, deliberately. A live board
 *  (who's on the clock, picks landing) is what the Sleeper app already shows,
 *  in real time, on the screen you're staring at during a draft — and it would
 *  be empty through `pre_draft`, which is most of the window. "Did your picks
 *  pan out" is the reading only this app has.
 *
 *  Every pick is graded against its own class (`slot_delta` = where it went
 *  minus where it finished by production), so there's no ADP table to go stale
 *  and no assumption about what a slot "should" return. */
function draftReviewContent(data: DashboardResp, leagueId: string): LeadContent {
  const review = data.draft_review;
  // No review means the class cannot be reviewed AT ALL — fewer than two
  // scored picks (keepers and auction picks are shown, never scored), or a
  // cache predating the field. An unplayed class is NOT this case: it comes
  // back `graded: false`, handled below. Fall back to the pre-authorized
  // trade source rather than print a hollow block.
  if (!review) {
    return tradeOfWeekContent(data, leagueId, "Trade of the week", "");
  }

  const at = (p: NonNullable<typeof review.best>) =>
    `${p.round}.${String(p.slot).padStart(2, "0")}`;
  const baselineLabel = (p: NonNullable<typeof review.best_value>) =>
    p.baseline_source === "rookie_ecr" ? "ECR" : p.baseline_source === "sleeper_adp" ? "ADP" : "consensus";

  // A class that has completed but not played yet: the results are real, the
  // production grade is not — naming a "best pick" out of an all-zero field
  // would invent one. But value vs draft-day consensus (rookie ECR, else
  // Sleeper ADP) needs no played game, so that's the ungraded window's
  // story: who fell past his expected slot (a steal) and who got reached
  // for hardest. `!review.best || !review.worst` below is the same contract
  // defensively — the backend only omits them when `graded` is false, but
  // the type is nullable independent of `graded`, and printing a crash beats
  // printing "null."
  if (!review.graded || !review.best || !review.worst) {
    const { best_value: value, reach, total, season } = review;
    if (value && reach) {
      const valueOwner = value.owner?.owner_name ?? value.drafter_id;
      const reachOwner = reach.owner?.owner_name ?? reach.drafter_id;
      const valueDelta = Math.round(value.baseline_delta ?? 0);
      const reachDelta = Math.round(reach.baseline_delta ?? 0);
      return {
        kicker: "Draft",
        phaseNote: "",
        headline: `${valueOwner} landed the steal of the ${season} draft — ${value.full_name} fell ${valueDelta} picks past his ${baselineLabel(value)} rank.`,
        body: (
          <>
            {reachOwner} reached hardest, taking {reach.full_name} at {at(reach)}
            {" — "}
            {Math.abs(reachDelta)} {Math.abs(reachDelta) === 1 ? "pick" : "picks"} ahead of
            his {baselineLabel(reach)} rank. Full grades land once the season&rsquo;s played
            a week.
          </>
        ),
        actionHref: `/league/${leagueId}/draft/${season}`,
        actionLabel: "See the draft board",
        cells: [
          {
            label: "Best value",
            value: (
              <NamedFigureCell
                name={valueOwner}
                figure={<span className={signColor(valueDelta)}>{fmtSigned(valueDelta)}</span>}
              />
            ),
            text: `${valueOwner} ${fmtSigned(valueDelta)}`,
          },
          {
            label: "Biggest reach",
            value: (
              <NamedFigureCell
                name={reachOwner}
                figure={<span className={signColor(reachDelta)}>{fmtSigned(reachDelta)}</span>}
              />
            ),
            text: `${reachOwner} ${fmtSigned(reachDelta)}`,
          },
          {
            label: "Picks",
            value: String(total),
            text: String(total),
          },
        ],
      };
    }

    // Nothing matched a consensus baseline (e.g. an all-keeper/all-auction
    // class, or a redraft league before its first ADP snapshot) — say less
    // rather than invent a story with no signal.
    return {
      kicker: "Draft",
      phaseNote: "",
      headline: `The ${review.season} draft is in the books — ${review.total} picks.`,
      body: "Grading starts once the season's played a week — check back after kickoff.",
      actionHref: `/league/${leagueId}/draft/${review.season}`,
      actionLabel: "See the draft board",
      cells: [
        { label: "Picks made", value: String(review.total), text: String(review.total) },
        { label: "Class", value: String(review.season), text: String(review.season) },
        { label: "Graded", value: "After week 1", text: "After week 1" },
      ],
    };
  }

  const { best, worst, beat_slot, total, season } = review;
  const bestOwner = best.owner?.owner_name ?? best.drafter_id;
  const worstOwner = worst.owner?.owner_name ?? worst.drafter_id;

  return {
    kicker: "Draft review",
    phaseNote: "",
    headline: `${bestOwner} got the best pick of the ${season} draft at ${at(best)}.`,
    body: (
      <>
        {best.full_name} has outproduced {best.slot_delta}{" "}
        {best.slot_delta === 1 ? "player" : "players"} taken ahead of him.
        {" "}
        {beat_slot} of {total} picks that year have beaten the slot they went at.
      </>
    ),
    // Same destination the ungraded branch offers: the board is where the
    // whole class lives, and the lead is the app's only route to it.
    actionHref: `/league/${leagueId}/draft/${season}`,
    actionLabel: "See the draft board",
    cells: [
      {
        label: "Best pick",
        value: <NamedFigureCell name={bestOwner} figure={at(best)} />,
        text: `${bestOwner} ${at(best)}`,
      },
      {
        label: "Worst pick",
        value: <NamedFigureCell name={worstOwner} figure={at(worst)} />,
        text: `${worstOwner} ${at(worst)}`,
      },
      {
        label: "Beat slot",
        value: `${beat_slot} / ${total}`,
        text: `${beat_slot} of ${total}`,
      },
    ],
  };
}

/** The postseason lead: who is still alive on the title path.
 *
 *  League-wide rather than viewer-specific, matching every other lead — the
 *  week recap names the league's high score, not yours. Bracket state comes
 *  off the persisted blob; the playoff-points figure is read from the same
 *  standings rows this response already built, so the lead can never disagree
 *  with the table underneath it.
 *
 *  Never invents bracket state: an unplayed game eliminates nobody, and an
 *  unknown seed or an empty playoff-points field prints the em-dash rather
 *  than a guess. */
function bracketWatchContent(data: DashboardResp): LeadContent {
  const week = data.phase_week;
  const watch = data.bracket_watch;
  const phaseNote = week ? `Wk ${week}` : "Postseason";

  if (!watch || watch.alive.length === 0) {
    return {
      kicker: "Bracket watch",
      phaseNote,
      headline: "The bracket hasn't been posted yet.",
      body: "Once the first playoff game is played, this is where who's still alive — and whose traded pieces are deciding it — will show up.",
      cells: [
        { label: "Alive", value: NO_FIGURE, text: NO_FIGURE_TEXT },
        { label: "Top seed", value: NO_FIGURE, text: NO_FIGURE_TEXT },
        { label: "Playoff pts", value: NO_FIGURE, text: NO_FIGURE_TEXT },
      ],
    };
  }

  const { alive_count, entered, top_seed_owner, top_seed } = watch;
  const leader = watch.playoff_points_leader;
  const pts = watch.playoff_points;
  const names = watch.alive.map((o) => o.owner_name);

  // One survivor means the final is over and the title is decided; two means
  // the final is the game left. Anything else is still a field.
  const headline =
    alive_count === 1
      ? `${names[0]} is your champion.`
      : alive_count === 2
        ? `${names[0]} and ${names[1]} are playing for it.`
        : `${alive_count} teams are still alive.`;

  return {
    kicker: "Bracket watch",
    phaseNote,
    headline,
    body: leader && pts != null ? (
      <>
        {entered} started the bracket. {leader.owner_name} leads the field with{" "}
        {pts.toFixed(1)} playoff points from players acquired in trades.
      </>
    ) : (
      <>
        {entered} started the bracket. No owner has scored playoff points from a
        trade-acquired player yet.
      </>
    ),
    cells: [
      {
        label: "Alive",
        value: `${alive_count} / ${entered}`,
        text: `${alive_count} of ${entered}`,
      },
      {
        label: "Top seed",
        value: top_seed_owner && top_seed != null
          ? <NamedFigureCell name={top_seed_owner.owner_name} figure={`#${top_seed}`} />
          : NO_FIGURE,
        text: top_seed_owner && top_seed != null
          ? `${top_seed_owner.owner_name} #${top_seed}`
          : NO_FIGURE_TEXT,
      },
      {
        label: "Playoff pts",
        value: leader && pts != null
          ? <NamedFigureCell name={leader.owner_name} figure={pts.toFixed(1)} />
          : NO_FIGURE,
        text: leader && pts != null
          ? `${leader.owner_name} ${pts.toFixed(1)}`
          : NO_FIGURE_TEXT,
      },
    ],
  };
}

function selectLead(data: DashboardResp, leagueId: string): LeadContent {
  const phase = data.phase ?? "offseason";
  switch (phase) {
    case "regular":
      return weekRecapContent(data);
    case "post":
      return bracketWatchContent(data);
    case "draft":
      return draftReviewContent(data, leagueId);
    default:
      return tradeOfWeekContent(data, leagueId, "Trade of the week", "Offseason");
  }
}

function signColor(n: number): string {
  return n > 0 ? "text-pos-strong" : n < 0 ? "text-neg-strong" : "text-dim";
}

/** One strip cell: a whisper label over a figure. Always three per lead, at
 *  every viewport and in every phase — the lead is one fixed skeleton and only
 *  the source changes, so the page never reflows across the season.
 *
 *  `text` is the figure as a plain string. The strip is two sibling grids (the
 *  26px rule pitch depends on it), so a screen reader linearizes all three
 *  labels and then all three figures, pairing them only by position. `text`
 *  restores the pairing as an aria-label without touching the layout. */
type FigureCell = { label: string; value: ReactNode; text: string; testId?: string };

/* ---------------------------------------------------------------------------
 * The figure strip (docs/superpowers/specs/2026-08-11-dashboard-lead-design.md).
 * Depth in this system is rules, not boxes.
 *
 * NOT ITS OWN PANEL. This used to be a `Panel` capped at 620px sitting BELOW
 * the prose on the page ground — so the lead read as two unrelated objects
 * floating in whitespace, a headline with no container and a half-width table
 * that looked like a stray fragment of the ledger further down. It is now the
 * foot of the lead's own card: the Rows draw their `--rule` hairlines against
 * the card's ground and span its full width, which is the only reason the
 * figures read as this story's receipt rather than a second table.
 * ------------------------------------------------------------------------ */
function FigureStrip({ cells }: { cells: FigureCell[] }) {
  return (
    <div>
      {/* The head row carries the hairline that separates the receipt from the
          prose above it. `Row variant="head"` draws only a BOTTOM border — a
          solid panel means every row draws its own rules, and the one at the
          top of this strip is not any row's by default. */}
      <Row variant="head" cols="repeat(3, minmax(0,1fr))" className="gap-4 border-t border-rule">
        {cells.map((c) => (
          <span
            key={c.label}
            className="min-w-0 truncate"
          >
            {c.label}
          </span>
        ))}
      </Row>
      <Row cols="repeat(3, minmax(0,1fr))" className="gap-4">
        {cells.map((c) => (
          <span
            key={c.label}
            data-testid={c.testId}
            aria-label={`${c.label}: ${c.text}`}
            className="min-w-0 truncate text-ink"
          >
            {c.value}
          </span>
        ))}
      </Row>
    </div>
  );
}

/** Cell-internal layout for a "name + figure" pairing (the week-recap cells:
 *  High/Blowout/Traded). The label degrades before the figure does — the
 *  figure is the payload and must never truncate ("Prose Never Shares A
 *  Rule"); only the name gives ground, with `title` as the hover escape
 *  hatch once it does. A long Sleeper display name inside the strip's outer
 *  `truncate` span would otherwise clip the number itself, not just the
 *  name — this inner two-track grid keeps the figure's own column
 *  (`auto`-width, `whitespace-nowrap`) immune to that. */
function NamedFigureCell({ name, figure }: { name: string; figure: ReactNode }) {
  return (
    <span className="grid grid-cols-[minmax(0,1fr)_auto] gap-1">
      {/* Archivo, not the cell's inherited Geist Mono: DESIGN.md § Type gives
          franchise names to the display face. The figure beside it stays
          mono + tabular. */}
      <span title={name} className="min-w-0 truncate font-display font-semibold">{name}</span>
      <span className="whitespace-nowrap">{figure}</span>
    </span>
  );
}

/** The POINTS cell. No sign color — received-only totals are never negative,
 *  so a sign color would be permanently green and mean nothing (DESIGN.md:
 *  color rides signed numbers only). The lens winner is weighted; the other
 *  side and the "vs" whisper. */
function PointsCell({ reading }: { reading: PointsReading }) {
  if (reading.kind === "unscored") return NO_FIGURE;
  // A null winner is a tie *after rounding* — two identical figures, so
  // neither is weighted and neither is dimmed.
  const weight = (side: "left" | "right") =>
    reading.winner === null ? "" : reading.winner === side ? "font-semibold" : "text-dim";
  return (
    <>
      <span className={weight("left")}>{reading.left}</span>
      <span className="text-dim"> vs </span>
      <span className={weight("right")}>{reading.right}</span>
    </>
  );
}

export function HeadlineMoves({ data, leagueId }: Props) {
  const lead = selectLead(data, leagueId);

  const headline = lead.href ? (
    <Link href={lead.href} className="hover:underline">{lead.headline}</Link>
  ) : (
    lead.headline
  );

  /* The way out of the lead: a bordered pill, not the stamp-filled primary
   * `Button` — the masthead directly above (`LeagueHeader`) is already a
   * full `--stamp` fill, and a second stamp block right under it would
   * out-shout the headline it's subordinate to (readme.md: one primary
   * Button per view). A pill border still reads as a clear, tappable CTA —
   * distinct from a bare MonoLink — using the same `rounded-pill` vocabulary
   * TopBar's own controls already draw from, just sized for a text label
   * instead of an icon. Same treatment for every lead source: one skeleton,
   * one exit chrome. */
  const exit = lead.actionHref
    ? { href: lead.actionHref, label: lead.actionLabel }
    : lead.href
      ? { href: lead.href, label: "Read the trade" }
      : null;

  return (
    /* ONE CARD. `.design/templates/dashboard/Dashboard.dc.html` draws the lead
     * as a single `--surface` panel between the masthead and the standings —
     * same width as both, one radius, one elevation. What shipped instead was a
     * bare kicker rule on the page ground, prose at 24ch/46ch, a cobalt button
     * and a separate 620px table, none of which shared an edge with anything;
     * "the league's latest" read as four loose fragments in a field of
     * whitespace. The measures below (34ch headline, 62ch body) are the
     * template's too — the old ones broke the headline at half the card. */
    <section className="mb-8">
      <Panel>
        <div className="px-4 pt-4 pb-5 sm:px-6 sm:pt-5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-mono text-label uppercase tracking-[0.16em] text-dim">{lead.kicker}</span>
            <span className="font-mono text-label uppercase tracking-[0.11em] text-dim">{lead.phaseNote}</span>
          </div>

          <h2 className="mt-2 max-w-[34ch] font-display text-lead font-extrabold leading-[1.05] tracking-[var(--track-lead)]">
            {headline}
          </h2>
          <p className="mt-2 max-w-[62ch] text-prose leading-relaxed text-body">{lead.body}</p>

          {exit && (
            <Link
              href={exit.href}
              className="mt-3 inline-flex min-h-tap items-center gap-1 rounded-pill border border-ink px-3.5 font-mono text-label font-bold uppercase tracking-[0.11em] transition-colors hover:bg-ink hover:text-bg"
            >
              {exit.label} →
            </Link>
          )}
        </div>

        <FigureStrip cells={lead.cells} />
      </Panel>
    </section>
  );
}
