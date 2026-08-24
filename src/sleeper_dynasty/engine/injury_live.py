"""Map a Sleeper players-dump raw record to a live-injury summary for the 'currently out' badge."""

from __future__ import annotations

# Sleeper injury_status values that mean a player is currently unavailable DUE TO INJURY.
# Deliberately excludes "Doubtful"/"Questionable" (game-time decisions that often play) and
# "Suspended" (not an injury) — this badge is "currently out hurt", not "any roster note".
_OUT_LIKE = {"Out", "IR", "PUP"}


def live_injury(raw: dict) -> dict:
    status = (raw or {}).get("injury_status")
    return {
        "currently_out": status in _OUT_LIKE,
        "status": status,
        "body_part": (raw or {}).get("injury_body_part"),
        "since": (raw or {}).get("injury_start_date"),
    }
