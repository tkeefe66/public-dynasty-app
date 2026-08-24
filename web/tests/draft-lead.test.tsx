import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HeadlineMoves } from "@/components/HeadlineMoves";

const dash = (over: Record<string, unknown> = {}) => ({
  league_id: "lg", phase: "draft", phase_season: 2026,
  trades: [], standings: [], owners: {},
  ...over,
}) as never;

describe("draft-window lead", () => {
  it("still renders three figures with no prior class and no trades", () => {
    const { container } = render(
      <HeadlineMoves data={dash({ draft_review: null })} leagueId="lg" />,
    );
    expect(container.textContent).toBeTruthy();
    expect(screen.queryByText(/undefined/i)).toBeNull();
  });

  it("reports an ungraded class as results, not as a grade", () => {
    render(
      <HeadlineMoves
        data={dash({
          draft_review: {
            season: 2026, graded: false, best: null, worst: null,
            beat_slot: 0, total: 24,
          },
        })}
        leagueId="lg"
      />,
    );
    expect(screen.queryByText(/best pick/i)).toBeNull();
  });
});
