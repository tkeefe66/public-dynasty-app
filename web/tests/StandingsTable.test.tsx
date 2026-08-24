import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  StandingsTable, FRANCHISE_COLS, FRANCHISE_GRID,
} from "../components/StandingsTable";
import { StandingRow } from "../lib/types";

const push = vi.fn();
let searchParams = new URLSearchParams();

// StandingsTable reads router + search params from next/navigation; stub both.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}));

const ROWS: StandingRow[] = [
  {
    rank: 1, user_id: "u1", owner: { user_id: "u1", owner_name: "Tom" },
    net_ktc: 2755, net_ktc_at_trade: 2400, net_ktc_aged: 2600,
    production_total: 406.8, production_regular: 350.0, production_playoff: 0, production_toilet: 0,
    trades: 5, grade: "A", window: "Contending",
    gm_rating: 1600, gm_rank: 1, gm_letter: "B+",
    season_record: "9-4", best_finish: "🏆", playoff_record: "8-4", draft_capital_value: 2140,
  },
  {
    rank: 2, user_id: "u2", owner: { user_id: "u2", owner_name: "Mike" },
    net_ktc: -1120, net_ktc_at_trade: 1000, net_ktc_aged: 1050,
    production_total: 220.1, production_regular: -180.0, production_playoff: 0, production_toilet: 0,
    trades: 5, grade: "C", window: "Rebuilding",
    gm_rating: 1400, gm_rank: 2, gm_letter: "C-",
    season_record: "8-5", best_finish: "—", playoff_record: "5-3", draft_capital_value: 0,
  },
];

// Owners whose input order (Tom, Mike) differs from GM-rating order (Mike, Tom)
// so a real GM-rating sort is observable in the rendered row order.
const GM_ROWS: StandingRow[] = [
  { ...ROWS[0], gm_rating: 1400, gm_rank: 2, season_wins: 30 },
  { ...ROWS[1], gm_rating: 1600, gm_rank: 1, season_wins: 10 },
];

function mikeBeforeTom(): boolean {
  // FRANCHISES and TRADES each render a desktop and a mobile copy, so every
  // owner name appears up to four times; comparing the first occurrence of
  // each name is sufficient since all copies share the same sorted order.
  const tom = screen.getAllByText("Tom")[0];
  const mike = screen.getAllByText("Mike")[0];
  return Boolean(
    tom.compareDocumentPosition(mike) & Node.DOCUMENT_POSITION_PRECEDING,
  );
}

beforeEach(() => {
  push.mockClear();
  searchParams = new URLSearchParams();
  window.localStorage.clear();
});

describe("StandingsTable sections", () => {
  /* ONE LEDGER PER INSTANCE. The two used to render together; they now live on
   * the tabs that own them, so each instance draws exactly one and the other
   * must be absent — a stray second ledger is the regression this pins. */
  it("draws only the Franchises ledger, and names it, by default", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    expect(screen.getByRole("button", { name: /franchises/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /trade grades/i })).toBeNull();
  });

  it("draws only the Trade Grades ledger when asked for it", () => {
    render(<StandingsTable sections="trades" leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    expect(screen.getByRole("button", { name: /trade grades/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /franchises/i })).toBeNull();
  });

  /* THE HEAD CARRIES NO SCOPE NOTE. It used to end in a mono line at the right
   * margin — "Career-wide" on Franchises, the selected season on Trade Grades.
   * The season one restated the year control a few inches to its left, and both
   * sat far enough from the heading to read as unrelated furniture. Neither the
   * note nor the row count comes back: what a column means belongs with the
   * column. */
  it("draws no scope note or row count on either head", () => {
    const { rerender } = render(
      <StandingsTable sections="trades" leagueId="123" rows={ROWS} year={2025} currentSeason={2026}
        yearControl={<button type="button">year-control</button>} />);
    expect(document.body.textContent).not.toMatch(/All-time|Career-wide/i);
    expect(document.body.textContent).not.toMatch(/\d+ rows/);
    rerender(
      <StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026}
        yearControl={<button type="button">year-control</button>} />);
    expect(document.body.textContent).not.toMatch(/All-time|Career-wide/i);
    expect(screen.getByRole("button", { name: "year-control" })).toBeInTheDocument();
  });

  /* An early fix for a since-deleted scope note put it inside the collapse
   * <button>, which silently renamed the control to "Franchises Career-wide" —
   * announced on every toggle, and enough to break an exact-name lookup.
   * Anything inside a button is part of its name; the trigger holds the title
   * and nothing else, and that contract outlives the note. */
  it("names the collapse trigger with the title alone", () => {
    render(
      <StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026}
        yearControl={<button type="button">year-control</button>} />);
    const trigger = screen.getByRole("button", { name: /^Franchises$/ });
    expect(trigger.textContent).not.toMatch(/Career-wide/i);
  });

  /* The head's trigger is a real <button> holding ONLY the title, so a control
   * can sit beside it without nesting one interactive element in another. */
  it("puts a passed year control beside the heading, outside the collapse trigger", () => {
    render(
      <StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026}
        yearControl={<button type="button">year-control</button>} />);
    const trigger = screen.getByRole("button", { name: /franchises/i });
    const control = screen.getByRole("button", { name: "year-control" });
    expect(trigger.contains(control)).toBe(false);
  });

  it("toggles a section's collapse and persists the choice to localStorage", async () => {
    const user = userEvent.setup();
    render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    const header = screen.getByRole("button", { name: /franchises/i });

    // Desktop default (jsdom's stubbed matchMedia reports non-mobile) is open.
    expect(header).toHaveAttribute("aria-expanded", "true");

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("dr:collapse:franchises")).toBe("closed");

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    expect(window.localStorage.getItem("dr:collapse:franchises")).toBe("open");
  });
});

