from __future__ import annotations

import pytest

from app.services.route_normalize import normalize_route


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/", ("/", None)),
        ("/admin", ("/admin", None)),
        ("/admin/user/u123", ("/admin/user/[id]", None)),
        ("/account", ("/account", None)),
        ("/leagues/add", ("/leagues/add", None)),
        ("/login", ("/login", None)),
        ("/methodology", ("/methodology", None)),
        ("/league/123", ("/league/[id]", "123")),
        ("/league/123/", ("/league/[id]", "123")),
        ("/league/123/gm", ("/league/[id]/gm", "123")),
        ("/league/123/settings", ("/league/[id]/settings", "123")),
        ("/league/123/owner/abc", ("/league/[id]/owner/[uid]", "123")),
        ("/league/123/trade/t9", ("/league/[id]/trade/[tid]", "123")),
        # Unknown shape: id-looking segments masked, no league.
        ("/wat/99/x", ("/wat/[seg]/x", None)),
    ],
)
def test_normalize_route(path, expected):
    assert normalize_route(path) == expected
