> _Historical doc — paths/names have changed. Repo is now `Code Apps/public-dynasty` (GitHub `tkeefe66/public-dynasty-app`), Railway project **shimmering-nature**, live at https://ffbdynasty.com. Ignore stale refs to `sleeper-dynasty` / `sleeper-trade-grader` / `web-production-f949`._

# GM-Rating Blurb Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a one-paragraph, LLM-written, per-owner blurb at the bottom of each expanded GM-rating breakdown panel, explaining who the GM is and why their grade landed where it did.

**Architecture:** Mirror the trade-story pattern exactly — a pure engine facts-builder feeds an Opus writer with the brand persona; a refresh stage generates blurbs per scope (all-time + each season) with facts-hash incremental-skip, cached on `ChainCacheEntry`; the leaderboard response carries the scope-correct blurb; the frontend renders it under the explainer line.

**Tech Stack:** Python (engine + FastAPI), Anthropic SDK (`claude-opus-4-8`), Next.js/React/Tailwind frontend, pytest + vitest.

---

## File Structure

**New files**
- `src/sleeper_dynasty/models/gm_rating_blurb.py` — `OwnerRatingFacts` dataclass + `rating_facts_hash`.
- `src/sleeper_dynasty/engine/gm_rating_blurb.py` — `build_owner_rating_facts` + label maps.
- `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py` — `GmRatingBlurbWriter` + `parse_blurb` + `load_blurb_persona`.
- `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md` — the persona prompt.
- `api/app/services/blurb_gen.py` — `owner_rating_facts_by_scope` + `generate_owner_rating_blurbs`.
- Tests: `tests/test_gm_rating_blurb_facts.py`, `tests/test_gm_rating_blurb_writer.py`, `api/tests/test_blurb_gen.py`, `api/tests/test_chain_cache_blurbs.py`, `api/tests/test_leaderboard_blurb.py`.

**Modified files**
- `api/app/services/chain_cache.py` — add `owner_rating_blurbs` field.
- `api/app/services/grader.py` — add `_blurb_writer` hook + blurb refresh stage.
- `api/app/models/leaderboard.py` — add `GMRow.blurb`.
- `api/app/services/leaderboard.py` — attach blurb in `build_leaderboard`.
- `web/lib/types.ts` — add `GMRow.blurb`.
- `web/components/Leaderboard.tsx` — render the blurb.

---

## Task 1: OwnerRatingFacts model + hash

