# Agate followups — CLOSED. The system it tracks is retired.

> **2026-08-14 — Agate was retired and this punch list closed with it.** The app now
> ships **Furniture** from the generated `.design/` package; see `DESIGN_SYSTEM.md`
> and the `furniture-styling` skill. This file is kept as the record of the Agate
> port, not as a work list. **Do not pick up an item here without re-deciding it
> against Furniture** — several are now moot by construction.
>
> What that retirement did to the open items:
>
> | Item | Now |
> |---|---|
> | **C3** mobile standings sort | Re-scope. Under Agate an entry was rules on a striped ground; under Furniture it is an `EntryCard`, so the sort affordance is a different question. |
> | **C9** mobile trade-ledger height | Likely moot. The 19-rule stack was a consequence of the 26px lockstep. Re-measure against `EntryCard` before designing anything. |
> | **C11** lint debt | **CLOSED 2026-08-14.** `npm run lint` reports "No ESLint warnings or errors". |
> | **C14** "nothing exercises Satori" | **Half stale.** `e2e/og.spec.ts` now runs the real pipeline. The unprotected `loadFonts()`/`ImageResponse` outside the route's `try`, and the asymmetric `GEIST_VERSION` pin, are still true. |
> | **A3/A4** unverified leads | Unaffected — still awaiting a real postseason and a real draft window. |
>
> **2026-08-14, second pass.** Also closed: the three-control debt
> (`SegmentControl` is the pill-in-a-well, `YearTabs` *is* a `SegmentControl`,
> `ThemeToggle` is a documented deliberate exception) and the **bets screens**,
> which were never visually verified during the port and are now covered by
> `e2e/viewport.spec.ts` at 3 widths × 2 themes.
>
> **C9 re-measured against Furniture and it is REAL, not moot.** The prediction
> above ("likely moot — the 19-rule stack was a consequence of the 26px lockstep")
> was wrong. At 390px each received asset renders one labelled row *per metric*,
> so a single-player side costs ~10 rows: five metrics plus a `TOTAL REALIZED`
> block repeating all five — even when the total equals the only row above it.
> That duplication is the first thing to fix, and it is worse for one asset than
> for several.
>
> Also stale below, and left uncorrected as history: every reference to the
> **`agate-styling`** skill (deleted — it is `furniture-styling` now),
> **`web/tests/agate-rules.test.ts`** (replaced by `furniture-rules.test.ts`, which is
> scoped to `SCOPED_DIRS` and starts inert), the **top-level `borderRadius` override**
> (removed — the radius scale resolves normally again), and **"stamp stays in its four
> places"** (Furniture sanctions five, and cobalt, not navy).