describe("StandingsTable structure — own row rules, no horizontal scroll", () => {
  /* INVERTED at the Furniture port. This used to assert every entry link had
   * `borderTopWidth: 0`, because under Agate the striped ground WAS the divider
   * and a row that drew its own border was the bug. A Panel is solid, so the
   * opposite is now true: an entry that draws no rule is invisible against its
   * neighbours. Same intent — "the dividers are correct" — inverted evidence.
   *
   * The no-sideways-scroll half is unchanged and survives both systems: data is
   * never hidden behind a swipe, and on a phone an entry wraps instead. */
  it("draws entry dividers per breakpoint: rules on desktop, card edges on a phone", () => {
    const { container } = render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    expect(container.innerHTML).not.toContain("overflow-x-auto");
    expect(container.innerHTML).not.toContain("min-w-[1040px]");
    expect(container.innerHTML).not.toContain("swipe");

    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);

    // The two branches answer "where does one entry end?" differently, and
    // each must answer it exactly once.
    const cards = links.filter((l) => /rounded-panel/.test(l.className));
    const rows = links.filter((l) => !/rounded-panel/.test(l.className));
    expect(cards.length, "the phone branch renders EntryCards").toBeGreaterThan(0);
    expect(rows.length, "the desktop branch renders ruled entries").toBeGreaterThan(0);

    for (const link of rows) {
      expect(link.className).not.toMatch(/border-b/);
      expect(
        link.className,
        "an entry on a solid panel must draw its own divider",
      ).toMatch(/border-t/);
    }
    for (const card of cards) {
      // A card's EDGE is the entry boundary. A top rule on top of that is the
      // second divider that `EntryCard.prompt.md` says "cut a franchise in
      // half" — the exact defect the phone branch was rebuilt to remove.
      expect(
        card.className,
        "a card must not also draw a rule — its edge is the boundary",
      ).not.toMatch(/border-t\b/);
    }
  });

  it("gives a phone entry ONE internal hairline, above its facts", () => {
    const { container } = render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    const card = screen.getAllByRole("link").find((l) => /rounded-panel/.test(l.className))!;
    // Exactly one: the MetaLine's, separating headline from detail. Anything
    // more and the entry reads as several entries.
    const internalRules = card.querySelectorAll('[class*="border-t"]');
    expect(internalRules).toHaveLength(1);
    expect(container.innerHTML).toContain("Draft cap");
  });

  it("wraps each franchise entry in exactly one link with no nested interactive elements", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    const links = screen.getAllByRole("link").filter((l) => l.getAttribute("href") === "/league/123/owner/u1");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(within(link).queryByRole("button")).toBeNull();
      expect(within(link).queryAllByRole("link")).toHaveLength(0);
    }
  });
});

describe("StandingsTable GM-rating sort and row order", () => {
  it("orders both ledgers by Franchise Rating (desc) by default", () => {
    render(<StandingsTable leagueId="123" rows={GM_ROWS} year="all" currentSeason={2026} />);
    expect(mikeBeforeTom()).toBe(true);
  });

  it("respects an explicit Franchise Rating sort", () => {
    searchParams = new URLSearchParams("sort=gm_rating.desc");
    render(<StandingsTable leagueId="123" rows={GM_ROWS} year="all" currentSeason={2026} />);
    expect(mikeBeforeTom()).toBe(true);
  });
});

