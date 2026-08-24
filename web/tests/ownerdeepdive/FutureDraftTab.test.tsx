import { render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DraftNeedsSection, DraftSection } from "@/components/ownerdeepdive/FutureDraftTab";
import type { OutlookView, DraftSkillView } from "@/lib/types";

const BASE = {
  window: "Contending",
  age_profile: {
    avg_age_by_position: {}, league_avg_age_by_position: {},
    overall_avg_age: 26, aging_risks: [], core_young: [],
  },
  draft_capital: {
    picks_by_season: { "2026": 2, "2027": 3 },
    picks_by_season_round: { "2026-2": 1, "2026-3": 1, "2027-1": 1, "2027-2": 1, "2027-4": 1 },
    net_vs_average: 1.8, status: "pick-rich", total_value: 4200,
  },
  draft_needs: [],
} as unknown as OutlookView;

function withNeeds(needs: OutlookView["draft_needs"]): OutlookView {
  return { ...BASE, draft_needs: needs };
}

/*
 * jsdom does not evaluate CSS, so both the desktop `hidden min-[701px]:block`
 * tree and the narrow `min-[701px]:hidden` tree exist in the rendered DOM at
 * once. Any assertion on text that is real content of the row (position,
 * urgency, reason, season, pick count) will therefore find it TWICE unless
 * scoped to one tree's testid — this is the same reason DraftGoingIn.test.tsx
 * scopes with `within(screen.getByTestId(...))` rather than bare `getByText`.
 * Structural fields that appear only in ONE tree by design (pip dots — desktop
 * only, see the fix note in FutureDraftTab.tsx) are asserted unscoped, since a
 * duplicate there would be the bug, not a testing artifact.
 */

describe("DraftNeedsSection", () => {
  it("draws depth pips only on the depth branch", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "RB", urgency: "developing", reason: "2/4 RB(s) on roster",
        held: 2, ideal: 4, kind: "depth" },
    ])} />);
    // Pips are desktop-only (the narrow card states depth as a "2 / 4" fact
    // instead), so this count is not doubled by the narrow tree existing
    // alongside the desktop one.
    const pips = container.querySelectorAll('[data-pip]');
    expect(pips).toHaveLength(4);
    expect(container.querySelectorAll('[data-pip="filled"]')).toHaveLength(2);
  });

  it("draws NO pips on a full room flagged for aging", () => {
    // The contradiction the gate exists to prevent: four filled pips beside a
    // live need. The aging branch is an elif reached only when held >= ideal.
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "TE", urgency: "developing", reason: "1 TE(s) aging out (Kelce)",
        held: 2, ideal: 2, kind: "aging" },
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
    const desktop = screen.getByTestId("draft-needs-desktop");
    expect(within(desktop).getByText(/aging out/)).toBeTruthy();
  });

  it("draws no pips on the starter-quality branch either", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "WR", urgency: "immediate", reason: "No WR ranked in starter tier (top 36)",
        held: 5, ideal: 5, kind: "quality" },
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
  });

  it("renders position codes in the mono face", () => {
    // Bricolage's Q carries a long baseline tail, so QB in the display face
    // reads as underlined at label sizes.
    render(<DraftNeedsSection outlook={withNeeds([
      { position: "QB", urgency: "immediate", reason: "Only 0 QB(s) on roster, need at least 1",
        held: 0, ideal: 2, kind: "starters" },
    ])} />);
    const desktop = screen.getByTestId("draft-needs-desktop");
    expect(within(desktop).getByText("QB").className).toContain("font-mono");
  });

  it("says what will appear here when there are no needs", () => {
    render(<DraftNeedsSection outlook={withNeeds([])} />);
    expect(screen.getByText(/no pressing needs/i)).toBeTruthy();
  });

  it("tolerates a pre-feature need with no held/ideal/kind", () => {
    const { container } = render(<DraftNeedsSection outlook={withNeeds([
      { position: "RB", urgency: "developing", reason: "2/4 RB(s) on roster" } as never,
    ])} />);
    expect(container.querySelectorAll("[data-pip]")).toHaveLength(0);
    const desktop = screen.getByTestId("draft-needs-desktop");
    expect(within(desktop).getByText(/2\/4/)).toBeTruthy();
  });

  /*
   * Structural check for the fix round: below 701px an entry is a CARD, not
   * a squeezed grid row, and every field the desktop table shows survives —
   * position, urgency, depth (as text, not dots — see above), and the full
   * reason (not truncated). jsdom cannot lay out the grid, so this cannot
   * prove the 390px render looks right, only that the right nodes exist and
   * that the narrow tree is not built from `Row`'s grid-templated markup.
   */
  it("renders the narrow tree as cards with every field present, not a squeezed grid row", () => {
    render(<DraftNeedsSection outlook={withNeeds([
      { position: "RB", urgency: "developing", reason: "2/4 RB(s) on roster",
        held: 2, ideal: 4, kind: "depth" },
    ])} />);
    const mobile = screen.getByTestId("draft-needs-mobile");
    expect(mobile.querySelectorAll('[class*="grid-cols-"]')).toHaveLength(0);
    expect(mobile.querySelectorAll("[data-pip]")).toHaveLength(0);
    expect(within(mobile).getByText("RB")).toBeTruthy();
    expect(within(mobile).getByText("developing")).toBeTruthy();
    expect(within(mobile).getByText("2 / 4")).toBeTruthy();
    expect(within(mobile).getByText(/2\/4 RB\(s\) on roster/)).toBeTruthy();
  });

  /*
   * Regression guard for the fix round's F1: a long reason rendered inside a
   * `Meta` (`whitespace-nowrap`, correct for a short fact like "2 / 4", wrong
   * for a sentence) measured 1005px wide in a live 390px-viewport render —
   * document.documentElement.scrollWidth came back 1044 against an innerWidth
   * of 390. jsdom lays out no CSS, so it cannot reproduce that pixel width;
   * what it CAN prove is the structural fix — the reason is no longer inside
   * any `whitespace-nowrap` element, so it is free to wrap. The live-browser
   * re-measurement (scrollWidth === innerWidth === 390, both themes) is
   * pasted in the task report rather than encoded here, since jsdom cannot
   * check it directly.
   */
  it("does not render the reason inside a whitespace-nowrap element", () => {
    const longReason = "1 TE(s) aging out (Travis Kelce), and the room behind him is a "
      + "single unproven rookie with no established target share to speak of";
    render(<DraftNeedsSection outlook={withNeeds([
      { position: "TE", urgency: "developing", reason: longReason, held: 2, ideal: 2, kind: "aging" },
    ])} />);
    const mobile = screen.getByTestId("draft-needs-mobile");
    const reasonEl = within(mobile).getByText(longReason);
    expect(reasonEl.className).not.toContain("whitespace-nowrap");
  });
});

