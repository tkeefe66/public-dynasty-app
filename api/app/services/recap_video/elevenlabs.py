"""Exact approved voice transport. No retries, fallback, SDK, or balance inference.

Network I/O is worker-only. API imports the pure validators below. All callbacks
persist through the leased API; no storage/database credentials reach the worker.
"""
import base64
import hashlib
import json
import logging
import math
import re
from decimal import Decimal, InvalidOperation

import httpx

MODEL = "eleven_v4"
FORMAT = "mp3_44100_128"
MAX_RESPONSE = 90 * 1024 * 1024
log = logging.getLogger(__name__)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Provider identity invalid")
    return value


def sanitized_receipt(receipt):
    """Admission shape only; billing decoder runs after raw evidence commit."""
    fields = {"schema", "request_digest", "outcome", "status", "identity", "error", "audio_sha256", "audio_size",
        "timing", "asset", "metering", "history_evidence"}
    if (not isinstance(receipt, dict) or set(receipt) - fields or receipt.get("schema") != "elevenlabs-v1"
            or not re.fullmatch(r"[0-9a-f]{64}", receipt.get("request_digest", ""))
            or receipt.get("outcome") not in ("unknown", "rejected", "received", "recovered")
            or receipt.get("error") not in ("", "provider_outcome_unknown", "provider_rejected", "response_invalid")
            or type(receipt.get("status")) is not int or not 0 <= receipt["status"] <= 599):
        raise ValueError("Provider receipt envelope invalid")
    identity = receipt.get("identity")
    if not isinstance(identity, dict) or set(identity) - {"request_id", "history_item_id"}:
        raise ValueError("Provider receipt identity invalid")
    for value in identity.values():
        identifier(value)
    for field in ("audio_sha256",):
        if field in receipt and not re.fullmatch(r"[0-9a-f]{64}", receipt[field]):
            raise ValueError("Provider receipt digest invalid")
    if "audio_size" in receipt and (type(receipt["audio_size"]) is not int or not 0 < receipt["audio_size"] <= 64 * 1024 * 1024):
        raise ValueError("Provider receipt audio size invalid")
    nested = {"timing": {"alignment_sha256", "character_count", "duration_seconds"},
        "asset": {"asset_id", "digest", "size"}, "metering": {"credits", "source"},
        "history_evidence": {"history_item_id", "request_id", "content_type", "character_count_change_from", "character_count_change_to"}}
    for name, allowed in nested.items():
        if name in receipt and (not isinstance(receipt[name], dict) or set(receipt[name]) - allowed):
            raise ValueError("Provider receipt metadata invalid")
    # Prevent freeform provider exception/header text from entering generic JSON.
    if "metering" in receipt:
        value = receipt["metering"]
        if value.get("source") != "character-cost-header" or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(value.get("credits", ""))):
            raise ValueError("Provider metering evidence invalid")
    if "asset" in receipt:
        asset = receipt["asset"]
        identifier(asset.get("asset_id"))
        if (not re.fullmatch(r"[0-9a-f]{64}", asset.get("digest", ""))
                or type(asset.get("size")) is not int or not 0 < asset["size"] <= 64 * 1024 * 1024):
            raise ValueError("Provider receipt asset invalid")
    if "timing" in receipt:
        timing = receipt["timing"]
        duration = timing.get("duration_seconds")
        if (not re.fullmatch(r"[0-9a-f]{64}", timing.get("alignment_sha256", ""))
                or type(timing.get("character_count")) is not int or not 0 < timing["character_count"] <= 4000
                or type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 1200):
            raise ValueError("Provider receipt timing invalid")
    if "history_evidence" in receipt:
        history = receipt["history_evidence"]
        for key in ("request_id", "history_item_id"):
            identifier(history.get(key))
        if history.get("content_type") != "audio/mpeg":
            raise ValueError("Provider history media type invalid")
        for key in ("character_count_change_from", "character_count_change_to"):
            if key in history and (type(history[key]) is not int or history[key] < 0):
                raise ValueError("Provider history metering invalid")
    return receipt


