# Command Center · Plan 3 — Franchise Outlook Blurb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a 1–2 sentence LLM "franchise outlook" blurb per owner — grounded in the dynasty-outlook facts (window, young core, aging risks, draft capital, top need, signature trade) — eagerly + incrementally during refresh, cached on the chain entry, and exposed on `OwnerDetailResp.franchise_blurb` (rendered by the Plan 2 hero band).

**Architecture:** Mirror the existing GM-rating-blurb subsystem exactly: a pure facts dataclass + stable hash (`models/`), a pure facts builder (`engine/`), an Anthropic writer with a cached persona system block (`llm/`), an async incremental generator (`api/app/services/`), and a refresh stage that skips unchanged facts by hash. Missing `ANTHROPIC_API_KEY` degrades gracefully — refresh completes with no blurbs.

**Tech Stack:** Python 3, pytest, `anthropic` SDK (`claude-opus-4-8`), asyncio, FastAPI/Pydantic.

**Prerequisites:** Plan 1 merged (`entry.dynasty_outlooks`, `entry.roster_ranks`,
`entry.outlook_signals`). Plan 2 merged (hero band already renders `detail.franchise_blurb`;
`franchise_blurb?` is in `web/lib/types.ts`).

This is **Plan 3 of 3** (spec: `docs/superpowers/specs/2026-06-13-franchise-command-center-design.md`).

**Pattern references (read before starting):**
- `src/sleeper_dynasty/models/gm_rating_blurb.py` (facts dataclass + `rating_facts_hash`)
- `src/sleeper_dynasty/engine/gm_rating_blurb.py` (`build_owner_rating_facts`)
- `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` (`GmRatingBlurbWriter`, persona, parse)
- `api/app/services/blurb_gen.py` (`generate_owner_rating_blurbs`, incremental skip)
- `api/app/services/grader.py:312-335` (the `owner_blurbs` refresh stage)

---

## File Structure

- **Create** `src/sleeper_dynasty/models/franchise_outlook.py` — `FranchiseFacts` dataclass + `franchise_facts_hash`.
- **Create** `src/sleeper_dynasty/engine/franchise_outlook.py` — `build_franchise_facts()` (pure).
- **Create** `src/sleeper_dynasty/llm/franchise_outlook_writer.py` — `FranchiseOutlookWriter` + persona loader + `parse_franchise`.
- **Create** `src/sleeper_dynasty/llm/franchise_outlook_persona.md` — the system persona text.
- **Create** `api/app/services/franchise_blurb_gen.py` — `generate_franchise_blurbs()` + `franchise_facts_by_owner()`.
- **Modify** `api/app/services/chain_cache.py` — add `franchise_blurbs` field.
- **Modify** `api/app/services/grader.py` — new `franchise_blurbs` refresh stage.
- **Modify** `api/app/models/owner.py` — add `franchise_blurb: str | None`.
- **Modify** `api/app/services/owner_view.py` — populate `franchise_blurb`.
- **Tests:** `tests/test_franchise_outlook.py`, `tests/test_franchise_writer.py`, `api/tests/test_franchise_blurb_gen.py`, extend `api/tests/test_owner_view_outlook.py`.

---

## Task 1: FranchiseFacts dataclass + hash

