"""What a league supports, derived from its format plus observed evidence.

Pure — no I/O, no platform knowledge. The format comes off the league itself
(each adapter maps its own encoding onto the shared vocabulary); the three
booleans come from what the data actually shows rather than what the declared
format implies, so a dynasty league with pick trading disabled reports no
future picks and a first-season dynasty league reports no multiyear history.
That is what makes this portable: a non-Sleeper league is described by asking
the same questions of its data, with no branch for where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULT_FORMAT = "dynasty"

# Formats whose rosters carry from one season to the next.
_CONTINUOUS_FORMATS = {"dynasty", "keeper"}


@dataclass(frozen=True)
class LeagueCapabilities:
    format: str              # "dynasty" | "keeper" | "redraft"
    future_picks: bool       # future draft picks are tradeable assets
    roster_continuity: bool  # rosters carry season to season
    multiyear_history: bool  # league chain is longer than one season


# What a cache entry written before this feature reads as. Full dynasty, so
# existing leagues are unaffected until their next refresh stamps the real one.
_LEGACY_DEFAULT = LeagueCapabilities(
    format=_DEFAULT_FORMAT,
    future_picks=True,
    roster_continuity=True,
    multiyear_history=True,
)


def derive_capabilities(
    league,
    *,
    chain_length: int,
    observed_pick_assets: bool,
) -> LeagueCapabilities:
    """Describe what ``league`` supports.

    ``chain_length`` is the number of seasons in the walked league chain.
    ``observed_pick_assets`` is whether any graded trade actually carried a
    draft-pick asset.
    """
    fmt = getattr(league, "format", None) or _DEFAULT_FORMAT
    return LeagueCapabilities(
        format=fmt,
        future_picks=bool(observed_pick_assets),
        roster_continuity=fmt in _CONTINUOUS_FORMATS,
        multiyear_history=chain_length > 1,
    )


def capabilities_to_dict(caps: LeagueCapabilities) -> dict:
    """Serialize for the cache entry / API layer."""
    return {
        "format": caps.format,
        "future_picks": caps.future_picks,
        "roster_continuity": caps.roster_continuity,
        "multiyear_history": caps.multiyear_history,
    }


def capabilities_from_dict(raw: dict | None) -> LeagueCapabilities:
    """Read back, falling back to full dynasty on empty/pre-feature entries."""
    if not raw:
        return _LEGACY_DEFAULT
    return LeagueCapabilities(
        format=str(raw.get("format") or _DEFAULT_FORMAT),
        future_picks=bool(raw.get("future_picks", True)),
        roster_continuity=bool(raw.get("roster_continuity", True)),
        multiyear_history=bool(raw.get("multiyear_history", True)),
    )
