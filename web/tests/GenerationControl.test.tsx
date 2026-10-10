import { cleanup, render, screen, fireEvent, waitFor, within } from "@testing-library/react";
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
const recapBalance = { known_microusd: 0, reserved_microusd: 0, carry_forward_microusd: 0,
  uncertain_microusd: 0, unknown_count: 0, unbounded_unknown_count: 0, remaining_microusd: 15_000_000, overcommitted: false };
const recapBudget = { series_id: "series-one", revision: 1, episode_id: null, month_key: "2026-10",
  caps: { video_episode_microusd: 3_000_000, video_month_microusd: 15_000_000, combined_episode_microusd: 5_000_000, combined_month_microusd: 25_000_000 },
  balances: { video_episode_microusd: null, video_month_microusd: recapBalance, combined_episode_microusd: null, combined_month_microusd: recapBalance },
  app_limit: { month_microusd: null, balance: recapBalance }, enforcement_state: { active: true, reason: "" }, media_automation_enabled: false };

beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (path = "", body) => {
    if (path === "") return { control: { hold: "", revision: 3, provider_hold: "", breakers_json: "{}" },
      effective, jobs: {}, known_cost_microusd: 1000000, unknown_cost_attempts: 2, execution_epoch_configured: false };
    if (path.startsWith("/leagues")) return { records: [{ id: "series-one", name: "Example League", lifecycle: "active", profile: "dynasty", revision: 1, hold: "", members: 2, seasons: [{ league_id: "synthetic", season: 2026, verified_at: 1 }], effective }], next_offset: null };
    if (path.startsWith("/policy")) return body ? { ...config, revision: 8, value: body.value } : config;
    if (path.startsWith("/recap-budgets")) return recapBudget;
    if (path.startsWith("/records/candidates")) return { records: [{ key: "candidate-1", label: "Owner One", feature: "gm_rating_blurb",
      league_id: "synthetic", event: "week:02", hold: "historical_approval_required", availability: "available",
      reviewable: true, review_reason: "historical_approval_required" }], next_offset: null };
    if (path.startsWith("/records")) return { records: [], next_offset: null };
    if (path === "/campaigns/preview") return { id: "preview-1", digest: "bound-digest", max_calls: 2, expires_at: 9999999999,
      items: [{ key: "candidate-1", label: "Owner One", league_id: "synthetic", feature: "gm_rating_blurb",
        event: "week:02", max_calls: 2, max_tokens_per_call: 1024, model: "claude-haiku-4-5-20251001",
        hold: "historical_approval_required", blocked_by: [] }] };
    return {};
  });
});
// Unmount before restoring request mocks; completed actions can schedule effects.
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("Generation controls", () => {
  it("names affected provider account and submits only scoped recovery", async () => {
    // Mutation: use global clear_provider or omit alias/revision in provider reset.
    const normal = request.getMockImplementation()!;
    request.mockImplementation(async (path = "", ...args) => path === "" ? {
      ...await normal(path, ...args), providers: [{ provider: "elevenlabs", account_key: "synthetic-voice",
        hold: "provider_auth_failed", cooldown_until: 0, max_concurrency: 1, revision: 7 }],
    } : normal(path, ...args));
    render(<GenerationControl />);
    await screen.findByRole("heading", { name: "Waiting for your approval" });
    fireEvent.click(screen.getByRole("button", { name: "Recovery" }));
    fireEvent.click(await screen.findByText("Activation and recovery", { selector: "summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Review elevenlabs / synthetic-voice recovery" }));
    const form = screen.getByRole("button", { name: "Reset provider account" }).closest("form")!;
    fireEvent.change(within(form).getByRole("textbox"), { target: { value: "Synthetic account credentials corrected" } });
    fireEvent.click(within(form).getByRole("button", { name: "Reset provider account" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/provider/reset", {
      provider: "elevenlabs", account_key: "synthetic-voice", expected_revision: 7,
      reason: "Synthetic account credentials corrected",
    }));
  });
  it("opens a held job's selected-league recap limits without approving requests", async () => {
    // Mutation: navigate to app defaults rather than the held job's league budget.
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.includes("state=held") ? Promise.resolve({ records: [{ id: "budget-job", feature: "analyst", state: "held", reason: "recap_budget_video_month", league_id: "synthetic", generation: 1 }], next_offset: null }) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Review recap limits" }));
    expect(await screen.findByLabelText("Video per episode ($)")).toHaveValue("3.00");
    expect(screen.getByLabelText("Recap limits for league")).toHaveValue("series-one");
    expect(request).toHaveBeenCalledWith("/recap-budgets/series-one");
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    expect(screen.getByRole("region", { name: "Weekly Analyst recap limits" })).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Recap limits for league"), { target: { value: "" } });
    expect(await screen.findByText(/Select an individual league above/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Content" }));
    fireEvent.click(screen.getByRole("button", { name: "Review recap limits" }));
    expect(await screen.findByLabelText("Video per episode ($)")).toHaveValue("3.00");
    expect(screen.getByLabelText("Recap limits for league")).toHaveValue("series-one");
  });
  it("requires an individual league and keeps budget forms outside writing rules", async () => {
    // Mutation: mix budget settings back into the policy form or imply all-league budget scope.
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Spend & limits" }));
    expect(await screen.findByText(/Select an individual league above/)).toBeInTheDocument();
    expect(request.mock.calls.some(c => c[0]?.startsWith("/recap-budgets"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Recap limits for league"), { target: { value: "series-one" } });
    const input = await screen.findByLabelText("Video per episode ($)");
    expect(input.closest("form")?.parentElement?.closest("form")).toBeNull();
    expect(screen.queryByLabelText("Trade stories mode")).not.toBeInTheDocument();
  });
  it("limits the bulk Automatic action to its four named writing features", async () => {
    // Mutation: derive bulk opt-in from every registered feature, including a future video feature.
    const labels = FEATURE_LABELS as Record<string, string>;
    const previousVideoLabel = labels.recap_video;
    labels.recap_video = "Recap video";
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.startsWith("/policy") && !args[0] ? Promise.resolve({ ...config,
      value: { features: { recap_video: { mode: "manual" } } },
      effective: { ...effective, policy: { ...effective.policy, features: { ...features, recap_video: featureSettings } } },
    }) : normal(path, ...args));
    try {
      render(<GenerationControl />);
      fireEvent.click(await screen.findByRole("button", { name: "Writing rules" }));
      fireEvent.click(await screen.findByRole("button", { name: "Set all four to Automatic" }));
      expect(screen.getByText(/Set trade stories, GM profiles, franchise outlooks, and Weekly Analyst together/)).toBeInTheDocument();
      expect(screen.getByLabelText("Recap video mode")).toHaveValue("manual");
      fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
      await waitFor(() => expect(request.mock.calls.find(c => c[0] === "/policy/app" && c[1])?.[1].value.features).toMatchObject({
        recap_video: { mode: "manual" }, analyst: { mode: "automatic" }, trade_story: { mode: "automatic" }, gm_rating_blurb: { mode: "automatic" }, franchise_blurb: { mode: "automatic" },
      }));
    } finally { labels.recap_video = previousVideoLabel; }
  });
  it("keeps free-refresh details read-only until the direct retry is clicked", async () => {
    const normal = request.getMockImplementation()!;
    const job = { id: "data-job", kind: "refresh", state: "needs_attention",
      reason: "execution_failed", generation: 2, league_id: "synthetic", calls: 0, max_calls: 0 };
    request.mockImplementation((path = "", ...args) => {
      if (path.startsWith("/records/jobs")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/data-job") return Promise.resolve({ job, attempts: [] });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    await screen.findByRole("heading", { name: "Needs your review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Review problem" })[0]);
    expect(await screen.findByText(/original member's league access and connection/)).toBeInTheDocument();
    expect(screen.getByText(/This action does not approve paid writing/)).toBeInTheDocument();
    expect(request.mock.calls.some(([path, body]) => path === "/jobs/data-job" && body)).toBe(false);
    expect(screen.queryByLabelText("Reason for this action")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry data refresh" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Retry data refresh" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/data-job", {
      action: "resume", expected_generation: 2, expected_state: "needs_attention", reason: "Retry failed data refresh from administration",
    }));
    expect(request.mock.calls.filter(([path, body]) => path === "/jobs/data-job" && !body)).toHaveLength(2);
    expect(request.mock.calls.some(([path]) => path?.startsWith("/campaigns"))).toBe(false);
  });

  it.each([
    { activity: "a settled receipt", calls: 0, max_calls: 0, attempts: [{ state: "received" }] },
    { activity: "recorded AI calls", calls: 1, max_calls: 0, attempts: [] },
    { activity: "an AI request allowance", calls: 0, max_calls: 2, attempts: [] },
  ])("refuses the free retry when its fresh record has $activity", async ({ calls, max_calls, attempts }) => {
    const normal = request.getMockImplementation()!;
    const job = { id: "data-job", kind: "refresh", state: "needs_attention", reason: "execution_failed",
      generation: 2, league_id: "synthetic", calls: 0, max_calls: 0 };
    request.mockImplementation((path = "", ...args) => {
      if (path.includes("state=needs_attention")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/data-job") return Promise.resolve({ job: { ...job, calls, max_calls }, attempts });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry data refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This data refresh has AI request activity");
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    expect(screen.queryByText("Data refresh queued.")).not.toBeInTheDocument();
  });

  it("selects all review work across pages and confirms one batch", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => {
      if (path === "/records/jobs?limit=25&state=held") return Promise.resolve({ records: [{ id: "held-one", feature: "analyst", state: "held", generation: 1 }], next_offset: 25 });
      if (path === "/records/jobs?limit=100&state=held&offset=0") return Promise.resolve({ records: [{ id: "held-one", feature: "analyst", state: "held", generation: 1 }], next_offset: 100 });
      if (path === "/records/jobs?limit=100&state=held&offset=100") return Promise.resolve({ records: [{ id: "held-two", feature: "analyst", state: "held", generation: 1 }], next_offset: null });
      if (path === "/jobs/batch/preview") return Promise.resolve({ id: "batch", digest: "exact-batch", action: "resume", items: [{ id: "held-one" }, { id: "held-two" }], skipped: [], remaining_calls: 8 });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByText("Review several jobs", { selector: "summary" }));
    fireEvent.click(await screen.findByRole("button", { name: "Select jobs across pages" }));
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
      if (path === "/records/candidates?limit=100&offset=0&view=review") return Promise.resolve({ records: [
        { key: "one", label: "One", hold: "", availability: "available", reviewable: true },
        { key: "queued", label: "Queued", availability: "queued", reviewable: false },
        { key: "automatic", label: "Automatic", availability: "available", reviewable: false },
      ], next_offset: 100 });
      if (path === "/records/candidates?limit=100&offset=100&view=review") return Promise.resolve({ records: [
        { key: "two", label: "Two", hold: "", availability: "available", reviewable: true },
        { key: "completed", label: "Completed", availability: "completed", reviewable: false },
      ], next_offset: null });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve writing" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Select all available content" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Select all available content" }));
    await screen.findByRole("button", { name: "Preview 2 selected" });
    fireEvent.click(screen.getByRole("button", { name: "Preview 2 selected" }));
    await screen.findByRole("button", { name: "Approve paid writing" });
    expect(request).toHaveBeenCalledWith("/campaigns/preview", { candidates: ["one", "two"], reason: "Approve selected available content across leagues" });
  });

  it("sets all four shared modes together without saving before review", async () => {
    // Mutation: bulk action silently opts the newly registered video feature in.
    const writingFeatures = ["trade_story", "gm_rating_blurb", "franchise_blurb", "analyst"] as const;
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Writing rules" }));
    fireEvent.click(await screen.findByRole("button", { name: "Set all four to Automatic" }));
    for (const feature of writingFeatures) {
      expect(screen.getByLabelText(FEATURE_LABELS[feature] + " mode")).toHaveValue("automatic");
    }
    expect(screen.getByLabelText(FEATURE_LABELS.recap_video + " mode")).toHaveValue("");
    expect(request.mock.calls.some(c => c[2] === "PUT")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/policy/app", {
      expected_revision: 7, reason: "Enable automatic writing for all four content types across leagues",
      value: { paused: false, features: Object.fromEntries(writingFeatures.map(k => [k, { mode: "automatic" }])) },
    }, "PUT"));
    await screen.findByText(/Configuration saved/);
    await waitFor(() => expect(screen.getByRole("button", { name: "Set all four to Automatic" })).toBeEnabled());
  });

  it("previews catch-up across all leagues without selecting individual rows", async () => {
    const normal = request.getMockImplementation()!;
    const loadedRecords = await normal("/records/candidates");
    let releaseRecords!: (value: unknown) => void;
    const records = new Promise(resolve => { releaseRecords = resolve; });
    request.mockImplementation((path = "", ...args) => path.startsWith("/records/candidates") ? records
      : path === "/campaigns/catch-up/preview" ? normal("/campaigns/preview", ...args) : normal(path, ...args));
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve writing" }));
    fireEvent.click(screen.getByText("Historical catch-up across content types", { selector: "summary" }));
    const preview = await screen.findByRole("button", { name: "Preview catch-up across all leagues" });
    expect(preview).toBeDisabled();
    fireEvent.click(preview);
    expect(request.mock.calls.some(c => c[0] === "/campaigns/catch-up/preview")).toBe(false);
    releaseRecords(loadedRecords);
    await waitFor(() => expect(preview).toBeEnabled());
    fireEvent.click(preview);
    await screen.findByRole("button", { name: "Approve paid writing" });
    expect(request).toHaveBeenCalledWith("/campaigns/catch-up/preview", {
      series_id: "", reason: "One-time catch-up of missing current content across leagues",
    });
    expect(request.mock.calls.some(c => c[0] === "/campaigns/apply")).toBe(false);
  });

  it("offers recovery of a settled unknown outcome using the original job", async () => {
    const normal = request.getMockImplementation()!;
    const job = { id: "original-job", kind: "generation", state: "needs_attention", reason: "provider_outcome_unknown",
      generation: 3, feature: "gm_rating_blurb", league_id: "synthetic" };
    request.mockImplementation((path = "", ...args) => {
      if (path.startsWith("/records/jobs")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/original-job") return Promise.resolve({ job: { ...job, generation: 7 }, attempts: [] });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    // Mutation: remove the original job's revision/state from the recovery request.
    await screen.findByRole("heading", { name: "Needs your review" });
    fireEvent.click(screen.getAllByRole("button", { name: "Review problem" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Resume after receipt review" }));
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Reason for this action"), { target: { value: "Receipt settled" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm resume" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/original-job", {
      action: "resume", expected_generation: 7, expected_state: "needs_attention", reason: "Receipt settled",
    }));
  });

  it.each(["refresh", "analyst_refresh"])("retries a failed %s directly using a fresh snapshot without approving paid writing", async kind => {
    const normal = request.getMockImplementation()!;
    const job = { id: "free-job", kind, state: "needs_attention", reason: "execution_failed",
      generation: 3, league_id: "470.l.123456", league_name: "Example Yahoo League", calls: 0, max_calls: 0 };
    request.mockImplementation((path = "", ...args) => {
      if (path.includes("state=needs_attention")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/free-job") return Promise.resolve({ job: { ...job, generation: 4 }, attempts: [] });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    const review = await screen.findByRole("region", { name: "Needs your review" });
    expect(await within(review).findByText("Data refresh stopped before completion")).toBeVisible();
    expect(within(review).getByText("Example Yahoo League")).toBeVisible();
    expect(within(review).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(within(review).queryByRole("button", { name: "Preview resume selected" })).not.toBeInTheDocument();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    fireEvent.click(within(review).getByRole("button", { name: "Retry data refresh" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/free-job", {
      action: "resume", expected_generation: 4, expected_state: "needs_attention",
      reason: "Retry failed data refresh from administration",
    }));
    expect(request.mock.calls.filter(c => c[0] === "/jobs/free-job" && !c[1])).toHaveLength(1);
    expect(request.mock.calls.some(c => c[0]?.startsWith("/campaigns"))).toBe(false);
    expect(screen.queryByLabelText("Reason for this action")).not.toBeInTheDocument();
    await screen.findByText("Data refresh queued.");
  });

  it("keeps manual and historical choices outside failures and hides content that cannot be reviewed", async () => {
    const normal = request.getMockImplementation()!;
    const hidden = ["completed", "queued", "running", "held", "needs_attention", "blocked"].map(state => ({
      key: state, label: `Hidden ${state}`, availability: state, reviewable: false,
    }));
    request.mockImplementation(async (path = "", ...args) => {
      if (path.startsWith("/records/candidates")) return { records: [
        { key: "manual", label: "Requested profile", availability: "available", reviewable: true, review_reason: "manual_approval_required" },
        { key: "history", label: "Older report", availability: "available", reviewable: true, review_reason: "historical_approval_required" },
        ...hidden, { key: "automatic", label: "Automatic event", availability: "available", reviewable: false },
        { key: "unknown", label: "Unclassified item" },
        { key: "blocked-malformed", label: "Blocked item", availability: "available", reviewable: true, blocked_by: ["feature_paused"] },
      ], next_offset: null };
      const result = await normal(path, ...args);
      if (path.startsWith("/leagues")) result.records[0].effective = { ...effective, policy: { ...effective.policy,
        features: { ...features, trade_story: { ...featureSettings, mode: "automatic" } } } };
      return result;
    });
    render(<GenerationControl />);
    await screen.findByRole("heading", { name: "Automatic writing is enabled" });
    const problems = screen.getByRole("region", { name: "Needs your review" });
    expect(within(problems).queryByText("Manual content and catch-up")).not.toBeInTheDocument();
    expect(request.mock.calls.some(c => c[0]?.startsWith("/records/candidates"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Approve writing" }));
    const optional = await screen.findByRole("region", { name: "Manual content and catch-up" });
    expect(screen.queryByRole("region", { name: "Needs your review" })).not.toBeInTheDocument();
    await within(optional).findByLabelText("Select Requested profile");
    expect(within(optional).getAllByRole("checkbox")).toHaveLength(2);
    expect(within(optional).getByText(/Awaiting manual approval/)).toBeVisible();
    expect(within(optional).getByText(/Optional historical content/)).toBeVisible();
    for (const label of [...hidden.map(row => row.label), "Automatic event", "Unclassified item", "Blocked item"]) {
      expect(within(optional).queryByText(label)).not.toBeInTheDocument();
    }
    expect(request).toHaveBeenCalledWith("/records/candidates?limit=25&offset=0&view=review");
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
  });

  it("keeps failed free refreshes out of batch selection while preserving paid batch review", async () => {
    const normal = request.getMockImplementation()!;
    const free = { id: "free-job", kind: "refresh", state: "needs_attention", reason: "execution_failed", generation: 3 };
    const paused = ["one", "two"].map(id => ({ id: `paid-${id}`, kind: "generation", state: "held", reason: "manual_only", generation: 2 }));
    request.mockImplementation((path = "", ...args) => {
      if (path.includes("state=needs_attention")) return Promise.resolve({ records: [free], next_offset: null });
      if (path.includes("state=held")) return Promise.resolve({ records: paused, next_offset: null });
      if (path === "/jobs/batch/preview") return Promise.resolve({ id: "batch", digest: "reviewed", action: "resume", items: paused, skipped: [], remaining_calls: 4 });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    const review = await screen.findByRole("region", { name: "Needs your review" });
    fireEvent.click(within(review).getByText("Review several jobs", { selector: "summary" }));
    await waitFor(() => expect(within(review).getAllByRole("checkbox")).toHaveLength(2));
    expect(within(review).queryByLabelText(/Select League data refresh/)).not.toBeInTheDocument();
    expect(within(review).getByRole("button", { name: "Retry data refresh" })).toBeVisible();
    fireEvent.click(within(review).getByRole("button", { name: "Select jobs across pages" }));
    await within(review).findByText("2 selected");
    fireEvent.click(within(review).getByRole("button", { name: "Preview resume selected" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/jobs/batch/preview", {
      job_ids: ["paid-one", "paid-two"], action: "resume", reason: "Resume selected stopped and paused work",
    }));
  });

  it.each(["queued", "unknown", "dispatching"])("does not retry a free job when its fresh status is %s", async state => {
    const normal = request.getMockImplementation()!;
    const job = { id: "free-job", kind: "refresh", state: "needs_attention", reason: "execution_failed", generation: 3 };
    request.mockImplementation((path = "", ...args) => {
      if (path.includes("state=needs_attention")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/free-job") return Promise.resolve({
        job: state === "queued" ? { ...job, state, generation: 4 } : job,
        attempts: state === "queued" ? [] : [{ state }],
      });
      return normal(path, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry data refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(state === "queued" ? "no longer needs this retry" : "provider request still needs review");
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    expect(screen.queryByText("Data refresh queued.")).not.toBeInTheDocument();
  });

  it("refetches a retry conflict without repeating the resume request", async () => {
    const normal = request.getMockImplementation()!;
    const job = { id: "free-job", kind: "refresh", state: "needs_attention", reason: "execution_failed", generation: 3 };
    let reads = 0;
    request.mockImplementation((path = "", body, ...args) => {
      if (path.includes("state=needs_attention")) return Promise.resolve({ records: [job], next_offset: null });
      if (path === "/jobs/free-job") {
        if (body) return Promise.reject(Object.assign(new Error("The refresh changed before retry."), { status: 409 }));
        reads++;
        return Promise.resolve({ job: reads > 1 ? { ...job, state: "running", generation: 4, reason: "" } : job, attempts: [] });
      }
      return normal(path, body, ...args);
    });
    render(<GenerationControl />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry data refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The refresh changed before retry.");
    expect(screen.getByText("In progress")).toBeVisible();
    expect(reads).toBe(2);
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Retry data refresh" })).not.toBeInTheDocument();
    expect(screen.queryByText("Data refresh queued.")).not.toBeInTheDocument();
  });

  it("identifies cold imports by safe league ID before their names are registered", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path = "", ...args) => path.includes("state=needs_attention")
      ? Promise.resolve({ records: ["470.l.123456", "470.l.654321"].map(league_id => ({
        id: `${league_id}-job`, league_id, kind: "refresh", state: "needs_attention", reason: "execution_failed", generation: 1,
      })), next_offset: null }) : normal(path, ...args));
    render(<GenerationControl />);
    const review = await screen.findByRole("region", { name: "Needs your review" });
    expect(await within(review).findByText("League 470.l.123456")).toBeVisible();
    expect(within(review).getByText("League 470.l.654321")).toBeVisible();
    expect(within(review).queryByText("League name unavailable")).not.toBeInTheDocument();
    expect(within(review).getAllByRole("button", { name: "Retry data refresh" })).toHaveLength(2);
    expect(within(review).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("saves only explicit overrides with the observed revision and reason", async () => {
    render(<GenerationControl />);
    // Mutation: save the resolved policy instead of only explicit overrides.
    fireEvent.click(await screen.findByRole("button", { name: "Writing rules" }));
    await screen.findByLabelText("Reason for this change");
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
    fireEvent.click(await screen.findByRole("button", { name: "Writing rules" }));
    await screen.findByLabelText("Reason for this change");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Pause" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Settings changed");
    expect(screen.queryByText(/Configuration saved/)).not.toBeInTheDocument();
  });

  it("approves only the exact preview digest and never buys from selection alone", async () => {
    render(<GenerationControl />);
    // Mutation: selecting a candidate buys work without the bound preview approval.
    fireEvent.click(await screen.findByRole("button", { name: "Approve writing" }));
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
    expect(within(review).queryByRole("button", { name: /Resume (data refresh|remaining work|after receipt review)/ })).not.toBeInTheDocument();
    expect(within(review).queryByRole("button", { name: "Retry data refresh" })).not.toBeInTheDocument();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    expect(within(review).queryByRole("button", { name: "Preview resume selected" })).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("button", { name: "Recovery" }));
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
    fireEvent.click(await screen.findByRole("button", { name: "Writing rules" }));
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

it('keeps episode and budget panels independently keyed while league settings resolve', async () => {
  // Duplicate sibling keys remount both panels continuously when episode selection updates.
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<GenerationControl />);
  fireEvent.click(await screen.findByRole('button', { name: 'Spend & limits' }));
  fireEvent.change(await screen.findByLabelText('Recap limits for league'), { target: { value: 'series-one' } });
  await screen.findByLabelText('Video per episode ($)');
  expect(errors.mock.calls.filter(args => args.join(' ').includes('same key'))).toHaveLength(0);
});
