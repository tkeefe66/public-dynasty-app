import { describe, it, expect, beforeEach } from "vitest";
import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "../components/ThemeProvider";
import { ThemeToggle } from "../components/ThemeToggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    localStorage.clear();
  });

  it("switches to dark when the Dark option is clicked", async () => {
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    await userEvent.click(screen.getByRole("button", { name: /dark theme/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("switches back to light when the Light option is clicked", async () => {
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    await userEvent.click(screen.getByRole("button", { name: /dark theme/i }));
    await userEvent.click(screen.getByRole("button", { name: /light theme/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  // C13: the persist effect used to fire once with the SSR-safe "light" default
  // and clobber a saved "dark" before the read effect ran. A single mount
  // self-corrects on the following render, so the bug only shows under
  // StrictMode's double-invoked effects — which is what `next dev` does, and
  // therefore what this test has to reproduce.
  it("keeps a saved dark theme under StrictMode's double-mount (C13)", () => {
    localStorage.setItem("theme", "dark");
    render(
      <StrictMode>
        <ThemeProvider><ThemeToggle /></ThemeProvider>
      </StrictMode>,
    );
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("persists preference to localStorage", async () => {
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    await userEvent.click(screen.getByRole("button", { name: /dark theme/i }));
    expect(localStorage.getItem("theme")).toBe("dark");
  });

  it("marks only the active option pressed — active inverted, year-line dialect", async () => {
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    expect(screen.getByRole("button", { name: /light theme/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /dark theme/i })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /dark theme/i }));
    expect(screen.getByRole("button", { name: /dark theme/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /light theme/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("renders the drawn light/dark marks instead of the old icon library's sun/moon", () => {
    const { container } = render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    // Two Agate icon marks (Icon.tsx), one per option — no external icon import.
    expect(container.querySelectorAll("svg").length).toBe(2);
    expect(container.querySelector(".rounded-full")).not.toBeInTheDocument();
  });
});
