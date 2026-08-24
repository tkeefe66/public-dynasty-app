import { getBackendToken } from "@/lib/auth-server";

// Node runtime so we can stream a long-lived upstream body (the SSE refresh
// endpoint holds one connection open for the whole refresh, then flushes).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Hop-by-hop / encoding headers we must not copy from the upstream response.
const STRIP_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function proxy(req: Request, path: string[]): Promise<Response> {
  const token = await getBackendToken();
  if (!token) {
    return new Response(JSON.stringify({ detail: "unauthorized" }), {
      status: 401,
      headers: { "content-type": "application/json" },
    });
  }

  const apiUrl = process.env.API_URL || "http://localhost:8000";
  const url = new URL(req.url);
  const target = `${apiUrl}/api/${path.join("/")}${url.search}`;

  const headers = new Headers();
  headers.set("authorization", `Bearer ${token}`);
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const accept = req.headers.get("accept");
  if (accept) headers.set("accept", accept);

  const init: RequestInit = {
    method: req.method,
    headers,
    redirect: "manual",
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.arrayBuffer();
  }

  const upstream = await fetch(target, init);

  // Stream the body through unbuffered. Critical for SSE (text/event-stream):
  // we pass upstream.body (a ReadableStream) straight through — never buffer
  // with .text()/.json(), or the refresh progress stream hangs until close.
  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE_HEADERS.has(key.toLowerCase())) {
      respHeaders.set(key, value);
    }
  });
  if ((upstream.headers.get("content-type") || "").includes("text/event-stream")) {
    respHeaders.set("cache-control", "no-cache, no-transform");
    respHeaders.set("x-accel-buffering", "no");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: respHeaders,
  });
}

type Ctx = { params: { path: string[] } };

export async function GET(req: Request, { params }: Ctx) {
  return proxy(req, params.path);
}
export async function POST(req: Request, { params }: Ctx) {
  return proxy(req, params.path);
}
export async function PUT(req: Request, { params }: Ctx) {
  return proxy(req, params.path);
}
export async function PATCH(req: Request, { params }: Ctx) {
  return proxy(req, params.path);
}
export async function DELETE(req: Request, { params }: Ctx) {
  return proxy(req, params.path);
}
