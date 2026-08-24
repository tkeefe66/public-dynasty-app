"""Save real Yahoo Fantasy API responses as test fixtures.

The Yahoo adapter is written against these rather than against guessed
payloads. Yahoo's format=json output is XML transliterated, and the exact
nesting varies by resource — any guess would be confidently wrong.

Usage:

    set -a; source api/.env; set +a          # or export the two below
    export YAHOO_DEV_ACCESS_TOKEN=...        # scripts/yahoo_dev_token.py
    export YAHOO_DEV_LEAGUE_KEY=461.l.123456
    python3 scripts/record_yahoo_fixtures.py

Writes tests/fixtures/yahoo/<name>.json. Run once; commit the results.

Privacy: these payloads contain your league-mates' team names, manager
nicknames, and Yahoo GUIDs. This repo is private, so that is acceptable — but
do not copy fixtures into a public issue, gist, or bug report.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "yahoo"

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
    token = (os.environ.get("YAHOO_DEV_ACCESS_TOKEN") or "").strip()
    league_key = (os.environ.get("YAHOO_DEV_LEAGUE_KEY") or "").strip()
    if not token or not league_key:
        sys.exit(
            "Set YAHOO_DEV_ACCESS_TOKEN and YAHOO_DEV_LEAGUE_KEY first.\n"
            "Get both from: python3 scripts/yahoo_dev_token.py\n"
            "The access token lasts one hour — re-mint if this 401s."
        )

    OUT.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for name, path in RESOURCES.items():
        url = f"{BASE}{path.format(lk=league_key)}?format=json"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()[:200].replace("\n", " ")
            print(f"  {exc.code}  {name:22} {body}")
            if exc.code == 401:
                sys.exit(
                    "\n401 — the access token expired (they last one hour). "
                    "Re-run scripts/yahoo_dev_token.py and try again."
                )
            failed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - dev script
            print(f"  ERR  {name:22} {exc}")
            failed += 1
            continue

        (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2))
        print(f"  200  {name:22} -> tests/fixtures/yahoo/{name}.json")
        ok += 1

    print(f"\n{ok} recorded, {failed} failed, into {OUT}")
    if failed:
        print(
            "A failed resource is not necessarily a problem — a league with no\n"
            "trades has no transactions, and a league that never reached week 16\n"
            "has no scoreboard for it. A 403 on everything means the app lacks\n"
            "fantasy read access."
        )


if __name__ == "__main__":
    main()
