// Narrow anonymous streaming proxy. The API validates the revocable capability
// on every request. Never attach a user's backend token or accept arbitrary URLs.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Ctx = { params: { token: string; bundle: string; asset: string } };
const ASSETS = new Set(["video.mp4", "audio.mp3", "poster.jpg", "captions.vtt"]);
const PRIVATE = { "cache-control": "private, no-store", "referrer-policy": "no-referrer",
  "x-robots-tag": "noindex, nofollow, noarchive", "x-content-type-options": "nosniff" };

async function stream(req: Request, { params }: Ctx) {
  const { token, bundle, asset } = params;
  if (!/^[A-Za-z0-9_-]{43}$/.test(token) || !/^[a-f0-9]{32}$/.test(bundle) || !ASSETS.has(asset)) {
    return new Response(null, { status: 404, headers: PRIVATE });
  }
  const suffix = new URL(req.url).searchParams.get("download") === "true" ? "?download=true" : "";
  const target = `${process.env.API_URL || "http://localhost:8000"}/api/public/analyst/${token}/media/${bundle}/${asset}${suffix}`;
  const headers = new Headers({ "accept-encoding": "identity" });
  for (const name of ["range", "if-range"]) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const connection = new AbortController();
  const deadline = setTimeout(() => connection.abort(), 10000);
  try {
    const upstream = await fetch(target, { method: req.method, headers, cache: "no-store", redirect: "error",
      signal: AbortSignal.any([req.signal, connection.signal]) });
    const output = new Headers(PRIVATE);
    for (const name of ["content-type", "content-length", "content-range", "accept-ranges", "content-disposition", "etag", "last-modified"]) {
      const value = upstream.headers.get(name);
      if (value) output.set(name, value);
    }
    return new Response(req.method === "HEAD" ? null : upstream.body, { status: upstream.status, headers: output });
  } catch {
    // Exception URLs contain share credentials: never print the thrown error.
    console.error("Shared recap media upstream unavailable");
    return new Response(req.method === "HEAD" ? null : "Media could not be loaded. Reload the recap to try again.", { status: 503, headers: PRIVATE });
  } finally {
    // Bound connection/header waits, not transfer time: a slow phone download
    // may legitimately take minutes. Client disconnect still aborts the body.
    clearTimeout(deadline);
  }
}

export const GET = stream;
export const HEAD = stream;
