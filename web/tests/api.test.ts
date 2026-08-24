import { describe, expect, it, vi, beforeEach } from "vitest";
import { ApiError, dashboard } from "../lib/api";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("dashboard appends year+lens query params", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );
    await dashboard("L1", { year: 2024, lens: "production" }).catch(() => {});
    const calledWith = fetchSpy.mock.calls[0][0] as string;
    expect(calledWith).toContain("year=2024");
    expect(calledWith).toContain("lens=production");
  });

  it("defaults to cache: no-store so SSR never serves stale league data", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), { status: 200 }),
    );
    await dashboard("L1").catch(() => {});
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect(init.cache).toBe("no-store");
  });

  it("throws ApiError on non-2xx", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "nope" }), { status: 404 }),
    );
    await expect(
      dashboard("ghost-league"),
    ).rejects.toThrow(ApiError);
  });
});
