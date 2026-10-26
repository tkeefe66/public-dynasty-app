import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SeasonMembershipNotice } from "../components/SeasonMembershipNotice";

it("shows unverified season participation outside rankings without overriding current membership", () => {
  // Mutation: omit the uncertainty, or incorrectly label a current owner former.
  render(<SeasonMembershipNotice leagueId="sample" year={2024} owners={[
    { user_id: "unknown", owner_name: "Alex", membership_status: "current" },
  ]} />);
  expect(screen.getByText("2024 participation unverified")).toBeInTheDocument();
  expect(screen.getByText(/Not included in 2024 rankings/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Alex" })).toHaveAttribute("href", "/league/sample/owner/unknown");
  expect(screen.queryByText(/Former owner/)).toBeNull();
});

it("does not attach season uncertainty to the all-time view", () => {
  // Mutation: show a selected-season warning in the career list.
  const { container } = render(<SeasonMembershipNotice leagueId="sample" year="all" owners={[
    { user_id: "unknown", owner_name: "Alex" },
  ]} />);
  expect(container.textContent).toBe("");
});
