import { beforeEach, expect, it, vi } from "vitest";

const cookie = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn() }));
const authToken = vi.hoisted(() => vi.fn());
vi.mock("next/headers", () => ({ cookies: () => cookie }));
vi.mock("@/lib/auth-server", () => ({ getBackendToken: authToken }));
import { POST } from "@/app/api/yahoo/connect/route";
import { GET } from "@/app/api/auth/callback/yahoo/route";
import { POST as proxyPost } from "@/app/api/[...path]/route";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.stubEnv("AUTH_URL", "https://example.test");
  authToken.mockResolvedValue("backend-jwt");
  vi.stubGlobal("fetch", vi.fn());
});

it("rejects cross-origin connect before touching the backend", async () => {
  // Mutation: remove same-origin gate, enabling unsolicited linking flows.
  const response = await POST(new Request("https://example.test/api/yahoo/connect", { method: "POST", headers: { origin: "https://evil.test" } }));
  expect(response.status).toBe(403);
  expect(fetch).not.toHaveBeenCalled();
});

it("starts with a secure browser state cookie and redirects only to Yahoo", async () => {
  // Mutation: fail to bind the browser or redirect to arbitrary upstream URLs.
  vi.mocked(fetch).mockResolvedValue(Response.json({ authorization_url: "https://api.login.yahoo.com/oauth2/request_auth?state=synthetic-state" }));
  const response = await POST(new Request("https://example.test/api/yahoo/connect", { method: "POST", headers: { origin: "https://example.test" } }));
  expect(response.status).toBe(303);
  expect(cookie.set).toHaveBeenCalledWith("yahoo-link-state", "synthetic-state", expect.objectContaining({ httpOnly: true, secure: true, sameSite: "lax", maxAge: 600 }));
  vi.mocked(fetch).mockResolvedValue(Response.json({ authorization_url: "https://evil.test/?state=synthetic-state" }));
  expect((await POST(new Request("https://example.test/api/yahoo/connect", { method: "POST", headers: { origin: "https://example.test" } }))).headers.get("location")).toContain("example.test/leagues/add");
});

it("rejects missing/mismatched browser state without exchanging a code", async () => {
  // Mutation: accept a callback carrying only a state minted in another browser.
  cookie.get.mockReturnValue({ value: "expected" });
  const response = await GET(new Request("https://example.test/api/auth/callback/yahoo?state=attacker&code=secret-code"));
  expect(fetch).not.toHaveBeenCalled();
  expect(response.headers.get("location")).toContain("yahoo=failed");
  expect(response.headers.get("location")).not.toContain("secret-code");
  expect(response.headers.get("referrer-policy")).toBe("no-referrer");
});

it("exchanges once on the server and strips code/state from the redirect", async () => {
  // Mutation: expose code or tokens in the browser response URL.
  cookie.get.mockReturnValue({ value: "expected" });
  vi.mocked(fetch).mockResolvedValue(Response.json({ status: "connected" }));
  const response = await GET(new Request("https://example.test/api/auth/callback/yahoo?state=expected&code=secret-code"));
  expect(response.headers.get("location")).toBe("https://example.test/leagues/add?provider=yahoo&yahoo=connected");
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/me/yahoo/complete"), expect.objectContaining({ body: JSON.stringify({ state: "expected", code: "secret-code" }) }));
  expect(cookie.set).toHaveBeenCalledWith("yahoo-link-state", "", expect.objectContaining({ maxAge: 0 }));
});

it("never exposes OAuth exchange through the generic browser proxy", async () => {
  // Mutation: allow browser callers to bypass the cookie validation route.
  const response = await proxyPost(new Request("https://example.test/api/me/yahoo/complete", { method: "POST" }), { params: { path: ["me", "yahoo", "complete"] } });
  expect(response.status).toBe(404);
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["start", "complete"])("rejects encoded path normalization bypass for %s", async (endpoint) => {
  // Mutation: compare raw path strings while fetch normalizes encoded dot segments.
  const response = await proxyPost(new Request("https://example.test/api/me/yahoo/%252e%252e/yahoo/" + endpoint, { method: "POST", headers: { origin: "https://example.test" } }), { params: { path: ["me", "yahoo", "%2e%2e", "yahoo", endpoint] } });
  expect(response.status).toBe(400);
  expect(fetch).not.toHaveBeenCalled();
});

it.each(["comple\tte", "sta\nrt", "complete "])("rejects URL-stripped characters in %j", async (segment) => {
  // Mutation: allow controls or trailing spaces that fetch strips before routing.
  const response = await proxyPost(new Request("https://example.test/api/me/yahoo/complete", { method: "POST", headers: { origin: "https://example.test" } }), { params: { path: ["me", "yahoo", segment] } });
  expect(response.status).toBe(400);
  expect(fetch).not.toHaveBeenCalled();
});

it("suppresses credential-bearing telemetry", async () => {
  // Mutation: keep OAuth request URLs/bodies or breadcrumbs in sentry events.
  const { redactOAuthEvent } = await import("@/lib/oauth-telemetry");
  expect(redactOAuthEvent({ type: undefined, request: { url: "https://example.test/api/auth/callback/yahoo?code=secret" } })).toBeNull();
  const event = redactOAuthEvent({ type: undefined, breadcrumbs: [{ data: { url: "https://api.login.yahoo.com/oauth2/request_auth?state=secret" } }, { message: "safe" }] });
  expect(event?.breadcrumbs).toEqual([{ message: "safe" }]);
});
