import { ContributionRow, fmtPts } from "@/components/RatingBars";
import { Panel } from "@/components/furniture/Panel";
import { Row } from "@/components/furniture/Row";
import { SectionHead } from "@/components/furniture/SectionHead";
import { MethodologySection } from "./MethodologySection";
import { SAMPLE, SECTIONS } from "./sample";
import generatedBands from "../../.generated/letter-bands.json";

/* ---------------------------------------------------------------------------
 * Methodology, set as a document rather than an app screen. Ported to
 * Furniture — the first screen off the retired Agate ground.
 *
 * What changed, and why each one is a rule rather than a preference:
 *
 *  - Section headings are Bricolage 700 in MIXED CASE, not Archivo 900
 *    uppercase. The shouting was the diagnosis, and the case carries as much of
 *    it as the face does.
 *  - The arithmetic blocks moved off `.ruled` onto `Panel` + `Row`. A Panel is
 *    solid, so each Row draws its own `--rule` hairline; under Agate the
 *    stripes were the dividers and a row that drew one was a bug. Exactly
 *    inverted.
 *  - Every size now comes off the seven-step scale (`text-section`, `text-name`,
 *    `text-figure`, `text-label`). The ad-hoc 20/14/13/11/10.5/9/8px this file
 *    used were sizes someone eyeballed.
 *
 * Unchanged: prose-entry lists (the five metrics, the supporting columns) still
 * take the heading-over-hairline form rather than a ledger, because a paragraph
 * cannot ellipsise to one line and still be a definition. That rule survived the
 * remodel; only the ground beneath the arithmetic blocks changed.
 *
 * PHONE LAYOUT. Every section is a `MethodologySection`: unchanged prose under a
 * `SectionHead` at ≥701px, a collapsed 44px disclosure row at ≤700px. Read that
 * file for why the breakpoint is CSS rather than `matchMedia`. Two consequences
 * land here — the spine down sections 1–3 and the 64px inter-section rhythm are
 * both desktop-only, because on a phone the sections are a flush ruled list, and
 * an indent on three of eight rows would break it.
 * ------------------------------------------------------------------------ */

/** A sub-heading for one entry in a prose list, with its formula on the right. */
function EntryHead({ title, formula }: { title: string; formula?: string }) {
  return (
    <SectionHead
      level={3}
      title={title}
      action={formula ? <Formula>{formula}</Formula> : undefined}
    />
  );
}

/** An aside: mono kicker, then prose. Formerly a tinted, rounded callout. */
function Aside({ kicker, children }: { kicker: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 border-t border-rule pt-2">
      <div className="font-mono text-label uppercase tracking-[0.16em] text-dim">{kicker}</div>
      <div className="mt-1.5 max-w-[68ch] text-prose leading-relaxed text-body">{children}</div>
    </div>
  );
}

// Shared scale for pillar bars: max |contribution| across pillars
const PILLAR_SCALE = Math.max(...SAMPLE.pillars.map((p) => Math.abs(p.contribution)), 1);

/* Letter bands: delta from 1500, inclusive lower bound. Generated from the
 * engine — `scripts/gen_letter_bands.py` writes web/.generated/letter-bands
 * .json from `gm_rating.LETTER_BANDS`, and this constant just re-exports that
 * JSON rather than re-typing it.
 *
 * Two DIFFERENT guarantees, not one, and they live on opposite sides of the
 * language boundary — neither substitutes for the other:
 *  - tests/test_letter_bands_export.py (pytest) is what actually prevents
 *    this page's numbers from diverging from the engine's: it compares the
 *    checked-in JSON against the LIVE `gm_rating.LETTER_BANDS` array. This is
 *    the real cross-language guard, and it's the one that runs in CI.
 *  - web/tests/methodology-bands.test.ts compares this constant to the SAME
 *    JSON file it's re-exported from, so it cannot detect engine drift — it
 *    would pass even if the JSON were stale. What it guards against is
 *    narrower: someone reintroducing a hand-typed array here later instead of
 *    this re-export. A tripwire, not a drift check.
 * A staleness that only the pytest side would catch is: change gm_rating.py,
 * forget to rerun the generator. A regression that only the vitest side would
 * catch is: someone deletes this JSON import and pastes the old literal array
 * back in.
 *
 * The engine's own array stops at D — D− is the implicit catch-all for
 * everything below D's floor (see gm_rating.py::rating_to_letter's fallback
 * return), not a banded entry — so it is added as a derived row below rather
 * than a 12th hand-typed line here. */
export const LETTER_BANDS: { letter: string; delta: number }[] = generatedBands;

