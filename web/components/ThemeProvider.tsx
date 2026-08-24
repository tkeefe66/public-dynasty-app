"use client";

import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

interface Ctx {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

const ThemeCtx = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  /* `null` = not resolved yet, and it is deliberately NOT "light".
   *
   * With a concrete SSR-safe default, the persist effect below fires in the same
   * commit as the read effect — carrying the default, because the read's
   * `setTheme` hasn't flushed yet — and overwrites a saved "dark" in
   * localStorage. A single mount self-corrects on the next render, so this only
   * bites where effects run twice: `next dev` StrictMode remounts the provider,
   * and the second read finds the value the first pass clobbered. A saved dark
   * theme silently reverted to light on every dev reload (C13).
   *
   * There is no default to persist now: the persist effect no-ops until a real
   * preference has been read, and consumers see "light" until then. */
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem("theme") as Theme | null;
    const initial: Theme = saved
      ?? (window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark" : "light");
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);

  useEffect(() => {
    if (theme === null) return;
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  return (
    <ThemeCtx.Provider value={{ theme: theme ?? "light", setTheme }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeCtx);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}
