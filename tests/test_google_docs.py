"""Unit tests for Google Docs request builders.

These verify the pure functions used to construct ``batchUpdate`` payloads
for the Google Docs API. The class-level integration is exercised by the
broader integration test (which mocks the API client).
"""

from unittest.mock import MagicMock

import pytest

from sleeper_dynasty.engine.simulator import (
    MatchupSimResult,
    SimulationResult,
    TeamSimResult,
)
from sleeper_dynasty.models.league import League, Roster
from sleeper_dynasty.output.google_docs import (
    COLOR_BLACK,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_WHITE,
    COLOR_YELLOW,
    GoogleDocsReport,
    _call_with_retry,
    _empty_table_footprint,
    _outlook_label,
    _playoff_color,
    build_cell_background_request,
    build_heading_request,
    build_page_break_request,
    build_paragraph_style_request,
    build_table_request,
    build_text_request,
    build_text_style_request,
)


def test_build_heading_request():
    req = build_heading_request("League Overview", index=1)
    assert req["insertText"]["text"] == "League Overview\n"
    assert req["insertText"]["location"]["index"] == 1


def test_build_text_request():
    req = build_text_request("Some body text here.", index=1)
    assert req["insertText"]["text"] == "Some body text here.\n"


def test_build_table_request():
    req = build_table_request(rows=3, columns=3, index=1)
    assert req["insertTable"]["rows"] == 3
    assert req["insertTable"]["columns"] == 3
    assert req["insertTable"]["location"]["index"] == 1


def test_build_page_break_request():
    req = build_page_break_request(index=42)
    assert req == {"insertPageBreak": {"location": {"index": 42}}}


def test_build_paragraph_style_request():
    req = build_paragraph_style_request(1, 10, "HEADING_1")
    assert req["updateParagraphStyle"]["paragraphStyle"][
        "namedStyleType"
    ] == "HEADING_1"
    assert req["updateParagraphStyle"]["range"] == {
        "startIndex": 1,
        "endIndex": 10,
    }
    assert req["updateParagraphStyle"]["fields"] == "namedStyleType"


def test_build_text_style_request_bold_only():
    req = build_text_style_request(1, 5, bold=True)
    ts = req["updateTextStyle"]
    assert ts["textStyle"] == {"bold": True}
    assert ts["fields"] == "bold"
    assert ts["range"] == {"startIndex": 1, "endIndex": 5}


def test_build_text_style_request_multi_field():
    req = build_text_style_request(
        1, 5, bold=True, font_size_pt=18, foreground_color=COLOR_WHITE
    )
    ts = req["updateTextStyle"]
    assert ts["textStyle"]["bold"] is True
    assert ts["textStyle"]["fontSize"] == {"magnitude": 18, "unit": "PT"}
    assert (
        ts["textStyle"]["foregroundColor"]["color"]["rgbColor"] == COLOR_WHITE
    )
    # fields should mention all three.
    for f in ("bold", "fontSize", "foregroundColor"):
        assert f in ts["fields"]


def test_build_cell_background_request():
    req = build_cell_background_request(
        table_start_index=100, row=2, column=4, color=COLOR_GREEN
    )
    cs = req["updateTableCellStyle"]
    assert cs["fields"] == "backgroundColor"
    assert cs["tableCellStyle"]["backgroundColor"]["color"]["rgbColor"] == (
        COLOR_GREEN
    )
    loc = cs["tableRange"]["tableCellLocation"]
    assert loc["tableStartLocation"]["index"] == 100
    assert loc["rowIndex"] == 2
    assert loc["columnIndex"] == 4
    assert cs["tableRange"]["rowSpan"] == 1
    assert cs["tableRange"]["columnSpan"] == 1


def test_playoff_color_thresholds():
    assert _playoff_color(90.0) == COLOR_GREEN
    assert _playoff_color(70.0) == COLOR_GREEN
    assert _playoff_color(55.0) == COLOR_YELLOW
    assert _playoff_color(30.0) == COLOR_YELLOW
    assert _playoff_color(15.0) == COLOR_RED


