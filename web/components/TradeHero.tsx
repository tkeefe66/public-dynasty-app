import { LensMargins, LensWinners, TradeCall, TradeSideView, TradeStory } from "@/lib/types";
import { fmtDateShort } from "@/lib/format-date";
import { fmtLensMargin, LENS_LABEL_LOWER, LENS_ORDER, soleDecidedLens } from "@/lib/trade-lens";

export interface TradeHeroProps {
  date: string;
  sides: TradeSideView[];
  story: TradeStory | null | undefined;
  /** Legacy received-Trade-Value magnitude (0..1) — the only thing it still
   *  drives is the Lopsided/Edge qualifier word under a unanimous ruling; who
   *  won comes from `call`/`winnersByLens` instead (they can legitimately
   *  disagree with this scalar when a flip changes who holds the value). */
  lopsidedness: number;
  winnersByLens: LensWinners;
  marginsByLens: LensMargins;
  call: TradeCall;
  lensTally: string;
  /** Optional share affordance (the copy-receipt button). */
  receipt?: React.ReactNode;
}

/* ---------------------------------------------------------------------------
 * TradeHero — design_handoff_agate/CLAUDE_CODE.md § Commit 4.
 *
 * Kicker is the date only. Headline is the two owner names joined with "V.",
 * Archivo 900 uppercase 33px. The ruling stamp sits on the right: three
 * states (unanimous / split / none) read straight off the API's
 * `winners_by_lens` / `margins_by_lens` / `call` / `lens_tally` — never
 * recomputed here (DESIGN.md § "Figures Reconcile").
 *
 * Instrument Serif is fully retired from this page: no serif verdict
 * headline, no serif "beat"/"vs" connector. The owner-v-owner headline plus
 * the ruling stamp together replace both.
 *
 * Stamp Direction B: a decided ruling (unanimous/split) is one of the four
 * sanctioned stamp surfaces — the "ruling-stamp header". Trade.dc.html /
 * Dashboard.dc.html / Mobile.dc.html / stamp-navy.html all draw the whole
 * card as `background: var(--stamp)` with no outer border (the fill does
 * the separating); kicker at ~70% stamp-ink, body copy at ~90%, and the
 * footer badge divided by a stamp-ink rule rather than `--rule` (`--rule`
 * has no drawn value against the stamp ground). The undecided "none" state
 * has no drawn stamp treatment anywhere in the handoff, so it keeps its
 * existing border-rule/text-dim de-emphasis unchanged.
 *
 * Signed color (`--pos`/`--neg`) belongs on ledger figures, not inside the
 * stamp — the margin figures in the unanimous/split rulings render in plain
 * stamp-ink prose (inherited, no color override), matching the drawn
 * templates. `--pos` on the stamp-navy fill also fails 3:1 non-text contrast
 * in light mode (#15803d on #172a44 ≈ 2.9:1).
 * ------------------------------------------------------------------------ */

function ownerName(sides: TradeSideView[], uid: string | null | undefined): string {
  return sides.find((s) => s.user_id === uid)?.owner_name ?? uid ?? "—";
}

// ---------- the ruling stamp ----------

