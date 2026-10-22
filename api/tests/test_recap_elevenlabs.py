"""Document-shaped synthetic HTTP fixtures; no authenticated capture or paid calls."""
import base64
import hashlib
import json
import httpx
import pytest
from app.services.recap_video.elevenlabs import ElevenLabsTransport, preflight_voice, settle_receipt

REQUEST = {"model_id": "eleven_v4", "inputs": [{"voice_id": "synthetic-voice", "text": "Avery won."}],
    "settings": {"stability": .5}}
RATE = {"unit": "character", "microusd_per_character": 7, "max_credits_per_character": "1",
    "source": "synthetic-qualified-billing", "revision": "synthetic-rate"}


def tagged_audio(encoder, *, geob=False, payload=b'\xff\xfbsynthetic-mpeg', padding=10, terminated=True):
    def size(n): return bytes((n>>21&127,n>>14&127,n>>7&127,n&127))
    def frame(kind,data): return kind+size(len(data))+b'\x00\x00'+data
    frames=frame(b'TSSE',b'\x03'+encoder.encode()+(b'\x00' if terminated else b''))
    if geob: frames+=frame(b'GEOB',b'\x03application/c2pa\x00manifest')
    tag=frames+b'\x00'*padding
    return b'ID3\x04\x00\x00'+size(len(tag))+tag+payload


@pytest.mark.asyncio
@pytest.mark.parametrize('changed_audio',[False,True])
async def test_history_metadata_reconstruction_requires_original_exact_hash(changed_audio):
    # Mutation: altered MPEG payload is accepted, or history metadata prevents exact original-byte recovery.
    original=tagged_audio('Lavf63.1.102')
    history=tagged_audio('Lavf63.1.102',terminated=False,geob=True,payload=b'\xff\xfbchanged' if changed_audio else b'\xff\xfbsynthetic-mpeg',padding=0)
    calls=[];events=[]
    def http(request):
        calls.append(request.method)
        if request.url.path.endswith('/audio'): return httpx.Response(200,content=history)
        return httpx.Response(200,json={'history_item_id':'synthetic-history','request_id':'synthetic-request','model_id':'eleven_v4',**REQUEST['inputs'][0]})
    action=transport(http,events).recover(REQUEST,{'history_item_id':'synthetic-history','request_id':'synthetic-request'},original_receipt={'audio_sha256':hashlib.sha256(original).hexdigest(),'audio_size':len(original)})
    if changed_audio:
        with pytest.raises(ValueError,match='original audio hash'): await action
        assert not any(kind=='audio' for kind,_ in events)
    else:
        recovered=await action
        assert recovered['audio_sha256']==hashlib.sha256(original).hexdigest()
        assert recovered['audio_size']==len(original)
    assert calls==['GET','GET']


def response():
    return {"audio_base64": base64.b64encode(b"synthetic-mp3").decode(),
        "alignment": {"characters": list("Avery won."), "character_start_times_seconds": [i * .1 for i in range(10)],
            "character_end_times_seconds": [(i + 1) * .1 for i in range(10)]},
        "voice_segments": [{"voice_id": "synthetic-voice", "start_time_seconds": 0,
            "end_time_seconds": 1, "character_start_index": 0, "character_end_index": 10, "dialogue_input_index": 0}]}


def transport(handler, events, *, key="synthetic-secret", store_failure=False):
    async def identity(row):
        events.append(("identity", row))
    async def save(data, sha):
        events.append(("audio", sha))
        if store_failure:
            raise RuntimeError("private storage unavailable")
        return {"asset_id": "synthetic-asset", "digest": sha, "size": len(data)}
    return ElevenLabsTransport(key, identity, save, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_exact_request_identity_precedes_audio_and_receipt_is_sanitized():
    calls, events = [], []
    def http(request):
        calls.append(request)
        assert json.loads(request.content) == REQUEST
        assert request.url.path == "/v1/text-to-dialogue/with-timestamps"
        assert request.url.params["output_format"] == "mp3_44100_128"
        return httpx.Response(200, json=response(), headers={"request-id": "synthetic-request", "history-item-id": "synthetic-history", "character-cost": "10"})
    receipt = await transport(http, events).send({"request": REQUEST, "rate_snapshot": RATE, "max_microusd": 70})
    assert [x[0] for x in events] == ["identity", "audio"]
    assert receipt["outcome"] == "received"
    assert "base64" not in json.dumps(receipt) and "synthetic-secret" not in json.dumps(receipt)
    assert settle_receipt(REQUEST, RATE, receipt) == ("received", 70, "")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["401", "429", "timeout", "invalid_json", "missing_alignment", "variants", "persist_failure"])
