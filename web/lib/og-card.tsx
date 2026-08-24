import {
  AnyCard, TradeCard, OwnerCard, LeagueCard, LeaderboardCard, LetterTone,
} from "./og-card-data";
import { fmtLensValue } from "./trade-lens";

/* ---------------------------------------------------------------------------
 * og-card.tsx — Agate share cards (design_handoff_agate/CLAUDE_CODE.md §
 * Commit 8, drawn in `Agate System.dc.html` §08). "The Card Is The Ledger"
 * (DESIGN.md): the same system at twice the size — 52px rule pitch at
 * 1200×630, eyebrow 18px mono, nameplate 68–80px display 800, rows 23px mono.
 *
 * TYPE is ported: the display face is Bricolage Grotesque at 800/700, matching
 * `--weight-display`/`--weight-heading`. Archivo 900 is gone, so its 900 sites
 * are 800 here — Bricolage's axis stops at 800. Every `fontFamily`/`fontWeight`
 * pair below must have a face registered in `lib/og-font.ts`; Satori
 * substitutes an unregistered pair silently, and `tests/og-font.test.ts` is
 * what keeps the two files honest.
 *
 * COLOUR is ported too now: `C` holds the Furniture LIGHT tokens. Satori cannot
 * read CSS custom properties, so they are literals and NOTHING enforces the
 * match — re-diff `C` against `.design/tokens/colors.css` on every sync.
 * Cards ship light-only; the dark ground is not a shipping card surface.
 *
 * STILL UNPORTED, deliberately: `PITCH`. 52px was "twice Agate's 26px rule
 * pitch". Furniture's pitch is 40, so the derivation now gives 80 — but that
 * halves the card's row budget, and there is NO Furniture card spec anywhere in
 * `.design` to check it against (the package ships no `ui_kits/`, and
 * `guidelines/DESIGN.md`'s "The Card Is The Ledger" is Agate's). Changing it
 * would be inventing a spec, so it stays 52 until one exists.
 *
 * Satori supports flexbox, not CSS grid (unlike the drawn prototype's grid-
 * template-columns rows) — every ledger row here is flex cells at fixed
 * widths, matching the app's own og-card precedent. The ruled ground is a
 * flat `--rule-lit` background per row with a `--rule` bottom hairline (the
 * ground IS the divider — no `repeating-linear-gradient`, which Satori does
 * not reliably support either).
 * ------------------------------------------------------------------------ */

/* Furniture LIGHT tokens, inlined because Satori cannot read CSS custom
 * properties. Kept in the same order as `.design/tokens/colors.css` so the two
 * can be diffed by eye on the next sync — nothing enforces the match, and this
 * object sat on the retired Agate palette for the whole port (`.design`'s own
 * Retired list names "og-card.tsx's entire local palette").
 *
 * `ruleLit` is `--surface` (#ffffff), not the old `--rule-lit`: under Agate a
 * row sat on the lit stripe of a striped ground; under Furniture a row sits on
 * a solid panel, and the panel is --surface. */
const C = {
  bg: "#f4f3ef",      // --bg
  ruleLit: "#ffffff", // --surface
  rule: "#eceae4",    // --rule
  dim: "#5f636e",     // --dim
  body: "#43464f",    // --body
  ink: "#14151a",     // --ink
  pos: "#00a63e",     // --pos
  neg: "#e12d39",     // --neg
};

const PITCH = 52; // twice the app's 26px rule pitch

function toneColor(tone: LetterTone): string {
  if (tone === "pos") return C.pos;
  if (tone === "ink") return C.ink;
  if (tone === "ink_soft") return "rgba(20,21,26,0.7)";   // --ink @70%
  if (tone === "neg_soft") return "rgba(225,45,57,0.7)";  // --neg @70%
  return C.neg;
}

/** Signed formatting with the typographic minus (matches trade-lens.ts's
 *  fmtLensMargin) — for the owner/league cards' career swings, which (unlike
 *  the trade card's per-side totals) are genuinely signed figures. */
function fmtSigned(n: number, dec: boolean): string {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  const mag = Math.abs(dec ? Number(n.toFixed(1)) : Math.round(n));
  return `${sign}${dec ? mag.toFixed(1) : mag.toLocaleString()}`;
}

