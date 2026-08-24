"use client";

import { useMemo, useState } from "react";
import type { DraftBoardOwner, DraftBoardPick, OwnerRef } from "@/lib/types";
import { CardList, EntryCard, MetaLine, Meta } from "./furniture/EntryCard";
import { Mark } from "./furniture/Mark";
import { Name } from "./furniture/Name";
import { SegmentControl } from "./SegmentControl";
import { startPct } from "@/lib/start-rate";
import { pickPositionInRound } from "@/lib/draft-pick-no";

/**
 * The picks ledger on a phone — grouped by owner, with the flat pick order a
 * tap away.
 *
 * WHY GROUPED. The board rendered a name rule plus TWO rules of three stat
 * cells per pick: ~108 rules for 36 picks, 3,880px at 390px. But the height was
 * the smaller problem. A draft board is read to answer "how did each manager
 * draft", and the owner was a stat cell of equal weight to ADP — so the
 * question the page exists for had to be reassembled by eye, 36 times. Owners
 * are the entity here; picks are their evidence.
 *
 * NO COLUMN IS LOST. `DraftBoard.tsx`'s own docstring calls this "the one
 * screen on the whole site where a phone reader is the primary audience (draft
 * night)", and rules that losing a column below the breakpoint is not an
 * acceptable trade. So an expanded owner reveals a full card per pick — the
 * class's baseline (ECR or ADP, whichever it actually has), its delta, Proj,
 * and the five-metric production run (Total Points, Start %, Regular,
 * Playoff, Toilet) plus Games Started, all present — rather than a
 * one-figure line. The grouping buys height back by DEFERRING picks, never
 * by dropping fields.
 *
 * THE OWNER FIGURE IS A SUM, NOT AN AVERAGE. `adp_total_delta` is the total of
 * an owner's scorable picks (`api/app/services/draft_board_view.py`), which is
 * what the desktop Owners table already labels "ADP +/-". A sum rewards volume
 * — five scorable picks can out-total two without drafting better per pick —
 * so `Coverage` (graded of total) rides on the same card as the denominator
 * that makes it readable. Inventing an average here would have been a new
 * metric wearing an old label, and it would disagree with the desktop table and
 * with the order the backend sorts owners in.
 *
 * THIS IS ALSO THE OWNERS SECTION NOW. `DraftBoard.tsx`'s desktop Owners table
 * is hidden below 910px — the same breakpoint `PicksSection`'s desktop table
 * uses, and deliberately so: an earlier version gated Owners at 701px and
 * Picks at 870px independently, which left a 701–869px band where this same
 * `OwnerGroup` card and the desktop Owners table both rendered at once, every
 * owner figure twice (see `DraftBoard.tsx`'s header docstring). Below 910px
 * the `OwnerGroup` card below is the ONLY place the owner rollup is reachable
 * (tablet and small-laptop widths included, not just a phone): rank, the
 * headline (PAR or ADP +/-, `ownerHeadlineFor`), then Picks/Coverage, the
 * graded five-metric run, and — new — ADP +/- as its own `Meta` when the
 * class is graded AND carries an ADP figure. That last one used to be lost
 * entirely once graded: the headline swaps to PAR, and nothing else on the
 * card ever showed the ADP delta, even though the desktop table's
 * `OWNER_GRID_GRADED_ADP` template carries it as a real ninth column in that
 * same state.
 *
 * `owners` ARRIVES SORTED (Task 2, fix round 1: `DraftBoard.tsx`'s
 * `sortedOwners`, following whatever column the desktop Owners table's
 * `SortButton`s currently sort by) — this component renders that ORDER, but
 * NOT the rank badge. Rank is read from the separate `rankOf` prop, a map
 * built once by `DraftBoard.tsx` from the owners list's ORIGINAL,
 * backend-sent order (PAR once graded, ADP total delta otherwise) — the same
 * guard the desktop table's own "#" column applies via its own `rankOf`.
 * Reading rank off `owners`' array index here, as an earlier version did,
 * silently renumbers the badge to match whatever column the user just
 * sorted by, which is a fact about the CURRENT VIEW, not about the owner —
 * exactly the trap the desktop table was built to avoid, just missed on this
 * side of the same fix.
 */
interface Props {
  picks: DraftBoardPick[];
  owners: DraftBoardOwner[];
  /** `user_id` → the owner's FIXED PAR/ADP-delta rank, independent of
   *  whatever order `owners` is currently sorted into. See this file's own
   *  docstring above. */
  rankOf: Map<string, number>;
  graded: boolean;
  hasBaseline: boolean;
  baselineLabel: string;
  hasProjected: boolean;
  hasVerdicts: boolean;
}

