/**
 * The League Settings phone layout.
 *
 * The defect this locks down: owner display names shipped as a two-column
 * `label | input` grid with the handle pinned to a fixed `w-32`, which left the
 * input around 150px wide at 390px — the field the page exists to edit was the
 * smallest thing on it. The contract now is ONE CARD PER OWNER, the handle as a
 * real `<label>`, and a full-width 44px input beneath it.
 *
 * These assertions are about STRUCTURE, not pixels: jsdom has no layout, so
 * "the input fills the card" is asserted as the classes that make it so
 * (`w-full`, `min-h-tap`) plus the absence of the fixed-width label column.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import { OwnerNamesForm } from "../components/OwnerNamesForm";
import { ManualRefresh } from "../components/ManualRefresh";

const putOwnerNames = vi.fn();
const refreshStream = vi.fn();

vi.mock("@/lib/api", () => ({
  putOwnerNames: (...args: unknown[]) => putOwnerNames(...args),
  refreshStream: (...args: unknown[]) => refreshStream(...args),
}));

const OWNERS = [
  { user_id: "u1", sleeper_name: "tkeefe", display_name: "Tom" },
  { user_id: "u2", sleeper_name: "joeybats", display_name: null },
  { user_id: "u3", sleeper_name: "amir", display_name: "Amir" },
];

beforeEach(() => {
  putOwnerNames.mockReset();
  refreshStream.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("OwnerNamesForm — one card per owner", () => {
  it("renders exactly one card per owner, each holding one input", () => {
    const { container } = render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);

    // EntryCard is the mobile entry primitive: a rounded, ruled, surfaced box.
    // Its edge IS the entry boundary, which is why there is no `border-t` on it.
    const cards = container.querySelectorAll("div.rounded-panel");
    expect(cards).toHaveLength(OWNERS.length);
    for (const card of Array.from(cards)) {
      expect(card.querySelectorAll("input")).toHaveLength(1);
      expect(card.querySelectorAll("label")).toHaveLength(1);
      // A card must not draw a top rule — that is what separates entries.
      expect(card.className).not.toMatch(/\bborder-t\b/);
    }
  });

  it("keeps a real <label for> association, not an aria-label", () => {
    const { container } = render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);

    for (const o of OWNERS) {
      const input = screen.getByLabelText(o.sleeper_name) as HTMLInputElement;
      expect(input.tagName).toBe("INPUT");
      expect(input.id).toBeTruthy();
      const label = container.querySelector(`label[for="${input.id}"]`);
      expect(label, `no <label for> pointing at ${o.sleeper_name}'s input`).not.toBeNull();
      expect(label!.textContent).toBe(o.sleeper_name);
    }
  });

  it("gives every input the full card width and a 44px tap target", () => {
    const { container } = render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);

    for (const input of Array.from(container.querySelectorAll("input"))) {
      expect(input.className).toMatch(/\bw-full\b/);
      expect(input.className).toMatch(/\bmin-h-tap\b/);
    }
    // The retired shape: a fixed-width handle column stealing the input's room.
    expect(container.innerHTML).not.toMatch(/\bw-32\b/);
  });

  it("prefills from display_name and falls back to empty, not the handle", () => {
    render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);
    expect((screen.getByLabelText("tkeefe") as HTMLInputElement).value).toBe("Tom");
    // display_name null → empty value, with the handle only as a placeholder.
    const blank = screen.getByLabelText("joeybats") as HTMLInputElement;
    expect(blank.value).toBe("");
    expect(blank.placeholder).toBe("joeybats");
  });

  it("still submits the whole owner map from one primary button", async () => {
    putOwnerNames.mockResolvedValue(undefined);
    render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);

    fireEvent.change(screen.getByLabelText("joeybats"), {
      target: { value: "Joey" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save names" }));

    await waitFor(() => expect(putOwnerNames).toHaveBeenCalledTimes(1));
    expect(putOwnerNames).toHaveBeenCalledWith("L", {
      u1: "Tom",
      u2: "Joey",
      u3: "Amir",
    });
    await screen.findByRole("button", { name: "Saved" });
  });

  it("has exactly one primary (stamp-filled) button", () => {
    const { container } = render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);
    const primaries = Array.from(container.querySelectorAll("button")).filter((b) =>
      /\bbg-stamp\b/.test(b.className),
    );
    expect(primaries).toHaveLength(1);
    expect(primaries[0].className).toMatch(/\bmin-h-tap\b/);
  });

  it("surfaces a failed save as an alert", async () => {
    putOwnerNames.mockRejectedValue(new Error("nope"));
    render(<OwnerNamesForm leagueId="L" initial={OWNERS} />);
    fireEvent.click(screen.getByRole("button", { name: "Save names" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Save failed. Try again.");
  });
});

/** The card body, with whitespace collapsed so `Meta`'s "label + value" pairs
 *  read as one string. `Meta` emits `<span>Teams <b>12</b></span>`, so a query
 *  for the exact text "Teams" would never match — assert on the card instead. */
