import { createHash, timingSafeEqual } from "node:crypto";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = process.env.RECAP_MONITOR_PROBE_TOKEN || "";
  const api = process.env.API_URL;
  const headers = { "cache-control": "private, no-store" };
  if (token.length < 32 || !api) return Response.json({ healthy: false }, { status: 503, headers });
  const hash = (value: string) => createHash("sha256").update(value).digest();
  if (!timingSafeEqual(hash(request.headers.get("authorization") || ""), hash(`Bearer ${token}`))) {
    return Response.json({ detail: "Monitor probe credential required" }, { status: 403, headers });
  }
  try {
    const upstream = await fetch(`${api.replace(/\/$/, "")}/api/internal/media/recap-monitor-health`, {
      headers: { authorization: `Bearer ${token}` }, cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(15000),
    });
    if (!upstream.ok) throw new Error("Health upstream unavailable");
    const body = await upstream.json();
    return Response.json({ healthy: body.healthy, reason: body.reason,
      checked_at: body.checked_at, heartbeat_at: body.heartbeat_at }, { headers });
  } catch {
    return Response.json({ healthy: false, reason: "monitor_api_unreachable" }, { status: 503, headers });
  }
}
