"use client";

import { useId, useRef, useState } from "react";
import {
  OwnerDetailResp, OwnerProfile, ProfilesMap,
} from "@/lib/types";
import { ownerReceipt, ownerPath } from "@/lib/receipts";
import { ProfileEditor } from "./ProfileEditor";
import { ReceiptButton } from "./ReceiptButton";
import { HeroBand } from "./ownerdeepdive/HeroBand";
import { OverviewTab, TabKey } from "./ownerdeepdive/OverviewTab";
import { TradesTab, tradeSeasons } from "./ownerdeepdive/TradesTab";
import { TrackRecordTab } from "./ownerdeepdive/TrackRecordTab";
import { PastPicksTable } from "./ownerdeepdive/PastPicksTable";
import { OutlookTab } from "./ownerdeepdive/OutlookTab";

/* ---------------------------------------------------------------------------
 * Agate — the franchise-page host (design_handoff_agate/DESIGN.md § "Named
 * rules"; CLAUDE_CODE.md § Commit 6; Agate System.dc.html Fig. 6.1). The tab
 * bar is a hairline with mono 10.5px uppercase labels, `min-height: 44px`
 * tap targets, and the active tab carrying a 2px inset ink underline instead
 * of a border-bottom swap — no card/surface framing left to remove (the host
 * never had any beyond the tab strip's own border, which is now the ruled
 * hairline). Tab/URL-state behavior is unchanged.
 * ------------------------------------------------------------------------ */

interface Props {
  leagueId: string;
  detail: OwnerDetailResp;
  profile?: OwnerProfile;
  /** Edit affordance only appears when both are provided (the Owners workspace). */
  others?: { user_id: string; name: string }[];
  onProfilesChange?: (profiles: ProfilesMap) => void;
  /** Deep-link entry tab (from the page's ?tab= param). */
  initialTab?: TabKey;
  /** Deep-link trades-year filter (from the page's ?year= param). Ignored
   *  unless it matches one of this owner's actual trade seasons. */
  initialTradesYear?: number;
  /** Mirror tab + trades-year into the query string (standalone owner page
   *  only — inside the dashboard's Owners pane the URL belongs to the
   *  dashboard's own year/lens/tab state and must not be clobbered). */
  syncUrl?: boolean;
}

