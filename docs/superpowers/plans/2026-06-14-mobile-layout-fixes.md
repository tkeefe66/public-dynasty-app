> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# Mobile Layout Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five mobile layout bugs: wrapping top-nav, orphaned owner sub-tabs, clipping hero stat card values, a 9-column standings table that's useless on mobile, and missing column headers in the trade receipt table.

**Architecture:** All changes are Tailwind class edits or small JSX restructures in four existing Next.js components. No new files, no data layer changes, no API changes. Each task is a single component — they are independent and can be reviewed individually. Verification is TypeScript compilation (`npx tsc --noEmit`) plus a visual check in a mobile-width browser window.

**Tech Stack:** Next.js 14, Tailwind CSS, TypeScript. Working dir for all commands: `web/` unless otherwise noted.

---

## File Structure

- **Modify** `web/components/TopBar.tsx` — Task 1: mobile nav
- **Modify** `web/components/OwnerDeepDive.tsx` — Task 2: sub-nav tabs
- **Modify** `web/components/HeroStatCard.tsx` — Task 3: value overflow
- **Modify** `web/components/StandingsTable.tsx` — Task 4: mobile-only 4-column view
- **Modify** `web/components/TradeStatTable.tsx` — Task 5: mobile column header
- **Deploy** — Task 6: TypeScript check, push, poll Railway deploy

---

## Task 1: TopBar — mobile nav

**Problem:** Five nav items in a `flex gap-6` row with no mobile treatment. "GM Ratings" (two words) breaks to a second line on narrow screens. "How this works" is the least important item and wastes the most space.

**Fix:**
- Reduce gap to `gap-3` / font to `11px` on mobile (restored on `sm:`)
- Add `whitespace-nowrap` per link so individual labels never break mid-word
- Abbreviate "GM Ratings" → "GM" on mobile via responsive spans
- Hide "How this works" on mobile (`hidden sm:inline`)

**File:** `web/components/TopBar.tsx`

- [ ] **Step 1: Read the file first**

Read `web/components/TopBar.tsx`. Locate the `<nav>` element (line ~47) and the `<Link>` mapping inside it.

- [ ] **Step 2: Replace the nav element**

Replace the entire `<nav className="flex gap-6 ...">` block (the nav + its children) with:

```tsx
<nav className="flex gap-3 sm:gap-6 text-[11px] sm:text-[12px] text-dim">
  {NAV.map((n) => (
    <Link
      key={n.key}
      href={navHref(n, leagueId, year, lens)}
      className={`whitespace-nowrap ${n.key === "methodology" ? "hidden sm:inline" : ""} ${
        activeNav === n.key
          ? "text-ink font-semibold"
          : "hover:text-ink transition-colors"
      }`}
    >
      {n.key === "gm" ? (
        <>
          <span className="sm:hidden">GM</span>
          <span className="hidden sm:inline">GM Ratings</span>
        </>
      ) : (
        n.label
      )}
    </Link>
  ))}
</nav>
```

- [ ] **Step 3: TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/TopBar.tsx
git commit -m "fix(web): mobile nav — abbreviate GM, hide methodology, tighten gap"
```

---

## Task 2: Owner deep-dive — sub-nav tabs

**Problem:** `flex flex-wrap gap-1` on the tablist allows tabs to wrap. With four tabs ("Overview", "Roster & Health", "Future & Draft", "Trades"), "Trades" orphans on a second line at narrow widths.

**Fix:** Replace `flex-wrap` with `overflow-x-auto` + `[scrollbar-width:none]` + `[&::-webkit-scrollbar]:hidden` so tabs scroll horizontally instead of wrapping. Add `whitespace-nowrap` to each button so tab labels never break.

**File:** `web/components/OwnerDeepDive.tsx`

- [ ] **Step 1: Read the file first**

Read `web/components/OwnerDeepDive.tsx`. Locate the `<div role="tablist" ...>` block (line ~86) and the `<button>` elements inside it.

- [ ] **Step 2: Update the tablist container**

Change:

```tsx
<div role="tablist" aria-label="Franchise sections" className="flex flex-wrap gap-1 border-b border-divider">
```

to:

```tsx
<div role="tablist" aria-label="Franchise sections" className="flex gap-1 border-b border-divider overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
```

- [ ] **Step 3: Add `whitespace-nowrap` to tab buttons**

The `<button>` inside the map currently has a className with `px-3 py-2 text-[12px] border-b-2 -mb-px transition-colors` plus the active/inactive conditional. Add `whitespace-nowrap` to that className string:

```tsx
className={`whitespace-nowrap px-3 py-2 text-[12px] border-b-2 -mb-px transition-colors ${
  tab === t.key
    ? "border-ink text-ink font-bold"
    : "border-transparent text-dim hover:text-ink"
}`}
```

- [ ] **Step 4: TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/OwnerDeepDive.tsx
git commit -m "fix(web): owner sub-nav tabs scroll horizontally on mobile instead of wrapping"
```