// ---------------------------------------------------------------------------
// Shared chrome
// ---------------------------------------------------------------------------

function Frame({ eyebrow, children }: { eyebrow: string; children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", width: "100%", height: "100%",
      background: C.bg, color: C.ink, padding: "48px 52px", fontFamily: "Geist Mono",
    }}>
      <div style={{
        display: "flex", fontFamily: "Geist Mono", fontWeight: 400, fontSize: 18,
        letterSpacing: "0.14em", textTransform: "uppercase", color: C.dim,
      }}>
        {eyebrow}
      </div>
      {children}
    </div>
  );
}

function Spacer() {
  return <div style={{ display: "flex", flex: 1 }} />;
}

function Nameplate({ text, size, marginTop = 16 }: { text: string; size: number; marginTop?: number }) {
  return (
    <div style={{
      /* Mixed case, not uppercase: Archivo 900 caps are exactly what read as
         shouting at consumer scale, and the card is the loudest surface the
         product has. Tracking is --track-nameplate (-0.034em), not Agate's
         -0.05em. */
      display: "flex", fontFamily: "Bricolage Grotesque", fontWeight: 800,
      letterSpacing: "-0.034em", lineHeight: 0.95, fontSize: size, marginTop, maxWidth: 1096,
    }}>
      {text}
    </div>
  );
}

function Footer({ left, right }: { left: string; right: string }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 24,
      fontFamily: "Geist Mono", fontSize: 18, letterSpacing: "0.14em", textTransform: "uppercase",
    }}>
      <span style={{ display: "flex", color: C.ink, fontWeight: 700 }}>{left}</span>
      <span style={{ display: "flex", color: C.dim }}>{right}</span>
    </div>
  );
}

function Cell({ width, align = "left", children }: {
  width: number | "flex"; align?: "left" | "right"; children?: React.ReactNode;
}) {
  return (
    <div style={{
      display: "flex",
      ...(width === "flex" ? { flex: 1, minWidth: 0 } : { width, flexShrink: 0 }),
      justifyContent: align === "right" ? "flex-end" : "flex-start",
      overflow: "hidden",
    }}>
      {children}
    </div>
  );
}

function Row({ children, gap = 24, borderTop }: {
  children: React.ReactNode; gap?: number; borderTop?: boolean;
}) {
  return (
    <div style={{
      display: "flex", height: PITCH, alignItems: "center", gap, padding: "0 16px",
      boxSizing: "border-box", background: C.ruleLit, borderBottom: `2px solid ${C.rule}`,
      ...(borderTop ? { borderTop: `2px solid ${C.ink}` } : {}),
    }}>
      {children}
    </div>
  );
}

// No `align`/`textAlign` prop: alignment is the parent Cell's job
// (justifyContent), and passing an undefined `textAlign` through to Satori's
// style parser throws (it calls `.trim()` on every declared value, including
// unset ones) — this is a flex child, `text-align` would be inert here anyway.
function HeaderLabel({ children }: { children: React.ReactNode }) {
  return (
    <span style={{
      display: "flex", fontFamily: "Geist Mono", fontSize: 17, letterSpacing: "0.1em",
      textTransform: "uppercase", color: C.dim,
    }}>
      {children}
    </span>
  );
}

const Ledger = ({ children }: { children: React.ReactNode }) => (
  <div style={{ display: "flex", flexDirection: "column", borderTop: `2px solid ${C.ink}` }}>
    {children}
  </div>
);

// ---------------------------------------------------------------------------
// Trade card — Fig. 8.1
// ---------------------------------------------------------------------------

