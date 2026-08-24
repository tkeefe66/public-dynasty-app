"use client";

import { FranchiseRating, OwnerDetailResp, ProseSegment, RankView, TrackRecord } from "@/lib/types";
import { Emphasis, isEmphasisKind } from "@/components/furniture/Emphasis";
import { StatStrip } from "./ui";
import { franchiseLetterTone, ordinal, ownerIdentitySlot } from "./util";

/* ---------------------------------------------------------------------------
 * Agate — the franchise hero (design_handoff_agate/DESIGN.md § "Named rules";
 * CLAUDE_CODE.md § Commit 6; Agate System.dc.html Fig. 6.1/6.4). Owner name is
 * Archivo 900 uppercase — plain text, no avatar (avatars are Commit 7's
 * OwnerLabel rebuild; the drawn hero doesn't show one). The rating "receipt"
 * that used to hide behind a tap is gone — the number, rank, and trend are
 * always visible in the right rail now (DESIGN.md § "Show The Evidence,
 * Don't Link To It": the figures answer the question without a second
 * destination), so `onSeeOverview` is retired along with it.
 * ------------------------------------------------------------------------ */

/** `Titles 🏆 1 · Playoff trips 5/7 · Record 61–42 · Best finish 1st` as
 *  labelled cells on one rule — two rules of two under 700px, where four
 *  cells cannot hold a letterspaced label and its figure. Best finish stays
 *  plain ink even at 1st: DESIGN.md § "The Signed Number" reserves --pos/
 *  --neg for signed values and grade letters, not categorical outcomes. */
function RingsStrip({ tr }: { tr: TrackRecord }) {
  const record = `${tr.career_wins}-${tr.career_losses}${tr.career_ties ? `-${tr.career_ties}` : ""}`;
  const cells = [
    { label: "Titles", value: tr.titles > 0 ? `🏆 ${tr.titles}` : "—" },
    { label: "Playoff trips", value: `${tr.playoff_appearances} / ${tr.seasons_played}` },
    { label: "Record", value: record },
    { label: "Best finish", value: tr.best_finish ? ordinal(tr.best_finish) : "—" },
  ];
  const cell = (c: (typeof cells)[number]) => (
    <div key={c.label} className="flex items-baseline gap-1.5 min-w-0">
      <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-label uppercase tracking-[0.11em] text-dim">
        {c.label}
      </span>
      <span className="flex-none whitespace-nowrap font-mono text-figure font-semibold tabular">{c.value}</span>
    </div>
  );
  return (
    // `--pad` (18px, panel spacing), not the 9px sibling `--gap` — this strip
    // is a Panel in its own right sitting below the nameplate block, not a
    // sibling chip within one, so it earns the larger of the two rhythm steps.
    <div className="mt-[var(--pad)]">
      {/* One render. Agate needed two — a 4-up and a hand-split 2-up — because
          `.ruled > *` clamped the strip to a single 26px rule and it clipped at
          phone width. A Panel row grows, so only the column count changes, and
          the two variants can no longer disagree about cell order. */}
      <StatStrip>{cells.map(cell)}</StatStrip>
    </div>
  );
}

/** Right rail: the grade LETTER, alone.
 *
 *  It carried a receipt underneath for one release — roster rank, the rating
 *  and its trend, and the biggest-drag signal — on the argument that a bare
 *  letter is a verdict a reader cannot check. The owner reviewed that live and
 *  wanted the letter to stand by itself: four mono figures stacked under a
 *  44px letter read as a caption competing with the verdict, and the argument
 *  they were answering is answered better in prose. The franchise blurb below
 *  the rings strip is where the explanation lives now, and the Overview tab
 *  still holds every figure with its contribution attached.
 *
 *  `aria-label` keeps the rank available to a screen reader — with the visible
 *  receipt gone there is no other route to it in this band. */
function VerdictRail({ fr }: { fr: FranchiseRating }) {
  return (
    <div className="shrink-0 text-right">
      <span
        aria-label={`Grade ${fr.letter}, ranked ${fr.rank} of ${fr.of} rated`}
        className={`font-display text-[length:var(--nameplate-2-sm)] min-[701px]:text-[length:var(--nameplate-1)] font-extrabold leading-[0.9] tracking-[var(--track-nameplate)] ${franchiseLetterTone(fr.letter)}`}
      >
        {fr.letter}
      </span>
    </div>
  );
}

/** The same rail when there is no rating to show.
 *
 *  A franchise with no completed season behind it is unrated — the API drops
 *  it from the rating population entirely rather than scoring it on zeros
 *  (`franchise_redesign.rated_owners`). So this renders the absence with the
 *  reason next to it: `first season` when the league itself has played
 *  nothing, `new franchise` when a replacement manager holds a roster he did
 *  not build. Roster rank stays — it is a census fact about today's roster,
 *  not a verdict on anyone's record. */
