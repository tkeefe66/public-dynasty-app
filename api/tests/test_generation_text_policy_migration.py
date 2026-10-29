"""Rollout changes text evidence routing, never paid authorization or caps."""
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select

from app.db.base import Base
from app.services.generation.models import GenerationAudit, GenerationPolicy
from app.services.generation.policy import Policy, effective
from app.services.generation.recap_models import RecapBudgetPolicy


def test_legacy_false_is_migrated_with_revision_and_audit_without_other_policy_changes():
    path = Path(__file__).parents[1] / "migrations/versions/0022_text_reconciliation.py"
    spec = importlib.util.spec_from_file_location("text_policy_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    policies = {}
    for scope, mode, paused in (("app", "automatic", False), ("profile:keeper", "manual", False),
                                ("series:paused", "automatic", True), ("series:disabled", "disabled", False)):
        value = Policy(paused=paused, recap_text_reconciliation=False).model_dump()
        value["features"]["analyst"]["mode"] = mode
        value["features"]["analyst"]["max_calls"] = 4
        policies[scope] = value
    with engine.begin() as conn:
        conn.execute(RecapBudgetPolicy.__table__.insert().values(series_id="preserved-budget",
            revision=9, caps_json='{"episode_microusd":5000000, "monthly_microusd":20000000}', updated_at=123))
        budget_before = conn.execute(select(RecapBudgetPolicy.__table__)).mappings().all()
        for scope, value in policies.items():
            conn.execute(GenerationPolicy.__table__.insert().values(scope=scope, revision=7, value_json=json.dumps(value)))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        rows = conn.execute(select(GenerationPolicy.__table__)).mappings().all()
        for row in rows:
            expected = dict(policies[row["scope"]])
            expected.pop("recap_text_reconciliation")
            assert json.loads(row["value_json"]) == expected
            assert row["revision"] == 8
            resolved = effective([("app", expected)])["policy"]
            assert resolved["recap_text_reconciliation"] is True
            prior = effective([("app", policies[row["scope"]])])["policy"]
            assert resolved["features"] == prior["features"]
        audits = conn.execute(select(GenerationAudit.__table__)).mappings().all()
        assert conn.execute(select(RecapBudgetPolicy.__table__)).mappings().all() == budget_before
        assert len(audits) == len(policies)
        assert {row["target"] for row in audits} == set(policies)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert conn.execute(select(GenerationPolicy.__table__)).mappings().all() == rows
        assert conn.execute(select(GenerationAudit.__table__)).mappings().all() == audits