Post-port work order. Updated **2026-08-11** after the completion sweep; superseded items
are recorded in git history (this file's first committed version) and the conversations
that shipped them — do not redo anything in "Shipped".

## Shipped (2026-08-04 → 2026-08-05)

- **Port commits 1–9** — merged `3b55237`, verified, deployed.
- **Handoff re-sync** (`ec428e7`) — `design_handoff_agate/DESIGN.md` updated from the
  "Dynasty Analyzer Design System" Claude Design project; its tokens/guidelines/templates
  mirrored under `design_handoff_agate/design-system/`; `Dynasty Directions.dc.html`
  committed, completing the bundle.
- **Stamp Direction B** (`1e21d5d`) — ink-navy second ink: masthead band (`LeagueHeader`
  full-bleed), ruling-stamp header (full-block fill, unanimous+split; no-call stays dim),
  primary buttons (new `web/components/agate/Button.tsx`), active MonoRun cells (×5),
  2px `--band-open` via `.ruled` + YearTabs. Dark counterpart shipped. Supersedes old C7.
  Dark `--stamp-rule` lifted `#3a6494`→`#41699a` for 3:1 non-text AA (3.14:1), written
  back to the design system project.
- **A1** (`54cd080`) — standings `s/t` = `Peaking 72/41` (Window stage + Strength/
  Trajectory), assembly-time join off `dynasty_outlooks`, no SCHEMA_VERSION change.
- **B1** (`36af56a`) — Leaderboard ported (ruled ledgers, ContributionRow ink bars,
  InfoTooltip, og-card last-place treatment, 👑/🪣 gone). 390px hand-checked, not
  screenshot-verified (see C6).
- **B2+B5** (`4be6457`) — OwnersTab bare letter; LeagueCard/HeroStatCard/SidebarPanels/
  RecordsPanel deleted.
- **C1, C4, C5, C8, C10** (`b942e50`) — flip-aware insight claims; `web/.eslintrc.json`
  (build lint decoupled via `ignoreDuringBuilds`, `npm run lint` is the entrypoint);
  `tsc --noEmit` fully clean; RatingBars/WindowSection contrast ≥3:1; ruling-card figures
  uncolored (stamp never touches a figure).
- **PastPicksTable rules-of-hooks bug** (`fd38718`) — hooks hoisted above the early return.
- **D1/D2** — CLAUDE.md styling bullet updated; `UpdatedDynastyDesign.md` deleted; this
  file committed.

## Shipped (2026-08-10 → 2026-08-11) — the completion sweep

- **The Agate port is complete** (`36ce8a8`…`8461249`, seven commits off
  `design_handoff_agate_completion/README.md`): signed-out funnel (**closes B3**), bets,
  the franchise page's formerly-deferred tabs, methodology, settings/editors, admin
  (**closes B4**), charts + the copy/emoji/empty-state sweep. No screen is on pre-Agate
  chrome. Notable data-honesty changes: `CareerArc` bars carry sign by position on a zero
  axis rather than hue, and `LlmCostPanel`'s four-hue stacked chart became one ink bar per
  day (the per-feature split it encoded is the ledger directly beneath it).
- **Drift is enforced, not remembered** — `web/tailwind.config.ts` overrides
  `borderRadius` at the **top level** (do not move it back under `extend`), and
  `web/tests/agate-rules.test.ts` fails the build on nine banned patterns across
  `web/{app,components,lib}` with exactly two sanctioned exceptions (both year lines).
  It shipped green against a 29-file baseline that is now empty and deleted. Any UI work
  goes through the **`agate-styling`** project skill.
- **"The Prose List"** added to `design_handoff_agate/DESIGN.md` and mirrored to the
  Claude Design project — resolves the work order's `divide-y`→`Ruled` instruction
  colliding with "Prose Never Shares A Rule" for paragraph-entry lists.
- **A2** (`c3c1fec`) — week-recap dashboard lead: `DashboardResp.week_recap` (high score,
  blowout, traded-starter points) computed at refresh from the matchup entries the
  standings read, never an in-progress week, no SCHEMA_VERSION bump.
- **C2** (`d191bcb`) — TopBar "Currently it is Week N" via a user-scoped, never-gated
  `GET /api/nfl-state` with a 300s in-process memo; renders nothing out of season.
- **C6** (`f6340cc`) — e2e auth fixture: forges the NextAuth JWE session cookie, zero app
  code. Playwright now reaches authed pages through real middleware. **Unblocks automated
  viewport QA** (the 390px gap under B1).
- **Visual QA, and it found a real bug** (**closes C12**) — `web/e2e/viewport.spec.ts` is
  a committed, env-gated matrix (3 widths × 2 themes × 7 screens) that *asserts* no
  horizontal overflow rather than only capturing images, run against a warm league via the
  C6 fixture. 44/44 green now; on the first run the **trade page overflowed the document by
  ~79px at 768–1180** because a long owner name set at 26px could not fit the ruling
  stamp's drawn 196px block. Fixed in `TradeHero` with a length-stepped display size.
  The funnel, methodology and admin were verified the same way.
- **CI** (`895fb13`) — `.github/workflows/ci.yml` runs vitest (incl. the drift guard),
  tsc, the build, and both pytest suites on push/PR. Before this nothing ran them: Railway
  deploys straight off a push.
- **C13** (`895fb13`) — `ThemeProvider` no longer clobbers a saved theme (dev-only bug; a
  `hydrated` ref does NOT fix it, the state must not have a default to persist).
- **D3** — the `og-card-satori-gotchas` project skill, which found and fixed a live bug:
  three card call sites requested **Archivo 700** while only 900 was registered, so
  Satori substituted silently. `og-font.ts` registers it now, font fetches check `r.ok`,
  and a test scans `og-card.tsx` for every family/weight pair it sets.

## A. Needs backend/API work

**A3. ~~Bracket-watch lead payload~~ — SHIPPED.** League-wide framing (Alive / Top seed /
Playoff pts), matching every other lead — the week recap names the league's high score,
not yours. `engine/playoff_phase.py::build_bracket_watch` is pure and conservative:
entrants come from every round (the top two seeds have byes and first appear in round 2,
so a round-1 scan reports a 4-team field and treats the 1 seed as eliminated), only a
*played* title-path loss eliminates, and placement games are not the title path. Persisted
as `ChainCacheEntry.bracket_watch` — value layer, always recomputed, **never frozen**:
who is alive changes every playoff week, so reusing a prior entry would stall the bracket
mid-postseason. **No SCHEMA_VERSION bump** (display data for a lead, `league_phase`
precedent). The playoff-points figure is read from the standings rows the same response
already built, so the lead cannot disagree with the table under it.

**Unverified against a real bracket.** `phase` is only `post` in Dec/Jan, so this shipped
on tests alone. First real postseason: confirm the alive count matches the bracket, the
top seed is a *surviving* seed rather than the highest that entered, and a bye week does
not eliminate anyone.

**A4. ~~Draft-phase lead~~ — SHIPPED.** The draft-window lead is now a *retrospective*
("how last year's picks panned out"), not the "picks landing" live board originally
sketched. A live board duplicates what the Sleeper app shows in real time on the screen
you're already watching during a draft, and would be empty through `pre_draft` — most of
the 7-day window. Each pick is graded against its own class
(`engine/draft_results.py::build_draft_review`: `slot_delta` = where it went minus where
it finished by production), so there is no ADP table to go stale. Surfaced as
`DashboardResp.draft_review`, built only during the draft window. Falls back to
trade-of-the-week when the class hasn't played yet — every pick at 0.0 would mean naming
a "best pick" out of ties.

**A5. ~~Weekly Trade Value series~~ — DROPPED, not deferred.** The history does not exist
and cannot be backfilled: KeepTradeCut publishes no historical endpoint, which is the same
wall that makes redraft realized repricing forward-only. `KtcSnapshotStore` only starts
accruing when the feature shipped, and the production chart spans a trade's whole tenure —
often several seasons. A metric-switcher option that renders a short scribble in the last
few percent of the x-axis reads as a broken chart, not as a data boundary, and labelling
does not fix that. Same reasoning that dropped redraft pick valuation. **If revisited:** the
only honest version needs a full season of accrued snapshots first, and even then it is
forward-only for trades made after the snapshot history begins.

## B. Screens still on old chrome

None. B3 and B4 shipped in the completion sweep; the drift guard now holds every file in
`web/{app,components,lib}` to the system.

## C. Quality followups

**C3. ~~Mobile standings sort~~ — CLOSED 2026-08-16.** A `SegmentControl` on the
Franchises card list with THREE keys — Rating, Rec, Value — chosen on a principle
rather than a budget: each is a figure the card itself renders, so the list can never
be reordered on evidence the reader cannot see. Desktop offers eight sortable columns;
no segmented control holds eight at 390px. Fixing it also surfaced a desktop bug —
`toggleSort` compared `state.sort` (sentinel `"auto"`) while every control DISPLAYED
`effectiveSort`, so the first click on the column already shown as active did nothing.

**C9. ~~Mobile trade-ledger height~~ — CLOSED 2026-08-16.** Every received asset is an
`EntryCard` — name, Trade Value (or Started Points once a trade has produced) as the
headline, the rest one tap away. Trade detail went **2,340px → 1,360px** at 390px.
Collapsed by default and deliberately not "first one open": assets sort by value, so
pre-opening the first card would always expand the biggest one. A FLIPPED asset gets no
chevron — it owns no figures, so there is nothing to open — and the TOTAL never
collapses, because "figures reconcile" means you must be able to check it against the
cards above it. The same medicine went to the draft board (3,880px → 2,619px, grouped
by owner) and the franchise trade ledger (2,058px → 1,736px).

**C14. Nothing exercises Satori.** vitest covers the OG *mappers* only, `next build`
never executes the `opengraph-image` routes (no `generateStaticParams`), and no e2e spec
requests one — so a card can 500 in production with every suite green. Related, from the
same audit: the route `try` wraps only the data fetch, leaving `loadFonts()` and
`ImageResponse` unprotected (the signature of "page fine, OG route 500s"), and
`GEIST_VERSION` drift is asymmetric — the app's faces come from the installed `geist`
package and auto-update, only the card's copy is hand-pinned. See the
`og-card-satori-gotchas` skill.

**C11. ~~Lint debt~~ — CLOSED 2026-08-14.** `cd web && npm run lint` reports
"No ESLint warnings or errors". The 20 `react/no-unescaped-entities` and the
`OwnerLabel.tsx` `no-img-element` warning are all gone.

## D. Docs / meta

**D3. ~~Skill candidate (unactioned)~~ — SHIPPED.** `og-card-satori-gotchas` exists at
`.claude/skills/og-card-satori-gotchas/SKILL.md` and C14 already cites it. Entry kept
only so the cross-reference from C14 resolves.

## Working conventions (bind on all of the above)

- Never render "KTC" — "Trade Value"/"Value". Five-metric vocabulary in exact order:
  Trade Value / Total Points / Regular Season Points / Playoff Points / Toilet Bowl Points.
- Figures Reconcile: any headline number equals the rows beneath it; margins from
  `margins_by_lens`, realized totals from `realizedTotals` — never recompute client-side.
- Stamp stays in **five** sanctioned places under Furniture (primary button fill,
  active segment/tab cell, link, focus ring, "you" marker) and is cobalt, not navy;
  never on figures/bars/letters. (`--band-open` was Agate's.)
- UI work loads the **`furniture-styling`** skill first — `agate-styling` is deleted.
  The guard test is not negotiable per-screen (a screen that seems to need an
  exception needs a named component instead). Read the matching
  `.design/templates/*.dc.html` too: the guard checks vocabulary, not composition.
- Never invent data; visible placeholder + report.
- Explicit-path `git add`; `Skill candidate:` line immediately before every commit;
  `Co-Authored-By:` trailer naming the model that did the work.
- Backend cache fields → `chain-cache-field` skill. Deploys → `railway-deploy` skill;
  push to `main` auto-deploys.
