import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationControl } from "../components/admin/GenerationControl";
import { FEATURE_LABELS } from "../lib/generation";

const request = vi.fn();
vi.mock("@/lib/api", () => ({ generationRequest: (...args: unknown[]) => request(...args) }));
const featureSettings = { mode: "manual", paused: false, model: "claude-haiku-4-5-20251001",
  review_model: "claude-sonnet-4-6", max_calls: 2, max_tokens: 1024, max_prompt_chars: 128000 };
const features = Object.fromEntries(Object.keys(FEATURE_LABELS).map(k => [k, { ...featureSettings, max_calls: k === "analyst" ? 4 : 2 }]));
const effective = { policy: { paused: false, refresh_interval_seconds: 10800, max_concurrency: 1, features },
  sources: {}, revisions: { app: 7 }, blocked_by: [] };
const config = { scope: "app", revision: 7, value: { paused: false }, effective };

beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (path = "", body) => {
    if (path === "") return { control: { hold: "", revision: 3, provider_hold: "", breakers_json: "{}" },
      effective, jobs: {}, known_cost_microusd: 1000000, unknown_cost_attempts: 2, execution_epoch_configured: false };
    if (path.startsWith("/leagues")) return { records: [{ id: "series-one", name: "Example League", lifecycle: "active", profile: "dynasty", revision: 1, hold: "", members: 2, seasons: [{ league_id: "synthetic", season: 2026, verified_at: 1 }], effective }], next_offset: null };
    if (path.startsWith("/policy")) return body ? { ...config, revision: 8, value: body.value } : config;
    if (path.startsWith("/records/candidates")) return { records: [{ key: "candidate-1", label: "Owner One", feature: "gm_rating_blurb",
      league_id: "synthetic", event: "week:02", hold: "historical_approval_required" }], next_offset: null };
    if (path.startsWith("/records")) return { records: [], next_offset: null };
    if (path === "/campaigns/preview") return { id: "preview-1", digest: "bound-digest", max_calls: 2, expires_at: 9999999999,
      items: [{ key: "candidate-1", label: "Owner One", league_id: "synthetic", feature: "gm_rating_blurb",
        event: "week:02", max_calls: 2, max_tokens_per_call: 1024, model: "claude-haiku-4-5-20251001",
        hold: "historical_approval_required", blocked_by: [] }] };
    return {};
  });
});
afterEach(() => vi.restoreAllMocks());