/** ASCII "-" (the engine's own alphabet) rendered as a typographic minus for
 *  display. The exported LETTER_BANDS above must stay byte-for-byte what the
 *  engine emits — this is purely a render-time cosmetic, applied wherever a
 *  grade letter is shown. */
function prettyLetter(letter: string): string {
  return letter.replace(/-/g, "−");
}

/** A formula or code token: mono text on a `--rule` underline, never a boxed
 *  chip. */
function Formula({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-b border-rule font-mono text-figure text-dim">{children}</span>
  );
}

/** The recurring sample owner, formerly a card. Now the running head of each
 *  section: name · letter · rating, then the pillar contributions as
 *  labelled figures on one rule. */
function SampleCard() {
  const pillars = SAMPLE.pillars;
  return (
    /* Was one fixed-height `.ruled` rule holding four `flex-wrap` items. The
     * wrap put a second line 9.5px outside the row box, painting over whatever
     * followed — measured, and it spilled worse at Agate's 26px pitch (40px of
     * overhang) than at Furniture's 40px. A Row sets `min-height` rather than
     * `height`, and the pillars are their own grid tracks, so this now grows
     * instead of overflowing at any width. */
    <div className="mb-6">
      <Panel>
        <Row variant="head">
          <span className="font-bold text-ink">
            {SAMPLE.name} · {SAMPLE.letter} · {SAMPLE.rating.toLocaleString()}
          </span>
        </Row>
        <Row cols={`repeat(${pillars.length}, minmax(0,1fr))`}>
          {pillars.map((p) => (
            <span key={p.key} className="flex min-w-0 items-baseline gap-1.5">
              <span className="truncate text-label uppercase tracking-[0.11em] text-dim">
                {p.label}
              </span>
              <span
                className={`shrink-0 tabular ${p.contribution >= 0 ? "text-pos-strong" : "text-neg-strong"}`}
              >
                {fmtPts(p.contribution)}
              </span>
            </span>
          ))}
        </Row>
      </Panel>
    </div>
  );
}

// The engine's LETTER_BANDS stops at D (see the comment on the export above);
// D− is derived here as the implicit catch-all rather than hand-typed as a
// 12th entry, so the one place a delta could go stale twice stays a
// computation instead of a second copy.
const LOWEST_BAND = LETTER_BANDS[LETTER_BANDS.length - 1];
const DISPLAY_BANDS: { letter: string; delta: number }[] = [
  ...LETTER_BANDS,
  { letter: "D-", delta: LOWEST_BAND.delta },
];

