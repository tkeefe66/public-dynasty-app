"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ThemeToggle } from "./ThemeToggle";
import { Mark as Icon, MarkName as IconName } from "./furniture/Mark";
import { WeekNote } from "./WeekNote";
import { Wordmark } from "./furniture/Wordmark";

type NavKey = "dashboard" | "trades" | "owners" | "gm" | "bets" | "draft" | "methodology" | "settings";

interface Props {
  activeNav?: NavKey;
  rightSlot?: React.ReactNode;
  // When set, Franchises/Trades/Owners become real links into this league,
  // preserving the current year/lens. Without it they stay inert ("#").
  leagueId?: string;
  year?: string;
  lens?: string;
}

const STORAGE_KEY = "last_league_ctx";

// Franchise Ratings (gm) intentionally omitted — it's covered by the dashboard
// and the Owners area. The /gm route still exists for direct links / OG cards.
//
// LABELS FOLLOW THE APPROVED INFORMATION ARCHITECTURE, and two of them moved:
// the league root (`/league/{id}`) is the standings ledger, so it is
// **Franchises**; the `?tab=owners` view is the per-manager area, so it is
// **Owners**. The keys are untouched, which is what keeps every existing
// `activeNav={tab}` call site (and `activeNav="owners"` on the owner page)
// highlighting the right item without a single caller changing.
//
// Icon assignment is per KEY, not per label: the league root reads as the
// ledger view (table), Trades is literally an exchange (swap), and the
// per-manager view is the career-wide, season-spanning one (season). Bets and
// Draft have no assigned mark — nothing in the nineteen-mark inventory reads
// as either, and drawing a twentieth is how a drawn set stops being a set.
const NAV: {
  key: NavKey;
  label: string;
  tab?: "trades" | "owners" | "gm" | "bets";
  icon?: IconName;
  // A real route rather than a `?tab=` on the league root. Draft is the only
  // entry that needs this — the minimum branch, not a reshape of the array.
  href?: (leagueId: string) => string;
}[] = [
  { key: "dashboard", label: "Franchises", icon: "table" },
  { key: "trades", label: "Trades", tab: "trades", icon: "swap" },
  { key: "owners", label: "Owners", tab: "owners", icon: "season" },
  // No icon — nothing in the nineteen marks reads as "draft" or "bets", so
  // both stay unmarked.
  { key: "draft", label: "Draft", href: (id) => `/league/${id}/draft` },
  { key: "bets", label: "Bets", tab: "bets" },
];

function navHref(
  n: (typeof NAV)[number],
  leagueId?: string,
  year?: string,
  lens?: string,
): string {
  if (!leagueId) return "#";
  if (n.href) return n.href(leagueId);
  const qs = new URLSearchParams();
  if (year && year !== "all") qs.set("year", year);
  if (lens) qs.set("lens", lens);
  if (n.tab) qs.set("tab", n.tab);
  const s = qs.toString();
  return `/league/${leagueId}${s ? `?${s}` : ""}`;
}

/**
 * The utility control — the second 31px cell in the right-hand group, opening a
 * small sheet with the two destinations that are not part of the league's own
 * story: **How this works** and **Settings**.
 *
 * WHY THESE TWO LEFT THE INLINE NAV. They were sitting in the same flat run as
 * Franchises/Trades/Owners/Bets, which reads as six peers when it is four
 * places you go to look at the league plus two pieces of housekeeping. They are
 * out of the run at ALL widths, not folded away below a breakpoint — an item
 * that moves between a nav and a menu depending on width is two different
 * information architectures.
 *
 * THE MARK IS `menu`. There is no gear in the nineteen (`add, alert, back,
 * close, closed, copy, dark, done, forward, info, light, menu, open, season,
 * share, sort-asc, sort-desc, swap, table`), and drawing a twentieth to avoid
 * that is how a drawn set stops being a set.
 *
 * Settings is league-scoped, so it renders only with a league in context
 * (either the current one or the one remembered in localStorage). A row
 * pointing at "#" is a dead destination, and an absent row reads truthfully as
 * "not here yet"; a dead one reads as broken.
 */
