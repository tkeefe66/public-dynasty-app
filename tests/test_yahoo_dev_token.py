"""Synthetic OAuth responses; live Yahoo consent is verified separately."""

import base64
import hashlib
import importlib.util
import json
import stat
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "yahoo_dev_token", Path(__file__).parents[1] / "scripts/yahoo_dev_token.py"
)
oauth = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(oauth)


def test_public_client_can_exchange_with_pkce_without_secret(
    monkeypatch, capsys, tmp_path
):
    # Mutation: requiring a client secret or omitting S256 breaks public clients.
    for name in (
        "TRADE_GRADER_YAHOO_CLIENT_SECRET",
        "YAHOO_APP_SECRET",
        "YAHOO_APP_CLIENT_ID",
        "YAHOO_OAUTH_SCOPE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADE_GRADER_YAHOO_CLIENT_ID", "synthetic-client")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    request = {}

    def callback(_prompt):
        output = capsys.readouterr().out
        url = next(
            line.strip() for line in output.splitlines() if "request_auth?" in line
        )
        request.update(parse_qs(urlparse(url).query))
        return (
            f"https://localhost:8000/?code=synthetic-code&state={request['state'][0]}"
        )

    def exchange(url, fields):
        assert "client_secret" not in fields
        assert fields["code"] == "synthetic-code"
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(fields["code_verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        assert request["code_challenge"] == [challenge]
        assert request["code_challenge_method"] == ["S256"]
        assert request["scope"] == ["fspt-r"]
        return {
            "access_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(oauth.getpass, "getpass", callback)
    monkeypatch.setattr(oauth, "_post_form", exchange)
    monkeypatch.setattr(oauth, "_get_json", lambda *args: {"fantasy_content": {}})
    oauth.main()
    output = capsys.readouterr().out
    assert "synthetic-access" not in output
    assert "synthetic-refresh" not in output
    files = list(tmp_path.glob("yahoo-access-*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["access_token"] == "synthetic-access"
    assert "refresh_token" not in saved
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "callback",
    [
        "https://localhost:8000/?code=secret&state=wrong",
        "https://localhost:8000/?code=secret&state=%C3%A9",
        "https://localhost:8000/?code=secret",
        "https://localhost:8000/?code=secret&state=right&state=wrong",
        "https://localhost:8000/?code=one&code=two&state=right",
        "https://attacker.example/?code=secret&state=right",
        "http://localhost:8000/?code=secret&state=right",
        "https://localhost:8000/unexpected?code=secret&state=right",
        "secret",
    ],
)
def test_callback_rejects_mismatched_origin_state_or_ambiguous_code(callback):
    # Mutation: accepting a bare code or ignoring state permits swapped callbacks.
    with pytest.raises(ValueError):
        oauth.code_from_callback(callback, "right")


def test_callback_accepts_matching_state():
    # Mutation: rejecting the root slash breaks Yahoo's localhost redirect.
    assert (
        oauth.code_from_callback(
            "https://localhost:8000/?code=synthetic&state=right", "right"
        )
        == "synthetic"
    )


def test_callback_errors_do_not_echo_provider_text():
    # Mutation: displaying error_description exposes untrusted callback data.
    with pytest.raises(ValueError, match="denied") as exc:
        oauth.code_from_callback(
            "https://localhost:8000/?error=access_denied&error_description=secret&state=right",
            "right",
        )
    assert "secret" not in str(exc.value)
