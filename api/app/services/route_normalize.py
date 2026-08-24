"""Map a raw URL pathname to a low-cardinality route template + league id.

Pure and deterministic — the single source of truth for how telemetry buckets
pages. Known App-Router shapes map to explicit templates; unknown shapes get
id-looking segments masked so a stray path can't explode `route` cardinality.
"""
from __future__ import annotations

import re

# Exact, parameterless routes.
_STATIC = {
    "/",
    "/admin",
    "/account",
    "/leagues/add",
    "/login",
    "/methodology",
}

# A segment that looks like an id (digits, or contains a digit, or long token).
_ID_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]+$")


def _looks_like_id(seg: str) -> bool:
    return bool(_ID_RE.match(seg)) or len(seg) >= 16


def normalize_route(path: str) -> tuple[str, str | None]:
    # Drop any query string / fragment and trailing slash (keep root "/").
    path = path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    if not path:
        path = "/"

    if path in _STATIC:
        return path, None

    parts = path.strip("/").split("/")

    # /admin/user/[id]
    if parts[:2] == ["admin", "user"] and len(parts) == 3:
        return "/admin/user/[id]", None

    # /league/[id]/...
    if parts[0] == "league" and len(parts) >= 2:
        league_id = parts[1]
        rest = parts[2:]
        if not rest:
            return "/league/[id]", league_id
        if rest == ["gm"]:
            return "/league/[id]/gm", league_id
        if rest == ["settings"]:
            return "/league/[id]/settings", league_id
        if rest[:1] == ["owner"] and len(rest) == 2:
            return "/league/[id]/owner/[uid]", league_id
        if rest[:1] == ["trade"] and len(rest) == 2:
            return "/league/[id]/trade/[tid]", league_id
        # Unknown sub-route under a known league: mask the tail.
        masked = "/".join("[seg]" if _looks_like_id(p) else p for p in rest)
        return f"/league/[id]/{masked}", league_id

    # Fallback: mask id-looking segments, no league.
    masked = "/".join("[seg]" if _looks_like_id(p) else p for p in parts)
    return "/" + masked, None
