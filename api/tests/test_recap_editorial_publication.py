import pytest
from app.services.generation.models import ContentArtifact
from app.services.generation.store import Held


@pytest.mark.asyncio
async def test_editorial_script_cannot_use_standing_publication_approval(maker, monkeypatch):
    # Mutation: treat editorial script approval as finished-media publication approval.
    from app.services.recap_video import publication, qualification
    async def verified(db, episode_id, media_id):
        return {}, 'editorial-script'
    monkeypatch.setattr(publication, 'verified_media', verified)
    async with maker.begin() as db:
        db.add(ContentArtifact(id='editorial-script', series_id='series', league_id='synthetic',
            feature='recap_video', subject='synthetic-video', revision=1,
            payload_json='{}', digest='synthetic', facts_json='{}', provenance='editorial_reviewed'))
    async with maker.begin() as db:
        with pytest.raises(Held, match='recap_editorial_publication_review_required'):
            await qualification.record_standing_approval(db, 'episode', 0, 'media')