type View = "owner" | "pick";

function ownerName(o?: OwnerRef | null, fallbackId?: string): string {
  return o?.owner_name ?? fallbackId ?? "Unknown";
}

/** PAR is `total − mean`, so a value can land in `(-0.05, 0)` — arithmetically
 *  zero once rounded to the one decimal this card renders at, but still
 *  negative as a float. Mirrors `DraftBoard.tsx`'s own `ZERO_EPSILON` clamp:
 *  "zero or an absent value is `--dim`, never invent a sign for zero"
 *  (`EntryCard.tsx`'s house rule). Kept as its own constant here rather than
 *  imported, the same standalone-copy choice `startPctText` makes below, so
 *  the two files don't form a circular module dependency. */
const ZERO_EPSILON = 0.05;

function toneOf(n: number | null | undefined): "pos" | "neg" | "dim" {
  if (n == null || Math.abs(n) < ZERO_EPSILON) return "dim";
  return n > 0 ? "pos" : "neg";
}

function signed(n: number | null | undefined, decimals: 0 | 1 = 1): string {
  if (n == null) return "—";
  if (Math.abs(n) < ZERO_EPSILON) return decimals === 1 ? "0.0" : "0";
  const mag = decimals === 1 ? n.toFixed(1) : Math.round(n).toLocaleString();
  return n > 0 ? `+${mag}` : mag;
}

/** Share of Total Points that came from the starting lineup, as display text.
 *  Em-dash when there's nothing sound to divide — a zero OR NEGATIVE total (a
 *  K/DEF pick can score negative in a started week). Shared with
 *  `DraftBoard.tsx`'s `StartPct` and `ownerdeepdive/PastPicksTable.tsx` via
 *  `web/lib/start-rate.ts`, mirroring `start_rate.py`'s `total > 0` gate —
 *  the previous per-file `!total` gate let a negative total slip through. */
function startPctText(started: number | undefined, total: number | undefined): string {
  return startPct(started, total) ?? "—";
}

/** Hit/Average/Bust as a `Meta` label+tone pair — coloured mono text, never a
 *  chip, matching `PastPicksTable.tsx`'s `Status` treatment: the word carries
 *  the meaning, the colour only restates it. An empty verdict renders an
 *  em-dash (unranked, keeper, auction, or too-thin a cohort cell), never a
 *  guess. */
const VERDICT_LABEL: Record<string, string> = { hit: "Hit", average: "Average", bust: "Bust" };
const VERDICT_TONE: Record<string, "pos" | "neg" | "dim"> = { hit: "pos", average: "dim", bust: "neg" };

/** The pick's current standing with the drafting owner, as a `Meta` label+tone
 *  pair — matches `PastPicksTable.tsx`'s `Status` column and `DraftBoard.tsx`'s
 *  own copy of this table exactly: the word carries the meaning, the colour
 *  only restates it. Trading a player away is a decision, not a failure, so
 *  Traded reads neutral — same tone as unknown (never a guess). */
const STATUS_LABEL: Record<string, string> = { rostered: "Rostered", traded: "Traded", dropped: "Dropped" };
const STATUS_TONE: Record<string, "pos" | "neg" | "dim"> = { rostered: "pos", traded: "dim", dropped: "neg" };

/**
 * `1.01`, not `1`.
 *
 * `pick_no` is the overall order, which tells you nothing about the shape of
 * the draft — in a 12-team league pick 13 is the second round's first pick, and
 * a reader should not have to divide by the team count to learn that. But the
 * position half is NOT `p.slot` — that's the team's draft seed, which only
 * equals within-round position in odd rounds of a snake draft. It's derived
 * via `lib/draft-pick-no.ts::pickPositionInRound` instead, the one exported
 * helper `DraftBoard.tsx`'s own `PickNo` also calls, so the two surfaces
 * cannot drift apart on the derivation.
 *
 * Two-tone — round dim, position in ink — matching `DraftBoard.tsx`'s own
 * `PickNo` exactly. Zero-padded to two digits.
 */
function PickNo({ p }: { p: DraftBoardPick }) {
  const within = pickPositionInRound(p.pick_no, p.round, p.slot, p.picks_in_round);
  return (
    <span
      className="shrink-0 font-mono text-label uppercase tracking-[0.08em] tabular-nums"
      data-testid="pick-no"
    >
      <span className="text-dim">{p.round}.</span>
      <span className="text-ink">{String(within).padStart(2, "0")}</span>
    </span>
  );
}