**Files:**
- Create: `src/sleeper_dynasty/models/franchise_outlook.py`
- Test: `tests/test_franchise_outlook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_franchise_outlook.py
from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)


def _facts(**over):
    base = dict(
        user_id="uA", owner_name="Alice", team_name="Team A",
        window="Ascending", trajectory="young + pick-rich",
        overall_avg_age=24.2, roster_rank=3, roster_of=12,
        young_core=["Young Gun"], aging_risks=["Old Back"],
        draft_capital_status="pick-rich", draft_capital_net=3.0,
        top_need="RB (immediate)", signature_trade="received Bijan (+1400)",
    )
    base.update(over)
    return FranchiseFacts(**base)


def test_to_dict_is_json_safe_and_complete():
    import json
    d = _facts().to_dict()
    json.dumps(d)
    assert d["window"] == "Ascending"
    assert d["young_core"] == ["Young Gun"]


def test_hash_stable_and_sensitive():
    h1 = franchise_facts_hash(_facts())
    h2 = franchise_facts_hash(_facts())
    h3 = franchise_facts_hash(_facts(window="Rebuilding"))
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 16
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_franchise_outlook.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the dataclass + hash**

```python
# src/sleeper_dynasty/models/franchise_outlook.py
"""Facts packet for the LLM franchise-outlook blurb (mirrors gm_rating_blurb)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass
class FranchiseFacts:
    user_id: str
    owner_name: str
    team_name: str | None
    window: str
    trajectory: str
    overall_avg_age: float
    roster_rank: int | None
    roster_of: int | None
    young_core: list[str]
    aging_risks: list[str]
    draft_capital_status: str
    draft_capital_net: float
    top_need: str | None
    signature_trade: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def franchise_facts_hash(facts: FranchiseFacts) -> str:
    """Stable 16-char hash of the facts packet (used for incremental skip)."""
    blob = json.dumps(facts.to_dict(), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_franchise_outlook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/franchise_outlook.py tests/test_franchise_outlook.py
git commit -m "feat(engine): franchise outlook facts dataclass + hash"
```

---

## Task 2: `build_franchise_facts` (pure)

Build facts from a serialized outlook dict (the shape `outlook_to_dict` produces in Plan 1) plus
identity, rank, and an optional signature-trade string.

**Files:**
- Create: `src/sleeper_dynasty/engine/franchise_outlook.py`
- Test: `tests/test_franchise_outlook.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_franchise_outlook.py
from sleeper_dynasty.engine.franchise_outlook import build_franchise_facts

_OUTLOOK = {
    "window": "Ascending", "trajectory": "young + pick-rich",
    "age_profile": {
        "avg_age_by_position": {"RB": 23.5}, "overall_avg_age": 24.2,
        "aging_risks": [{"player_id": "rb_old", "full_name": "Old Back", "position": "RB", "age": 29}],
        "core_young": [{"player_id": "wr_y", "full_name": "Young Gun", "position": "WR", "age": 22}],
    },
    "draft_capital": {"picks_by_season": {"2027": 5}, "picks_by_season_round": {},
                      "net_vs_average": 3.0, "status": "pick-rich"},
    "draft_needs": [{"position": "RB", "urgency": "immediate", "reason": "thin"},
                    {"position": "TE", "urgency": "developing", "reason": "ok"}],
}


def test_build_franchise_facts_pulls_from_outlook_dict():
    facts = build_franchise_facts(
        user_id="uA", owner_name="Alice", team_name="Team A",
        outlook=_OUTLOOK, roster_rank={"rank": 3, "of": 12},
        signature_trade="received Bijan (+1400)")
    assert facts.window == "Ascending"
    assert facts.young_core == ["Young Gun"]
    assert facts.aging_risks == ["Old Back"]
    assert facts.top_need == "RB (immediate)"   # first/most-urgent need
    assert facts.roster_rank == 3 and facts.roster_of == 12
    assert facts.draft_capital_net == 3.0


def test_build_franchise_facts_tolerates_missing_rank_and_needs():
    ol = {**_OUTLOOK, "draft_needs": []}
    facts = build_franchise_facts(
        user_id="uB", owner_name="Bob", team_name=None,
        outlook=ol, roster_rank=None, signature_trade=None)
    assert facts.top_need is None
    assert facts.roster_rank is None and facts.roster_of is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_franchise_outlook.py -v`
Expected: FAIL — `build_franchise_facts` missing.

- [ ] **Step 3: Implement the builder**

```python
# src/sleeper_dynasty/engine/franchise_outlook.py
"""Build the franchise-outlook facts packet from a serialized dynasty outlook."""

from __future__ import annotations

from sleeper_dynasty.models.franchise_outlook import FranchiseFacts


def build_franchise_facts(
    *,
    user_id: str,
    owner_name: str,
    team_name: str | None,
    outlook: dict,
    roster_rank: dict | None,
    signature_trade: str | None,
) -> FranchiseFacts:
    """Assemble FranchiseFacts from the serialized outlook dict (outlook_to_dict)."""
    ap = outlook.get("age_profile", {})
    dc = outlook.get("draft_capital", {})
    needs = outlook.get("draft_needs", []) or []
    # Most-urgent need first ("immediate" before "developing").
    needs_sorted = sorted(
        needs, key=lambda n: 0 if n.get("urgency") == "immediate" else 1)
    top_need = (
        f"{needs_sorted[0]['position']} ({needs_sorted[0]['urgency']})"
        if needs_sorted else None
    )
    return FranchiseFacts(
        user_id=user_id,
        owner_name=owner_name,
        team_name=team_name,
        window=outlook.get("window", ""),
        trajectory=outlook.get("trajectory", ""),
        overall_avg_age=float(ap.get("overall_avg_age", 0.0) or 0.0),
        roster_rank=(roster_rank or {}).get("rank"),
        roster_of=(roster_rank or {}).get("of"),
        young_core=[p["full_name"] for p in ap.get("core_young", [])],
        aging_risks=[p["full_name"] for p in ap.get("aging_risks", [])],
        draft_capital_status=dc.get("status", ""),
        draft_capital_net=float(dc.get("net_vs_average", 0.0) or 0.0),
        top_need=top_need,
        signature_trade=signature_trade,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_franchise_outlook.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/franchise_outlook.py tests/test_franchise_outlook.py
git commit -m "feat(engine): build franchise outlook facts"
```

---

## Task 3: Writer + persona + parser

Mirror `GmRatingBlurbWriter`. The writer must construct the same system/user request shape; the
parser turns the model text into `{"blurb": ...}`.

**Files:**
- Create: `src/sleeper_dynasty/llm/franchise_outlook_persona.md`
- Create: `src/sleeper_dynasty/llm/franchise_outlook_writer.py`
- Test: `tests/test_franchise_writer.py`

- [ ] **Step 1: Write the persona file**

```markdown
<!-- src/sleeper_dynasty/llm/franchise_outlook_persona.md -->
You are a sharp dynasty-fantasy-football analyst writing a one- to two-sentence
franchise outlook. Use ONLY the facts in the provided packet — never invent
players, picks, or results. Lead with the team's competitive window, weave in the
strongest one or two signals (young core, aging risk, draft capital, a pressing
need, or the signature trade), and end with a forward-looking read. Be vivid and
concise. No headings, no lists, no markdown — just the prose.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_franchise_writer.py
import json

from sleeper_dynasty.llm.franchise_outlook_writer import (
    FranchiseOutlookWriter, parse_franchise,
)
from sleeper_dynasty.models.franchise_outlook import FranchiseFacts


def _facts():
    return FranchiseFacts(
        user_id="uA", owner_name="Alice", team_name="Team A",
        window="Ascending", trajectory="young + pick-rich", overall_avg_age=24.2,
        roster_rank=3, roster_of=12, young_core=["Young Gun"],
        aging_risks=[], draft_capital_status="pick-rich", draft_capital_net=3.0,
        top_need="RB (immediate)", signature_trade="received Bijan (+1400)")


def test_parse_franchise_trims_to_blurb():
    out = parse_franchise("  Ascending and dangerous.\n")
    assert out == {"blurb": "Ascending and dangerous."}


def test_build_request_embeds_facts_json_and_caches_persona():
    w = FranchiseOutlookWriter(api_key="test-key")
    system, messages = w.build_request(_facts())
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    user_text = messages[0]["content"][0]["text"]
    assert "Ascending" in user_text
    # the facts packet is embedded as JSON
    assert json.dumps(_facts().to_dict(), indent=2) in user_text
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/test_franchise_writer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 4: Implement the writer**

```python
# src/sleeper_dynasty/llm/franchise_outlook_writer.py
"""LLM writer for the franchise-outlook blurb (mirrors gm_rating_blurb_writer)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import anthropic

