---
version: 1
slug: "web-components-headlinemoves-tsx"
primary_target: "web/components/HeadlineMoves.tsx"
related_targets: ["web/components/WeekRecapLead.tsx","web/components/AnalystMasthead.tsx","web/components/AnalystArchive.tsx"]
---

# Weekly recap and Analyst invitation

Scope: the regular-season dashboard lead and the shared Analyst masthead. Read mode for league managers scanning completed results before opening the weekly roast.

Lead with the top scorer and full score, then explain the trade-acquired starter contribution. Describe trade points as part of that high score only when the source user IDs match; display names are editable and may collide. A separate supporting story names both sides of the largest winning margin. Do not invent an absent trade tally.

The footer introduces The Analyst using the same masthead component as its archive page. The CTA names the completed week's roast and opens that exact season/week, independently of the current phase week. Before a completed recap exists, explain the waiting state and offer the archive without claiming a published edition exists.

Use the incumbent Furniture system. Two unequal story columns on desktop stack on mobile; names wrap, figures remain whole, and the footer CTA fills the narrow viewport. No repeated three-column stats strip. All themes must preserve contrast, keyboard focus, and tap targets.

Other seasonal dashboard leads retain their existing layouts. Archive content, generation, sharing, and corrections are outside this visual change. No unresolved design decisions.
