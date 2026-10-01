"""A provider key and standalone writer must never bypass durable admission."""
from pathlib import Path

import pytest

from sleeper_dynasty.llm.managed import UnmanagedGenerationError
from sleeper_dynasty.llm.trade_story_writer import TradeStoryWriter


def test_unmanaged_writer_fails_before_network(monkeypatch):
    """Mutation: replace DeniedClient with a directly constructed SDK client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-unused-key")
    writer = TradeStoryWriter()
    with pytest.raises(UnmanagedGenerationError, match="authorized admin job"):
        writer._client.messages.create(model=writer.model, max_tokens=1, messages=[])


def test_no_direct_sdk_client_constructors_in_product_code():
    root = Path(__file__).parents[1]
    offenders = []
    for folder in (root / "src", root / "api/app", root / "scripts"):
        for path in folder.rglob("*.py"):
            body = path.read_text()
            if any(token in body for token in ("anthropic.Anthropic(", "anthropic.AsyncAnthropic(")):
                offenders.append(str(path.relative_to(root)))
    assert not offenders, offenders
