"""Synthetic full season: missing one game must fail independent qualification."""
import csv
import io
import json

import pytest

from sleeper_dynasty.api.nfl_schedule import NFL_TEAMS


def season_sources():
    teams = sorted(NFL_TEAMS)
    rows, events = [], []
    for week in range(1, 18):
        rotated = teams[1:]
        rotated = rotated[week-1:] + rotated[:week-1]
        ring = [teams[0], *rotated]
        for j in range(16):
            home, away = ring[j], ring[-j-1]
            ident = f"synthetic-{week}-{j}"
            rows.append(dict(game_id=ident, season=2026, game_type="REG", week=week,
                gameday="2026-10-11", gametime="13:00", home_team=home, away_team=away, espn=ident))
            events.append({"id": ident, "season": {"year": 2026, "type": 2}, "week": {"number": week},
                "date": "2026-10-11T17:00:00Z", "competitions": [{"date": "2026-10-11T17:00:00Z", "competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}}]}]})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=rows[0])
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode(), json.dumps({"events": events}).encode()


def test_qualifies_full_season_and_persists_original_bytes_crosswalk():
    from sleeper_dynasty.api.nfl_inventory import qualify_inventory
    raw, second = season_sources()
    result = qualify_inventory(raw, [second], 2026)
    assert len(result["games"]) == 272
    assert result["source_bytes"]["nflverse"].encode() == raw
    assert result["source_bytes"]["espn"][0].encode() == second
    assert result["games"][0]["source_id"].startswith("synthetic-")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "teams", "week", "schema"])
def test_partial_or_conflicting_second_source_never_qualifies(mutation):
    from sleeper_dynasty.api.nfl_inventory import qualify_inventory, InventoryUnqualified
    raw, second = season_sources()
    payload = json.loads(second)
    if mutation == "missing":
        payload["events"].pop()
    elif mutation == "duplicate":
        payload["events"].append(payload["events"][0])
    elif mutation == "teams":
        payload["events"][0]["competitions"][0]["competitors"][0]["team"]["abbreviation"] = "NO"
    elif mutation == "week":
        payload["events"][0]["week"]["number"] = 18
    else:
        raw = b"unexpected,schema\n1,2\n"
    with pytest.raises(InventoryUnqualified, match="schedule_inventory_unqualified"):
        qualify_inventory(raw, [json.dumps(payload).encode()], 2026)


def test_scores_do_not_change_schedule_revision():
    from sleeper_dynasty.api.nfl_inventory import qualify_inventory
    raw, second = season_sources()
    payload = json.loads(second)
    payload["events"][0]["status"] = {"type": {"completed": True}}
    assert qualify_inventory(raw, [second], 2026)["revision"] == qualify_inventory(
        raw, [json.dumps(payload).encode()], 2026)["revision"]