describe("DraftSection", () => {
  const skill: DraftSkillView = { score: 0.4, rank: 4, of: 12 };

  it("carries no section-header meta line", () => {
    // The header is the title alone. The skill ordinal that used to sit here
    // was removed with every other top-right meta on this tab, which means
    // draft skill is no longer surfaced anywhere on the Outlook tab — assert
    // its absence so a future edit that reinstates it is a deliberate one.
    render(<DraftSection outlook={BASE} draftSkill={skill} />);
    expect(screen.queryByText(/skill #/i)).toBeNull();
    expect(screen.queryByText(/future pick/i)).toBeNull();
    expect(screen.queryByText(/next class/i)).toBeNull();
  });

  it("lists every season's picks and rounds, and totals them", () => {
    render(<DraftSection outlook={BASE} draftSkill={skill} />);
    const desktop = screen.getByTestId("outlook-draft-picks-desktop");
    expect(within(desktop).getByText("2026")).toBeTruthy();
    expect(within(desktop).getByText("2027")).toBeTruthy();
    expect(within(desktop).getByText("5")).toBeTruthy();   // total row
  });

  it("omits the skill meta entirely when there is no score", () => {
    render(<DraftSection outlook={BASE} draftSkill={null} />);
    expect(screen.queryByText(/skill #/i)).toBeNull();
  });

  /* Structural check for the fix round: this section had NO narrow variant
   * at all before it. Below 701px every season becomes a card, plus a
   * totals card carrying the same figure the desktop total row shows. */
  it("renders the narrow tree as cards with every season and the total present", () => {
    render(<DraftSection outlook={BASE} draftSkill={skill} />);
    const mobile = screen.getByTestId("outlook-draft-picks-mobile");
    expect(mobile.querySelectorAll('[class*="grid-cols-"]')).toHaveLength(0);
    expect(within(mobile).getByText("2026")).toBeTruthy();
    expect(within(mobile).getByText("2027")).toBeTruthy();
    expect(within(mobile).getByText("Total")).toBeTruthy();
    expect(within(mobile).getByText("5")).toBeTruthy();
  });
});