---

## Task 3: HeroStatCard — value overflow

**Problem:** The value line is `text-[28px] font-extrabold` with no overflow handling. When the value is a long username (e.g. "waterboyboucher" for the "Can't Stop Wheelin'" card), it overflows the card boundary on mobile.

**Fix:** Add `truncate` (= `overflow-hidden text-ellipsis whitespace-nowrap`) to the value `<div>`. This shows an ellipsis for long strings and clips gracefully. Numbers ("+8122") are short enough at any card width and are unaffected.

**File:** `web/components/HeroStatCard.tsx`

- [ ] **Step 1: Read the file first**

Read `web/components/HeroStatCard.tsx`. Locate the value `<div>` (line ~44).

- [ ] **Step 2: Add `truncate` to the value div**

Change:

```tsx
<div className={`tabular text-[28px] font-extrabold tracking-tight leading-none mt-1.5 ${color}`}>
  {value}
</div>
```

to:

```tsx
<div className={`tabular text-[28px] font-extrabold tracking-tight leading-none mt-1.5 truncate ${color}`}>
  {value}
</div>
```

- [ ] **Step 3: TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/HeroStatCard.tsx
git commit -m "fix(web): truncate long hero stat card values (usernames) on mobile"
```

---

## Task 4: StandingsTable — mobile 4-column view

**Problem:** The standings table uses `min-w-[1100px]` inside `overflow-x-auto`. On desktop this is fine; on mobile the 9-column horizontal-scroll table is unusable — headers read "Trade Va" (truncated), values clip, and swiping to scroll is not discoverable.

**Fix:** Add a `sm:hidden` mobile-only section that shows only the four most important columns: #, Owner, Trade Value, Grade. The existing full table gets `hidden sm:block`.

**File:** `web/components/StandingsTable.tsx`

The existing `gradePillClass` helper (already defined in the file at line ~51) is reused in the mobile view. No duplication needed.

- [ ] **Step 1: Read the file first**

Read `web/components/StandingsTable.tsx`. Identify:
- The outer card wrapper `<div className="bg-surface border border-divider rounded-card p-4 px-5">` (line ~86)
- The title+row-count header `<div className="flex justify-between items-baseline mb-3.5">` (line ~87)
- The existing `<div className="overflow-x-auto">` that wraps the full table (line ~92)

- [ ] **Step 2: Wrap the existing full table in `hidden sm:block`**

Change:

```tsx
<div className="overflow-x-auto">
```

to:

```tsx
<div className="hidden sm:block overflow-x-auto">
```

- [ ] **Step 3: Insert the mobile view immediately before that wrapper**

Place the following block between the title row `</div>` and the `<div className="hidden sm:block overflow-x-auto">`:

```tsx
{/* Mobile: 4 columns — rank, owner, trade value, grade */}
<div className="sm:hidden">
  <div className="grid grid-cols-[24px_minmax(0,1fr)_80px_54px] gap-2 pb-2 border-b border-divider font-mono text-[9px] uppercase tracking-wide text-dim">
    <div>#</div>
    <div>Owner</div>
    <div className="text-right">Value</div>
    <div className="text-right">Grade</div>
  </div>
  {visible.map((r) => (
    <Link
      key={r.user_id}
      href={`/league/${leagueId}/owner/${r.user_id}`}
      className="grid grid-cols-[24px_minmax(0,1fr)_80px_54px] gap-2 py-2.5 border-b border-divider last:border-b-0 hover:bg-bg items-center cursor-pointer"
    >
      <div className="font-mono text-[11px] text-dim">{r.rank}</div>
      <div className="min-w-0">
        <OwnerLabel owner={r.owner} variant="full" />
      </div>
      <div className={`text-right text-[13px] font-semibold tabular ${
        r.net_ktc > 0 ? "text-pos" : r.net_ktc < 0 ? "text-neg" : "text-dim"
      }`}>
        {r.net_ktc > 0 ? "+" : ""}{Math.round(r.net_ktc).toLocaleString()}
      </div>
      <div className="flex justify-end">
        <span
          className="px-2 py-0.5 rounded font-bold text-[11px] font-sans"
          style={{
            background: `var(--pill-${gradePillClass(r.grade)}-bg)`,
            borderColor: `var(--pill-${gradePillClass(r.grade)}-border)`,
            color: `var(--pill-${gradePillClass(r.grade)}-text)`,
            border: "1px solid",
          }}
        >
          {r.grade}
        </span>
      </div>
    </Link>
  ))}
