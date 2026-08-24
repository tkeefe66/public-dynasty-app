"""Mint a Yahoo access token for local development, and list your leagues.

Dev-only. The auth plan replaces this with a real OAuth flow and an encrypted
per-user token store; this exists so the ingestion work can be built and
verified against a real league before any of that is written.

Usage:

    # once, in api/.env or your shell
    export TRADE_GRADER_YAHOO_CLIENT_ID=...
    export TRADE_GRADER_YAHOO_CLIENT_SECRET=...

    python3 scripts/yahoo_dev_token.py

It prints an authorize URL, you approve in the browser, Yahoo bounces you to
https://localhost:8000/?code=... — your browser will show a connection error
because nothing is listening there, which is expected. Copy the `code` value
out of the URL bar and paste it in.

The access token lasts one hour. Re-run this rather than trying to keep it
alive; the refresh-token machinery belongs to the auth plan, not here.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Must exactly match one of the Redirect URI(s) registered on the Yahoo app.
REDIRECT_URI = "https://localhost:8000"

# No scope by default.
#
# The obvious move is to request Yahoo's fantasy read scope, "fspt-r", since
# recent app-registration forms no longer offer a Fantasy Sports permission
# checkbox. Yahoo rejects that outright:
#     ?error=invalid_scope&error_description=invalid+scope
# Omitting the parameter entirely makes Yahoo grant whatever the app is
# provisioned for, which is the working path. Override to experiment:
#     YAHOO_OAUTH_SCOPE=fspt-r python3 scripts/yahoo_dev_token.py
SCOPE = (os.environ.get("YAHOO_OAUTH_SCOPE") or "").strip()


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
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        sys.exit(
            f"\nYahoo rejected the token request ({exc.code}).\n{detail}\n\n"
            "Most common causes: the code was already used (they are single-use "
            "— restart this script), the code expired (they are short-lived), or "
            "the redirect URI here does not exactly match one registered on the "
            f"app (this script sends {REDIRECT_URI!r})."
        )


def _get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    client_id = _first_env("TRADE_GRADER_YAHOO_CLIENT_ID", "YAHOO_APP_CLIENT_ID")
    client_secret = _first_env(
        "TRADE_GRADER_YAHOO_CLIENT_SECRET", "YAHOO_APP_SECRET")
    if not client_id or not client_secret:
        sys.exit(
            "Yahoo app credentials not found. Set either pair:\n"
            "  TRADE_GRADER_YAHOO_CLIENT_ID / TRADE_GRADER_YAHOO_CLIENT_SECRET\n"
            "  YAHOO_APP_CLIENT_ID / YAHOO_APP_SECRET\n\n"
            "If they are in api/.env, load it into this shell first:\n"
            "    set -a; source api/.env; set +a"
        )

    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    }
    if SCOPE:
        params["scope"] = SCOPE
    query = urllib.parse.urlencode(params)
    print("\n1. Open this URL and approve access:\n")
    print(f"   {AUTHORIZE_URL}?{query}\n")
    print(f"2. Yahoo redirects to {REDIRECT_URI}/?code=...")
    print("   The page will fail to load — that is expected, nothing is running")
    print("   there. Copy the `code` value out of the browser's URL bar.\n")

    code = input("3. Paste the code here: ").strip()
    if not code:
        sys.exit("no code entered")
    # A pasted full URL is the obvious slip; take the code out of it rather
    # than failing with an opaque Yahoo error.
    if code.startswith("http"):
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)
        code = (parsed.get("code") or [""])[0].strip()
        if not code:
            sys.exit("that URL has no ?code= parameter")

    token = _post_form(TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "code": code,
        "grant_type": "authorization_code",
    })

    access = token.get("access_token", "")
    print("\n--- token ---")
    print(f"expires_in: {token.get('expires_in')} seconds")
    print(f"\nYAHOO_DEV_ACCESS_TOKEN={access}")

    # The refresh token is what the auth plan will store encrypted. Printed so
    # it can be kept for that work, NOT so it goes in a file today.
    if token.get("refresh_token"):
        print("\n(a refresh_token was also issued — the auth plan's encrypted")
        print(" store is its home. Do not commit it or paste it anywhere.)")

    print("\n--- your NFL leagues ---")
    try:
        payload = _get_json(
            f"{FANTASY_BASE}/users;use_login=1/games;game_keys=nfl/leagues"
            "?format=json",
            access,
        )
    except Exception as exc:  # noqa: BLE001 - dev script, report and move on
        print(f"could not list leagues: {exc}")
        print("If this is a 403, the app may lack fantasy read access — see the")
        print("SCOPE note at the top of this file.")
        return

    for key, name, season in _walk_leagues(payload):
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
                found.append((
                    str(node.get("league_key")),
                    str(node.get("name")),
                    str(node.get("season", "?")),
                ))
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