function UtilityMenu({ leagueId, activeNav }: { leagueId?: string; activeNav?: NavKey }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLAnchorElement>(null);

  const items: { key: NavKey; label: string; href: string }[] = [
    { key: "methodology", label: "How this works", href: "/methodology" },
    ...(leagueId
      ? [{ key: "settings" as NavKey, label: "Settings", href: `/league/${leagueId}/settings` }]
      : []),
  ];

  // FOCUS, ESCAPE, OUTSIDE-CLICK — the three things a disclosure owes its user.
  // Opening moves focus INTO the sheet (the keyboard user asked to be there);
  // Escape closes and hands focus BACK to the trigger, so the tab position is
  // where it was rather than at the top of the document; a mousedown outside
  // just closes, silently, because a pointer user has already moved on and
  // yanking focus would scroll the page under them.
  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();
    function onDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const activeHere = activeNav === "methodology" || activeNav === "settings";

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Menu"
        /* Matches ThemeToggle's 31px cell and its bordered pill exactly — the
           sanctioned chrome-strip size, not a tap-target miss (see
           `.design/components/controls/ThemeToggle.prompt.md`). Two controls
           the same size and shape read as one group; a 44px neighbour would
           make the toggle look shrunken and define the strip's height. */
        className={`flex h-[31px] w-[31px] items-center justify-center rounded-pill border border-rule-strong transition-colors ${
          open || activeHere ? "bg-ink text-bg" : "text-dim hover:text-ink"
        }`}
      >
        <Icon name="menu" size={14} />
      </button>
      {/* A solid panel has no stripe, so each row draws its own `--rule`
          hairline (the first row draws none). Popovers get no backdrop field.
          Rows are the full 44px tap target — the 31px exception is the chrome
          strip's, and it does not travel into a sheet. */}
      {open && (
        <div
          role="menu"
          className="animate-panel-in absolute right-0 top-full z-50 mt-1.5 min-w-[214px] rounded-sm border border-ink bg-bg"
        >
          {items.map((item, i) => (
            <Link
              key={item.key}
              ref={i === 0 ? firstItemRef : undefined}
              role="menuitem"
              href={item.href}
              onClick={() => setOpen(false)}
              className={`flex min-h-tap w-full items-center px-2.5 no-underline ${
                i > 0 ? "border-t border-rule" : ""
              } ${activeNav === item.key ? "font-bold text-ink" : "text-dim hover:text-ink"}`}
            >
              {item.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * The app chrome — ONE strip. `.design/components/ledger/TopBar.prompt.md` is
 * explicit: "there is no second nav and no ink app bar." Agate had a reversed
 * black app strip above the nav because its rule was that the app's name lived
 * in a 6px mono strip "and nowhere else"; Furniture retired that and folds the
 * wordmark into the nav row itself, in the DISPLAY face at mixed case rather
 * than reversed mono caps.
 *
 * Left to right: wordmark · league · the five league destinations · the right
 * group (week note, theme, utility sheet).
 */
export function TopBar({ activeNav, rightSlot, leagueId, year, lens }: Props) {
  const [saved, setSaved] = useState<{ leagueId: string; year?: string; lens?: string } | null>(null);
  useEffect(() => {
    if (leagueId) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ leagueId, year, lens }));
    } else {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) setSaved(JSON.parse(raw));
      } catch {}
    }
  }, [leagueId, year, lens]);

  const effectiveId = leagueId ?? saved?.leagueId;
  const effectiveYear = year ?? saved?.year;
  const effectiveLens = lens ?? saved?.lens;

  // The five destinations are league-context — only show them inside a league.
  // On My Leagues / Account / Admin the strip is the wordmark plus the right
  // group. (How this works stays reachable there: it lives in the sheet, which
  // renders at every width and on every screen.)
  const navItems = leagueId ? NAV : [];

  return (
    <header className="mb-6">
      <nav className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-rule px-1 py-2.5 font-mono text-label uppercase tracking-[0.11em] text-dim">
        <Link href="/" className="shrink-0 no-underline" aria-label="Fantasy Analyzer home">
          <Wordmark />
        </Link>
        {/* THE LEAGUE SITS BESIDE THE WORDMARK, not in the right group.
            `TopBar.prompt.md`: "Trades, Bets and Franchises have no masthead,
            so it is the only thing telling you which league you are in" — it
            holds identity at the left edge, where the eye lands. */}
        {/* NO LEAGUE CHIP HERE. The league name IS the masthead now
            (`LeagueHeader` hosts `LeagueSwitcher` as the nameplate), so a chip
            beside the wordmark would state the league a second time within one
            screen — the duplication this whole pass set out to remove. Two
            agents each left it in place so as not to fight the other for this
            file; removing it is the join between their halves. */}

        {/* FIVE items, one line, and NOT RENDERED AT ALL below 701px — the
            phone gets a tab bar in the dashboard body instead, and two navs
            for the same destinations is one nav too many. `hidden` (not
            a wrap) is the point: this run does not exist on a phone, so it
            cannot wrap onto a second line of chrome above the content.

            701px is the app's own breakpoint — the same one StandingsTable,
            Leaderboard and TradeStatTable use to swap a panel for cards, so
            the whole page changes shape at one width rather than three. */}
        <div className="hidden min-w-0 min-[701px]:flex items-center gap-x-5">
          {navItems.map((n) => (
            <Link
              key={n.key}
              href={navHref(n, effectiveId, effectiveYear, effectiveLens)}
              className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap ${
                activeNav === n.key ? "text-ink font-bold" : "hover:text-ink transition-colors"
              }`}
            >
              {n.icon && <Icon name={n.icon} size={12} />}
              {n.label}
            </Link>
          ))}
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {/* Drawn at the right end of the nav strip (Dashboard.dc.html) —
              renders nothing out of season or before the week is known. */}
          <WeekNote />
          <ThemeToggle />
          <UtilityMenu leagueId={effectiveId} activeNav={activeNav} />
          {rightSlot}
        </div>
      </nav>
    </header>
  );
}
