---
target: landing dashboard (holistic review)
total_score: 31
p0_count: 0
p1_count: 3
timestamp: 2026-06-25T03-12-52Z
slug: web-components-dashboardclient-tsx
---
# Critique: Landing Dashboard (web/components/DashboardClient.tsx)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Cold-start staged progress good; year/lens refetch dims silently with no "fetching…" label (DashboardClient.tsx:127-129). |
| 2 | Match System / Real World | 3 | Five-metric vocab grounded, but "GM Rating 1500-centered" opaque, buried in a disclosure. |
| 3 | User Control & Freedom | 3 | Tabs/sort flip freely via URL state; no reset-filters, no league-switcher escape from a wrong LEAGUE_ID. |
| 4 | Consistency & Standards | 4 | Token system + mono-for-data cohesive. Minor: "All years" vs "All-time" wording drift. |
| 5 | Error Prevention | 3 | Cold-start handled; no league-id validation, no retry-eligibility signal. |
| 6 | Recognition vs Recall | 3 | Hero cards labeled + linked; 11 standings columns need per-column tooltip hover to decode. |
| 7 | Flexibility & Efficiency | 2 | No expand-all, no export, no saved views, no keyboard accel; Leaderboard is click-per-row x12. Weakest pillar vs stated power-user audience. |
| 8 | Aesthetic & Minimalist | 4 | Genuinely restrained: zero gradients, deliberate spacing, mono accents. |
| 9 | Error Recovery | 2 | Catch-all "The refresh stopped before it finished. Try again." (:54); no diagnostic, insiders can't tell 409 vs 500 vs rate-limit. |
| 10 | Help & Documentation | 3 | Explainer + tooltips + methodology exist, but methodology buried and explainer localStorage-gated with no reopen. |
| **Total** | | **31/40** | **Good** — solid foundation, gaps in power-user flexibility, error recovery, first-visit teaching. |

## Anti-Patterns Verdict

LLM assessment: Mostly not slop — token system, mono-for-numerics, hand-built Leaderboard magnitude bars are intentional, domain-specific. One real exception: the Hero Stats row (HeroStatsRow.tsx:37, grid-cols-2 lg:grid-cols-4) is the textbook hero-metric template + identical 4-card grid — the precise pattern PRODUCT.md anti-references reject. Avoids the gradient tell, but the shape is the cliche. Biggest "AI reached for the default" moment on the page.

Deterministic scan: detect.mjs ran clean across all 8 markup files (exit 0, [], zero findings). Expected and not reassuring alone: it inspects static className strings and cannot resolve CSS-custom-property tokens, so color/contrast rules had no data. Treat as "no gradient-text / side-stripe / eyebrow-spam syntax tells," not "color verified."

Visual overlays: Skipped — no browser automation. Nothing visually verified in a running browser; source-level critique only. A live pass (running backend + graded league, cold-start returns 409 until refresh) is the honest next step for contrast/responsive checks.

## Overall Impression

Confident, dense, insider-tuned dashboard that already honors most of its brand (receipts over opinions, three lenses always visible, Linear/Vercel restraint). A Good 31/40, not a rescue job. Biggest opportunity: close the gap between what the brand promises power users (settle the argument fast, drill into any claim) and what the UI actually lets them do quickly — the receipts loop and the power-user accelerators are both one step short.

## What's Working

1. Three-lens honesty is structural, not cosmetic. Standings show Trade Value + Reg/Playoff/Toilet points + Grade side-by-side; nobody can cherry-pick. Product principle made literal.
2. Token-driven theming + focus discipline. Complete light/dark token set, :focus-visible rings wired to --ringfocus, real prefers-reduced-motion block. Accessibility floor met deliberately.
3. Cold-start doesn't blank-flash. 409 -> staged SSE progress -> skeleton -> dimmed-stale-while-refetch is a mature loading story.

## Priority Issues

[P1] The receipts loop never closes on the landing page. Every hero card links to an owner page (HeroStatsRow.tsx:33-34, ownerHref); none link to the trades that produced the number. Core job (show me what Tom fleeced) takes 3 clicks. Fix: point value/affordance at a filtered trades view, or embed a 3-row headline-trades widget. Command: shape.

[P1] First-visit teaching is fragile. The explainer defining all five metrics is localStorage-gated (ExplainerBanner.tsx:6,11,26) and once dismissed has no reopen path — a mid-season new manager who clicked x once can never get it back. Methodology only linked from inside that banner. Fix: persistent "What am I looking at?" affordance in header; don't gate the only teaching surface behind a one-way dismiss. Command: onboard.

[P1] Power-user flexibility thin for the stated audience. No expand-all/collapse-all on Leaderboard (12 rows = 12 clicks), no export/copy, no saved default view, no keyboard accelerators. Brand says power users / drill into any claim; UI makes them click one row at a time. Fix: expand-all toolbar, copy-as-CSV, persist last sort/lens. Command: shape.

[P2] Refetch has no visible in-flight signal. Changing year/lens dims content (opacity-60 + aria-busy, :127-129) but shows no label; sighted users may read as a hang and re-trigger. Fix: small "Updating…" pill or active-tab pulse while loading. Command: animate.

[P2] Hero row leans on the one banned template. Identical 4-card hero-metric grid (HeroStatsRow.tsx:37). Least distinctive, most generic-SaaS moment, contradicts PRODUCT.md. Fix: break uniformity — dominant primary stat + smaller supporting trio, or a denser league-pulse strip with sparklines/trend arrows. Command: bolder.

[P3] Error copy undiagnosable + tooltip flips theme. Generic refresh-failure string (:54); InfoTooltip hardcodes bg-ink text-bg so it inverts against dark mode (contrast passes, visually jarring). Command: clarify.

## Persona Red Flags

Alex (power user): No export, no saved views, no expand-all, no keyboard path. Sets sort manually every session despite URL state existing. Would reach for dev-tools to scrape the table.

Sam (accessibility): Strong base (focus rings, aria-busy, role=alert, aria-expanded). Gaps: Leaderboard magnitude bars are aria-hidden with no aria-label on the signed value; no "showing X of Y" count; refetch state announced but not labeled visually.

League insider (project persona): Lands wanting "who's winning the trade war this year" — but that's column 9 of 12 in standings, not a hero stat, and hero cards bounce to owner pages instead of trades. Trash-talk payoff present in data but one navigation hop too far.

## Minor Observations

- "All years" (YearTabs) vs "All-time" (Leaderboard) — unify vocabulary.
- ExplainerBanner uses a tiny uppercase mono eyebrow ("First time here?") — fine as a single contextual banner, would be a slop tell if repeated per-section.
- No breadcrumb / league-switch affordance if the wrong league loads.

## Questions to Consider

- What would the dashboard look like if "who's winning the trade war right now" were the first thing you see, not a sortable column?
- Does the hero row need to be 4 equal cards, or is there one stat that's the headline?
- Should the explainer ever be fully dismissable, given new managers join mid-season?