function AbsentVerdictRail({
  reason, rosterRank,
}: { reason: string; rosterRank?: RankView | null }) {
  const caption = reason === "first_season" ? "first season" : "new franchise";
  return (
    <div className="shrink-0 text-right">
      <span
        aria-label={`No Franchise Rating yet — ${caption}`}
        className="font-display text-[length:var(--nameplate-2-sm)] min-[701px]:text-[length:var(--nameplate-1)] font-extrabold leading-[0.9] tracking-[var(--track-nameplate)] text-dim"
      >
        —
      </span>
      <div className="mt-1 font-mono text-label uppercase tracking-[0.11em] text-dim">
        {rosterRank && <div>ROSTER #{rosterRank.rank} OF {rosterRank.of}</div>}
        <div>{caption}</div>
      </div>
    </div>
  );
}

/** The blurb's body, one element per emphasis run.
 *
 *  THE SHAPE IS THE SECURITY PROPERTY. The model writes inline marks
 *  (`[num]73%[/num]`), the server parses them into `{text, mark}` segments, and
 *  this maps each to an element — so React escapes every character and there is
 *  no `dangerouslySetInnerHTML` on this path. Handing the browser a marked-up
 *  string and letting it parse would be a shorter route to the same picture and
 *  is the thing this shape exists to foreclose.
 *
 *  A mark the component does not know is prose, not an error: `isEmphasisKind`
 *  narrows at the boundary, so a blurb cached by a future build that adds a
 *  fifth mark still reads correctly here, one treatment short. */
function ReadBody({ segments }: { segments: ProseSegment[] }) {
  return (
    <>
      {segments.map((seg, i) =>
        isEmphasisKind(seg.mark) ? (
          <Emphasis key={i} kind={seg.mark}>
            {seg.text}
          </Emphasis>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </>
  );
}

/** The letter's explanation, in a panel of its own.
 *
 *  A lead sentence at `--text-lead` in the display face carries the verdict; the
 *  body sets at prose size underneath with four kinds of emphasis inside it (see
 *  `Emphasis` for why colour is confined to the two valence marks).
 *
 *  Its own white `--surface` panel rather than more copy on the identity-tinted
 *  band: the band is the franchise's colour, and prose that has to be read
 *  rather than glanced at earns paper.
 *
 *  A pre-marks cached blurb has no lead and no segments and renders as plain
 *  prose in the same panel — an older blurb is prose, never an empty panel. */
function ReadPanel({
  lead, blurb, segments,
}: {
  lead?: string | null;
  blurb?: string | null;
  segments?: ProseSegment[] | null;
}) {
  if (!lead && !blurb && !segments?.length) return null;
  // No mono label above this panel. It had one ("The read") on the theory that
  // a named block reads as deliberate rather than as loose text; on the page it
  // just added a row of chrome above a paragraph that already announces itself
  // — the panel edge is the boundary and the lead is the heading. Every other
  // panel in this hero labels FIGURES, which need naming; prose does not.
  return (
    <div className="mt-[var(--pad)] rounded-panel bg-surface shadow-panel px-5 py-4">
      {lead && (
        <div className="font-display text-lead font-bold tracking-[var(--track-lead)] leading-[1.18] text-ink text-balance max-w-[30ch]">
          {lead}
        </div>
      )}
      {/* leading-[1.72], looser than prose sets anywhere else in the app, and
          deliberately: a `num` mark draws a 1.5px hairline 1px under its
          baseline, and at a snug leading that rule lands on the descenders of
          the line above it. The emphasis is the reason the leading is wrong
          for prose in isolation — do not "fix" it back to snug. */}
      {(segments?.length || blurb) && (
        <div className="mt-2 text-prose leading-[1.72] text-body max-w-[66ch]">
          {segments?.length ? <ReadBody segments={segments} /> : blurb}
        </div>
      )}
    </div>
  );
}

export function HeroBand({
  detail, archetype, rivalNames, roast, editAffordance,
}: {
  detail: OwnerDetailResp;
  archetype?: string;
  rivalNames: string[];
  roast?: string;
  editAffordance?: React.ReactNode;
}) {
  const fr = detail.franchise_rating;
  const tr = detail.track_record;

  // Franchise identity: a stable owner_id -> slot mapping picks one of the
  // six `--id-N` hues (colors.css). 13% tint of the full value is the hero's
  // ground; the full value is the 5px edge — identity is never used on a
  // figure, bar, series, or the grade letter itself (VerdictRail below is
  // untouched). `color-mix` needs an inline style — awkward as a Tailwind
  // arbitrary value — but it points at `var(--id-N)`, never a literal hex,
  // so it isn't a raw-hex violation.
  const idVar = `var(--id-${ownerIdentitySlot(detail.user_id)})`;

  return (
    <header
      className="relative overflow-hidden rounded-panel shadow-panel mt-[length:var(--pad)] pl-[30px] pr-[26px] py-6"
      style={{ background: `color-mix(in srgb, ${idVar} 13%, var(--surface))` }}
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[5px]" style={{ background: idVar }} />
      <div className="flex items-start justify-between gap-5">
        <div className="min-w-0">
          <h1 className="font-display text-lead min-[701px]:text-nameplate font-extrabold tracking-[-0.034em] leading-[0.95]">
            {detail.owner.owner_name}
          </h1>
          {(archetype || rivalNames.length > 0) && (
            <div className="mt-1.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
              {archetype}
              {archetype && rivalNames.length > 0 && " · "}
              {rivalNames.length > 0 && `rivals ${rivalNames.join(", ")}`}
            </div>
          )}
          {roast && <div className="mt-1.5 text-figure italic text-dim leading-snug max-w-[48ch]">&ldquo;{roast}&rdquo;</div>}
        </div>
        <div className="flex items-start gap-2 shrink-0">
          {fr ? (
            <VerdictRail fr={fr} />
          ) : detail.unrated_reason ? (
            <AbsentVerdictRail reason={detail.unrated_reason} rosterRank={detail.roster_rank} />
          ) : null}
          {editAffordance}
        </div>
      </div>

      {tr && tr.seasons_played > 0 && <RingsStrip tr={tr} />}

      {/* The letter's explanation. With the mono receipt gone from the rail
          this is the only thing on the band that says WHY the grade reads the
          way it does, so it sits in the hero rather than a tab. */}
      <ReadPanel
        lead={detail.franchise_lead}
        blurb={detail.franchise_blurb}
        segments={detail.franchise_segments}
      />
    </header>
  );
}
