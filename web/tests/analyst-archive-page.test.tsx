import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
const { archive, shareState, published } = vi.hoisted(() => ({ archive: vi.fn(), shareState: vi.fn(), published: vi.fn() }));
vi.mock("@/lib/api", () => ({ analystArchive: archive, analystShareState: shareState }));
vi.mock("@/lib/public-analyst", () => ({ publicAnalyst: published }));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
import Page from "@/app/league/[id]/analyst/page";

const token = "a".repeat(43);
const media = { id: "b".repeat(32), duration_seconds: 90, video_bytes: 4000000, audio_bytes: 2000000 };
const week4 = { season: 2026, week: 4, league_name: "Test league", generated_at: "2026-10-06T12:00:00Z", markdown: "Week four article", revision: 1, model: "test" };
const week5 = { ...week4, week: 5, markdown: "Week five article" };
const props = { params: { id: "test" }, searchParams: { edition: "2026-4" } };
beforeEach(() => {
  vi.resetAllMocks();
  archive.mockResolvedValue({ editions: [week5, week4] });
  shareState.mockResolvedValue({ token });
  published.mockResolvedValue({ ...week4, media, status: "published" });
});

it("shows existing video and audio for the selected archive edition", async () => {
  // Mutation: omit archive media, use the newest week, or replace the written article.
  render(await Page(props));
  const video = screen.getByLabelText("Week 4 video recap");
  expect(video).toHaveAttribute("src", `/api/public/analyst/${token}/media/${media.id}/video.mp4`);
  expect(screen.getByRole("link", { name: /Download MP3/ })).toHaveAttribute("href", `/api/public/analyst/${token}/media/${media.id}/audio.mp3?download=true`);
  expect(video.compareDocumentPosition(screen.getByText("Week four article")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(shareState).toHaveBeenCalledWith("test", 2026, 4);
});

it.each([
  ["changed article", { markdown: "A different revision" }],
  ["different week", { week: 5 }],
  ["different season", { season: 2025 }],
  ["withdrawn edition", { status: "withdrawn" }],
  ["no media", { media: null }],
])("does not attach media from %s", async (_label, change) => {
  // Mutation: render media without matching publication state and the selected article.
  published.mockResolvedValue({ ...week4, media, status: "published", ...change });
  render(await Page(props));
  expect(screen.queryByLabelText("Week 4 video recap")).not.toBeInTheDocument();
  expect(screen.getByText("Week four article")).toBeInTheDocument();
});

it("keeps an unshared edition readable without creating a share", async () => {
  // Mutation: load media or create a token when existing sharing is disabled.
  shareState.mockResolvedValue({ token: null });
  render(await Page(props));
  expect(screen.getByText("Week four article")).toBeInTheDocument();
  expect(published).not.toHaveBeenCalled();
});

it("explains media lookup failure while preserving the article", async () => {
  // Mutation: swallow media failures or fail the whole archive when media is unavailable.
  published.mockRejectedValue(new Error("upstream unavailable"));
  render(await Page(props));
  expect(screen.getByRole("status")).toHaveTextContent("Video and audio could not be loaded. Reload this page to try again.");
  expect(screen.getByText("Week four article")).toBeInTheDocument();
});

it("does not load media for a missing selected edition", async () => {
  // Mutation: fall back to the newest episode's media on a missing week.
  render(await Page({ ...props, searchParams: { edition: "2026-3" } }));
  expect(screen.getByText("That edition is not available yet.")).toBeInTheDocument();
  expect(shareState).not.toHaveBeenCalled();
});
