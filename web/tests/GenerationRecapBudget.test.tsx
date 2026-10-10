import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GenerationRecapBudget, parseDollars } from "../components/admin/GenerationRecapBudget";
import { RecapBudgetView } from "../lib/generation";

const request = vi.fn();
vi.mock("@/lib/api", () => ({ generationRequest: (...args: unknown[]) => request(...args) }));
// Synthetic contract fixture: backend Task 2 handoff, no production access.
const balance = { known_microusd: 1_000_000, reserved_microusd: 2_000_000, carry_forward_microusd: 1_000_000,
  uncertain_microusd: 2_000_000, unknown_count: 2, unbounded_unknown_count: 0, remaining_microusd: 11_000_000, overcommitted: false };
const view: RecapBudgetView = { series_id: "synthetic-series", revision: 1, episode_id: null, month_key: "2026-10",
  caps: { video_episode_microusd: 3_000_000, video_month_microusd: 15_000_000, combined_episode_microusd: 5_000_000, combined_month_microusd: 25_000_000 },
  balances: { video_episode_microusd: null, video_month_microusd: balance, combined_episode_microusd: null, combined_month_microusd: { ...balance, remaining_microusd: 21_000_000 } },
  app_limit: { month_microusd: 2_000_000, balance: { ...balance, remaining_microusd: 0, overcommitted: true } },
  enforcement_state: { active: true, reason: "" }, media_automation_enabled: false };
