import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mock the server-only auth module so importing the route handler doesn't pull
// in `server-only` / next-auth (which throw outside an RSC/server runtime).
const { getBackendToken } = vi.hoisted(() => ({
  getBackendToken: vi.fn<() => Promise<string | null>>(),
}));
vi.mock("@/lib/auth-server", () => ({ getBackendToken }));

import { GET, POST } from "../app/api/[...path]/route";

const ctx = (path: string[]) => ({ params: { path } });

describe("api proxy route handler", () => {
  beforeEach(() => {
    getBackendToken.mockReset();
    process.env.API_URL = "http://backend:8000";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns 401 when there is no session token", async () => {
    getBackendToken.mockResolvedValue(null);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const res = await GET(
      new Request("http://web/api/league/L1"),
      ctx(["league", "L1"]),
    );

    expect(res.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("forwards to the backend with a Bearer header and query string", async () => {
    getBackendToken.mockResolvedValue("tok-123");
    const upstream = new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
    const fetchSpy = vi.fn().mockResolvedValue(upstream);
    vi.stubGlobal("fetch", fetchSpy);

    const res = await GET(
      new Request("http://web/api/league/L1/trades?year=2024"),
      ctx(["league", "L1", "trades"]),
    );

    expect(res.status).toBe(200);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/league/L1/trades?year=2024");
    expect((init.headers as Headers).get("authorization")).toBe("Bearer tok-123");
    expect(await res.json()).toEqual({ ok: true });
  });

  it("passes through an SSE stream unbuffered", async () => {
    getBackendToken.mockResolvedValue("tok-123");
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: progress\ndata: {}\n\n"));
        controller.close();
      },
    });
    const upstream = new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(upstream));

    const res = await GET(
      new Request("http://web/api/league/L1/refresh"),
      ctx(["league", "L1", "refresh"]),
    );

    expect(res.headers.get("content-type")).toBe("text/event-stream");
    expect(res.headers.get("x-accel-buffering")).toBe("no");
    const text = await res.text();
    expect(text).toContain("event: progress");
  });

  it("forwards a POST body", async () => {
    getBackendToken.mockResolvedValue("tok-123");
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);

    await POST(
      new Request("http://web/api/league/L1/owner-names", {
        method: "POST",
        body: JSON.stringify({ overrides: {} }),
        headers: { "content-type": "application/json" },
      }),
      ctx(["league", "L1", "owner-names"]),
    );

    const [, init] = fetchSpy.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBeDefined();
  });
});