describe("StandingsTable sort controls", () => {
  it("renders sort controls as real buttons with accessible names", () => {
    render(<StandingsTable sections="trades" leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("button", { name: /sort by value/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /sort by franchise/i }).length).toBeGreaterThan(0);
  });

  it("sorts when a header button is activated", async () => {
    const user = userEvent.setup();
    render(<StandingsTable sections="trades" leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    await user.click(screen.getAllByRole("button", { name: /sort by value/i })[0]);
    expect(push).toHaveBeenCalled();
    expect(push.mock.calls[0][0]).toContain("/league/123");
    expect(push.mock.calls[0][0]).toContain("sort=net_ktc");
  });
});

describe("StandingsTable grade and rating letters", () => {
  it("renders Grade and Rating as plain letters with no pill class", () => {
    // The trade grade is on Trade Grades; the Franchise Rating letter is on
    // Franchises. One ledger per instance now, so assert each where it lives.
    const { unmount } = render(
      <StandingsTable sections="trades" leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    const gradeA = screen.getAllByText("A");
    expect(gradeA.length).toBeGreaterThan(0);
    for (const el of gradeA) {
      expect(el.className).not.toMatch(/rounded/);
      expect(el.className).not.toMatch(/pill/);
    }
    unmount();
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    const ratingLetter = screen.getAllByText("B+");
    expect(ratingLetter.length).toBeGreaterThan(0);
    for (const el of ratingLetter) {
      expect(el.className).not.toMatch(/rounded/);
      expect(el.className).not.toMatch(/pill/);
    }
  });
});

describe("StandingsTable Window column", () => {
  it("shows the Window cell as mono uppercase stage text with no nested button", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    expect(screen.getAllByText("CONTENDING").length).toBeGreaterThan(0);
    expect(screen.getAllByText("REBUILDING").length).toBeGreaterThan(0);
    // Pre-authorized removal: no ?tab=outlook deep link, no nested button.
    for (const link of screen.getAllByRole("link")) {
      expect(within(link).queryByRole("button")).toBeNull();
    }
    expect(push).not.toHaveBeenCalledWith(expect.stringContaining("tab=outlook"));
  });

  it("has no s/t column and no Strength x Trajectory vocabulary anywhere", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    expect(screen.queryByText("s/t")).toBeNull();
    expect(screen.queryAllByTestId("st-value")).toHaveLength(0);
    // The tooltip bodies are in the DOM, so this reaches the Window tooltip
    // too — the one place the retired formula was still published.
    expect(document.body.textContent).not.toMatch(/Strength/i);
    expect(document.body.textContent).not.toMatch(/Trajectory/i);
  });

  it("shows the Window column for a rated dynasty league", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("columnheader", { name: /window/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("CONTENDING").length).toBeGreaterThan(0);
  });

  /* FRANCHISE_GRID and its three variants are written out in full because
     Tailwind's JIT only sees literal class names — so a dropped column and a
     dropped track are two separate edits that must stay in step. This counts
     them against each other in every gating combination the component can
     reach; jsdom lays out no grid, so a mismatch is otherwise invisible to
     every other test in this file. */
  const tracks = (g: string) => g.slice("grid-cols-[".length, -1).split("_").length;

  it("column count and grid track count agree in every gating combination", () => {
    // Rendered variant by variant so the assertion reads the same private
    // pairing the component makes, without exporting the other three names.
    expect(tracks(FRANCHISE_GRID)).toBe(FRANCHISE_COLS.length);

    const cases: { rows: StandingRow[]; drop: number }[] = [
      { rows: ROWS.map((r) => ({ ...r, roster_rank: 4 })), drop: 0 },
      { rows: ROWS.map((r) => ({ ...r, roster_rank: null })), drop: 1 },
      {
        rows: ROWS.map((r) => ({
          ...r, roster_rank: 4, window: null, draft_capital_value: null,
        })),
        drop: 2,
      },
      {
        rows: ROWS.map((r) => ({
          ...r, roster_rank: null, window: null, draft_capital_value: null,
        })),
        drop: 3,
      },
    ];
    for (const c of cases) {
      const { container, unmount } = render(
        <StandingsTable leagueId="123" rows={c.rows} year="all" currentSeason={2026} />,
      );
      const head = within(container as HTMLElement).getByTestId("franchise-head");
      const grid = /grid-cols-\[[^\]]+\]/.exec(head.className)![0];
      const headers = within(head).getAllByRole("columnheader").length;
      expect(tracks(grid), `drop=${c.drop} grid ${grid}`).toBe(headers);
      expect(headers, `drop=${c.drop}`).toBe(FRANCHISE_COLS.length - c.drop);
      unmount();
    }
  });

  it("clears a persisted sort on the deleted s/t column", () => {
    // Dropping the key from OUTLOOK_COL_KEYS is what stops the orphan check
    // catching it, so RETIRED_COL_KEYS has to. Rows are fed REVERSED so input
    // order disagrees with the default sort — without the clear, the inert
    // sort preserves input order and Mike stays first.
    searchParams = new URLSearchParams("sort=strength_trajectory.desc");
    const reversed = [...ROWS].reverse();
    render(<StandingsTable leagueId="123" rows={reversed} year="all" currentSeason={2026} />);
    const names = screen.getAllByText(/^(Tom|Mike)$/).map((n) => n.textContent);
    expect(names[0]).toBe("Tom");
  });
});

