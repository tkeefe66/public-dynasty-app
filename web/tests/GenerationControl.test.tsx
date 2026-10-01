import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
    if (path.startsWith("/leagues")) return { records: [], next_offset: null };
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
  it("saves only explicit overrides with the observed revision and reason", async () => {
    render(<GenerationControl />);
    await screen.findByLabelText("Configuration scope");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Enable new stories" } });
    fireEvent.change(screen.getByLabelText("Trade stories mode"), { target: { value: "automatic" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/policy/app", {
      expected_revision: 7, reason: "Enable new stories",
      value: { paused: false, features: { trade_story: { mode: "automatic" } } },
    }, "PUT"));
    expect(screen.getByText(/2 request\(s\) with unknown cost/)).toBeInTheDocument();
  });

  it("keeps a stale-save conflict visible instead of claiming success", async () => {
    const normal = request.getMockImplementation()!;
    request.mockImplementation((path, body, method) => body && path === "/policy/app"
      ? Promise.reject(new Error("Settings changed. Reload before saving.")) : normal(path, body, method));
    render(<GenerationControl />);
    await screen.findByLabelText("Configuration scope");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Pause" } });
    fireEvent.click(screen.getByRole("button", { name: "Save configuration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Settings changed");
    expect(screen.queryByText(/Configuration saved/)).not.toBeInTheDocument();
  });

  it("approves only the exact preview digest and never buys from selection alone", async () => {
    render(<GenerationControl />);
    await screen.findByLabelText("Activity");
    fireEvent.change(screen.getByLabelText("Reason for this change"), { target: { value: "Initial profile" } });
    fireEvent.change(screen.getByLabelText("Activity"), { target: { value: "candidates" } });
    fireEvent.click(await screen.findByLabelText("Select Owner One"));
    expect(request.mock.calls.some(c => c[0] === "/campaigns/apply")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Preview 1 selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve this exact campaign" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/campaigns/apply", {
      preview_id: "preview-1", digest: "bound-digest", reason: "Initial profile",
    }));
  });
});
