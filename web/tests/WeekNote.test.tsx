import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { WeekNote } from "@/components/WeekNote";

/**
 * The week note is a whisper (followup C2): it renders the drawn copy in season
 * and NOTHING otherwise — not a placeholder, not an error. Only the in-season
 * case was drawn, so silence is the specified behavior everywhere else.
 */

function mockState(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok, json: () => Promise.resolve(body) }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WeekNote", () => {
  it("renders the drawn copy during the regular season", async () => {
    mockState({ season: "2026", season_type: "regular", week: 14 });
    render(<WeekNote />);
    // Exact wording from design-system/templates/Dashboard.dc.html.
    expect(await screen.findByText("Currently it is Week 14")).toBeInTheDocument();
  });

  it("renders nothing before the fetch resolves", () => {
    mockState({ season: "2026", season_type: "regular", week: 14 });
    const { container } = render(<WeekNote />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing outside the regular season", async () => {
    for (const season_type of ["post", "off", "pre"]) {
      mockState({ season: "2026", season_type, week: 3 });
      const { container, unmount } = render(<WeekNote />);
      await waitFor(() => expect(fetch).toHaveBeenCalled());
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it("renders nothing when the request fails", async () => {
    mockState(null, false);
    const { container } = render(<WeekNote />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when fetch rejects outright", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { container } = render(<WeekNote />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the week is missing or zero", async () => {
    for (const week of [null, 0, "soon"]) {
      mockState({ season: "2026", season_type: "regular", week });
      const { container, unmount } = render(<WeekNote />);
      await waitFor(() => expect(fetch).toHaveBeenCalled());
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
});