function cardText(container: HTMLElement): string {
  const card = container.querySelector("div.rounded-panel");
  expect(card, "no EntryCard rendered").not.toBeNull();
  return (card as HTMLElement).textContent!.replace(/\s+/g, " ");
}

/** Capture the SSE callback so a test can drive the stream by hand. */
function captureStream() {
  const box: { emit: ((e: { stage: string }) => void) | null } = { emit: null };
  refreshStream.mockImplementation(
    (_id: string, cb: (e: { stage: string }) => void) => {
      box.emit = cb;
      return { close: () => {} };
    },
  );
  return box;
}

describe("ManualRefresh — the admin data card", () => {
  it("presents league state as a card, with the action as a secondary button", () => {
    const { container } = render(
      <ManualRefresh leagueId="L" teams={12} season={2025} warm={true} />,
    );

    const text = cardText(container);
    expect(text).toContain("Last refreshed");
    expect(text).toContain("Teams 12");
    expect(text).toContain("Season 2025");
    expect(text).toContain("Cache Built");

    // Secondary, not a second stamp fill — one primary per view, and that one
    // is `Save names` on the owner list above.
    const action = screen.getByRole("button", { name: "Refresh data" });
    expect(action.className).not.toMatch(/\bbg-stamp\b/);
    expect(action.className).toMatch(/\bborder-rule-strong\b/);
    expect(action.className).toMatch(/\bmin-h-tap\b/);
  });

  it("renders em dashes rather than inventing figures it wasn't given", () => {
    const { container } = render(
      <ManualRefresh leagueId="L" teams={null} season={null} warm={null} />,
    );
    const text = cardText(container);
    expect(text).toContain("Teams —");
    expect(text).toContain("Season —");
    expect(text).toContain("Cache —");
  });

  it("says Not built when the chain cache is cold", () => {
    const { container } = render(
      <ManualRefresh leagueId="L" teams={12} season={2025} warm={false} />,
    );
    expect(cardText(container)).toContain("Cache Not built");
  });

  it("streams a refresh and stamps the time it finished", async () => {
    const stream = captureStream();

    const { container } = render(
      <ManualRefresh leagueId="L" teams={12} season={2025} warm={true} />,
    );
    expect(cardText(container)).toContain("Last refreshed—");

    fireEvent.click(screen.getByRole("button", { name: "Refresh data" }));
    expect(refreshStream).toHaveBeenCalledWith("L", expect.any(Function));
    await screen.findByRole("button", { name: "Refreshing…" });

    act(() => stream.emit!({ stage: "done" }));

    await screen.findByRole("button", { name: "Refresh data" });
    expect(screen.getByText("Refresh complete.")).toBeInTheDocument();
    // The headline now reads a clock time, not the em dash.
    expect(cardText(container)).not.toContain("Last refreshed—");
    expect(cardText(container)).toMatch(/Last refreshed\s*\d{1,2}:\d{2}/);
  });

  it("reports a failed stream as an alert", async () => {
    const stream = captureStream();
    render(<ManualRefresh leagueId="L" teams={12} season={2025} warm={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh data" }));
    act(() => stream.emit!({ stage: "error" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh failed. Try again.");
  });
});