/**
 * The figure a card leads with, or NULL when there is not one.
 *
 * Graded classes lead with what the pick actually scored. An ungraded class
 * leads with how far from the baseline it went — but the baseline is
 * **forward-only** in this app (`adp_snapshot_store.py`: a draft predating the
 * first daily snapshot has no baseline, permanently), so a real league can
 * have neither. Verified on the live 2026 class: every delta null, every
 * owner `0 of 7` coverage.
 *
 * Returning null rather than an em-dash is the point. A headline slot reading
 * "— ADP +/-" on every card is a column of nothing wearing a label, and it
 * pushes the player's name — the only thing that card actually knows — into a
 * narrower column to make room for it.
 *
 * `deltaLabel` defaults to the owner-level "ADP +/-" (owner grading is still
 * ADP-only); pick-level callers pass the class's actual baseline label.
 */
function headlineFor(
  graded: boolean,
  production: number,
  delta: number | null | undefined,
  deltaLabel: string = "ADP +/-",
): { value: string; label: string; tone?: "pos" | "neg" | "dim" } | null {
  if (graded) return { value: production.toFixed(1), label: "Total Points" };
  if (delta == null) return null;
  return { value: signed(delta), label: deltaLabel, tone: toneOf(delta) };
}

/**
 * The owner card's headline — distinct from `headlineFor` because a graded
 * owner leads with **Points Above Round**, not Total Points, mirroring the
 * desktop Owners table's own prominence swap (`DraftBoard.tsx`'s
 * `OwnersSection`): raw Total Points ranks draft POSITION — whoever picked
 * first tends to win — while PAR (`engine/draft_par.py`) is zero-sum within
 * the class and rewards drafting well from a bad slot. It is also the figure
 * the backend actually sorts owners by once graded, so this is "show the
 * figure you sorted by" applied to the card the same way it's applied to the
 * table row.
 *
 * Null PAR (an owner with nothing scorable, e.g. an all-keeper class) prints
 * no headline at all, same "no headline over a dead figure" rule
 * `headlineFor` already follows for an unplayed/unbaselined pick — an em-dash
 * headline squeezes the owner's name for a column that is not a real reading.
 */
function ownerHeadlineFor(
  graded: boolean,
  par: number | null | undefined,
  delta: number | null | undefined,
): { value: string; label: string; tone?: "pos" | "neg" | "dim" } | null {
  if (graded) {
    if (par == null) return null;
    return { value: signed(par), label: "Points Above Round", tone: toneOf(par) };
  }
  if (delta == null) return null;
  return { value: signed(delta), label: "ADP +/-", tone: toneOf(delta) };
}

/** The headline block, or nothing. */
function Headline({ h }: { h: { value: string; label: string; tone?: "pos" | "neg" | "dim" } | null }) {
  if (!h) return null;
  const cls = h.tone === "pos" ? "text-pos-strong"
    : h.tone === "neg" ? "text-neg-strong"
    : h.tone === "dim" ? "text-dim" : "text-ink";
  return (
    <span className="grid shrink-0 justify-items-end text-right">
      <b className={`font-mono text-name font-semibold tabular leading-none ${cls}`}>{h.value}</b>
      <span className="mt-0.5 font-mono text-label uppercase tracking-[0.12em] text-dim">{h.label}</span>
    </span>
  );
}

