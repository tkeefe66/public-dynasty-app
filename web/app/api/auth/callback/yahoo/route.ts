import { timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { getBackendToken } from "@/lib/auth-server";
import { appOrigin, YAHOO_STATE_COOKIE } from "@/lib/yahoo-oauth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const params = new URL(req.url).searchParams;
  const expected = cookies().get(YAHOO_STATE_COOKIE)?.value;
  cookies().set(YAHOO_STATE_COOKIE, "", { path: "/api/auth/callback/yahoo", maxAge: 0 });
  const state = params.get("state");
  let result = "failed";
  try {
    const token = await getBackendToken();
    if (!token || !expected || !state || expected.length !== state.length || !timingSafeEqual(Buffer.from(expected), Buffer.from(state))) throw new Error("Invalid callback");
    if (params.get("error") === "access_denied") result = "cancelled";
    else {
      const code = params.get("code");
      if (!code || params.has("error")) throw new Error("Invalid callback");
      const upstream = await fetch(`${process.env.API_URL || "http://localhost:8000"}/api/me/yahoo/complete`, {
        method: "POST", cache: "no-store", signal: AbortSignal.timeout(30_000),
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ state, code }),
      });
      if (upstream.ok) result = "connected";
    }
  } catch {
    // OAuth codes, state and upstream bodies must never appear in logs or URLs.
    result = "failed";
  }
  return new Response(null, { status: 303, headers: {
    Location: `${appOrigin()}/leagues/add?provider=yahoo&yahoo=${result}`,
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
  } });
}