def validate_request(request, rate, maximum):
    if (not isinstance(request, dict) or request.get("model_id") != MODEL
            or set(request) - {"model_id", "inputs", "settings", "language_code", "seed", "apply_text_normalization", "previous_text", "future_text"}
            or not isinstance(request.get("inputs"), list) or len(request["inputs"]) != 1):
        raise ValueError("Qualified exact dialogue request required")
    item = request["inputs"][0]
    if set(item) != {"voice_id", "text"} or not isinstance(item["text"], str) or not 0 < len(item["text"]) <= 2000:
        raise ValueError("Narration input character bound invalid")
    identifier(item["voice_id"])
    if (rate.get("unit") != "character" or not rate.get("source") or not rate.get("revision")
            or type(rate.get("microusd_per_character")) is not int or rate["microusd_per_character"] <= 0):
        raise ValueError("Qualified billing rate missing")
    try:
        credits = Decimal(rate.get("max_credits_per_character", "0"))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Qualified credit rate invalid") from None
    if not credits.is_finite() or credits <= 0:
        raise ValueError("Qualified credit rate missing")
    price = len(item["text"]) * rate["microusd_per_character"]
    if type(maximum) is not int or maximum < price:
        raise ValueError("Narration exceeds admitted allocation")
    return price


async def _json_get(client, path):
    async with client.stream("GET", path) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 256_000:
                raise ValueError("Provider metadata response too large")
    return json.loads(body)


async def preflight_voice(client, voice_id: str, model_id: str) -> dict:
    identifier(voice_id)
    if model_id != MODEL:
        raise ValueError("Approved dialogue model required")
    voice = await _json_get(client, "/v1/voices/" + voice_id)
    models = await _json_get(client, "/v1/models")
    subscription = await _json_get(client, "/v1/user/subscription")
    user = await _json_get(client, "/v1/user")
    account = {key: identifier(user.get(key)) for key in ("user_id", "workspace_id")}
    matches = [m for m in models if m.get("model_id") == model_id]
    if (voice.get("voice_id") != voice_id or len(matches) != 1 or matches[0].get("can_do_text_to_speech") is not True
            or subscription.get("status") != "active" or not subscription.get("tier")):
        raise ValueError("Exact voice, model or account unavailable")
    # Missing optional entitlement fields remain missing, for durable qualification
    # to evaluate explicitly. GET access alone is never paid dialogue entitlement.
    return {"provenance": "elevenlabs-readonly-v1",
        "account": account,
        "voice": {k: voice[k] for k in ("voice_id", "available_for_tiers", "high_quality_base_model_ids",
            "safety_control", "permission_on_resource") if k in voice},
        "sharing": {k: voice.get("sharing", {})[k] for k in ("status", "rate", "disable_at_unix", "available_for_tiers")
            if k in (voice.get("sharing") or {})},
        "model": {k: matches[0][k] for k in ("model_id", "can_do_text_to_speech", "model_rates", "token_cost_factor",
            "requires_alpha_access", "maximum_text_length_per_request") if k in matches[0]},
        "subscription": {k: subscription[k] for k in ("tier", "status")}}


def alignment_evidence(body, request):
    alignment = body.get("alignment")
    if not isinstance(alignment, dict):
        raise ValueError("Provider alignment missing")
    chars = alignment.get("characters", [])
    starts, ends = alignment.get("character_start_times_seconds", []), alignment.get("character_end_times_seconds", [])
    if (not chars or not all(isinstance(c, str) and len(c) == 1 for c in chars)
            or len(chars) != len(starts) or len(chars) != len(ends) or len(chars) > 4000):
        raise ValueError("Provider alignment invalid")
    previous = 0
    for start, end in zip(starts, ends):
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) or start < previous or end < start:
            raise ValueError("Provider alignment invalid")
        previous = start
    segments = body.get("voice_segments")
    if (not isinstance(segments, list) or not segments or len(segments) > 64
            or any(s.get("voice_id") != request["inputs"][0]["voice_id"] or s.get("dialogue_input_index") != 0 for s in segments)):
        raise ValueError("Provider voice evidence invalid")
    # Sanitized timing only, voice identifier stays in protected request config.
    return {"alignment_sha256": canonical({"characters": chars, "character_start_times_seconds": starts,
        "character_end_times_seconds": ends}), "character_count": len(chars), "duration_seconds": max(ends)}


