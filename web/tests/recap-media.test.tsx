import { fireEvent, render, screen } from "@testing-library/react";
import { transferableAbortController } from "node:util";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RecapMedia } from "@/components/RecapMedia";
import { GET, HEAD } from "@/app/api/public/analyst/[token]/media/[bundle]/[asset]/route";

const token = "a".repeat(43);
const id = "b".repeat(32);
const media = { id, duration_seconds: 122, video_bytes: 4000000, audio_bytes: 2000000 };
const base = `/api/public/analyst/${token}/media/${id}`;
const params = { token, bundle: id, asset: "video.mp4" };
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
// Route handlers run in Node. jsdom's AbortSignal lacks Node's any() method.
beforeEach(() => {
  const controller = transferableAbortController();
  vi.stubGlobal("AbortSignal", controller.signal.constructor);
  vi.stubGlobal("AbortController", controller.constructor);
  // jsdom 25 strips Range in Headers.set even with guard=none; use Node's
  // Headers, which is the actual runtime of this streaming route.
  vi.stubGlobal("Headers", new Request("https://example.test/").headers.constructor);
});

it("offers inline mobile playback, captions, and direct file downloads", () => {
  // Mutation: point media at a private route or omit inline playback and downloads.
  render(<RecapMedia token={token} media={media} week={4} />);
  const video = screen.getByLabelText("Week 4 video recap");
  expect(video).toHaveAttribute("src", `${base}/video.mp4`);
  expect(video).toHaveAttribute("playsinline");
  expect(video).toHaveAttribute("controls");
  expect(video).not.toHaveAttribute("autoplay");
  expect(video.querySelector("track")).toHaveAttribute("src", `${base}/captions.vtt`);
  expect(screen.getByRole("link", { name: /Download MP4/ })).toHaveAttribute("href", `${base}/video.mp4?download=true`);
  expect(screen.getByRole("link", { name: /Download MP3/ })).toHaveAttribute("href", `${base}/audio.mp3?download=true`);
  fireEvent.error(video);
  expect(screen.getByRole("alert")).toHaveTextContent("Reload this page");
});

it("streams ranges anonymously with length intact and forwards only the download flag", async () => {
  // Mutation: drop Range/Content-Length, buffer the stream, or forward arbitrary query parameters.
  const fetcher = vi.fn().mockResolvedValue(new Response(new Uint8Array([4, 5]), { status: 206,
    headers: { "content-type": "video/mp4", "content-length": "2", "content-range": "bytes 4-5/10", "accept-ranges": "bytes" } }));
  vi.stubGlobal("fetch", fetcher);
  const req = new Request(`https://example.test${base}/video.mp4?download=true&evil=1`, { headers: { Range: "bytes=4-5" } });
  expect(req.headers.get("range")).toBe("bytes=4-5");
  const res = await GET(req, { params });
  expect(res.status).toBe(206);
  expect(res.headers.get("content-length")).toBe("2");
  expect(res.headers.get("content-range")).toBe("bytes 4-5/10");
  expect(res.headers.get("cache-control")).toContain("no-store");
  expect(Array.from(new Uint8Array(await res.arrayBuffer()))).toEqual([4, 5]);
  expect(fetcher.mock.calls[0][0]).toMatch(/video\.mp4\?download=true$/);
  expect(fetcher.mock.calls[0][1].headers.get("range")).toBe("bytes=4-5");
  expect(fetcher.mock.calls[0][1].headers.has("authorization")).toBe(false);
});

it("rejects traversal and non-media paths before any backend request", async () => {
  // Mutation: let this anonymous proxy fetch arbitrary API routes or filesystem paths.
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  for (const bad of [{ ...params, asset: "manifest.json" }, { ...params, bundle: ".." }, { ...params, token: "guess" }]) {
    const response = await GET(new Request("https://example.test/"), { params: bad });
    expect(response.status).toBe(404);
  }
  expect(fetcher).not.toHaveBeenCalled();
});

it("preserves revocation and HEAD responses without caching and handles upstream failures", async () => {
  // Mutation: turn upstream errors into a successful media response or cache a revoked link.
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
  expect((await HEAD(new Request("https://example.test/", { method: "HEAD" }), { params })).status).toBe(404);
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("private backend address")));
  const res = await GET(new Request("https://example.test/"), { params });
  expect(res.status).toBe(503);
  expect(res.headers.get("cache-control")).toContain("no-store");
  expect(await res.text()).not.toContain("private backend address");
});

it("keeps slow transfers alive after headers but still cancels on client disconnect", async () => {
  // Mutation: leave the connection deadline running after the response body starts.
  vi.useFakeTimers();
  const controller = new AbortController();
  const fetcher = vi.fn().mockResolvedValue(new Response("media", { headers: { "content-type": "video/mp4" } }));
  vi.stubGlobal("fetch", fetcher);
  await GET(new Request("https://example.test/", { signal: controller.signal }), { params });
  await vi.advanceTimersByTimeAsync(130000);
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false);
  controller.abort();
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
});
