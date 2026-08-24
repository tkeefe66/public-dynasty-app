import { describe, it, expect } from "vitest";
import { sortRows, nextSort } from "@/lib/draft-sort";

const get = (r: Record<string, unknown>, k: string) => r[k] as number | string | null;

describe("sortRows", () => {
  const rows = [{ n: 3 }, { n: 1 }, { n: 2 }];

  it("does not mutate its input", () => {
    const copy = [...rows];
    sortRows(rows, { key: "n", dir: "ascending" }, get);
    expect(rows).toEqual(copy);
  });

  it("returns the original order when there is no sort", () => {
    expect(sortRows(rows, null, get)).toEqual(rows);
  });

  it("sorts numbers, both ways", () => {
    expect(sortRows(rows, { key: "n", dir: "ascending" }, get).map((r) => r.n)).toEqual([1, 2, 3]);
    expect(sortRows(rows, { key: "n", dir: "descending" }, get).map((r) => r.n)).toEqual([3, 2, 1]);
  });

  it("sorts strings case-insensitively", () => {
    const s = [{ v: "beta" }, { v: "Alpha" }, { v: "gamma" }];
    expect(sortRows(s, { key: "v", dir: "ascending" }, get).map((r) => r.v)).toEqual(["Alpha", "beta", "gamma"]);
  });

  it("puts nulls last in BOTH directions", () => {
    // An absent figure is not a small one. A null that sorts to the top
    // descending would read as the best pick in the class.
    const n = [{ v: 5 }, { v: null }, { v: 9 }];
    expect(sortRows(n, { key: "v", dir: "descending" }, get).map((r) => r.v)).toEqual([9, 5, null]);
    expect(sortRows(n, { key: "v", dir: "ascending" }, get).map((r) => r.v)).toEqual([5, 9, null]);
  });

  it("is stable for equal keys", () => {
    const t = [{ v: 1, id: "a" }, { v: 1, id: "b" }, { v: 0, id: "c" }];
    expect(sortRows(t, { key: "v", dir: "descending" }, get).map((r) => r.id)).toEqual(["a", "b", "c"]);
  });
});

describe("nextSort", () => {
  it("opens a numeric column descending", () => {
    expect(nextSort(null, "total", true)).toEqual({ key: "total", dir: "descending" });
  });

  it("opens a text column ascending", () => {
    expect(nextSort(null, "player", false)).toEqual({ key: "player", dir: "ascending" });
  });

  it("flips the active column", () => {
    expect(nextSort({ key: "total", dir: "descending" }, "total", true)).toEqual({ key: "total", dir: "ascending" });
    expect(nextSort({ key: "total", dir: "ascending" }, "total", true)).toEqual({ key: "total", dir: "descending" });
  });

  it("switching columns opens the new one at its own default", () => {
    expect(nextSort({ key: "total", dir: "ascending" }, "player", false)).toEqual({ key: "player", dir: "ascending" });
  });
});