class ElevenLabsTransport:
    def __init__(self, api_key, persist_identity, persist_audio, *, transport=None):
        self.key, self.persist_identity, self.persist_audio = api_key, persist_identity, persist_audio
        self.transport = transport  # Tests use MockTransport; runtime always retries=0.

    def client(self):
        if not self.key:
            raise ValueError("ElevenLabs supervisor credential missing")
        return httpx.AsyncClient(base_url="https://api.elevenlabs.io", headers={"xi-api-key": self.key},
            timeout=httpx.Timeout(120, connect=10, pool=5), follow_redirects=False,
            transport=self.transport or httpx.AsyncHTTPTransport(retries=0))

    async def send(self, request: dict) -> dict:
        payload, rate = request["request"], request["rate_snapshot"]
        validate_request(payload, rate, request["max_microusd"])
        receipt = {"schema": "elevenlabs-v1", "request_digest": canonical(payload), "outcome": "unknown",
            "status": 0, "identity": {}, "error": "provider_outcome_unknown"}
        async with self.client() as client:
            try:
                log.info("Narration provider request dispatching")
                async with client.stream("POST", "/v1/text-to-dialogue/with-timestamps",
                        params={"output_format": FORMAT, "enable_logging": "true"}, json=payload) as response:
                    receipt["status"] = response.status_code
                    identity = {key: identifier(response.headers[header]) for key, header in (
                        ("request_id", "request-id"), ("history_item_id", "history-item-id")) if response.headers.get(header)}
                    receipt["identity"] = identity
                    credit = response.headers.get("character-cost")
                    if credit is not None:
                        receipt["metering"] = {"credits": credit, "source": "character-cost-header"}
                    if identity:
                        # This awaited API commit happens BEFORE reading response bytes.
                        await self.persist_identity(identity)
                    if response.status_code != 200:
                        receipt["outcome"], receipt["error"] = "rejected", "provider_rejected"
                        return receipt
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE:
                            raise ValueError("Provider response too large")
                    value = json.loads(body)
                    if not isinstance(value, dict) or any(k in value for k in ("variants", "audios", "outputs")):
                        raise ValueError("Provider result ambiguous")
                    timing = alignment_evidence(value, payload)
                    audio = base64.b64decode(value["audio_base64"], validate=True)
                    if not audio or len(audio) > 64 * 1024 * 1024:
                        raise ValueError("Provider audio size invalid")
                    sha = hashlib.sha256(audio).hexdigest()
                    receipt.update(audio_sha256=sha, audio_size=len(audio), timing=timing)
                    asset = await self.persist_audio(audio, sha)
                    receipt["asset"] = asset
                    if not identity:
                        raise ValueError("Provider identity missing")
                    receipt["outcome"], receipt["error"] = "received", ""
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                receipt["error"] = "response_invalid" if receipt["status"] == 200 else "provider_outcome_unknown"
                log.warning("Narration provider result uncertain; exact-identity reconciliation required")
            except Exception:
                # Storage/API failure must not trigger resend or leak exception URLs.
                receipt["error"] = "provider_outcome_unknown"
                log.error("Narration evidence persistence failed; exact-identity reconciliation required")
        return receipt

    async def recover(self, request, identity):
        """Only exact retained history IDs. Request-only identity cannot guess history.

        History has no documented alignment endpoint. Recovered audio is held for
        independent speech verification and subsequent timing qualification.
        """
        history_id = identifier(identity.get("history_item_id"))
        request_id = identifier(identity.get("request_id"))
        async with self.client() as client:
            metadata = await _json_get(client, "/v1/history/" + history_id)
            if (metadata.get("history_item_id") != history_id or metadata.get("request_id") != request_id
                    or metadata.get("voice_id") != request["inputs"][0]["voice_id"]
                    or metadata.get("model_id") != MODEL or metadata.get("text") != request["inputs"][0]["text"]):
                raise ValueError("Exact history evidence unavailable or ambiguous")
            await self.persist_identity(identity)
            async with client.stream("GET", "/v1/history/" + history_id + "/audio") as response:
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 64 * 1024 * 1024:
                        raise ValueError("Recovered audio exceeds bound")
            if not data:
                raise ValueError("Recovered audio empty")
            sha = hashlib.sha256(data).hexdigest()
            asset = await self.persist_audio(bytes(data), sha)
            # Per-item history metering is retained as evidence; account-wide balance
            # differences are never used to identify or price an outcome.
            return {"schema": "elevenlabs-v1", "request_digest": canonical(request), "identity": identity,
                "status": 200, "outcome": "recovered", "error": "response_invalid", "audio_sha256": sha,
                "audio_size": len(data), "asset": asset,
                "history_evidence": {k: metadata[k] for k in ("history_item_id", "request_id", "content_type",
                    "character_count_change_from", "character_count_change_to") if k in metadata}}


