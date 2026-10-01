import json
from types import SimpleNamespace

import pytest
from app.services.analyst_store import AnalystStore
from app.services.generation.migration import reconcile_legacy
from app.services.generation.models import (
    ContentArtifact,
    LeagueSeason,
    ProviderAttempt,
)
from app.services.generation.planner import collect
from sqlalchemy import func, select


@pytest.mark.asyncio
async def test_yahoo_collection_and_reconciliation_preserve_supported_prose(maker, tmp_path):
    """Mutation: collecting Sleeper Analyst archives for a dotted Yahoo ID aborts refresh."""
    # Production provider-key shape, with synthetic identifiers and prose.
    yahoo_id = "999.l.100000001"
    sleeper_id = "synthetic-sleeper"
    caps = {"format": "redraft", "future_picks": False,
            "roster_continuity": False, "multiyear_history": True}
    saved = {"all": {"owner": {"body": "Saved rating explanation"}}}
    (tmp_path / f"chain_{yahoo_id}.json").write_text(json.dumps({
        "league_id": yahoo_id, "league_season_by_id": {yahoo_id: 2026},
        "owner_rating_blurbs": saved,
    }))
    AnalystStore(tmp_path).save(sleeper_id, {
        "season": 2026, "week": 2, "league_name": "Synthetic league",
        "generated_at": "2026-09-22T12:00:00+00:00", "model": "saved",
        "markdown": "Saved original edition", "facts": {},
    })

    def entry(league_id):
        return SimpleNamespace(
            league_id=league_id, chain=[{"league_id": league_id, "season": 2026,
                                        "format_verified": True}],
            league_season_by_id={league_id: 2026}, league_name_by_id={league_id: "Synthetic league"},
            capabilities=caps, generation_inputs=[], generation_period={},
            trade_stories={}, owner_rating_blurbs={}, franchise_blurbs={},
        )

    yahoo = entry(yahoo_id)
    async with maker.begin() as db:
        await collect(db, yahoo, tmp_path)
        await collect(db, entry(sleeper_id), tmp_path)
    async with maker.begin() as db:
        registered = await db.get(LeagueSeason, yahoo_id)
        assert registered.provider == "yahoo" and registered.verified_at > 0
        first = await reconcile_legacy(db, tmp_path)
        second = await reconcile_legacy(db, tmp_path)
        assert first == second
        assert not first["blocked"] and not first["conflicts"]
        artifacts = (await db.scalars(select(ContentArtifact))).all()
        assert {(row.league_id, row.feature) for row in artifacts} == {
            (yahoo_id, "gm_rating_blurb"), (sleeper_id, "analyst")}
        assert await db.scalar(select(func.count()).select_from(ProviderAttempt)) == 0
    assert yahoo.owner_rating_blurbs == saved
    assert AnalystStore(tmp_path).editions(sleeper_id)[0]["markdown"] == "Saved original edition"