// ─── Section 1: The verdict ───────────────────────────────────────────────────
function Verdict() {
  const delta = SAMPLE.rating - 1500;
  return (
    /* Every kicker below is DERIVED from the array it sits above, never typed:
       a count on the disclosure row is a headline figure, and a headline figure
       has to reconcile with the rows beneath it. */
    <MethodologySection
      id="verdict"
      title={SECTIONS[0].title}
      kicker={`${DISPLAY_BANDS.length} bands`}
    >
      <p className="mb-4 font-mono text-label uppercase tracking-[0.16em] text-dim">
        The Franchise letter
      </p>
      <SampleCard />
      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        The <span className="text-ink font-semibold">Franchise Rating</span> is your platform-wide owner verdict
        — one letter, your whole career. It is a number centered at{" "}
        <span className="text-ink font-semibold">1,500</span> (exactly league-average = a <strong>C</strong>),
        clamped between <span className="font-mono text-prose">800</span> and{" "}
        <span className="font-mono text-prose">2,200</span>, and mapped to a letter by fixed bands.
      </p>

      {/* The three things v2 makes true that the old page didn't say, or said
          the opposite of. Each corrects a specific claim the previous
          methodology page made about a model that has since been replaced. */}
      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        It is a <span className="text-ink font-semibold">percentile within your league</span>, not an absolute
        standard. Every signal that feeds it is z-scored against your own league-mates before it&rsquo;s weighted
        — so an A− in a league of casual managers and an A− in a league of sharks are the same number, not the
        same achievement. There is no cross-league scale, and there isn&rsquo;t going to be one: measuring you
        against strangers you&rsquo;ve never played would answer a different question than the one this letter
        answers.
      </p>
      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        The scale runs <span className="text-ink font-semibold">A+ to D−, with no F</span> — on purpose. A
        twelve-owner league&rsquo;s grades span roughly ±1.75 standard deviations end to end, so an F band could
        only ever sit inside that span (which would mean carving it out of D&rsquo;s territory rather than
        measuring anything real below it) or outside it, where nobody could ever earn it. Announcing a grade
        nobody can reach is dead ink, so the scale simply stops at D−.
      </p>
      <p className="mb-6 max-w-[68ch] text-prose leading-relaxed text-body">
        Results carry a <span className="text-ink font-semibold">two-season half-life</span> — last season
        counts more than the one before it, on a curve that halves every two years. The decay itself is
        well-founded: a franchise&rsquo;s results two seasons apart correlate at roughly the square of how much
        results one season apart do, which is the signature of a real, ongoing process rather than noise. But the
        specific number — two seasons, not one or three — is a{" "}
        <span className="text-ink font-semibold">chosen prior, not a measured one</span>. Three seasons of twelve
        owners isn&rsquo;t enough data to fit a half-life from, so this one was picked rather than estimated, and
        it will be revisited once there&rsquo;s more history to estimate it from.
      </p>
      <p className="mb-6 max-w-[68ch] text-prose leading-relaxed text-body">
        {SAMPLE.name} sits at{" "}
        <span className="font-mono font-bold">{SAMPLE.rating.toLocaleString()}</span>,
        which is <span className="font-mono">+{delta}</span> above center — landing him in the{" "}
        {prettyLetter(SAMPLE.letter)} band.
      </p>

      {/* The bands are a ledger. The sample owner's band was tinted `bg-pos/5`
          — a translucent colored ground, twice forbidden; it is marked by the
          `--ink` marker stripe and its named callout instead. A grade letter
          may carry tone; the ground may not. */}
      <div className="mb-1.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
        Letter bands — delta from 1,500
      </div>
      <Panel>
        {DISPLAY_BANDS.map(({ letter, delta: d }, i) => {
          const isSample = letter === SAMPLE.letter;
          const isFloor = i === DISPLAY_BANDS.length - 1; // D−, the implicit catch-all
          const prevDelta = i === 0 ? null : DISPLAY_BANDS[i - 1].delta;
          const sgn = (n: number) => (n >= 0 ? `+${n}` : `−${Math.abs(n)}`);
          const range = isFloor
            ? `below ${sgn(d)}`
            : prevDelta != null
            ? `${sgn(d)} to ${sgn(prevDelta - 1)}`
            : `≥ ${sgn(d)}`;
          return (
            /* `mine` is the stamp-marked variant — the row the reader is
             * looking for. Under Agate this was `.you-marker`, an ink inset on
             * a striped ground; the Row variant carries it now, and the letter
             * keeps --pos because a grade letter is one of the two things
             * allowed to wear colour. */
            <Row
              key={letter}
              variant={isSample ? "mine" : "body"}
              cols="34px minmax(0,1fr) auto"
            >
              <span
                className={`font-display text-name font-bold ${isSample ? "text-pos-strong" : "text-ink"}`}
              >
                {prettyLetter(letter)}
              </span>
              <span className="tabular">{range}</span>
              {isSample ? (
                <span className="text-label uppercase tracking-[0.11em]">
                  ← {SAMPLE.name}
                </span>
              ) : (
                <span />
              )}
            </Row>
          );
        })}
      </Panel>
    </MethodologySection>
  );
}

// ─── Section 2: The two pillars ──────────────────────────────────────────────
function Pillars() {
  const pillarDescs: Record<string, string> = {
    results:
      "What the franchise has actually achieved, luck-adjusted and weighted toward recent seasons: your all-play win rate, how deep your playoff runs go, and how much of your record schedule luck accounts for. The record still speaks first.",
    assets:
      "What the franchise holds right now and is building toward: current roster value as a share of the league's, how much of that value sits in players 25 or younger, and the market value of picks still on the shelf.",
  };
  return (
    <MethodologySection
      id="pillars"
      title={SECTIONS[1].title}
      kicker={`${SAMPLE.pillars.length} pillars`}
    >
      <SampleCard />
      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        <span className="text-ink font-semibold">Results</span> leads at 60% — what a franchise has actually
        achieved is the truest measure of it.{" "}
        <span className="text-ink font-semibold">Assets</span> (40%) is the forward-looking half: what you hold
        today and how well-positioned you are to keep winning. There is no separate Skill pillar in this version
        — trading, drafting, and lineup management aren&rsquo;t graded on their own anymore. They only move your
        letter once they&rsquo;ve actually produced a better record or a stronger roster, not before.
      </p>
      <div className="space-y-3 mb-6">
        {SAMPLE.pillars.map((p) => (
          <div key={p.key}>
            <ContributionRow
              label={p.label}
              weight={p.weight}
              points={p.contribution}
              scale={PILLAR_SCALE}
            />
            <p className="mt-1 max-w-[68ch] pl-1 text-figure text-body">{pillarDescs[p.key]}</p>
          </div>
        ))}
      </div>
      <p className="max-w-[68ch] text-prose leading-relaxed text-body">
        Each bar above is {SAMPLE.name}&rsquo;s contribution to the final rating. The center axis is a
        league-average C; bars to the right add points, bars to the left subtract them.
      </p>
    </MethodologySection>
  );
}

