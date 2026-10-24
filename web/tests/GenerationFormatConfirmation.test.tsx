import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { GenerationSettings } from "../components/admin/GenerationSettings";
import { FEATURE_LABELS, GenerationSeries, PolicyView } from "../lib/generation";

const request = vi.fn();
vi.mock("@/lib/api", () => ({ generationRequest: (...args: unknown[]) => request(...args) }));
const policy: PolicyView = {
  scope: "app", revision: 3, value: {}, effective: {
    policy: { paused: false, max_concurrency: 1, series_concurrency: 1, breaker_failures: 3,
      refresh_interval_seconds: 10800, features: Object.fromEntries(Object.keys(FEATURE_LABELS).map(key => [key, {
        mode: "manual", paused: false, model: "claude-sonnet-4-6", review_model: "claude-sonnet-4-6",
        max_calls: 4, max_tokens: 8192, max_prompt_chars: 128000,
      }])) as PolicyView["effective"]["policy"]["features"] }, sources: {}, revisions: { app: 3 }, blocked_by: [],
  },
};
// Synthetic identifiers; shape mirrors the live league setup response.
const league: GenerationSeries = {
  id: "yahoo-series", name: "Example Yahoo league", revision: 7, profile: "redraft",
  lifecycle: "pending_verification", hold: "activation_required", members: 1, effective: policy.effective,
  seasons: [
    { league_id: "test.l.old", season: 2025, verified_at: 0, capabilities_json: "{}", format_confirmation_available: true },
    { league_id: "test.l.current", season: 2026, verified_at: 0, capabilities_json: "{}", format_confirmation_available: true },
  ],
};

beforeEach(() => { request.mockReset(); request.mockResolvedValue(policy); });
afterEach(cleanup);

async function openSetup(value = league) {
  render(<GenerationSettings leagues={[value]} busy={false} version={0} run={async action => { await action(); }} />);
  await screen.findByLabelText("Weekly Analyst mode");
  fireEvent.change(screen.getByLabelText("Apply settings to"), { target: { value: "series:yahoo-series" } });
  await screen.findByLabelText("Weekly Analyst mode");
  fireEvent.click(screen.getByText("League setup and activation"));
}

it("records only the chosen current-season format after explicit confirmation", async () => {
  // Mutation: submit the oldest season, activate writing, or send on format selection.
  await openSetup();
  fireEvent.click(screen.getByRole("button", { name: "Review league format" }));
  const confirm = screen.getByRole("button", { name: "Confirm season format" });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Confirmed season format"), { target: { value: "keeper" } });
  fireEvent.change(screen.getByLabelText("Reason for this action"), { target: { value: "Owner confirms this season uses keepers" } });
  expect(request.mock.calls.filter(([, body]) => body)).toHaveLength(0);
  fireEvent.click(confirm);
  await waitFor(() => expect(request.mock.calls.filter(([, body]) => body)).toEqual([
    ["/leagues/yahoo-series/format-confirmation", {
      expected_revision: 7, league_id: "test.l.current", format: "keeper",
      reason: "Owner confirms this season uses keepers",
    }],
  ]));
});

it("does not offer confirmation based on an older season's missing format", async () => {
  // Mutation: select the first/any eligible season instead of the latest season.
  await openSetup({ ...league, seasons: [league.seasons[0], { ...league.seasons[1],
    verified_at: 123, format_confirmation_available: false,
  }] } as GenerationSeries);
  expect(screen.queryByRole("button", { name: "Review league format" })).not.toBeInTheDocument();
});
