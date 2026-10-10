from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_recap_video_claims import snapshot, script_for


class Client:
    def __init__(self, outputs):
        self.outputs, self.requests, self.messages = iter(outputs), [], self

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use",
            name=request["tools"][0]["name"], input=next(self.outputs))])


def review(script, issues=None):
    return {"approved": not issues, "issues": issues or [],
            "checked_segment_ids": ["opening", *[s["id"] for s in script["segments"]], "closing"],
            "checks": {k: True for k in ("facts", "article_agreement", "coverage", "spoken_numbers", "premise_variety")}}


def test_bounded_repair_review_order_and_unresolved_hold():
    # Mutation: return repaired script before fresh review or silently attempt a fifth paid call.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter, ScriptHold
    claims = compile_claims(snapshot())
    script = script_for(claims)
    issue = {"code": "unsupported_personal", "segment_id": script["segments"][0]["id"],
             "quote": "invented anecdote", "evidence": "No source supports this anecdote"}
    client = Client([script, review(script, [issue]), script, review(script, [issue])])
    with pytest.raises(ScriptHold, match="unsupported_personal"):
        RecapVideoWriter(client=client).write(claims, {"digest": "published-revision-2", "markdown": "Published roast"})
    assert [r["tools"][0]["name"] for r in client.requests] == ["submit_script", "review_script", "submit_script", "review_script"]


def test_review_covers_every_segment_and_saved_article_context():
    # Mutation: approve from boolean alone; omit complete published article from reviewer.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter, ScriptHold
    claims = compile_claims(snapshot())
    script = script_for(claims)
    verdict = review(script)
    verdict["checked_segment_ids"].pop()
    client = Client([script, verdict])
    with pytest.raises(ScriptHold, match="review_incomplete"):
        RecapVideoWriter(client=client).write(claims, {"digest": "published-revision-2", "markdown": "Corrected published roast"})
    assert "Corrected published roast" in client.requests[1]["messages"][0]["content"]


def test_approved_complete_script_retains_numbers_and_prompt_contract():
    # Mutation: hard truncate longer scripts or inject raw multi-megabyte snapshots into prompts.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter
    claims = compile_claims(snapshot())
    script = script_for(claims)
    script["segments"][0]["text"] = "What a damned football league. " * 60
    client = Client([script, review(script)])
    result = RecapVideoWriter(client=client).write(claims, {"digest": "published-revision-2", "markdown": "Roast"})
    assert result["segments"][0]["text"] == script["segments"][0]["text"]
    prompt = client.requests[0]["system"]
    assert all(term in prompt for term in ("Cal Mercer", "AM-radio", "profanity", "callback", "not a hard"))


@pytest.mark.parametrize('max_calls', [2, 4])
def test_oversized_complete_script_uses_only_existing_repair_allowance(max_calls):
    # Mutation: truncate missing owners, ignore the paid envelope, or buy an extra repair.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter, ScriptHold
    claims = compile_claims(snapshot())
    script = script_for(claims)
    oversized = deepcopy(script)
    oversized['segments'][0]['text'] = 'What a damned football league. ' * 1000
    client = Client([oversized, review(oversized), script, review(script)])
    writer = RecapVideoWriter(client=client, max_calls=max_calls)
    if max_calls == 2:
        with pytest.raises(ScriptHold, match='narration_segment_exceeds_envelope'):
            writer.write(claims, {'digest': 'published-revision-2'})
    else:
        result = writer.write(claims, {'digest': 'published-revision-2'})
        assert result['segments'] == script['segments']
    assert len(client.requests) == max_calls


@pytest.mark.parametrize("code", ["article_disagreement", "unsupported_injury", "invented_anecdote", "meaningless_owner_coverage"])
def test_semantic_review_issues_hold_even_with_complete_ids(code):
    # Mutation: ignore review issues because deterministic ID coverage passes.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter, ScriptHold
    claims = compile_claims(snapshot())
    script = script_for(claims)
    verdict = review(script, [{"code": code, "segment_id": script["segments"][0]["id"],
        "quote": "Football has consequences.", "evidence": "Overlapping facts contradict corrected article or lack source."}])
    client = Client([script, verdict])
    with pytest.raises(ScriptHold, match=code):
        RecapVideoWriter(client=client, max_calls=2).write(claims, {"digest": "published-revision-2", "markdown": "Correction"})
    assert len(client.requests) == 2


def test_recycled_premise_holds_without_callback_reason():
    # Mutation: trust approval boolean despite an exact repeated premise without explanation.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter, ScriptHold
    claims = compile_claims(snapshot())
    script = script_for(claims)
    script["premises"] = [{"premise": "The score is a parking ticket", "punchline": "Pay up", "owner_ids": ["owner-1"]}]
    history = [{"episode_id": "last", "premises": script["premises"]}]
    client = Client([script, review(script)])
    with pytest.raises(ScriptHold, match="repeated_premise"):
        RecapVideoWriter(client=client, max_calls=2).write(claims, {"digest": "published-revision-2"}, recent_premises=history)


def test_successful_repair_requires_final_review_and_stops_at_four():
    # Mutation: skip final review or use draft model for repair outside immutable stage plan.
    from sleeper_dynasty.engine.recap_video_claims import compile_claims
    from sleeper_dynasty.llm.recap_video_writer import RecapVideoWriter
    claims = compile_claims(snapshot())
    script = script_for(claims)
    bad = deepcopy(script)
    bad["segments"].pop()
    client = Client([bad, review(bad), script, review(script)])
    result = RecapVideoWriter(client=client, model="draft", review_model="review").write(claims, {"digest": "published-revision-2"})
    assert result["segments"] == script["segments"]
    assert [r["model"] for r in client.requests] == ["draft", "review", "review", "review"]
    assert len(result["reviews"]) == 2
