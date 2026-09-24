"""Select evidence for a single edition without inferring a cause from low usage."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MAX_NEWS = 60
LIMITED_SHARE = 0.25  # At most a quarter of offensive plays; never an injury diagnosis.


def _team(value):
    return {"LAR": "LA", "STL": "LA", "SD": "LAC", "OAK": "LV", "JAC": "JAX", "WSH": "WAS"}.get(value, value)


def _time(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def build_context(*, season, week, now, results, players, news_by_player, snap_rows, id_rows, schedule_rows):
    kickoffs = {}
    week_starts = {}
    for row in schedule_rows:
        if str(row.get("season")) != str(season) or row.get("game_type") != "REG":
            continue
        try:
            game_week = int(row["week"])
            start = datetime.fromisoformat(f'{row["gameday"]}T{row["gametime"]}').replace(
                tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        except (ValueError, TypeError, KeyError):
            continue
        week_starts[game_week] = min(start, week_starts.get(game_week, start))
        if game_week == week:
            for team in (row.get("home_team"), row.get("away_team")):
                kickoffs[_team(team)] = start.isoformat()
    start = week_starts.get(week)
    # A historical boundary must be backed by next week's actual schedule.
    end = week_starts.get(week + 1)
    cutoff = min(now, end) if end else None
    window_start = start - timedelta(days=7) if start else None
    chronology = bool(window_start and cutoff)
    mapping = {}
    for row in id_rows:
        pfr, sid = row.get("pfr_id"), row.get("sleeper_id")
        if pfr and sid and pfr not in ("NA", "null") and sid not in ("NA", "null"):
            mapping.setdefault(pfr, set()).add(sid)
    usage = {}
    teams = {}
    for row in snap_rows:
        if (str(row.get("season")) != str(season) or str(row.get("week")) != str(week)
                or row.get("game_type") != "REG"):
            continue
        matches = mapping.get(row.get("pfr_player_id"), set())
        if len(matches) != 1:
            continue
        sid = next(iter(matches))
        snaps, share = _number(row.get("offense_snaps")), _number(row.get("offense_pct"))
        if snaps is None or snaps < 0 or not snaps.is_integer() or share is None or not 0 <= share <= 1:
            continue
        usage[sid] = {"offense_snaps": int(snaps), "offense_share": share, "limited_opportunity": share <= LIMITED_SHARE}
        teams[sid] = row.get("team")
    starter_points = {pid: r.players_points.get(pid, 0) for r in results for pid in r.starters if pid != "0"}
    # Rostered bench players are lower priority; they provide context for legal
    # swaps already verified by the recap engine, never new swap recommendations.
    rostered = {pid for r in results for pid in r.players if pid != "0"}
    ordered = sorted(starter_points, key=lambda pid: (starter_points[pid], pid)) + sorted(rostered - starter_points.keys())
    selected = []
    notes = []
    if not chronology:
        notes.append("News omitted because the NFL week schedule is unavailable.")
    for pid in ordered:
        player = players.get(pid)
        if player is None:
            continue
        relevant = {}
        for item in news_by_player.get(pid, []) if chronology else []:
            published, observed = _time(item.get("published_at")), _time(item.get("observed_at"))
            if (published is None or observed is None or not window_start <= published <= cutoff or observed > cutoff):
                continue
            prior = relevant.get(item["item_id"])
            if prior is None or observed > _time(prior["observed_at"]):
                relevant[item["item_id"]] = item
        items = sorted(relevant.values(), key=lambda n: n["published_at"], reverse=True)[:2]
        if pid not in starter_points and not items:
            continue
        # Weekly team from the snap row is historical evidence. Today's roster
        # team must not assign an old kickoff after an NFL trade.
        selected.append({"player_id": pid, "player": player.full_name, "position": player.position,
                         "started": pid in starter_points, "usage": usage.get(pid),
                         "kickoff_at": kickoffs.get(_team(teams.get(pid))), "news": [], "_candidates": items})
    count = 0
    for slot in range(2):
        for player in selected:
            if count < MAX_NEWS and len(player["_candidates"]) > slot:
                player["news"].append(player["_candidates"][slot])
                count += 1
    for player in selected:
        del player["_candidates"]
    missing_usage = sum(p["started"] and p["usage"] is None for p in selected)
    if missing_usage:
        notes.append(f"Snap counts unavailable for {missing_usage} starters; missing data is not zero playing time.")
    if not count:
        notes.append("No eligible player news was available by this edition's evidence cutoff.")
    sources = []
    seen = set()
    for player in selected:
        for item in player["news"]:
            if item["id"] not in seen:
                seen.add(item["id"])
                sources.append({k: item.get(k) for k in ("publisher", "title", "published_at", "url")})
    if any(p["usage"] for p in selected):
        sources.append({"publisher": "nflverse / Pro Football Reference", "title": f"{season} Week {week} snap counts",
                        "published_at": None, "url": "https://nflreadr.nflverse.com/reference/load_snap_counts.html"})
    return {"season": season, "week": week, "as_of": (cutoff or now).isoformat(),
            "players": selected, "news_count": count, "sources": sources,
            "note": " ".join(notes) or None}