def settle_receipt(request, rate, receipt):
    if receipt.get("schema") != "elevenlabs-v1" or receipt.get("request_digest") != canonical(request):
        raise ValueError("Provider receipt does not match saved request")
    validate_request(request, rate, 9_007_199_254_740_991)
    if receipt.get("status") != 200 or not receipt.get("identity"):
        return ("rejected" if receipt.get("outcome") == "rejected" else "unknown", None,
            "provider_rejected" if receipt.get("outcome") == "rejected" else "provider_outcome_unknown")
    metering = receipt.get("metering", {})
    if metering.get("source") != "character-cost-header":
        return "unknown", None, "provider_outcome_unknown"
    credits = Decimal(metering.get("credits", "NaN"))
    expected = len(request["inputs"][0]["text"]) * Decimal(rate["max_credits_per_character"])
    if not credits.is_finite() or credits < 0 or credits != expected:
        return "unknown", None, "provider_outcome_unknown"
    amount = len(request["inputs"][0]["text"]) * rate["microusd_per_character"]
    error = "" if receipt.get("outcome") == "received" and receipt.get("timing") and receipt.get("asset") else "response_invalid"
    return "received", amount, error


# Task10 supplies an API-owned durable qualification reader. It must return the
# exact approved config, metadata snapshot, rate snapshot and durable revision.
# A worker-authored revision or success flag is never authority.
QUALIFICATION_READER = None  # async (db, episode_id) -> qualification dict


def preflight_config():
    from app.config import get_settings
    from app.services.generation.store import Held
    config = get_settings()
    if (not config.elevenlabs_voice_id or QUALIFICATION_READER is None
            or not re.fullmatch(r"[0-9a-f]{64}", config.elevenlabs_account_identity_digest)):
        raise Held("media_qualification_required")
    return {"voice_id": config.elevenlabs_voice_id, "model_id": MODEL, "output_format": FORMAT,
        "settings": config.elevenlabs_dialogue_settings, "account_alias": config.elevenlabs_account_alias,
        "account_identity_digest": config.elevenlabs_account_identity_digest}


async def qualification(db, episode_id):
    from app.services.generation.store import Held
    if QUALIFICATION_READER is None:
        raise Held("media_qualification_required")
    value = await QUALIFICATION_READER(db, episode_id)
    if (not isinstance(value, dict) or set(value) != {"revision", "config", "metadata", "rate_snapshot"}
            or not isinstance(value["revision"], str) or not value["revision"] or len(value["revision"]) > 128
            or value["config"] != preflight_config()):
        raise Held("media_qualification_changed")
    return value


async def validate_preflight(db, stage, result):
    from app.services.generation.store import Held, dump
    approved = await qualification(db, stage.episode_id)
    metadata = result["report"]
    if metadata != approved["metadata"] or metadata.get("provenance") != "elevenlabs-readonly-v1":
        raise Held("media_preflight_metadata_changed")
    cfg = approved["config"]
    if (set(metadata.get("account", {})) != {"user_id", "workspace_id"}
            or canonical(metadata["account"]) != cfg["account_identity_digest"]):
        raise Held("media_preflight_account_changed")
    try:
        validate_request({"model_id": MODEL, "inputs": [{"voice_id": cfg["voice_id"], "text": "x"}],
            "settings": cfg["settings"]}, approved["rate_snapshot"], 9_007_199_254_740_991)
    except (ValueError, TypeError, KeyError):
        raise Held("media_rate_unqualified") from None
    if (metadata.get("voice", {}).get("voice_id") != cfg["voice_id"]
            or metadata.get("model", {}).get("model_id") != MODEL
            or metadata.get("model", {}).get("can_do_text_to_speech") is not True
            or metadata.get("subscription", {}).get("status") != "active"):
        raise Held("media_preflight_invalid")
    # Detailed minimal necessary evidence retained independently of compatibility.
    stage.evidence_json = dump({"metadata": metadata, "rate_snapshot": approved["rate_snapshot"], "config": cfg,
        "qualification_revision": approved["revision"]})
    return dict(episode_id=stage.episode_id, account_alias=cfg["account_alias"],
        voice_digest=canonical([cfg, metadata]), rate_digest=canonical(approved["rate_snapshot"]),
        qualification_revision=approved["revision"])