export function OwnerDeepDive({
  leagueId, detail, profile, others, onProfilesChange, initialTab,
  initialTradesYear, syncUrl,
}: Props) {
  const [editing, setEditing] = useState(false);
  const editable = !!(others && onProfilesChange);
  const hasDraftPicks = Object.keys(detail.draft_picks_by_season ?? {}).length > 0;
  const TABS: { key: TabKey; label: string; short?: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "record", label: "Track Record", short: "Record" },
    { key: "trades", label: "Trades" },
    // Gated on the picks themselves, NOT on outlook: redraft leagues drop the
    // Outlook tab entirely, which used to take draft grading down with it.
    ...(hasDraftPicks ? [{ key: "draft" as TabKey, label: "Draft" }] : []),
    ...(detail.outlook ? [{ key: "outlook" as TabKey, label: "Outlook" }] : []),
  ];
  const seasons = tradeSeasons(detail.trades);
  const [tab, setTab] = useState<TabKey>(
    initialTab && TABS.some((t) => t.key === initialTab) ? initialTab : "overview",
  );
  const [tradesYear, setTradesYear] = useState<number | "all">(
    initialTradesYear !== undefined && seasons.includes(initialTradesYear)
      ? initialTradesYear
      : "all",
  );
  // `tab` can go stale when `detail` swaps under us (the Owners pane reuses one
  // instance across owners): e.g. Outlook selected, next owner has no outlook.
  const activeTab: TabKey = TABS.some((t) => t.key === tab) ? tab : "overview";

  // Shallow URL sync: history.replaceState updates the address bar (and keeps
  // Next 14.1+'s router in sync) without re-running this force-dynamic route's
  // server fetch the way router.replace would. Replace — not push — so
  // back/forward walks pages, not every tab click. Defaults are omitted so the
  // canonical URL stays clean.
  function syncQuery(nextTab: TabKey, nextYear: number | "all") {
    if (!syncUrl) return;
    const sp = new URLSearchParams(window.location.search);
    if (nextTab === "overview") sp.delete("tab");
    else sp.set("tab", nextTab);
    if (nextTab === "trades" && nextYear !== "all") sp.set("year", String(nextYear));
    else sp.delete("year");
    const qs = sp.toString();
    window.history.replaceState(
      window.history.state, "",
      `${window.location.pathname}${qs ? `?${qs}` : ""}`,
    );
  }
  function selectTab(next: TabKey) {
    setTab(next);
    syncQuery(next, tradesYear);
  }
  function selectTradesYear(next: number | "all") {
    setTradesYear(next);
    syncQuery(activeTab, next);
  }

  // Full ARIA tabs pattern: ids pair each tab with its panel, inactive tabs
  // leave the tab order (roving tabindex), and Left/Right/Home/End move both
  // selection and focus. useId keeps the ids unique per mounted instance.
  const idBase = useId();
  const tabId = (k: TabKey) => `${idBase}-tab-${k}`;
  const panelId = (k: TabKey) => `${idBase}-panel-${k}`;
  const tabRefs = useRef(new Map<TabKey, HTMLButtonElement>());
  function onTablistKeyDown(e: React.KeyboardEvent) {
    const keys = TABS.map((t) => t.key);
    const idx = keys.indexOf(activeTab);
    let next: number;
    if (e.key === "ArrowRight") next = (idx + 1) % keys.length;
    else if (e.key === "ArrowLeft") next = (idx - 1 + keys.length) % keys.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = keys.length - 1;
    else return;
    e.preventDefault();
    selectTab(keys[next]);
    tabRefs.current.get(keys[next])?.focus();
  }

  if (editing && others) {
    return (
      <ProfileEditor
        leagueId={leagueId}
        userId={detail.user_id}
        displayName={detail.owner.owner_name}
        profile={profile}
        others={others}
        onSaved={(updated) => {
          onProfilesChange?.(updated);
          setEditing(false);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const rivalNames = (profile?.rivals ?? [])
    .map((uid) => others?.find((o) => o.user_id === uid)?.name ?? null)
    .filter((n): n is string => !!n);

  const editButton = editable ? (
    <button
      type="button"
      onClick={() => setEditing(true)}
      aria-label={`Edit ${detail.owner.owner_name}'s profile`}
      className="shrink-0 font-mono text-label uppercase tracking-[0.11em] text-dim hover:text-ink transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ringfocus)]"
    >
      <span aria-hidden="true">✎</span> Edit
    </button>
  ) : null;

  return (
    <div>
      {/* 1 · Identity + verdict header */}
      <HeroBand
        detail={detail}
        archetype={profile?.archetype}
        rivalNames={rivalNames}
        roast={profile?.roast}
        editAffordance={editButton}
      />

      <div className="flex items-stretch border-b border-rule mt-4">
        {/* The strip wraps instead of scrolling: nothing but the year line
            scrolls horizontally in Agate. */}
        <div role="tablist" aria-label="Franchise sections" onKeyDown={onTablistKeyDown}
          className="flex min-w-0 flex-1 flex-wrap">
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={activeTab === t.key}
              id={tabId(t.key)} aria-controls={panelId(t.key)}
              tabIndex={activeTab === t.key ? 0 : -1}
              ref={(el) => {
                if (el) tabRefs.current.set(t.key, el);
                else tabRefs.current.delete(t.key);
              }}
              onClick={() => selectTab(t.key)}
              className={`tap flex items-end whitespace-nowrap px-3 pb-2 font-mono text-label uppercase tracking-[0.11em] transition-colors ${
                activeTab === t.key
                  ? "border-b-2 border-ink text-ink font-bold"
                  : "border-b-2 border-transparent text-dim hover:text-ink"}`}>
              {t.short ? (
                <><span className="sm:hidden">{t.short}</span><span className="hidden sm:inline">{t.label}</span></>
              ) : t.label}
            </button>
          ))}
        </div>
        <div className="flex items-end pb-2 shrink-0">
          <ReceiptButton
            claim={() => ownerReceipt(detail, activeTab, tradesYear)}
            path={() => ownerPath(leagueId, detail.user_id, activeTab, tradesYear)}
          />
        </div>
      </div>
      <div className="mt-5" role="tabpanel" id={panelId(activeTab)} aria-labelledby={tabId(activeTab)}>
        {activeTab === "overview" && <OverviewTab detail={detail} />}
        {activeTab === "record" && (
          <TrackRecordTab
            trackRecord={detail.track_record}
            headToHead={detail.head_to_head}
            leagueId={leagueId}
            userId={detail.user_id}
          />
        )}
        {activeTab === "trades" && (
          <TradesTab
            leagueId={leagueId}
            detail={detail}
            yearFilter={tradesYear}
            onYearFilterChange={selectTradesYear}
          />
        )}
        {activeTab === "draft" && (
          <PastPicksTable
            bySeason={detail.draft_picks_by_season ?? {}}
            ownerName={detail.owner.owner_name}
            format={detail.format}
            leagueId={leagueId}
          />
        )}
        {activeTab === "outlook" && detail.outlook && <OutlookTab detail={detail} />}
      </div>
    </div>
  );
}