// ─── Section 3: Inside each pillar ───────────────────────────────────────────
const SIGNAL_DEFS: Record<string, { def: string; formula?: string; extra?: React.ReactNode }> = {
  // Results — src/sleeper_dynasty/engine/results_signals.py
  expected_wins: {
    def: "All-play win rate — the record you'd have if you played every team, every week, instead of just your actual schedule. It's what's left of “quality of play” once your specific opponents are averaged out, recency-weighted so recent seasons count more.",
    formula: "all-play win% · recency-weighted",
  },
  playoff_success: {
    def: "How deep your playoff runs go, recency-weighted. A postseason berth alone is worth half a round win, so reaching the bracket counts for something even before you win a game there; each round won adds a full round win, and a championship adds a bonus on top.",
    formula: "berth ½ + rounds won + title bonus, recency-wtd",
    extra: (
      <Aside kicker={`Mini-example — one season for ${SAMPLE.name}`}>
        He made the playoffs (<span className="font-mono text-ink">+0.5</span>) and won one round before losing
        (<span className="font-mono text-ink">+1.0</span>) — <span className="font-mono text-ink">1.5</span> that
        season, before recency-weighting shrinks older seasons toward zero. A championship that year would have
        added another <span className="font-mono text-ink">1.5</span> on top.
      </Aside>
    ),
  },
  luck: {
    def: "Your actual record minus your all-play (expected) record — the part of your win total that schedule luck accounts for, rather than the quality of your lineup each week. It's orthogonal to Expected Wins by construction, so nothing here double-counts what that signal already measures.",
    formula: "actual win% − expected win%",
  },
  // Assets — src/sleeper_dynasty/engine/asset_signals.py
  roster_value_share: {
    def: "Your current roster's dynasty market value as a share of the whole league's — a scale-free read of how strong your active core is right now, next to everyone else's, rather than a raw number that means nothing on its own.",
    formula: "your roster value / league roster value",
  },
  young_core_share: {
    def: "The share of your OWN roster's value held by players 25 or younger. A straight average age can be dragged down by bench filler even when your best assets are young — this instead asks what fraction of what you actually own is young.",
    formula: "value in players ≤25 / total valued roster",
  },
  draft_capital: {
    def: "Tier-adjusted dynasty market value of all future rookie picks currently held. Weaker teams' earlier picks are worth more (higher upside). Always reflects today's holdings, not a fixed snapshot.",
    formula: "Σ value(held future picks, tier-adjusted)",
  },
};

