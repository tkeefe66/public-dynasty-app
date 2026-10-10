"""Conservative independent speech verification; alignment is never semantic proof.

No ASR dependency is imported by the API. Worker packaging supplies faster-whisper
and the four verified local artifacts. No model hub name or download is permitted.
"""
import hashlib
import math
import re
from decimal import Decimal
from pathlib import Path

MODEL_REVISION = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
MODEL_FILES = ("model.bin", "tokenizer.json", "config.json", "vocabulary.txt")
MODEL_CHECKSUMS = (
    "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
    "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df",
    "666a9605530ac1f61fa8177f3702b4dacec9966749e42610839fcc32661d5fae",
    "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf",
)
MODEL_SHA256 = dict(zip(MODEL_FILES, MODEL_CHECKSUMS, strict=True))


def split_narration(segments: list[dict], max_chars: int = 2000) -> list[dict]:
    if type(max_chars) is not int or not 1 <= max_chars <= 2000 or not segments:
        raise ValueError("Narration requires segments and a character bound up to 2000")
    chunks = []
    for segment in segments:
        text, identity = segment.get("text"), segment.get("id")
        if not isinstance(text, str) or not text.strip() or not isinstance(identity, str) or not identity:
            raise ValueError("Narration segment is incomplete")
        if len(text) > max_chars:
            raise ValueError("Narration segment exceeds bound; revise at a reviewed narrative boundary")
        if not chunks or len(chunks[-1]["text"]) + 1 + len(text) > max_chars:
            chunks.append({"text": text, "segment_ids": [identity]})
        else:
            chunks[-1]["text"] += " " + text
            chunks[-1]["segment_ids"].append(identity)
    return chunks


def script_segments(script):
    return ([{"id": "opening", "text": script["opening"]}] if script.get("opening") else []) + script["segments"] + (
        [{"id": "closing", "text": script["closing"]}] if script.get("closing") else [])


ONES = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
CONTRACTIONS = {"should've": "should have", "could've": "could have", "would've": "would have",
    "didn't": "did not", "doesn't": "does not", "don't": "do not", "wasn't": "was not", "weren't": "were not",
    "isn't": "is not", "aren't": "are not", "won't": "will not", "can't": "can not", "cannot": "can not",
    "hasn't": "has not", "haven't": "have not", "hadn't": "had not", "shouldn't": "should not",
    "wouldn't": "would not", "couldn't": "could not", "gotta": "got to", "gonna": "going to", "wanna": "want to"}


def _numbers(tokens):
    """Unambiguous cardinal/decimal orthography, never a numeric approximation.

    Keep adjacent independent numbers separate. Unsupported constructions remain
    tokens and hold on disagreement rather than guessing their numeric meaning.
    """
    def below_hundred(index):
        word = tokens[index] if index < len(tokens) else ""
        if word in ONES:
            return ONES[word], index + 1
        if word in TENS:
            value, end = TENS[word], index + 1
            if end < len(tokens) and tokens[end] in ONES and 0 < ONES[tokens[end]] < 10:
                value, end = value + ONES[tokens[end]], end + 1
            return value, end
        return None, index
    output, index = [], 0
    while index < len(tokens):
        start = index
        word = tokens[index]
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", word):
            output.append(format(Decimal(word).normalize(), "f"))
            index += 1
            continue
        if word == "a" and index + 1 < len(tokens) and tokens[index + 1] == "hundred":
            value, index = 1, index + 1
        else:
            value, index = below_hundred(index)
        if value is None:
            output.append(word)
            index += 1
            continue
        if index < len(tokens) and tokens[index] == "hundred" and 0 < value < 10:
            value *= 100
            index += 1
            tail_start = index + (index < len(tokens) and tokens[index] == "and")
            tail, end = below_hundred(tail_start)
            if tail is not None:
                value, index = value + tail, end
        result = str(value)
        if index < len(tokens) and tokens[index] == "point":
            end, decimal = index + 1, ""
            while end < len(tokens) and tokens[end] in ONES and ONES[tokens[end]] < 10:
                decimal += str(ONES[tokens[end]])
                end += 1
            if decimal:
                result, index = format(Decimal(result + "." + decimal).normalize(), "f"), end
        output.append(result)
        assert index > start
    return output


def _tokens(text):
    text = re.sub(r"\[[^\]]*\]", "", text.lower().replace("’", "'").replace("−", "-").replace("%", " percent").replace("$", "dollars "))
    words = re.findall(r"[-+]?\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?", text)
    expanded = [part for word in words for part in CONTRACTIONS.get(word, word).split()]
    return _numbers(expanded)


