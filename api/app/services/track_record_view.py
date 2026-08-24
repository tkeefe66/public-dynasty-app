"""Build one owner's Track Record from the refresh-computed ``season_records``.

``season_records`` (persisted on ChainCacheEntry, str(year) -> uid -> record) is
the single source of truth for season finishes — it already excludes phantom
roster entries and re-ranks among real teams. This slices it for one owner into
a per-season timeline plus career rollups, so the owner page and the dashboard
Record column never disagree on who won what.
"""

from __future__ import annotations

from app.models.owner import SeasonResultView, TrackRecordView


def build_track_record(
    season_records: dict[str, dict[str, dict]], user_id: str,
) -> TrackRecordView:
    """Per-season + career track record for one owner (empty when absent)."""
    seasons: list[SeasonResultView] = []
    for season in sorted(season_records, key=int):
        rec = season_records[season].get(user_id)
        if rec is None:
            continue
        seasons.append(SeasonResultView(
            season=int(season),
            rank=int(rec.get("rank", 0)),
            of=int(rec.get("total_teams", 0)),
            wins=int(rec.get("wins", 0)),
            losses=int(rec.get("losses", 0)),
            ties=int(rec.get("ties", 0)),
            made_playoffs=bool(rec.get("made_playoffs")),
            champion=bool(rec.get("champion")),
            runner_up=bool(rec.get("runner_up")),
            rounds_won=int(rec.get("rounds_won", 0) or 0),
            playoff_place=rec.get("playoff_place"),
            made_toilet=bool(rec.get("made_toilet")),
            toilet_place=rec.get("toilet_place"),
        ))

    places = [s.playoff_place for s in seasons if s.playoff_place is not None]
    return TrackRecordView(
        seasons=seasons,
        titles=sum(1 for s in seasons if s.champion),
        runner_ups=sum(1 for s in seasons if s.runner_up),
        playoff_appearances=sum(1 for s in seasons if s.made_playoffs),
        seasons_played=len(seasons),
        best_finish=min(places) if places else None,
        career_wins=sum(s.wins for s in seasons),
        career_losses=sum(s.losses for s in seasons),
        career_ties=sum(s.ties for s in seasons),
    )