/** One pick, with every field the desktop row carries. */
function PickCard({ p, hasBaseline, baselineLabel, hasProjected, hasVerdicts, graded, showOwner }: {
  p: DraftBoardPick; hasBaseline: boolean; baselineLabel: string; hasProjected: boolean;
  hasVerdicts: boolean; graded: boolean; showOwner: boolean;
}) {
  const facts: { label: string; value: string; tone?: "pos" | "neg" | "dim" }[] = [];
  if (showOwner) facts.push({ label: "Owner", value: ownerName(p.owner, p.drafter_id) });
  if (hasBaseline) {
    facts.push({
      label: baselineLabel,
      value: p.baseline != null ? p.baseline.toFixed(1) : "—",
      tone: p.baseline == null ? "dim" : undefined,
    });
  }
  if (hasVerdicts) {
    facts.push({
      label: "Verdict",
      value: p.verdict ? VERDICT_LABEL[p.verdict] ?? "—" : "—",
      tone: p.verdict ? VERDICT_TONE[p.verdict] : "dim",
    });
  }
  if (hasProjected && !graded) {
    facts.push({
      label: "Proj",
      value: p.projected_points != null ? p.projected_points.toFixed(1) : "—",
      tone: p.projected_points == null ? "dim" : undefined,
    });
  }
  if (graded) {
    facts.push({ label: "Total", value: p.production_total.toFixed(1) });
    facts.push({ label: "Start %", value: startPctText(p.production_started, p.production_total) });
    facts.push({ label: "GS", value: String(p.games_started ?? 0) });
  }
  // Unconditional, like Owner/Player — every pick has a current standing.
  // Undefined only on a pre-feature response the API hasn't sent this field
  // on yet, and em-dashes rather than guessing "Dropped" (`Verdict`'s own
  // fallback above runs the same rule).
  facts.push({
    label: "Now",
    value: p.roster_status ? STATUS_LABEL[p.roster_status] ?? "—" : "—",
    tone: p.roster_status ? STATUS_TONE[p.roster_status] : "dim",
  });

  // The pick's VERDICT — or nothing, when the class is unplayed AND has no
  // baseline to be judged against. See `headlineFor`. "Slot +/-" is the
  // pick-level headline label on the phone card (the desktop header shortens
  // its own column to "Slot" — Treatment C's header re-cut, see
  // `draft-columns.ts` — but this card has room to spell it out) — it is
  // format-neutral and does not repeat the adjacent ECR/ADP column's own
  // label. Distinct from the owner-level headline below, which is a real sum
  // of ADP deltas and keeps the "ADP +/-" name.
  const headline = headlineFor(graded, p.production_total, p.baseline_delta, "Slot +/-");

  return (
    <EntryCard>
      <div className="flex min-w-0 items-center gap-2.5">
        <PickNo p={p} />
        <span className="min-w-0 flex-1 truncate">
          <Name>{p.full_name}</Name>
          <span className="ml-1.5 font-mono text-label uppercase tracking-[0.1em] text-dim">{p.position}</span>
          {p.is_keeper && (
            <span className="ml-1.5 font-mono text-label uppercase tracking-[0.1em] text-dim">· Keeper</span>
          )}
        </span>
        <Headline h={headline} />
      </div>
      {facts.length > 0 && (
        <MetaLine className="mt-2.5">
          {facts.map((f) => (
            <Meta key={f.label} label={f.label} tone={f.tone}>{f.value}</Meta>
          ))}
        </MetaLine>
      )}
    </EntryCard>
  );
}

function OwnerGroup({
  owner, rank, totalOwners, picks, graded, hasBaseline, baselineLabel, hasProjected, hasVerdicts,
}: {
  owner: DraftBoardOwner; rank: number; totalOwners: number; picks: DraftBoardPick[];
  graded: boolean; hasBaseline: boolean; baselineLabel: string; hasProjected: boolean;
  hasVerdicts: boolean;
}) {
  const [open, setOpen] = useState(false);
  const bodyId = `draft-owner-${owner.user_id}`;

  const headline = ownerHeadlineFor(graded, owner.points_above_round, owner.adp_total_delta);

  return (
    <EntryCard className="p-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="tap flex w-full min-h-tap items-center gap-2.5 px-3.5 py-3 text-left"
      >
        <span className="min-w-0 flex-1 truncate font-display text-name font-bold tracking-[-0.01em] text-ink">
          {ownerName(owner.owner, owner.user_id)}
        </span>
        <Headline h={headline} />
        <Mark name={open ? "open" : "closed"} size={13} className="shrink-0 text-dim" />
      </button>

      <div className="px-3.5 pb-3">
        <MetaLine>
          {/* The desktop table's own `#` column — a FIXED fact about the
              owner (PAR once graded, ADP total delta otherwise), read from
              `DraftPicksMobile`'s `rankOf` map rather than this card's
              position in whatever order `owners` is currently sorted into.
              Below 910px this is the only place it's reachable at all. */}
          <Meta label="Rank">{`${rank} of ${totalOwners}`}</Meta>
          <Meta label="Picks">{String(picks.length)}</Meta>
          {/* The denominator for the summed ADP delta: how many of this
              owner's picks could be scored on the ADP baseline. Gated on the
              same `adp_total_delta != null` check the desktop Owners table's
              `hasAdpColumns` already runs (`DraftBoard.tsx::OwnersSection`) —
              `owner_adp_grades` (`draft_baselines.py`) keys off the
              Sleeper-ADP-specific `adp_delta` field, which is always null on
              a dynasty rookie class (graded on rookie ECR instead). Rendering
              this unconditionally printed "Coverage 0 of 3" on a dynasty
              league's owner card — the exact dead figure a previous fix
              already removed from the desktop table, which this card had no
              test pinning it against. */}
          {owner.adp_total_delta != null && (
            <Meta label="Coverage">{`${owner.graded_picks} of ${owner.total_picks}`}</Meta>
          )}
          {/* The rest of the five-metric run — PAR is the headline above, so
              it isn't repeated here. Same figures the desktop Owners table
              carries as real columns. */}
          {graded && (
            <>
              <Meta label="Total">{owner.production_total.toFixed(1)}</Meta>
              <Meta label="Start %">{startPctText(owner.production_started, owner.production_total)}</Meta>
              <Meta label="Reg">{(owner.production_regular ?? 0).toFixed(1)}</Meta>
              <Meta label="Playoff">{(owner.production_playoff ?? 0).toFixed(1)}</Meta>
              <Meta label="Toilet">{(owner.production_toilet ?? 0).toFixed(1)}</Meta>
            </>
          )}
          {/* The desktop table's Hit/Bust column. Unlike that column this card
              carries it even when the class also has ADP figures — a Meta
              costs no grid track, so the width trade that keeps Hit/Bust off
              `OWNER_GRID_GRADED_ADP` simply doesn't apply here. Counted from
              the same per-pick verdicts rendered in the expanded body below,
              so the two always agree. Omitted, not zeroed, when nothing in
              the owner's class could be judged. */}
          {graded && hasVerdicts
            && ((owner.hit ?? 0) + (owner.average ?? 0) + (owner.bust ?? 0)) > 0 && (
            <Meta label="Hit/Bust">{`${owner.hit ?? 0} / ${owner.bust ?? 0}`}</Meta>
          )}
          {/* Graded AND carrying an ADP figure: the headline above has already
              swapped to PAR, so — unlike the ungraded case, where ADP +/- IS
              the headline — this is the only place on the card the ADP delta
              still shows. Matches the desktop table's `OWNER_GRID_GRADED_ADP`
              template, which keeps ADP +/- as a real ninth column once graded. */}
          {graded && owner.adp_total_delta != null && (
            <Meta label="ADP +/-" tone={toneOf(owner.adp_total_delta)}>{signed(owner.adp_total_delta)}</Meta>
          )}
        </MetaLine>
      </div>

      <div id={bodyId} hidden={!open} className="border-t border-rule bg-surface-sunk px-3 py-3">
        <CardList>
          {picks.map((p) => (
            <PickCard
              key={`${p.pick_no}-${p.player_id}`}
              p={p}
              graded={graded}
              hasBaseline={hasBaseline}
              baselineLabel={baselineLabel}
              hasProjected={hasProjected}
              hasVerdicts={hasVerdicts}
              showOwner={false}
            />
          ))}
        </CardList>
      </div>
    </EntryCard>
  );
}

