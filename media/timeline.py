"""Pure bound timeline. No database, network, source fetching or prose generation."""
import hashlib
import json
import math
from pathlib import Path
from media.audio_seams import chunk_record

VERSION = "recap-v8-linux-1"
FONTS = dict(zip(("Bricolage", "Geist", "GeistMono"), (
    "a756882d8a7802ebd4663b4544a62ebedafc7227c1c159ab95eea61393af3f8e",
    "19f9c92546aa300c312235e3125af1b81394d8db9a4bc4a425cd5b641d2d54e1",
    "684ad5b531f81d43c1e8c7038262d5db7cdc1f68006e04d6c7769efa8d33c8cc"), strict=True))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def scene_plan(script, claims):
    """Prepaid visual admission. Multi-result blocks require disjoint owner anchors.

    Repeated/interleaved names cannot establish when a score belongs on screen;
    hold the script rather than divide its duration or trust claim-list ordering.
    """
    from app.services.recap_video.audio import _tokens
    index = {c["id"]:c for c in claims["claims"]}
    names = {o["id"]:_tokens(o["name"]) for o in claims["owners"]}
    plan = {}
    for segment in script["segments"]:
        tokens = _tokens(segment["text"])
        selected = [index[c] for c in segment["claim_ids"] if index[c]["kind"] in ("result", "owner_status")]
        if not selected:
            raise ValueError("scene_claim_missing:"+segment["id"])
        anchored = []
        for claim in selected:
            positions = []
            for owner in claim["owner_ids"]:
                name = names[owner]
                matches = [i for i in range(len(tokens)-len(name)+1) if tokens[i:i+len(name)] == name]
                if not matches or len(selected)>1 and len(matches)!=1:
                    raise ValueError("scene_anchor_ambiguous:"+segment["id"])
                positions.extend(matches)
            anchored.append(dict(claim=claim, token=min(positions) if len(selected)>1 else 0, last=max(positions)))
        anchored.sort(key=lambda a:a["token"])
        if any(a["last"] >= b["token"] for a,b in zip(anchored,anchored[1:])):
            raise ValueError("scene_anchor_ambiguous:"+segment["id"])
        for i, anchor in enumerate(anchored):
            end = anchored[i+1]["token"] if i+1<len(anchored) else len(tokens)
            block = tokens[anchor["token"]:end]
            claim = anchor["claim"]
            if claim["kind"] == "owner_status":
                expected = "bye" if claim["status"] == "bye" else "finished"
                if expected not in block:
                    raise ValueError("status_anchor_missing:"+segment["id"])
            if claim["kind"] == "result":
                verbs = {"tie", "tied"} if claim.get("result") == "tie" else {"beat", "beats", "won", "win", "lost", "defeated", "edged", "wins", "loss"}
                if not verbs.intersection(block):
                    raise ValueError("result_anchor_missing:"+segment["id"])
                for number in segment.get("spoken_numbers", []):
                    if number["claim_id"] == claim["id"]:
                        spoken = _tokens(number["spoken"])
                        if not any(block[j:j+len(spoken)] == spoken for j in range(len(block)-len(spoken)+1)):
                            raise ValueError("numeric_anchor_ambiguous:"+segment["id"])
        plan[segment["id"]] = anchored
    return plan

