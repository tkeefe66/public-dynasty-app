"""Replayable full-player pick estimates using a single dated player board."""

from copy import deepcopy
from datetime import date
from math import isfinite
from types import SimpleNamespace

from app.services.full_player_pick_values import with_full_player_pick_values


def estimate(
    *,
    season,
    league_id,
    cutoff,
    source,
    format,
    draft,
    picks,
    positions,
    board,
    exclude_idp=False,
    reconstruction=None,
):
    if (
        source not in {"stats_guy", "dynasty_process"}
        or format not in {"sf_dynasty", "non_sf_dynasty"}
        or board.get("format") != format
        or board.get("tep") != "std"
        or not 1
        <= (date.fromisoformat(cutoff) - date.fromisoformat(board["asOf"])).days
        <= 7
        or board.get("offset", 0) != 0
        or len(board["rankings"]) != board["total"]
    ):
        raise ValueError(
            "Historical pick board is incomplete, stale, future, or wrong-format."
        )
    values = {str(p["id"]): p for p in board["rankings"]}
    if len(values) != len(board["rankings"]) or any(
        not isfinite(float(p["value"])) or float(p["value"]) < 0
        for p in values.values()
    ):
        raise ValueError(
            "Historical pick board has duplicate players or invalid prices."
        )
    if any(
        pid in values and values[pid]["position"] != pos
        for pid, pos in positions.items()
    ):
        raise ValueError(
            "Historical draft player position disagrees with price evidence."
        )
    league = SimpleNamespace(
        league_id=league_id,
        season=season,
        format="keeper",
        total_rosters=draft["settings"]["teams"],
        format_evidence={},
    )
    support = {
        "positions": positions,
        "ktc_by_player_id": {
            pid: SimpleNamespace(superflex_value=float(p["value"]))
            for pid, p in values.items()
        },
        "player_value_sources": {pid: source for pid in values},
    }
    valuation_picks = picks
    if reconstruction is not None:
        from app.services.keeper_placeholders import normalize

        valuation_picks = normalize(
            season=season,
            league_id=league_id,
            draft=draft,
            picks=picks,
            evidence=reconstruction,
        )
    result = with_full_player_pick_values(
        league,
        [draft],
        {draft["draft_id"]: valuation_picks},
        support,
        prices_as_of=board["asOf"],
        exclude_idp=exclude_idp,
    )
    receipt = result["full_player_pick_valuation"]
    if receipt["status"] != "ready":
        raise ValueError(receipt["reason"])
    return deepcopy(
        {
            "season": season,
            "league_id": league_id,
            "cutoff": cutoff,
            "source": source,
            "format": format,
            "draft": draft,
            "picks": picks,
            "positions": positions,
            "board": board,
            "exclude_idp": exclude_idp,
            "estimate": receipt,
            **(
                {"reconstruction": reconstruction} if reconstruction is not None else {}
            ),
        }
    )


def validate(receipt):
    try:
        replay = estimate(**{k: v for k, v in receipt.items() if k != "estimate"})
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Historical pick estimate replay failed: {exc}") from exc
    if replay != receipt:
        raise ValueError("Historical pick estimate replay does not match saved values.")
    return replay["estimate"]


def snapshot_valuation(snapshot):
    """Only a validated, result-bound manifest may make a dated rating provisional."""
    source = snapshot.get("asset_source") or {}
    if not source.get("pick_valuation"):
        return None
    from app.services.historical_rating_assets import HistoricalRatingAssets
    from app.services.season_ratings import historical_results_digest

    try:
        assets = HistoricalRatingAssets.model_validate(source)
        if (
            assets.validation is None
            or assets.validation.result_inputs_sha256
            != historical_results_digest(snapshot)
            or assets.format != snapshot.get("format")
            or set(assets.owners) != set(snapshot.get("owners", []))
            or assets.as_of.isoformat() != snapshot.get("as_of")
        ):
            return None
        signals, ranks = assets.signals()
        if signals != snapshot.get("outlook_signals") or ranks != snapshot.get(
            "roster_ranks"
        ):
            return None
        return assets.pick_valuation["estimate"]
    except (KeyError, TypeError, ValueError):
        return None
