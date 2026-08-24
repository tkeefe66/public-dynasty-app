import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReceiptButton } from "../components/ReceiptButton";

afterEach(() => vi.unstubAllGlobals());

function mockClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText }, share: undefined });
  return writeText;
}

describe("ReceiptButton", () => {
  it("copies claim + absolute URL and confirms", async () => {
    const writeText = mockClipboard();
    render(<ReceiptButton claim={() => "Mike: B franchise"} path={() => "/league/L/owner/u_a"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(writeText).toHaveBeenCalledWith(
      `Mike: B franchise\n${window.location.origin}/league/L/owner/u_a`,
    );
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("shows an error state when the clipboard rejects", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("nope")) },
      share: undefined,
    });
    render(<ReceiptButton claim={() => "x"} path={() => "/p"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(await screen.findByText(/failed/i)).toBeInTheDocument();
  });

  it("evaluates the getters at tap time, not render time", async () => {
    const writeText = mockClipboard();
    let n = 1;
    render(<ReceiptButton claim={() => `claim ${n}`} path={() => "/p"} />);
    n = 2;
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining("claim 2"));
  });

  it("uses the share sheet on coarse-pointer devices, not the clipboard", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query === "(pointer: coarse)" })));
    vi.stubGlobal("navigator", { ...navigator, share, clipboard: { writeText } });
    render(<ReceiptButton claim={() => "Mike: B franchise"} path={() => "/league/L/owner/u_a"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    expect(share).toHaveBeenCalledWith({
      text: `Mike: B franchise\n${window.location.origin}/league/L/owner/u_a`,
    });
    expect(writeText).not.toHaveBeenCalled();
  });

  it("does not show a failed state when the share sheet is cancelled", async () => {
    const share = vi.fn().mockRejectedValue(new Error("cancelled"));
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query === "(pointer: coarse)" })));
    vi.stubGlobal("navigator", { ...navigator, share, clipboard: undefined });
    render(<ReceiptButton claim={() => "x"} path={() => "/p"} />);
    await userEvent.click(screen.getByRole("button", { name: /copy receipt/i }));
    await waitFor(() => expect(share).toHaveBeenCalled());
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });
});
