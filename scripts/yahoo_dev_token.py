"""Mint a Yahoo access token for local development, and list your leagues.

Dev-only. The auth plan replaces this with a real OAuth flow and an encrypted
per-user token store; this exists so the ingestion work can be built and
verified against a real league before any of that is written.

Usage:

    # once, in api/.env or your shell
    export TRADE_GRADER_YAHOO_CLIENT_ID=...
    # Confidential clients only; OMIT for a Public Client:
    export TRADE_GRADER_YAHOO_CLIENT_SECRET=...

    python3 scripts/yahoo_dev_token.py

It prints an authorize URL, you approve in the browser, Yahoo bounces you to
https://localhost:8000/?code=... — your browser will show a connection error
because nothing is listening there, which is expected. Copy the complete URL
out of the URL bar and paste it at the hidden prompt. Do not bypass any browser
security warning. PKCE (S256) and state protect both public and confidential
clients. See https://developer.yahoo.com/sign-in-with-yahoo/.

The access token lasts one hour. Re-run this rather than trying to keep it
alive; the refresh-token machinery belongs to the auth plan, not here.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Must exactly match one of the Redirect URI(s) registered on the Yahoo app.
REDIRECT_URI = "https://localhost:8000"

# Approval is required before this read-only scope is available. Before Yahoo
# approved the app, requesting it failed with invalid_scope; that is not a
# reason to request unspecified permissions once approval has arrived.
SCOPE = "fspt-r"


def code_from_callback(callback: str, state: str) -> str:
    """Validate the full redirect, never accept a bare code without state."""
    parsed = urllib.parse.urlparse(callback)
    expected = urllib.parse.urlparse(REDIRECT_URI)
    if (parsed.scheme, parsed.netloc, parsed.path or "/") != (
        expected.scheme,
        expected.netloc,
        expected.path or "/",
    ) or parsed.fragment:
        raise ValueError(
            "Unexpected callback URL; paste the complete localhost redirect URL."
        )
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    states = params.get("state", [])
    if len(states) != 1 or not hmac.compare_digest(states[0].encode(), state.encode()):
        raise ValueError(
            "OAuth state mismatch; restart this script and authorize again."
        )
    if "error" in params:
        raise ValueError(
            "Yahoo authorization was denied or failed; restart and review permissions."
        )
    codes = params.get("code", [])
    if len(codes) != 1 or not codes[0].strip():
        raise ValueError(
            "Callback has no unique authorization code; restart this script."
        )
    return codes[0]


def _first_env(*names: str) -> str | None:
    """First of ``names`` that is set and non-empty.

    Two accepted spellings: the TRADE_GRADER_-prefixed pair the backend
    settings will read once the auth plan lands, and the shorter YAHOO_APP_
    pair. Whichever is present wins; the auth plan settles on one.
    """
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            sys.exit(
                "Yahoo token endpoint rate limit reached; wait before restarting authorization."
            )
        sys.exit(
            f"\nYahoo rejected the token request (HTTP {exc.code}).\n\n"
            "Most common causes: the code was already used (they are single-use "
            "— restart this script), the code expired (they are short-lived), or "
            "the redirect URI here does not exactly match one registered on the "
            f"app (this script sends {REDIRECT_URI!r})."
        )
    except (urllib.error.URLError, TimeoutError):
        sys.exit(
            "Yahoo token request timed out or could not connect; check network and restart."
        )
    except ValueError:
        sys.exit(
            "Yahoo token endpoint returned invalid JSON; try authorization again later."
        )


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    client_id = _first_env("TRADE_GRADER_YAHOO_CLIENT_ID", "YAHOO_APP_CLIENT_ID")
    client_secret = _first_env("TRADE_GRADER_YAHOO_CLIENT_SECRET", "YAHOO_APP_SECRET")
    if not client_id:
        sys.exit(
            "Yahoo Client ID not found. Set TRADE_GRADER_YAHOO_CLIENT_ID\n"
            "(or YAHOO_APP_CLIENT_ID). Public Clients do not use a secret.\n\n"
            "If they are in api/.env, load it into this shell first:\n"
            "    set -a; source api/.env; set +a"
        )

    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if SCOPE:
        params["scope"] = SCOPE
    query = urllib.parse.urlencode(params)
    print("\n1. Open this URL and approve access:\n")
    print(f"   {AUTHORIZE_URL}?{query}\n")
    print(f"2. Yahoo redirects to {REDIRECT_URI}/?code=...")
    print("   The page will fail to load — that is expected, nothing is running")
    print("   there. Copy the COMPLETE URL from the address bar. Do not bypass")
    print("   a security warning. The following prompt hides your input.\n")

    try:
        code = code_from_callback(
            getpass.getpass("3. Paste callback URL: ").strip(), state
        )
    except ValueError as exc:
        sys.exit(str(exc))

    fields = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }
    if client_secret:
        fields["client_secret"] = client_secret
    token = _post_form(TOKEN_URL, fields)

    access = token.get("access_token", "")
    if not isinstance(access, str) or not access:
        sys.exit("Yahoo returned no access token; restart authorization.")
    expires_in = int(token.get("expires_in", 3600))
    # mkstemp creates an owner-only (0600) file outside the repository. Never
    # print a bearer token or persist the long-lived refresh token in this tool.
    fd, token_path = tempfile.mkstemp(prefix="yahoo-access-", suffix=".json")
    with os.fdopen(fd, "w") as handle:
        json.dump(
            {"access_token": access, "expires_at": time.time() + expires_in}, handle
        )
    print(f"\nAccess token obtained; expires in {expires_in} seconds.")
    print(f"YAHOO_DEV_TOKEN_FILE={token_path}")
    print(
        "Token saved with owner-only permissions; delete this file after local verification."
    )

    print("\n--- your NFL leagues ---")
    try:
        payload = _get_json(
            f"{FANTASY_BASE}/users;use_login=1/games;game_keys=nfl/leagues?format=json",
            access,
        )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sys.exit(
                f"Fantasy API refused read access (HTTP {exc.code}); check app approval and authorize again."
            )
        if exc.code == 429:
            sys.exit("Fantasy API rate limit reached; wait before trying again.")
        sys.exit(f"Fantasy league listing failed (HTTP {exc.code}); try again later.")
    except (urllib.error.URLError, TimeoutError):
        sys.exit(
            "Fantasy league listing timed out or could not connect; check network and try again."
        )
    except ValueError:
        sys.exit("Fantasy league listing returned invalid JSON; try again later.")

    leagues = list(_walk_leagues(payload))
    print(
        f"Fantasy API read succeeded (HTTP 200); {len(leagues)} current NFL league(s)."
    )
    for key, name, season in leagues:
        print(f"  YAHOO_DEV_LEAGUE_KEY={key}   {name} ({season})")


def _walk_leagues(payload: dict):
    """Yield (league_key, name, season) from the users/games/leagues payload.

    Deliberately a brute-force walk rather than a precise path: this runs once,
    by hand, and the point is to survive whatever nesting Yahoo returns rather
    than to model it. The real parsing lives in api/yahoo_json.py.
    """
    found: list[tuple[str, str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            if "league_key" in node and "name" in node:
                found.append(
                    (
                        str(node.get("league_key")),
                        str(node.get("name")),
                        str(node.get("season", "?")),
                    )
                )
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    seen = set()
    for row in found:
        if row[0] not in seen:
            seen.add(row[0])
            yield row


if __name__ == "__main__":
    main()
