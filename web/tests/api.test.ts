import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { ApiError, dashboard, refreshStream } from "../lib/api";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("turns a Yahoo provider limit into an actionable refresh error", () => {
    // Mutation: discarding server error-event data hides the provider limit.
    let stream: EventTarget & { close: ReturnType<typeof vi.fn> };
    class TestEventSource extends EventTarget {
      close = vi.fn();
      constructor() { super(); stream = this; }
    }
    vi.stubGlobal("EventSource", TestEventSource);
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent);
    stream!.dispatchEvent(new MessageEvent("error", {
      data: JSON.stringify({ stage: "error", error_code: "yahoo_rate_limited", message: "private upstream details" }),
    }));
    expect(onEvent).toHaveBeenCalledWith({ stage: "error", message: expect.stringMatching(/Yahoo.*wait/i) });
    expect(onEvent.mock.calls[0][0].message).not.toContain("private");
    expect(stream!.close).toHaveBeenCalledOnce();
  });

  it.each([undefined, "not-json", '{"message":"private upstream details"}'])("keeps unknown stream failures generic (%s)", (data) => {
    // Mutation: echoing arbitrary error payloads exposes internal failures.
    let stream: EventTarget;
    class TestEventSource extends EventTarget {
      close() {}
      constructor() { super(); stream = this; }
    }
    vi.stubGlobal("EventSource", TestEventSource);
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent);
    stream!.dispatchEvent(data === undefined ? new Event("error") : new MessageEvent("error", { data }));
    expect(onEvent).toHaveBeenCalledWith({ stage: "error", message: "The refresh stopped before it finished. Try again." });
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
