import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TopBar } from "@/components/TopBar";
import HomePage from "@/app/page";
import AdminPage from "@/app/admin/page";
import { ApiError, adminOverview, getMe } from "@/lib/api";

vi.mock("@/auth", () => ({ signOut: vi.fn() }));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => null }));
vi.mock("@/components/WeekNote", () => ({ WeekNote: () => null }));
vi.mock("@/components/admin/GenerationControl", () => ({
  GenerationControl: () => <h2>Generation controls</h2>,
}));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  getMe: vi.fn(),
  myLeagues: vi.fn().mockResolvedValue([]),
  adminOverview: vi.fn(),
  adminLeagues: vi.fn().mockResolvedValue([]),
  adminUsers: vi.fn().mockResolvedValue([]),
  adminActiveUsers: vi.fn().mockResolvedValue({ daily: [], d1: 0, d7: 0, d30: 0 }),
  adminBackups: vi.fn().mockResolvedValue(null),
}));

const profile = { email: "owner@example.test", name: null, avatar_url: null,
  sleeper_user_id: null, sleeper_username: null, is_admin: true };

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(getMe).mockResolvedValue(profile);
  vi.mocked(adminOverview).mockRejectedValue(new ApiError(500, "Reporting unavailable"));
});

describe("Owner access to Admin", () => {
  it("waits for a confirmed owner role before exposing the shortcut", async () => {
    // Mutation: starting navigation in the admin state while identity is still loading.
    vi.mocked(getMe).mockReturnValue(new Promise(() => {}));
    render(<TopBar />);
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  });

  it.each([undefined, "example-league"])("puts Admin directly in the header with league context %s", async (leagueId) => {
    // Mutation: hiding Admin in a dropdown or the desktop-only league navigation.
    await act(async () => { render(<TopBar leagueId={leagueId} />); });
    const link = screen.getByRole("link", { name: "Admin" });
    expect(link).toHaveAttribute("href", "/admin");
    expect(link.closest("header")).not.toBeNull();
    expect(link.closest('[role="menu"]')).toBeNull();
    expect(link.closest(".hidden")).toBeNull();
    expect(adminOverview).not.toHaveBeenCalled();
  });

  it("keeps the home page Admin shortcut when reporting fails", async () => {
    // Mutation: using overview availability as an authorization check.
    await act(async () => { render(await HomePage()); });
    const shortcut = screen.getAllByRole("link", { name: "Admin" })
      .find(link => !link.closest("header"));
    expect(shortcut).toHaveAttribute("href", "/admin");
    expect(adminOverview).not.toHaveBeenCalled();
  });

  it.each([false, "unavailable"])("keeps owner navigation hidden for profile %s", async (role) => {
    // Mutation: showing the owner link before role confirmation or on an auth error.
    if (role === false) vi.mocked(getMe).mockResolvedValue({ ...profile, is_admin: false });
    else vi.mocked(getMe).mockRejectedValue(new Error("Profile unavailable"));
    await act(async () => { render(<TopBar />); });
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
  });

  it("keeps generation controls accessible to an owner during a reporting failure", async () => {
    // Mutation: one failed report prevents every administrative control from rendering.
    await act(async () => { render(await AdminPage()); });
    expect(screen.getByRole("heading", { name: "Generation controls" })).toBeInTheDocument();
    expect(screen.getByText(/Admin reports didn't load/)).toBeInTheDocument();
  });

  it("does not render generation controls for a non-owner during a reporting failure", async () => {
    // Mutation: the reporting fallback exposes the admin workspace without a confirmed owner role.
    vi.mocked(getMe).mockResolvedValue({ ...profile, is_admin: false });
    await act(async () => { render(await AdminPage()); });
    expect(screen.queryByRole("heading", { name: "Generation controls" })).toBeNull();
    expect(screen.getByText("This area is for app owners.")).toBeInTheDocument();
    expect(adminOverview).not.toHaveBeenCalled();
  });

  it.each([401, 500])("requires owner confirmation even when profile lookup fails with %s", async (status) => {
    // Mutation: treating unavailable identity as permission to render administrative controls.
    vi.mocked(getMe).mockRejectedValue(new ApiError(status, "Profile unavailable"));
    await act(async () => { render(await AdminPage()); });
    expect(screen.queryByRole("heading", { name: "Generation controls" })).toBeNull();
    expect(adminOverview).not.toHaveBeenCalled();
  });
});
