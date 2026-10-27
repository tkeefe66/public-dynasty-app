"""Receipt-bound, separately approved Analyst repair; no live provider calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services.generation import administration
from app.services.generation.models import (
    GenerationAudit,
    GenerationCandidate,
    GenerationControl,
    GenerationOperation,
    ProviderAttempt,
    stamp,
)
from app.services.generation.resolution import prepare_replacement, resolution
from app.services.generation.store import Held, digest, dump
from sqlalchemy import select

from tests.test_generation_gateway import seed_job


async def failed_recap(maker, *, calls=4, reason="execution_failed"):
    await seed_job(maker)
    fixture = json.loads(
        (
            Path(__file__).parent
            / "fixtures/synthetic_analyst_grounded_v1_receipts.json"
        ).read_text()
    )
    payload = fixture["payload"]
    payload["edition"].update(
        league_name="Synthetic League",
        generated_at="2026-10-20T00:00:00+00:00",
        model="results",
        edition_type="results",
        markdown="Verified results only.",
    )
    payload.update(facts=payload["edition"]["facts"], season=2026, week=5)
    fixture["requests"] = fixture["requests"][:calls]
    fixture["responses"] = fixture["responses"][:calls]
    last = fixture["responses"][-1]
    last["stop_reason"] = "tool_use"
    last["content"] = [
        {
            "type": "tool_use",
            "id": "synthetic-rejection",
            "name": "submit_recap_review",
            "input": {
                "approved": False,
                "checks": [
                    {
                        "status": "needs_correction",
                        "quote": "Team A",
                        "evidence": "Remove the unsupported claim; retain verified fantasy points.",
                    }
                ],
            },
        }
    ]
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.feature, job.state, job.reason = (
            "analyst",
            "needs_attention",
            reason,
        )
        job.calls = job.max_calls = calls
        job.candidate_key = "original"
        job.payload_json, job.request_digest = dump(payload), digest(payload)
        db.add(
            GenerationCandidate(
                key="original",
                series_id=job.series_id,
                league_id=job.league_id,
                feature=job.feature,
                subject=job.subject,
                event="2026:week:05",
                payload_json=job.payload_json,
                digest=job.request_digest,
                hold="subject_needs_attention",
            )
        )
        for stage, (request, body) in enumerate(
            zip(fixture["requests"], fixture["responses"]), 1
        ):
            db.add(
                ProviderAttempt(
                    id=f"source-{stage}",
                    operation_id=job.id,
                    stage=stage,
                    generation=1,
                    request_json=dump(request),
                    request_digest=digest(request),
                    model=request["model"],
                    state="received",
                    usage_state="known",
                    cost_microusd=100,
                    settled_at=stamp(),
                    status_code=200,
                    receipt_json=dump(
                        {"status": 200, "body": json.dumps(body), "headers": {}}
                    ),
                )
            )
    return fixture


async def prepare(maker):
    async with maker.begin() as db:
        return await prepare_replacement(
            db,
            "job",
            SimpleNamespace(
                expected_generation=1,
                expected_state="needs_attention",
                reason="Review exact saved draft repair",
            ),
            "owner",
        )


async def apply(maker, preview):
    async with maker.begin() as db:
        result = await administration.apply_campaign(
            db,
            preview["id"],
            preview["digest"],
            "owner",
            "Approve one passage repair and one complete factual review",
        )
        return result["jobs"][0]


async def results_head(maker):
    from app.services.generation.artifacts import import_artifact

    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        payload = json.loads(job.payload_json)
        row = await import_artifact(
            db,
            series_id=job.series_id,
            league_id=job.league_id,
            feature="analyst",
            subject=job.subject,
            payload=payload["edition"],
            target={},
            facts=payload["facts"],
        )
        job.expected_artifact = row.id
        return row.id


async def running(maker, ident):
    from app.services.generation.commands import claim_operation

    async with maker.begin() as db:
        job = await claim_operation(db, "test-worker")
        assert job.id == ident
        return job


class RepairTransport:
    def __init__(self, *, approved=True):
        self.requests = []
        self.approved = approved

    async def send(self, request):
        from app.services.generation.transport import Receipt

        from tests.test_generation_gateway import BODY

        self.requests.append(request)
        value = (
            {"edits": []}
            if len(self.requests) == 1
            else {
                "approved": self.approved,
                "checks": []
                if self.approved
                else [
                    {
                        "status": "needs_correction",
                        "quote": "Team A",
                        "evidence": "Still unsupported",
                    }
                ],
            }
        )
        body = {
            **BODY,
            "model": request["model"],
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"synthetic-{len(self.requests)}",
                    "name": request["tool_choice"]["name"],
                    "input": value,
                }
            ],
        }
        return Receipt(200, json.dumps(body), {"request-id": "synthetic"})


@pytest.mark.asyncio
async def test_describe_is_read_only_under_breaker_and_binds_exact_saved_review(maker):
    # Mutation: reconstruct a draft or acquire a new allowance while merely inspecting eligibility.
    from app.services.generation.analyst_saved_draft import describe

    fixture = await failed_recap(maker)
    async with maker.begin() as db:
        (await db.get(GenerationControl, "global")).breakers_json = dump(
            {"analyst": {"open": True}}
        )
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        proposal = await describe(db, job)
        assert proposal["contract"] == "analyst_saved_draft_repair_v1"
        assert (
            proposal["draft"]
            == json.loads(fixture["requests"][-1]["messages"][0]["content"])["draft"]
        )
        assert proposal["grounding_version"] == "recap-owner-evidence-v1"
        assert proposal["source"]["request_digest"] == digest(fixture["requests"][-1])
        assert proposal["source"]["draft_digest"] == digest(proposal["draft"])
        assert proposal["max_calls"] == 2
        assert job.state == "needs_attention" and job.generation == 1 and job.calls == 4
        assert len((await db.scalars(select(GenerationOperation))).all()) == 1
        assert len((await db.scalars(select(GenerationAudit))).all()) == 0
    with pytest.raises(Held, match="feature_breaker_open"):
        await prepare(maker)
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "needs_attention"
        assert len((await db.scalars(select(GenerationCandidate))).all()) == 1


@pytest.mark.asyncio
async def test_replacement_is_manual_separate_and_two_calls_despite_four_call_policy(
    maker,
):
    # Mutation: reuse/enlarge the failed job, inherit four calls, or replace saved facts with refreshed facts.
    await failed_recap(maker)
    async with maker() as db:
        assert (await resolution(db, await db.get(GenerationOperation, "job")))[
            "action"
        ] == "replacement"
        original_receipts = [
            (a.id, a.request_json, a.receipt_json)
            for a in (await db.scalars(select(ProviderAttempt))).all()
        ]
    preview = await prepare(maker)
    assert preview["max_calls"] == preview["items"][0]["max_calls"] == 2
    assert preview["saved_draft_repair"]["maximum_additional_microusd"] > 0
    async with maker() as db:
        source = await db.get(GenerationOperation, "job")
        assert (source.state, source.generation, source.calls, source.max_calls) == (
            "cancelled",
            2,
            4,
            4,
        )
        candidate = await db.get(GenerationCandidate, preview["items"][0]["key"])
        assert (
            candidate.key != source.candidate_key
            and candidate.hold == "manual_approval_required"
        )
        payload = json.loads(candidate.payload_json)
        assert payload["edition"] == json.loads(source.payload_json)["edition"]
        assert payload["saved_draft_repair"]["source"]["generation"] == 2
        assert len((await db.scalars(select(GenerationOperation))).all()) == 1
    ident = await apply(maker, preview)
    async with maker() as db:
        job = await db.get(GenerationOperation, ident)
        assert job.id != "job" and job.calls == 0 and job.max_calls == 2
        assert (
            json.loads(job.policy_json)["policy"]["features"]["analyst"]["max_calls"]
            == 2
        )
        assert [
            (a.id, a.request_json, a.receipt_json)
            for a in (await db.scalars(select(ProviderAttempt))).all()
        ] == original_receipts


@pytest.mark.asyncio
async def test_exhausted_two_call_source_offers_saved_repair_instead_of_full_redraft(
    maker,
):
    # Mutation: require execution_failed only and fall back to a generic four-call replacement for a rejected two-call job.
    from app.services.generation.analyst_saved_draft import describe

    await failed_recap(maker, calls=2, reason="attempt_allowance_exhausted")
    await results_head(maker)
    async with maker() as db:
        source = await db.get(GenerationOperation, "job")
        guidance = await resolution(db, source)
        assert guidance.get("replacement_kind") == "analyst_saved_draft_repair_v1"
        proposal = await describe(db, source)
        assert proposal["source"]["attempt_id"] == "source-2"
    preview = await prepare(maker)
    assert preview["max_calls"] == 2
    ident = await apply(maker, preview)
    async with maker() as db:
        source = await db.get(GenerationOperation, "job")
        replacement = await db.get(GenerationOperation, ident)
        assert (source.calls, source.max_calls) == (2, 2)
        assert (
            json.loads(replacement.payload_json)["saved_draft_repair"]["draft"]
            == proposal["draft"]
        )
        assert replacement.max_calls == 2 and replacement.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "approved",
        "malformed",
        "wrong_tool",
        "unsettled",
        "error",
        "facts",
        "outlook",
        "lore",
        "candidate",
        "period",
        "generation",
        "head",
        "related",
    ],
)
async def test_source_evidence_must_prove_one_current_rejected_draft(maker, change):
    # Mutation: trust a rejected label without matching source facts, complete receipts, current identity, and head.
    from app.services.generation.analyst_saved_draft import describe
    from app.services.generation.models import ArtifactHead

    await failed_recap(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        last = await db.get(ProviderAttempt, "source-4")
        if change in ("approved", "malformed"):
            receipt = json.loads(last.receipt_json)
            body = json.loads(receipt["body"])
            body["content"][0]["input"] = (
                {"approved": True, "checks": []}
                if change == "approved"
                else {"approved": False, "checks": []}
            )
            receipt["body"] = json.dumps(body)
            last.receipt_json = dump(receipt)
        elif change in ("wrong_tool", "facts", "outlook", "lore"):
            request = json.loads(last.request_json)
            if change == "wrong_tool":
                request["tool_choice"]["name"] = "submit_recap_passage_edits"
            else:
                packet = json.loads(request["messages"][0]["content"])
                packet[change] = "different evidence"
                request["messages"][0]["content"] = json.dumps(packet)
            last.request_json, last.request_digest = dump(request), digest(request)
        elif change == "unsettled":
            (await db.get(ProviderAttempt, "source-1")).settled_at = 0
        elif change == "error":
            last.error_code = "provider_error"
        elif change == "candidate":
            (await db.get(GenerationCandidate, "original")).digest = "changed"
        elif change == "period":
            payload = json.loads(job.payload_json)
            payload["week"] += 1
            job.payload_json, job.request_digest = dump(payload), digest(payload)
            candidate = await db.get(GenerationCandidate, "original")
            candidate.payload_json, candidate.digest = (
                job.payload_json,
                job.request_digest,
            )
        elif change == "generation":
            last.generation += 1
        elif change == "head":
            db.add(ArtifactHead(subject=job.subject, artifact_id="newer", revision=1))
        else:
            db.add(
                GenerationOperation(
                    id="other",
                    kind="generation",
                    league_id=job.league_id,
                    series_id=job.series_id,
                    feature="analyst",
                    subject=job.subject,
                    state="queued",
                )
            )
    async with maker() as db:
        with pytest.raises(Held, match="saved_repair_"):
            await describe(db, await db.get(GenerationOperation, "job"))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["candidate", "receipt", "source_generation"])
async def test_campaign_apply_rechecks_saved_source_after_preview(maker, change):
    # Mutation: rely only on the repair candidate digest and miss changes to its source after preview.
    await failed_recap(maker)
    preview = await prepare(maker)
    async with maker.begin() as db:
        if change == "candidate":
            (await db.get(GenerationCandidate, "original")).digest = "new-facts"
        elif change == "receipt":
            last = await db.get(ProviderAttempt, "source-4")
            receipt = json.loads(last.receipt_json)
            receipt["headers"]["request-id"] = "different-receipt"
            last.receipt_json = dump(receipt)
        else:
            (await db.get(GenerationOperation, "job")).generation += 1
    with pytest.raises(Held, match="saved_repair_"):
        await apply(maker, preview)
    async with maker() as db:
        assert len((await db.scalars(select(GenerationOperation))).all()) == 1


@pytest.mark.asyncio
async def test_two_call_repair_replays_and_publishes_over_identical_results_head(maker):
    # Mutation: reject the existing results head, redraft instead of repair, upgrade v1 prompts, or replay paid requests.
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import ArtifactHead, GenerationOutbox

    await failed_recap(maker)
    old_head = await results_head(maker)
    preview = await prepare(maker)
    ident = await apply(maker, preview)
    job = await running(maker, ident)
    transport = RepairTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    result = await generate(job, gateway)
    assert result.stages == 2
    assert [request["tool_choice"]["name"] for request in transport.requests] == [
        "submit_recap_passage_edits",
        "submit_recap_review",
    ]
    assert all(
        request["system"][1]["text"].startswith("recap-owner-evidence-v1\n")
        for request in transport.requests
    )
    replay = await generate(job, gateway)
    assert (
        len(transport.requests) == 2
        and replay.payload["markdown"] == result.payload["markdown"]
    )
    async with maker.begin() as db:
        artifact = await save_artifact(db, job.id, job.generation, result)
        assert artifact.revision == 2
        assert (
            (await db.get(ArtifactHead, job.subject)).artifact_id
            == artifact.id
            != old_head
        )
        assert await db.scalar(
            select(GenerationOutbox).where(
                GenerationOutbox.key == "artifact:" + artifact.id
            )
        )
        assert (await db.get(GenerationOperation, "job")).calls == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["dispatch", "publication"])
@pytest.mark.parametrize(
    "change",
    [
        "candidate",
        "receipt",
        "head",
        "approval",
        "member",
        "allowance",
        "policy_revision",
    ],
)
async def test_changed_source_or_approval_blocks_dispatch_and_publication(
    maker, point, change
):
    # Mutation: only revalidate at campaign apply, letting stale source/grant/approval publish or spend later.
    from app.db.models import LeagueMembership
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import (
        ArtifactHead,
        ContentArtifact,
        GenerationOutbox,
    )
    from sqlalchemy import delete

    await failed_recap(maker)
    preview = await prepare(maker)
    job = await running(maker, await apply(maker, preview))
    transport = RepairTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    result = await generate(job, gateway) if point == "publication" else None
    async with maker.begin() as db:
        if change == "candidate":
            (await db.get(GenerationCandidate, "original")).digest = "changed-source"
        elif change == "receipt":
            (await db.get(ProviderAttempt, "source-4")).cost_microusd += 1
        elif change == "head":
            db.add(ArtifactHead(subject=job.subject, artifact_id="newer", revision=2))
        elif change == "approval":
            record = await db.get(GenerationAudit, preview["id"])
            value = json.loads(record.after_json)
            value["items"][0]["max_calls"] = 4
            record.after_json = dump(value)
        elif change == "member":
            await db.execute(delete(LeagueMembership))
        elif change == "policy_revision":
            from app.services.generation.models import GenerationPolicy

            (await db.get(GenerationPolicy, "app")).revision += 1
        else:
            current = await db.get(GenerationOperation, job.id)
            current.max_calls = 4
            policy = json.loads(current.policy_json)
            policy["policy"]["features"]["analyst"]["max_calls"] = 4
            current.policy_json = dump(policy)
    with pytest.raises(Held):
        if point == "dispatch":
            await generate(job, gateway)
        else:
            async with maker.begin() as db:
                await save_artifact(db, job.id, job.generation, result)
    assert len(transport.requests) == (0 if point == "dispatch" else 2)
    async with maker() as db:
        assert not (await db.scalars(select(ContentArtifact))).all()
        assert not (
            await db.scalars(
                select(GenerationOutbox).where(GenerationOutbox.kind == "artifact")
            )
        ).all()


@pytest.mark.asyncio
async def test_second_rejection_never_publishes_or_automatically_retries(maker):
    # Mutation: accept the saved rejection as final approval, add a third call, or offer another repair automatically.
    from app.services.generation.commands import attention
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway
    from app.services.generation.worker import admit_automatic

    await failed_recap(maker)
    job = await running(maker, await apply(maker, await prepare(maker)))
    transport = RepairTransport(approved=False)
    with pytest.raises(ValueError, match="did not receive factual approval"):
        await generate(job, Gateway(maker, transport, epoch="test-epoch"))
    async with maker.begin() as db:
        await attention(db, job.id, job.generation, "execution_failed")
        failed = await db.get(GenerationOperation, job.id)
        assert (await resolution(db, failed))["action"] == "replacement"
    await admit_automatic(maker)
    async with maker() as db:
        assert (await db.get(GenerationOperation, job.id)).calls == 2
        assert len((await db.scalars(select(GenerationOperation))).all()) == 2
    assert len(transport.requests) == 2

    # A new explicit approval can repair the latest rejected draft, with a fresh
    # two-call bound. Neither inspection nor scheduler admission buys those calls.
    async with maker.begin() as db:
        failed = await db.get(GenerationOperation, job.id)
        proposal = await prepare_replacement(db, failed.id, SimpleNamespace(
            expected_generation=failed.generation, expected_state=failed.state,
            reason="Owner approves another bounded repair"), "owner")
    assert proposal["max_calls"] == 2
    next_job = await running(maker, await apply(maker, proposal))
    from app.services.generation.artifacts import save_artifact
    result = await generate(next_job, Gateway(maker, RepairTransport(), epoch="test-epoch"))
    async with maker.begin() as db:
        await save_artifact(db, next_job.id, next_job.generation, result)
    async with maker() as db:
        assert (await db.get(GenerationOperation, next_job.id)).state == "succeeded"
        assert len((await db.scalars(select(ProviderAttempt))).all()) == 8


@pytest.mark.asyncio
async def test_original_event_stays_manual_after_free_recollection(maker):
    # Mutation: protect only the new repair key and let collection automatically buy a new full draft.
    from app.services.generation.candidate_status import replacement_requires_approval
    from app.services.generation.commands import authorize_candidate
    from app.services.generation.models import GenerationPolicy
    from app.services.generation.planner import observe

    await failed_recap(maker)
    await prepare(maker)
    async with maker.begin() as db:
        old = await db.get(GenerationCandidate, "original")
        assert await replacement_requires_approval(db, old.subject, old.event)
        (await db.get(GenerationPolicy, "app")).value_json = dump(
            {"paused": False, "features": {"analyst": {"mode": "automatic"}}}
        )
        refreshed = await observe(
            db,
            series_id=old.series_id,
            league_id=old.league_id,
            feature=old.feature,
            subject=old.subject,
            event=old.event,
            payload=json.loads(old.payload_json),
        )
        assert refreshed.hold == "manual_approval_required"
        with pytest.raises(Held, match="manual_approval_required"):
            await authorize_candidate(
                db,
                refreshed.key,
                actor_id="owner",
                actor_kind="scheduler",
                reason="Automatic weekly recap",
                authorization_key="automatic:synthetic",
            )


@pytest.mark.asyncio
async def test_one_call_policy_refuses_repair_before_authorization(maker, monkeypatch):
    # Mutation: clamp a two-stage repair to one call and pay for unreviewable output.
    from app.services.generation import analyst_saved_draft

    await failed_recap(maker)
    original = analyst_saved_draft.resolve_policy

    async def one_call(db, series_id):
        result = await original(db, series_id)
        result["policy"]["features"]["analyst"]["max_calls"] = 1
        return result

    monkeypatch.setattr(analyst_saved_draft, "resolve_policy", one_call)
    with pytest.raises(Held, match="saved_repair_two_calls_required"):
        await prepare(maker)
    async with maker() as db:
        assert (await db.get(GenerationOperation, "job")).state == "needs_attention"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["review_rejected", "review_draft", "output_facts", "edits_receipt"]
)
async def test_publication_requires_exact_repaired_output_and_approving_full_review(
    maker, change
):
    # Mutation: trust a ValidatedOutput marker after receipt, final draft, or original evidence has changed.
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import ValidatedOutput, generate
    from app.services.generation.gateway import Gateway

    await failed_recap(maker)
    job = await running(maker, await apply(maker, await prepare(maker)))
    result = await generate(job, Gateway(maker, RepairTransport(), epoch="test-epoch"))
    async with maker.begin() as db:
        attempts = list(
            (
                await db.scalars(
                    select(ProviderAttempt)
                    .where(ProviderAttempt.operation_id == job.id)
                    .order_by(ProviderAttempt.stage)
                )
            ).all()
        )
        if change == "review_rejected":
            receipt = json.loads(attempts[1].receipt_json)
            response = json.loads(receipt["body"])
            response["content"][0]["input"] = {
                "approved": False,
                "checks": [
                    {
                        "status": "needs_correction",
                        "quote": "Team A",
                        "evidence": "Unsupported",
                    }
                ],
            }
            receipt["body"] = json.dumps(response)
            attempts[1].receipt_json = dump(receipt)
        elif change == "review_draft":
            request = json.loads(attempts[1].request_json)
            evidence = json.loads(request["messages"][0]["content"])
            evidence["draft"] = "A different reviewed draft"
            request["messages"][0]["content"] = json.dumps(evidence)
            attempts[1].request_json, attempts[1].request_digest = (
                dump(request),
                digest(request),
            )
        elif change == "edits_receipt":
            receipt = json.loads(attempts[0].receipt_json)
            response = json.loads(receipt["body"])
            response["content"][0]["input"] = {
                "edits": [{"passage_id": "p1", "after": "Different repaired draft"}]
            }
            receipt["body"] = json.dumps(response)
            attempts[0].receipt_json = dump(receipt)
        else:
            payload = {**result.payload, "facts": {"week": 5, "invented": True}}
            result = ValidatedOutput(
                payload, digest(payload), result.snapshot_digest, result.stages
            )
    with pytest.raises(Held, match="saved_repair_"):
        async with maker.begin() as db:
            await save_artifact(db, job.id, job.generation, result)


async def yahoo_source(maker):
    from app.db.models import LeagueMembership, YahooConnection, YahooLeagueGrant
    from app.services.generation.models import LeagueSeason

    from tests.test_generation_yahoo_authorization import LEAGUE

    await failed_recap(maker)
    async with maker.begin() as db:
        (await db.scalar(select(LeagueMembership))).league_id = LEAGUE
        season = await db.get(LeagueSeason, "synthetic")
        season.league_id, season.provider, season.provider_key = LEAGUE, "yahoo", LEAGUE
        source = await db.get(GenerationOperation, "job")
        source.league_id, source.connection_generation = LEAGUE, "original"
        (await db.get(GenerationCandidate, "original")).league_id = LEAGUE
        db.add(
            YahooConnection(
                user_id="owner",
                generation="original",
                status="connected",
                sealed_tokens="synthetic-not-read",
                expires_at=stamp() + 3600,
            )
        )
        db.add(
            YahooLeagueGrant(
                user_id="owner",
                league_id=LEAGUE,
                generation="original",
                expires_at=stamp() + 300,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("point", ["apply", "dispatch", "publication"])
async def test_yahoo_reconnect_cannot_replace_original_repair_authority(
    maker, monkeypatch, point
):
    # Mutation: authorize against any fresh Yahoo account instead of the source's exact connection generation.
    from app.db.models import YahooConnection, YahooLeagueGrant
    from app.services.generation.artifacts import save_artifact
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway

    from tests.test_generation_yahoo_authorization import LEAGUE, verified_provider

    await yahoo_source(maker)
    preview = await prepare(maker)
    transport = RepairTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    verified = verified_provider(monkeypatch)
    job = (
        await running(maker, await apply(maker, preview)) if point != "apply" else None
    )
    result = await generate(job, gateway) if point == "publication" else None
    async with maker.begin() as db:
        (await db.get(YahooConnection, "owner")).generation = "replacement"
        (await db.get(YahooLeagueGrant, ("owner", LEAGUE))).generation = "replacement"
    with pytest.raises(Held, match="provider_grant_changed"):
        if point == "apply":
            await apply(maker, preview)
        elif point == "dispatch":
            await generate(job, gateway)
        else:
            async with maker.begin() as db:
                await save_artifact(db, job.id, job.generation, result)
    assert verified == []
    assert len(transport.requests) == (2 if point == "publication" else 0)


@pytest.mark.asyncio
async def test_yahoo_repair_renews_expiry_but_replay_requires_no_yahoo_or_paid_network(
    maker, monkeypatch
):
    # Mutation: demand a new grant while replaying saved repair receipts, or skip renewal before a new stage.
    from app.db.models import YahooLeagueGrant
    from app.services.generation.features import generate
    from app.services.generation.gateway import Gateway

    from tests.test_generation_yahoo_authorization import LEAGUE, verified_provider

    await yahoo_source(maker)
    job = await running(maker, await apply(maker, await prepare(maker)))
    async with maker.begin() as db:
        (await db.get(YahooLeagueGrant, ("owner", LEAGUE))).expires_at = stamp() - 1
    verified = verified_provider(monkeypatch)
    transport = RepairTransport()
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await generate(job, gateway)
    assert verified == [("owner", LEAGUE)]
    async with maker.begin() as db:
        (await db.get(YahooLeagueGrant, ("owner", LEAGUE))).expires_at = stamp() - 1
    await generate(job, gateway)
    assert verified == [("owner", LEAGUE)] and len(transport.requests) == 2