async def test_failures_never_resend(mode):
    calls, events = [], []
    def http(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("https://user:secret@host/private")
        if mode.isdigit():
            return httpx.Response(int(mode), json={"detail": "private provider details"})
        body = response()
        if mode == "missing_alignment":
            body.pop("alignment")
        if mode == "variants":
            body["variants"] = [response(), response()]
        return httpx.Response(200, content=b"invalid" if mode == "invalid_json" else json.dumps(body).encode(),
            headers={"request-id": "synthetic-request", "history-item-id": "synthetic-history"})
    receipt = await transport(http, events, store_failure=mode == "persist_failure").send(
        {"request": REQUEST, "rate_snapshot": RATE, "max_microusd": 70})
    assert receipt["outcome"] != "received" and len(calls) == 1
    assert "secret" not in json.dumps(receipt) and "base64" not in json.dumps(receipt)
    assert settle_receipt(REQUEST, RATE, receipt)[1] is None  # no invented zero charge


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["credentials", "rate", "model", "voice", "bound", "allocation"])
async def test_local_gates_prevent_physical_send(change):
    calls, events = [], []
    request = json.loads(json.dumps(REQUEST))
    rate = RATE.copy()
    if change == "rate": rate = {}
    if change == "model": request["model_id"] = "eleven_v3"
    if change == "voice": request["inputs"][0]["voice_id"] = ""
    if change == "bound": request["inputs"][0]["text"] = "x" * 2001
    client = transport(lambda r: calls.append(r), events, key="" if change == "credentials" else "synthetic")
    with pytest.raises(ValueError):
        await client.send({"request": request, "rate_snapshot": rate, "max_microusd": 1 if change == "allocation" else 70})
    assert not calls


@pytest.mark.asyncio
async def test_preflight_only_exact_readonly_metadata():
    calls = []
    def http(request):
        calls.append(request)
        assert request.method == "GET"
        data = {"/v1/voices/synthetic-voice": {"voice_id": "synthetic-voice", "available_for_tiers": ["creator"],
            "high_quality_base_model_ids": ["eleven_v4"], "sharing": {"status": "enabled", "rate": .2}, "private_description": "omit"},
            "/v1/models": [{"model_id": "eleven_v4", "can_do_text_to_speech": True, "model_rates": {"character_cost_multiplier": 1}}],
            "/v1/user": {"user_id": "synthetic-user", "workspace_id": "synthetic-workspace", "xi_api_key_preview": "omit-secret"},
            "/v1/user/subscription": {"tier": "creator", "status": "active", "character_count": 999, "open_invoices": []}}
        return httpx.Response(200, json=data[request.url.path])
    async with httpx.AsyncClient(base_url="https://api.elevenlabs.io", transport=httpx.MockTransport(http)) as client:
        report = await preflight_voice(client, "synthetic-voice", "eleven_v4")
    assert len(calls) == 4
    assert report["subscription"] == {"tier": "creator", "status": "active"}
    assert "private_description" not in json.dumps(report)
    assert "character_count" not in json.dumps(report)
    assert "omit-secret" not in json.dumps(report)