def validate_episode(e):
    issues = []
    try:
        duration = e["duration"]
        if not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 0 < duration <= 1200:
            return ["duration_invalid"]
        if e["renderer_version"] != VERSION or e["geometry"] != {"width": 1280, "height": 720, "fps": 30}:
            issues.append("renderer_binding_invalid")
        from media.audio_seams import boundaries_valid, RATE
        if not boundaries_valid(e["chunk_timing"],e["audio_chunks"],round(e["audio_duration"]*RATE)):
            issues.append("chunk_boundaries_invalid")
        chunks = e["audio_chunks"]
        if not chunks or len(chunks) != len(set(chunks)):
            issues.append("duplicate_chunk")
        for key, issue in (("scenes", "scene_time_invalid"), ("captions", "caption_time_invalid")):
            end = 0
            if not e[key]:
                issues.append(issue)
            for item in e[key]:
                a, b = item["start"], item["end"]
                if (not all(type(t) in (int, float) and math.isfinite(t) for t in (a, b))
                        or a < end or b <= a or b > duration or key == "scenes" and abs(a-end) > .001):
                    issues.append(issue)
                end = b
            if key == "scenes" and abs(end-duration) > .001:
                issues.append(issue)
        claims = {c["id"]: c for c in e["claims"]["claims"]}
        covered, covered_status = [], []
        for scene in e["scenes"]:
            if scene["kind"] == "status":
                claim = claims[scene["claim_id"]]
                if scene["status"] != claim["status"] or scene["owner_id"] not in claim["owner_ids"]:
                    issues.append("status_graphic_mismatch")
                covered_status.extend(claim["owner_ids"])
            if scene["kind"] != "matchup":
                continue
            claim = claims[scene["claim_id"]]
            values = claim["values"]
            owners = claim["owner_ids"]
            index = 0 if claim["winner_id"] in (None, owners[0]) else 1
            expected = (values["score_a"], values["score_b"])[::1 if index == 0 else -1]
            if (scene["winner_points"], scene["loser_points"]) != expected:
                issues.append("score_graphic_mismatch")
            if scene["result"] != claim["result"]:
                issues.append("result_graphic_mismatch")
            covered.extend(claim["matchup_ids"])
        if set(covered) != set(e["claims"]["matchup_ids"]):
            issues.append("matchup_coverage_missing")
        if set(covered_status) != {o for c in claims.values() if c["kind"] == "owner_status" for o in c["owner_ids"]}:
            issues.append("status_coverage_missing")
    except (KeyError, TypeError, ValueError):
        issues.append("timeline_invalid")
    return sorted(set(issues))

