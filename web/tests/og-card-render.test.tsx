import { describe, expect, it } from "vitest";
import React from "react";

import { renderCard } from "@/lib/og-card";
import {
  fallbackCard,
  leagueCard,
  leaderboardCard,
  ownerCard,
  tradeCard,
} from "@/lib/og-card-data";

/**
 * Satori-safety guard for the rendered element tree.
 *
 * `tests/og-card-data.test.ts` covers the pure mappers and `og-font.test.ts`
 * covers font registration, but until now NOTHING inspected what `renderCard`
 * actually produces. `next build` type-checks the routes without executing
 * them (no `generateStaticParams`), so a style value Satori throws on ships
 * with every suite green — the whole point of followup C14.
 *
 * This walks the tree instead of rendering it, so it is fast, deterministic,
 * and needs no fonts or network. It catches the three failure modes that are
 * silent or fatal in Satori and invisible to TypeScript:
 *
 *   1. `undefined` style values — Satori calls `.trim()` on every *declared*
 *      value, so one conditional prop takes down the whole render.
 *   2. `display: grid` / `gridTemplate*` — unsupported; columns collapse.
 *   3. `var(--token)` — CSS custom properties resolve to nothing, so the
 *      type or rule silently disappears.
 *
 * It does NOT prove the card renders: only Satori can, which is what the
 * `e2e/og.spec.ts` smoke test is for.
 */

// Deliberately hostile: the longest plausible name, a five-digit figure, a
// negative sign, and an empty string. Fixtures elsewhere use short names, and
// `Cell` clips silently rather than erroring.
const LONG = "Cornelius Wetherington-Fitzgerald III";

function walk(node: React.ReactNode, visit: (style: Record<string, unknown>, path: string) => void, path = "root"): void {
  if (node === null || node === undefined || typeof node === "boolean") return;
  if (Array.isArray(node)) {
    node.forEach((child, i) => walk(child, visit, `${path}[${i}]`));
    return;
  }
  if (!React.isValidElement(node)) return;

  const props = node.props as Record<string, unknown>;
  const here = `${path} > ${typeof node.type === "string" ? node.type : (node.type as { name?: string }).name || "Component"}`;

  if (props.style && typeof props.style === "object") {
    visit(props.style as Record<string, unknown>, here);
  }

  // A component element has not rendered yet — render it one level so its own
  // styles are inspected too. Card views are plain function components.
  if (typeof node.type === "function") {
    const rendered = (node.type as (p: unknown) => React.ReactNode)(props);
    walk(rendered, visit, here);
    return;
  }
  walk(props.children as React.ReactNode, visit, here);
}

function stylesOf(card: React.ReactElement): { style: Record<string, unknown>; path: string }[] {
  const out: { style: Record<string, unknown>; path: string }[] = [];
  walk(card, (style, path) => out.push({ style, path }));
  return out;
}

const gmRow = (rank: number, name: string, rating: number, letter: string) => ({
  rank, user_id: name, owner: { user_id: name, owner_name: name },
  rating, letter, pillars: {}, trend: 0, trades: 0,
  net_ktc: 0, production_regular: 0, production_playoff: 0, production_toilet: 0,
});

const OWNER_BASE = {
  owner: { user_id: "u1", owner_name: LONG },
  totals_by_lens: { ktc: -12345, regular: -1234.5, playoff: 9876.5, toilet: 0, total: 0 },
  career_arc: [{ season: 2024, trades: 4 }, { season: 2025, trades: 4 }],
  trades: [], best_trade_id: "t1", worst_trade_id: "t9",
};

const CARDS: [string, () => React.ReactElement][] = [
  ["fallback", () => renderCard(fallbackCard())],
  [
    "league",
    () =>
      renderCard(
        leagueCard({
          league: { name: LONG, season: 2025, total_rosters: 12 },
          standings: [
            { rank: 1, owner: { owner_name: LONG }, net_ktc: 99999, trades: 41 },
            // Empty name + a negative five-figure value: Cell clips silently
            // rather than erroring, so the hostile case has to be asserted.
            { rank: 2, owner: { owner_name: "" }, net_ktc: -99999, trades: 0 },
            { rank: 3, owner: { owner_name: "C" }, net_ktc: 0, trades: 7 },
          ],
        } as never),
      ),
  ],
  [
    "owner",
    () =>
      renderCard(
        ownerCard(
          {
            ...OWNER_BASE,
            franchise_rating: {
              letter: "A+", rating: 2200, rank: 1, of: 12, trend: 1, pillars: {},
            },
            track_record: {
              seasons: [], titles: 3, runner_ups: 1, playoff_appearances: 9,
              seasons_played: 11, best_finish: 1,
              career_wins: 0, career_losses: 0, career_ties: 0,
            },
          } as never,
          LONG,
        ),
      ),
  ],
  [
    "owner (no rating — the omit-don't-invent path)",
    () => renderCard(ownerCard(OWNER_BASE as never, LONG)),
  ],
  [
    "leaderboard",
    () =>
      renderCard(
        leaderboardCard(
          {
            league_id: "L", scope: "all", generated_at: "2026-01-01T00:00:00Z",
            rows: [
              gmRow(1, LONG, 2200, "A+"),
              gmRow(2, "", 1600, "A"),
              gmRow(3, "Carol", 1550, "B"),
              gmRow(4, "Dave", 1500, "B"),
              gmRow(5, "Erin", 1400, "C"),
              gmRow(6, "Gina", -999, "F"),
            ],
          } as never,
          LONG,
          "week 18",
        ),
      ),
  ],
];

describe("renderCard produces a Satori-safe tree", () => {
  for (const [name, build] of CARDS) {
    describe(name, () => {
      it("declares no undefined style values", () => {
        const offenders: string[] = [];
        for (const { style, path } of stylesOf(build())) {
          for (const [k, v] of Object.entries(style)) {
            if (v === undefined) offenders.push(`${path}: ${k}`);
          }
        }
        expect(
          offenders,
          "Satori calls .trim() on every declared style value, so an " +
            "`undefined` takes down the entire render. Spread the whole " +
            "declaration in conditionally instead: `...(cond ? { x } : {})`.",
        ).toEqual([]);
      });

      it("uses no grid layout", () => {
        const offenders: string[] = [];
        for (const { style, path } of stylesOf(build())) {
          if (style.display === "grid" || style.display === "inline-grid") {
            offenders.push(`${path}: display:${String(style.display)}`);
          }
          for (const k of Object.keys(style)) {
            if (k.startsWith("grid")) offenders.push(`${path}: ${k}`);
          }
        }
        expect(
          offenders,
          "Satori is flexbox-only. The app's .ruled grid does not port — " +
            "rebuild as flex Cells at fixed pixel widths.",
        ).toEqual([]);
      });

      it("references no CSS custom properties", () => {
        const offenders: string[] = [];
        for (const { style, path } of stylesOf(build())) {
          for (const [k, v] of Object.entries(style)) {
            if (typeof v === "string" && v.includes("var(--")) {
              offenders.push(`${path}: ${k} = ${v}`);
            }
          }
        }
        expect(
          offenders,
          "Satori cannot resolve CSS custom properties — the value becomes " +
            "nothing and the type or rule silently disappears. Inline the hex " +
            "literal from og-card.tsx's C object.",
        ).toEqual([]);
      });
    });
  }
});
