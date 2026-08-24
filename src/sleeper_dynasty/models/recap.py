"""Structured 'facts packet' models for the weekly recap.

These dataclasses are the contract between the FactsBuilder (engine/recap.py)
and the RecapWriter (llm/recap_writer.py). The writer serializes them to JSON
and is instructed to joke ONLY about facts present here — so every number the
comedy references is engine-verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlayerLine:
    """One player's line in a recap beat (hero, goat, bust, bench)."""
    player: str
    owner: str
    points: float
    position: str | None = None
    projected: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"player": self.player, "owner": self.owner, "points": self.points}
        if self.position is not None:
            d["position"] = self.position
        if self.projected is not None:
            d["projected"] = self.projected
        return d


@dataclass
class MatchupRecap:
    winner: str
    loser: str
    winner_points: float
    loser_points: float
    margin: float
    blowout: bool
    nailbiter: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner, "loser": self.loser,
            "winner_points": self.winner_points,
            "loser_points": self.loser_points,
            "margin": self.margin,
            "blowout": self.blowout, "nailbiter": self.nailbiter,
        }


@dataclass
class BenchRegret:
    owner: str
    points_left_on_bench: float
    benched_hero: PlayerLine
    started_dud: PlayerLine

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "points_left_on_bench": self.points_left_on_bench,
            "benched_hero": self.benched_hero.to_dict(),
            "started_dud": self.started_dud.to_dict(),
        }


@dataclass
class LuckNote:
    owner: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {"owner": self.owner, "note": self.note}


@dataclass
class RecapFacts:
    week: int
    league_name: str
    standings: list[dict[str, Any]]
    matchups: list[MatchupRecap]
    high_scorer: dict[str, Any] | None
    low_scorer: dict[str, Any] | None
    bench_regret: list[BenchRegret]
    lucky: list[LuckNote]
    unlucky: list[LuckNote]
    heroes: list[PlayerLine]
    goats: list[PlayerLine]
    busts: list[PlayerLine]

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "league_name": self.league_name,
            "standings": self.standings,
            "matchups": [m.to_dict() for m in self.matchups],
            "high_scorer": self.high_scorer,
            "low_scorer": self.low_scorer,
            "bench_regret": [b.to_dict() for b in self.bench_regret],
            "lucky": [n.to_dict() for n in self.lucky],
            "unlucky": [n.to_dict() for n in self.unlucky],
            "heroes": [p.to_dict() for p in self.heroes],
            "goats": [p.to_dict() for p in self.goats],
            "busts": [p.to_dict() for p in self.busts],
        }


@dataclass
class MatchupPreview:
    home: str
    away: str
    home_projected: float
    away_projected: float
    favorite: str
    spread: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "home": self.home, "away": self.away,
            "home_projected": self.home_projected,
            "away_projected": self.away_projected,
            "favorite": self.favorite, "spread": self.spread,
        }


@dataclass
class ByeTrouble:
    owner: str
    players_on_bye: list[str]
    likely_replacement: str | None
    replacement_projected: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "players_on_bye": self.players_on_bye,
            "likely_replacement": self.likely_replacement,
            "replacement_projected": self.replacement_projected,
        }


@dataclass
class WeatherNote:
    game: str
    wind_mph: float | None
    temp_f: float | None
    precip: str | None
    affected_players: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "game": self.game, "wind_mph": self.wind_mph,
            "temp_f": self.temp_f, "precip": self.precip,
            "affected_players": self.affected_players,
        }


@dataclass
class PlayoffStake:
    owner: str
    status: str  # must-win | can-clinch | eliminated | spoiler | in-the-hunt

    def to_dict(self) -> dict[str, Any]:
        return {"owner": self.owner, "status": self.status}


@dataclass
class OutlookFacts:
    week: int
    matchups: list[MatchupPreview]
    byes: list[ByeTrouble]
    weather: list[WeatherNote]
    playoff_stakes: list[PlayoffStake]

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "matchups": [m.to_dict() for m in self.matchups],
            "byes": [b.to_dict() for b in self.byes],
            "weather": [w.to_dict() for w in self.weather],
            "playoff_stakes": [p.to_dict() for p in self.playoff_stakes],
        }