function RulingStamp({
  sides, winnersByLens, marginsByLens, call, lensTally, lopsidedness,
}: {
  sides: TradeSideView[];
  winnersByLens: LensWinners;
  marginsByLens: LensMargins;
  call: TradeCall;
  lensTally: string;
  lopsidedness: number;
}) {
  // ONE decided lens is not a sweep, so it does not get sweep language. `call`
  // is "unanimous" whenever every DECIDED lens went to one side — including
  // when only one lens could be decided, which is the normal state of a trade
  // nobody has played yet: all four production lenses sit at 0 for both sides
  // and are unscored. This branch must come FIRST, before the unanimous one it
  // would otherwise fall into.
  //
  // The copy says "ahead", not "won", and never claims a cause: all-zero
  // production also happens when the assets simply never scored, and the
  // payload cannot distinguish that from no games having been played.
  const sole = soleDecidedLens(winnersByLens);
  if (sole) {
    const uid = winnersByLens[sole]!;
    return (
      <div className="w-full min-[701px]:w-[240px] shrink-0 rounded-panel bg-stamp px-[18px] py-4 text-stamp-ink">
        <div className="font-mono text-label font-bold uppercase tracking-[0.16em] text-stamp-ink-dim pt-1.5">
          Ruling
        </div>
        <div
          className={`break-words font-display font-extrabold leading-none tracking-[var(--track-nameplate)] pt-1 ${stampNameSize(ownerName(sides, uid))}`}
        >
          {ownerName(sides, uid)}
        </div>
        <div className="text-figure leading-[1.35] text-stamp-ink-dim pt-1 pb-2.5">
          ahead by{" "}
          <span className="font-mono font-semibold tabular">
            {fmtLensMargin(sole, marginsByLens[sole])}
          </span>{" "}
          {LENS_LABEL_LOWER[sole]}. No points on the board yet.
        </div>
        <div className="mt-2 border-t border-stamp-lit pt-2 font-mono text-label font-bold uppercase tracking-[0.15em] text-stamp-ink-dim">
          {LENS_LABEL_LOWER[sole]} only
        </div>
      </div>
    );
  }

  if (call === "unanimous") {
    const winnerUid = LENS_ORDER.map((l) => winnersByLens[l]).find((v): v is string => !!v)!;
    const decided = LENS_ORDER.filter((l) => winnersByLens[l] === winnerUid && marginsByLens[l] != null);
    const badge = lopsidedness >= 0.6 ? "Lopsided" : "Edge";
    return (
      <div className="w-full min-[701px]:w-[240px] shrink-0 rounded-panel bg-stamp px-[18px] py-4 text-stamp-ink">
        <div className="font-mono text-label font-bold uppercase tracking-[0.16em] text-stamp-ink-dim pt-1.5">
          Ruling
        </div>
        {/* The stamp is a fixed 196px block at ≥701px, and a long owner name set
            at 26px does not fit it: the name overflowed its box and cascaded a
            ~79px horizontal overflow onto the whole document at 768–1180
            (caught by e2e/viewport.spec.ts). The size steps down by name length
            so the ruling still names the winner at display size instead of
            breaking a handle mid-word; `break-words` is the backstop for a name
            longer than any step anticipates. */}
        <div
          className={`break-words font-display font-extrabold leading-none tracking-[var(--track-nameplate)] pt-1 ${stampNameSize(ownerName(sides, winnerUid))}`}
        >
          {ownerName(sides, winnerUid)}
        </div>
        <div className="text-figure leading-[1.35] text-stamp-ink-dim pt-1 pb-2.5">
          won it by{" "}
          {decided.map((l, i) => (
            <span key={l}>
              <span className="font-mono font-semibold tabular">
                {fmtLensMargin(l, marginsByLens[l])}
              </span>{" "}
              {LENS_LABEL_LOWER[l]}
              {i < decided.length - 2 ? ", " : i === decided.length - 2 ? " and " : ""}
            </span>
          ))}
          .
        </div>
        <div className="mt-2 border-t border-stamp-lit pt-2 font-mono text-label font-bold uppercase tracking-[0.15em] text-stamp-ink-dim">
          {badge}
        </div>
      </div>
    );
  }

  if (call === "split") {
    const winningUids = Array.from(
      new Set(LENS_ORDER.map((l) => winnersByLens[l]).filter((v): v is string => !!v)),
    );
    return (
      <div className="w-full min-[701px]:w-[240px] shrink-0 rounded-panel bg-stamp px-[18px] py-4 text-stamp-ink">
        <div className="font-mono text-label font-bold uppercase tracking-[0.16em] text-stamp-ink-dim pt-1.5">
          Ruling
        </div>
        {winningUids.map((uid) => {
          const lenses = LENS_ORDER.filter((l) => winnersByLens[l] === uid);
          return (
            <div key={uid} className="flex items-baseline justify-between gap-2 pt-1.5">
              <span className="font-display text-name font-extrabold leading-none tracking-[var(--track-name)] truncate">
                {ownerName(sides, uid)}
              </span>
              <span className="font-mono text-figure font-semibold tabular whitespace-nowrap shrink-0">
                {lenses
                  .map((l) => `${fmtLensMargin(l, marginsByLens[l])} ${LENS_LABEL_LOWER[l]}`)
                  .join(", ")}
              </span>
            </div>
          );
        })}
        <div className="text-prose leading-[1.35] opacity-90 pt-1.5 pb-2.5">
          The lenses disagree. Nobody gets the headline.
        </div>
        <div className="border-t border-stamp-lit font-mono text-label font-bold uppercase tracking-[0.14em] py-1.5">
          Split · {lensTally}
        </div>
      </div>
    );
  }

  // "none" — nothing decided: every scored lens tied, or nothing scored.
  return (
    <div className="w-full min-[701px]:w-[196px] shrink-0 border border-rule">
      <div className="font-mono text-label font-bold uppercase tracking-[0.16em] text-dim pt-1.5">
        Ruling
      </div>
      <div className="font-display text-lead font-extrabold leading-none tracking-[var(--track-lead)] text-dim pt-1">
        Nobody
      </div>
      <div className="text-figure leading-[1.35] text-body pt-1 pb-2.5">
        No lens decided it — every scored lens tied, or nothing scored at all.
      </div>
      <div className="border-t border-rule font-mono text-label font-bold uppercase tracking-[0.16em] text-dim py-1.5">
        Too close
      </div>
    </div>
  );
}

