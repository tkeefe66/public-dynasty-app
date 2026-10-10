"""Four-stage managed script contract. Provider data is never executable."""
from __future__ import annotations

import json
import logging
from importlib import resources

from pydantic import BaseModel, ConfigDict, Field

from sleeper_dynasty.engine.recap_video_claims import validate_script
from sleeper_dynasty.llm.managed import DeniedClient

log = logging.getLogger(__name__)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SpokenNumber(Strict):
    claim_id: str
    field: str
    exact: str
    spoken: str


class Segment(Strict):
    id: str
    owner_ids: list[str]
    matchup_ids: list[str]
    claim_ids: list[str]
    text: str = Field(min_length=1)
    spoken_numbers: list[SpokenNumber]


class Premise(Strict):
    premise: str
    punchline: str
    owner_ids: list[str]
    callback_reason: str = ""


class Script(Strict):
    article_digest: str
    opening: str = Field(min_length=1)
    closing: str = Field(min_length=1)
    segments: list[Segment] = Field(min_length=1)
    premises: list[Premise]


class Issue(Strict):
    code: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    evidence: str = Field(min_length=1)


class Checks(Strict):
    facts: bool
    article_agreement: bool
    coverage: bool
    spoken_numbers: bool
    premise_variety: bool


class Review(Strict):
    approved: bool
    issues: list[Issue]
    checked_segment_ids: list[str]
    checks: Checks


class ScriptHold(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("Script held: " + json.dumps(issues))


class RecapVideoWriter:
    def __init__(self, *, client=None, model="claude-sonnet-4-6", review_model="claude-sonnet-4-6", max_calls=4):
        if max_calls not in (2, 4):
            raise ValueError("Script requires draft/review with at most one repair/review")
        self.client = client if client is not None else DeniedClient()
        self.model, self.review_model, self.max_calls = model, review_model, max_calls
        self.prompt = resources.files("sleeper_dynasty.llm.prompts").joinpath("recap_video.md").read_text()

    def _call(self, stage, data):
        review = stage in (2, 4)
        schema = Review if review else Script
        name = "review_script" if review else "submit_script"
        instruction = ("Audit the WHOLE script, including opening/closing. Return every unresolved issue; "
            "audit semantic claims in jokes, unsupported medical/personal/causal statements, exact numbers, "
            "meaningful owner and matchup coverage, agreement with corrected published prose, and repeated "
            "premises. A boolean or ID inventory alone is insufficient. Check all categories and each segment."
            if review else "Write the complete structured show. On repair, fix all evidenced issues using only the original evidence.")
        log.info("Recap video script stage=%s model=%s", stage, self.model if stage == 1 else self.review_model)
        response = self.client.messages.create(model=self.model if stage == 1 else self.review_model,
            max_tokens=8192, system=self.prompt + "\n" + instruction,
            messages=[{"role": "user", "content": json.dumps(data, separators=(",", ":"))}],
            tools=[{"name": name, "description": instruction, "input_schema": schema.model_json_schema()}],
            tool_choice={"type": "tool", "name": name})
        blocks = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or len(blocks) != 1 or blocks[0].name != name:
            raise ScriptHold([{"code": "structured_response_missing", "stage": stage}])
        try:
            return schema.model_validate(blocks[0].input).model_dump()
        except ValueError as exc:
            raise ScriptHold([{"code": "structured_response_invalid", "stage": stage}]) from exc

    def write(self, claims, published_article, *, recent_premises=None):
        # Caller supplies only server-owned, compact published-selection history.
        evidence = {"claims": claims, "published_article": published_article,
                    "recent_premises": (recent_premises or [])[:6]}
        script = self._call(1, evidence)
        reviews = []
        for stage in (2, 4):
            issues = [{"code": e, "segment_id": "script", "quote": "validation", "evidence": e}
                      for e in validate_script(script, claims, published_article)]
            normalize = lambda value: " ".join(value.casefold().split())
            past = {normalize(p["premise"]) for episode in evidence["recent_premises"] for p in episode["premises"]}
            for premise in script["premises"]:
                if normalize(premise["premise"]) in past and not premise["callback_reason"].strip():
                    issues.append({"code": "repeated_premise", "segment_id": "script",
                        "quote": premise["premise"], "evidence": "Published premise repeated without intentional callback explanation"})
            verdict = self._call(stage, {**evidence, "script": script, "deterministic_issues": issues})
            expected = {"opening", "closing", *[s["id"] for s in script["segments"]]}
            if set(verdict["checked_segment_ids"]) != expected:
                raise ScriptHold([{"code": "review_incomplete"}])
            issues.extend(verdict["issues"])
            if not all(verdict["checks"].values()) or not verdict["approved"]:
                if not verdict["issues"]:
                    raise ScriptHold([{"code": "review_incomplete"}])
            reviews.append(verdict)
            if verdict["approved"] and all(verdict["checks"].values()) and not issues:
                return {**script, "reviews": reviews}
            if stage == self.max_calls:
                log.warning("Recap video script held after stage=%s issues=%s", stage, [i["code"] for i in issues])
                raise ScriptHold(issues)
            script = self._call(3, {**evidence, "script": script, "issues": issues})
        raise AssertionError("Unreachable bounded script contract")
