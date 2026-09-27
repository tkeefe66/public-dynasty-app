"""Save real Yahoo Fantasy API responses as test fixtures.

The Yahoo adapter is written against these rather than against guessed
payloads. Yahoo's format=json output is XML transliterated, and the exact
nesting varies by resource — any guess would be confidently wrong.

Usage:

    set -a; source api/.env; set +a          # or export the two below
    export YAHOO_DEV_TOKEN_FILE=/path/printed/by/yahoo_dev_token.py
    export YAHOO_DEV_LEAGUE_KEY=your-league-key
    python3 scripts/record_yahoo_fixtures.py

Writes to a private temporary directory outside the repo. Optionally set
YAHOO_FIXTURE_DIR to another directory outside the repo.

Privacy: these payloads contain your league-mates' team names, manager
nicknames, and Yahoo GUIDs. Do not commit raw captures. Anonymize a separate
copy before turning it into a checked-in fixture.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
REPO = pathlib.Path(__file__).resolve().parents[1]


def load_access_token() -> str:
    token_file = (os.environ.get("YAHOO_DEV_TOKEN_FILE") or "").strip()
    if token_file:
        try:
            payload = json.loads(pathlib.Path(token_file).read_text())
            if float(payload["expires_at"]) <= time.time():
                sys.exit(
                    "Yahoo access token expired; re-run scripts/yahoo_dev_token.py."
                )
            token = payload["access_token"]
            if not isinstance(token, str) or not token.strip():
                raise ValueError("missing token")
            return token
        except (OSError, ValueError, TypeError, KeyError):
            sys.exit(
                "Cannot read a valid Yahoo token file; re-run scripts/yahoo_dev_token.py."
            )
    return (os.environ.get("YAHOO_DEV_ACCESS_TOKEN") or "").strip()


def output_directory() -> pathlib.Path:
    configured = (os.environ.get("YAHOO_FIXTURE_DIR") or "").strip()
    out = (
        pathlib.Path(configured).expanduser().resolve()
        if configured
        else pathlib.Path(tempfile.mkdtemp(prefix="yahoo-fixtures-"))
    )
    if out == REPO or REPO in out.parents:
        sys.exit(
            "Raw Yahoo fixtures must stay outside the repository; anonymize copies before committing."
        )
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    return out


# One per seam the adapter has to normalize, plus the two the league half needs.
RESOURCES = {
    "league_meta": "/league/{lk}",
    "league_settings": "/league/{lk}/settings",
    "teams": "/league/{lk}/teams",
    "standings": "/league/{lk}/standings",
    "scoreboard_wk1": "/league/{lk}/scoreboard;week=1",
    # A late week is where is_playoffs / is_consolation actually appear — week 1
    # alone would leave the phase map completely unexercised.
    "scoreboard_wk15": "/league/{lk}/scoreboard;week=15",
    "scoreboard_wk16": "/league/{lk}/scoreboard;week=16",
    "transactions_trades": "/league/{lk}/transactions;types=trade",
    "transactions_all": "/league/{lk}/transactions",
    "draftresults": "/league/{lk}/draftresults",
    "user_leagues": "/users;use_login=1/games;game_keys=nfl/leagues",
}


def main() -> None:
    token = load_access_token()
    league_key = (os.environ.get("YAHOO_DEV_LEAGUE_KEY") or "").strip()
    if not token or not league_key:
        sys.exit(
            "Set YAHOO_DEV_TOKEN_FILE and YAHOO_DEV_LEAGUE_KEY first.\n"
            "Get both from: python3 scripts/yahoo_dev_token.py\n"
            "The access token lasts one hour — re-mint if this 401s."
        )

    if not re.fullmatch(r"(?:\d+|nfl)\.l\.\d+", league_key):
        sys.exit(
            "Invalid Yahoo league key; use the exact key from scripts/yahoo_dev_token.py."
        )
    out = output_directory()
    ok = failed = 0
    for name, path in RESOURCES.items():
        url = f"{BASE}{path.format(lk=league_key)}?format=json"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            print(f"  {exc.code}  {name:22}")
            if exc.code in (401, 403):
                sys.exit(
                    "\nYahoo refused access; check app approval and league access, "
                    "then re-run scripts/yahoo_dev_token.py."
                )
            if exc.code == 429:
                sys.exit(
                    "Yahoo rate limit reached; wait before retrying fixture capture."
                )
            failed += 1
            continue
        except (urllib.error.URLError, TimeoutError, ValueError):
            print(f"  ERR  {name:22} Network failure or invalid response; retry later.")
            failed += 1
            continue

        # Refuse overwrite/symlink targets and create private files even when
        # the caller selected a directory with broader permissions.
        path = out / f"{name}.json"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            sys.exit(
                "Fixture output already exists; select a fresh directory and retry."
            )
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, indent=2)
        print(f"  200  {name:22} -> {path.name}")
        ok += 1

    print(f"\n{ok} recorded, {failed} failed, into {out}")
    if failed:
        print(
            "A failed resource is not necessarily a problem — a league with no\n"
            "trades has no transactions, and a league that never reached week 16\n"
            "has no scoreboard for it. A 403 on everything means the app lacks\n"
            "fantasy read access."
        )


if __name__ == "__main__":
    main()