from sleeper_dynasty.models.franchise_outlook import FranchiseFacts

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 400
_PERSONA_PATH = Path(__file__).with_name("franchise_outlook_persona.md")
_PERSONA_FALLBACK = (
    "You are a dynasty-fantasy analyst. Using ONLY the provided facts, write a "
    "one- to two-sentence franchise outlook leading with the competitive window. "
    "No markdown."
)


def load_franchise_persona() -> str:
    try:
        return _PERSONA_PATH.read_text().strip()
    except OSError:
        return _PERSONA_FALLBACK


def parse_franchise(text: str) -> dict[str, str]:
    return {"blurb": (text or "").strip()}


class FranchiseOutlookWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_franchise_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: FranchiseFacts) -> tuple[list[dict], list[dict]]:
        system = [{"type": "text", "text": self.persona,
                   "cache_control": {"type": "ephemeral"}}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the one- to two-sentence franchise outlook."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: FranchiseFacts) -> dict[str, str]:
        system, messages = self.build_request(facts)
        logger.info("Requesting franchise blurb from %s (owner %s)",
                    self.model, facts.owner_name)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages)
        return parse_franchise(resp.content[0].text)
```

> NOTE: confirm the persona `.md` is included in the package build (the GM persona file ships the
> same way — match whatever `MANIFEST.in` / `pyproject` package-data mechanism it uses, if any).
> The `_PERSONA_FALLBACK` keeps the writer functional even if the file isn't bundled.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/test_franchise_writer.py -v`
Expected: PASS — note these tests never call the network (`write` is not exercised).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/franchise_outlook_writer.py src/sleeper_dynasty/llm/franchise_outlook_persona.md tests/test_franchise_writer.py
git commit -m "feat(llm): franchise outlook writer + persona"
```

---

## Task 4: Incremental generator

Mirror `generate_owner_rating_blurbs`, but flat (single scope, keyed by uid).

**Files:**
- Create: `api/app/services/franchise_blurb_gen.py`
- Test: `api/tests/test_franchise_blurb_gen.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_franchise_blurb_gen.py
import asyncio

