"""Operator-verified historical assets, kept separate from today's price cache.

The import CLI makes no network or model calls and never infers ownership.
Refresh independently checks completed-week schedule evidence. Import only
after checking the source roster, complete pick ledger, and dated prices.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sleeper_dynasty.engine.asset_signals import asset_signals
from sleeper_dynasty.util.atomic import write_json_atomic

log = logging.getLogger(__name__)


class HistoricalPlayer(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    player_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    value: float = Field(ge=0)
    birth_date: date


class HistoricalPick(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    season: int
    round: int = Field(ge=1)
    original_owner_id: str
    owner_id: str
    value: float = Field(ge=0)


class HistoricalRatingAssets(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: Literal[1]
    season: int = Field(ge=2000, le=2100)
    season_league_id: str = Field(min_length=1)
    format: Literal["dynasty", "keeper"]
    as_of: date
    through_week: int = Field(ge=1, le=18)
    prices_as_of: date
    identity_version: str
    verified_by: str = Field(min_length=1)
    verified_at: date
    roster_source: str = Field(min_length=1)
    picks_source: str = Field(min_length=1)
    prices_source: str = Field(min_length=1)
    owners: list[str] = Field(min_length=2)
    # The attested future-pick inventory; zero rounds means the source
    # explicitly confirms no future draft assets, not that a fetch failed.
    draft_rounds: int = Field(ge=0, le=30)
    pick_horizon: int = Field(ge=1, le=3)
    players: list[HistoricalPlayer] = Field(min_length=1)
    picks: list[HistoricalPick]

    @model_validator(mode="after")
    def complete_at_cutoff(self):
        if not date(self.season, 12, 1) <= self.as_of <= date(self.season + 1, 2, 28):
            raise ValueError("Cutoff must be at the end of the selected fantasy season.")
        if not 0 <= (self.as_of - self.prices_as_of).days <= 7:
            raise ValueError("Prices must be on or before cutoff and no more than seven days old.")
        if self.verified_at < self.as_of:
            raise ValueError("Verification cannot predate the historical cutoff.")
        owners = set(self.owners)
        if len(owners) != len(self.owners) or any(not uid.strip() for uid in owners):
            raise ValueError("Owners must be distinct nonempty identities.")
        if {p.owner_id for p in self.players} != owners:
            raise ValueError("Every historical owner must have a verified roster.")
        if len({p.player_id for p in self.players}) != len(self.players):
            raise ValueError("A player cannot belong to multiple historical rosters.")
        if any(not 15 <= (self.as_of - p.birth_date).days / 365.25 <= 60 for p in self.players):
            raise ValueError("Player birth dates must establish a plausible age at cutoff.")
        expected = {(y, r, uid) for y in range(self.season + 1, self.season + self.pick_horizon + 1)
                    for r in range(1, self.draft_rounds + 1) for uid in owners}
        actual = {(p.season, p.round, p.original_owner_id) for p in self.picks}
        if actual != expected or len(actual) != len(self.picks) or any(p.owner_id not in owners for p in self.picks):
            raise ValueError("Historical future-pick inventory is incomplete, duplicated, or has unknown owners.")
        if sum(p.value for p in self.players) <= 0:
            raise ValueError("Historical roster prices cannot all be zero.")
        return self

    def signals(self) -> tuple[dict, dict]:
        ages = {p.player_id: self.as_of.year - p.birth_date.year - (
            (self.as_of.month, self.as_of.day) < (p.birth_date.month, p.birth_date.day)) for p in self.players}
        signals = asset_signals(
            current_holders={p.player_id: p.owner_id for p in self.players},
            value_by_player={p.player_id: p.value for p in self.players},
            age_by_player=ages, owners=self.owners)
        values = {uid: sum(p.value for p in self.players if p.owner_id == uid) for uid in self.owners}
        ranks = {uid: {"rank": 1 + sum(v > values[uid] for v in values.values()), "of": len(values)}
                 for uid in values}
        for uid in self.owners:
            signals[uid]["roster_value"] = values[uid]
            signals[uid]["draft_capital"] = sum(p.value for p in self.picks if p.owner_id == uid)
        return signals, ranks


class HistoricalAssetStore:
    def __init__(self, cache_dir: Path, league_id: str):
        self.directory = Path(cache_dir) / "historical-rating-assets"
        self.chain_id = league_id

    def _path(self, season_league_id: str, season: int) -> Path:
        # Historical league IDs survive a chain rollover; newest chain IDs do not.
        return self.directory / hashlib.sha256(season_league_id.encode()).hexdigest() / f"{int(season)}.json"

    def exists(self, season_league_id: str, season: int) -> bool:
        return self._path(season_league_id, season).exists()

    def import_verified(self, raw: dict) -> Path:
        manifest = HistoricalRatingAssets.model_validate(raw)
        path = self._path(manifest.season_league_id, manifest.season)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Corrections must be explicit: never silently overwrite evidence.
        payload = manifest.model_dump(mode="json")
        if path.exists() and json.loads(path.read_text()) != payload:
            raise ValueError("A different manifest already exists. Review and archive it before importing a correction.")
        write_json_atomic(path, payload)
        log.info("historical rating assets imported chain=%s season=%s path=%s", self.chain_id, manifest.season, path)
        return path

    def load(self, *, season: int, season_league_id: str, owners: list[str], format: str,
             identity_version: str, through_week: int, cutoff_date: str | None = None):
        path = self._path(season_league_id, season)
        if not path.exists():
            return None, "Verified historical roster, pick ownership, and asset prices are missing."
        try:
            assets = HistoricalRatingAssets.model_validate_json(path.read_text())
        except (OSError, ValueError):
            log.exception("historical rating assets invalid season=%s path=%s", season, path)
            return None, "Historical asset evidence is invalid. Review and reimport the verified snapshot."
        if (assets.season != season or assets.season_league_id != season_league_id
                or set(assets.owners) != set(owners) or assets.format != format
                or assets.identity_version != identity_version or assets.through_week != through_week):
            return None, "Historical asset evidence does not match this season, owner mapping, format, or final week."
        if cutoff_date is None:
            return None, "The historical season-end cutoff has not been independently verified. Refresh league data."
        if assets.as_of.isoformat() != cutoff_date:
            return None, "Historical asset cutoff does not match the verified final-week date. Review the source manifest."
        return assets, None

    async def verified_week_cutoff(self, season: int, week: int) -> str:
        """Immutable completed-week evidence, fetched only for an existing import.

        Normalize to 00:00 UTC on the day after the last game's UTC kickoff
        date. The entire NFL week must be completed. Never guess from calendar
        arithmetic or accept an importer-supplied final-week date as proof.
        """
        from sleeper_dynasty.api.nfl_schedule import (
            fetch_week_evidence,
            parse_scoreboard,
        )
        path = self.directory / "week-evidence" / f"{int(season)}-{int(week)}.json"
        evidence = json.loads(path.read_text()) if path.exists() else await fetch_week_evidence(season, week)
        raw = json.loads(evidence["raw"])
        if int((raw.get("season") or {}).get("year", 0)) != season or int((raw.get("week") or {}).get("number", 0)) != week:
            raise ValueError("NFL evidence season/week does not match the requested historical cutoff")
        games = parse_scoreboard(raw, strict=True)
        if not games or any(not g["completed"] or not g["kickoff"] for g in games):
            raise ValueError("NFL final-week evidence is incomplete; historical cutoff remains unverified")
        last_kickoff = max(datetime.fromisoformat(g["kickoff"]) for g in games)
        cutoff = (last_kickoff.date() + timedelta(days=1)).isoformat()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(path, evidence)
        return cutoff


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Validate/import operator-verified historical rating assets; no network calls.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--league-id", required=True, help="Current chain league ID")
    parser.add_argument("--apply", action="store_true", help="Persist after validation (default: dry run)")
    args = parser.parse_args()
    try:
        raw = json.loads(args.input.read_text())
        manifest = HistoricalRatingAssets.model_validate(raw)
        if args.apply:
            path = HistoricalAssetStore(args.cache_dir, args.league_id).import_verified(raw)
            print(f"Imported season {manifest.season}: {path}. Run a free league refresh to calculate ratings.")
        else:
            print(f"Valid season {manifest.season} manifest; {len(manifest.owners)} owners. Nothing written.")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Historical asset import failed: {exc}\nCorrect the source manifest and retry.\n")


if __name__ == "__main__":
    main()
