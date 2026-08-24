"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { leaderboard as fetchLeaderboard } from "@/lib/api";
import { ContributionRow } from "@/components/RatingBars";
import { GMRow, LeaderboardResp, Year } from "@/lib/types";
import { InfoTooltip } from "./InfoTooltip";
import { SegmentControl } from "./SegmentControl";
import { Mark as Icon } from "./furniture/Mark";
import { Panel } from "./furniture/Panel";
import { Row } from "./furniture/Row";
import { StateMessage } from "./furniture/StateMessage";
import { CardHead } from "./ownerdeepdive/ui";
import { franchiseLetterTone, SIGNAL_LABELS } from "./ownerdeepdive/util";

/* ---------------------------------------------------------------------------
 * Furniture — this screen wasn't drawn in the design bundle, so it applies
 * the system's existing vocabulary rather than inventing new chrome:
 *  - Ledger rows are `Panel`/`Row` (furniture/Panel.tsx, furniture/Row.tsx).
 *    A Panel is solid — no striped ground doing the dividing for you — so
 *    every `Row` draws its own `--rule` top border; the old per-entry
 *    `borderTopWidth: 0`-except-last-place trick is gone because there's no
 *    "last place re-enables its own rule" special case left to encode (og-
 *    card.tsx's LeaderboardCardView is still the drawn-equivalent reference).
 *  - The pillar/signal breakdown reuses `ContributionRow` (RatingBars.tsx) —
 *    the same Ink Bars component OverviewTab.tsx already draws for the
 *    identical GM-rating receipt on the owner franchise page — instead of a
 *    bespoke bar. Its bar (fixed center axis, ink fill) is what "Ink Bars"
 *    actually specifies; the old asymmetric data-driven-axis Bar predates
 *    the port and wasn't spec-compliant.
 *  - Tooltips reuse `InfoTooltip.tsx` verbatim (title/body/formula) instead
 *    of a parallel bespoke popover; the per-row "You: raw · zσ vs league ·
 *    weight% of X" stat line folds into the `formula` footer slot.
 *  - The year/all-time switcher is `SegmentControl` (the shared mono-run
 *    dialect), not the YearTabs "year line" — DashboardClient.tsx already
 *    treats the GM board's switcher as separate from the page-wide year
 *    line ("The GM board carries its own all-time/per-season toggle").
 *  - No 👑/🪣: DESIGN.md's "Two Glyphs" rule reserves 🏆/🚽 for a Trophy
 *    column, which this screen doesn't have — dropped outright, no
 *    replacement.
 * ------------------------------------------------------------------------ */

/** prev_rank − rank: positive = climbed, negative = slipped, 0 = held/new. */
function Trend({ trend }: { trend: number }) {
  if (trend > 0) {
    return (
      <span
        className="font-mono text-figure font-semibold text-pos-strong"
        aria-label={`Up ${trend}`}
      >
        ▲{trend}
      </span>
    );
  }
  if (trend < 0) {
    return (
      <span
        className="font-mono text-figure font-semibold text-neg-strong"
        aria-label={`Down ${-trend}`}
      >
        ▼{-trend}
      </span>
    );
  }
  return (
    <span className="font-mono text-figure text-dim" aria-label="No change">
      —
    </span>
  );
}

function signed(n: number): string {
  const r = Math.round(n);
  return r > 0 ? `+${r}` : String(r);
}

function pointClass(n: number): string {
  return n > 0 ? "text-pos-strong font-semibold" : n < 0 ? "text-neg-strong font-semibold" : "text-dim";
}

// v2: 0.60 Results + 0.40 Assets, no Skill/Outlook pillars
// (src/sleeper_dynasty/engine/gm_rating.py::V2_PILLAR_WEIGHTS["v2_dynasty"]).
// A redraft league scores Results only (V2_PILLAR_WEIGHTS["v2_redraft"]) — the
// rows below already render whatever pillar keys the API actually returns
// (`if (!p) return null`), so this list only needs to name the keys v2 can
// send, not gate on format itself.
const PILLAR_ORDER = ["results", "assets"];
const PILLAR_LABELS: Record<string, string> = {
  results: "Results", assets: "Assets",
};

/** Plain-language definitions, faithful to engine/results_signals.py +
 *  engine/asset_signals.py. Each signal is z-scored against the league, so
 *  "league-relative" is the shared subtext (also stated in the panel footer). */