// ---------- main component ----------

/** Display size for the ruling stamp's winner name, stepped by length so it
 *  fits the drawn 196px block. Twelve characters is where 26px starts to
 *  overflow at ≥701px; the second step covers the longest Sleeper handles. */
function stampNameSize(name: string): string {
  if (name.length > 16) return "text-[length:var(--nameplate-4-sm)]";
  if (name.length > 11) return "text-[length:var(--nameplate-3-sm)]";
  return "text-[length:var(--nameplate-2-sm)]";
}

export function TradeHero({
  date, sides, story, lopsidedness, winnersByLens, marginsByLens, call, lensTally, receipt,
}: TradeHeroProps) {
  const headline = sides.length >= 2
    ? `${sides[0].owner_name} V. ${sides[1].owner_name}`
    : (sides[0]?.owner_name ?? "");

  const hasBeats = !!(story?.beats && story.beats.length > 0);
  const bodyParagraphs =
    !hasBeats && story?.body
      ? story.body
          .split(/\n\s*\n/)
          .map((p) => p.trim())
          .filter(Boolean)
      : [];

  return (
    <section className="border-b-[3px] border-ink pb-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="font-mono text-label uppercase tracking-[0.12em] text-dim">
          {fmtDateShort(date)}
        </div>
        {receipt}
      </div>

      <div className="flex flex-col min-[701px]:flex-row items-start justify-between gap-5">
        <div className="min-w-0 flex-1">
          <h1 className="mt-1.5 font-display text-[length:var(--nameplate-2-sm)] sm:text-nameplate font-extrabold leading-[0.98] tracking-[var(--track-nameplate)] max-w-[20ch]">
            {headline}
          </h1>

          {hasBeats ? (
            <>
              {story?.lede && (
                <p className="mt-2.5 max-w-[50ch] text-prose leading-[1.55] text-body">{story.lede}</p>
              )}
              <ul className="mt-1.5 flex list-none flex-col gap-1 p-0">
                {story!.beats!.map((beat, i) => (
                  <li
                    key={i}
                    className="relative pl-3 text-prose leading-[1.55] text-body before:absolute before:left-0 before:content-['·'] before:text-dim"
                  >
                    {beat}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            bodyParagraphs.length > 0 && (
              <div className="mt-2.5 flex flex-col gap-2">
                {bodyParagraphs.map((p, i) => (
                  <p key={i} className="max-w-[50ch] text-prose leading-[1.55] text-body">
                    {p}
                  </p>
                ))}
              </div>
            )
          )}
        </div>

        <RulingStamp
          sides={sides}
          winnersByLens={winnersByLens}
          marginsByLens={marginsByLens}
          call={call}
          lensTally={lensTally}
          lopsidedness={lopsidedness}
        />
      </div>
    </section>
  );
}