describe("StandingsTable signed figures", () => {
  it("renders signed values with the sign character always present", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    expect(screen.getAllByText("+2,755").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-1,120").length).toBeGreaterThan(0);
  });

  it("dims a zero value and renders it with no sign prefix", () => {
    const rows = [{ ...ROWS[0], net_ktc: 0 }];
    render(<StandingsTable leagueId="123" rows={rows} year={2025} currentSeason={2026} />);
    const zeros = screen.getAllByText("0");
    expect(zeros.length).toBeGreaterThan(0);
    for (const el of zeros) {
      expect(el.className).toMatch(/text-dim/);
    }
  });
});

/* The two dashboard ledgers are the one surface where the *franchise* is the
 * subject, so the Franchise column reads the Sleeper team name. Every other
 * surface (owner page, trade page, leaderboard, Owners tab) stays on the owner
 * name — see OwnerLabel.test.tsx. */
describe("StandingsTable Franchise column", () => {
  const NAMED: StandingRow[] = [
    { ...ROWS[0], owner: { ...ROWS[0].owner, team_name: "Dynasty Warriors" } },
    { ...ROWS[1], owner: { ...ROWS[1].owner, team_name: "  " } },
  ];

  it("shows the Sleeper team name on both breakpoints when the franchise has one", () => {
    render(<StandingsTable leagueId="123" rows={NAMED} year="all" currentSeason={2026} />);
    // FRANCHISES + TRADES, each in a desktop and a mobile variant.
    expect(screen.getAllByText("Dynasty Warriors").length).toBe(2);
    expect(screen.queryByText("Tom")).toBeNull();
  });

  it("falls back to the owner name when the team name is absent or blank", () => {
    render(<StandingsTable leagueId="123" rows={NAMED} year="all" currentSeason={2026} />);
    expect(screen.getAllByText("Mike").length).toBe(2);
  });

  it("sorts the Franchise column by the label it renders, not the owner name", async () => {
    const user = userEvent.setup();
    // Owner names sort Mike < Tom; team names sort Zephyrs (Tom) after Anchors (Mike)
    // only if the sort reads team names — flip them so the two orders disagree.
    const rows: StandingRow[] = [
      { ...ROWS[0], owner: { ...ROWS[0].owner, team_name: "Anchors" } },
      { ...ROWS[1], owner: { ...ROWS[1].owner, team_name: "Zephyrs" } },
    ];
    render(<StandingsTable leagueId="123" rows={rows} year="all" currentSeason={2026} />);
    await user.click(screen.getAllByRole("button", { name: /sort by franchise/i })[0]);
    expect(push).toHaveBeenCalledWith(expect.stringContaining("sort=owner_name"));
  });
});

/* ---------------------------------------------------------------------------
 * Redraft — a league with no Outlook data carries no Window / Draft cap
 * readings, and the ledger drops those columns outright. "Absence, not an
 * empty state": a column of em-dashes would still point the reader at an
 * Outlook tab that redraft owner pages do not have.
 * ------------------------------------------------------------------------ */