def build_episode(inputs, raw, audio_chunks, audio_sha256, duration, *, aliases=None, chunk_timing=None):
    """Match approved prose spans to independently verified words. Ambiguity holds.

    Prefix matching permits cardinal/decimal normalization without assigning invented
    per-word times. Caption groups retain exact approved prose and real end times.
    """
    from app.services.recap_video.audio import _tokens, script_segments, verify_speech
    if not verify_speech(inputs["script"], raw, reviewed_aliases=aliases)["passed"]:
        raise ValueError("speech_verification_failed")
    replacements = {variant.lower(): name.lower() for name, variants in (aliases or {}).items() for variant in variants}
    words = raw["words"]
    prefixes = {}
    for index in range(1, len(words)+1):
        tokens = tuple(replacements.get(t, t) for t in _tokens(" ".join(w["word"] for w in words[:index])))
        prefixes[tokens] = index
    captions, scenes, approved = [], [], []
    previous = 0
    names = {o["id"]: o["name"] for o in inputs["claims"]["owners"]}
    segments = script_segments(inputs["script"])
    plan = scene_plan(inputs["script"], inputs["claims"])
    for segment_index, segment in enumerate(segments):
        start_index = previous
        before_segment = list(approved)
        pieces = segment["text"].split()
        pending = []
        for piece_index, piece in enumerate(pieces):
            approved.append(piece)
            pending.append(piece)
            matched = prefixes.get(tuple(_tokens(" ".join(approved))))
            if matched is not None and (len(pending) >= 9 or piece_index == len(pieces)-1):
                captions.append(dict(start=words[previous]["start"], end=words[matched-1]["end"], text=" ".join(pending)))
                previous, pending = matched, []
        if pending or previous <= start_index:
            raise ValueError("caption_alignment_ambiguous")
        start = 0 if segment_index == 0 else words[start_index]["start"]
        if scenes:
            scenes[-1]["end"] = start
        scene = dict(start=start, end=duration, kind="intro" if segment_index == 0 else "outro",
                     title="Weekly recap." if segment_index == 0 else "See you next week.", label="Weekly recap")
        if 0 < segment_index < len(segments)-1:
            source = inputs["script"]["segments"][segment_index-1]
            for anchor_index, anchor in enumerate(plan[source["id"]]):
                claim = anchor["claim"]
                token_prefix = _tokens(" ".join(before_segment)) + _tokens(source["text"])[:anchor["token"]]
                raw_index = prefixes.get(tuple(token_prefix), 0 if not token_prefix else None)
                if raw_index is None:
                    raise ValueError("scene_timing_ambiguous:"+source["id"])
                scene_start = start if anchor_index == 0 else words[raw_index]["start"]
                if anchor_index:
                    scenes[-1]["end"] = scene_start
                current = dict(scene, start=scene_start, claim_id=claim["id"], light=segment_index % 2 == 0)
                owners = claim["owner_ids"]
                if claim["kind"] == "owner_status":
                    current.update(kind="status", owner_id=owners[0], owner=names[owners[0]], status=claim["status"])
                else:
                    order = [0, 1] if claim["winner_id"] in (None, owners[0]) else [1, 0]
                    points = [claim["values"]["score_a"], claim["values"]["score_b"]]
                    current.update(kind="matchup", label="Matchup " + str(segment_index),
                        winner=names[owners[order[0]]], loser=names[owners[order[1]]],
                        winner_points=points[order[0]], loser_points=points[order[1]], result=claim["result"],
                        highlights=[dict(at=scene_start, value=claim["values"]["margin"], label="FINAL MARGIN")])
                scenes.append(current)
            continue
        scenes.append(scene)
    e = dict(renderer_version=VERSION, geometry=dict(width=1280, height=720, fps=30), fonts=FONTS,
        duration=duration, title="WEEKLY RECAP", edition=inputs["claims"]["period_id"],
        script_digest=inputs["script_digest"], claims=inputs["claims"], audio="audio.wav", audio_sha256=audio_sha256,
        audio_chunks=audio_chunks, audio_duration=duration, chunk_timing=chunk_timing or [chunk_record(audio_chunks[0],audio_sha256,round(duration*44100))], transcript_digest=digest(raw), scenes=scenes, captions=captions)
    errors = validate_episode(e)
    if errors:
        raise ValueError(",".join(errors))
    return e

def synthetic_episode(duration=2):
    """Public deterministic fixture; also drives resource qualification."""
    claim = dict(id="result:demo", kind="result", owner_ids=["alpha", "bravo"], matchup_ids=["demo"],
        winner_id="alpha", result="win", values=dict(score_a="124.25", score_b="101.50", margin="22.75"))
    return dict(renderer_version=VERSION, geometry=dict(width=1280, height=720, fps=30), fonts=FONTS,
        title="WEEKLY RECAP", edition="DEMO", duration=duration, script_digest=digest("Synthetic narration"),
        claims=dict(claims=[claim], matchup_ids=["demo"]), audio="audio.wav", audio_sha256="",
        audio_chunks=["synthetic-chunk"], audio_duration=duration,
        chunk_timing=[chunk_record('synthetic-chunk','0'*64,round(duration*44100))], captions=[dict(start=0, end=duration, text="Every matchup. Every final score.")],
        scenes=[dict(start=0, end=duration/4, kind="intro", title="Weekly recap.", label="Opening"),
            dict(start=duration/4, end=duration*.75, kind="matchup", claim_id="result:demo", winner="Alpha", loser="Bravo",
                winner_points="124.25", loser_points="101.50", result="win", label="Matchup", light=False,
                highlights=[dict(at=duration/4, value="22.75", label="FINAL MARGIN")]),
            dict(start=duration*.75, end=duration, kind="outro", title="See you next week.", label="Closing")])