from app.services.franchise_blurb_gen import generate_franchise_blurbs
from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)


def _facts(uid):
    return FranchiseFacts(
        user_id=uid, owner_name=uid, team_name=None, window="Ascending",
        trajectory="t", overall_avg_age=24.0, roster_rank=1, roster_of=2,
        young_core=[], aging_risks=[], draft_capital_status="neutral",
        draft_capital_net=0.0, top_need=None, signature_trade=None)


class _FakeWriter:
    def __init__(self):
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return {"blurb": f"blurb for {facts.user_id}"}


def test_generates_and_skips_unchanged_by_hash():
    facts_by_owner = {"uA": _facts("uA"), "uB": _facts("uB")}
    writer = _FakeWriter()
    out = asyncio.run(generate_franchise_blurbs(
        facts_by_owner=facts_by_owner, prior_blurbs={}, writer=writer))
    assert out["uA"]["blurb"] == "blurb for uA"
    assert writer.calls == 2

    # Second run with matching prior hashes -> no new writer calls.
    writer2 = _FakeWriter()
    out2 = asyncio.run(generate_franchise_blurbs(
        facts_by_owner=facts_by_owner, prior_blurbs=out, writer=writer2))
    assert writer2.calls == 0
    assert out2["uA"]["blurb"] == "blurb for uA"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest api/tests/test_franchise_blurb_gen.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the generator**