def test_outlook_label():
    assert _outlook_label(75.0) == "Contender"
    assert _outlook_label(60.0) == "Contender"
    assert _outlook_label(40.0) == "Bubble"
    assert _outlook_label(30.0) == "Bubble"
    assert _outlook_label(10.0) == "Rebuilding"


def test_google_docs_report_init():
    report = GoogleDocsReport(league_name="Test League")
    assert report.title == "Test League - Dynasty Analysis"
    assert report.league_name == "Test League"


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


def _make_http_error(status: int):
    """Build an ``HttpError`` instance with a given status for tests."""
    from googleapiclient.errors import HttpError

    resp = MagicMock()
    resp.status = status
    resp.reason = "Quota exceeded" if status == 429 else "Error"
    # The HttpError constructor only needs (resp, content). content can be
    # any bytes-like; we don't inspect it.
    return HttpError(resp=resp, content=b"{}")


def test_call_with_retry_passes_through_success():
    sentinel = object()
    result = _call_with_retry(lambda: sentinel, context="test")
    assert result is sentinel


def test_call_with_retry_retries_on_429_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def op():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_http_error(429)
        return "ok"

    result = _call_with_retry(op, context="test", sleep=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 3
    # Backoff schedule: attempt 0 -> 1s, attempt 1 -> 2s
    assert sleeps == [1.0, 2.0]


def test_call_with_retry_raises_after_max_attempts():
    sleeps: list[float] = []

    def op():
        raise _make_http_error(429)

    from googleapiclient.errors import HttpError

    with pytest.raises(HttpError):
        _call_with_retry(op, context="test", sleep=sleeps.append)
    # 5 attempts means 4 sleeps before the final attempt.
    assert len(sleeps) == 4
    # Backoff caps at 60s.
    assert all(s <= 60.0 for s in sleeps)
    # Schedule should be 1, 2, 4, 8.
    assert sleeps == [1.0, 2.0, 4.0, 8.0]


def test_call_with_retry_does_not_retry_non_429():
    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise _make_http_error(500)

    from googleapiclient.errors import HttpError

    with pytest.raises(HttpError):
        _call_with_retry(op, context="test", sleep=lambda _: None)
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Empty-table footprint formula
# ---------------------------------------------------------------------------


def test_empty_table_footprint_formula():
    # 1 row × 1 col empty table: 1 table marker + 1 row marker + 1 cell wrapper
    # + 1 paragraph end = 4 indices.
    assert _empty_table_footprint(1, 1) == 1 + 1 * (1 + 2 * 1)
    # 2 rows × 3 cols: 1 + 2 * (1 + 6) = 15
    assert _empty_table_footprint(2, 3) == 15


# ---------------------------------------------------------------------------
# End-to-end call-count tests
#
# The whole point of the recent refactor is to avoid Google Docs' 60 writes
# per minute quota by packing many sub-requests into a small number of
# batchUpdate HTTP calls. These tests mock the docs service and assert that
# each ``write_tab_*`` method makes only a handful of calls — NOT one per
# paragraph or cell.
# ---------------------------------------------------------------------------


def _build_mock_docs_service():
    """Return a mock ``docs_service`` and counters tracking API call volume.

    The mock tracks every ``insertTable`` request issued via ``batchUpdate``
    so that on subsequent ``documents.get`` calls it can return synthetic
    table elements at those exact indices. This mimics the real API closely
    enough that the populate phase can locate every queued table.
    """
    docs_service = MagicMock()
    batch_calls: list[list[dict]] = []
    get_calls = [0]
    # Inserted tables: list of (start_index, rows, columns) in insertion
    # order. The synthetic get_doc reconstructs each table's structure so
    # the populate phase can locate every cell — required for tests that
    # exercise per-cell behavior (e.g., text color on colored cells).
    inserted_tables: list[tuple[int, int, int]] = []

    def batch_update(documentId, body):
        requests = body["requests"]
        batch_calls.append(requests)
        for req in requests:
            if "insertTable" in req:
                it = req["insertTable"]
                inserted_tables.append(
                    (it["location"]["index"], it["rows"], it["columns"])
                )
        m = MagicMock()
        m.execute = MagicMock(return_value={})
        return m

    def get_doc(documentId):
        get_calls[0] += 1
        content = []
        # Deduplicate by start_index (last wins) and emit synthetic table
        # elements that match the dimensions of the original insertTable.
        seen: dict[int, tuple[int, int]] = {}
        for idx, rows, cols in inserted_tables:
            seen[idx] = (rows, cols)
        for idx in sorted(seen):
            rows, cols = seen[idx]
            table_rows = []
            cell_counter = 0
            for r in range(rows):
                cells = []
                for c in range(cols):
                    # Each cell content paragraph gets a unique index based
                    # on the table start so populate inserts don't collide.
                    cells.append({"startIndex": idx + 1 + cell_counter})
                    cell_counter += 1
                table_rows.append({"tableCells": cells})
            content.append(
                {
                    "startIndex": idx,
                    "endIndex": idx + 50 + cell_counter,
                    "table": {"tableRows": table_rows},
                }
            )
        # Trailing paragraph so _get_end_index returns a sensible value.
        content.append(
            {
                "startIndex": 1,
                "endIndex": 2,
                "paragraph": {},
            }
        )
        m = MagicMock()
        m.execute = MagicMock(return_value={"body": {"content": content}})
        return m

    docs_service.documents.return_value.batchUpdate.side_effect = batch_update
    docs_service.documents.return_value.get.side_effect = get_doc
    return docs_service, batch_calls, get_calls


def _make_league_fixture():
    league = League(
        league_id="L1",
        name="Test Dynasty",
        season=2026,
        total_rosters=2,
        roster_positions=["QB", "RB", "WR"],
        scoring_settings={"rec": 1.0, "pass_td": 4.0},
        playoff_week_start=15,
        num_playoff_teams=2,
        status="in_season",
    )
    rosters = [
        Roster(
            roster_id=1,
            owner_id="u1",
            owner_name="Alice",
            players=["p1"],
            wins=3,
            losses=1,
            ties=0,
            points_for=420.5,
            points_against=380.0,
        ),
        Roster(
            roster_id=2,
            owner_id="u2",
            owner_name="Bob",
            players=["p2"],
            wins=1,
            losses=3,
            ties=0,
            points_for=380.0,
            points_against=420.5,
        ),
    ]
    return league, rosters


def _make_sim_result(rosters):
    team_results = {
        r.roster_id: TeamSimResult(
            roster_id=r.roster_id,
            avg_wins=8.5,
            avg_losses=5.5,
            win_low=6,
            win_high=11,
            playoff_pct=55.0,
            championship_pct=12.0,
            avg_points_for=1500.0,
        )
        for r in rosters
    }
    matchup_results = [
        MatchupSimResult(
            week=1,
            roster_id_1=1,
            roster_id_2=2,
            win_pct_1=55.0,
            win_pct_2=45.0,
            avg_score_1=120.0,
            avg_score_2=110.0,
        ),
    ]
    return SimulationResult(
        team_results=team_results, matchup_results=matchup_results
    )


def test_write_tab_projected_standings_makes_few_api_calls():
    """Projected Standings has 1 table → 1 structural chunk + 1 populate
    batch = 2 batchUpdate calls. 1 starting-cursor GET + 1 populate GET
    = 2 documents.get calls (no inter-chunk GET since the table-ending
    chunk is also the final chunk)."""
    league, rosters = _make_league_fixture()
    roster_map = {r.roster_id: r for r in rosters}
    sim = _make_sim_result(rosters)

    report = GoogleDocsReport(league_name=league.name)
    docs_service, batch_calls, get_calls = _build_mock_docs_service()
    report._docs_service = docs_service

    report.write_tab_projected_standings("doc1", sim, roster_map)

    assert len(batch_calls) == 2
    assert get_calls[0] == 2


def test_write_tab_matchup_forecasts_makes_few_api_calls():
    """All weeks share one section flush. With ``W`` weekly tables that's
    W structural chunks + 1 populate batch. The fixture emits 1 week → 1
    table → 1 structural chunk + 1 populate = 2 batchUpdate calls."""
    league, rosters = _make_league_fixture()
    roster_map = {r.roster_id: r for r in rosters}
    sim = _make_sim_result(rosters)

    report = GoogleDocsReport(league_name=league.name)
    docs_service, batch_calls, get_calls = _build_mock_docs_service()
    report._docs_service = docs_service

    report.write_tab_matchup_forecasts("doc1", sim, roster_map)

    # Fixture has only 1 week → 1 table → 1 chunk + 1 populate.
    assert len(batch_calls) == 2
    assert get_calls[0] == 2


def test_no_insert_text_after_insert_table_in_same_batch():
    """Critical invariant guarding against the recurring "insertion index
    must be inside the bounds of an existing paragraph" error.

    The Google Docs API throws that error when a batch contains an
    ``insertText`` request whose index falls inside a table inserted
    earlier in the SAME batch. The previous structural-insert design
    computed text-after-table indices via the empty-table footprint
    formula ``1 + R*(1 + 2*C)`` and the formula occasionally drifted
    from the API's actual table footprint, breaking real runs even
    though the test mock accepted it.

    The new chunked-flush model partitions every section into batches
    where each batch contains at most ONE ``insertTable`` and that
    ``insertTable`` is always the LAST sub-request in the batch. This
    test enforces that invariant for every batchUpdate emitted during
    a full doc write.
    """
    league, rosters = _make_league_fixture()
    roster_map = {r.roster_id: r for r in rosters}
    sim = _make_sim_result(rosters)

    report = GoogleDocsReport(league_name=league.name)
    docs_service, batch_calls, _ = _build_mock_docs_service()
    report._docs_service = docs_service

    report.write_tab_projected_standings("doc1", sim, roster_map)
    report.write_tab_team_reports(
        "doc1",
        rosters,
        sim,
        dynasty_outlooks={},
        player_projections={},
        player_names={},
        player_ages={},
    )
    report.write_tab_matchup_forecasts("doc1", sim, roster_map)

    for batch_idx, requests in enumerate(batch_calls):
        seen_insert_table = False
        for req_idx, req in enumerate(requests):
            if "insertTable" in req:
                # A second insertTable in the same batch would also be
                # suspect — we allow at most one per structural batch.
                assert not seen_insert_table, (
                    f"Batch {batch_idx} contains multiple insertTable "
                    f"requests; the chunked-flush invariant requires one "
                    f"insertTable per batch (request {req_idx})"
                )
                seen_insert_table = True
            elif "insertText" in req and seen_insert_table:
                pytest.fail(
                    f"Batch {batch_idx} request {req_idx} is an "
                    f"insertText AFTER an insertTable in the same "
                    f"batch — this is the exact pattern that triggers "
                    f"the 'insertion index must be inside the bounds "
                    f"of an existing paragraph' Google Docs API error."
                )


def test_throttler_sleeps_when_budget_exhausted(monkeypatch):
    """When we hit the write budget, the throttler should sleep."""
    from sleeper_dynasty.output.google_docs import GoogleDocsReport
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    report = GoogleDocsReport(league_name="test")
    # Pre-fill the timestamps to exactly the budget
    now = time.time()
    report._write_timestamps = [now - i * 0.5 for i in range(report._WRITES_PER_MINUTE)]

    report._throttle_before_write()

    assert len(sleeps) == 1, "expected one sleep call when over budget"
    assert sleeps[0] > 0, "expected positive sleep duration"


def test_throttler_no_sleep_when_under_budget(monkeypatch):
    """When we're under the budget, no sleep should happen."""
    from sleeper_dynasty.output.google_docs import GoogleDocsReport
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    report = GoogleDocsReport(league_name="test")
    # Only 5 prior writes — well under budget
    now = time.time()
    report._write_timestamps = [now - i * 0.5 for i in range(5)]

    report._throttle_before_write()

    assert sleeps == [], "expected no sleep when under budget"


def test_full_doc_well_under_quota():
    """End-to-end: writing the whole doc emits well under 60 batchUpdate
    HTTP calls (the Docs write quota / minute / user).

    This guards against regressions that re-introduce per-paragraph or
    per-cell flushes.
    """
    league, rosters = _make_league_fixture()
    roster_map = {r.roster_id: r for r in rosters}
    sim = _make_sim_result(rosters)

    report = GoogleDocsReport(league_name=league.name)
    docs_service, batch_calls, _ = _build_mock_docs_service()
    report._docs_service = docs_service

    report.write_tab_projected_standings("doc1", sim, roster_map)
    report.write_tab_team_reports(
        "doc1",
        rosters,
        sim,
        dynasty_outlooks={},
        player_projections={},
        player_names={},
        player_ages={},
    )
    report.write_tab_matchup_forecasts("doc1", sim, roster_map)

    # Hard ceiling: 60 batchUpdate calls would exceed quota. We expect to
    # come in well below that — roughly 2 calls per write_tab_ plus 2 per
    # team in the team-reports tab.
    assert report._batch_update_call_count < 60, (
        f"Exceeded quota: {report._batch_update_call_count} batchUpdate calls"
    )
    # Sanity: should be in the rough ballpark we designed for (3 tabs × 2
    # + 1 team-reports preamble × 1 + N teams × 2).
    assert report._batch_update_call_count <= 20, (
        f"Surprisingly many calls ({report._batch_update_call_count}); "
        "buffer pattern may have regressed."
    )


def test_colored_cells_get_black_foreground_text():
    """Contrast guard: any cell that gets a caller-supplied background
    color (e.g., the playoff% green/yellow/red cells) must also
    get an explicit BLACK foreground color applied to its text in the
    populate batch.

    Without this, light backgrounds (yellow, light green) plus an inherited
    light text color (e.g., the white that header rows use) would render
    invisible text.
    """
    league, rosters = _make_league_fixture()
    roster_map = {r.roster_id: r for r in rosters}
    sim = _make_sim_result(rosters)

    report = GoogleDocsReport(league_name=league.name)
    docs_service, batch_calls, _ = _build_mock_docs_service()
    report._docs_service = docs_service

    report.write_tab_projected_standings("doc1", sim, roster_map)

    # Collect every cell-background color request and every text-style
    # request with a BLACK foreground color across all batches.
    bg_color_requests = []
    black_fg_requests = []
    for batch in batch_calls:
        for req in batch:
            if "updateTableCellStyle" in req:
                color = (
                    req["updateTableCellStyle"]["tableCellStyle"]
                    .get("backgroundColor", {})
                    .get("color", {})
                    .get("rgbColor")
                )
                if color and color != {
                    "red": 0.23,
                    "green": 0.40,
                    "blue": 0.65,
                }:
                    # Skip the blue header background — that pairs with
                    # white text, not black.
                    bg_color_requests.append(req)
            if "updateTextStyle" in req:
                fg = (
                    req["updateTextStyle"]["textStyle"]
                    .get("foregroundColor", {})
                    .get("color", {})
                    .get("rgbColor")
                )
                if fg == COLOR_BLACK:
                    black_fg_requests.append(req)

    # Every team in the fixture (2 teams) gets a colored playoff% cell, so
    # there should be at least one colored-background request and at least
    # one matching BLACK foreground request paired with it.
    assert len(bg_color_requests) >= 1, (
        "Expected at least one non-blue colored cell background"
    )
    assert len(black_fg_requests) >= 1, (
        "Expected at least one BLACK foreground request for the text in a "
        "cell with a colored background — without it the text may be "
        "invisible against the light fill."
    )