**Files:**
- Create: `src/sleeper_dynasty/models/gm_rating_blurb.py`
- Test: `tests/test_gm_rating_blurb_facts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gm_rating_blurb_facts.py
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash


def _facts(**over):
    base = dict(
        user_id="u1", owner_name="Bob", team_name="Sticky Icky",
        scope_label="career", rank=2, rating=1741,
        pillars=[
            {"label": "Outcomes", "weight": 0.45, "contribution": 148,
             "top_signals": [{"label": "Championships", "contribution": 55}],
             "worst_signals": []},
        ],
        championships=1, made_playoffs_rate=0.6, draft_capital_counted=False,
    )
    base.update(over)
    return OwnerRatingFacts(**base)


def test_to_dict_rounds_and_includes_scope():
    d = _facts().to_dict()
    assert d["scope_label"] == "career"
    assert d["rating"] == 1741
    assert d["pillars"][0]["label"] == "Outcomes"
    assert d["draft_capital_counted"] is False


def test_hash_is_stable_and_changes_on_rating():
    a = rating_facts_hash(_facts())
    b = rating_facts_hash(_facts())
    c = rating_facts_hash(_facts(rating=1800))
    assert a == b and a != c
    assert len(a) == 16
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gm_rating_blurb_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.models.gm_rating_blurb`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/models/gm_rating_blurb.py
"""Facts packet for the per-owner GM-rating blurb.

Contract between engine/gm_rating_blurb.py (builder) and
llm/gm_rating_blurb_writer.py (writer). The writer references ONLY these facts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OwnerRatingFacts:
    user_id: str
    owner_name: str
    team_name: str | None
    scope_label: str          # "career" | "the 2025 season"
    rank: int
    rating: int
    # each: {label, weight, contribution, top_signals[], worst_signals[]}
    pillars: list[dict[str, Any]] = field(default_factory=list)
    championships: int = 0
    made_playoffs_rate: float = 0.0
    draft_capital_counted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "owner_name": self.owner_name,
            "team_name": self.team_name,
            "scope_label": self.scope_label,
            "rank": self.rank,
            "rating": self.rating,
            "pillars": self.pillars,
            "championships": self.championships,
            "made_playoffs_rate": round(self.made_playoffs_rate, 2),
            "draft_capital_counted": self.draft_capital_counted,
        }


def rating_facts_hash(facts: OwnerRatingFacts) -> str:
    """Stable 16-char hash of the facts packet (used for incremental skip)."""
    blob = json.dumps(facts.to_dict(), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gm_rating_blurb_facts.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/models/gm_rating_blurb.py tests/test_gm_rating_blurb_facts.py
git commit -m "feat(engine): OwnerRatingFacts model + facts hash for GM-rating blurb"
```

---

## Task 2: build_owner_rating_facts (engine)

**Files:**
- Create: `src/sleeper_dynasty/engine/gm_rating_blurb.py`
- Test: `tests/test_gm_rating_blurb_facts.py` (append)

Input `pillars` is the per-scope breakdown dict exactly as produced by
`compute_gm_ratings` (and surfaced on `GMRow.pillars` via `.model_dump()`):
`{pillar_key: {"weight": float, "z": float, "contribution": int, "signals": {signal_key: {"raw": float, "z": float, "weight": float, "contribution": int}}}}`.

- [ ] **Step 1: Write the failing test (append to tests/test_gm_rating_blurb_facts.py)**

```python
from sleeper_dynasty.engine.gm_rating_blurb import build_owner_rating_facts


def _pillars():
    return {
        "outcomes": {"weight": 0.45, "z": 0.5, "contribution": 148, "signals": {
            "championships": {"raw": 1.0, "z": 1.2, "weight": 0.35, "contribution": 55},
            "playoff_depth": {"raw": 3.0, "z": 0.9, "weight": 0.25, "contribution": 52},
            "made_playoffs": {"raw": 0.6, "z": 0.0, "weight": 0.15, "contribution": 0},
            "final_seed": {"raw": 8.0, "z": 0.4, "weight": 0.15, "contribution": 21},
            "points_for_rank": {"raw": 7.0, "z": 0.3, "weight": 0.10, "contribution": 20},
        }},
        "trade_impact": {"weight": 0.30, "z": 0.4, "contribution": 102, "signals": {
            "playoff": {"raw": 200.0, "z": 1.0, "weight": 0.40, "contribution": 63},
            "regular": {"raw": 300.0, "z": 0.3, "weight": 0.30, "contribution": 22},
            "value": {"raw": 500.0, "z": 0.3, "weight": 0.22, "contribution": 21},
            "toilet": {"raw": 40.0, "z": 0.5, "weight": 0.08, "contribution": -5},
        }},
        "outlook": {"weight": 0.25, "z": -0.1, "contribution": -8, "signals": {
            "roster_value": {"raw": 50000.0, "z": 0.2, "weight": 0.40, "contribution": 13},
            "draft_capital": {"raw": 0.0, "z": 0.0, "weight": 0.35, "contribution": 0},
            "youth": {"raw": -27.0, "z": -0.8, "weight": 0.25, "contribution": -22},
        }},
    }


def test_build_facts_selects_top_and_worst_signals():
    f = build_owner_rating_facts(
        scope_label="career", owner_name="Bob", team_name="Icky",
        rank=2, rating=1741, pillars=_pillars(),
    )
    out = next(p for p in f.pillars if p["label"] == "Outcomes")
    # top signals are highest positive contributions, human-labeled, max 3
    assert out["top_signals"][0]["label"] == "Championships"
    assert out["top_signals"][0]["contribution"] == 55
    assert len(out["top_signals"]) <= 3
    # outlook worst signal is the negative Youth
    ol = next(p for p in f.pillars if p["label"] == "Outlook")
    assert ol["worst_signals"][0]["label"] == "Youth"
    assert ol["worst_signals"][0]["contribution"] == -22
    # headline facts
    assert f.championships == 1
    assert f.made_playoffs_rate == 0.6
    assert f.draft_capital_counted is False


def test_build_facts_season_scope_label():
    f = build_owner_rating_facts(
        scope_label="the 2025 season", owner_name="Bob", team_name=None,
        rank=1, rating=1900, pillars=_pillars(),
    )
    assert f.scope_label == "the 2025 season"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gm_rating_blurb_facts.py::test_build_facts_selects_top_and_worst_signals -v`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.engine.gm_rating_blurb`

- [ ] **Step 3: Write minimal implementation**

```python
# src/sleeper_dynasty/engine/gm_rating_blurb.py
"""Build an OwnerRatingFacts packet from a single owner's per-scope pillar
breakdown (the same numbers the /gm panel renders)."""

from __future__ import annotations

from typing import Any

from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts

PILLAR_LABELS = {
    "outcomes": "Outcomes",
    "trade_impact": "Trade Impact",
    "outlook": "Outlook",
}
SIGNAL_LABELS = {
    "championships": "Championships", "playoff_depth": "Playoff Depth",
    "made_playoffs": "Made Playoffs", "final_seed": "Final Seed",
    "points_for_rank": "Points-For Rank",
    "playoff": "Playoff Points", "regular": "Regular Season",
    "value": "Trade Value", "toilet": "Toilet Bowl",
    "roster_value": "Roster Value", "draft_capital": "Draft Capital",
    "youth": "Youth",
}
_PILLAR_ORDER = ["outcomes", "trade_impact", "outlook"]


def _labeled(signals: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"label": SIGNAL_LABELS.get(k, k), "contribution": int(s["contribution"])}
        for k, s in signals.items()
    ]


def build_owner_rating_facts(
    *,
    scope_label: str,
    owner_name: str,
    team_name: str | None,
    rank: int,
    rating: int,
    pillars: dict[str, dict[str, Any]],
) -> OwnerRatingFacts:
    pillar_facts: list[dict[str, Any]] = []
    for pk in _PILLAR_ORDER:
        p = pillars.get(pk)
        if not p:
            continue
        labeled = _labeled(p.get("signals", {}))
        top = sorted(
            (s for s in labeled if s["contribution"] > 0),
            key=lambda s: s["contribution"], reverse=True,
        )[:3]
        worst = sorted(
            (s for s in labeled if s["contribution"] < 0),
            key=lambda s: s["contribution"],
        )[:2]
        pillar_facts.append({
            "label": PILLAR_LABELS.get(pk, pk),
            "weight": round(float(p["weight"]), 2),
            "contribution": int(p["contribution"]),
            "top_signals": top,
            "worst_signals": worst,
        })

    out_sig = (pillars.get("outcomes") or {}).get("signals", {})
    champs = int((out_sig.get("championships") or {}).get("raw", 0))
    made_rate = float((out_sig.get("made_playoffs") or {}).get("raw", 0.0))

    return OwnerRatingFacts(
        user_id="",  # filled by the caller if needed; not used by the writer
        owner_name=owner_name,
        team_name=team_name,
        scope_label=scope_label,
        rank=rank,
        rating=rating,
        pillars=pillar_facts,
        championships=champs,
        made_playoffs_rate=made_rate,
        draft_capital_counted=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gm_rating_blurb_facts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/sleeper_dynasty/engine/gm_rating_blurb.py tests/test_gm_rating_blurb_facts.py
git commit -m "feat(engine): build_owner_rating_facts from per-scope pillar breakdown"
```

---

## Task 3: GmRatingBlurbWriter + persona

**Files:**
- Create: `src/sleeper_dynasty/llm/gm_rating_blurb_writer.py`
- Create: `src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md`
- Test: `tests/test_gm_rating_blurb_writer.py`

- [ ] **Step 1: Write the persona prompt**

```markdown
<!-- src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md -->
# The GM Profiler

You write a one-paragraph scouting take on a fantasy dynasty GM for ~10 friends
in one private league who already know each other and love trash talk. You
settle arguments with receipts.

## Hard rules
- Use ONLY facts in the FACTS PACKET. Never invent a number, a season, a player,
  a trade, or an event. If a fact is not in the packet, do not mention it.
- Output EXACTLY one paragraph, 3 to 4 sentences. No headings, no lists, no
  bold, no preamble, no sign-off.
- Reference `owner_name` (and `team_name` when it fits) from the packet, never
  the user_id.
- No em dashes. No "--". Use commas, periods, colons, or parentheses.
- Plain language only. Never use jargon: no "z-score", "KTC", "swing",
  "pillar", "signal", or stat acronyms. Say "market value" for Trade Value,
  "playoff production" for Playoff Points, and so on.
- If `draft_capital_counted` is false, do NOT claim draft capital helps or hurts
  the grade; it is not counted yet.

## What to write
- Lead with who this GM is, using `scope_label`: a `career` packet is a career
  profile; a season packet ("the 2025 season") is about that season only.
- Name the grade in context: their `rank` and `rating` (centered at 1500, so
  above 1500 is above the league's average GM, below is under it).
- Explain WHY the grade landed there: the pillar carrying them (highest
  `contribution`) and one or two `top_signals`, plus the biggest drag from
  `worst_signals` when present. Use plain descriptions of the signal labels.
- Close with the forward look from the Outlook pillar (roster value, youth):
  a win-now team, a young riser, a roster aging out, etc.

## Voice
- Sharp, candid, competitive, a little cocky. Spicy but grounded in the packet.
- Vary your cadence. Do not fall into a repeated shape across blurbs.
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_gm_rating_blurb_writer.py
from unittest.mock import MagicMock, patch

from sleeper_dynasty.llm.gm_rating_blurb_writer import (
    GmRatingBlurbWriter, load_blurb_persona, parse_blurb,
)
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts


def _facts():
    return OwnerRatingFacts(
        user_id="u1", owner_name="Bob", team_name="Sticky Icky",
        scope_label="career", rank=2, rating=1741,
        pillars=[{"label": "Outcomes", "weight": 0.45, "contribution": 148,
                  "top_signals": [{"label": "Championships", "contribution": 55}],
                  "worst_signals": []}],
        championships=1, made_playoffs_rate=0.6, draft_capital_counted=False,
    )


def test_persona_loads_with_hard_rules():
    p = load_blurb_persona()
    assert "ONLY" in p and "GM Profiler" in p


def test_parse_blurb_collapses_to_one_paragraph():
    out = parse_blurb("  Bob is a win-now killer.\n\nHis roster is aging.  ")
    assert out["blurb"] == "Bob is a win-now killer. His roster is aging."


def test_build_request_has_cached_persona_and_facts_only():
    w = GmRatingBlurbWriter(api_key="test")
    system, messages = w.build_request(_facts())
    assert system[0]["cache_control"]["type"] == "ephemeral"
    assert "GM Profiler" in str(system)
    assert "1741" in str(messages) and "use only" in str(messages).lower()


def test_write_calls_client_with_opus_and_parses():
    fake = MagicMock()
    fake.content = [MagicMock(text="Bob ranks 2nd.\n\nHe is win-now.")]
    client = MagicMock()
    client.messages.create.return_value = fake
    w = GmRatingBlurbWriter(api_key="test")
    with patch.object(w, "_client", client):
        out = w.write(_facts())
    assert out["blurb"] == "Bob ranks 2nd. He is win-now."
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == "claude-opus-4-8"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_gm_rating_blurb_writer.py -v`
Expected: FAIL with `ModuleNotFoundError: sleeper_dynasty.llm.gm_rating_blurb_writer`

- [ ] **Step 4: Write minimal implementation**

```python
# src/sleeper_dynasty/llm/gm_rating_blurb_writer.py
"""GmRatingBlurbWriter: turn an OwnerRatingFacts packet into one paragraph.

