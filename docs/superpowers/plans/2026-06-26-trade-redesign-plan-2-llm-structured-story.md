# Trade Redesign — Plan 2: LLM Structured Story

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the trade-story LLM output from a single paragraph `body` to a **structured** `{verdict, lede, beats[]}` (scannable headline + one lede sentence + 2–4 bullet beats), surfaced on the API, so Plan 3's ESPN hero can render it.

**Architecture:** Keep one Haiku call. The persona emits a headline line, then a lede sentence, then bulleted beats. `parse_story` splits that into `{verdict, lede, beats, body}` — `body` is kept as a back-compat fallback (lede + beats joined) so stories cached before this change still render. The existing sanitize/repair/validation pipeline runs over verdict + lede + each beat. Bump `STORY_PROMPT_VERSION` to regenerate every cached story into the new shape.

**Tech Stack:** Python 3.11, pytest, Anthropic SDK (Haiku), FastAPI/Pydantic.

## Global Constraints

- LLM output is **structured**: `verdict` (headline, 5–8 words), `lede` (one sentence), `beats` (2–4 short grounded sentences). The engine still owns all numbers; the LLM never emits the callout figures.
- **Back-compat:** `parse_story` must degrade gracefully on output with no bullets (old format) → `verdict` = first line, `lede` = the prose, `beats` = `[]`. Stories cached before this change (which have only `verdict`/`body`) must still deserialize and render — every new field defaults (`lede=""`, `beats=[]`).
- The deterministic safeguards stay: `sanitize_prose` (KTC ban) + `repair_prose` (dashes) + `tidy_headline` apply to verdict, lede, and each beat; `find_violations` (direction reversal / epithet / headline length) runs over verdict + the combined lede+beats prose; the regenerate-on-violation loop in `story_gen` is preserved.
- Bump `STORY_PROMPT_VERSION` "4" → "5" (a prompt/shape change the facts-hash won't otherwise pick up). One-time regen of all stories on next refresh.
- Never let "KTC" or an em dash reach the page; never let a reversed direction or bare positional epithet ship.
- Run engine tests from repo root with `.venv/bin/python -m pytest`; API tests from `api/` with `../.venv/bin/python -m pytest`. Commit after each task. Branch: `trade-redesign`.

---

### Task 1: `parse_story` → structured; writer sanitizes all parts

**Files:**
- Modify: `src/sleeper_dynasty/llm/trade_story_writer.py` (`parse_story` ~51-66, `write` ~88-101)
- Test: `tests/test_trade_story_writer.py`

**Interfaces:**
- Produces: `parse_story(text) -> {"verdict": str, "lede": str, "beats": list[str], "body": str}`. `write(facts)` returns the same keys plus `_usage`, with `verdict`/`lede`/each `beat`/`body` sanitized+repaired and `verdict` tidied.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_trade_story_writer.py`:

```python
from sleeper_dynasty.llm.trade_story_writer import parse_story


def test_parse_story_structured_headline_lede_beats():
    raw = (
        "Mikey robbed Tom\n\n"
        "Tom flipped a future RB1 for a pick that evaporated.\n\n"
        "- Bijan became a workhorse: 705 points for Mikey.\n"
        "- Chubb got dropped before he paid off.\n"
        "- The market gives Mikey a 9,000-point edge today.\n"
    )
    out = parse_story(raw)
    assert out["verdict"] == "Mikey robbed Tom"
    assert out["lede"] == "Tom flipped a future RB1 for a pick that evaporated."
    assert out["beats"] == [
        "Bijan became a workhorse: 705 points for Mikey.",
        "Chubb got dropped before he paid off.",
        "The market gives Mikey a 9,000-point edge today.",
    ]
    # body is a readable fallback: lede + beats
    assert "Bijan became a workhorse" in out["body"]
    assert out["body"].startswith("Tom flipped a future RB1")


def test_parse_story_backcompat_no_bullets():
    # Old shape (headline + paragraph, no bullets): degrade gracefully.
    raw = "Mikey robbed Tom\n\nThree months later it is not close. Receipts."
    out = parse_story(raw)
    assert out["verdict"] == "Mikey robbed Tom"
    assert out["beats"] == []
    assert out["lede"] == "Three months later it is not close. Receipts."
    assert out["body"] == "Three months later it is not close. Receipts."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py -k "structured or backcompat" -v`
Expected: FAIL — `KeyError: 'lede'` (parse_story doesn't return lede/beats yet).

- [ ] **Step 3: Rewrite `parse_story`**

Replace the body of `parse_story` in `src/sleeper_dynasty/llm/trade_story_writer.py`:

```python
_BULLETS = ("- ", "* ", "• ", "› ")


def parse_story(text: str) -> dict:
    """Split raw model output into {verdict, lede, beats, body}.

    Verdict = first non-empty line (markdown bold stripped). The remainder is
    split into bullet lines (beats) and non-bullet prose (the lede). `body` is a
    readable fallback (lede then beats) for stories rendered before the
    structured shape existed. Degrades to lede-only when no bullets are present.
    """
    lines = [ln.rstrip() for ln in text.strip().splitlines()]
    verdict = ""
    rest_start = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            verdict = ln.strip().strip("*").strip()
            rest_start = i + 1
            break
    beats: list[str] = []
    lede_parts: list[str] = []
    for ln in lines[rest_start:]:
        s = ln.strip()
        if not s:
            continue
        if s[:2] in _BULLETS:
            beats.append(s[2:].strip())
        else:
            lede_parts.append(s)
    lede = " ".join(lede_parts).strip()
    body = "\n".join(([lede] if lede else []) + beats).strip()
    return {"verdict": verdict, "lede": lede, "beats": beats, "body": body}
```

- [ ] **Step 4: Sanitize all parts in `write`**

In `write`, replace the sanitize block with:

```python
        result = parse_story(resp.content[0].text)
        # Sanitize banned jargon, then apply always-safe repairs (dashes, headline
        # punctuation/markdown) to every rendered part. Semantic checks happen in
        # story_gen, which can regenerate; these transforms need no regeneration.
        result["verdict"] = tidy_headline(repair_prose(sanitize_prose(result["verdict"])))
        result["lede"] = repair_prose(sanitize_prose(result.get("lede", "")))
        result["beats"] = [repair_prose(sanitize_prose(b)) for b in result.get("beats", [])]
        result["body"] = repair_prose(sanitize_prose(result["body"]))
        result["_usage"] = usage_dict(resp.usage)
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py -v`
Expected: PASS (new + existing — the existing `test_write_calls_client_and_parses` still works because verdict is still the first line; if an existing test asserted on `body` as the full paragraph, confirm it still holds since `body` now = lede when no bullets).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/trade_story_writer.py tests/test_trade_story_writer.py
git commit -m "feat(story): parse structured verdict/lede/beats from the writer"
```

---

### Task 2: Persona rewrite + prompt-version bump

**Files:**
- Modify: `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`
- Modify: `api/app/services/story_gen.py` (`STORY_PROMPT_VERSION` :38)
- Test: `tests/test_trade_story_writer.py` (persona-shape assertion)

**Interfaces:**
- Produces: a persona that instructs the headline + lede + 2–4 bullet beats structure, and `STORY_PROMPT_VERSION == "5"`.

- [ ] **Step 1: Write the failing test**

```python
from sleeper_dynasty.llm.trade_story_writer import load_persona


def test_persona_instructs_structured_output():
    p = load_persona()
    assert "lede" in p.lower()
    assert "beat" in p.lower()
    # the output contract still bans em dashes and KTC
    assert "em dash" in p.lower() or "—" in p
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py::test_persona_instructs_structured_output -v`
Expected: FAIL (persona has no "lede"/"beat" instruction yet).

- [ ] **Step 3: Rewrite the persona output contract**

In `src/sleeper_dynasty/llm/prompts/trade_story_persona.md`, replace the output-format section (the rule block that currently says "Output exactly: one HEADLINE line, then a blank line, then 1-2 short paragraphs of body") with:

```markdown
- Output EXACTLY this structure, nothing else:
  1. One HEADLINE line — 5-8 words, names the winner (or implies a draw when
     `winner_user_id` is null). A title, not a sentence. No period at the end.
  2. A blank line, then one LEDE sentence — the single sharpest summary of the
     trade (who, what, the turn).
  3. A blank line, then 2-4 BEAT lines, each starting with "- ", each a single
     grounded sentence carrying one vivid fact (a season-high, a flip, a drop, a
     decisive start, the value-vs-points tension). No sub-bullets, no paragraphs.
- No headings, no preamble, no labels (do not write "HEADLINE:" or "LEDE:").
- No em dashes anywhere (headline, lede, or beats). No "--". Use commas, periods,
  colons, or parentheses.
```

Keep every other section of the persona unchanged (trade-direction rules, the
fits/breaks tilt section, the flip-not-flop rules, the no-KTC rule, etc.) — they
still bind each beat.

- [ ] **Step 4: Bump the prompt version**

In `api/app/services/story_gen.py`, update the version + add a log line:

```python
# v4: per-side received_summary + deterministic this_trade_tilt / fits_career_tilt ...
# v5: structured output — verdict + lede + 2-4 bullet beats (was a paragraph body).
STORY_PROMPT_VERSION = "5"
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_trade_story_writer.py -v`
Expected: PASS (the new persona test + existing persona tests; the existing `test_persona_includes_given_summary_instruction` etc. still pass because those sections are untouched).

- [ ] **Step 6: Commit**

```bash
git add src/sleeper_dynasty/llm/prompts/trade_story_persona.md api/app/services/story_gen.py
git commit -m "feat(story): structured persona (headline/lede/beats) + bump version to 5"
```

---

### Task 3: Validate + cache lede/beats; surface on the API

**Files:**
- Modify: `api/app/services/story_gen.py` (`_one`, the `find_violations` call + cached dict)
- Modify: `api/app/models/trade.py` (`TradeStory` model :77-79)
- Modify: `api/app/services/trade_view.py` (story assembly :302-307)
- Test: `api/tests/test_story_gen.py`, `api/tests/test_trade_view_story.py`

**Interfaces:**
- Consumes: `writer.write` returning `{verdict, lede, beats, body, _usage}` (Task 1).
- Produces: cached story dict includes `lede` + `beats`; `find_violations` runs over verdict + combined lede/beats prose; API `TradeStory` model carries `lede: str = ""` and `beats: list[str] = []`, populated in `trade_view`.

- [ ] **Step 1: Write the failing tests**

In `api/tests/test_story_gen.py`, extend the fake writer to return structured output and assert it's cached and validated over the combined prose. Add:

```python
def test_structured_story_is_cached_with_lede_and_beats():
    class StructuredWriter(FakeWriter):
        def write(self, facts):
            self.calls += 1
            return {"verdict": f"V {facts.trade_id}", "lede": "L",
                    "beats": ["b1", "b2"], "body": "L\nb1\nb2"}

    writer = StructuredWriter()
    resolved = [_rt("t1")]
    grades = {"t1": {"snapshot_value_swing": {"u_mike": 900.0, "u_tom": -900.0}}}
    stories, _ = asyncio.run(generate_stories(
        resolved=resolved, grades=grades, supporting=_supporting(),
        prior_stories={}, writer=writer, max_concurrency=4,
    ))
    assert stories["t1"]["lede"] == "L"
    assert stories["t1"]["beats"] == ["b1", "b2"]
```

In `api/tests/test_trade_view_story.py`, assert the API `TradeStory` carries lede/beats when the cached entry has them. (Follow that file's existing fixture for building an entry with `trade_stories`; set the story dict to include `lede` and `beats`, then assert `resp.story.lede` and `resp.story.beats`.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_story_gen.py::test_structured_story_is_cached_with_lede_and_beats tests/test_trade_view_story.py -v`
Expected: FAIL — story_gen validation reads `result.get("body")` only (beats not in cache assertion fails) and/or `TradeStory` has no `lede`/`beats`.

- [ ] **Step 3: Validate over combined prose + cache lede/beats**

In `api/app/services/story_gen.py`, `_one`, change the violation check to run over verdict + lede + beats. Find the existing `find_violations(result.get("verdict", ""), result.get("body", ""), facts)` call and replace with:

```python
            # Validate over verdict + the full rendered prose (lede + beats).
            _prose = "\n".join(
                [result.get("lede", "")] + (result.get("beats") or [])
            ).strip() or result.get("body", "")
            violations = find_violations(
                result.get("verdict", ""), _prose, facts)
```

The cached `story = {**result, "facts_hash": h, "generated_at": ...}` already
carries `lede`/`beats` because they're in `result` — no change needed there.

- [ ] **Step 4: Add lede/beats to the API model + passthrough**

In `api/app/models/trade.py`, `TradeStory`:

```python
class TradeStory(BaseModel):
    verdict: str
    lede: str = ""
    beats: list[str] = []
    body: str
```

(keep the rest of the model, e.g. `generated_at`, unchanged.)

In `api/app/services/trade_view.py` (story assembly ~302-307):

```python
        TradeStory(verdict=raw_story.get("verdict", ""),
                   lede=raw_story.get("lede", ""),
                   beats=raw_story.get("beats", []) or [],
                   body=raw_story.get("body", ""),
                   generated_at=raw_story.get("generated_at"))
```

- [ ] **Step 5: Run tests**

Run: `cd api && ../.venv/bin/python -m pytest tests/test_story_gen.py tests/test_trade_view_story.py -v`
Expected: PASS (new + existing). Existing story_gen tests that return `{"verdict","body"}` still pass: `_prose` falls back to `body`, and a missing `beats` key yields `[]`.

- [ ] **Step 6: Commit**

```bash
git add api/app/services/story_gen.py api/app/models/trade.py api/app/services/trade_view.py api/tests/test_story_gen.py api/tests/test_trade_view_story.py
git commit -m "feat(api): validate+cache structured story; surface lede/beats"
```

---

## Self-Review

**Spec coverage:** structured LLM output (verdict/lede/beats) → Tasks 1+2; parse + sanitize all parts → Task 1; persona rewrite + version bump → Task 2; validation over combined prose, cache, API surfacing → Task 3; back-compat (defaults + body fallback) → Tasks 1 & 3. FE rendering of lede/beats is **Plan 3** (out of scope). The `find_violations` signature is intentionally unchanged (verdict, prose, facts) — Task 3 feeds it the combined prose, avoiding churn to the validated, working validator.

**Placeholder scan:** Task 3 Step 1's second test says "follow that file's existing fixture" rather than pasting an entry-construction fixture — acceptable because the assertion (`resp.story.lede`/`.beats`) is concrete and the fixture is the file's established pattern; the implementer must not invent a new one. No TBD/TODO.

**Type consistency:** `parse_story`/`write` return `{verdict, lede: str, beats: list[str], body}` across Tasks 1/3; the cached dict carries the same; `TradeStory` model fields match (`lede: str`, `beats: list[str]`); `_prose` is a `str` fed to `find_violations(str, str, facts)`. Consistent.

**Rollout:** `STORY_PROMPT_VERSION` 4→5 regenerates all stories into the structured shape on next refresh (Haiku cost, one-time). Old cached stories (no lede/beats) deserialize via defaults and render via `body` until regen. Deploy happens with Plan 3.