@pytest.mark.asyncio
async def test_headers_are_committed_before_body_crash_and_recovery_only_gets_exact_id():
    events, calls = [], []
    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            assert events[0][0] == "identity"
            raise httpx.ReadError("body interrupted")
            yield b""
    def broken(request):
        calls.append(request.method)
        return httpx.Response(200, stream=BrokenBody(), headers={"request-id": "synthetic-request",
            "history-item-id": "synthetic-history", "character-cost": "10"})
    receipt = await transport(broken, events).send({"request": REQUEST, "rate_snapshot": RATE, "max_microusd": 70})
    assert calls == ["POST"] and receipt["outcome"] == "unknown"
    assert settle_receipt(REQUEST, RATE, receipt) == ("received", 70, "response_invalid")
    def retrieve(request):
        calls.append(request.method)
        if request.url.path.endswith("/audio"):
            return httpx.Response(200, content=b"exact-saved-audio")
        return httpx.Response(200, json={"history_item_id": "synthetic-history", "request_id": "synthetic-request",
            "voice_id": "synthetic-voice", "model_id": "eleven_v4", "text": "Avery won.", "content_type": "audio/mpeg",
            "character_count_change_from": 100, "character_count_change_to": 110})
    recovered = await transport(retrieve, events).recover(REQUEST, receipt["identity"])
    assert calls == ["POST", "GET", "GET"]
    assert recovered["audio_sha256"] == hashlib.sha256(b"exact-saved-audio").hexdigest()
    assert settle_receipt(REQUEST, RATE, recovered) == ("unknown", None, "provider_outcome_unknown")
    with pytest.raises(ValueError):
        await transport(retrieve, events).recover(REQUEST, {"request_id": "synthetic-request"})
    assert calls == ["POST", "GET", "GET"]


@pytest.mark.asyncio
async def test_storage_failure_retains_audio_hash_before_exact_recovery():
    events = []
    adapter = transport(lambda r: httpx.Response(200, json=response(), headers={"request-id": "synthetic-request",
        "history-item-id": "synthetic-history", "character-cost": "10"}), events, store_failure=True)
    receipt = await adapter.send({"request": REQUEST, "rate_snapshot": RATE, "max_microusd": 70})
    assert receipt["audio_sha256"] == hashlib.sha256(b"synthetic-mp3").hexdigest()
    assert receipt["outcome"] == "unknown" and "asset" not in receipt
    assert settle_receipt(REQUEST, RATE, receipt) == ("received", 70, "response_invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['', 'text', 'voice_id', 'extra_speaker', 'request_id', 'conflicting_legacy'])
async def test_dialogue_history_recovery_matches_exact_saved_input(change):
    # Mutation: requiring legacy top-level text rejects real dialogue history;
    # ignoring dialogue identity would recover a different paid take.
    events, calls = [], []
    # Shape captured from production history, with all identifiers/text replaced.
    metadata = dict(history_item_id='synthetic-history', request_id='synthetic-request',
        model_id='eleven_v4', text=None, voice_id=None, content_type='audio/mpeg',
        dialogue=[dict(text='Avery won.', voice_id='synthetic-voice', voice_name='Synthetic')],
        character_count_change_from=100, character_count_change_to=102)
    if change in ('text', 'voice_id'):
        metadata['dialogue'][0][change] = 'different'
    if change == 'extra_speaker':
        metadata['dialogue'].append(dict(metadata['dialogue'][0]))
    if change == 'request_id':
        metadata['request_id'] = 'different'
    if change == 'conflicting_legacy':
        metadata['text'] = 'Avery lost.'
    def http(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith('/audio'):
            return httpx.Response(200, content=b'exact-saved-audio')
        return httpx.Response(200, json=metadata)
    action = transport(http, events).recover(REQUEST,
        dict(request_id='synthetic-request', history_item_id='synthetic-history'))
    if change:
        with pytest.raises(ValueError):
            await action
        assert len(calls) == 1 and not events
    else:
        result = await action
        assert result['audio_sha256'] == hashlib.sha256(b'exact-saved-audio').hexdigest()
        assert calls == [('GET', '/v1/history/synthetic-history'), ('GET', '/v1/history/synthetic-history/audio')]


@pytest.mark.asyncio
@pytest.mark.parametrize('credits', ['2', '10', '10.1', '-1', 'NaN', 'invalid'])
async def test_receipt_credit_limit_is_a_ceiling(credits):
    # Mutation: equality with maximum rejects a valid discounted metered request.
    receipt = await transport(lambda r: httpx.Response(200, json=response(), headers={
        'request-id': 'synthetic-request', 'history-item-id': 'synthetic-history',
        'character-cost': '10'}), []).send(dict(request=REQUEST, rate_snapshot=RATE, max_microusd=70))
    receipt['metering']['credits'] = credits
    if credits in ('2', '10'):
        assert settle_receipt(REQUEST, RATE, receipt) == ('received', 70, '')
    else:
        assert settle_receipt(REQUEST, RATE, receipt) == ('unknown', None, 'provider_outcome_unknown')