async def build_media_plan(db, artifact, evidence):
    from sleeper_dynasty.engine.recap_narration import narration_chunks
    from app.services.recap_video.speech_reviews import bind_reviews
    from app.services.generation.store import Held
    payload = json.loads(artifact.payload_json)
    approved = await qualification(db, payload["episode_id"])
    if (evidence["qualification_revision"] != approved["revision"]
            or evidence["voice_digest"] != canonical([approved["config"], approved["metadata"]])
            or evidence["rate_digest"] != canonical(approved["rate_snapshot"])):
        raise Held("media_qualification_changed")
    script = payload["script"]
    from media.timeline import scene_plan
    try:
        scene_plan(script, payload["claims"])
    except ValueError as exc:
        raise Held(str(exc).split(":")[0]) from None
    except (KeyError, TypeError):
        raise Held("render_script_mapping_ambiguous") from None
    speech_review = await bind_reviews(db, artifact)
    cfg, rate = approved["config"], approved["rate_snapshot"]
    try:
        chunks = narration_chunks(script)
    except ValueError as exc:
        raise Held(str(exc)) from None
    plan = []
    for i, chunk in enumerate(chunks):
        request = {"model_id": MODEL, "inputs": [{"voice_id": cfg["voice_id"], "text": chunk["text"]}], "settings": cfg["settings"]}
        maximum = validate_request(request, rate, 9_007_199_254_740_991)
        plan.append(dict(kind="narrate", chunk=i, input={"paid": {"request": request,
            "rate_snapshot": rate, "max_microusd": maximum}, "segment_ids": chunk["segment_ids"]}))
    for kind in ("speech_check", "render", "media_check"):
        plan.append(dict(kind=kind, chunk=0, input={"script": script, "chunks": chunks,
            "script_digest": artifact.digest, "claims": payload["claims"]}))
        plan[-1]["input"]["speech_review"] = speech_review
    return plan


async def validate_narration(db, stage, result):
    from sqlalchemy import select
    from app.services.generation.recap_models import RecapProviderAttempt, RecapAsset
    from app.services.generation.store import Held
    attempt = await db.scalar(select(RecapProviderAttempt).where(RecapProviderAttempt.stage_id == stage.id))
    receipt = json.loads(attempt.receipt_json or "{}") if attempt else {}
    asset = await db.get(RecapAsset, receipt.get("asset", {}).get("asset_id", ""))
    if (not asset or asset.stage_id != stage.id or asset.generation != stage.generation
            or result["asset_ids"] != [asset.id] or receipt.get("audio_sha256") != asset.digest
            or receipt.get("audio_size") != asset.size or result["report"] != {"receipt_digest": canonical(receipt)}):
        raise Held("narration_asset_evidence_invalid")


async def validate_speech(db, stage, result):
    from app.services.recap_video.audio import verify_speech, MODEL_REVISION, MODEL_SHA256
    from app.services.generation.store import Held, dump
    from app.services.generation.recap_models import RecapAsset, RecapStage
    from app.services.recap_video.storage import configured_store
    from sqlalchemy import select
    import asyncio
    identity = result["report"].get("transcript_asset_id", "")
    asset = await db.get(RecapAsset, identity)
    if (not asset or asset.stage_id != stage.id or asset.generation != stage.generation
            or asset.media_type != "application/json" or result["asset_ids"] != [identity] or asset.size > 2_000_000):
        raise Held("speech_evidence_missing")
    narration = (await db.scalars(select(RecapStage).where(RecapStage.script_id == stage.script_id,
        RecapStage.execution_revision == stage.execution_revision,
        RecapStage.kind == "narrate", RecapStage.state == "succeeded").order_by(RecapStage.chunk))).all()
    expected_audio = [identity for row in narration for identity in json.loads(row.result_json)["asset_ids"]]
    if result["report"].get("audio_asset_ids") != expected_audio or not expected_audio:
        raise Held("speech_audio_inputs_changed")
    data = await asyncio.to_thread(configured_store().read_range, asset.storage_key, 0, asset.size - 1)
    if hashlib.sha256(data).hexdigest() != asset.digest:
        raise Held("speech_evidence_corrupt")
    raw = json.loads(data)
    if raw.get("model_revision") != MODEL_REVISION or raw.get("model_sha256") != MODEL_SHA256["model.bin"]:
        raise Held("speech_model_unqualified")
    from app.services.recap_video.speech_reviews import validate_binding
    inputs = json.loads(stage.input_json)
    binding = await validate_binding(db, stage, inputs)
    report = verify_speech(inputs["script"], raw, reviewed_aliases=binding["aliases"])
    stage.evidence_json = dump({"verifier_revision": report["verifier_revision"], "passed": report["passed"],
        "transcript_asset_id": identity, "transcript_digest": asset.digest, "audio_asset_ids": expected_audio,
        "speech_review": binding, "issues": report["issues"]})
    if not report["passed"]:
        raise Held("speech_verification_failed")


def install_api():
    from app.services.recap_video import workflow
    workflow.PREFLIGHT_CONFIG = preflight_config
    workflow.MEDIA_PLAN_BUILDER = build_media_plan
    workflow.RECEIPT_SETTLERS["elevenlabs"] = settle_receipt
    workflow.RESULT_VALIDATORS.update(preflight=validate_preflight, narrate=validate_narration, speech_check=validate_speech)
    from app.services.recap_video.rendering import install_api as install_rendering
    install_rendering()
