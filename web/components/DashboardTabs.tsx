"use client";

import Link from "next/link";
import type { DashboardTab } from "./DashboardClient";

/**
 * The phone's navigation: five tabs under the masthead, below 701px only.
 *
 * WHY A TAB BAR AND NOT THE NAV. `TopBar`'s inline run is six-ish mono links
 * that wrapped onto two rows at 390px, and stacked with the wordmark, the
 * league chip and the theme control it cost ~330px of chrome before any
 * content. `.design/templates/mobile/Mobile.dc.html` draws the phone form with
 * a tab bar instead — full-width cells, 44px, a 2px ink underline on the active
 * one — and no app nav at all. This is that, with the destinations the app
 * actually has (78px cells at 390px with five of them; the 44px height is
 * untouched).
 *
 * ABOVE 701px THIS DOES NOT RENDER and `TopBar`'s inline nav does. Same
 * destinations either way — the information architecture is identical, only its
 * presentation changes with width. `Dashboard.dc.html` draws the desktop form
 * with the nav, so both are the system's own answer at their own width.
 *
 * NOT FIXED, NOT STICKY. `readme.md`'s Layout rules still say "nothing is fixed
 * or sticky", so this scrolls away with the page like everything else.
 *
 * The labels are the ones the app should have had: **Franchises** for the
 * franchise ledger and **Owners** for the owner picker. The nav used to call
 * them "Dashboard" and "Franchises", so the word "Franchises" pointed at the
 * picker while the ledger it names sat under "Dashboard".
 */
// Draft is a real route, not one of the dashboard's own tabs — `active` is
// still typed `DashboardTab` below (it never equals "draft" in practice, so
// the cell simply never highlights), and the key type here is widened just
// enough to admit it.
const TABS: { key: DashboardTab | "draft"; label: string; href: (id: string) => string }[] = [
  { key: "dashboard", label: "Franchises", href: (id) => `/league/${id}` },
  { key: "trades", label: "Trades", href: (id) => `/league/${id}?tab=trades` },
  { key: "owners", label: "Owners", href: (id) => `/league/${id}?tab=owners` },
  { key: "bets", label: "Bets", href: (id) => `/league/${id}?tab=bets` },
  { key: "draft", label: "Draft", href: (id) => `/league/${id}/draft` },
];

export function DashboardTabs({
  leagueId,
  active,
}: {
  leagueId: string;
  active: DashboardTab;
}) {
  return (
    <nav
      aria-label="League sections"
      className="mb-4 flex border-b border-rule min-[701px]:hidden"
    >
      {TABS.map((t) => {
        const on = t.key === active;
        return (
          <Link
            key={t.key}
            href={t.href(leagueId)}
            aria-current={on ? "page" : undefined}
            className={`relative flex min-h-tap flex-1 items-center justify-center whitespace-nowrap font-mono text-label uppercase tracking-[0.06em] no-underline ${
              on ? "font-bold text-ink" : "text-dim"
            }`}
          >
            {t.label}
            {/* The active marker is a 2px ink rule sitting ON the container's
                hairline, not a fill — a tab is not one of stamp's five slots. */}
            {on && <span aria-hidden="true" className="absolute inset-x-0 -bottom-px h-0.5 bg-ink" />}
          </Link>
        );
      })}
    </nav>
  );
}
