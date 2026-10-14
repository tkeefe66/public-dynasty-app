import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/internal/media/[...path]/route";

const token = "synthetic-worker-token-01234567890123456789";
const upstream = vi.fn();
beforeEach(() => {
  vi.stubEnv("MEDIA_WORKER_TOKEN", token);
  vi.stubEnv("API_URL", "http://api.internal:8000");
  vi.stubGlobal("fetch", upstream);
  upstream.mockReset().mockResolvedValue(new Response("null", { headers: { "content-type": "application/json" } }));
});
afterEach(() => vi.unstubAllGlobals());
function request(body = "{}", headers: Record<string, string> = {}) {
  return new Request("https://example.test/api/internal/media/claim", {
    method: "POST", body, headers: { authorization: `Bearer ${token}`, "content-type": "application/json", ...headers },
  });
}

it.each(["", "Bearer wrong", "Bearer browser-session-jwt"])("rejects unauthorized credentials before forwarding: %s", async (authorization) => {
  // Mutation: relying on browser sessions or forwarding arbitrary bearer tokens.
  expect((await POST(request("{}", { authorization }), { params: { path: ["claim"] } })).status).toBe(403);
  expect(upstream).not.toHaveBeenCalled();
});

it("fails closed when worker configuration is missing", async () => {
  // Mutation: treating an unset token as permission to forward.
  vi.stubEnv("MEDIA_WORKER_TOKEN", "");
  expect((await POST(request(), { params: { path: ["claim"] } })).status).toBe(503);
  expect(upstream).not.toHaveBeenCalled();
});

it("forwards the dedicated principal and lease, without cookies or caller-selected destinations", async () => {
  // Mutation: replacing worker auth with a browser JWT or dropping the lease header.
  await POST(request("{}", { cookie: "private-session", "x-media-lease": "lease", "x-content-sha256": "digest" }), { params: { path: ["claim"] } });
  const [url, init] = upstream.mock.calls[0];
  expect(url).toBe("http://api.internal:8000/api/internal/media/claim");
  expect(init.headers.get("authorization")).toBe(`Bearer ${token}`);
  expect(init.headers.get("x-media-lease")).toBe("lease");
  expect(init.headers.get("cookie")).toBeNull();
  expect(init.redirect).toBe("manual");
  expect(new TextDecoder().decode(init.body)).toBe("{}");
});

it.each([["..", "admin"], ["assets", "%2e%2e"], ["publish"], ["assets", "a/b"]])("rejects routes outside the media protocol: %s", async (...path) => {
  // Mutation: generic path forwarding exposes API admin routes or path traversal.
  expect((await POST(request(), { params: { path } })).status).toBe(404);
  expect(upstream).not.toHaveBeenCalled();
});

it("limits JSON by received bytes even without content-length", async () => {
  // Mutation: trusting only Content-Length permits oversized chunked requests.
  expect((await POST(request("a".repeat(40_001)), { params: { path: ["claim"] } })).status).toBe(413);
  expect(upstream).not.toHaveBeenCalled();
});

it("streams permitted assets and drops upstream cookies and redirects", async () => {
  // Mutation: broad response header forwarding leaks cookies or credentialed redirects.
  upstream.mockResolvedValue(new Response(new Uint8Array([1, 2, 3]), { headers: { "content-type": "audio/mpeg", "set-cookie": "secret", location: "https://elsewhere.test" } }));
  const r = await GET(new Request("https://example.test/api/internal/media/assets/asset-1", { headers: { authorization: `Bearer ${token}` } }), { params: { path: ["assets", "asset-1"] } });
  expect(Array.from(new Uint8Array(await r.arrayBuffer()))).toEqual([1, 2, 3]);
  expect(r.headers.get("set-cookie")).toBeNull();
  expect(r.headers.get("location")).toBeNull();
  expect(r.headers.get("cache-control")).toBe("private, no-store");
});

it("returns a sanitized unavailable response without retrying an uncertain dispatch", async () => {
  // Mutation: retrying network failure can repeat a one-time dispatch request.
  upstream.mockRejectedValue(new Error("secret URL"));
  const r = await POST(request(), { params: { path: ["authorize-dispatch"] } });
  expect(r.status).toBe(503);
  expect(await r.text()).not.toContain("secret URL");
  expect(upstream).toHaveBeenCalledTimes(1);
});