describe("Generation controls", () => {
  it("selects all review work across pages and confirms one batch", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => {
      if (path === "/records/jobs?limit=100&state=held&offset=0") return Promise.resolve({ records: [{ id: "held-one", feature: "analyst", state: "held", generation: 1 }], next_offset: 100 });
      if (path === "/records/jobs?limit=100&state=held&offset=100") return Promise.resolve({ records: [{ id: "held-two", feature: "analyst", state: "held", generation: 1 }], next_offset: null });
      if (path === "/jobs/batch/preview") return Promise.resolve({ id: "batch", digest: "exact-batch", action: "resume", items: [{ id: "held-one" }, { id: "held-two" }], skipped: [], remaining_calls: 8 });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Select all stopped and paused work" }));
    await screen.findByText("2 selected");
    fireEvent.click(screen.getByRole("button", { name: "Preview resume selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm resume 2 jobs" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/batch/apply", {
      preview_id: "batch", digest: "exact-batch", reason: "Resume selected stopped and paused work",
    }));
    await screen.findByText(/Selected work resumed/);
  });

  it("selects every available candidate across pages and previews above the list", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => {
      if (path === "/records/candidates?limit=100&offset=0") return Promise.resolve({ records: [
        { key: "one", label: "One", hold: "" }, { key: "queued", label: "Queued", availability: "queued" },
      ], next_offset: 100 });
      if (path === "/records/candidates?limit=100&offset=100") return Promise.resolve({ records: [{ key: "two", label: "Two", hold: "" }], next_offset: null });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Approve new content", { selector: "summary" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select all available content" }));
    await screen.findByRole("button", { name: "Preview 2 selected" });
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 selected" }));
    await screen.findByRole("button", { name: "Approve paid writing" });
    expect(request).toHaveBeenCalledWith("/campaigns/preview", { candidates: ["one", "two"], reason: "Approve selected available content across leagues" });
  });

  it("sets all four shared modes together without saving before review", async () => {
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Settings", { selector: "summary" }));
    fireEvent.click(await screen.findByRole("button", { name: "Set all four to Automatic" }));
    for (const label of Object.values(FEATURE_LABELS)) {
      expect(screen.getByLabelText(label + " mode")).toHaveValue("automatic");
    }
    expect(request.mock.calls.some(c => c[2] === "PUT")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/policy/app", {
      expected_revision: 7, reason: "Enable automatic writing for all four content types across leagues",
      value: { paused: false, features: Object.fromEntries(Object.keys(FEATURE_LABELS).map(k => [k, { mode: "automatic" }])) },
    }, "PUT"));
    await screen.findByText(/Configuration saved/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Set all four to Automatic" })).toBeEnabled());
  });

  it("previews catch-up across all leagues without selecting individual rows", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path, ...args) => path === "/campaigns/catch-up/preview"
      ? normal("/campaigns/preview", ...args) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Approve new content", { selector: "summary" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview catch-up across all leagues" }));
    await screen.findByRole("button", { name: "Approve paid writing" });
    expect(request).toHaveBeenCalledWith("/campaigns/catch-up/preview", {
      series_id: "", reason: "One-time catch-up of missing current content across leagues",
    });
    expect(request.mock.calls.some(c => c[0] === "/campaigns/apply")).toBe(false);
  });

  it("offers recovery of a settled unknown outcome using the original job", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.startsWith("/records/jobs")
      ? Promise.resolve({ records: [{ id: "original-job", state: "needs_attention", reason: "provider_outcome_unknown",
          generation: 3, feature: "gm_rating_blurb", league_id: "synthetic" }], next_offset: null })
      : normal(path, ...args));
    render(<GenerationControl />);
    // Mutation: remove the original job's revision/state from the recovery request.
    await screen.findByRole("heading", { name: "Needs your review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Review problem" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Resume after receipt review" }));
    fireEvent.change(screen.getByLabelText("Reason for this action"), { target: { value: "Receipt settled" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm resume" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/original-job", {
      action: "resume", expected_generation: 3, expected_state: "needs_attention", reason: "Receipt settled",
    }));
  });

  it("saves only explicit overrides with the observed revision and reason", async () => {
    render(<GenerationControl />);
    // Mutation: save the resolved policy instead of only explicit overrides.
    fireEvent.click(await screen.findByText("Settings", { selector: "summary" }));
    await screen.findByLabelText("Apply settings to");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Enable new stories" } });
    fireEvent.change(screen.getByLabelText("Trade stories mode"), { target: { value: "automatic" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/policy/app", {
      expected_revision: 7, reason: "Enable new stories",
      value: { paused: false, features: { trade_story: { mode: "automatic" } } },
    }, "PUT"));
    expect(screen.getByText(/2 requests still have unknown cost/)).toBeInTheDocument();
  });

  it("keeps a stale-save conflict visible instead of claiming success", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path, body, method) => body && path === "/policy/app"
      ? Promise.reject(new Error("Settings changed. Reload before saving.")) : normal(path, body, method));
    render(<GenerationControl />);
    // Mutation: swallow a revision conflict and display a success notice.
    fireEvent.click(await screen.findByText("Settings", { selector: "summary" }));
    await screen.findByLabelText("Apply settings to");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Pause" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Settings changed");
    expect(screen.queryByText(/Configuration saved/)).not.toBeInTheDocument();
  });

  it("approves only the exact preview digest and never buys from selection alone", async () => {
    render(<GenerationControl />);
    // Mutation: selecting a candidate buys work without the bound preview approval.
    fireEvent.click(await screen.findByText("Approve new content", { selector: "summary" }));
    fireEvent.click(await screen.findByLabelText("Select Owner One"));
    expect(request.mock.calls.some(c => c[0] === "/campaigns/apply")).toBe(false);
    fireEvent.change(screen.getByLabelText("Reason for this approval"), { target: { value: "Initial profile" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview 1 selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve paid writing" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/campaigns/apply", {
      preview_id: "preview-1", digest: "bound-digest", reason: "Initial profile",
    }));
  });

  it("surfaces an older stopped job separately from recent successful activity", async () => {
    // Mutation: derive review items from only the first recent-activity page.
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.includes("state=needs_attention")
      ? Promise.resolve({ records: [{ id: "older-failure", label: "Owner One", league_id: "synthetic", feature: "gm_rating_blurb", state: "needs_attention", reason: "execution_failed", calls: 1, max_calls: 1 }], next_offset: null })
      : normal(path, ...args));
    render(<GenerationControl />);
    const review = await screen.findByRole("region", { name: "Needs your review" });
    expect(await within(review).findByText("Example League")).toBeVisible();
    expect(within(review).getByText(/Writing stopped before completion/)).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Review problem" }));
    expect(await within(review).findByText(/The exact cause was not recorded/)).toBeVisible();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    expect(within(review).getByRole("button", { name: "Preview resume selected" })).toBeDisabled();
  });

  it("treats the deployment emergency pause as paused even when policy allows writing", async () => {
    // Mutation: ignore the deployment pause in the visible AI status.
    const normal = request.getMockImplementation()!;
    request.mockImplementation(async (path = "", ...args) => path === ""
      ? { ...await normal(path, ...args), emergency_paused: true }
      : normal(path, ...args));
    render(<GenerationControl />);
    expect(await screen.findByRole("heading", { name: "AI is paused" })).toBeVisible();
    expect(screen.getByText(/deployment safety switch/)).toBeVisible();
  });

  it("reports automatic league overrides instead of claiming all work needs approval", async () => {
    // Mutation: use app defaults alone for the all-league AI status.
    const normal = request.getMockImplementation()!;
    request.mockImplementation(async (path = "", ...args) => {
      const result = await normal(path, ...args);
      if (path.startsWith("/leagues")) result.records[0].effective = { ...effective, policy: { ...effective.policy, features: { ...features, trade_story: { ...featureSettings, mode: "automatic" } } } };
      return result;
    });
    render(<GenerationControl />);
    expect(await screen.findByRole("heading", { name: "Automatic writing is enabled" })).toBeVisible();
  });

  it("uses actual league permission when only the default app policy is paused", async () => {
    // Mutation: treat an unresolved app default pause as a global hold over allowed leagues.
    const normal = request.getMockImplementation()!;
    request.mockImplementation(async (path = "", ...args) => path === "" ? {
      ...await normal(path, ...args), effective: { ...effective, policy: { ...effective.policy, paused: true }, blocked_by: ["activation_required"] },
    } : normal(path, ...args));
    render(<GenerationControl />);
    expect(await screen.findByRole("heading", { name: "Waiting for your approval" })).toBeVisible();
    expect(screen.queryByText(/New paid writing is blocked/)).not.toBeInTheDocument();
  });

  it("uses the API delivered flag and does not offer unsupported league filters", async () => {
    // Mutation: read a nonexistent delivered_at field or imply outbox filtering works.
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.startsWith("/records/outbox") ? Promise.resolve({ records: [{ id: "delivery-one", delivered: true, error: "", kind: "generation_publish" }], next_offset: null }) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Advanced", { selector: "summary" }));
    await screen.findByLabelText("Record type");
    await waitFor(() => expect(screen.getByLabelText("Record type")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Record type"), { target: { value: "outbox" } });
    expect(await screen.findByText("Delivered")).toBeVisible();
    expect(screen.queryByLabelText("Records for league")).not.toBeInTheDocument();
  });

  it("does not label a saved override as the inherited value", async () => {
    // Mutation: use current effective mode as the value that removing an override will select.
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.startsWith("/policy") ? Promise.resolve({ ...config, value: { features: { trade_story: { mode: "manual" } } } }) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Settings", { selector: "summary" }));
    const mode = await screen.findByLabelText("Trade stories mode");
    expect(within(mode).getByRole("option", { name: "Use shared default" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Advanced trade stories settings", { selector: "summary" }));
    fireEvent.click(screen.getByText("Advanced shared settings", { selector: "summary" }));
    expect(screen.queryByRole("option", { name: /^Use default \(/ })).not.toBeInTheDocument();
    fireEvent.change(mode, { target: { value: "" } });
    expect(screen.getByText(/Removing this override uses the shared defaults/)).toBeVisible();
  });

  it("shows a feature safety stop instead of promising automatic writing", async () => {
    // Mutation: include automatic features with open circuit breakers in available modes.
    const normal = request.getMockImplementation()!;
    request.mockImplementation(async (path = "", ...args) => {
      const result = await normal(path, ...args);
      if (path === "") result.control.breakers_json = JSON.stringify({ trade_story: { open: true } });
      if (path.startsWith("/leagues")) result.records[0].effective = { ...effective, policy: { ...effective.policy, features: { ...features, trade_story: { ...featureSettings, mode: "automatic" } } } };
      return result;
    });
    render(<GenerationControl />);
    expect(await screen.findByRole("heading", { name: "Waiting for your approval" })).toBeVisible();
    expect(screen.getByText(/Trade stories is stopped after repeated failures/)).toBeVisible();
  });

  it("explains restored work and does not offer a resume the server forbids", async () => {
    // Mutation: treat restored generation as an ordinary resumable held job.
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.includes("state=held") ? Promise.resolve({ records: [{ id: "restored-job", kind: "generation", state: "held", reason: "restore_reapproval_required", label: "Owner One", feature: "gm_rating_blurb", generation: 2 }], next_offset: null }) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Review problem" }));
    expect(await screen.findByText(/This work was restored from a backup/)).toBeVisible();
    await screen.findByRole("button", { name: "Cancel this work" });
    expect(screen.queryByRole("button", { name: "Resume remaining work" })).not.toBeInTheDocument();
  });
});
