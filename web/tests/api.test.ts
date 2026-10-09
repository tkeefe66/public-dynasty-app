import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { ApiError, dashboard, refreshStream } from "../lib/api";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => vi.unstubAllGlobals());

  it("turns a durable Yahoo provider hold into an actionable error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      id: "job", state: "needs_attention", reason: "yahoo_rate_limited", progress: {},
      message: "private upstream details",
    }), { status: 202 }));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent);
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({ stage: "error", message: expect.stringMatching(/Yahoo.*wait/i) }));
    expect(onEvent.mock.calls[0][0].message).not.toContain("private");
  });

  it("keeps server exceptions private", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "private upstream details" }), { status: 500 }));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent);
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({ stage: "error", message: expect.stringMatching(/needs attention/) }));
    expect(onEvent.mock.calls[0][0].message).not.toContain("private");
  });

  it("submits once, observes with GET, and finishes without another submission", async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job", state: "queued", reason: "", progress: {} }), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job", state: "succeeded", reason: "", progress: {} })));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent);
    await vi.runAllTimersAsync();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(fetchSpy.mock.calls[0][1]?.method).toBe("POST");
    expect(fetchSpy.mock.calls[1][1]?.method).toBeUndefined();
    expect(fetchSpy.mock.calls[1][0]).toContain("/refresh-jobs/job");
    expect(onEvent).toHaveBeenLastCalledWith({ stage: "done" });
    vi.useRealTimers();
  });

  it("closing the watcher never cancels the durable job", async () => {
    vi.useFakeTimers();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "job", state: "queued", progress: {} })));
    const onEvent = vi.fn();
    const watcher = refreshStream("synthetic-league", onEvent);
    watcher.close();
    await vi.runAllTimersAsync();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(onEvent).not.toHaveBeenCalled();
    expect(fetchSpy.mock.calls[0][0]).toMatch(/refresh-jobs$/);
    vi.useRealTimers();
  });

  it("reopens a failed job with GET and never submits another refresh", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      id: "failed-job", state: "needs_attention", reason: "execution_failed", progress: {},
    })));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent, { jobId: "failed-job" });
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({
      stage: "error", message: expect.stringMatching(/needs attention/),
    }));
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toMatch(/refresh-jobs\/failed-job$/);
    expect(fetchSpy.mock.calls[0][1]?.method).toBeUndefined();
  });

  it("preserves the caller's first-build key across effect restarts", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      id: "job", state: "succeeded", reason: "", progress: {},
    }), { status: 202 }));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent, { idempotencyKey: "one-first-build" });
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({ stage: "done" }));
    expect(JSON.parse(fetchSpy.mock.calls[0][1]?.body as string)).toEqual({
      idempotency_key: "one-first-build",
    });
  });

  it("stops watching an unrecognized state instead of claiming it is queued", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      id: "job", state: "new-terminal-state", reason: "private details", progress: {},
    })));
    const onEvent = vi.fn();
    refreshStream("synthetic-league", onEvent, { jobId: "job" });
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith({
      stage: "error", message: expect.stringMatching(/needs attention/),
    }));
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(onEvent.mock.calls[0][0].message).not.toContain("private");
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