function TradeCardView({ card }: { card: TradeCard }) {
  type ColTone = "winner" | "loser" | "even";
  const toneA: ColTone = card.winnerCol === "a" ? "winner" : card.winnerCol === "b" ? "loser" : "even";
  const toneB: ColTone = card.winnerCol === "b" ? "winner" : card.winnerCol === "a" ? "loser" : "even";
  const colorFor = (t: ColTone) => (t === "loser" ? C.body : C.ink);
  const weightFor = (t: ColTone): 400 | 700 => (t === "winner" ? 700 : 400);

  return (
    <Frame eyebrow={card.eyebrow}>
      <div style={{
        display: "flex", fontFamily: "Bricolage Grotesque", fontWeight: 800, letterSpacing: "-0.035em",
        lineHeight: 1.08, fontSize: 54, marginTop: 16, maxWidth: 920,
      }}>
        {card.headline}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 20, marginTop: 18 }}>
        <div style={{
          display: "flex", fontFamily: "Geist Mono", fontWeight: 700, fontSize: 18,
          letterSpacing: "0.14em", textTransform: "uppercase", color: C.ink,
          border: `2px solid ${C.ink}`, padding: "6px 14px",
        }}>
          {card.ruling.badge}
        </div>
        <div style={{ display: "flex", fontFamily: "Geist Mono", fontSize: 20, color: C.dim, maxWidth: 680 }}>
          {card.ruling.note}
        </div>
      </div>

      <Spacer />

      <Ledger>
        <Row>
          <Cell width="flex" />
          <Cell width={192} align="right">
            <span style={{
              fontFamily: "Geist Mono", fontSize: 17, letterSpacing: "0.1em", textTransform: "uppercase",
              fontWeight: weightFor(toneA), color: colorFor(toneA),
            }}>
              {card.colA}
            </span>
          </Cell>
          <Cell width={192} align="right">
            <span style={{
              fontFamily: "Geist Mono", fontSize: 17, letterSpacing: "0.1em", textTransform: "uppercase",
              fontWeight: weightFor(toneB), color: colorFor(toneB),
            }}>
              {card.colB}
            </span>
          </Cell>
        </Row>

        {card.rows.map((r) => (
          <Row key={r.label}>
            <Cell width="flex"><HeaderLabel>{r.label}</HeaderLabel></Cell>
            <Cell width={192} align="right">
              <span style={{ fontFamily: "Geist Mono", fontSize: 23, fontWeight: weightFor(toneA), color: colorFor(toneA) }}>
                {fmtLensValue(r.lens, r.a)}
              </span>
            </Cell>
            <Cell width={192} align="right">
              <span style={{ fontFamily: "Geist Mono", fontSize: 23, fontWeight: weightFor(toneB), color: colorFor(toneB) }}>
                {fmtLensValue(r.lens, r.b)}
              </span>
            </Cell>
          </Row>
        ))}
      </Ledger>

      <Footer left={card.footer.left} right={card.footer.right} />
    </Frame>
  );
}

// ---------------------------------------------------------------------------
// Owner card — Fig. 8.4
// ---------------------------------------------------------------------------

function OwnerCardView({ card }: { card: OwnerCard }) {
  return (
    <Frame eyebrow={card.eyebrow}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 18, marginTop: 16 }}>
        <Nameplate text={card.name} size={card.nameplateSize} marginTop={0} />
        {card.rating && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
              <span style={{
                display: "flex", fontFamily: "Bricolage Grotesque", fontWeight: 800, fontSize: 88,
                letterSpacing: "-0.05em", lineHeight: 0.9, color: toneColor(card.rating.tone),
              }}>
                {card.rating.letter}
              </span>
              <span style={{ display: "flex", fontFamily: "Geist Mono", fontSize: 22, color: C.dim }}>
                #{card.rating.rank}<span style={{ opacity: 0.7 }}>/{card.rating.of}</span>
              </span>
            </div>
            <div style={{ display: "flex", fontFamily: "Geist Mono", fontSize: 22, color: C.ink }}>
              {card.rating.value.toLocaleString()}
            </div>
          </div>
        )}
      </div>

      <Spacer />

      <Ledger>
        {card.rows.map((r) => (
          <Row key={r.label}>
            <Cell width="flex"><HeaderLabel>{r.label}</HeaderLabel></Cell>
            <Cell width={240} align="right">
              <span style={{
                fontFamily: "Geist Mono", fontSize: 23, fontWeight: 700,
                color: r.kind === "plain" ? C.ink : r.value > 0 ? C.pos : r.value < 0 ? C.neg : C.dim,
              }}>
                {r.kind === "plain" ? Math.round(r.value).toLocaleString() : fmtSigned(r.value, r.kind === "signed_dec")}
              </span>
            </Cell>
          </Row>
        ))}
      </Ledger>

      <Footer left={card.footer.left} right={card.footer.right} />
    </Frame>
  );
}

