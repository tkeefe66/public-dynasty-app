"""Display-only league names for owner records, including failed first imports."""

from sqlalchemy import func, select

from app.db.models import LeagueMembership
from app.services.generation.models import LeagueSeason, LeagueSeries


async def attach_league_names(db, records: list[dict]) -> None:
    """Enrich a bounded admin page without provider calls or identity changes.

    A first import can fail before the generation registry exists. The name
    captured with its membership remains useful for display; it never verifies
    league continuity, capabilities, or authorization.
    """
    league_ids = sorted({row["league_id"] for row in records if row.get("league_id")})
    if not league_ids:
        return
    names = {
        league_id: name.strip()
        for league_id, name in await db.execute(
            select(LeagueSeason.league_id, LeagueSeries.name)
            .join(LeagueSeries, LeagueSeries.id == LeagueSeason.series_id)
            .where(LeagueSeason.league_id.in_(league_ids))
        )
        if name and name.strip()
    }
    missing = [league_id for league_id in league_ids if league_id not in names]
    if missing:
        captured = select(
            LeagueMembership.league_id,
            LeagueMembership.league_name,
            func.row_number().over(
                partition_by=LeagueMembership.league_id,
                order_by=(LeagueMembership.added_at.desc(), LeagueMembership.id.desc()),
            ).label("position"),
        ).where(
            LeagueMembership.league_id.in_(missing),
            LeagueMembership.league_name.is_not(None),
            func.trim(LeagueMembership.league_name) != "",
        ).subquery()
        for league_id, name in await db.execute(
            select(captured.c.league_id, captured.c.league_name)
            .where(captured.c.position == 1)
        ):
            names[league_id] = name.strip()
    for row in records:
        if row.get("league_id"):
            row["league_name"] = names.get(row["league_id"])
