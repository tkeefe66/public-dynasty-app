import { render } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

import { Telemetry } from "@/components/Telemetry";

describe("Telemetry beacon", () => {
  beforeEach(() => {
    pathname = "/";
    (navigator as unknown as { sendBeacon: ReturnType<typeof vi.fn> }).sendBeacon =
      vi.fn(() => true);
  });

  it("fires on initial mount with the current path", () => {
    render(<Telemetry />);
    expect(navigator.sendBeacon).toHaveBeenCalledTimes(1);
    const [url] = (navigator.sendBeacon as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/events");
  });

  it("fires again when the path changes", () => {
    const { rerender } = render(<Telemetry />);
    pathname = "/league/9";
    rerender(<Telemetry />);
    expect(navigator.sendBeacon).toHaveBeenCalledTimes(2);
  });
});
