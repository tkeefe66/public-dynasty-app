"""FantasyCalc dynasty-value fallback.

FantasyCalc publishes a 0-10000ish integer value scale similar to KTC.
Used as a SECONDARY source for players KTC doesn't rank (KTC caps at
top 500). FantasyCalc's API returns Sleeper IDs directly, so we
build a dict[sleeper_player_id, value] with no name normalization.

We fetch Superflex (numQbs=2) and 1QB (numQbs=1) variants separately.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

_FC_URL = "https://api.fantasycalc.com/values/current"


async def fetch_fantasycalc_values(
    *, dynasty: bool = True
) -> dict[str, dict[str, int]]:
    """Fetch FantasyCalc values keyed by Sleeper player_id.

    Args:
        dynasty: True for dynasty values, False for redraft. Redraft leagues
            must use redraft values — dynasty pricing carries a rookie/youth
            premium that is simply wrong when there is no next season.

    Returns:
        Dict mapping sleeper_player_id -> {"superflex": int, "one_qb": int}.
        Missing format values are absent (not None). Empty dict on network
        failure — graceful degradation matching the KTC fetcher.

    Note: the redraft set is thinner than the dynasty set (~200 players vs
    ~474). Players absent from it resolve to no value, the same as any other
    unmatched player. Do NOT fall back to dynasty values to fill the gap —
    that reintroduces exactly the pricing this exists to avoid.
    """
    log.info("Fetching FantasyCalc %s values", "dynasty" if dynasty else "redraft")
    out: dict[str, dict[str, int]] = {}

    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True
    ) as client:
        for num_qbs, format_key in ((2, "superflex"), (1, "one_qb")):
            try:
                resp = await client.get(
                    _FC_URL,
                    params={
                        "isDynasty": "true" if dynasty else "false",
                        "numQbs": str(num_qbs),
                        "numTeams": "12",
                        "ppr": "1",
                    },
                )
                resp.raise_for_status()
                data: list[dict[str, Any]] = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning(
                    "FantasyCalc fetch failed for numQbs=%d: %s", num_qbs, e
                )
                continue
            for entry in data:
                player = entry.get("player") or {}
                sleeper_id = player.get("sleeperId")
                value = entry.get("value")
                if not sleeper_id or value is None:
                    continue
                bucket = out.setdefault(str(sleeper_id), {})
                try:
                    bucket[format_key] = int(value)
                except (TypeError, ValueError):
                    continue
    log.info("FantasyCalc returned %d players", len(out))
    return out
