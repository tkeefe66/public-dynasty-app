"""Local, manual Dynasty Bitch pilot. No provider calls or scheduled work.

The ledger is an operator receipt, not a provider integration. A reservation
does not submit a job. Unknown/failed charges remain unresolved until reported.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import math
import re
import shutil
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ASSETS = Path(__file__).with_name("recap-pilot")
REPO = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("recap_pilot")


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    temp.replace(path)


def spoken_text(episode):
    return "\n\n".join(scene["narration"] for scene in episode["scenes"])


def script_hash(episode):
    return hashlib.sha256(spoken_text(episode).encode()).hexdigest()


def finite(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("Credits must be a finite, nonnegative number")
    return value


def initialize(cache, root):
    chain = read(cache)
    league_id = chain["league_id"]
    if (
        chain.get("league_name_by_id", {}).get(league_id, "").casefold()
        != "dynasty bitch"
    ):
        raise ValueError("This pilot is restricted to the Dynasty Bitch league")
    if chain.get("league_season_by_id", {}).get(league_id) != 2026:
        raise ValueError("The supplied pilot facts are for the 2026 Week 4 episode")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    episode = read(ASSETS / "episode.template.json")
    episode["league_id"] = league_id
    episode["audio"] = None
    write(
        root / "config.json",
        {"allowed_league_id": league_id, "season": 2026, "week": 4},
    )
    write(root / "episode.json", episode)
    write(root / "credits.json", {"quote": None, "attempts": []})
    LOG.info("Initialized one local pilot; no external requests submitted")


def load_episode(root):
    root = Path(root)
    config, episode = read(root / "config.json"), read(root / "episode.json")
    if (
        episode["league_id"] != config["allowed_league_id"]
        or episode["league_name"].casefold() != "dynasty bitch"
    ):
        raise ValueError("Episode league does not match the configured pilot league")
    if (episode["season"], episode["week"]) != (config["season"], config["week"]):
        raise ValueError("Only the configured season/week is enabled for this pilot")
    if episode["duration"] != 90:
        raise ValueError("The pilot duration must be 90 seconds")
    expected = 0
    kinds = {"intro", "score", "margin", "trades", "share", "outro"}
    for scene in episode["scenes"]:
        if scene["start"] != expected or not scene["start"] < scene["end"] <= 90:
            raise ValueError("Scene timeline has a gap, overlap or invalid duration")
        if scene["kind"] not in kinds or not scene["narration"].strip():
            raise ValueError("Each scene needs a supported graphic and narration")
        expected = scene["end"]
    if expected != 90:
        raise ValueError("Scene timeline must end at 90 seconds")
    # These supplied facts are fixed for this single-episode experiment.
    if episode["facts"] != read(ASSETS / "episode.template.json")["facts"]:
        raise ValueError(
            "Pilot facts changed; verify a new source before changing the template"
        )
    return episode


@contextmanager
def locked(root):
    root = Path(root)
    with (root / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield read(root / "credits.json")
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def stamp():
    return datetime.now(UTC).isoformat()


def quote(root, credits, model, voice_id, voice_type):
    finite(credits)
    episode = load_episode(root)
    if not model or not voice_id or voice_type not in {"preset", "element"}:
        raise ValueError("A quote needs the exact model and selected voice ID/type")
    with locked(root) as ledger:
        ledger["quote"] = {
            "credits": credits,
            "model": model,
            "voice_id": voice_id,
            "voice_type": voice_type,
            "script_hash": script_hash(episode),
            "at": stamp(),
        }
        write(Path(root) / "credits.json", ledger)
    LOG.info("Recorded provider quote: %s credits; no job submitted", credits)


def reserve(root, attempt_id, credit_cap):
    finite(credit_cap)
    episode = load_episode(root)
    with locked(root) as ledger:
        quoted = ledger["quote"]
        if not quoted or quoted["script_hash"] != script_hash(episode):
            raise ValueError(
                "Obtain a new quote for the current script before reserving"
            )
        if not attempt_id.strip() or any(
            a["id"] == attempt_id for a in ledger["attempts"]
        ):
            raise ValueError(
                "Attempt ID must be nonempty and unique; never resubmit an unknown request"
            )
        if any(a["actual_credits"] is None for a in ledger["attempts"]):
            raise ValueError(
                "An earlier charge is unresolved; reconcile it before another attempt"
            )
        spent = sum(a["actual_credits"] for a in ledger["attempts"])
        if credit_cap <= 0 or spent + quoted["credits"] > credit_cap:
            raise ValueError("Quote exceeds the explicit total pilot credit cap")
        ledger["attempts"].append(
            {
                **quoted,
                "id": attempt_id,
                "status": "reserved",
                "actual_credits": None,
                "job_id": None,
                "credit_cap": credit_cap,
                "events": [{"at": stamp(), "status": "reserved"}],
            }
        )
        write(Path(root) / "credits.json", ledger)
    LOG.info(
        "Reserved attempt %s; submit manually once, then record the provider receipt",
        attempt_id,
    )


def settle(root, attempt_id, status, actual_credits, job_id=None):
    if status not in {"submitted", "completed", "failed", "canceled"}:
        raise ValueError("Unsupported provider status")
    if actual_credits is not None:
        finite(actual_credits)
    with locked(root) as ledger:
        attempt = next((a for a in ledger["attempts"] if a["id"] == attempt_id), None)
        if not attempt:
            raise ValueError("No reserved attempt with that ID")
        if attempt["actual_credits"] is not None:
            raise ValueError(
                "Receipt already settled; preserve it rather than overwrite it"
            )
        if status == "submitted" and actual_credits is not None:
            raise ValueError("A pending job cannot be marked settled")
        attempt.update(status=status, actual_credits=actual_credits)
        if job_id:
            attempt["job_id"] = job_id
        attempt["events"].append(
            {
                "at": stamp(),
                "status": status,
                "actual_credits": actual_credits,
                "job_id": job_id,
            }
        )
        write(Path(root) / "credits.json", ledger)
    LOG.info(
        "Recorded %s for %s; charge %s",
        status,
        attempt_id,
        actual_credits if actual_credits is not None else "unknown",
    )


def cost_summary(root):
    ledger = read(Path(root) / "credits.json")
    return {
        "quoted_credits": ledger["quote"]["credits"] if ledger["quote"] else None,
        "known_charged_credits": sum(
            a["actual_credits"]
            for a in ledger["attempts"]
            if a["actual_credits"] is not None
        ),
        "unsettled_attempts": sum(
            a["actual_credits"] is None for a in ledger["attempts"]
        ),
        "attempts": len(ledger["attempts"]),
    }


def attach_audio(root, path, attempt_id):
    root, path = Path(root), Path(path)
    episode = load_episode(root)
    if (
        path.suffix.lower() not in {".mp3", ".wav", ".m4a", ".ogg"}
        or not path.is_file()
    ):
        raise ValueError("Import an existing MP3, WAV, M4A or OGG narration file")
    with locked(root) as ledger:
        attempt = next((a for a in ledger["attempts"] if a["id"] == attempt_id), None)
        if (
            not attempt
            or attempt["status"] != "completed"
            or attempt["script_hash"] != script_hash(episode)
        ):
            raise ValueError("Audio needs a completed attempt for this exact script")
        dest = root / ("narration" + path.suffix.lower())
        if path.resolve() != dest.resolve():
            shutil.copy2(path, dest)
        episode["audio"] = {
            "file": dest.name,
            "script_hash": attempt["script_hash"],
            "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "attempt_id": attempt_id,
        }
        write(root / "episode.json", episode)
    LOG.info("Attached narration; preview its duration and cue timing before export")


def build(root):
    root = Path(root)
    episode = load_episode(root)
    digest = script_hash(episode)
    audio = episode.get("audio")
    if audio:
        path = root / audio["file"]
        if (
            path.parent != root
            or audio["script_hash"] != digest
            or hashlib.sha256(path.read_bytes()).hexdigest() != audio["sha256"]
        ):
            raise ValueError(
                "Narration does not match the current script/file; import the correct take"
            )
    out = root / "preview"
    out.mkdir(exist_ok=True)
    for name in ("index.html", "player.js", "style.css"):
        shutil.copy2(ASSETS / name, out / name)
    fonts = out / "fonts"
    fonts.mkdir(exist_ok=True)
    for path in (REPO / ".design/assets/fonts").iterdir():
        shutil.copy2(path, fonts / path.name)
    public = {k: v for k, v in episode.items() if k != "league_id"}
    public.update(script_hash=digest, credits=cost_summary(root))
    # JSON lives in a JS file, not an HTML script tag; no markup interpolation.
    (out / "episode.js").write_text(
        "window.EPISODE = "
        + json.dumps(public, ensure_ascii=False, allow_nan=False)
        + ";\n"
    )
    (root / "narration.txt").write_text(spoken_text(episode) + "\n")
    if audio:
        shutil.copy2(root / audio["file"], out / audio["file"])
    LOG.info(
        "Built %s; %s words; no provider requests",
        out,
        len(spoken_text(episode).split()),
    )
    return out


def range_bounds(header, size):
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError("Invalid media byte range")
    left, right = match.groups()
    if left:
        start, end = int(left), min(int(right), size - 1) if right else size - 1
    else:
        start, end = max(0, size - int(right)), size - 1
    if not 0 <= start <= end < size:
        raise ValueError("Media range is outside the file")
    return start, end


class PreviewHandler(SimpleHTTPRequestHandler):
    """Serve only the preview directory, with the ranges media seeking needs."""

    def send_head(self):
        self.remaining = None
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(Path(self.directory).resolve()):
            self.send_error(403, "File is outside the pilot preview")
            return None
        header = self.headers.get("Range")
        if not header or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        try:
            start, end = range_bounds(header, size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        handle = path.open("rb")
        handle.seek(start)
        self.remaining = end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Length", str(self.remaining))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return handle

    def copyfile(self, source, outputfile):
        if self.remaining is None:
            return super().copyfile(source, outputfile)
        while self.remaining > 0:
            chunk = source.read(min(64 * 1024, self.remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            self.remaining -= len(chunk)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / ".recap-pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--cache", type=Path, required=True)
    sub.add_parser("build")
    sub.add_parser("costs")
    server = sub.add_parser("serve")
    server.add_argument("--port", type=int, default=4821)
    q = sub.add_parser("quote")
    q.add_argument("--credits", type=float, required=True)
    q.add_argument("--model", required=True)
    q.add_argument("--voice-id", required=True)
    q.add_argument("--voice-type", choices=["preset", "element"], required=True)
    r = sub.add_parser("reserve")
    r.add_argument("--attempt", required=True)
    r.add_argument("--credit-cap", type=float, required=True)
    s = sub.add_parser("settle")
    s.add_argument("--attempt", required=True)
    s.add_argument(
        "--status",
        choices=["submitted", "completed", "failed", "canceled"],
        required=True,
    )
    s.add_argument("--actual-credits", type=float)
    s.add_argument("--job-id")
    a = sub.add_parser("audio")
    a.add_argument("--file", type=Path, required=True)
    a.add_argument("--attempt", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.command == "init":
            initialize(args.cache, args.root)
        elif args.command == "build":
            build(args.root)
        elif args.command == "quote":
            quote(args.root, args.credits, args.model, args.voice_id, args.voice_type)
        elif args.command == "reserve":
            reserve(args.root, args.attempt, args.credit_cap)
        elif args.command == "settle":
            settle(
                args.root, args.attempt, args.status, args.actual_credits, args.job_id
            )
        elif args.command == "audio":
            attach_audio(args.root, args.file, args.attempt)
        elif args.command == "serve":
            preview = args.root / "preview"
            if not (preview / "index.html").is_file():
                raise ValueError("Build the pilot before serving its preview")
            handler = partial(PreviewHandler, directory=str(preview))
            with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
                LOG.info("Local pilot: http://127.0.0.1:%s", args.port)
                try:
                    server.serve_forever()
                except KeyboardInterrupt:
                    LOG.info("Pilot preview stopped")
        else:
            print(json.dumps(cost_summary(args.root), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        LOG.error(
            "Pilot %s failed: %s. Check the local episode/config and receipts before retrying.",
            args.command,
            exc,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