def verify_speech(script: dict, raw_transcript: dict) -> dict:
    expected = _tokens(" ".join(s["text"] for s in script_segments(script)))
    actual = _tokens(raw_transcript.get("text", ""))
    # Aliases are explicit reviewed name spellings, never number/result synonyms.
    forbidden = set("not no never won win wins lost lose loses tied beat defeated fourteen forty".split())
    for canonical, variants in script.get("name_aliases", {}).items():
        target = _tokens(canonical)
        if not target or any(t in forbidden or any(c.isdigit() for c in t) for t in target):
            continue
        for variant in variants:
            alias = _tokens(variant)
            if len(alias) != 1 or len(target) != 1 or alias[0] in forbidden or any(c.isdigit() for c in alias[0]):
                continue
            actual = [target[0] if t == alias[0] else t for t in actual]
    issues = []
    if actual != expected:
        issues.append("content_mismatch")
    for segment in script.get("segments", []):
        for number in segment.get("spoken_numbers", []):
            spoken = " ".join(_tokens(number["spoken"]))
            if (" " + " ".join(actual) + " ").count(" " + spoken + " ") != (
                    " " + " ".join(expected) + " ").count(" " + spoken + " "):
                issues.append("spoken_number_mismatch")
    for vocabulary, issue in (({"not", "no", "never", "didn't", "wasn't", "isn't"}, "negation_mismatch"),
            ({"won", "win", "wins", "lost", "lose", "loses", "tied", "beat", "defeated"}, "result_verb_mismatch")):
        if [t for t in actual if t in vocabulary] != [t for t in expected if t in vocabulary]:
            issues.append(issue)
    words = raw_transcript.get("words")
    if not isinstance(words, list) or not words:
        issues.append("speech_evidence_missing")
    else:
        previous = 0
        for word in words:
            try:
                start, end, probability = word["start"], word["end"], word["probability"]
                if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, probability)):
                    raise ValueError()
                if start < previous or end <= start or not 0 <= probability <= 1:
                    raise ValueError()
                previous = end
                if probability < .75:
                    issues.append("speech_confidence_low")
            except (KeyError, TypeError, ValueError):
                issues.append("speech_evidence_invalid")
                break
        if _tokens(" ".join(str(w.get("word", "")) for w in words)) != _tokens(raw_transcript.get("text", "")):
            issues.append("speech_evidence_inconsistent")
    return {"passed": not issues, "issues": sorted(set(issues)), "raw_transcript": raw_transcript,
        "verifier_revision": "strict-independent-v1"}


def verify_model_artifacts(directory):
    path = Path(directory)
    for name, expected in MODEL_SHA256.items():
        file = path / name
        if not file.is_file():
            raise ValueError("Pinned speech model artifact missing")
        sha = hashlib.sha256()
        with file.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != expected:
            raise ValueError("Pinned speech model checksum mismatch")
    return str(path.resolve())


def transcribe_local(audio_path, model_directory):
    path = verify_model_artifacts(model_directory)
    from faster_whisper import WhisperModel  # Worker-only optional pinned dependency.
    model = WhisperModel(path, device="cpu", compute_type="int8", local_files_only=True)
    # Supervisor decodes to bounded PCM WAV. Avoid depending on a second decoder
    # with different codec/runtime behavior inside the independent recognizer.
    import wave
    import numpy as np
    with wave.open(str(audio_path), "rb") as source:
        if source.getnchannels() != 1 or source.getframerate() != 16000 or source.getsampwidth() != 2 or source.getnframes() > 16000 * 1200:
            raise ValueError("Speech input must be bounded mono 16kHz PCM16 WAV")
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
    segments, info = model.transcribe(samples, language="en", beam_size=5,
        word_timestamps=True, condition_on_previous_text=False)
    rows = list(segments)
    return {"text": " ".join(s.text.strip() for s in rows),
        "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
            for s in rows for w in (s.words or [])],
        "segments": [{"text": s.text, "start": s.start, "end": s.end, "avg_logprob": s.avg_logprob,
            "no_speech_prob": s.no_speech_prob} for s in rows],
        "model_revision": MODEL_REVISION, "model_sha256": MODEL_SHA256["model.bin"]}


if __name__ == "__main__":
    import json
    import sys
    Path(sys.argv[3]).write_text(json.dumps(transcribe_local(sys.argv[1], sys.argv[2])))