```python
# api/app/services/franchise_blurb_gen.py
"""Incremental generation of per-owner franchise blurbs (mirrors blurb_gen)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sleeper_dynasty.models.franchise_outlook import (
    FranchiseFacts, franchise_facts_hash,
)

log = logging.getLogger(__name__)


async def generate_franchise_blurbs(
    *,
    facts_by_owner: dict[str, FranchiseFacts],
    prior_blurbs: dict[str, dict],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    pending: list[tuple[str, FranchiseFacts, str]] = []
    for uid, facts in facts_by_owner.items():
        h = franchise_facts_hash(facts)
        prior = prior_blurbs.get(uid)
        if prior and prior.get("facts_hash") == h:
            out[uid] = prior  # incremental skip
            continue
        pending.append((uid, facts, h))

    if not pending:
        return out

    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0

    async def _one(uid: str, facts: FranchiseFacts, h: str):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("franchise blurb failed for %s", uid)
                return
            out[uid] = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        done += 1
        if progress_cb is not None:
            await progress_cb("franchise_blurbs",
                              f"Writing franchise outlooks {done}/{len(pending)}")

    todo = pending
    for attempt in range(max(1, max_attempts)):
        if not todo:
            break
        if attempt > 0 and retry_delay > 0:
            await asyncio.sleep(retry_delay)
        await asyncio.gather(*(_one(u, f, h) for u, f, h in todo))
        todo = [(u, f, h) for (u, f, h) in pending if u not in out]

    if todo:
        log.error("%d franchise blurb(s) still missing after %d attempts",
                  len(todo), max_attempts)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest api/tests/test_franchise_blurb_gen.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/app/services/franchise_blurb_gen.py api/tests/test_franchise_blurb_gen.py
git commit -m "feat(api): incremental franchise blurb generator"
```

---

## Task 5: Persist + refresh stage

**Files:**
- Modify: `api/app/services/chain_cache.py`
- Modify: `api/app/services/grader.py`

- [ ] **Step 1: Add the cache field**

In `ChainCacheEntry` (after `roster_ranks` from Plan 1), add:

```python
    # uid -> {blurb, facts_hash, generated_at}
    franchise_blurbs: dict[str, dict[str, Any]] = field(default_factory=dict)
```

- [ ] **Step 2: Add the refresh stage in `grader.py`**

After the dynasty-outlook stage (Plan 1) and the existing `owner_blurbs` stage, add a
`franchise_blurbs` stage. It reuses `dynasty_outlooks`, `entry.owners`, `roster_ranks`, and a
best-trade-per-owner signature string. Place it just before `return entry`:

```python
        await progress_cb("franchise_blurbs", "Writing franchise outlooks")
        try:
            from app.services.aggregations import _format_assets_short
            from app.services.franchise_blurb_gen import generate_franchise_blurbs
            from sleeper_dynasty.engine.franchise_outlook import build_franchise_facts

            fr_writer = _franchise_writer
            if fr_writer is None:
                from sleeper_dynasty.llm.franchise_outlook_writer import (
                    FranchiseOutlookWriter,
                )
                fr_writer = FranchiseOutlookWriter()  # reads ANTHROPIC_API_KEY

            # Signature trade per owner = highest realized received_ktc.
            best_by_uid: dict[str, tuple[float, str]] = {}
            for rt in resolved_dicts:
                tx = rt["trade"]["transaction_id"]
                grade = grades.get(tx) or {}
                for uid, val in (grade.get("received_ktc") or {}).items():
                    v = float(val or 0)
                    if uid not in best_by_uid or v > best_by_uid[uid][0]:
                        my_side = (rt.get("sides") or {}).get(uid) or {}
                        sig = (f"received {_format_assets_short(my_side)} "
                               f"({'+' if v >= 0 else ''}{round(v)})")
                        best_by_uid[uid] = (v, sig)

            facts_by_owner = {}
            for uid, ol in dynasty_outlooks.items():
                owner = entry.owners.get(uid, {})
                facts_by_owner[uid] = build_franchise_facts(
                    user_id=uid,
                    owner_name=owner.get("owner_name") or uid,
                    team_name=owner.get("team_name"),
                    outlook=ol,
                    roster_rank=roster_ranks.get(uid),
                    signature_trade=(best_by_uid.get(uid) or (0, None))[1])

            prior_fr: dict = {}
            if cache_dir is not None:
                from app.services.chain_cache import ChainCache
                prev_fr = ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                prior_fr = prev_fr.franchise_blurbs if prev_fr else {}

            entry.franchise_blurbs = await generate_franchise_blurbs(
                facts_by_owner=facts_by_owner, prior_blurbs=prior_fr,
                writer=fr_writer, progress_cb=progress_cb)
        except Exception as e:  # never fail refresh on blurb errors
            log.exception("franchise blurb stage failed")
            entry.warnings.append(f"franchise blurbs skipped: {e}")
```

Also add a module-level test seam near the other writer seams (`_story_writer`, `_blurb_writer`):

