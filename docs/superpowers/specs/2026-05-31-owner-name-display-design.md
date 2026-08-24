# Owner Name + Team Name Display — Design

**Date:** 2026-05-31
**Status:** Approved (pre-implementation)

## Problem

Across the web app we surface a single identity string per team. Today that string
is built once in `api/app/services/grader_io.py` as `team_name OR display_name OR
user_id`, cached in `ChainCacheEntry.display_names`, and rendered everywhere as
`display_name`. The result: when a manager set a team name, the UI shows the *team*
name; the human owner/manager is invisible.

**Goal:** show the **owner name** (the Sleeper account handle) as the primary label
everywhere, with the **team name** as a smaller secondary label beside it, plus the
team/owner **avatar**. This applies to every site where a team identity is rendered.

## Decisions (from brainstorming)

- **Mapping:** owner name = Sleeper `display_name` (the handle, always present);
  team name = `metadata.team_name` (often `null`).
- **Missing team name:** when `team_name` is `null`, render the owner line only — no
  placeholder second line.
- **Compact spots:** owner name only (no team name) in tight one-liners.
- **Avatars:** prefer the custom team avatar (`metadata.avatar`, a full URL), fall
  back to the account avatar (`https://sleepercdn.com/avatars/thumbs/{avatar}`), else
  `null`. Show avatars everywhere it makes sense (including trade cards).
- **No avatar at all:** render an initial-monogram circle (first letter of owner name)
  using existing color tokens, so rows stay aligned.
- **Architecture:** one shared `OwnerRef` shape through the API and one reusable
  `<OwnerLabel variant="full" | "compact">` React component at every site.

## Render-site inventory

**Full treatment** (avatar + owner name + dimmed team-name line when present):

| Site | File |
|------|------|
| Standings rows | `web/components/StandingsTable.tsx` |
| Owners grid cards | `web/components/OwnersTab.tsx` |
| Owner detail header | `web/app/league/[id]/owner/[uid]/page.tsx` |
| Trade side panel header | `web/components/TradeSidePanel.tsx` |

**Compact treatment** (owner name only; small avatar where it fits):

| Site | File | Avatar? |
|------|------|---------|
| Trade card parties | `web/components/TradeCard.tsx` | yes (small) |
| Hero stat owner | `web/components/HeroStatsRow.tsx` (via `HeroStat.owner`) | no — text card |
| Records owner suffix | `web/components/RecordsPanel.tsx` | no — inline sentence |
| Pick-origin `(orig: …)` | `web/components/AssetRender.tsx` | no — inline text |

## Data model

### Engine — `src/sleeper_dynasty/api/sleeper.py::get_users`

Return per `user_id`:

```python
{
    "owner_name": u.get("display_name") or "Unknown",   # the handle
    "team_name": (u.get("metadata") or {}).get("team_name"),  # nullable
    "avatar_url": _resolve_avatar(u),                   # nullable
}
```

`_resolve_avatar`: prefer `(metadata or {}).get("avatar")` when it is a full URL;
else if top-level `avatar` (an id) is set, `https://sleepercdn.com/avatars/thumbs/{id}`;
else `None`.

`get_rosters` (engine `Roster.owner_name`, used only by the CLI) is **unchanged**.

### `api/app/services/grader_io.py`

`_league_matchup_bundle` builds `owners: dict[uid, {owner_name, team_name,
avatar_url}]` from `get_users` and stores it in the bundle under key `owners`
(replacing `display_names`). `pull_supporting_data` merges `owners` across the chain
with `setdefault` per uid and returns it under `owners`.

### `api/app/services/grader.py`

Pass `owners=supporting["owners"]` into `ChainCacheEntry` (was `display_names=`).

### `api/app/services/chain_cache.py`

- `ChainCacheEntry.display_names: dict[str, str]` → `owners: dict[str, dict[str, Any]]`.
- `read()`: if a loaded file has no `owners` key, return `None` (legacy entry →
  treated as cache-miss → cold-start refresh re-pulls it). This honors the existing
  `409 cache cold` contract; no manual migration.
- `_league_matchup_bundle`: if a cached sealed-league bundle lacks `owners`, ignore
  the cache and re-fetch (so old sealed bundles re-pull too).

## API models

New shared model (in `api/app/models/`, e.g. `common.py`, imported where needed):