describe("StandingsTable outlook columns", () => {
  const REDRAFT_ROWS: StandingRow[] = ROWS.map((r) => ({
    ...r,
    window: null,
    draft_capital_value: null,
  }));

  it("omits the Window and Draft cap columns when no row carries an outlook", () => {
    render(<StandingsTable leagueId="123" rows={REDRAFT_ROWS} year="all" currentSeason={2026} />);
    expect(screen.queryByRole("columnheader", { name: /window/i })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /draft cap/i })).toBeNull();
    expect(screen.queryByText(/^cap$/i)).toBeNull();
  });

  it("keeps every other franchise column when the outlook columns drop", () => {
    render(<StandingsTable leagueId="123" rows={REDRAFT_ROWS} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("columnheader", { name: /rating/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("columnheader", { name: /trophy/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("columnheader", { name: /playoff$/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tom").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Mike").length).toBeGreaterThan(0);
  });

  it("falls back to the default sort when a saved URL names a dropped outlook column", () => {
    // A dynasty deep link opened against a redraft league. Every value in that
    // column is null, so the sort would be inert AND invisible — no header to
    // see it on or clear it from. It must degrade to the Franchise Rating
    // default, which puts Tom (1600) above Mike.
    //
    // Rows are fed in REVERSED so input order (Mike first) disagrees with the
    // default sort. Without the fallback the inert sort preserves input order
    // and Mike stays first — so this assertion genuinely discriminates.
    searchParams = new URLSearchParams("sort=draft_capital_value.desc");
    const reversed = [...REDRAFT_ROWS].reverse();
    render(<StandingsTable leagueId="123" rows={reversed} year="all" currentSeason={2026} />);
    expect(screen.queryAllByRole("columnheader", { name: /draft cap/i })).toHaveLength(0);
    const names = screen.getAllByText(/^(Tom|Mike)$/).map((n) => n.textContent);
    expect(names[0]).toBe("Tom");
  });

  it("still honours an explicit sort on a column the redraft league does render", () => {
    searchParams = new URLSearchParams("sort=owner_name.asc");
    render(<StandingsTable leagueId="123" rows={REDRAFT_ROWS} year="all" currentSeason={2026} />);
    const names = screen.getAllByText(/^(Tom|Mike)$/).map((n) => n.textContent);
    expect(names[0]).toBe("Mike");
  });

  it("keeps the outlook columns for a dynasty league (one owner missing an outlook is not enough to drop them)", () => {
    const partial: StandingRow[] = [
      ROWS[0],
      { ...ROWS[1], window: null, draft_capital_value: null },
    ];
    render(<StandingsTable leagueId="123" rows={partial} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("columnheader", { name: /window/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("CONTENDING").length).toBeGreaterThan(0);
  });
});

/* ---------------------------------------------------------------------------
 * Roster column — today's roster-value rank, gated independently of Outlook
 * (same backend condition today, but the frontend checks its own field so a
 * future format split can't silently couple the two).
 * ------------------------------------------------------------------------ */
describe("StandingsTable Roster column", () => {
  it("renders a Roster column when the rows carry a rank", () => {
    const rows: StandingRow[] = [{ ...ROWS[0], roster_rank: 6, roster_of: 12 }];
    render(<StandingsTable leagueId="123" rows={rows} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("columnheader", { name: /roster/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("#6").length).toBeGreaterThan(0);
  });

  it("omits the Roster column entirely for redraft", () => {
    const rows: StandingRow[] = ROWS.map((r) => ({ ...r, roster_rank: null, roster_of: null }));
    render(<StandingsTable leagueId="123" rows={rows} year="all" currentSeason={2026} />);
    expect(screen.queryByRole("columnheader", { name: /roster/i })).toBeNull();
    expect(screen.queryByText(/^#\d+$/)).toBeNull();
  });

  it("keeps the Roster column independent of the Outlook columns — present without Outlook", () => {
    const rows: StandingRow[] = [{
      ...ROWS[0], roster_rank: 3, roster_of: 12,
      window: null, draft_capital_value: null,
    }];
    render(<StandingsTable leagueId="123" rows={rows} year="all" currentSeason={2026} />);
    expect(screen.getAllByRole("columnheader", { name: /roster/i }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: /window/i })).toBeNull();
  });
});

describe("mobile sort (C3)", () => {
  /* Below 701px there is no HeaderRow, so sorting was desktop-only and the
   * cards sat in whatever order the server sent. jsdom renders both branches,
   * so these reach the control by its own accessible name.
   *
   * The subset is the point: three keys, each a figure the CARD renders
   * (Rating is its headline; Rec and Trade value are two of its four facts).
   * Sorting by a column the card does not show would reorder the list on
   * evidence the reader cannot see. */
  const sorter = () => screen.getByRole("group", { name: /sort franchises/i });

  it("offers exactly the three keys the card itself shows", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    const labels = within(sorter()).getAllByRole("button").map((b) => b.textContent?.replace(/[▾▴]/g, "").trim());
    expect(labels).toEqual(["Rating", "Rec", "Value"]);
  });

  it("marks the active key and shows its direction", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    // Default sort is gm_rating desc — the same order the # column shows.
    const active = within(sorter()).getByRole("button", { pressed: true });
    expect(active.textContent).toMatch(/^Rating/);
    expect(active.textContent).toContain("\u25be"); // descending
  });

  it("routes on a new key, and flips direction when the active key is tapped", async () => {
    const user = userEvent.setup();
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    push.mockClear();

    await user.click(within(sorter()).getByRole("button", { name: /^Rec/ }));
    expect(push).toHaveBeenCalledWith(expect.stringContaining("season_wins"));

    push.mockClear();
    // Tapping the ACTIVE key flips direction rather than re-selecting it —
    // the same behaviour a desktop header has.
    await user.click(within(sorter()).getByRole("button", { pressed: true }));
    expect(push).toHaveBeenCalledWith(expect.stringMatching(/asc/));
  });

  it("does not render on desktop, where the header row sorts", () => {
    render(<StandingsTable leagueId="123" rows={ROWS} year={2025} currentSeason={2026} />);
    expect(sorter().parentElement!.className).toMatch(/min-\[701px\]:hidden/);
  });

});

describe("Trade Grades ledger — Started Points", () => {
  /* The metric shipped on the trade page and the franchise page and stopped
   * there. This is the ledger that RANKS who trades well, so it is the one
   * place the "did you actually play them?" reading matters most, and it was
   * the last screen without it. */
  const WITH_STARTED = ROWS.map((r, i) => ({
    ...r, production_started: i === 0 ? 300.5 : -80.25,
  }));

  it("shows Started as a column, between Value and Reg pts", () => {
    render(<StandingsTable sections="trades" leagueId="123" rows={WITH_STARTED}
                           year={2025} currentSeason={2026} />);
    /* The HEAD ROW, with no fallback. The first version of this fell back to
     * a queryable ancestor when the testid was missing, and that ancestor was
     * wide enough to contain the phone card's "Started" fact — so renaming the
     * COLUMN to something else left this green. */
    const head = screen.getByTestId("trade-head");
    const labels = Array.from(head.children).map((c) => (c.textContent ?? "").trim());
    expect(labels).toContain("Started");
    // Between Value and Reg pts — the narrowing order the app uses everywhere.
    expect(labels.indexOf("Started")).toBeGreaterThan(labels.indexOf("Value"));
    expect(labels.indexOf("Started")).toBeLessThan(labels.indexOf("Reg pts"));
  });

  it("prints the figure on desktop and as a card fact", () => {
    render(<StandingsTable sections="trades" leagueId="123" rows={WITH_STARTED}
                           year={2025} currentSeason={2026} />);
    // Two homes, desktop row and phone card — presence in both, hence All.
    expect(screen.getAllByText("+300.5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-80.3").length).toBeGreaterThan(0);
  });

  it("dashes rather than zeroes when the response predates the field", () => {
    // A cached response served before `production_started` existed omits it.
    // Printing 0.0 would read as "this owner never started anyone".
    render(<StandingsTable sections="trades" leagueId="123" rows={ROWS}
                           year={2025} currentSeason={2026} />);
    expect(document.body.textContent).not.toMatch(/Started\s*0\.0/);
  });
});

describe("StandingsTable — an unrated franchise", () => {
  const UNRATED: StandingRow[] = [
    ROWS[0],
    { ...ROWS[1], gm_rating: null, gm_letter: null, gm_rank: null },
  ];

  it("renders an em dash in dim ink, never a C-toned letter", () => {
    render(<StandingsTable leagueId="123" rows={UNRATED} year={2025} currentSeason={2026} />);
    const dash = screen.getAllByText("—").find((el) => el.className.includes("font-display"));
    expect(dash).toBeTruthy();
    // franchiseLetterTone("C") is `text-ink/70` — toning an absence as an
    // average verdict is the bug this guards.
    expect(dash!.className).toContain("text-dim");
    expect(dash!.className).not.toContain("text-ink/70");
  });
});
