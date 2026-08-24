import { Lens, Year } from "./types";

export type SortDirection = "asc" | "desc";

export interface SortState {
  column: string;
  direction: SortDirection;
}

export interface DashboardState {
  year: Year;
  lens: Lens;
  sort: SortState;
  filters: Record<string, string[] | [number | null, number | null]>;
}

// "auto" is a sentinel, not a real column: it means "the user hasn't picked a
// sort, so let the view choose its own sensible default." This lets clicking a
// real column (including Franchise Rating) register as an explicit choice that the
// view-specific default logic must respect. See StandingsTable.effectiveSort.
const DEFAULTS: DashboardState = {
  year: "all",
  lens: "ktc",
  sort: { column: "auto", direction: "desc" },
  filters: {},
};

// Production columns were renamed (swing -> received-only). Map legacy column
// ids from older shared/bookmarked URLs onto the current names so they still work.
const LEGACY_COLUMN_ALIASES: Record<string, string> = {
  net_production: "production_total",
  net_production_started_regular: "production_regular",
  net_production_started_playoff: "production_playoff",
  net_production_started_toilet: "production_toilet",
};
const canonicalColumn = (c: string): string => LEGACY_COLUMN_ALIASES[c] ?? c;

export function decodeDashboardState(sp: URLSearchParams): DashboardState {
  const year = sp.get("year");
  const lens = sp.get("lens") as Lens | null;
  const sortRaw = sp.get("sort");

  let sort: SortState = DEFAULTS.sort;
  if (sortRaw) {
    const [col, dir] = sortRaw.split(".");
    if (col && (dir === "asc" || dir === "desc")) {
      sort = { column: canonicalColumn(col), direction: dir };
    }
  }

  const filters: DashboardState["filters"] = {};
  sp.forEach((value, key) => {
    const m = key.match(/^filter\[([^\]]+)\](?:\[(gte|lte)\])?$/);
    if (!m) return;
    const col = canonicalColumn(m[1]);
    const op = m[2];
    if (op === "gte" || op === "lte") {
      const cur = (filters[col] as [number | null, number | null] | undefined) ??
        [null, null];
      const n = value === "" ? null : Number(value);
      filters[col] = op === "gte" ? [n, cur[1]] : [cur[0], n];
    } else {
      filters[col] = value.split(",").filter(Boolean);
    }
  });

  return {
    year: year === "all" || year === null ? "all" : Number(year),
    lens: lens && ["ktc", "production"].includes(lens) ? lens : "ktc",
    sort,
    filters,
  };
}

export function encodeDashboardState(state: DashboardState): string {
  const sp = new URLSearchParams();
  if (state.year !== DEFAULTS.year) sp.set("year", String(state.year));
  if (state.lens !== DEFAULTS.lens) sp.set("lens", state.lens);
  if (
    state.sort.column !== DEFAULTS.sort.column ||
    state.sort.direction !== DEFAULTS.sort.direction
  ) {
    sp.set("sort", `${state.sort.column}.${state.sort.direction}`);
  }
  for (const [col, val] of Object.entries(state.filters)) {
    if (Array.isArray(val) && typeof val[0] === "string") {
      if ((val as string[]).length > 0) {
        sp.set(`filter[${col}]`, (val as string[]).join(","));
      }
    } else if (Array.isArray(val) && val.length === 2) {
      const [lo, hi] = val as [number | null, number | null];
      if (lo !== null) sp.set(`filter[${col}][gte]`, String(lo));
      if (hi !== null) sp.set(`filter[${col}][lte]`, String(hi));
    }
  }
  return sp.toString();
}
