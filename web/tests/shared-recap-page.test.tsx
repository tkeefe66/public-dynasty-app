import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
const { load } = vi.hoisted(() => ({ load: vi.fn() }));
vi.mock("@/lib/public-analyst", () => ({ publicAnalyst: load }));
import Page, { generateMetadata } from "@/app/share/analyst/[token]/page";

it("gives text-message previews the episode poster and keeps the article below the player", async () => {
  // Mutation: leave empty OG images, point at a private asset, or replace the written recap.
  const token = "a".repeat(43), id = "b".repeat(32);
  load.mockResolvedValue({ season: 2026, week: 4, league_name: "Test league", markdown: "Verified written recap",
    media: { id, duration_seconds: 135, video_bytes: 4000000, audio_bytes: 2000000 } });
  const metadata = await generateMetadata({ params: { token } });
  expect(metadata.openGraph?.images).toEqual([{ url: `/api/public/analyst/${token}/media/${id}/poster.jpg`, alt: "Weekly recap · Week 4 · Test league" }]);
  expect(metadata.twitter).toMatchObject({ card: "summary_large_image" });
  render(await Page({ params: { token } }));
  const video = screen.getByLabelText("Week 4 video recap");
  expect(video.compareDocumentPosition(screen.getByText("Verified written recap")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("keeps text-only editions readable without advertising absent media", async () => {
  // Mutation: render a broken player and poster when the API has no current media.
  load.mockResolvedValue({ season: 2026, week: 4, league_name: "Test league", markdown: "Text only", media: null });
  const metadata = await generateMetadata({ params: { token: "a".repeat(43) } });
  expect(metadata.openGraph?.images).toEqual([]);
  render(await Page({ params: { token: "a".repeat(43) } }));
  expect(screen.queryByLabelText("Week 4 video recap")).not.toBeInTheDocument();
  expect(screen.getByText("Text only")).toBeInTheDocument();
});

it("shows correction status at the same URL without stale article or media", async () => {
  // Mutation: ignore DB withdrawal and render retained article/media projections.
  load.mockResolvedValue({ season: 2026, week: 4, league_name: "Test league", status: "withdrawn", markdown: "Stale score", media: null });
  render(await Page({ params: { token: "a".repeat(43) } }));
  expect(screen.getByRole("heading", { name: "This recap is being corrected." })).toBeInTheDocument();
  expect(screen.queryByText("Stale score")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Week 4 video recap")).not.toBeInTheDocument();
});
