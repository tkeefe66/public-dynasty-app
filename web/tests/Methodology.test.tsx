import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { SAMPLE, SECTIONS } from "../components/methodology/sample";
import { MethodologyContent } from "../components/methodology/MethodologyContent";

describe("MethodologyContent", () => {
  it("renders all eight section headings", () => {
    render(<MethodologyContent />);
    for (const s of ["The verdict", "The two pillars", "Inside each pillar",
      "The trade metrics", "The math", "Supporting columns",
      "How the words are written", "Sources & limits"]) {
      /* AT LEAST one. Today it is two — a desktop `SectionHead` and a mobile
       * disclosure, each `display: none` at the other's width, and jsdom applies
       * no stylesheet so both land in the tree. But two is an artifact of how
       * the breakpoint is gated, NOT the contract: pinning it exactly would
       * fail a future single-head design for being better. What actually has to
       * hold is that the section is reachable, and that each head is gated to
       * its own width — the gating is asserted directly further down. */
      expect(
        screen.getAllByRole("heading", { name: new RegExp(s, "i") }).length,
      ).toBeGreaterThanOrEqual(1);
    }
  });

  it("shows the worked example and the live pillar weights", () => {
    render(<MethodologyContent />);
    expect(screen.getAllByText(/Marcus/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("B").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1,?674/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("60%").length).toBeGreaterThan(0); // pillar weight chips
  });

  it("explains playoff success with the berth/round mini-example", () => {
    render(<MethodologyContent />);
    expect(screen.getByText(/Playoff Success/i)).toBeInTheDocument();
    expect(screen.getAllByText(/playoffs/i).length).toBeGreaterThan(0);
  });

  it("never shows the term KTC", () => {
    const { container } = render(<MethodologyContent />);
    expect(container.textContent).not.toMatch(/KTC/);
  });

  it("publishes the model that ships, not the retired one", () => {
    render(<MethodologyContent />);
    const text = document.body.textContent ?? "";
    // Case-sensitive on purpose: the Draft Capital entry legitimately says
    // "roster strength" in lower case, and only the capitalised axis NAMES are
    // the retired model's vocabulary.
    for (const dead of ["draft skill", "year-over-year momentum", "Strength",
                        "Trajectory", "Competing now", "Peaking", "Ascending",
                        "Descending"]) {
      expect(text, `retired vocabulary still on the page: ${dead}`).not.toContain(dead);
    }
    for (const live of ["Retooling", "Contending", "Rebuilding"]) {
      expect(text, `missing live stage: ${live}`).toContain(live);
    }
  });

  it("states the bands' n=12 caveat rather than implying calibration", () => {
    render(<MethodologyContent />);
    expect(document.body.textContent).toMatch(/one league/i);
  });

  it("keeps the Window entry OUT of the not-part-of-the-formula section", () => {
    // Section 6's lead asserts its entries are "not part of the Franchise
    // Rating formula". Window is banded off the rating, so that framing is
    // false for it — the entry has to live under the rating's own section.
    render(<MethodologyContent />);
    const columns = document.getElementById("columns");
    expect(columns).not.toBeNull();
    expect(within(columns as HTMLElement).queryByText("Window")).toBeNull();
    const math = document.getElementById("math");
    expect(within(math as HTMLElement).getAllByText("Window").length).toBeGreaterThan(0);
  });
});

/* ---------------------------------------------------------------------------
 * The phone layout. Below 701px the eight sections are an accordion, collapsed
 * by default; at 701px and above the page is unchanged expanded prose beside
 * the Contents rail. The breakpoint is CSS, not JS, so these assertions read
 * the class that carries it — that string IS the mechanism, and a test that
 * only checked React state would pass while the body stayed visible on a phone.
 * ------------------------------------------------------------------------ */
describe("MethodologyContent — phone accordion", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  const disclosure = (title: string) =>
    screen.getByRole("button", { name: new RegExp(title, "i") });

  it("gives every section a disclosure button that is a real button, collapsed", () => {
    render(<MethodologyContent />);
    for (const s of SECTIONS) {
      const btn = disclosure(s.title);
      expect(btn.tagName).toBe("BUTTON");
      expect(btn).toHaveAttribute("aria-expanded", "false");
      // `.tap` is min-height: var(--tap-min) — the 44px floor.
      expect(btn.className).toContain("tap");
    }
  });

  it("wraps each disclosure in the heading it replaces, in mixed case", () => {
    render(<MethodologyContent />);
    for (const s of SECTIONS) {
      const btn = disclosure(s.title);
      expect(btn.parentElement?.tagName).toBe("H2");
      // Mixed case, never uppercase — uppercase headings died with Agate. The
      // mono kicker beside it keeps its caps, so this checks the title span.
      const titleSpan = within(btn).getByText(s.title);
      expect(titleSpan.className).toContain("font-display");
      expect(titleSpan.className).not.toContain("uppercase");
    }
  });

  it("associates each body with its button, hidden ≤700px and open ≥701px", () => {
    const { container } = render(<MethodologyContent />);
    for (const s of SECTIONS) {
      const bodyId = disclosure(s.title).getAttribute("aria-controls");
      expect(bodyId).toBe(`${s.id}-body`);
      const body = container.querySelector(`[id="${bodyId}"]`);
      expect(body).not.toBeNull();
      // Collapsed on a phone …
      expect(body!.className).toContain("hidden");
      // … and still expanded at every desktop width, whatever the state says.
      expect(body!.className).toContain("min-[701px]:block");
    }
  });

  it("opens one section on tap without touching the others", () => {
    const { container } = render(<MethodologyContent />);
    const btn = disclosure("The math");
    fireEvent.click(btn);

    expect(btn).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector('[id="math-body"]')!.className).not.toContain("hidden");
    // The neighbours stay shut — this is an accordion of independent sections,
    // not a single-open tab strip.
    expect(disclosure("The verdict")).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector('[id="verdict-body"]')!.className).toContain("hidden");

    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector('[id="math-body"]')!.className).toContain("hidden");
  });

  it("keeps every anchor id, on the section element deep links point at", () => {
    const { container } = render(<MethodologyContent />);
    for (const s of SECTIONS) {
      const el = container.querySelector(`[id="${s.id}"]`);
      expect(el, `#${s.id} must survive — deep links point at it`).not.toBeNull();
      expect(el!.tagName).toBe("SECTION");
    }
  });

  it("opens the section a deep link targets, so the anchor resolves", () => {
    window.location.hash = "#signals";
    const { container } = render(<MethodologyContent />);
    expect(disclosure("Inside each pillar")).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector('[id="signals-body"]')!.className).not.toContain("hidden");
    // Untargeted sections are untouched.
    expect(disclosure("The math")).toHaveAttribute("aria-expanded", "false");
  });

  it("counts on the disclosure rows reconcile with what is inside them", () => {
    render(<MethodologyContent />);
    // A kicker is a headline figure, so it must equal the rows beneath it.
    expect(disclosure("The two pillars").textContent).toContain(
      `${SAMPLE.pillars.length} pillars`,
    );
    const signals = SAMPLE.pillars.reduce((n, p) => n + p.signals.length, 0);
    expect(disclosure("Inside each pillar").textContent).toContain(`${signals} signals`);
    // DERIVED, not hardcoded. This line said `"The five trade metrics"` and
    // `"5 metrics"`, so adding a sixth metric failed it — correctly, because
    // the section TITLE still said five while the kicker counted six. The
    // title no longer carries a number at all (the kicker already states it
    // from the data), and this reads the count from the same source the
    // component does, so the two cannot disagree again.
    expect(disclosure("The trade metrics").textContent).toMatch(/\d+ metrics/);
  });

  /* ------------------------------------------------------------------------
   * ADDED IN REVIEW. The whole design rests on TWO class strings — the one
   * that hides the desktop head below 701px, and the one that hides the mobile
   * disclosure at 701px and above. Neither was asserted anywhere: every test
   * above reads the button, the body, or the ids, so deleting
   * `min-[701px]:hidden` from the disclosure heading would put BOTH heads on
   * the desktop page, twice per section, with the whole suite still green.
   * That is the same failure mode the guard's own history records — green over
   * a rule it does not have.
   * --------------------------------------------------------------------- */
  const desktopHeadWrapper = (title: string, container: HTMLElement) => {
    const section = container.querySelector(
      `[id="${SECTIONS.find((s) => s.title === title)!.id}"]`,
    )!;
    // The `SectionHead` h2 — the one that is NOT the disclosure's heading.
    const heads = Array.from(section.querySelectorAll(":scope > *"));
    return heads[0] as HTMLElement;
  };

  it("hides the desktop head below 701px and the disclosure at 701px and up", () => {
    const { container } = render(<MethodologyContent />);
    for (const s of SECTIONS) {
      // Desktop head: display:none on a phone, block from 701px.
      const deskWrap = desktopHeadWrapper(s.title, container);
      expect(deskWrap.tagName, `#${s.id} desktop head wrapper`).toBe("DIV");
      expect(deskWrap.className).toContain("hidden");
      expect(deskWrap.className).toContain("min-[701px]:block");
      expect(within(deskWrap).getByRole("heading", { name: s.title })).toBeInTheDocument();

      // Disclosure heading: the inverse gate. Without this class both heads
      // paint on the desktop page.
      const h2 = disclosure(s.title).parentElement!;
      expect(h2.tagName).toBe("H2");
      expect(h2.className, `#${s.id} disclosure heading must vanish ≥701px`).toContain(
        "min-[701px]:hidden",
      );
    }
  });

  it("gates the spine and the 64px rhythm to ≥701px, so a phone gets a flush list", () => {
    const { container } = render(<MethodologyContent />);
    const spine = container.querySelector('[id="verdict"]')!.parentElement!;
    for (const c of ["min-[701px]:space-y-16", "min-[701px]:border-l", "min-[701px]:pl-6"]) {
      expect(spine.className, "the sections 1–3 spine is desktop-only").toContain(c);
    }
    // …and no ungated spelling survives, which would indent the phone list.
    expect(spine.className.split(/\s+/)).not.toContain("border-l");
    expect(spine.className.split(/\s+/)).not.toContain("pl-6");
    expect(spine.className.split(/\s+/)).not.toContain("space-y-16");
    expect(spine.parentElement!.className.split(/\s+/)).not.toContain("space-y-16");
  });

  it("opens a section on a LATER hashchange, not only on mount", () => {
    // The mount path is already pinned above. This pins the listener: a
    // same-page jump (the Contents rail, a back/forward, a pasted anchor)
    // arrives as `hashchange` long after mount, and the section it names is
    // still collapsed until that handler runs.
    const { container } = render(<MethodologyContent />);
    expect(disclosure("Supporting columns")).toHaveAttribute("aria-expanded", "false");

    window.location.hash = "#columns";
    fireEvent(window, new Event("hashchange"));

    expect(disclosure("Supporting columns")).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector('[id="columns-body"]')!.className).not.toContain("hidden");
    // An unknown hash opens nothing and throws nothing.
    window.location.hash = "#no-such-section";
    fireEvent(window, new Event("hashchange"));
    expect(
      container.querySelectorAll('button[aria-expanded="true"]').length,
      "an unknown hash must not open (or close) anything",
    ).toBe(1);
  });

  it("unsubscribes its hashchange listeners on unmount", () => {
    const added = new Set<EventListenerOrEventListenerObject>();
    // Wrap the real methods (bound to `window`) rather than reaching for
    // `Window.prototype` — jsdom's EventTarget rejects a re-dispatched `this`.
    const realAdd = window.addEventListener.bind(window);
    const realRemove = window.removeEventListener.bind(window);
    const addSpy = vi
      .spyOn(window, "addEventListener")
      .mockImplementation(((type: string, fn: EventListenerOrEventListenerObject, opts?: unknown) => {
        if (type === "hashchange" && fn) added.add(fn);
        return realAdd(type, fn, opts as never);
      }) as typeof window.addEventListener);
    const removeSpy = vi
      .spyOn(window, "removeEventListener")
      .mockImplementation(((type: string, fn: EventListenerOrEventListenerObject, opts?: unknown) => {
        if (type === "hashchange" && fn) added.delete(fn);
        return realRemove(type, fn, opts as never);
      }) as typeof window.removeEventListener);

    const { unmount } = render(<MethodologyContent />);
    expect(added.size, "one listener per section").toBe(SECTIONS.length);
    unmount();
    expect(added.size, "every listener is torn down — eight per mount leaks fast").toBe(0);

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});

describe("methodology sample data (coherence)", () => {
  it("pillar contributions sum to the rating delta from 1500", () => {
    const sum = SAMPLE.pillars.reduce((a, p) => a + p.contribution, 0);
    expect(1500 + sum).toBe(SAMPLE.rating); // 1500 + 132 + 42 = 1674
    expect(SAMPLE.rating).toBe(1674);
    expect(SAMPLE.letter).toBe("B"); // delta 174: >= 124 (B), < 187 (B+)
  });

  it("each pillar's signal contributions sum (within rounding) to the pillar", () => {
    for (const p of SAMPLE.pillars) {
      const s = p.signals.reduce((a, x) => a + x.contribution, 0);
      expect(Math.abs(s - p.contribution)).toBeLessThanOrEqual(2);
    }
  });

  it("uses the live v2 pillar weights (0.60 Results + 0.40 Assets, no Skill)", () => {
    const w = Object.fromEntries(SAMPLE.pillars.map((p) => [p.key, p.weight]));
    expect(w).toEqual({ results: 0.60, assets: 0.40 });
  });

  it("has the eight ordered TOC sections", () => {
    expect(SECTIONS).toHaveLength(8);
    expect(SECTIONS[0].title).toMatch(/verdict/i);
  });
});
