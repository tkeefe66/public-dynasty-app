"""Explicit, source-bound coverage for provisional historical full ratings.

Import is an operator attestation after per-season collector validation, just
like historical asset import. No exclusions are inferred during normal refresh.
"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.historical_backfill import digest
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)


class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    season: int
    reason: str = Field(min_length=1)


class PointsResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    season: int
    roster_id: int
    field: Literal["points_for", "points_against"]
    provider: float
    recomputed: float


class ResultsCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal[1] = 1
    season: int
    season_league_id: str = Field(min_length=1)
    identity_version: str
    league_seasons: dict[str, int]
    included_seasons: list[int] = Field(min_length=1)
    excluded_seasons: list[Exclusion] = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_points_resolutions: list[PointsResolution] = Field(default_factory=list)
    verified_by: str = Field(min_length=1)
    verified_at: datetime

    @model_validator(mode="after")
    def partition(self):
        years = set(self.league_seasons.values())
        included = set(self.included_seasons)
        excluded = {x.season for x in self.excluded_seasons}
        if (
            len(years) != len(self.league_seasons)
            or len(included) != len(self.included_seasons)
            or len(excluded) != len(self.excluded_seasons)
            or included & excluded
            or included | excluded != years
            or self.season not in included
            or max(years) != self.season
            or self.league_seasons.get(self.season_league_id) != self.season
        ):
            raise ValueError(
                "Coverage must partition the exact history and include the verified selected year."
            )
        keys = [
            (x.season, x.roster_id, x.field) for x in self.approved_points_resolutions
        ]
        if len(set(keys)) != len(keys) or any(
            x.season not in included for x in self.approved_points_resolutions
        ):
            raise ValueError(
                "Points approvals must uniquely address included seasons only."
            )
        self.included_seasons.sort()
        self.excluded_seasons.sort(key=lambda x: x.season)
        return self


def source_digest(entry, supporting, season):
    """Bind only rating-relevant raw facts; ignore labels/lineups/derived phases."""
    lids = {lid: y for lid, y in entry.league_season_by_id.items() if y <= season}
    records = supporting.get("source_roster_records_by_league")
    if records is None:
        records = supporting.get("roster_records_by_league") or {}
    sources = {}
    for lid, year in sorted(lids.items()):
        sources[lid] = {
            "season": year,
            "membership": entry.roster_to_user_by_league.get(lid, {}),
            "games": [
                [
                    week,
                    rid,
                    {
                        k: (round(float(row[k]), 6) if row.get(k) is not None else None)
                        for k in (
                            "team_points",
                            "opponent_points",
                            "opponent_roster_id",
                        )
                    },
                ]
                for (lg, week, rid), row in sorted(
                    (supporting.get("matchups") or {}).items()
                )
                if lg == lid
            ],
            "records": {
                str(rid): {
                    k: round(float(row[k]), 6) if row.get(k) is not None else None
                    for k in ("wins", "losses", "ties", "points_for", "points_against")
                }
                for rid, row in (records.get(lid) or {}).items()
            },
            **{
                key: (supporting.get(key + "_by_league") or {}).get(lid)
                for key in (
                    "playoff_week_start",
                    "num_playoff_teams",
                    "winners_bracket",
                    "losers_bracket",
                    "postseason_results",
                )
            },
        }
    return digest(
        {"identity_version": entry.owner_identity_version, "seasons": sources}
    )


def make_coverage(entry, supporting, season, *, verified_by, evidence_sha256):
    lids = {lid: y for lid, y in entry.league_season_by_id.items() if y <= season}
    targets = [lid for lid, y in lids.items() if y == season]
    if len(targets) != 1:
        raise ValueError("Coverage requires one selected-season league.")
    return ResultsCoverage(
        season=season,
        season_league_id=targets[0],
        identity_version=entry.owner_identity_version,
        league_seasons=lids,
        included_seasons=supporting.get("verified_result_seasons", []),
        excluded_seasons=[
            {"season": int(y), "reason": why}
            for y, why in supporting.get("excluded_result_seasons", {}).items()
        ],
        source_sha256=source_digest(entry, supporting, season),
        evidence_sha256=evidence_sha256,
        approved_points_resolutions=supporting.get("approved_points_resolutions", []),
        verified_by=verified_by,
        verified_at=datetime.now(UTC),
    )


def apply_coverage(entry, supporting, season, raw):
    policy = ResultsCoverage.model_validate(raw)
    lids = {lid: y for lid, y in entry.league_season_by_id.items() if y <= season}
    if (
        policy.season != season
        or policy.league_seasons != lids
        or policy.identity_version != entry.owner_identity_version
        or policy.source_sha256 != source_digest(entry, supporting, season)
    ):
        raise ValueError(
            "Historical Results source or owner identity changed. Revalidate provisional coverage."
        )
    filtered = {lid: y for lid, y in lids.items() if y in policy.included_seasons}
    # Start with raw records even in a preview, so exact approvals apply once.
    records = deepcopy(
        supporting.get(
            "source_roster_records_by_league",
            supporting.get("roster_records_by_league"),
        )
        or {}
    )
    for approval in policy.approved_points_resolutions:
        lid = next(lid for lid, year in filtered.items() if year == approval.season)
        rows = records.get(lid, {})
        row = rows.get(approval.roster_id, rows.get(str(approval.roster_id), {}))
        if (
            row.get(approval.field) is None
            or abs(row[approval.field] - approval.provider) > 1e-7
        ):
            raise ValueError(
                "Historical Results points approval changed. Revalidate provisional coverage."
            )
        row[approval.field] = approval.recomputed
    return {
        **supporting,
        "league_season_by_id": filtered,
        "matchups": {
            key: row
            for key, row in supporting.get("matchups", {}).items()
            if key[0] in filtered
        },
        "roster_records_by_league": {
            lid: records[lid] for lid in filtered if lid in records
        },
    }, policy


class HistoricalResultsStore:
    def __init__(self, cache_dir):
        self.directory = Path(cache_dir) / "historical-results-coverage"

    def _path(self, lid, season):
        return (
            self.directory
            / hashlib.sha256(lid.encode()).hexdigest()
            / f"{int(season)}.json"
        )

    def import_verified(self, raw):
        policy = ResultsCoverage.model_validate(raw)
        path = self._path(policy.season_league_id, policy.season)
        payload = policy.model_dump(mode="json")
        if path.exists() and json.loads(path.read_text()) != payload:
            raise ValueError(
                "Different coverage already exists. Review and archive before correcting it."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, payload)
        log.info(
            "historical Results coverage imported season=%s path=%s",
            policy.season,
            path,
        )
        return path

    def load(self, lid, season):
        path = self._path(lid, season)
        if not path.exists():
            return None
        try:
            return ResultsCoverage.model_validate_json(path.read_text()).model_dump(
                mode="json"
            )
        except (OSError, ValueError) as exc:
            log.exception("historical Results coverage invalid season=%s", season)
            raise ValueError(
                "Historical Results coverage is invalid. Review and reimport it."
            ) from exc
