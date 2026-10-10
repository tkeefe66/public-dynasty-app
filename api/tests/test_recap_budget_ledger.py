"""Budget obligations persist across cancellation, revisions and billing windows."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.services.generation import recap_budget as budget
from app.services.generation.models import LeagueSeries
from app.services.generation.store import Conflict, Held


def at(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo("America/Denver")).timestamp())


NOW = at("2026-10-09T12:00:00")


def allocation(amount=2_000_000, key="voice", category="video"):
    return dict(key=key, category=category, max_microusd=amount,
                rate_snapshot={"version": "qualified-test", "unit": "microusd"}, operation_id="")


async def seed(maker):
    async with maker.begin() as db:
        db.add(LeagueSeries(id="series"))


def test_unknown_reservations_are_not_free_budget():
    # Mutation: subtract known only and ignore reserved exposure.
    assert budget.remaining_microusd(3_000_000, 1_000_000, 1_500_000) == 500_000
    assert budget.remaining_microusd(3_000_000, 2_000_000, 1_500_000) == 0


def test_pricing_bound_includes_serialization_tools_and_all_calls():
    # Mutation: use chars/4, omit tool schemas, or reserve only first draft.
    from app.services.generation.accounting import bounded_plan, pricing, request_ceiling
    from app.services.generation.policy import Policy
    from tests.test_generation_gateway import REQUEST
    from sleeper_dynasty.llm.recap_writer import REVIEW_TOOL
    request = {**REQUEST, "tools": [REVIEW_TOOL], "tool_choice": {"type": "tool", "name": REVIEW_TOOL["name"]}}
    assert request_ceiling(request, pricing(request["model"])) > len(json.dumps(request))
    policy = Policy().model_dump()["features"]["analyst"]
    plan = bounded_plan("op", "analyst", policy, policy, 4)
    assert len(plan) == 4
    assert all(a["max_microusd"] >= policy["max_prompt_chars"] * 3 + policy["max_tokens"] * 15 for a in plan)
    with pytest.raises(Held, match="request_option_unregistered"):
        request_ceiling({**REQUEST, "messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]}, pricing(request["model"]))


@pytest.mark.asyncio
async def test_duplicate_plan_idempotent_changed_payload_conflicts(maker):
    # Mutation: key replay bypasses immutable payload comparison.
    await seed(maker)
    async with maker.begin() as db:
        one = await budget.reserve_plan(db, "episode", "series", "first", [allocation()], NOW)
        assert await budget.reserve_plan(db, "episode", "series", "first", [allocation()], NOW) == one
        with pytest.raises(Conflict):
            await budget.reserve_plan(db, "episode", "series", "first", [allocation(1)], NOW)
        view = await budget.get_budget_view(db, "series", "episode", NOW)
        assert view["balances"]["video_episode_microusd"]["reserved_microusd"] == 2_000_000


@pytest.mark.asyncio
async def test_all_intersecting_caps_and_revisions_share_episode(maker):
    # Mutation: enforce video only or give corrections fresh episode allowance.
    await seed(maker)
    async with maker.begin() as db:
        await budget.reserve_plan(db, "episode", "series", "written", [allocation(3_000_000, category="written")], NOW)
        await budget.reserve_plan(db, "episode", "series", "video", [allocation()], NOW)
        with pytest.raises(Held, match="combined_episode"):
            await budget.reserve_plan(db, "episode", "series", "correction", [allocation(1)], NOW)


@pytest.mark.asyncio
async def test_unknown_carries_forward_then_late_settlement_stays_in_original_month(maker):
    # Mutation: rollover or cancellation releases unknown; late receipt moves invoice month.
    from app.services.generation.recap_models import RecapBudgetAllocation
    await seed(maker)
    async with maker.begin() as db:
        await budget.reserve_plan(db, "episode", "series", "first", [allocation()], at("2026-09-30T23:59:00"))
        row = await db.scalar(select(RecapBudgetAllocation))
        await budget.settle_allocation(db, row.id, None, {"state": "cancelled_unknown"})
        view = await budget.get_budget_view(db, "series", "episode", NOW)
        balance = view["balances"]["video_month_microusd"]
        assert balance["reserved_microusd"] == 0
        assert balance["carry_forward_microusd"] == 2_000_000
        assert balance["uncertain_microusd"] == 2_000_000  # Subset of reserved + carry, not an extra charge.
        assert balance["remaining_microusd"] == 13_000_000
        await budget.settle_allocation(db, row.id, 750_000, {"receipt": "late"})
        await budget.settle_allocation(db, row.id, 750_000, {"receipt": "late"})
        with pytest.raises(Conflict):
            await budget.settle_allocation(db, row.id, 1, {"receipt": "changed"})
        view = await budget.get_budget_view(db, "series", "episode", NOW)
        assert view["balances"]["video_month_microusd"]["carry_forward_microusd"] == 0
        assert view["balances"]["video_month_microusd"]["known_microusd"] == 0
        assert view["balances"]["video_month_microusd"]["uncertain_microusd"] == 0
        assert view["balances"]["video_episode_microusd"]["known_microusd"] == 750_000


@pytest.mark.asyncio
async def test_cap_reduction_requires_acknowledgment_and_stops_admission(maker):
    # Mutation: cap edits ignore already committed obligations.
    await seed(maker)
    async with maker.begin() as db:
        await budget.reserve_plan(db, "episode", "series", "first", [allocation()], NOW)
        with pytest.raises(Conflict, match="acknowledge"):
            await budget.save_caps(db, "series", budget.RecapCaps(video_episode_microusd=1_000_000), 0, "owner", "Lower", False)
        await budget.save_caps(db, "series", budget.RecapCaps(video_episode_microusd=1_000_000), 0, "owner", "Lower", True)
        with pytest.raises(Held, match="video_episode"):
            await budget.reserve_plan(db, "episode", "series", "second", [allocation(1)], NOW)


@pytest.mark.asyncio
async def test_real_collector_payload_binds_episode_across_article_revisions(maker, tmp_path):
    # Mutation: expect invented period_id field instead of real collect_analyst envelope.
    from app.services.analyst_store import AnalystEdition, AnalystStore
    from app.services.generation.models import GenerationCandidate, GenerationOperation
    from app.services.generation.planner import collect_analyst
    from app.services.generation.store import dump
    await seed(maker)
    store = AnalystStore(tmp_path)
    edition = AnalystEdition(season=2026, week=4, edition_type="results", markdown="private results", facts={},
        league_name="Synthetic", generated_at="2026-10-09T12:00:00+00:00", model="results")
    root = store.league_dir("synthetic")
    root.mkdir(parents=True)
    (root / "2026-week-04.json").write_text(edition.model_dump_json())
    async with maker.begin() as db:
        await collect_analyst(db, "synthetic", "series", tmp_path)
        candidate = await db.scalar(select(GenerationCandidate))
        assert candidate is not None
        job = GenerationOperation(series_id="series", feature="analyst", payload_json=candidate.payload_json)
        original = budget.operation_episode(job)
        payload = json.loads(job.payload_json)
        payload["edition"]["revision"] = 2
        job.payload_json = dump(payload)
        assert budget.operation_episode(job) == original == budget.episode_identity("series", 2026, "4")


@pytest.fixture(autouse=True)
def owner_allowlist(monkeypatch):
    monkeypatch.setenv("TRADE_GRADER_ADMIN_EMAILS", "owner@test.local")


async def analyst_job(maker):
    from app.services.generation.models import GenerationOperation
    from app.services.generation.store import dump
    from tests.test_generation_gateway import seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.feature = "analyst"
        job.max_calls = 4
        job.payload_json = dump({"season": 2026, "week": 4, "edition": {"season": 2026, "week": 4, "revision": 1}})


@pytest.mark.asyncio
async def test_complete_written_plan_reserved_before_first_paid_request_and_revalidated(maker):
    # Mutation: reserve draft only, or ignore reduced policy before second dispatch.
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_generation_gateway import BODY, REQUEST, FakeTransport
    await analyst_job(maker)
    request = {**REQUEST, "model": "claude-sonnet-4-6"}
    transport = FakeTransport(body=json.dumps({**BODY, "model": request["model"]}))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    await gateway.invoke("job", 1, 1, request)
    async with maker.begin() as db:
        rows = list((await db.scalars(select(RecapBudgetAllocation))).all())
        assert len(rows) == 4
        assert sum(row.outstanding_microusd > 0 for row in rows) == 3
        await budget.save_caps(db, "series", budget.RecapCaps(combined_episode_microusd=1), 0, "owner", "Lower", True)
    with pytest.raises(Held, match="combined_episode"):
        await gateway.invoke("job", 1, 2, request)
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_low_cap_holds_entire_plan_without_paid_request(maker):
    # Mutation: purchase first draft before confirming all four calls fit.
    from app.services.generation.gateway import Gateway
    from tests.test_generation_gateway import REQUEST, FakeTransport
    await analyst_job(maker)
    async with maker.begin() as db:
        await budget.save_caps(db, "series", budget.RecapCaps(combined_episode_microusd=1_000_000), 0, "owner", "Lower", False)
    transport = FakeTransport()
    with pytest.raises(Held, match="combined_episode"):
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, {**REQUEST, "model": "claude-sonnet-4-6"})
    assert transport.sends == 0


@pytest.mark.asyncio
async def test_cancel_retains_sent_exposure_and_releases_only_future_calls(maker):
    # Mutation: cancellation releases every reservation including sent unknown requests.
    from app.services.generation.commands import cancel
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_generation_gateway import REQUEST, FakeTransport
    await analyst_job(maker)
    with pytest.raises(Held, match="provider_outcome_unknown"):
        await Gateway(maker, FakeTransport(lost=True), epoch="test-epoch").invoke(
            "job", 1, 1, {**REQUEST, "model": "claude-sonnet-4-6"})
    async with maker.begin() as db:
        await cancel(db, "job", "owner", "Cancel uncertain work")
        rows = list((await db.scalars(select(RecapBudgetAllocation))).all())
        sent = next(row for row in rows if row.attempt_id)
        assert sent.actual_microusd is None and sent.outstanding_microusd == sent.max_microusd
        assert all(row.actual_microusd == 0 and row.outstanding_microusd == 0 for row in rows if not row.attempt_id)
        with pytest.raises(Held, match="outcome_unknown"):
            await budget.reserve_plan(db, budget.episode_identity("series", 2026, "4"), "series", "replacement", [allocation(1)], NOW)


@pytest.mark.asyncio
async def test_backfill_keeps_known_receipt_single_count_and_unknown_cancelled_visible(maker):
    # Mutation: add old receipt and its backfilled allocation twice; cancelled unknown becomes zero.
    from app.services.generation.accounting import pricing
    from app.services.generation.models import GenerationOperation, ProviderAttempt
    from app.services.generation.store import dump
    from tests.test_generation_gateway import REQUEST
    await analyst_job(maker)
    async with maker.begin() as db:
        job = await db.get(GenerationOperation, "job")
        job.state = "cancelled"
        db.add(ProviderAttempt(id="known", operation_id="job", stage=1, generation=1,
            model=REQUEST["model"], request_digest="one", request_json=dump(REQUEST), pricing_json=dump(pricing(REQUEST["model"])),
            cost_microusd=200_000, usage_state="known", state="received", created_at=NOW))
        db.add(ProviderAttempt(id="unknown", operation_id="job", stage=2, generation=1,
            model=REQUEST["model"], request_digest="two", request_json="{}", pricing_json="{}", state="unknown", created_at=NOW))
        before = await budget.get_budget_view(db, "series", budget.operation_episode(job), NOW)
        await budget.backfill_written(db, "series")
        await budget.backfill_written(db, "series")
        after = await budget.get_budget_view(db, "series", budget.operation_episode(job), NOW)
        assert before == after
        balance = after["balances"]["combined_episode_microusd"]
        assert balance["known_microusd"] == 200_000
        assert balance["unbounded_unknown_count"] == 1
        assert balance["remaining_microusd"] is None
        assert after["app_limit"]["balance"]["known_microusd"] == 200_000


@pytest.mark.asyncio
async def test_receipt_over_reservation_records_honest_cost_and_holds_provider(maker):
    # Mutation: clamp actual costs to reservation or allow next paid call after rate error.
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationControl
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_generation_gateway import BODY, REQUEST, FakeTransport, seed_job
    await seed_job(maker)
    body = {**BODY, "usage": {"input_tokens": 100_000, "output_tokens": 5}}
    transport = FakeTransport(body=json.dumps(body))
    gateway = Gateway(maker, transport, epoch="test-epoch")
    with pytest.raises(Held, match="reservation_exceeded"):
        await gateway.invoke("job", 1, 1, REQUEST)
    async with maker() as db:
        row = await db.scalar(select(RecapBudgetAllocation))
        assert row.actual_microusd == 100_025 and row.state == "overrun"
        assert (await db.get(GenerationControl, "global")).provider_hold == "reservation_exceeded"
    with pytest.raises(Held, match="reservation_exceeded"):
        await gateway.invoke("job", 1, 2, REQUEST)
    assert transport.sends == 1


@pytest.mark.asyncio
async def test_audited_financial_reconciliation_updates_receipt_without_freeing_unknown(maker):
    # Mutation: reconcile only allocation, leaving ProviderAttempt/admin usage inconsistent.
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import ProviderAttempt
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job
    await seed_job(maker)
    with pytest.raises(Held):
        await Gateway(maker, FakeTransport(lost=True), epoch="test-epoch").invoke("job", 1, 1, REQUEST)
    async with maker.begin() as db:
        row = await db.scalar(select(RecapBudgetAllocation))
        with pytest.raises(budget.InvalidBudgetRequest):
            await budget.reconcile_allocation(db, row.id, 0, {}, "owner", "")
        assert row.outstanding_microusd > 0
        await budget.reconcile_allocation(db, row.id, 321, {"invoice_line": "synthetic-evidence"}, "owner", "Verified invoice")
        assert row.actual_microusd == 321 and row.outstanding_microusd == 0
        attempt = await db.scalar(select(ProviderAttempt))
        assert attempt.cost_microusd == 321
        assert attempt.usage_state == "financially_reconciled"
        assert attempt.state == "unknown"  # Financial evidence is not reusable prose.
        from types import SimpleNamespace
        from app.services.generation.administration import resolve_attempt
        with pytest.raises(Conflict, match="Known paid usage"):
            await resolve_attempt(db, attempt.id, SimpleNamespace(action="not_sent", expected_state="unknown",
                workers_stopped=True, evidence="Contradictory", reason="Override"), "owner")


def test_narration_uses_final_characters_and_all_authorized_chunks():
    # Mutation: use script estimates instead of submitted chunks or omit replacements.
    from app.services.generation.accounting import narration_allocations
    rate = dict(provider="qualified", product="tts", version="v1", currency="USD",
                unit="character", microusd_per_character="80", evidence="account-qualified")
    allocations = narration_allocations("op", ["a" * 2000, "b" * 123], rate, replacements=1)
    assert len(allocations) == 4
    assert sum(a["max_microusd"] for a in allocations) == 2 * 2123 * 80
    with pytest.raises(Held, match="pricing_unknown"):
        narration_allocations("op", ["text"], {**rate, "voice_adjustment": "unknown"})


def test_unknown_receipt_rate_dimensions_remain_unpriced():
    # Mutation: price familiar token fields while silently dropping a new billed dimension.
    from app.services.generation.accounting import price_usage, pricing
    from tests.test_generation_gateway import BODY, REQUEST
    body = {**BODY, "usage": {**BODY["usage"], "new_paid_dimension": 10}}
    state, _, amount = price_usage(body, pricing(REQUEST["model"]))
    assert state == "pricing_unknown" and amount is None


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,category", [("video_month_microusd", "video"), ("combined_month_microusd", "written")])
async def test_monthly_caps_span_distinct_episodes(maker, scope, category):
    # Mutation: monthly admission sums only the current episode.
    await seed(maker)
    async with maker.begin() as db:
        await budget.save_caps(db, "series", budget.RecapCaps(**{scope: 2_000_000}), 0, "owner", "Limit", False)
        await budget.reserve_plan(db, "first", "series", "one", [allocation(category=category)], NOW)
        with pytest.raises(Held, match=scope.removesuffix("_microusd")):
            await budget.reserve_plan(db, "second", "series", "one", [allocation(1, category=category)], NOW)


@pytest.mark.asyncio
async def test_current_model_authority_rechecked_before_dispatch(maker):
    # Mutation: current policy model change does not revoke old saved model permission.
    from app.services.generation.gateway import Gateway
    from app.services.generation.models import GenerationPolicy
    from app.services.generation.store import dump
    from tests.test_generation_gateway import REQUEST, FakeTransport, seed_job
    await seed_job(maker)
    async with maker.begin() as db:
        (await db.get(GenerationPolicy, "app")).value_json = dump({"paused": False,
            "features": {"trade_story": {"model": "claude-sonnet-4-6"}}})
    transport = FakeTransport()
    with pytest.raises(Held, match="request_model_changed"):
        await Gateway(maker, transport, epoch="test-epoch").invoke("job", 1, 1, REQUEST)
    assert transport.sends == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("action,released", [("not_sent", True), ("abandon_unknown", False)])
async def test_existing_audited_resolution_reconciles_only_proven_non_submission(maker, action, released):
    # Mutation: legacy resolve_attempt ignores allocation, or abandonment zeroes unknown spend.
    from types import SimpleNamespace
    from app.services.generation.administration import resolve_attempt
    from app.services.generation.gateway import Gateway
    from app.services.generation.recap_models import RecapBudgetAllocation
    from tests.test_generation_gateway import REQUEST, FakeTransport
    await analyst_job(maker)
    with pytest.raises(Held):
        await Gateway(maker, FakeTransport(lost=True), epoch="test-epoch").invoke(
            "job", 1, 1, {**REQUEST, "model": "claude-sonnet-4-6"})
    async with maker.begin() as db:
        row = await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id.is_not(None)))
        await resolve_attempt(db, row.attempt_id, SimpleNamespace(action=action, expected_state="unknown",
            workers_stopped=True, evidence="Verified provider submission records", reason="Resolve"), "owner")
        assert (row.outstanding_microusd == 0) == released
        others = list((await db.scalars(select(RecapBudgetAllocation).where(RecapBudgetAllocation.attempt_id.is_(None)))).all())
        assert all(a.actual_microusd == 0 for a in others)


@pytest.mark.asyncio
async def test_historical_view_uses_requested_month_for_legacy_spend(maker, tmp_path, monkeypatch):
    # Mutation: app balance reads wall-clock legacy spend despite caller's month window.
    from sleeper_dynasty.llm.cost_store import LlmCostStore
    from app.services.generation.store import dump
    await seed(maker)
    monkeypatch.setenv("TRADE_GRADER_CACHE_DIR", str(tmp_path))
    store = LlmCostStore(tmp_path)
    store.record(model="claude-haiku-4-5-20251001", writer="trade_story", league_id="synthetic",
                 input_tokens=1, output_tokens=0)
    records = store.read_all()
    assert len(records) == 1
    # Use existing store output format, changing only the timestamp for a fixed window.
    path = tmp_path / "llm_costs.jsonl"
    path.write_text(dump({**records[0], "ts": "2020-02-12T12:00:00+00:00", "cost_usd": 1.25}) + "\n")
    async with maker() as db:
        view = await budget.get_budget_view(db, "series", None, at("2020-02-12T12:00:00"))
        assert view["app_limit"]["balance"]["known_microusd"] == 1_250_000
