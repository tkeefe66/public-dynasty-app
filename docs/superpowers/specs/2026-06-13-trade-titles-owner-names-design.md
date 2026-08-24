# Design: Short Trade Titles + Owner Name Mapping

**Date:** 2026-06-13
**Branch:** worktree-trade-titles-owner-names

---

## Overview

Two independent improvements to make the trade experience more readable:

1. **Short trade titles** — LLM-generated trade story headlines are currently full sentences. Change the prompt so line 1 is a punchy 5–8 word headline instead.
2. **Owner name mapping** — Sleeper usernames/handles are shown throughout the app. Add a per-league settings page where owners can be given friendly display names that propagate everywhere, including LLM story generation.

---

## Feature 1: Short Trade Titles

### Problem

The LLM's verdict line (rendered as `<h1>` on the trade detail page) is a full sentence — sometimes 20+ words. It's too long for a title.

### Solution

Update the LLM persona prompt (`trade_story_persona.md`) to produce a 5–8 word punchy headline as line 1, followed by a blank line, then 1–2 body paragraphs. The verdict sentence moves into the body prose.

### What changes

**`src/sleeper_dynasty/llm/prompts/trade_story_persona.md`** — three prompt changes (already applied):
- Line 1 instruction: short headline (5–8 words), not a sentence
- Removed "Someone got robbed. Say so." — was prescribing specific vocabulary
- Extended em-dash ban: "No em dashes anywhere in your output (headline, verdict, or body)"

**No other changes.** `parse_story()` already treats line 1 as `verdict` and the rest as `body`. The frontend already renders `verdict` as `<h1>`. No schema changes.

### Cache behavior

Existing cached stories keep their current (long) verdict. New stories and refreshed leagues get the short headline. No migration needed.

---

## Feature 2: Owner Name Settings Page

### Problem

Sleeper `display_name` values are whatever owners typed in their Sleeper profile — often handles like `tkeefe66`. These appear everywhere: trade cards, owner labels, GM ratings, and LLM-generated trade stories.

### Solution

A per-league settings page at `/league/[id]/settings` where owners can be given friendly display names. Overrides are stored server-side so they apply everywhere, including story generation.

### Data model

Override file per league chain at:
```
{CACHE_DIR}/owner_name_overrides/{league_id}.json
```

Structure:
```json
{
  "user_id_1": "Tom",
  "user_id_2": "Jake"
}
```

- Keyed by Sleeper `user_id` (stable across seasons, unlike `display_name`)
- Only overridden owners appear in the file; absent = use Sleeper `display_name`
- Survives ChainCache refreshes (separate file)
- `league_id` here is the root/entry league ID for the chain

### Backend

**New: `api/app/services/name_overrides.py`**
- `load_overrides(league_id: str) -> dict[str, str]` — reads the JSON file, returns `{}` if absent
- `save_overrides(league_id: str, overrides: dict[str, str]) -> None` — writes the JSON file

**Updated: `api/app/services/identity.py`**
- `owner_name(entry, uid)` checks overrides first, falls back to `entry.owners[uid]["owner_name"]`
- `owner_ref(entry, uid)` same — applies override to the `owner_name` field in `OwnerRef`

**Updated: `api/app/services/grader.py`**
- `owners_display` dict (used when building `TradeStoryFacts`) built via the updated `identity.owner_name()` so LLM stories use friendly names automatically

**New routes in `api/app/routes/league.py`** (or a new `settings.py` router):
- `GET /api/league/{id}/owner-names` — returns `{ owners: [ { user_id, sleeper_name, display_name } ] }` for all owners in the chain
- `PUT /api/league/{id}/owner-names` — accepts `{ overrides: { user_id: display_name } }`, saves file, returns 200

### Frontend

**New: `web/app/league/[id]/settings/page.tsx`**
- Fetches `GET /api/league/{id}/owner-names`
- Renders a list: avatar + Sleeper handle on the left, editable text input on the right
- Empty input = use Sleeper name (no override stored)
- Save button sends `PUT /api/league/{id}/owner-names` with the full override map
- Success: brief confirmation; error: show message

**Navigation:** Link to `/league/[id]/settings` from the league page header (e.g., a small gear icon or "Settings" link).

### Override resolution order

1. `owner_name_overrides/{league_id}.json` (if entry exists for this `user_id`)
2. `entry.owners[uid]["owner_name"]` (Sleeper `display_name`)
3. Raw `user_id` (final fallback)

### Scope

- Trade cards, owner labels, GM ratings, trade detail pages — all use `identity.owner_name()` or `OwnerRef`, so they pick up overrides automatically once identity.py is updated
- LLM trade stories — `owners_display` dict flows through the same resolver
- New story generation uses friendly names immediately; cached stories are not regenerated (acceptable — they'll update on next refresh)

---

## Out of scope

- Editing team names (separate from display names)
- Per-season name overrides
- Bulk import / CSV upload
- Visibility controls (names are global to the instance)
