"""The fixture recorder keeps raw Yahoo data outside the source tree."""

import importlib.util
import json
import time
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "record_yahoo_fixtures",
    Path(__file__).parents[1] / "scripts/record_yahoo_fixtures.py",
)
capture = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(capture)


def test_reads_private_token_file(monkeypatch, tmp_path):
    # Mutation: reading only the old env token rejects the new PKCE output.
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps({"access_token": "synthetic", "expires_at": time.time() + 60})
    )
    monkeypatch.delenv("YAHOO_DEV_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("YAHOO_DEV_TOKEN_FILE", str(token_file))
    assert capture.load_access_token() == "synthetic"


def test_rejects_expired_token_file(monkeypatch, tmp_path):
    # Mutation: ignoring expiry submits a known-invalid token to Yahoo.
    token_file = tmp_path / "token.json"
    token_file.write_text(
        json.dumps({"access_token": "secret", "expires_at": time.time() - 1})
    )
    monkeypatch.delenv("YAHOO_DEV_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("YAHOO_DEV_TOKEN_FILE", str(token_file))
    with pytest.raises(SystemExit, match="expired") as exc:
        capture.load_access_token()
    assert "secret" not in str(exc.value)


def test_raw_fixtures_cannot_be_saved_in_repo(monkeypatch):
    # Mutation: accepting a source-tree output path risks committing private data.
    monkeypatch.setenv(
        "YAHOO_FIXTURE_DIR", str(Path(__file__).parent / "fixtures/yahoo")
    )
    with pytest.raises(SystemExit, match="outside"):
        capture.output_directory()
