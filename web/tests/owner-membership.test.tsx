import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OwnerStatus } from "../components/OwnerStatus";
import { membershipRows, ownerNameWithStatus } from "../lib/owner-membership";
import { OwnerRef } from "../lib/types";

const former: OwnerRef = { user_id: "old", owner_name: "Past Owner", membership_status: "former", last_active_season: 2023 };

describe("shared owner membership", () => {
  it("retains unverified owners without treating them as former", () => {
    // Mutation: filter anything other than explicitly current out of the list.
    const unknown = { owner: { user_id: "unknown", owner_name: "Unknown", membership_status: "unverified" as const } };
    expect(membershipRows([{ owner: former }, unknown], "current", false)).toEqual([unknown]);
    render(<OwnerStatus owner={unknown.owner} />);
    expect(screen.getByText("Membership unverified")).toHaveAttribute("title", expect.stringContaining("Refresh league data"));
  });

  it("preserves former owners in selected historical seasons", () => {
    // Mutation: current population filter also strips historical participants.
    expect(membershipRows([{ owner: former }], "current", true)).toEqual([{ owner: former }]);
  });

  it("uses identical former status in labels and plain-text selectors", () => {
    // Mutation: selectors flatten membership back to just a name.
    render(<OwnerStatus owner={former} />);
    const label = screen.getByText("Former owner · last played 2023");
    expect(ownerNameWithStatus(former)).toBe(`Past Owner · ${label.textContent}`);
  });

  it("does not invent status for old API response shapes", () => {
    // Mutation: missing new field is silently presented as confirmed current.
    const legacy = { user_id: "old-api", owner_name: "Legacy" };
    const { container } = render(<OwnerStatus owner={legacy} />);
    expect(container.textContent).toBe("");
    expect(ownerNameWithStatus(legacy)).toBe("Legacy");
  });
});
