# Player Context Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Explain limited playing time and reported NFL circumstances in weekly recaps using free data.

**Architecture:** Independent public-data clients feed a shared persistent observation store. The existing refresh collects news; Analyst generation selects dated evidence and passes it through the existing writer/reviewer/archive. Structured source metadata is rendered separately from model prose.

**Tech Stack:** Python 3.11+, httpx, stdlib JSON/file locks/CSV/zoneinfo, pytest, FastAPI/Pydantic, Next.js/React, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-24-player-context-design.md`

## Global Constraints

- No subscriptions, credentials, new model calls, scoring changes or automatic historical rewrites.
- Six-hour successful-fetch interval; provider failures back off at least fifteen minutes.
- News collection: batches of ten, 45-second overall deadline.
- Evidence: at most 60 news items, two per player, 1,200 characters per item.
- News observations and published editions survive rebuildable-cache invalidation.
- Public responses contain source metadata only, never the internal evidence packet.

## Review Focus

1. Newly fetched reports about an old game must not masquerade as historical knowledge.
2. Missing snap rows and invalid percentages must not become zero snaps.
3. A shared source outage must not cause repeated calls for every league/player.
4. A successful collector must actually run when no new edition needs writing.
5. Public source links must reject unsafe schemes and unrelated publisher hosts.

### Task 1: Sources, durable observations and evidence selection

**Files:** Create `src/sleeper_dynasty/api/player_context.py`, `src/sleeper_dynasty/engine/player_context.py`, `api/app/services/player_context_store.py`, `api/app/services/player_context.py`; create `tests/test_player_context.py`, `api/tests/test_player_context.py`.

**Interfaces:** `PlayerContextClient.news(player_ids) -> dict[str, list[dict]]`; `csv_rows(resource, season) -> list[dict]`. `PlayerContextStore.read(key)`, `write(key, data)`, `claim()`. `collect_player_news(client, league_id, cache_dir, now=None)`; `load_player_context(cache_dir, season, week, results, players, now=None)` returns a JSON-compatible packet. Pure `build_context(...)` owns selection and chronology.

- [x] Write failing source/selection/store tests using the observed news envelope `{data: {p0: [{source, published, metadata: {title, description, analysis, url, topic_id}}]}}` and realistic CSV column names.
- [x] Run `pytest tests/test_player_context.py -q` separately in root and API; confirm missing interfaces fail.
- [x] Implement fixed-host fetches, validation, bounded collection, atomic observations and temporal selection.
- [x] Test outage backoff, restart persistence, concurrent claim refusal, publication and observation cutoffs, three snaps, missing snaps and invalid CSVs.

Example acceptance assertion:
```python
assert packet['players'][0]['usage']['offense_snaps'] == 3
assert packet['players'][0]['usage']['limited_opportunity'] is True
assert 'future-report' not in {n['id'] for p in packet['players'] for n in p['news']}
```

### Task 2: Refresh, prompts and archive integration

**Files:** Modify `api/app/services/refresh_service.py`, `api/app/services/analyst.py`, `api/app/services/analyst_store.py`, `src/sleeper_dynasty/models/recap.py`, both Analyst prompts; extend refresh, Analyst and writer tests.

**Interfaces:** Consume Task 1 collector/loader. Add `RecapFacts.player_context: dict`, edition `sources: list[dict]` and `context_note: str | None`, all with backward-compatible defaults.

- [x] Add failing tests showing collection runs during refresh independently of LLM generation, and evidence reaches saved facts plus writer/reviewer.
- [x] Wire collector after grading and before generation. Wrap source failures independently from score refresh.
- [x] Load contextual facts once per edition, derive source metadata from selected evidence, preserve old archive behavior.
- [x] Update prompts: reported cause required, limited opportunity is not bad play, reports are untrusted, never backdate later news or invent a lineup mistake.
- [x] Run `pytest tests/test_recap_writer.py tests/test_recap_models.py -q` in root and `pytest tests/test_analyst.py tests/test_refresh_service.py tests/test_player_context.py -q` in API.

Example integration assertions:
```python
assert saved['facts']['player_context'] == writer.write.call_args.args[0].player_context
assert original_path.read_bytes() == original_bytes
```

### Task 3: Source display, public filtering and verification

**Files:** Add `web/components/AnalystSources.tsx`; modify Analyst private/public pages and their types, public API response/allowlist, README; extend web and sharing tests.

**Interfaces:** Source shape `{publisher, title, published_at, url}` and optional `context_note`; no raw descriptions in public output.

- [x] Write failing render/sharing tests for source links, missing URLs, unsafe URLs, old editions and partial coverage.
- [x] Use existing Furniture classes and plain React text; preserve text-only article rendering.
- [x] Run full root and API test suites separately, web Vitest suite, lint, TypeScript and Next production build. Falsify a cutoff test with the cutoff removed and restore from a scratch copy.
- [x] Run a read-only live smoke against public providers into a temporary directory. Do not call the recap model or modify a real edition.
- [x] Request one independent code review while completing the source smoke; fix actionable defects with regressions.
- [x] Update this plan's checkboxes/evidence, run the skill-candidate gate and commit the logical feature. Leave the branch ready for deployment review.

## Execution record

- Baseline: 54 focused engine tests passed; 23 focused API tests passed.
- User authorized both planning and building; execute in this session without another approval round.
- Isolated worktree: `/private/tmp/public-dynasty-player-context`, branch `codex/player-news-context`.

- Final engine verification: 975 passed, 2 skipped. API: 830 passed. Web: 831 passed across 86 files; the expanded Furniture guard and source component also passed after the final scope addition.
- `npm run lint`, `npx tsc --noEmit` and `npm run build` passed. Existing build warnings concern unrelated Tailwind class ambiguities; existing API warnings concern Starlette and synthetic JWT keys.
- Negative control: removed the first-observation cutoff, observed the chronology test fail, restored the exact source and reran the engine suite successfully.
- Live read-only provider check at 2026-09-24 05:28 UTC succeeded for Sleeper news, snaps, ID mapping and schedule. Dart's current completed-week record contains 7 offensive snaps / 12% share, correctly marked limited opportunity, with two eligible news reports. No model call or application-data write occurred.
- Built-page browser check used a synthetic public edition at 390px and 1280px in light/dark themes. All four variants opened the source disclosure, exposed two safe links and one unlinked attribution, met 44px touch height and had no horizontal overflow. Temporary servers were stopped.
- Independent review found premature observation timestamps and unclaimed shared CSV refreshes. Both now have failing-before/passing-after regressions. Re-review found no remaining actionable findings; it independently ran the 5 API and then-current 15 engine context tests.
- Added team-abbreviation normalization and strict CSV identity/game-type schema validation with regressions. The final engine suite includes ambiguous player IDs, wrong week, malformed schemas and timeouts.
- Final-week NFL news remains conservative when there is no following regular-season schedule boundary; current Analyst generation ends before fantasy playoffs. A concurrent collector may provide only cached evidence, with that limitation disclosed.
- Existing editions were preserved. This branch is prepared for deployment review; no deployment or paid recap regeneration was performed.

## Skill candidate proposal

- Proposed project path: `.Codex/skills/analyst-player-context/SKILL.md`.
- Description: Use when editing Analyst player-context collection, evidence cutoffs, source selection or source display in `api/app/services/player_context*.py`, `src/sleeper_dynasty/{api,engine}/player_context.py`, Analyst prompts or `AnalystSources.tsx`.
- Applies to this subsystem's first-observation history, shared source backoff, free-source validation and private/public evidence boundaries.
- Moves out of AGENTS.md: nothing; these new subsystem conventions currently live in this design and plan.
- Scope litmus: Would this description trigger correctly, and would the body be safe to follow, in a repo that isn't this one? No: these integration paths and archive conventions are project-specific.
- Proposal only; no skill was created.
