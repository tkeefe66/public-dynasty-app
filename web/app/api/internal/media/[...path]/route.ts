import { createHash, timingSafeEqual } from "node:crypto";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const JSON_LIMIT = 40_000;
const ASSET_LIMIT = 64 * 1024 * 1024;
const POSTS = new Set(["claim", "heartbeat", "complete", "authorize-dispatch", "receipt",
  "identity", "recovery-claim", "recovery-complete", "recovery-receipt", "assets"]);
const ID = "[A-Za-z0-9_-]{1,64}";
const failure = (status: number, detail: string) => Response.json({ detail }, {
  status, headers: { "cache-control": "private, no-store" },
});

async function proxy(req: Request, path: string[]) {
  const route = path.join("/");
  const upload = req.method === "POST" && (route === "assets" || new RegExp(`^attempts/${ID}/audio$`).test(route));
  const allowed = req.method === "GET"
    ? new RegExp(`^(assets/${ID}|attempts/${ID}/recovery)$`).test(route)
    : req.method === "POST" && (POSTS.has(route) || upload);
  if (!allowed || path.some((part) => !/^[A-Za-z0-9_-]+$/.test(part)) || new URL(req.url).search) {
    return failure(404, "Unknown media protocol route");
  }
  const token = process.env.MEDIA_WORKER_TOKEN || "";
  const api = process.env.API_URL;
  if (token.length < 32 || !api) return failure(503, "Media worker gateway is not configured");
  const expected = createHash("sha256").update(`Bearer ${token}`).digest();
  const supplied = createHash("sha256").update(req.headers.get("authorization") || "").digest();
  if (!timingSafeEqual(expected, supplied)) return failure(403, "Dedicated media worker credential required");

  // This route never accepts browser cookies or mints an administrator JWT.
  // The API independently checks the principal, capability, lease and budget.
  const headers = new Headers({ authorization: `Bearer ${token}`, "accept-encoding": "identity" });
  for (const name of ["content-type", "x-media-lease", "x-content-sha256"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const limit = upload ? ASSET_LIMIT : JSON_LIMIT;
  let body: Uint8Array | undefined;
  if (req.method === "POST") {
    if (Number(req.headers.get("content-length")) > limit) return failure(413, "Media request exceeds maximum body size");
    const reader = req.body?.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    if (reader) {
      try {
        while (true) {
          const next = await reader.read();
          if (next.done) break;
          size += next.value.byteLength;
          if (size > limit) {
            await reader.cancel();
            return failure(413, "Media request exceeds maximum body size");
          }
          chunks.push(next.value);
        }
      } catch {
        return failure(400, "Media request body was interrupted");
      }
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  try {
    // No redirects or retries: a failed response may follow a committed dispatch.
    const upstream = await fetch(`${api.replace(/\/$/, "")}/api/internal/media/${route}`, {
      method: req.method, headers, body, cache: "no-store", redirect: "manual", signal: req.signal,
    });
    const responseHeaders = new Headers({ "cache-control": "private, no-store" });
    const contentType = upstream.headers.get("content-type");
    if (contentType) responseHeaders.set("content-type", contentType);
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    console.error("Media gateway upstream unavailable; preserve saved attempt and check API status");
    return failure(503, "Media API unavailable; check saved attempt before retrying dispatch");
  }
}

type Context = { params: { path: string[] } };
export async function GET(req: Request, { params }: Context) { return proxy(req, params.path); }
export async function POST(req: Request, { params }: Context) { return proxy(req, params.path); }
