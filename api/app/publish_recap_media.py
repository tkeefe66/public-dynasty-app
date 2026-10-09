"""Attach an operator-reviewed episode without enabling or changing share links."""
import argparse
import json
import logging
from pathlib import Path

from app.services.analyst_media import AnalystMedia


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--league-id", required=True)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--week", required=True, type=int)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--duration-seconds", required=True, type=float)
    parser.add_argument("--bundle", required=True, type=Path, help="Directory with video.mp4, audio.mp3, poster.jpg, captions.vtt")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        manifest = AnalystMedia(args.cache_dir).attach(args.league_id, args.season, args.week, args.bundle,
            revision=args.revision, duration_seconds=args.duration_seconds)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Media was not published: {error}\nCheck the bundle, cache directory and published article revision.\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
