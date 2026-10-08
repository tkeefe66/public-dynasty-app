import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { YearTabs } from "@/components/YearTabs";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
beforeEach(() => push.mockClear());

it("writes an explicit All choice so the automatic season cannot override it", () => {
  // Mutation: omit year=all when clicking All.
  render(<YearTabs compact leagueId="L1" seasons={[2024, 2026]} current={2026} lens="ktc" />);
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  expect(push).toHaveBeenCalledWith("/league/L1?year=all");
});
