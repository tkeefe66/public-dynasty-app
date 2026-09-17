import { expect, it, vi } from "vitest";

vi.mock("@/auth", () => ({ auth: (handler: unknown) => handler }));
import middleware from "@/middleware";

it("permits only the shared article route without login", async () => {
  // Mutation: allow all /share or /league routes instead of the exact public page shape.
  const run = middleware as unknown as (request: unknown) => Response | undefined;
  const request = (path: string) => ({ auth: null, nextUrl: new URL(`https://example.com${path}`), headers: new Headers() });
  expect(run(request(`/share/analyst/${"a".repeat(43)}`))).toBeUndefined();
  for (const path of ["/league/test", "/league/test/analyst", "/share/analyst/a/private", "/share/other/a", "/admin"]) {
    const response = run(request(path));
    expect(response?.headers.get("location")).toBe("https://example.com/login");
  }
});