// ---------------------------------------------------------------------------
// League card — Fig. 8.2
// ---------------------------------------------------------------------------

function LeagueCardView({ card }: { card: LeagueCard }) {
  return (
    <Frame eyebrow={card.eyebrow}>
      <Nameplate text={card.name} size={card.nameplateSize} />
      <div style={{
        display: "flex", fontFamily: "Geist Mono", fontSize: 18, letterSpacing: "0.14em",
        textTransform: "uppercase", color: C.dim, marginTop: 18,
      }}>
        {card.subhead}
      </div>

      <Spacer />

      <Ledger>
        <Row>
          <Cell width={52}><HeaderLabel>#</HeaderLabel></Cell>
          <Cell width="flex"><HeaderLabel>Franchise</HeaderLabel></Cell>
          <Cell width={220} align="right"><HeaderLabel>Value</HeaderLabel></Cell>
        </Row>
        {card.rows.map((r) => (
          <Row key={r.rank}>
            <Cell width={52}><span style={{ fontFamily: "Geist Mono", fontSize: 23, color: C.dim }}>{r.rank}</span></Cell>
            <Cell width="flex">
              <span style={{ fontFamily: "Bricolage Grotesque", fontWeight: 700, fontSize: 26, letterSpacing: "-0.02em", color: C.ink }}>
                {r.name}
              </span>
            </Cell>
            <Cell width={220} align="right">
              <span style={{
                fontFamily: "Geist Mono", fontSize: 23, fontWeight: 700,
                color: r.value > 0 ? C.pos : r.value < 0 ? C.neg : C.dim,
              }}>
                {fmtSigned(r.value, false)}
              </span>
            </Cell>
          </Row>
        ))}
      </Ledger>

      <Footer left={card.footer.left} right={card.footer.right} />
    </Frame>
  );
}

// ---------------------------------------------------------------------------
// Leaderboard card — Fig. 8.3 (Franchise Ratings)
// ---------------------------------------------------------------------------

function LeaderboardCardView({ card }: { card: LeaderboardCard }) {
  return (
    <Frame eyebrow={card.eyebrow}>
      <Nameplate text={card.name} size={card.nameplateSize} />
      <Spacer />
      <Ledger>
        {card.rows.map((r) => (
          <Row key={r.rank} borderTop={r.last}>
            <Cell width={60}>
              <span style={{ fontFamily: "Geist Mono", fontSize: 23, color: C.dim }}>{r.rank}</span>
            </Cell>
            <Cell width="flex">
              <span style={{
                fontFamily: "Bricolage Grotesque", fontWeight: 700, fontSize: 26, letterSpacing: "-0.02em",
                color: r.last ? C.dim : C.ink,
              }}>
                {r.name}
              </span>
            </Cell>
            <Cell width={48}>
              <span style={{ fontFamily: "Bricolage Grotesque", fontWeight: 700, fontSize: 23, color: toneColor(r.tone) }}>
                {r.letter}
              </span>
            </Cell>
            <Cell width={148} align="right">
              <span style={{ fontFamily: "Geist Mono", fontSize: 23, color: C.dim }}>
                {r.rating.toLocaleString()}
              </span>
            </Cell>
          </Row>
        ))}
      </Ledger>
      <Footer left={card.footer.left} right={card.footer.right} />
    </Frame>
  );
}

// ---------------------------------------------------------------------------

export function renderCard(card: AnyCard): React.ReactElement {
  if (card.kind === "trade") return <TradeCardView card={card} />;
  if (card.kind === "owner") return <OwnerCardView card={card} />;
  if (card.kind === "league") return <LeagueCardView card={card} />;
  if (card.kind === "leaderboard") return <LeaderboardCardView card={card} />;
  return (
    <Frame eyebrow={card.eyebrow}>
      <Spacer />
      <div style={{
        display: "flex", fontFamily: "Bricolage Grotesque", fontWeight: 800,
        letterSpacing: "-0.034em", lineHeight: 0.95, fontSize: 68,
      }}>
        {card.title}
      </div>
      <Spacer />
    </Frame>
  );
}