Mirrors TradeStoryWriter: a prompt-cached persona system block plus a user turn
carrying the facts JSON. The model uses only packet facts.
"""

from __future__ import annotations

import json
import logging
import re
from importlib import resources

import anthropic

from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts

logger = logging.getLogger(__name__)

_PROMPTS = "sleeper_dynasty.llm.prompts"
DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 512


def load_blurb_persona() -> str:
    return resources.files(_PROMPTS).joinpath("gm_rating_blurb_persona.md").read_text()


def parse_blurb(text: str) -> dict[str, str]:
    """Collapse the model output to a single clean paragraph."""
    collapsed = re.sub(r"\s+", " ", text.strip())
    return {"blurb": collapsed}


class GmRatingBlurbWriter:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 persona: str | None = None) -> None:
        self.model = model
        self.persona = persona or load_blurb_persona()
        self._client = anthropic.Anthropic(api_key=api_key)

    def build_request(self, facts: OwnerRatingFacts) -> tuple[list[dict], list[dict]]:
        system = [{"type": "text", "text": self.persona,
                   "cache_control": {"type": "ephemeral"}}]
        user = (
            "FACTS PACKET (use ONLY these facts):\n\n```json\n"
            + json.dumps(facts.to_dict(), indent=2)
            + "\n```\n\nWrite the one-paragraph profile."
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": user}]}]
        return system, messages

    def write(self, facts: OwnerRatingFacts) -> dict[str, str]:
        system, messages = self.build_request(facts)
        logger.info("Requesting GM blurb from %s (owner %s, %s)",
                    self.model, facts.owner_name, facts.scope_label)
        resp = self._client.messages.create(
            model=self.model, max_tokens=MAX_TOKENS,
            system=system, messages=messages,
        )
        return parse_blurb(resp.content[0].text)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_gm_rating_blurb_writer.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/gm_rating_blurb_writer.py src/sleeper_dynasty/llm/prompts/gm_rating_blurb_persona.md tests/test_gm_rating_blurb_writer.py
git commit -m "feat(llm): GmRatingBlurbWriter + persona for per-owner GM blurb"
```

---

## Task 4: ChainCacheEntry.owner_rating_blurbs field

**Files:**
- Modify: `api/app/services/chain_cache.py:40` (add field after `outlook_signals`)
- Test: `api/tests/test_chain_cache_blurbs.py`

No `SCHEMA_VERSION` bump: the field has a `default_factory`, so existing cache
files load fine (blurbs simply absent until the next refresh writes them).

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_chain_cache_blurbs.py
from pathlib import Path

from app.services.chain_cache import ChainCache, ChainCacheEntry


def _entry(**over):
    base = dict(
        league_id="L", chain=[], resolved_trades=[], grades={}, owners={},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={}, cached_at="now",
    )
    base.update(over)
    return ChainCacheEntry(**base)


def test_owner_rating_blurbs_round_trip(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    e = _entry(owner_rating_blurbs={
        "all": {"u1": {"blurb": "Bob rules.", "facts_hash": "h", "generated_at": "now"}},
    })
    c.write("L", e)
    back = c.read("L")
    assert back.owner_rating_blurbs["all"]["u1"]["blurb"] == "Bob rules."


def test_owner_rating_blurbs_defaults_empty(tmp_path: Path):
    c = ChainCache(cache_dir=tmp_path)
    c.write("L", _entry())
    assert c.read("L").owner_rating_blurbs == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_chain_cache_blurbs.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'owner_rating_blurbs'`

- [ ] **Step 3: Add the field**

In `api/app/services/chain_cache.py`, after line 40 (`outlook_signals = ...`):

```python
    # scope ("all"|str(year)) -> uid -> {blurb, facts_hash, generated_at}
    owner_rating_blurbs: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
```

(Place it before `schema_version: int = SCHEMA_VERSION`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_chain_cache_blurbs.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/chain_cache.py api/tests/test_chain_cache_blurbs.py
git commit -m "feat(cache): owner_rating_blurbs field on ChainCacheEntry"
```

---

## Task 5: generate_owner_rating_blurbs orchestration

**Files:**
- Create: `api/app/services/blurb_gen.py`
- Test: `api/tests/test_blurb_gen.py`

Decomposed so the orchestration is unit-testable with fake facts + a fake
writer (no `ChainCacheEntry` needed). `owner_rating_facts_by_scope` is the thin
glue over `build_leaderboard`, exercised in Task 6's live refresh.

- [ ] **Step 1: Write the failing test (orchestration only)**

```python
# api/tests/test_blurb_gen.py
import asyncio

from app.services.blurb_gen import generate_owner_rating_blurbs
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash


def _facts(uid, rating):
    return OwnerRatingFacts(
        user_id=uid, owner_name=uid, team_name=None, scope_label="career",
        rank=1, rating=rating, pillars=[], championships=0,
        made_playoffs_rate=0.0, draft_capital_counted=False,
    )


class _FakeWriter:
    def __init__(self):
        self.calls = 0

    def write(self, facts):
        self.calls += 1
        return {"blurb": f"{facts.owner_name}@{facts.rating}"}


def test_generates_and_skips_unchanged():
    w = _FakeWriter()
    facts_by_scope = {"all": {"u1": _facts("u1", 1700), "u2": _facts("u2", 1500)}}
    prior = {"all": {"u1": {"blurb": "old", "facts_hash": rating_facts_hash(_facts("u1", 1700)),
                            "generated_at": "t0"}}}
    out = asyncio.run(generate_owner_rating_blurbs(
        facts_by_scope=facts_by_scope, prior_blurbs=prior, writer=w))
    # u1 unchanged -> reused prior; u2 newly written
    assert out["all"]["u1"]["blurb"] == "old"
    assert out["all"]["u2"]["blurb"] == "u2@1500"
    assert w.calls == 1


def test_regenerates_when_rating_changes():
    w = _FakeWriter()
    facts_by_scope = {"all": {"u1": _facts("u1", 1800)}}
    prior = {"all": {"u1": {"blurb": "old", "facts_hash": rating_facts_hash(_facts("u1", 1700)),
                            "generated_at": "t0"}}}
    out = asyncio.run(generate_owner_rating_blurbs(
        facts_by_scope=facts_by_scope, prior_blurbs=prior, writer=w))
    assert out["all"]["u1"]["blurb"] == "u1@1800"
    assert w.calls == 1


def test_scope_is_ratable_needs_two_traders():
    from types import SimpleNamespace

    from app.services.blurb_gen import _scope_is_ratable

    assert _scope_is_ratable(
        [SimpleNamespace(trades=3), SimpleNamespace(trades=0)]) is False
    assert _scope_is_ratable(
        [SimpleNamespace(trades=1), SimpleNamespace(trades=2),
         SimpleNamespace(trades=0)]) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_blurb_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.blurb_gen`

- [ ] **Step 3: Write minimal implementation**

```python
# api/app/services/blurb_gen.py
"""Eager + incremental + concurrent per-owner GM-rating blurb generation.