const PILLAR_HELP: Record<string, string> = {
  results:
    "What this franchise has actually achieved, luck-adjusted and weighted toward recent seasons: all-play win rate, playoff depth, and schedule luck. 60% of the rating.",
  assets:
    "What the franchise holds right now and is building toward: roster value share, young-core share, and draft capital. 40% of the rating.",
};
const SIGNAL_HELP: Record<string, string> = {
  expected_wins:
    "All-play win rate — the record you'd have if you played every team every week, recency-weighted so recent seasons count more.",
  playoff_success:
    "How deep your playoff runs go: a berth alone is worth half a round win, each round won a full one, a title a bonus on top — recency-weighted.",
  luck:
    "Your actual record minus your all-play (expected) record — the part of your win total that's schedule luck, not lineup quality.",
  roster_value_share: "Today's dynasty market value of your roster, as a share of the whole league's.",
  young_core_share: "The share of your OWN roster's value held by players 25 or younger.",
  draft_capital:
    "Market value of the future rookie picks you hold across the next three drafts, tiered early/mid/late by each pick's original team strength (a rebuilder's pick is worth more).",
};

/** Raw inputs span wildly different units (a championship count vs a market value sum),
 *  so scale the precision to the magnitude. */
function fmtRaw(n: number): string {
  const a = Math.abs(n);
  if (a >= 1000) return Math.round(n).toLocaleString();
  if (Number.isInteger(n)) return String(n);   // counts: "2", not "2.0"
  if (a >= 10) return String(Math.round(n));
  return n.toFixed(a >= 1 ? 1 : 2);
}

function fmtZ(z: number): string {
  return `${z >= 0 ? "+" : ""}${z.toFixed(1)}σ`;
}

/** The Base/Franchise Rating rows flanking the pillar/signal breakdown share
 *  ContributionRow's own grid tracks so every figure lands on the same
 *  column as the bars above and below it. */
const TOTAL_ROW_GRID = "grid-cols-[minmax(0,1fr)_52px] min-[701px]:grid-cols-[168px_1fr_52px]";

function GmRowView({
  r,
  total,
  leagueId,
  expanded,
  onToggle,
}: {
  r: GMRow;
  total: number;
  leagueId: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isLast = total > 1 && r.rank === total;

  // Shared bar scale across every pillar + signal contribution in this row —
  // the max, not the largest signal (DESIGN.md § "Ink Bars").
  const scale = useMemo(() => {
    const mags = [1];
    for (const pk of PILLAR_ORDER) {
      const p = r.pillars[pk];
      if (!p) continue;
      mags.push(Math.abs(p.contribution));
      for (const s of Object.values(p.signals)) mags.push(Math.abs(s.contribution));
    }
    return Math.max(...mags);
  }, [r]);

  return (
    <>
      <Row className="grid-cols-[28px_minmax(0,1fr)_136px]">
        <span>{r.rank}</span>
        {/* Name → franchise page (primary). */}
        <Link href={`/league/${leagueId}/owner/${r.user_id}`} className="min-w-0">
          <span
            className={`block truncate font-display text-name font-bold tracking-[var(--track-name)] text-ink ${
              isLast ? "text-dim" : "text-ink"
            }`}
          >
            {r.owner.owner_name}
          </span>
        </Link>
        {/* Rating + trend → expand the breakdown (secondary). */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} rating breakdown for ${r.owner.owner_name}`}
          className="flex items-center justify-end gap-2.5"
        >
          <span className={`font-display text-name font-bold leading-none ${franchiseLetterTone(r.letter)}`}>
            {r.letter}
          </span>
          <span>{r.rating}</span>
          <Trend trend={r.trend} />
          <Icon name={expanded ? "open" : "closed"} size={10} className="text-dim" />
        </button>
      </Row>

      {expanded && (
        <div className="pb-3">
          <Panel>
            <Row className={TOTAL_ROW_GRID}>
              <span>Base</span>
              <span className="hidden min-[701px]:block" aria-hidden="true" />
              <span className="text-right tabular">1500</span>
            </Row>
            {/* Roster rank — mirrors StandingsTable's Roster column (same
                today's-roster-value signal, api/app/services/leaderboard.py
                reading the same entry.roster_ranks source under the same
                redraft gate). Gated per row rather than per league because a
                cache written before the field existed, or a redraft league,
                both leave it None on every row — an absent field degrades to
                an omitted line, never a blank one, exactly like the ledger. */}
            {r.roster_rank != null && (
              <Row className={TOTAL_ROW_GRID}>
                <span>Roster</span>
                <span className="hidden min-[701px]:block" aria-hidden="true" />
                <span className="text-right tabular">
                  {`#${r.roster_rank}`}{r.roster_of != null ? ` of ${r.roster_of}` : ""}
                </span>
              </Row>
            )}
            {PILLAR_ORDER.map((pk) => {
              const p = r.pillars[pk];
              if (!p) return null;
              return (
                <Fragment key={pk}>
                  <ContributionRow
                    label={PILLAR_LABELS[pk]}
                    weight={p.weight}
                    points={p.contribution}
                    scale={scale}
                    tooltip={
                      <InfoTooltip
                        title={PILLAR_LABELS[pk]}
                        body={PILLAR_HELP[pk]}
                        formula={`${fmtZ(p.z)} vs league · ${Math.round(p.weight * 100)}% of the rating`}
                      />
                    }
                  />
                  {Object.entries(p.signals).map(([sk, s]) => (
                    <ContributionRow
                      key={sk}
                      signal
                      label={SIGNAL_LABELS[sk] ?? sk}
                      points={s.contribution}
                      scale={scale}
                      tooltip={
                        <InfoTooltip
                          title={SIGNAL_LABELS[sk] ?? sk}
                          body={SIGNAL_HELP[sk]}
                          formula={`${fmtRaw(s.raw)} · ${fmtZ(s.z)} vs league · ${Math.round(s.weight * 100)}% of ${PILLAR_LABELS[pk]}`}
                        />
                      }
                    />
                  ))}
                </Fragment>
              );
            })}
            <Row variant="total" className={TOTAL_ROW_GRID}>
              <span className="font-display text-figure font-bold text-ink">Franchise Rating</span>
              <span className={`hidden min-[701px]:block text-right text-figure font-normal ${pointClass(r.rating - 1500)}`}>
                {signed(r.rating - 1500)}
              </span>
              <span className="text-right font-mono text-figure tabular text-ink">{r.rating}</span>
            </Row>
          </Panel>
          <p className="mt-2 text-figure leading-snug text-dim">
            Every point is league-relative, centered at 1500. Each signal is
            scored against the rest of your league.
          </p>
          {r.blurb && (
            <p className="mt-3 border-t border-rule pt-3 font-sans text-figure leading-relaxed text-ink">
              {r.blurb}
            </p>
          )}
        </div>
      )}
    </>
  );
}