export function DraftPicksMobile({
  picks, owners, rankOf, graded, hasBaseline, baselineLabel, hasProjected, hasVerdicts,
}: Props) {
  const [view, setView] = useState<View>("owner");

  const byOwner = useMemo(() => {
    const m = new Map<string, DraftBoardPick[]>();
    for (const p of picks) {
      const uid = String(p.drafter_id ?? "");
      const list = m.get(uid);
      if (list) list.push(p);
      else m.set(uid, [p]);
    }
    return m;
  }, [picks]);

  return (
    <div>
      {/* Pick ORDER is not lost, it is one tap away. A draft board answers two
          questions — "how did each manager draft" and "what went when" — and
          grouping only serves the first, so the second keeps a first-class
          route to it rather than being traded away. */}
      <div className="mb-3">
        <SegmentControl<View>
          aria-label="Group draft picks"
          options={[{ key: "owner", label: "By owner" }, { key: "pick", label: "By pick" }]}
          value={view}
          onChange={setView}
        />
      </div>

      {view === "owner" ? (
        <CardList>
          {owners.map((o, i) => (
            <OwnerGroup
              key={o.user_id}
              owner={o}
              // Fixed PAR/ADP rank, not this card's position in whatever
              // order `owners` is currently sorted into. `?? i + 1` is a
              // defensive fallback only — `rankOf` is built from this same
              // owner set by `DraftBoard.tsx`, so every id resolves.
              rank={rankOf.get(o.user_id) ?? i + 1}
              totalOwners={owners.length}
              picks={byOwner.get(o.user_id) ?? []}
              graded={graded}
              hasBaseline={hasBaseline}
              baselineLabel={baselineLabel}
              hasProjected={hasProjected}
              hasVerdicts={hasVerdicts}
            />
          ))}
        </CardList>
      ) : (
        <CardList>
          {picks.map((p) => (
            <PickCard
              key={`${p.pick_no}-${p.player_id}`}
              p={p}
              graded={graded}
              hasBaseline={hasBaseline}
              baselineLabel={baselineLabel}
              hasProjected={hasProjected}
              hasVerdicts={hasVerdicts}
              showOwner
            />
          ))}
        </CardList>
      )}
    </div>
  );
}
