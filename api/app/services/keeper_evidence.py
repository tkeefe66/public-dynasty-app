"""Provider-neutral keeper reconstruction and season-bound format evidence.

Adapters normalize owners and player IDs before calling the detector. Drafted
again is deliberately only a candidate: overlap does not prove retention.
"""

import hashlib
import json
import logging
import re
from copy import copy
from pathlib import Path

from app.services.historical_backfill import digest
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)


def resolve_season_formats(chain, store, *, prior_chain=()):
    """Resolve reviewed evidence before pricing, drafts, and capabilities.

    Preserve provider verification separately; member evidence must never be
    reported as a provider setting. Conflicts and lost records fail closed.
    """
    required = {(r.get("league_id"), r.get("season")) for r in prior_chain
                if r.get("format_evidence") or r.get("requires_format_evidence")}
    resolved = []
    for source in chain:
        league = copy(source)
        league.effective_format_verified = getattr(source, "format_verified", False) is True
        league.format_evidence = None
        league.format_error = None
        league.requires_format_evidence = (league.league_id, league.season) in required
        try:
            evidence = store.load(league.league_id, league.season) if store else None
            if evidence:
                league.requires_format_evidence = True
                if league.effective_format_verified and league.format != evidence["format"]:
                    raise ValueError("Provider and reviewed season format conflict; review both sources.")
                league.format = evidence["format"]
                league.format_evidence = evidence
                league.effective_format_verified = True
            elif league.requires_format_evidence:
                raise ValueError("Reviewed season format evidence is missing; restore its verified record.")
        except (ValueError, OSError) as exc:
            league.effective_format_verified = False
            league.format_error = str(exc)
            log.error("season format unavailable league=%s season=%s: %s",
                      league.league_id, league.season, exc)
        resolved.append(league)
    return resolved


def detect_keepers(
    *,
    previous,
    opening,
    draft,
    attested_format=None,
    provider_format=None,
    keeper_limit=None,
):
    confirmed = sorted(
        {(p["owner"], p["player"]) for p in draft if p.get("keeper") is True}
    )
    drafted = {(p["owner"], p["player"]) for p in draft}
    candidates = [
        {"owner": owner, "player": player, "drafted_again": (owner, player) in drafted}
        for owner in sorted(opening)
        for player in sorted(set(opening[owner]) & set(previous.get(owner, [])))
        if (owner, player) not in confirmed
    ]
    formats = {f for f in (attested_format, provider_format) if f is not None}
    if not formats <= {"keeper", "redraft", "dynasty"}:
        raise ValueError("Unknown format evidence; normalize provider metadata first.")
    if confirmed:
        formats.add("keeper")
    # Dynasty leagues may also mark retained startup players; do not demote.
    conflict = len(formats) > 1 and formats != {"dynasty", "keeper"}
    fmt = (
        None
        if conflict
        else "dynasty"
        if "dynasty" in formats
        else next(iter(formats), None)
    )
    counts = {owner: sum(o == owner for o, _ in confirmed) for owner, _ in confirmed}
    if keeper_limit is not None and (
        type(keeper_limit) is not int
        or keeper_limit < 0
        or any(n > keeper_limit for n in counts.values())
    ):
        raise ValueError("Keeper allowance conflicts with observed retained players.")
    return {
        "format": fmt,
        "conflict": conflict,
        "confirmed": [{"owner": o, "player": p} for o, p in confirmed],
        "candidates": candidates,
        "observed_max": max(counts.values(), default=0),
        "keeper_limit": keeper_limit,
    }


class SeasonFormatStore:
    """Reviewed evidence is immutable, dated by league ID, never copied forward."""

    def __init__(self, cache_dir):
        self.directory = Path(cache_dir) / "season-format-evidence"

    def path(self, league_id, season):
        return (
            self.directory
            / hashlib.sha256(league_id.encode()).hexdigest()
            / f"{int(season)}.json"
        )

    def save(self, league_id, season, evidence):
        if (
            evidence.get("format") not in {"redraft", "keeper", "dynasty"}
            or not evidence.get("basis")
            or not isinstance(evidence.get("evidence_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", evidence["evidence_sha256"])
        ):
            raise ValueError(
                "Format requires reviewed provenance and an evidence digest."
            )
        payload = {
            **evidence,
            "version": 1,
            "league_id": league_id,
            "season": int(season),
        }
        payload["sha256"] = digest(payload)
        path = self.path(league_id, season)
        if path.exists() and json.loads(path.read_text()) != payload:
            raise ValueError(
                "Different format evidence exists; review before replacing it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, payload)
        log.info(
            "season format evidence saved league=%s season=%s format=%s",
            league_id,
            season,
            payload["format"],
        )

    def load(self, league_id, season):
        path = self.path(league_id, season)
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(  # noqa: TRY004 -- corrupt persisted data
                "Season format evidence must be an object; restore its verified record."
            )
        if raw.get("sha256") != digest({k: v for k, v in raw.items() if k != "sha256"}):
            raise ValueError(
                "Season format evidence hash mismatch; review source evidence."
            )
        if (
            raw.get("version") != 1
            or raw.get("league_id") != league_id
            or raw.get("season") != int(season)
            or raw.get("format") not in {"keeper", "redraft", "dynasty"}
        ):
            raise ValueError(
                "Season format evidence does not match requested league/year."
            )
        return raw
