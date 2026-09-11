import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ProfileEditor } from "../components/ProfileEditor";

const putProfile = vi.fn();
vi.mock("@/lib/api", () => ({
  putProfile: (...args: unknown[]) => putProfile(...args),
}));

const others = [
  { user_id: "u_joey", name: "Drew" },
  { user_id: "u_amir", name: "Avery" },
];

beforeEach(() => {
  putProfile.mockReset();
});

describe("ProfileEditor", () => {
  it("prefills from an existing profile", () => {
    render(
      <ProfileEditor
        leagueId="L" userId="u_mike" displayName="Morgan"
        profile={{ win_name: "Morgan", loss_name: "Finley", rivals: ["u_joey"] }}
        others={others} onSaved={vi.fn()} onCancel={vi.fn()}
      />,
    );
    expect((screen.getByLabelText("Win name") as HTMLInputElement).value).toBe("Morgan");
    expect((screen.getByLabelText("Loss name") as HTMLInputElement).value).toBe("Finley");
    expect(screen.getByRole("button", { name: "Drew" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Avery" })).toHaveAttribute("aria-pressed", "false");
  });

  it("saves trimmed fields + selected rivals and reports the result", async () => {
    const updated = { u_mike: { win_name: "Morgan", loss_name: "Finley", rivals: ["u_joey", "u_amir"] } };
    putProfile.mockResolvedValue(updated);
    const onSaved = vi.fn();

    render(
      <ProfileEditor
        leagueId="L" userId="u_mike" displayName="Morgan"
        profile={{ win_name: "Morgan", loss_name: "Finley", rivals: ["u_joey"] }}
        others={others} onSaved={onSaved} onCancel={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Archetype"), { target: { value: "  The Planner  " } });
    fireEvent.click(screen.getByRole("button", { name: "Avery" })); // add second rival
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(putProfile).toHaveBeenCalledTimes(1));
    expect(putProfile).toHaveBeenCalledWith("L", "u_mike", {
      win_name: "Morgan",
      loss_name: "Finley",
      archetype: "The Planner",
      roast: undefined,
      rivals: ["u_joey", "u_amir"],
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated));
  });

  it("surfaces a save error and stays open", async () => {
    putProfile.mockRejectedValue(new Error("cache cold"));
    const onSaved = vi.fn();
    render(
      <ProfileEditor
        leagueId="L" userId="u_mike" displayName="Morgan"
        others={others} onSaved={onSaved} onCancel={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cache cold");
    expect(onSaved).not.toHaveBeenCalled();
  });
});