Mirrors story_gen.generate_stories: build a facts packet per (scope, owner),
skip any whose facts hash matches the prior cached blurb, generate the rest
concurrently with bounded retry, never fail the refresh.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.models.leaderboard import GMRow
from app.services.chain_cache import ChainCacheEntry
from app.services.leaderboard import build_leaderboard
from sleeper_dynasty.engine.gm_rating_blurb import build_owner_rating_facts
from sleeper_dynasty.models.gm_rating_blurb import OwnerRatingFacts, rating_facts_hash

log = logging.getLogger(__name__)


def _scope_label(scope_key: str) -> str:
    return "career" if scope_key == "all" else f"the {scope_key} season"


def _scope_is_ratable(rows) -> bool:
    """Skip-silently rule: a scope is worth a blurb only when at least two owners
    actually traded in it. Otherwise everyone sits near the 1500 average and
    there is nothing to say (avoids thin LLM filler). All-time always qualifies."""
    return sum(1 for r in rows if r.trades > 0) >= 2


def _facts_from_row(scope_key: str, row: GMRow) -> OwnerRatingFacts:
    facts = build_owner_rating_facts(
        scope_label=_scope_label(scope_key),
        owner_name=row.owner.owner_name,
        team_name=row.owner.team_name,
        rank=row.rank,
        rating=row.rating,
        pillars={p: pb.model_dump() for p, pb in row.pillars.items()},
    )
    facts.user_id = row.user_id
    return facts