```python
_franchise_writer = None  # test seam; defaults to FranchiseOutlookWriter()
```

> NOTE: confirm `resolved_dicts`, `grades`, and `cache_dir` are in scope at this point in `run`
> (they are used by the existing `stories` and `owner_blurbs` stages just above). Reuse the same
> variables — do not refetch. If `dynasty_outlooks`/`roster_ranks` (Plan 1) are local vars rather
> than already on `entry`, reference the locals.

- [ ] **Step 3: Smoke check**

Run: `pytest api/tests -q`
Expected: PASS (no network calls in tests; the new stage is only exercised at runtime).

- [ ] **Step 4: Commit**

```bash
git add api/app/services/chain_cache.py api/app/services/grader.py
git commit -m "feat(api): generate + persist franchise blurbs during refresh"
```

---

## Task 6: Expose `franchise_blurb` on the owner endpoint

**Files:**
- Modify: `api/app/models/owner.py`
- Modify: `api/app/services/owner_view.py`
- Test: `api/tests/test_owner_view_outlook.py`

- [ ] **Step 1: Write the failing test**

Append to `api/tests/test_owner_view_outlook.py`:

```python
def test_franchise_blurb_exposed_when_present():
    entry = _entry(
        franchise_blurbs={"uA": {"blurb": "Ascending and dangerous.",
                                 "facts_hash": "x", "generated_at": "t"}})
    resp = build_owner_detail(entry, "uA")
    assert resp.franchise_blurb == "Ascending and dangerous."


def test_franchise_blurb_absent_is_none():
    resp = build_owner_detail(_entry(), "uA")
    assert resp.franchise_blurb is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest api/tests/test_owner_view_outlook.py -v`
Expected: FAIL — field not present/populated.

- [ ] **Step 3: Add the Pydantic field**

In `api/app/models/owner.py`, add to `OwnerDetailResp`:

```python
    franchise_blurb: str | None = None
```

- [ ] **Step 4: Populate it in `build_owner_detail`**

Before the `return OwnerDetailResp(...)`, add:

```python
    franchise_blurb = (
        (entry.franchise_blurbs or {}).get(user_id, {}).get("blurb"))
```

And add to the constructor kwargs:

```python
        franchise_blurb=franchise_blurb,
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest api/tests/test_owner_view_outlook.py -v`
Expected: PASS.

- [ ] **Step 6: Full suites + typecheck**

Run: `pytest -q && pytest api/tests -q && cd web && npx tsc --noEmit`
Expected: all green. The Plan 2 hero band now renders real blurbs end-to-end.

- [ ] **Step 7: Commit**

```bash
git add api/app/models/owner.py api/app/services/owner_view.py api/tests/test_owner_view_outlook.py
git commit -m "feat(api): expose franchise_blurb on owner detail"
```

---

## Self-Review

**Spec coverage:**
- LLM franchise blurb grounded in outlook facts → Tasks 1–3. ✓
- Eager + incremental, cached, hash-skipped during refresh → Tasks 4, 5. ✓
- Graceful without `ANTHROPIC_API_KEY` (per-owner try/except + stage try/except) → Tasks 4, 5. ✓
- Exposed on `OwnerDetailResp.franchise_blurb`, rendered by Plan 2 hero → Task 6. ✓
- Signature-trade fact (best realized received deal) → Task 5. ✓

**Placeholder scan:** none. Two NOTE callouts (persona packaging, grader var scope) are
confirm-and-match against existing patterns, not unfilled work. Tests never hit the network (the
writer's `write` is faked in `generate_franchise_blurbs` tests and not invoked in writer tests).

**Type consistency:** `FranchiseFacts` fields are identical across Tasks 1/2/3/4/5. `parse_franchise`
returns `{"blurb": ...}`, consumed by `generate_franchise_blurbs` (`**result`) and read as
`["blurb"]` in `owner_view` (Task 6). The cache field `franchise_blurbs: dict[uid -> {blurb,
facts_hash, generated_at}]` matches what the generator writes and what `owner_view` reads. The
`franchise_blurb?` TS field already exists from Plan 2.