</div>
```

- [ ] **Step 4: TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors. `OwnerLabel`, `Link`, `gradePillClass`, `visible`, `leagueId`, and `r` are all already in scope in this component.

- [ ] **Step 5: Commit**

```bash
git add web/components/StandingsTable.tsx
git commit -m "fix(web): standings table mobile view — 4 columns (rank, owner, value, grade)"
```

---

## Task 5: TradeStatTable — mobile column header

**Problem:** The `sm:hidden` mobile view (lines 220–280) shows two values per row (VALUE and TOT) but has no column header row, so the user can't tell what the numbers mean.

**Fix:** Insert a header row as the first child of the `sm:hidden` wrapper, before `{sorted.map(...)}`.

**File:** `web/components/TradeStatTable.tsx`

- [ ] **Step 1: Read the file first**

Read `web/components/TradeStatTable.tsx`. Locate the `<div className="sm:hidden divide-y divide-divider/60 text-[12.5px]">` block (line ~220). Its first child is currently `{sorted.map((r, i) => {`.

- [ ] **Step 2: Insert the header row**

Add the following immediately after `<div className="sm:hidden divide-y divide-divider/60 text-[12.5px]">` and before `{sorted.map((r, i) => {`:

```tsx
{/* Column header — mirrors the two values shown per row */}
<div className="flex items-baseline justify-between px-4 py-1.5 border-b border-divider/80">
  <span className="font-mono text-[9px] uppercase tracking-wide text-dim">Player</span>
  <span className="flex gap-3 shrink-0">
    <span className="font-mono text-[9px] uppercase tracking-wide text-dim">Value</span>
    <span className="font-mono text-[9px] uppercase tracking-wide text-dim w-12 text-right">Tot</span>
  </span>
</div>
```

- [ ] **Step 3: TypeScript check**

```bash
cd web && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/TradeStatTable.tsx
git commit -m "fix(web): mobile trade receipt table — add column headers (Player / Value / Tot)"
```

---

## Task 6: Deploy

- [ ] **Step 1: Push to origin (triggers Railway auto-deploy)**

```bash
git push origin main
```

- [ ] **Step 2: Poll api deploy** (the `web` service carries the Next.js changes)

```bash
for i in $(seq 1 30); do
  st=$(railway deployment list --service web --limit 1 --json 2>/dev/null \
    | grep -m1 '"status"' | sed 's/.*: *"//; s/".*//')
  sha=$(railway deployment list --service web --limit 1 --json 2>/dev/null \
    | grep -m1 '"commitHash"' | sed 's/.*: *"//; s/".*//' | cut -c1-7)
  echo "[$i] web: $st ($sha)"
  case "$st" in SUCCESS|FAILED|CRASHED) break;; esac
  sleep 20
done
```

Expected: `web: SUCCESS (<sha matching HEAD>)`

- [ ] **Step 3: Verify**

```bash
echo "homepage: $(curl -sL -o /dev/null -w '%{http_code}' https://web-production-f949.up.railway.app/)"
echo "health:   $(curl -s https://web-production-f949.up.railway.app/api/health)"
```

Expected: `homepage: 200`, `health: {"status":"ok"}`

---

## Self-Review

**Spec coverage:**
- TopBar nav wrapping → Task 1 ✓
- Owner sub-nav tab orphan → Task 2 ✓
- HeroStatCard value clip → Task 3 ✓
- StandingsTable 9-column unusable on mobile → Task 4 ✓
- TradeStatTable mobile missing headers → Task 5 ✓
- Deploy → Task 6 ✓

**Placeholder scan:** No TBD/TODO. Every step shows the complete code block.

**Type consistency:**
- `gradePillClass(r.grade)` in Task 4 — function already defined in the same file at line ~51, in scope.
- `OwnerLabel`, `Link`, `visible`, `leaggeId` in Task 4 — all already imported/in scope in StandingsTable.tsx.
- `sorted`, `FromPickTag`, `TradedToLine`, `StateTag`, `FlippedTag` in Task 5 — all defined earlier in TradeStatTable.tsx, in scope.

**Known trade-off (Task 4):** The mobile standings view hides the 5 production columns (Total Points, Reg, Playoff, Toilet Bowl, Trades). These are visible on tablet/desktop or by rotating the phone. This is intentional — the primary ranking signal on mobile is Trade Value, and all 9 columns in a 390px window is worse than useful.
