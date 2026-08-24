import type { DraftPickResult } from "@/lib/types";

/** Sentinel value used in the year selector for the All-Time view. */
export const ALL_TIME = "all";

const delta = (r: DraftPickResult): number => r.current_value - r.avg_slot_value;

/** Every pick across all seasons, sorted by value-vs-slot delta (best first). */
export function flattenAllTime(
  bySeason: Record<string, DraftPickResult[]>,
): DraftPickResult[] {
  return Object.values(bySeason)
    .flat()
    .sort((a, b) => delta(b) - delta(a));
}

export interface ColumnTotals {
  current_value: number;
  lowest_value: number;
  highest_value: number;
  deltaSum: number;
  production_total: number;
  production_started: number;
  production_regular: number;
  production_playoff: number;
  production_toilet: number;
  games_started: number;
}

/** Sum every numeric column across the given rows. */
export function columnTotals(rows: DraftPickResult[]): ColumnTotals {
  return rows.reduce<ColumnTotals>(
    (t, r) => ({
      current_value: t.current_value + r.current_value,
      lowest_value: t.lowest_value + r.lowest_value,
      highest_value: t.highest_value + r.highest_value,
      deltaSum: t.deltaSum + delta(r),
      production_total: t.production_total + r.production_total,
      production_started: t.production_started + (r.production_started ?? 0),
      production_regular: t.production_regular + r.production_regular,
      production_playoff: t.production_playoff + r.production_playoff,
      production_toilet: t.production_toilet + r.production_toilet,
      games_started: t.games_started + r.games_started,
    }),
    {
      current_value: 0, lowest_value: 0, highest_value: 0, deltaSum: 0,
      production_total: 0, production_started: 0, production_regular: 0,
      production_playoff: 0, production_toilet: 0, games_started: 0,
    },
  );
}
