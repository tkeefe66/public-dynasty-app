import { cookies } from "next/headers";
import { getBackendToken } from "@/lib/auth-server";
import { appOrigin, sameOrigin, YAHOO_STATE_COOKIE } from "@/lib/yahoo-oauth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  if (!sameOrigin(req)) return new Response("Invalid request origin", { status: 403 });
  const token = await getBackendToken();
  if (!token) return new Response("Sign in before connecting Yahoo", { status: 401 });
  try {
    const upstream = await fetch(`${process.env.API_URL || "http://localhost:8000"}/api/me/yahoo/start`, {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    if (!upstream.ok) throw new Error("Yahoo connection unavailable");
    const body = await upstream.json();
    const url = new URL(body.authorization_url);
    const state = url.searchParams.get("state");
    if (url.origin !== "https://api.login.yahoo.com" || url.pathname !== "/oauth2/request_auth" || !state) throw new Error("Invalid authorization destination");
    cookies().set(YAHOO_STATE_COOKIE, state, {
      httpOnly: true, secure: appOrigin().startsWith("https:"), sameSite: "lax",
      path: "/api/auth/callback/yahoo", maxAge: 600,
    });
    return new Response(null, { status: 303, headers: { Location: url.toString(), "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" } });
  } catch {
    return Response.redirect(`${appOrigin()}/leagues/add?provider=yahoo&yahoo=failed`, 303);
  }
}