```python
class OwnerRef(BaseModel):
    user_id: str
    owner_name: str
    team_name: str | None = None
    avatar_url: str | None = None
```

Changes:

- `StandingRow`: drop `display_name`, add `owner: OwnerRef`.
- `OwnerDetailResp`: drop `display_name`, add `owner: OwnerRef`.
- `TradeSideView`: rename `display_name` → `owner_name`, add `team_name: str | None`,
  `avatar_url: str | None`.
- `LatestTrade.parties: list[str]` → `list[OwnerRef]`.
- `HeroStat.owner`, `Records.*_owner`: unchanged type (`str | None`) — now the owner
  handle, not the team name.

Service helpers (in `aggregations.py` or a shared module):

```python
def _owner_name(entry, uid) -> str:
    return (entry.owners.get(uid) or {}).get("owner_name") or uid

def _owner_ref(entry, uid) -> OwnerRef:
    o = entry.owners.get(uid) or {}
    return OwnerRef(user_id=uid, owner_name=o.get("owner_name") or uid,
                    team_name=o.get("team_name"), avatar_url=o.get("avatar_url"))
```

Replace every `entry.display_names.get(uid, uid)` / `entry.display_names[uid]`:
- Standings/owner rows, owner detail, trade sides → `_owner_ref`.
- Hero owner, records owner, latest-trade parties (parties → `_owner_ref`),
  trade-page pick-origin map → `_owner_name` (parties uses `_owner_ref`).

## Frontend

### `web/lib/types.ts`

```ts
export interface OwnerRef {
  user_id: string;
  owner_name: string;
  team_name?: string;
  avatar_url?: string;
}
```

- `StandingRow`: `display_name` → `owner: OwnerRef`.
- `OwnerDetailResp`: `display_name` → `owner: OwnerRef`.
- `TradeSideView`: `display_name` → `owner_name`; add `team_name?`, `avatar_url?`.
- `LatestTrade.parties: string[]` → `OwnerRef[]`.

### `web/components/OwnerLabel.tsx` (new)

```ts
interface Props { owner: OwnerRef; variant?: "full" | "compact"; }
```

- Avatar slot: `<img src={avatar_url}>` when present, else an initial-monogram circle
  (first letter of `owner_name`) using existing tokens (`--surface`/`--dim`).
- `full`: avatar + owner name (primary) and, when `team_name` is set, a smaller dimmed
  team-name line beneath.
- `compact`: avatar (small) + owner name inline; no team line.

### Component updates

- `StandingsTable.tsx`: owner cell → `<OwnerLabel owner={r.owner} variant="full" />`.
  Column header stays "Owner".
- `OwnersTab.tsx`: card name → `<OwnerLabel owner={o.owner} variant="full" />`.
- `owner/[uid]/page.tsx`: header → `<OwnerLabel owner={data.owner} variant="full" />`
  (large).
- `TradeSidePanel.tsx`: header → `<OwnerLabel>` built from side fields
  (`{user_id, owner_name, team_name, avatar_url}`), `full`.
- `TradeCard.tsx`: replace `trade.parties.join(" ↔ ")` with mapped
  `<OwnerLabel variant="compact">` separated by `↔`.
- `RecordsPanel.tsx`, `HeroStatsRow.tsx`, `AssetRender.tsx`: no markup change.
- `web/app/league/[id]/trade/[tid]/page.tsx`: build the `displayNames` map from
  `s.owner_name`; header join uses `s.owner_name`.
- `web/lib/standings-filter.ts`: sort/filter key `display_name` → `owner.owner_name`.

## Testing

- **Engine:** `get_users` avatar resolution (team URL preferred; account id →
  thumbs URL; neither → `null`); `team_name` passthrough incl. `null`.
- **API:** aggregations/owner_view/trade_view emit `OwnerRef` with correct fields;
  compact spots (hero/records/parties names) carry the handle, not the team name;
  `chain_cache.read()` returns `None` for a file lacking `owners`.
- **Frontend:** `OwnerLabel` renders the team line only when `team_name` set; monogram
  fallback when no `avatar_url`; updated `standings-filter` test for `owner.owner_name`.

## Out of scope

- CLI rendering / `Roster.owner_name` / `get_rosters`.
- Resolving pick-origin owners who never appear in a trade's sides (pre-existing
  fallback to raw id).