def owner_rating_facts_by_scope(
    entry: ChainCacheEntry,
) -> dict[str, dict[str, OwnerRatingFacts]]:
    """All-time + each season -> uid -> facts. Sparse scopes simply yield rows
    with whatever signals exist; empty leaderboards contribute nothing."""
    seasons = sorted({int(s) for s in entry.league_season_by_id.values()})
    scopes: list[str] = ["all"] + [str(s) for s in seasons]
    out: dict[str, dict[str, OwnerRatingFacts]] = {}
    for scope_key in scopes:
        year: Any = "all" if scope_key == "all" else int(scope_key)
        resp = build_leaderboard(entry, year=year, prev_ratings={})
        if not _scope_is_ratable(resp.rows):
            continue  # skip silently: too few traders to say anything real
        rows = {r.user_id: _facts_from_row(scope_key, r) for r in resp.rows}
        if rows:
            out[scope_key] = rows
    return out


async def generate_owner_rating_blurbs(
    *,
    facts_by_scope: dict[str, dict[str, OwnerRatingFacts]],
    prior_blurbs: dict[str, dict[str, dict]],
    writer,
    max_concurrency: int = 3,
    progress_cb=None,
    max_attempts: int = 3,
    retry_delay: float = 4.0,
) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    pending: list[tuple[str, str, OwnerRatingFacts, str]] = []

    for scope_key, owners in facts_by_scope.items():
        out.setdefault(scope_key, {})
        for uid, facts in owners.items():
            h = rating_facts_hash(facts)
            prior = (prior_blurbs.get(scope_key) or {}).get(uid)
            if prior and prior.get("facts_hash") == h:
                out[scope_key][uid] = prior  # incremental skip
                continue
            pending.append((scope_key, uid, facts, h))

    if not pending:
        return out

    sem = asyncio.Semaphore(max(1, max_concurrency))
    done = 0

    async def _one(scope_key: str, uid: str, facts: OwnerRatingFacts, h: str):
        nonlocal done
        async with sem:
            try:
                result = await asyncio.to_thread(writer.write, facts)
            except Exception:
                log.exception("GM blurb generation failed for %s/%s", scope_key, uid)
                return
            out[scope_key][uid] = {
                **result, "facts_hash": h,
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        done += 1
        if progress_cb is not None:
            await progress_cb("owner_blurbs",
                              f"Writing GM profiles {done}/{len(pending)}")

    todo = pending
    for attempt in range(max(1, max_attempts)):
        if not todo:
            break
        if attempt > 0:
            log.warning("retrying %d GM blurb(s), round %d/%d",
                        len(todo), attempt + 1, max_attempts)
            if retry_delay > 0:
                await asyncio.sleep(retry_delay)
        await asyncio.gather(*(_one(s, u, f, h) for s, u, f, h in todo))
        todo = [(s, u, f, h) for (s, u, f, h) in pending if u not in out.get(s, {})]

    if todo:
        log.error("%d GM blurb(s) still missing after %d attempts",
                  len(todo), max_attempts)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest api/tests/test_blurb_gen.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add api/app/services/blurb_gen.py api/tests/test_blurb_gen.py
git commit -m "feat(api): per-scope GM blurb orchestration (incremental + concurrent)"
```

---

## Task 6: Wire the blurb stage into refresh

**Files:**
- Modify: `api/app/services/grader.py` (method signature `_blurb_writer=None` near line 61; new stage after the entry is built near line 227)

- [ ] **Step 1: Add the `_blurb_writer` hook to the method signature**

In `grader.py`, find the line `_story_writer=None,` (~line 61) and add directly after it:

```python
        _blurb_writer=None,
```

- [ ] **Step 2: Add the blurb stage after entry construction**

In `grader.py`, the entry is built at `entry = ChainCacheEntry(...)` ending around line 227, then `return entry` (line 228). Replace `return entry` with:

```python
        await progress_cb("owner_blurbs", "Writing GM profiles")
        try:
            from app.services.blurb_gen import (
                generate_owner_rating_blurbs, owner_rating_facts_by_scope,
            )
            blurb_writer = _blurb_writer
            if blurb_writer is None:
                from sleeper_dynasty.llm.gm_rating_blurb_writer import GmRatingBlurbWriter
                blurb_writer = GmRatingBlurbWriter()  # reads ANTHROPIC_API_KEY
            prior_blurbs: dict = {}
            if cache_dir is not None:
                from app.services.chain_cache import ChainCache
                prev_b = ChainCache(cache_dir=cache_dir).read(
                    current_league_id, max_age_seconds=10 ** 9)
                prior_blurbs = prev_b.owner_rating_blurbs if prev_b else {}
            facts_by_scope = owner_rating_facts_by_scope(entry)
            entry.owner_rating_blurbs = await generate_owner_rating_blurbs(
                facts_by_scope=facts_by_scope, prior_blurbs=prior_blurbs,
                writer=blurb_writer, progress_cb=progress_cb,
            )
        except Exception as e:  # never fail refresh on blurb errors
            log.exception("owner rating blurb stage failed")
            entry.warnings.append(f"owner blurbs skipped: {e}")

        return entry
```

- [ ] **Step 3: Verify the engine + api suites still pass**

Run: `pytest -q && pytest api/tests -q`
Expected: PASS (no regressions; blurb stage is import-guarded and never raises)

- [ ] **Step 4: Commit**

```bash
git add api/app/services/grader.py
git commit -m "feat(api): generate per-owner GM blurbs during refresh"
```

---

## Task 7: Expose blurb on GMRow + leaderboard

**Files:**
- Modify: `api/app/models/leaderboard.py:35` (add field to `GMRow`)
- Modify: `api/app/services/leaderboard.py` (compute `scope_key` before the loop; attach blurb)
- Test: `api/tests/test_leaderboard_blurb.py`

- [ ] **Step 1: Write the failing test**

```python
# api/tests/test_leaderboard_blurb.py
from app.services.chain_cache import ChainCacheEntry
from app.services.leaderboard import build_leaderboard


def _entry():
    # Minimal single-owner entry; no trades -> trade_impact zero, but a row exists.
    return ChainCacheEntry(
        league_id="L", chain=[], resolved_trades=[], grades={},
        owners={"u1": {"owner_name": "Bob", "team_name": "Icky"}},
        playoff_weeks_by_league={}, roster_to_user_by_league={},
        league_name_by_id={}, league_season_by_id={"L": 2025}, cached_at="now",
        outcome_signals={"u1": {}}, outlook_signals={"u1": {}},
        owner_rating_blurbs={"all": {"u1": {"blurb": "Bob rules.",
                                            "facts_hash": "h", "generated_at": "now"}}},
    )


def test_blurb_attached_for_scope():
    resp = build_leaderboard(_entry(), year="all", prev_ratings={})
    row = next(r for r in resp.rows if r.user_id == "u1")
    assert row.blurb == "Bob rules."


def test_blurb_none_when_missing_for_scope():
    # owner_rating_blurbs only has the "all" scope; the 2025 scope has no entry,
    # so the row's blurb is None.
    resp = build_leaderboard(_entry(), year=2025, prev_ratings={})
    row = next(r for r in resp.rows if r.user_id == "u1")
    assert row.blurb is None
```

`_aggregate_owner_rows` seeds a row for every owner in `entry.owners`
(`{uid: _blank(uid) for uid in entry.owners}`), so `u1` always appears even with
no trades — the `next(...)` lookups never raise.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest api/tests/test_leaderboard_blurb.py -v`
Expected: FAIL — `GMRow` has no `blurb` (AttributeError / validation), or `blurb` is unset.

- [ ] **Step 3: Add the `GMRow.blurb` field**

In `api/app/models/leaderboard.py`, in `GMRow`, after `production_toilet: float = 0.0`:

```python
    blurb: str | None = None   # LLM-written per-scope profile
```

- [ ] **Step 4: Attach the blurb in build_leaderboard**

In `api/app/services/leaderboard.py`, compute the scope key BEFORE the row loop
(replace the `scope: str = ...` line near the end and move it up). Right after
`out_rows: list[GMRow] = []` (line 80), add:

```python
    scope_key = "all" if year == "all" else str(year)
    blurbs_for_scope = (entry.owner_rating_blurbs or {}).get(scope_key, {})
```

Then in the `GMRow(...)` construction add:

```python
                blurb=(blurbs_for_scope.get(uid) or {}).get("blurb"),
```

And change the final return to reuse `scope_key`:

```python
    return LeaderboardResp(
        league_id=entry.league_id,
        scope=scope_key,
        rows=out_rows,
        generated_at=entry.cached_at,
    )
```

(Remove the now-duplicate `scope: str = ...` line.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest api/tests/test_leaderboard_blurb.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add api/app/models/leaderboard.py api/app/services/leaderboard.py api/tests/test_leaderboard_blurb.py
git commit -m "feat(api): expose per-scope GM blurb on the leaderboard row"
```

---

## Task 8: Frontend render

**Files:**
- Modify: `web/lib/types.ts` (add `blurb` to `GMRow`)
- Modify: `web/components/Leaderboard.tsx` (render blurb in the expanded panel)

- [ ] **Step 1: Add `blurb` to the frontend GMRow type**

In `web/lib/types.ts`, in `interface GMRow`, after `production_toilet: number;`:

```typescript
  blurb?: string | null;
```

- [ ] **Step 2: Render the blurb under the explainer line**

In `web/components/Leaderboard.tsx`, inside the expanded panel, the explainer
`<div>` ("Every point is league-relative…") is the last child of the panel.
Immediately AFTER that explainer `</div>`, add:

```tsx
            {r.blurb && (
              <p className="mt-3 border-t border-divider pt-3 font-sans text-[12.5px] leading-relaxed text-ink">
                {r.blurb}
              </p>
            )}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npx tsc --noEmit 2>&1 | grep -v "dev/loading"`
Expected: no errors from `components/Leaderboard.tsx` or `lib/types.ts`

- [ ] **Step 4: Commit**

```bash
git add web/lib/types.ts web/components/Leaderboard.tsx
git commit -m "feat(web): render the per-owner GM blurb in the breakdown panel"
```

---

## Task 9: Live verification + deploy

**Files:** none (verification + deploy)

- [ ] **Step 1: Full test suites green**

Run: `pytest -q && pytest api/tests -q && cd web && npm run test 2>&1 | tail -5`
Expected: all pass.

- [ ] **Step 2: Local refresh to generate blurbs**

With `ANTHROPIC_API_KEY` set and both dev servers running, trigger a refresh:

Run: `curl -N "http://localhost:8000/api/league/9000000000000000001/refresh" | tail -5`
Expected: SSE stream ends with a "done"/completion event; logs show "Writing GM profiles N/M".

- [ ] **Step 3: Confirm the blurb is in the leaderboard payload**

Run: `curl -s "http://localhost:8000/api/league/9000000000000000001/leaderboard?year=all" | python3 -c "import sys,json; rows=json.load(sys.stdin)['rows']; print(rows[0]['owner']['owner_name'], '->', (rows[0].get('blurb') or '')[:120])"`
Expected: a non-empty one-paragraph blurb for the top owner.

- [ ] **Step 4: Visual check via Playwright**

Drive `http://localhost:3000/league/9000000000000000001?tab=gm`, expand the top
row, screenshot, and confirm the blurb renders under the explainer line in sans
prose at desktop and mobile widths (reuse the `gm-real.mjs` harness pattern from
the prior session).

- [ ] **Step 5: Deploy**

Per `railway-deploy` skill: changes touch BOTH `api/` (engine, services) and
`web/`, so redeploy BOTH services.

```bash
railway up --service api --detach -m "GM-rating per-owner blurb"
railway up --service web --detach -m "GM-rating per-owner blurb"
```

Poll each: `railway deployment list --service <svc> --limit 1 --json` -> `.status` == SUCCESS.
Verify: `curl -s https://web-production-f949.up.railway.app/api/health` -> `{"status":"ok"}`.

Note: prod blurbs populate on the next prod refresh (auto-refresh scheduler or a
manual `/refresh`); the field defaults empty until then, so the panel degrades
gracefully.

- [ ] **Step 6: Commit any verification harness cleanup (if added) and finish**

```bash
git add -A && git commit -m "chore: verify GM blurb end-to-end" || true
```

---

## Notes for the implementer

- **Never break refresh.** The blurb stage is wrapped in try/except and only
  appends a warning on failure, exactly like the trade-story stage. Missing
  `ANTHROPIC_API_KEY` makes `GmRatingBlurbWriter()` construction succeed but
  `write()` raise at call time; the per-owner `_one` catch swallows it and the
  refresh still completes with blurbs absent.
- **Cost:** first warm refresh writes ~all (scope × owner) blurbs (~60). Every
  refresh after only regenerates owners/scopes whose rounded numbers changed
  (live season + all-time in steady state); completed seasons skip.
- **Scope correctness is automatic on the frontend:** changing the year tab
  reloads the leaderboard for that scope, so `r.blurb` always matches the
  visible numbers.
- **DRY:** the engine label maps (`PILLAR_LABELS` / `SIGNAL_LABELS`) intentionally
  mirror the frontend constants in `Leaderboard.tsx`; keep them in sync if labels
  ever change.
```
