"""API-owned spelling reviews. Generated prose and workers have no write path.

Reviews preserve their original artifact/reviewer. Each media plan snapshots a
new immutable binding; reuse requires the same source person, name and season.
"""
import json
from types import SimpleNamespace

from sqlalchemy import select
from sleeper_dynasty.llm.recap_video_writer import Script
from app.services.generation.commands import require_actor
from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationOperation
from app.services.generation.recap_models import RecapEpisode, RecapSpeechReview
from app.services.generation.store import Held, audit, digest, dump, lock_control
from app.services.recap_video.audio import _tokens, script_segments, validate_alias_spellings

VERSION = "reviewed-spellings-v1"
FIELDS = ("id", "series_id", "season", "entity_kind", "entity_id", "canonical_name", "canonical_token", "reusable",
    "aliases_json", "script_id", "script_digest", "script_revision", "reviewer_id", "reason", "created_at")


async def context(db, artifact):
    if not artifact or artifact.feature != "recap_video" or artifact.provenance != "managed":
        raise Held("speech_review_script_invalid")
    payload = json.loads(artifact.payload_json)
    if digest(payload) != artifact.digest:
        raise Held("speech_review_script_changed")
    Script.model_validate({k: v for k, v in payload["script"].items() if k != "reviews"})
    episode = await db.get(RecapEpisode, payload["episode_id"])
    if not episode or episode.series_id != artifact.series_id:
        raise Held("speech_review_episode_changed")
    entities = {}
    def add(kind, identity, name):
        if isinstance(identity, str) and identity and isinstance(name, str) and name:
            key = (kind, identity)
            if key in entities and entities[key] != name:
                raise Held("speech_review_entity_ambiguous")
            entities[key] = name
    for owner in payload["claims"].get("owners", []):
        add("owner", owner.get("id"), owner.get("name"))
    for claim in payload["claims"].get("claims", []):
        for operand in claim.get("operands", []):
            add("player", operand.get("player_id"), operand.get("name"))
    words = _tokens(" ".join(s["text"] for s in script_segments(payload["script"])))
    return episode, entities, words


def validate_rule(rule, entities, words):
    key = (rule.entity_kind, rule.entity_id)
    if entities.get(key) != rule.canonical_name:
        return False
    token, aliases = validate_alias_spellings(rule.canonical_token, json.loads(rule.aliases_json))
    if token not in _tokens(rule.canonical_name) or token not in words:
        return False
    other_names = {word for entity, name in entities.items() if entity != key for word in _tokens(name)}
    # Shared first names cannot be mapped without occurrence-level identity proof.
    if token in other_names or set(aliases) & (other_names | set(words)):
        raise Held("speech_review_name_ambiguous")
    return True


async def approve_spellings(db, *, script_id, entity_kind, entity_id, canonical_token, aliases, actor_id, reason,
                            reusable=False):
    """Called only by an authenticated API admin action (Task10), never media routes."""
    await lock_control(db)
    artifact = await db.get(ContentArtifact, script_id)
    episode, entities, words = await context(db, artifact)
    head = await db.get(ArtifactHead, artifact.subject)
    job = await db.get(GenerationOperation, artifact.operation_id)
    if not head or head.artifact_id != script_id or not job or job.state != "succeeded":
        raise Held("speech_review_script_not_current")
    await require_actor(db, SimpleNamespace(actor_id=actor_id, kind="generation", league_id=artifact.league_id,
        connection_generation=job.connection_generation))
    if type(reusable) is not bool or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError("Reviewed spelling requires a bounded review reason")
    token, variants = validate_alias_spellings(canonical_token, aliases)
    name = entities.get((entity_kind, entity_id))
    if not name:
        raise Held("speech_review_entity_missing")
    row = RecapSpeechReview(series_id=artifact.series_id, season=episode.season, entity_kind=entity_kind,
        entity_id=entity_id, canonical_name=name, canonical_token=token, aliases_json=dump(variants),
        script_id=script_id, script_digest=artifact.digest, script_revision=artifact.revision,
        reviewer_id=actor_id, reason=reason.strip(), reusable=reusable)
    if not validate_rule(row, entities, words):
        raise Held("speech_review_name_absent")
    db.add(row)
    await db.flush()
    audit(db, actor_id, "speech_spelling_reviewed", row.id, reason, after={"script_id": script_id,
        "script_digest": artifact.digest, "entity_kind": entity_kind, "entity_id": entity_id})
    return row


async def bind_reviews(db, artifact, *, review_ids=None):
    episode, entities, words = await context(db, artifact)
    query = select(RecapSpeechReview).where(RecapSpeechReview.series_id == artifact.series_id,
        RecapSpeechReview.season == episode.season).order_by(RecapSpeechReview.id)
    if review_ids is not None:
        query = query.where(RecapSpeechReview.id.in_(review_ids))
    rows = (await db.scalars(query)).all()
    rules, aliases, mappings = [], {}, {}
    for row in rows:
        if not row.reusable and (row.script_id, row.script_digest, row.script_revision) != (artifact.id, artifact.digest, artifact.revision):
            continue
        if not validate_rule(row, entities, words):
            continue
        for spelling in json.loads(row.aliases_json):
            if spelling in mappings and mappings[spelling] != row.canonical_token:
                raise Held("speech_review_name_ambiguous")
            mappings[spelling] = row.canonical_token
            aliases.setdefault(row.canonical_token, set()).add(spelling)
        rules.append({field: getattr(row, field) for field in FIELDS})
    return {"version": VERSION, "script_id": artifact.id, "script_digest": artifact.digest,
        "script_revision": artifact.revision, "series_id": artifact.series_id, "season": episode.season,
        "rules": rules, "aliases": {k: sorted(v) for k, v in aliases.items()}}


async def validate_binding(db, stage, inputs):
    binding = inputs.get("speech_review")
    artifact = await db.get(ContentArtifact, stage.script_id)
    if not isinstance(binding, dict) or not isinstance(binding.get("rules"), list):
        raise Held("speech_review_binding_missing")
    expected = await bind_reviews(db, artifact, review_ids=[r.get("id") for r in binding["rules"]])
    if (binding != expected or inputs["script"] != json.loads(artifact.payload_json)["script"]
            or inputs.get("script_digest") != artifact.digest):
        raise Held("speech_review_binding_changed")
    return binding