/** Collapsed-by-default "how the rating is computed" disclosure.
 *
 *  `hasOutlook` is false for a redraft league, which scores on one pillar,
 *  not two (engine/gm_rating.py `V2_PILLAR_WEIGHTS["v2_redraft"]`: Results
 *  100%, Assets dropped — nothing carries over between seasons for a redraft
 *  league, so there's nothing for Assets to measure). The rows themselves
 *  already render whatever pillars come back; this is the prose that used to
 *  describe three pillars (Results/Skill/Outlook) regardless of the league's
 *  format — v2 has no Skill pillar at all. */
function RatingExplainer({ hasOutlook }: { hasOutlook: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 font-mono text-label uppercase tracking-widest text-dim hover:text-ink"
      >
        <Icon name={open ? "open" : "closed"} size={10} aria-hidden="true" />
        How the Franchise Rating works
      </button>
      {open && (
        <div className="mt-2 max-w-2xl space-y-2.5 border-t border-rule pt-3 text-figure leading-relaxed text-dim">
          <p>
            It&apos;s a letter grade off one league-relative number, centered at{" "}
            <strong className="text-ink">1500</strong> — an exactly average GM in
            your league is a C. It blends{" "}
            {hasOutlook ? "two pillars" : "one pillar"} of running the
            franchise:
          </p>
          <ul className="space-y-1 pl-1 font-mono text-figure tabular">
            <li>
              <span className="text-ink">Results</span> · {hasOutlook ? "60%" : "100%"} — what you&apos;ve
              won, luck-adjusted: all-play win rate, playoff depth, schedule luck.
            </li>
            {hasOutlook && (
              <li>
                <span className="text-ink">Assets</span> · 40% — what your franchise
                holds and is building toward: roster value share, young-core share,
                draft capital.
              </li>
            )}
          </ul>
          <p>
            Each signal inside a pillar is scored against the rest of your league
            (so titles, points, and market value all land on one scale), blended by
            weight, and re-centered on 1500, then graded.{" "}
            {hasOutlook
              ? "What you've done and what you're building toward, in one letter."
              : "What you've done, in one letter."}
          </p>
          <p className="text-figure">
            Tap any GM for the full receipt — every pillar and signal, down to the
            points it added or cost.{" "}
            <Link href="/methodology" className="underline">
              Full methodology →
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}

interface Props {
  leagueId: string;
  initialYear: Year;
  seasons: number[];
  /** From `DashboardResp.capabilities.format`, threaded down by
   *  `DashboardClient.tsx` — same path the rest of the app reads format
   *  from (`LeagueCapabilities.format`, `lib/types.ts`). Optional and
   *  defaults to full dynasty, matching every other `capabilities` consumer:
   *  an older cached fixture or a `web` deploy that lands ahead of the
   *  `capabilities` field must not suddenly read as redraft. */
  format?: "dynasty" | "keeper" | "redraft";
}

export function Leaderboard({ leagueId, initialYear, seasons, format }: Props) {
  const router = useRouter();
  const [data, setData] = useState<LeaderboardResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchLeaderboard(leagueId, { year: initialYear });
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load the leaderboard.");
    } finally {
      setLoading(false);
    }
  }, [leagueId, initialYear]);

  useEffect(() => {
    load();
  }, [load]);

  const items: { key: Year; label: string }[] = useMemo(
    () => [
      ...seasons.map((s) => ({ key: s as Year, label: String(s) })),
      { key: "all" as Year, label: "All-time" },
    ],
    [seasons],
  );

  const choose = (y: Year) => {
    const sp = new URLSearchParams();
    sp.set("tab", "gm");
    if (y !== "all") sp.set("year", String(y));
    router.push(`/league/${leagueId}?${sp.toString()}`);
  };

  const rows = data?.rows ?? [];

  // Format decides the pillar count, not row shape. This USED to check
  // `rows.some((r) => "outlook" in r.pillars)` — under v2 NO weight tree
  // carries an `outlook` pillar key at all (see franchise_redesign.py), so
  // that check was permanently false and every league, dynasty included,
  // would have read as redraft the moment v2 shipped. `format` is undefined
  // before the first response lands (and on any cache/route that omits
  // capabilities), which defaults to dynasty — same convention as every
  // other `capabilities` consumer in the app.
  const hasOutlook = format !== "redraft";

  return (
    <section aria-busy={loading}>
      {/* The season control rides the head, beside the title it filters. The
          head used to carry a dim caption naming the selected year at the far
          right — with the control itself sitting here, that caption states the
          same fact twice, and the one it was reading from is now the one a
          reader can act on. */}
      <CardHead
        title="Franchise Ratings"
        filter={
          <SegmentControl options={items} value={initialYear} onChange={choose} aria-label="Season" />
        }
      />
      <p className="text-figure text-dim">
        One letter per GM —{" "}
        {hasOutlook ? "results and assets" : "results"}, against
        your league. Tap a row for the full receipt.
      </p>
      <RatingExplainer hasOutlook={hasOutlook} />

      {error ? (
        <StateMessage
          className="mt-6"
          tone="negative"
          kicker="Ratings didn't load"
          headline={error}
          body="Not you — us. The board comes back once the league's cache is warm."
        />
      ) : rows.length === 0 && !loading ? (
        <StateMessage
          className="mt-6"
          kicker="No completed season yet"
          headline="Every franchise gets a rating here."
          body="Franchise Rating grades a full season of results and assets. The board fills in once this league has one in the books."
        />
      ) : (
        <div className={loading ? "opacity-60" : ""}>
          <Panel>
            <Row variant="head" className="grid-cols-[28px_minmax(0,1fr)_136px]">
              <span>#</span>
              <span>Franchise</span>
              {/* The Season control above legitimately re-filters the trade
                  columns in each row's expanded receipt (net_ktc/production
                  are year-scoped in _aggregate_owner_rows) — but v2's rating
                  itself has no per-season signal left (franchise_redesign
                  .live_ratings ignores `year` entirely) and reads the same
                  letter for every year. Same framing as StandingsTable's
                  Franchise Rating tooltip, so the two surfaces agree. */}
              <span className="flex items-center justify-end gap-1 text-right">
                Rating
                <InfoTooltip
                  align="right"
                  title="Franchise Rating"
                  body="Career-scoped: weighted toward recent seasons but always as-of-now. Picking a season above re-filters the trade ledger below, not this letter."
                />
              </span>
            </Row>
          </Panel>
          {rows.map((r) => (
            <GmRowView
              key={r.user_id}
              r={r}
              total={rows.length}
              leagueId={leagueId}
              expanded={open === r.user_id}
              onToggle={() =>
                setOpen((cur) => (cur === r.user_id ? null : r.user_id))
              }
            />
          ))}
        </div>
      )}
    </section>
  );
}
