import { StandingRow } from "./types";
import { SortState } from "./url-state";

export interface StandingsState {
  sort: SortState;
  filters: Record<string, string[] | [number | null, number | null]>;
}

const NUMERIC_COLUMNS = new Set<string>([
  "rank", "net_ktc", "production_total",
  "production_regular", "production_playoff", "production_toilet",
  "trades", "gm_rating", "gm_rank", "draft_capital_value", "season_wins", "season_rank",
]);

function gradeBucket(grade: string): "A" | "B" | "C" | "D" {
  const head = grade.charAt(0).toUpperCase();
  if (head === "A" || head === "B" || head === "C" || head === "D") return head;
  return "C";
}

// The Franchise column sorts/filters on the label the dashboard ledgers
// actually render — the Sleeper team name, falling back to the owner name —
// so an A→Z sort matches what the reader sees. Other columns read directly
// off the row. (Kept under the `owner_name` key: that's the column id in the
// URL state, and changing it would break saved links.)
export function franchiseSortKey(r: StandingRow): string {
  return r.owner.team_name?.trim() || r.owner.owner_name;
}

function cellValue(r: StandingRow, col: string): any {
  if (col === "owner_name") return franchiseSortKey(r);
  return (r as any)[col];
}

export function applyStandingsState(
  rows: StandingRow[], state: StandingsState,
): StandingRow[] {
  let out = [...rows];

  for (const [col, val] of Object.entries(state.filters)) {
    if (Array.isArray(val) && typeof val[0] === "string") {
      const sv = (val as string[]).map((s) => s.toLowerCase()).filter(Boolean);
      if (sv.length === 0) continue;
      if (col === "grade") {
        out = out.filter((r) => sv.includes(gradeBucket(r.grade).toLowerCase()));
      } else if (col === "owner_name") {
        const term = sv[0];
        const chars = term.split("");
        out = out.filter((r) => {
          const lower = franchiseSortKey(r).toLowerCase();
          return chars.every((ch) => lower.includes(ch));
        });
      }
    } else if (Array.isArray(val) && val.length === 2) {
      const [lo, hi] = val as [number | null, number | null];
      if (NUMERIC_COLUMNS.has(col as keyof StandingRow)) {
        out = out.filter((r) => {
          const n = (r as any)[col] as number;
          if (lo !== null && n < lo) return false;
          if (hi !== null && n > hi) return false;
          return true;
        });
      }
    }
  }

  out.sort((a, b) => {
    const av = cellValue(a, state.sort.column);
    const bv = cellValue(b, state.sort.column);
    if (av === bv) return 0;
    const cmp = av > bv ? 1 : -1;
    return state.sort.direction === "asc" ? cmp : -cmp;
  });

  return out.map((r, i) => ({ ...r, rank: i + 1 }));
}
