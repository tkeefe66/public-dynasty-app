"""Free public context sources. No credentials, model calls or dynamic hosts."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
GRAPHQL_URL = "https://sleeper.com/graphql"
CSV_URLS = {
    "snaps": "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv",
    "ids": "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv",
    "schedule": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
}
PUBLISHERS = {"rotowire": ("RotoWire", "rotowire.com"), "rotoballer": ("RotoBaller", "rotoballer.com"),
              "fantasy_pros": ("FantasyPros", "fantasypros.com")}


class SourceUnavailable(RuntimeError):
    def __init__(self, message: str, retry_after: float = 900):
        super().__init__(message)
        self.retry_after = min(86400, max(900, retry_after))


def safe_source_url(value, domain: str | None) -> str | None:
    if not isinstance(value, str) or not domain or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and (host == domain or host.endswith("." + domain))
                and not any(ord(c) < 33 for c in value) and "\\" not in value):
            return value
    except ValueError:
        pass
    return None


def normalize_news(rows: list[dict], *, observed_at: datetime) -> list[dict]:
    """Retain an observation/version, not an inferred cause or event date."""
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("metadata"), dict):
            continue
        meta = row["metadata"]
        try:
            milliseconds = float(row["published"])
            if not math.isfinite(milliseconds):
                continue
            published = datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
            if not 2000 <= published.year <= 2200:
                continue
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        def clean(value, limit):
            return " ".join(BeautifulSoup(value, "html.parser").get_text(" ").split())[:limit] if isinstance(value, str) else ""
        title = clean(meta.get("title"), 240)
        text = clean(" ".join(v for v in (meta.get("description"), meta.get("analysis")) if isinstance(v, str)), 1200)
        if not title or not text:
            continue
        source = row.get("source") if isinstance(row.get("source"), str) else "unknown"
        publisher, domain = PUBLISHERS.get(source, ("Sleeper news", None))
        identity = json.dumps([source, published.isoformat(), str(meta.get("topic_id") or title)])
        item_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        url = safe_source_url(meta.get("url"), domain)
        version = hashlib.sha256(json.dumps([item_id, title, text, url]).encode()).hexdigest()[:24]
        result.append({"id": version, "item_id": item_id, "publisher": publisher, "title": title,
                       "text": text, "url": url, "published_at": published.isoformat(),
                       "observed_at": observed_at.isoformat()})
    return result


class PlayerContextClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _request(self, method, url, **kwargs):
        log.info("Player context request provider=%s method=%s", urlsplit(url).hostname, method)
        try:
            response = await self.http.request(method, url, timeout=12,
                headers={"User-Agent": "public-dynasty-player-context/1.0"}, **kwargs)
            if response.status_code >= 400:
                try:
                    delay = float(response.headers.get("Retry-After", 900))
                except ValueError:
                    delay = 900
                raise SourceUnavailable(f"Player context HTTP {response.status_code}; retry after backoff", delay)
            response.raise_for_status()
            if len(response.content) > 12_000_000:
                raise SourceUnavailable("Player context response exceeds 12 MB; source omitted")
            return response
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"Player context request failed ({type(exc).__name__}); retry after backoff") from exc

    async def news(self, player_ids: list[str]) -> dict[str, list[dict]]:
        if not player_ids or len(player_ids) > 10:
            raise ValueError("News batches require one to ten players")
        fields = [f'p{i}:get_player_news(sport:"nfl",player_id:{json.dumps(pid)},limit:20){{source published metadata}}'
                  for i, pid in enumerate(player_ids)]
        response = await self._request("POST", GRAPHQL_URL, json={"query": "{" + " ".join(fields) + "}"})
        try:
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
                raise ValueError("GraphQL refused the query")
            result = {pid: payload["data"].get(f"p{i}") for i, pid in enumerate(player_ids)}
            if any(not isinstance(rows, list) for rows in result.values()):
                raise ValueError("Missing player news list")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailable("Sleeper news returned invalid or refused GraphQL data; retry after backoff") from exc

    async def csv_rows(self, resource: str, season: int) -> list[dict]:
        response = await self._request("GET", CSV_URLS[resource].format(season=season), follow_redirects=True)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        required = {"snaps": {"season", "week", "game_type", "team", "pfr_player_id", "offense_snaps", "offense_pct"},
                    "ids": {"pfr_id", "sleeper_id"},
                    "schedule": {"season", "week", "gameday", "gametime", "game_type", "home_team", "away_team"}}
        if not rows or not required[resource].issubset(rows[0]):
            raise SourceUnavailable(f"Invalid {resource} CSV; source omitted until next retry")
        return rows