const run = vi.fn(async (action: () => Promise<unknown>) => { await action(); });
const props = { seriesId: "synthetic-series", busy: false, version: 0, run };
beforeEach(() => { request.mockReset(); run.mockClear(); request.mockResolvedValue(view); });
async function edit(value = "4.50") {
  const user = userEvent.setup();
  await screen.findByLabelText("Video per episode ($)");
  await user.clear(screen.getByLabelText("Video per episode ($)"));
  await user.type(screen.getByLabelText("Video per episode ($)"), value);
  await user.type(screen.getByLabelText("Reason for budget change"), "Allow longer coverage");
  return user;
}
describe("recap budgets", () => {
  it("shows four saved limits, scope dates and unavailable episode accounting", async () => {
    // Mutation: count uncertain dollars twice, or invent zero episode balances.
    render(<GenerationRecapBudget {...props} />);
    expect(await screen.findByLabelText("Video per episode ($)")).toHaveValue("3.00");
    expect(screen.getByLabelText("Video per month ($)")).toHaveValue("15.00");
    expect(screen.getByLabelText("Combined recap per episode, including video ($)")).toHaveValue("5.00");
    expect(screen.getByLabelText("Combined recap per month, including video ($)")).toHaveValue("25.00");
    expect(screen.getByText(/Oct 1–31, 2026 · America\/Denver/)).toBeInTheDocument();
    expect(screen.getByText(/Media automation is not enabled/)).toBeInTheDocument();
    expect(screen.getByText(/Select an episode to see episode spending/)).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Video month spending" })).getByText(/Remaining: \$11.0000/)).toBeInTheDocument();
    expect(screen.getByText(/App-wide monthly AI cap: \$2.0000/)).toBeInTheDocument();
    expect(screen.getByText(/UTC calendar month/)).toBeInTheDocument();
  });
  it("saves exact dollars explicitly and refetches server-confirmed caps", async () => {
    // Mutation: save floating dollars or claim the local draft is persisted without refetching.
    request.mockImplementation(async (_path, body) => body ? { ...view, revision: 2 } : request.mock.calls.length > 2 ? { ...view, revision: 2, caps: { ...view.caps, video_episode_microusd: 4_500_000 } } : view);
    render(<GenerationRecapBudget {...props} />);
    const user = await edit();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Save recap limits" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/recap-budgets/synthetic-series", {
      expected_revision: 1, caps: { ...view.caps, video_episode_microusd: 4_500_000 }, reason: "Allow longer coverage", acknowledge_overcommitted: false,
    }, "PUT"));
    expect(await screen.findByText("Recap limits saved and reloaded.")).toBeInTheDocument();
    expect(screen.getByLabelText("Video per episode ($)")).toHaveValue("4.50");
  });
  it.each([422, 409, 500])("preserves draft on ordinary %s failure without acknowledging", async status => {
    // Mutation: overwrite unsaved values on failure or treat all conflicts as acknowledgment requests.
    request.mockImplementation(async (_path, body) => { if (body) throw Object.assign(new Error(status === 409 ? "Stale revision. Reload limits." : "Save failed."), { status }); return view; });
    render(<GenerationRecapBudget {...props} />);
    const user = await edit(); await user.click(screen.getByRole("button", { name: "Save recap limits" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(status === 409 ? "Stale revision" : "Save failed");
    expect(screen.getByLabelText("Video per episode ($)")).toHaveValue("4.50");
    expect(screen.getByLabelText("Reason for budget change")).toHaveValue("Allow longer coverage");
    expect(screen.queryByLabelText(/I acknowledge/)).not.toBeInTheDocument();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(1);
  });
  it("requires acknowledgment for obligations and invalidates it when the draft changes", async () => {
    // Mutation: subtract unknown exposure twice, or keep acknowledgment valid for edited caps.
    render(<GenerationRecapBudget {...props} />); await edit();
    fireEvent.change(screen.getByLabelText("Video per month ($)"), { target: { value: "3.99" } });
    expect(screen.getByText(/These limits are below committed obligations/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save recap limits" })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I acknowledge/));
    expect(screen.getByRole("button", { name: "Save recap limits" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Video per month ($)"), { target: { value: "3.98" } });
    expect(screen.getByLabelText(/I acknowledge/)).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save recap limits" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Video per month ($)"), { target: { value: "4.00" } });
    expect(screen.queryByLabelText(/I acknowledge/)).not.toBeInTheDocument();
  });
  it("handles newly observed server obligations with explicit acknowledgment only", async () => {
    // Mutation: automatically retry a structured 409 with acknowledge_overcommitted true.
    request.mockImplementation(async (_path, body) => { if (body && !body.acknowledge_overcommitted) throw Object.assign(new Error("New obligations need acknowledgment."), { status: 409, detail: { code: "recap_budget_overcommitted", acknowledgment_required: true, affected: [{ scope: "video_episode", episode_id: "other-episode", ...balance }] } }); return view; });
    render(<GenerationRecapBudget {...props} />); const user = await edit();
    await user.click(screen.getByRole("button", { name: "Save recap limits" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("New obligations");
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(1);
    expect(screen.getByText(/other-episode/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save recap limits" })).toBeDisabled();
    await user.click(screen.getByLabelText(/I acknowledge/));
    await user.click(screen.getByRole("button", { name: "Save recap limits" }));
    await waitFor(() => expect(request.mock.calls.filter(c => c[1])[1][1]).toMatchObject({ acknowledge_overcommitted: true, expected_revision: 1 }));
  });
  it.each(["", "0", "-1", "1.001", "1e3", " 2", "9007199254740992"])("rejects invalid money %s", value => {
    // Mutation: accept scientific notation, fractional cents, zero, or unsafe integers.
    expect(parseDollars(value)).toBeNull();
  });
  it("prevents invalid money from reaching the API", async () => {
    // Mutation: submit a malformed draft anyway.
    render(<GenerationRecapBudget {...props} />); await edit("1.001");
    expect(screen.getByRole("button", { name: "Save recap limits" })).toBeDisabled();
    expect(screen.getByText(/positive dollar amount with at most two decimal places/)).toBeInTheDocument();
    expect(request.mock.calls.filter(c => c[1])).toHaveLength(0);
  });
  it("does not claim confirmed success when the post-save reload fails", async () => {
    // Mutation: announce saved confirmation before its required server reload succeeds.
    request.mockImplementation(async (_path, body) => { if (body) return view; if (request.mock.calls.length > 1) throw new Error("Read failed."); return view; });
    render(<GenerationRecapBudget {...props} />); const user = await edit();
    await user.click(screen.getByRole("button", { name: "Save recap limits" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Limits were saved, but reloading failed");
    expect(screen.getByLabelText("Video per episode ($)")).toHaveValue("4.50");
    expect(screen.queryByText("Recap limits saved and reloaded.")).not.toBeInTheDocument();
  });
  it("ignores a delayed earlier league response", async () => {
    // Mutation: allow the first league's response to replace the selected league.
    let resolve!: (value: RecapBudgetView) => void;
    request.mockImplementation(path => path.includes("synthetic-series") ? new Promise(r => { resolve = r; }) : Promise.resolve({ ...view, series_id: "other", caps: { ...view.caps, video_episode_microusd: 8_000_000 } }));
    const mounted = render(<GenerationRecapBudget {...props} />);
    mounted.rerender(<GenerationRecapBudget {...props} seriesId="other" />);
    expect(await screen.findByLabelText("Video per episode ($)")).toHaveValue("8.00");
    await act(async () => resolve(view));
    expect(screen.getByLabelText("Video per episode ($)")).toHaveValue("8.00");
  });
  it("preserves unsaved caps and their revision when unrelated status reloads", async () => {
    // Mutation: refetch a version change and overwrite a dirty budget draft.
    const mounted = render(<GenerationRecapBudget {...props} />); await edit();
    request.mockResolvedValue({ ...view, revision: 9 });
    mounted.rerender(<GenerationRecapBudget {...props} version={1} />);
    expect(screen.getByLabelText("Video per episode ($)")).toHaveValue("4.50");
    expect(screen.getByLabelText("Reason for budget change")).toHaveValue("Allow longer coverage");
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("queries the selected episode and renders unbounded remaining as unavailable", async () => {
    // Mutation: omit episode identity or render unbounded remaining as zero.
    request.mockResolvedValue({ ...view, episode_id: "episode-one", balances: { ...view.balances, video_episode_microusd: { ...balance, carry_forward_microusd: 0, remaining_microusd: null, unbounded_unknown_count: 1 } } });
    render(<GenerationRecapBudget {...props} episodeId="episode-one" episodeLabel="Round 1 · Week 15 · 2026" />);
    expect(await screen.findByText("Episode: Round 1 · Week 15 · 2026")).toBeInTheDocument();
    expect(screen.getByText("Technical episode identity")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/recap-budgets/synthetic-series?episode_id=episode-one");
    expect(screen.getByText(/Remaining: unavailable — unknown cost has no defensible ceiling/)).toBeInTheDocument();
  });
});
