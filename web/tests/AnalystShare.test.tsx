import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AnalystShare } from "@/components/AnalystShare";

const shareDescriptor = Object.getOwnPropertyDescriptor(navigator, "share");
const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks();
  for (const [key, descriptor] of [["share", shareDescriptor], ["clipboard", clipboardDescriptor]] as const) {
    if (descriptor) Object.defineProperty(navigator, key, descriptor);
    else Reflect.deleteProperty(navigator, key);
  }
});

it("creates a link, opens native sharing, and disables the capability", async () => {
  // Mutation: share the private login-gated URL, or leave a revoked link displayed.
  const token = "a".repeat(43);
  const fetcher = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ token }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ token: null }) });
  vi.stubGlobal("fetch", fetcher);
  const share = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "share", { configurable: true, value: share });
  render(<AnalystShare leagueId="test" season={2026} week={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Share recap" }));
  await screen.findByRole("button", { name: "Send link" });
  fireEvent.click(screen.getByRole("button", { name: "Send link" }));
  expect(share).toHaveBeenCalledWith(expect.objectContaining({ url: `${window.location.origin}/share/analyst/${token}` }));
  fireEvent.click(screen.getByRole("button", { name: "Disable link" }));
  await waitFor(() => expect(screen.queryByLabelText("Recap share link")).not.toBeInTheDocument());
  expect(fetcher.mock.calls[1][1].method).toBe("DELETE");
});

it("keeps the link available for manual copying when clipboard access fails", async () => {
  // Mutation: silently drop the share link when the browser rejects clipboard access.
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ token: "b".repeat(43) }) }));
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error("blocked")) } });
  render(<AnalystShare leagueId="test" season={2026} week={1} />);
  fireEvent.click(screen.getByRole("button", { name: "Share recap" }));
  fireEvent.click(await screen.findByRole("button", { name: "Copy link" }));
  expect(await screen.findByText("Select and copy the link below.")).toBeInTheDocument();
  expect(screen.getByLabelText("Recap share link")).toHaveValue(`${window.location.origin}/share/analyst/${"b".repeat(43)}`);
});
