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

describe('authenticated private recap preview streaming', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('preserves ranges and byte length through the authenticated proxy', async () => {
    getBackendToken.mockResolvedValue('throwaway');
    // jsdom's Headers silently forbids Range; this route runs in Node.
    vi.stubGlobal('Headers', new Request('http://synthetic.invalid').headers.constructor);
    const fetchSpy = vi.fn().mockResolvedValue(new Response('bytes', { status: 206, headers: {
      'content-type': 'video/mp4', 'content-length': '5', 'content-range': 'bytes 5-9/20', 'accept-ranges': 'bytes',
    } }));
    vi.stubGlobal('fetch', fetchSpy);
    const path = ['admin', 'generation', 'recap-episodes', 'synthetic', 'preview', 'media', 'video.mp4'];
    const request = new Request('http://web/api/' + path.join('/'), { headers: { Range: 'bytes=5-9', 'If-Range': 'synthetic-etag' } });
    const response = await GET(request, ctx(path));
    expect(fetchSpy.mock.calls[0][1].headers.get('range')).toBe('bytes=5-9');
    expect(fetchSpy.mock.calls[0][1].headers.get('if-range')).toBe('synthetic-etag');
    expect(fetchSpy.mock.calls[0][1].signal).toBe(request.signal);
    expect(response.headers.get('content-length')).toBe('5');
    expect(response.headers.get('content-range')).toBe('bytes 5-9/20');
    expect(await response.text()).toBe('bytes');
  });
});

it('HEAD keeps private preview byte metadata and has no body', async () => {
  const { HEAD } = await import('../app/api/[...path]/route');
  getBackendToken.mockResolvedValue('throwaway');
  vi.stubGlobal('Headers', new Request('http://synthetic.invalid').headers.constructor);
  const fetchSpy = vi.fn().mockResolvedValue(new Response(null, { headers: { 'content-length': '42', 'accept-ranges': 'bytes' } }));
  vi.stubGlobal('fetch', fetchSpy);
  try {
    const path = ['admin','generation','recap-episodes','synthetic','preview','media','video.mp4'];
    const response = await HEAD(new Request('http://web/api/' + path.join('/'), { method: 'HEAD' }), ctx(path));
    expect(fetchSpy.mock.calls[0][1].method).toBe('HEAD');
    expect(response.headers.get('content-length')).toBe('42');
    expect(response.headers.get('accept-ranges')).toBe('bytes');
    expect(await response.text()).toBe('');
  } finally { vi.unstubAllGlobals(); }
});

it('preserves unsatisfiable preview range status and total length', async () => {
  getBackendToken.mockResolvedValue('throwaway');
  vi.stubGlobal('Headers', new Request('http://synthetic.invalid').headers.constructor);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 416, headers: { 'content-range': 'bytes */42' } })));
  try {
    const path = ['admin','generation','recap-episodes','synthetic','preview','media','video.mp4'];
    const response = await GET(new Request('http://web/api/' + path.join('/'), { headers: { Range: 'bytes=100-200' } }), ctx(path));
    expect(response.status).toBe(416);
    expect(response.headers.get('content-range')).toBe('bytes */42');
  } finally { vi.unstubAllGlobals(); }
});
