"""Create an ingestion client with caller-scoped credentials.

Developer tokens are deliberately not read from process environment here.
Production Yahoo refresh stays unavailable until account-scoped OAuth lands.
"""

import re

from sleeper_dynasty.api.platform import PLATFORM_SLEEPER, platform_for_league_id
from sleeper_dynasty.api.sleeper import SleeperClient


class YahooCredentialsMissing(RuntimeError):
    """The caller has no authorized Yahoo connection for this league."""


def client_for_league(league_id: str, *, access_token: str | None = None):
    platform = platform_for_league_id(league_id)
    if platform == PLATFORM_SLEEPER:
        return SleeperClient()
    if not re.fullmatch(r"\d+\.l\.\d+", league_id):
        raise ValueError("Invalid Yahoo league key.")
    if not access_token:
        raise YahooCredentialsMissing(
            "Yahoo account connection is required before this league can refresh."
        )
    from sleeper_dynasty.api.yahoo import YahooAdapter

    return YahooAdapter(access_token)
