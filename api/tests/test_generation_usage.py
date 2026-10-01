"""Usage boundary regressions for PostgreSQL numeric values."""
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.generation.models import GenerationOperation, ProviderAttempt
from app.services.generation.usage import ledger_records


@pytest.mark.asyncio
@pytest.mark.parametrize("microusd, expected", [(Decimal(0), 0.0), (Decimal(1_234_567), 1.234567)])
async def test_ledger_decimal_costs_mix_with_legacy_float_records(microusd, expected):
    """Mutation: leave a Decimal dollar value in the legacy-compatible record."""
    attempt = ProviderAttempt(id="attempt", created_at=1, model="model", cost_microusd=microusd)
    job = GenerationOperation(feature="trade_story", league_id="synthetic")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(attempt, job)])))

    records = await ledger_records(db)

    assert json.loads(json.dumps(records))[0]["cost_usd"] == expected
    assert 0.5 + records[0]["cost_usd"] == pytest.approx(0.5 + expected)