function Signals() {
  const signalCount = SAMPLE.pillars.reduce((n, p) => n + p.signals.length, 0);
  return (
    <MethodologySection
      id="signals"
      title={SECTIONS[2].title}
      kicker={`${signalCount} signals`}
    >
      <SampleCard />
      <p className="mb-6 max-w-[68ch] text-prose leading-relaxed text-body">
        Each pillar is a weighted sum of signals. Every signal is z-scored across your league before
        weighting, so a win-rate edge and a roster-value edge land on the same scale. Below: plain-English
        definition, how it&rsquo;s measured, and {SAMPLE.name}&rsquo;s raw reading for each.
      </p>

      {SAMPLE.pillars.map((pillar) => {
        const pillarScale = Math.max(...pillar.signals.map((s) => Math.abs(s.contribution)), 1);
        return (
          <div key={pillar.key} className="mb-10">
            <div className="flex items-baseline gap-2 mb-4">
              <h3 className="font-display text-section font-bold tracking-[-0.024em]">{pillar.label}</h3>
              <span className="font-mono text-figure text-dim">
                {Math.round(pillar.weight * 100)}% of rating
              </span>
            </div>
            <div className="space-y-5">
              {pillar.signals.map((sig) => {
                const def = SIGNAL_DEFS[sig.key];
                return (
                  <div key={sig.key} className="border-l-2 border-rule pl-4">
                    <div className="flex flex-wrap items-baseline gap-2 mb-1">
                      <span className="text-prose font-semibold text-ink">{sig.label}</span>
                      <span className="font-mono text-figure text-dim">
                        {Math.round(sig.weight * 100)}% of {pillar.label}
                      </span>
                      {def?.formula && <Formula>{def.formula}</Formula>}
                    </div>
                    {def?.def && (
                      <p className="mb-2 max-w-[68ch] text-prose leading-relaxed text-body">{def.def}</p>
                    )}
                    <div className="mt-2">
                      <ContributionRow
                        label={`${SAMPLE.name}: ${sig.raw}`}
                        points={sig.contribution}
                        scale={pillarScale}
                        signal
                      />
                    </div>
                    {def?.extra}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </MethodologySection>
  );
}

// ─── Section 4: The trade metrics ────────────────────────────────────────────
const METRICS_DATA = [
  {
    name: "Trade Value",
    formula: "Σ realized value of received assets",
    desc: "Dynasty market value of what you received — each asset valued at what you sold it for (if flipped), today's market price (if still on your roster), or 0 (if dropped). This is a zero-sum swing: one side's gain equals the other's loss.",
  },
  {
    name: "Total Points",
    formula: "Σ received pts post-trade",
    desc: "Points scored by all received players since the trade — starters and bench alike, the bench-inclusive tally behind the trade detail page's production read.",
  },
  {
    name: "Started Points",
    formula: "Σ received started pts, every week",
    desc: "Points from starters only, across every week — what you actually deployed. The gap between this and Total Points is what sat on your bench. NOT the sum of the three phase metrics below: Playoff Points counts live title-path games only, so started points in a placement game or an eliminated week belong to no phase at all. Display-only — not a rating signal.",
  },
  {
    name: "Regular Season Points",
    formula: "Σ received started reg-season pts",
    desc: "Started points only, regular season weeks only (before your league's playoff week). A great pickup that never cracked the starting lineup shows as zero here — and Started Points above is where you see how often that happened. Display-only — not a rating signal.",
  },
  {
    name: "Playoff Points",
    formula: "Σ received started title-bracket pts",
    desc: "Started points in live championship-bracket games. Byes, eliminated weeks, and 3rd/5th-place games count zero. Often the sharpest read on whether a trade delivered when it mattered. Display-only — not a rating signal.",
  },
  {
    name: "Toilet Bowl Points",
    formula: "Σ received started losers-bracket pts",
    desc: "Started points in any losers-bracket game. Shown for color and analysis — not a Franchise Rating signal.",
  },
];

function Metrics() {
  return (
    <MethodologySection
      id="metrics"
      title={SECTIONS[3].title}
      kicker={`${METRICS_DATA.length} metrics`}
    >
      <SampleCard />
      <p className="mb-2 max-w-[68ch] text-prose leading-relaxed text-body">
        None of these feed the Franchise Rating directly — there is no Skill pillar in this version, so no trade
        signal is scored on its own. They power the trade detail page instead, and any real trading edge still
        surfaces there: it shows up in Results and Assets once it&rsquo;s actually produced a better record or a
        stronger roster, not before.{" "}
        <span className="text-ink font-semibold">Trade Value is a zero-sum swing</span>; the production
        metrics are <span className="text-ink font-semibold">received-only tallies</span> (no subtraction for
        what you gave up — each trade reads as a head-to-head).
      </p>

      {/* Five prose entries: each is a heading over a hairline with its formula
          on the right, then the definition. The old `divide-y` row borders are
          gone — a paragraph is too tall for the ruled ground. */}
      <div className="mb-8 mt-5 space-y-5">
        {METRICS_DATA.map((m) => (
          <div key={m.name}>
            <EntryHead title={m.name} formula={m.formula} />
            <p className="max-w-[68ch] text-prose leading-relaxed text-body">{m.desc}</p>
          </div>
        ))}
      </div>

      <div>
        <div className="border-b border-rule pb-1.5 font-mono text-label uppercase tracking-[0.16em] text-dim">
          How a trade&rsquo;s real outcome is traced
        </div>
        <p className="mb-3 mt-2 max-w-[68ch] text-prose leading-relaxed text-body">
          Each received asset has a journey: it was <span className="text-ink">kept</span>,{" "}
          <span className="text-ink">dropped</span>, or <span className="text-ink">flipped</span> to another
          team. Flipped assets are followed through a bounded lineage walk to their terminal players — the
          grade reflects what your haul ultimately became, not just what you first received.
        </p>
        <ul className="max-w-[68ch] space-y-1.5 text-prose leading-relaxed text-body">
          <li>
            <span className="text-ink font-medium">Asset journey</span> — per-player status: on-roster, dropped,
            or traded onward with full chain.
          </li>
          <li>
            <span className="text-ink font-medium">Became-grade</span> — the same five metrics recomputed on
            the terminal players your haul turned into via the lineage walk.
          </li>
          <li>
            <span className="text-ink font-medium">&ldquo;Did it pan out&rdquo; timeline</span> — cumulative production
            over tenure, chain-aware: a dropped asset&rsquo;s line stops at the drop, a flipped asset continues
            onto what it became.
          </li>
          <li>
            <span className="text-ink font-medium">Injury context</span> — games missed by phase (regular
            season vs playoffs) so a lost season to injury is visible alongside the production numbers.
          </li>
        </ul>
      </div>
    </MethodologySection>
  );
}

// ─── Section 5: The math ─────────────────────────────────────────────────────
function Math_() {
  const pillars = SAMPLE.pillars;
  const base = 1500;
  // Marcus's contributions are all positive — show plain magnitudes joined by
  // " + " so the assembly reads "1,500 + 132 + 42 = 1,674 → B".
  const contributions = pillars.map((p) => p.contribution).join(" + ");
  return (
    <MethodologySection id="math" title={SECTIONS[4].title}>
      <SampleCard />
      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        Every signal is <span className="text-ink font-semibold">z-scored across your league</span> before
        weighting — this puts dynasty market value and fantasy points on the same scale. A pillar&rsquo;s z is
        the weighted sum of its signal z&rsquo;s; the composite rating is built from the weighted pillar z&rsquo;s:
      </p>

      <div className="mb-4">
        <Formula>rating = clamp(1500 + SCALE · Σ(weight_pillar · z_pillar), 800, 2200)</Formula>
      </div>

      <p className="mb-4 max-w-[68ch] text-prose leading-relaxed text-body">
        One full league standard deviation of performance is worth <span className="font-mono text-ink">275</span>{" "}
        rating points, by design. <span className="font-mono text-ink">SCALE</span> stretches that further,
        because the composite itself — the weighted blend of pillar z-scores — is narrower than any single
        z-scored signal, the way an average of several imperfectly-correlated numbers always shrinks toward the
        center. SCALE corrects for that using an estimate of how spread the composite actually is, and that
        estimate is a <span className="text-ink font-semibold">placeholder carried over from the old model</span>{" "}
        — v2&rsquo;s own composite hasn&rsquo;t been measured yet. This page won&rsquo;t quote a precise SCALE
        value until that measurement lands; treat the formula as the mechanism, not a calibrated instrument, for
        now.
      </p>

      {/* Arithmetic that reconciles: every entry is a label and a figure, so
          this is a ledger. `total` carries the 2px ink rule and the sunk ground
          — and it NAMES what it totals, which is the rule that makes a headline
          figure checkable against the rows above it. */}
      <div className="mb-6">
        <div className="mb-1.5 font-mono text-label uppercase tracking-[0.16em] text-dim">
          {SAMPLE.name}&rsquo;s final assembly
        </div>
        <Panel>
          {pillars.map((p) => (
            <Row key={p.key} cols="96px minmax(0,1fr) auto">
              <span>{p.label}</span>
              <span className="text-label uppercase tracking-[0.11em]">
                weight {Math.round(p.weight * 100)}%
              </span>
              <span className={p.contribution >= 0 ? "text-pos-strong" : "text-neg-strong"}>
                {fmtPts(p.contribution)}
              </span>
            </Row>
          ))}
          <Row variant="total" cols="96px minmax(0,1fr)">
            <span className="text-label font-bold uppercase tracking-[0.11em]">Rating</span>
            {/* Was `truncate`. At 390px the 1fr track is ~180px and the
                assembly is ~35 characters, so the total that has to reconcile
                with the rows above it ellipsised to "1,500 + 132 + 42 →…" — the
                figure hidden, on the one row where hiding it is fatal. It fits
                on one line at every width ≥701px, so wrapping changes nothing
                on desktop and restores the sum on a phone. */}
            <span className="text-right">
              {base.toLocaleString()} + {contributions} = {SAMPLE.rating.toLocaleString()} → {prettyLetter(SAMPLE.letter)}
            </span>
          </Row>
        </Panel>
      </div>

      <div className="max-w-[68ch] space-y-3 text-prose leading-relaxed text-body">
        <p>
          <span className="text-ink font-semibold">What feeds the rating from trades: nothing, directly.</span>{" "}
          There is no Skill pillar in this version, so trading, drafting, and lineup management aren&rsquo;t
          scored on their own. A great trade only moves your letter once it&rsquo;s actually produced a better
          record (Results) or a stronger, younger roster (Assets) — a great trade that hasn&rsquo;t paid off yet
          doesn&rsquo;t move it at all.
        </p>
        <p>
          <span className="text-ink font-semibold">The ▲▼ on the leaderboard</span> is your rank change versus
          the most recent earlier NFL week on file — not the start of the season.
        </p>
      </div>

      {/* THE WINDOW ENTRY LIVES HERE, NOT IN "Supporting columns".
          That section's lead paragraph says its entries are "not part of the
          Franchise Rating formula" — true of Draft cap and Trade Grade, and
          false of Window the moment the stage became a band on this rating.
          Leaving it there would have published a framing the model contradicts.

          DELIBERATELY NO NUMBER. `LETTER_BANDS` above is generated from the
          engine (`scripts/gen_letter_bands.py`) with a pytest drift guard;
          STAGE_BANDS gets no such generator because this entry states the
          CONSTRUCTION rather than an edge. A hand-typed engine constant here
          would be exactly the drift that guard exists to catch. If a later
          edit puts a figure like an absolute band edge on this page, add the
          generator and the guard in the same commit.

          WHY THE COPY NO LONGER SAYS "Dynasty starts where A- does" FLATLY.
          It used to, citing the engine's `test_aligned_with_the_letter_scale`
          as proof. That test calls `rating_to_stage(1748)` with `sd=None`,
          which is the FIXED reference unit — and no shipped surface does:
          every one passes `sd=` (that league's own realized rating spread,
          `franchise_redesign.py::league_stage_sd`). The letter scale has no
          such parameter and stays on POINTS_PER_SD. So the two rails share
          their sd MULTIPLES (`_STAGE_SD` and `_BAND_SD` both cut Dynasty/A-
          at 0.90) but not their unit, and their edges coincide only where a
          league's spread equals the reference. On the reference league itself
          `league_stage_sd` is 252.6 against POINTS_PER_SD 275, putting the
          Dynasty edge at 1727 and the A- edge at 1748 — 21 rating points
          apart. The copy landed in 8d07fd8; 715ba4b made the bands
          league-relative and did not revisit it. */}
      <div className="mt-6">
        <EntryHead
          title="Window"
          formula="Rebuilding · Retooling · Competing · Contending · Dynasty"
        />
        <p className="max-w-[68ch] text-prose leading-relaxed text-body">
          Your competitive stage, banded straight off the Franchise Rating above — the same
          number, cut on the same kind of standard-deviation scale the letter grades use.
          <span className="text-ink"> Dynasty</span> is cut at the same multiple{" "}
          <span className="text-ink">A−</span> is, and <span className="text-ink">Competing</span>{" "}
          straddles the middle where league-average sits by definition. There is no separate
          window model: a better rating can never land you on a lower stage.
        </p>
        <p className="mt-2 max-w-[68ch] text-prose leading-relaxed text-body">
          The two rails share a construction, not a set of edges. The letter is cut against a
          reference spread; the stage is cut against{" "}
          <span className="text-ink">your own league&rsquo;s</span> spread, so a league that has
          separated gets wide rungs and a tight one gets narrow rungs. Where your league&rsquo;s
          spread happens to match the reference the two line up exactly — otherwise they sit a
          little apart, and the stage is the one that knows your league.
        </p>
        <p className="mt-2 max-w-[68ch] text-prose leading-relaxed text-body">
          Like the letter, the stage is a <span className="text-ink">percentile within your
          league</span>, not an absolute scale. The band multiples were measured on one league of
          twelve franchises — honestly derived, not proven to hold everywhere.
        </p>
      </div>
    </MethodologySection>
  );
}

// ─── Section 6: Supporting columns ───────────────────────────────────────────
function Columns() {
  return (
    <MethodologySection id="columns" title={SECTIONS[5].title}>
      <p className="mb-6 max-w-[68ch] text-prose leading-relaxed text-body">
        These columns appear in the dashboard but are <span className="text-ink font-semibold">not</span> part
        of the Franchise Rating formula — they&rsquo;re supporting context. (Window used to sit here and no
        longer does: it is banded off the rating itself, so it belongs above, with the model it comes from.)
      </p>

      <div className="space-y-5">
        <div>
          <EntryHead title="Draft Capital" formula="Σ value(held future picks, tier-adjusted)" />
          <p className="max-w-[68ch] text-prose leading-relaxed text-body">
            Dynasty market value of all future rookie picks currently held, tiered by the originating team&rsquo;s
            roster strength — weaker teams have earlier picks worth more. Not year-scoped; always reflects
            today&rsquo;s holdings.
          </p>
        </div>

        <div>
          <EntryHead title="Trade Grade" formula="A ≥ +1.25σ · A− ≥ +0.75σ · B+ ≥ +0.25σ · B ≈ 0 · B− ≥ −0.75σ · C ≥ −1.25σ · D below" />
          <p className="max-w-[68ch] text-prose leading-relaxed text-body">
            A letter from your <span className="text-ink font-semibold">realized Trade Value</span> z-scored
            versus leaguemates — a distinct signal from the Franchise letter, and — since this version has no
            Skill pillar — now the only place trading itself earns a letter. It grades trading activity only and
            is explicitly <span className="text-ink font-semibold">not</span> the platform&rsquo;s owner verdict.
            A franchise that never trades sits near B; the grade rewards consistent value-positive dealing.
          </p>
        </div>

        <div>
          <EntryHead title="Record, Finishes & Standings" />
          <p className="max-w-[68ch] text-prose leading-relaxed text-body">
            Regular-season standings reconstructed from each roster-week&rsquo;s points-for and points-against, then
            self-validated against Sleeper&rsquo;s authoritative record. Per-season finishes and all-time
            head-to-head vs each league-mate are on the Franchise page.
          </p>
        </div>
      </div>
    </MethodologySection>
  );
}

// ─── Section 7: How the words are written ────────────────────────────────────
function Words() {
  return (
    <MethodologySection id="words" title={SECTIONS[6].title}>
      <p className="max-w-[68ch] text-prose leading-relaxed text-body">
        The trade verdicts and stories, and the per-pillar highlights on your Franchise page, are written by
        a language model — but they are <span className="text-ink font-semibold">grounded</span>. The model
        receives the exact facts above (the grade, the pillar contributions, the five metric head-to-heads,
        asset journeys, injury context) and is instructed to narrate only those numbers. It does not invent
        claims. The prose is a plain-language reading of the data; the data is the source of truth. Any
        value-market term that could mislead is deterministically scrubbed before the text reaches the page.
      </p>
    </MethodologySection>
  );
}

// ─── Section 8: Sources & limits ─────────────────────────────────────────────
function Sources() {
  return (
    <MethodologySection id="sources" title={SECTIONS[7].title}>
      <div className="grid sm:grid-cols-2 gap-8 mb-8">
        <div>
          <h3 className="mb-2 border-b border-rule pb-1 font-display text-name font-bold tracking-[-0.024em]">Data sources</h3>
          <ul className="space-y-1 text-prose text-dim">
            <li>Sleeper API — league chain, trades, matchups, drafts</li>
            <li>KeepTradeCut — current dynasty market values (top ~500)</li>
            <li>FantasyCalc — fallback for players not in the primary source</li>
            <li>nflverse rosters — weekly roster snapshots for injury context</li>
          </ul>
        </div>
        <div>
          <h3 className="mb-2 border-b border-rule pb-1 font-display text-name font-bold tracking-[-0.024em]">Known limitations</h3>
          <ul className="space-y-2 text-prose text-dim">
            <li>
              <span className="text-ink font-medium">Inactive / retired players.</span>{" "}
              Players absent from dynasty value sources default to 0 value, which can distort grades from
              older trades.
            </li>
            <li>
              <span className="text-ink font-medium">Draft slot derivation.</span>{" "}
              Older Sleeper data missing{" "}
              <code className="border-b border-rule font-mono text-figure">draft_order</code>{" "}
              falls back to a position heuristic.
            </li>
            <li>
              <span className="text-ink font-medium">Waivers not graded.</span>{" "}
              Free-agent pickup value is not yet measured — only trades are graded.
            </li>
            <li>
              <span className="text-ink font-medium">Dynasty value history.</span>{" "}
              Market-value history only goes back a limited window; older snapshots use today&rsquo;s prices
              as a proxy.
            </li>
          </ul>
        </div>
      </div>

      <p className="text-figure text-dim">
        Source on{" "}
        <a className="underline" href="https://github.com/tkeefe66/sleeper-dynasty">
          GitHub
        </a>
        .{" "}
        <a href="/" className="underline ml-3">
          ← Back to home
        </a>
      </p>
    </MethodologySection>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Main export. It USED to be "pure presentational, no 'use client', no hooks,
// no navigation" — that is no longer true: every section is a client component
// with `useState`, a `hashchange` effect and hash navigation, so a deep link
// can open a collapsed section.
// ────────────────────────────────────────────────────────────────────────────
export function MethodologyContent() {
  return (
    <div className="max-w-[72ch]">
      {/* Hero */}
      <div className="mb-12">
        <h1 className="font-display text-lead font-extrabold tracking-[-0.03em]">How the grade is built</h1>
        <p className="mt-3 max-w-[68ch] text-prose leading-relaxed text-body">
          Every number on this page traces back to the box scores.
        </p>
      </div>

      {/* Content rail: thin left spine connects sections 1–3.
          Both the spine and the 64px inter-section rhythm are ≥701px only. On a
          phone the eight sections are a flush ruled list of disclosure rows —
          64px of air between collapsed rows is not a list, and indenting three
          of the eight rows by 24px breaks the left edge they share. */}
      <div className="min-[701px]:space-y-16">
        <div className="min-[701px]:space-y-16 min-[701px]:border-l min-[701px]:border-rule min-[701px]:pl-6">
          <Verdict />
          <Pillars />
          <Signals />
        </div>

        <Metrics />
        <Math_ />
        <Columns />
        <Words />
        <Sources />
      </div>
    </div>
  );
}
