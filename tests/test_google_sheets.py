"""Unit tests for the Google Sheets trade report output module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from sleeper_dynasty.models.trade import (
    FaabAsset,
    OwnerTradeRecord,
    PickAsset,
    PlayerAsset,
    ResolvedTrade,
    Trade,
    TradeSide,
)
from sleeper_dynasty.output.google_sheets import GoogleSheetsReport, _render_asset


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_report():
    """Return a GoogleSheetsReport with services pre-mocked (no auth needed)."""
    report = GoogleSheetsReport(league_name="Dynasty Bros", season=2024)
    report._sheets_service = MagicMock()
    report._sheets_service.spreadsheets.return_value.create.return_value.execute.return_value = {
        "spreadsheetId": "fake-id",
        "sheets": [
            {"properties": {"sheetId": 0, "title": "Trade Ledger"}},
            {"properties": {"sheetId": 1, "title": "Owner Standings"}},
        ],
    }
    report._sheets_service.spreadsheets.return_value.values.return_value.update.return_value.execute.return_value = {}
    report._sheets_service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
    report._drive_service = MagicMock()
    return report


def _make_trade(
    transaction_id: str,
    num_sides: int = 2,
    season: int = 2024,
    week: int = 2,
    league_id: str = "L1",
) -> ResolvedTrade:
    """Build a minimal ResolvedTrade with PlayerAsset placeholders."""
    sides = {}
    for i in range(num_sides):
        uid = f"u{i + 1}"
        sides[uid] = TradeSide(
            user_id=uid,
            received=[PlayerAsset(player_id=f"p_recv_{i}", name=f"Player Recv {i}")],
            given=[PlayerAsset(player_id=f"p_gave_{i}", name=f"Player Gave {i}")],
        )
    trade = Trade(
        transaction_id=transaction_id,
        league_id=league_id,
        season=season,
        week=week,
        traded_at=datetime(season, 9, 12, tzinfo=timezone.utc),
        sides=sides,
    )
    return ResolvedTrade(trade=trade, sides=sides)


# ---------------------------------------------------------------------------
# _render_asset
# ---------------------------------------------------------------------------


def test_render_asset_player():
    asset = PlayerAsset(player_id="p1", name="Bijan Robinson")
    assert _render_asset(asset, {}) == "Bijan Robinson"


def test_render_asset_player_fallback_to_id():
    asset = PlayerAsset(player_id="p_unknown", name="")
    assert _render_asset(asset, {}) == "p_unknown"


def test_render_asset_pick_with_display_name():
    asset = PickAsset(season=2025, round=2, original_owner_user_id="u_alice")
    display_names = {"u_alice": "Alice"}
    result = _render_asset(asset, display_names)
    assert result == "2025 2nd pick (orig: Alice)"


def test_render_asset_pick_fallback_to_user_id():
    asset = PickAsset(season=2025, round=1, original_owner_user_id="u_unknown")
    result = _render_asset(asset, {})
    assert result == "2025 1st pick (orig: u_unknown)"


def test_render_asset_faab():
    asset = FaabAsset(amount=50)
    assert _render_asset(asset, {}) == "$50 FAAB"


# ---------------------------------------------------------------------------
# create_spreadsheet
# ---------------------------------------------------------------------------


def test_create_spreadsheet_creates_with_two_sheets():
    """create_spreadsheet must pass 'Definitions', 'Trade Ledger', and
    'Owner Standings' sheet names in the creation body, with Definitions first."""
    report = _make_report()
    spreadsheet_id = report.create_spreadsheet()

    assert spreadsheet_id == "fake-id"

    # Check what was actually sent to the API.
    call_args = (
        report._sheets_service.spreadsheets.return_value.create.call_args
    )
    body = call_args.kwargs.get("body") or call_args.args[0]
    sheet_titles = [
        s["properties"]["title"] for s in body.get("sheets", [])
    ]
    assert len(sheet_titles) == 3, f"Expected 3 sheets, got {len(sheet_titles)}: {sheet_titles}"
    assert sheet_titles[0] == "Definitions", f"First sheet must be 'Definitions', got {sheet_titles[0]!r}"
    assert "Trade Ledger" in sheet_titles
    assert "Owner Standings" in sheet_titles


def test_write_definitions_emits_both_section_headers():
    """write_definitions must produce rows for all Trade Ledger and Owner
    Standings columns, both section headers, and a NOTES section."""
    report = GoogleSheetsReport(league_name="X", season=2026)
    captured: dict = {"rows": None}

    mock_service = MagicMock()

    def _capture_update(**kwargs):
        captured["rows"] = kwargs["body"]["values"]
        m = MagicMock()
        m.execute.return_value = {}
        return m

    mock_service.spreadsheets.return_value.values.return_value.update.side_effect = (
        lambda **kw: _capture_update(**kw)
    )
    mock_service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
    mock_service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [
            {"properties": {"sheetId": 100, "title": "Definitions"}},
            {"properties": {"sheetId": 101, "title": "Trade Ledger"}},
            {"properties": {"sheetId": 102, "title": "Owner Standings"}},
        ]
    }

    report._sheets_service = mock_service
    report.write_definitions("fake_id")

    rows = captured["rows"]
    assert rows is not None, "write_definitions did not call values().update()"

    # First row is the Trade Ledger section header.
    assert rows[0][0] == "TRADE LEDGER COLUMNS", (
        f"Expected 'TRADE LEDGER COLUMNS' in rows[0][0], got {rows[0][0]!r}"
    )
    # Sub-header immediately after.
    assert rows[1] == ["Column", "Definition"], (
        f"Expected sub-header ['Column', 'Definition'] at rows[1], got {rows[1]!r}"
    )

    flat_col_a = [r[0] for r in rows]

    # Owner Standings section is also present.
    assert "OWNER STANDINGS COLUMNS" in flat_col_a, (
        "Missing 'OWNER STANDINGS COLUMNS' section header"
    )
    # Notes section is present.
    assert "NOTES" in flat_col_a, "Missing 'NOTES' section header"

    # Every Trade Ledger column appears with a non-empty definition.
    for col in (
        "Trade Date", "Week", "Season", "League", "Owner",
        "Received", "Gave", "Trade Value", "Total Points",
        "Points Started", "Playoff Points", "Trade ID",
    ):
        matching = [r for r in rows if r[0] == col]
        assert matching, f"Missing definition row for Trade Ledger column '{col}'"
        assert matching[0][1], f"Empty definition for Trade Ledger column '{col}'"

    # Every Owner Standings column appears with a non-empty definition.
    for col in (
        "Trades", "Trade Value", "Total Points",
        "Points Started", "Playoff Points", "Best Trade", "Worst Trade",
    ):
        matching = [r for r in rows if r[0] == col]
        assert matching, f"Missing definition row for Owner Standings column '{col}'"
        assert matching[0][1], f"Empty definition for Owner Standings column '{col}'"


# ---------------------------------------------------------------------------
# write_trade_ledger — row count and structure
# ---------------------------------------------------------------------------


def test_write_trade_ledger_emits_one_row_per_side():
    """One 2-team trade + one 3-team trade → header + 2 + 3 = 6 rows total."""
    report = _make_report()

    rt_two = _make_trade("tx_a", num_sides=2)
    rt_three = _make_trade("tx_b", num_sides=3)

    captured_values = []

    def spy_update(**kwargs):
        body = kwargs.get("body") or {}
        values = body.get("values", [])
        captured_values.extend(values)
        m = MagicMock()
        m.execute.return_value = {}
        return m

    report._sheets_service.spreadsheets.return_value.values.return_value.update.side_effect = (
        lambda **kw: spy_update(**kw)
    )

    report.write_trade_ledger(
        spreadsheet_id="fake-id",
        resolved_trades=[rt_two, rt_three],
        grades_by_trade_id={},
        display_names={"u1": "Alice", "u2": "Bob", "u3": "Carol"},
        league_name_by_id={"L1": "Dynasty Bros"},
    )

    # 1 header + 2 sides (tx_a) + 3 sides (tx_b) = 6 rows.
    assert len(captured_values) == 6, (
        f"Expected 6 rows (1 header + 2 + 3), got {len(captured_values)}"
    )
    # Header row first.
    header = captured_values[0]
    assert "Owner" in header
    assert "Trade Date" in header
    assert "Received" in header
    assert "Gave" in header


def test_write_trade_ledger_renders_player_names_and_pick_origin():
    """Received cell shows player name; pick origin shows display name not uid."""
    report = _make_report()

    pick = PickAsset(season=2025, round=2, original_owner_user_id="u_alice")
    player = PlayerAsset(player_id="p_bijan", name="Bijan Robinson")

    alice_side = TradeSide(user_id="u_alice", received=[player, pick], given=[])
    bob_side = TradeSide(user_id="u_bob", received=[], given=[player, pick])

    trade = Trade(
        transaction_id="tx_render",
        league_id="L1",
        season=2024,
        week=3,
        traded_at=datetime(2024, 10, 1, tzinfo=timezone.utc),
        sides={"u_alice": alice_side, "u_bob": bob_side},
    )
    rt = ResolvedTrade(trade=trade, sides={"u_alice": alice_side, "u_bob": bob_side})

    captured_rows: list[list] = []

    def spy_update(**kwargs):
        body = kwargs.get("body") or {}
        captured_rows.extend(body.get("values", []))
        m = MagicMock()
        m.execute.return_value = {}
        return m

    report._sheets_service.spreadsheets.return_value.values.return_value.update.side_effect = (
        lambda **kw: spy_update(**kw)
    )

    report.write_trade_ledger(
        spreadsheet_id="fake-id",
        resolved_trades=[rt],
        grades_by_trade_id={},
        display_names={"u_alice": "Alice", "u_bob": "Bob"},
        league_name_by_id={"L1": "Dynasty Bros"},
    )

    # Find Alice's row.
    headers = captured_rows[0]
    owner_col = headers.index("Owner")
    received_col = headers.index("Received")

    alice_row = next(
        row for row in captured_rows[1:] if row[owner_col] == "Alice"
    )
    received_cell = alice_row[received_col]
    assert "Bijan Robinson" in received_cell, (
        f"Expected 'Bijan Robinson' in Received cell, got: {received_cell!r}"
    )
    assert "2025 2nd pick (orig: Alice)" in received_cell, (
        f"Expected '2025 2nd pick (orig: Alice)' in Received cell, got: {received_cell!r}"
    )


# ---------------------------------------------------------------------------
# write_owner_standings — sort order
# ---------------------------------------------------------------------------


def test_write_owner_standings_sorts_by_net_ktc_desc():
    """Owner standings rows are sorted Net KTC descending."""
    report = _make_report()

    records = {
        "u_low": OwnerTradeRecord(
            user_id="u_low",
            display_name="Loser",
            trades=5,
            net_ktc=-500.0,
            production_total=-100.0,
            production_regular=-80.0,
            production_playoff=-20.0,
            production_toilet=-5.0,
        ),
        "u_high": OwnerTradeRecord(
            user_id="u_high",
            display_name="Winner",
            trades=10,
            net_ktc=2000.0,
            production_total=350.0,
            production_regular=300.0,
            production_playoff=90.0,
            production_toilet=15.0,
        ),
    }

    captured_rows: list[list] = []

    def spy_update(**kwargs):
        body = kwargs.get("body") or {}
        captured_rows.extend(body.get("values", []))
        m = MagicMock()
        m.execute.return_value = {}
        return m

    report._sheets_service.spreadsheets.return_value.values.return_value.update.side_effect = (
        lambda **kw: spy_update(**kw)
    )

    report.write_owner_standings(spreadsheet_id="fake-id", records=records)

    # Header + 2 data rows.
    assert len(captured_rows) == 3, f"Expected 3 rows, got {len(captured_rows)}"

    headers = captured_rows[0]
    owner_col = headers.index("Owner")

    # Winner (net_ktc=2000) before Loser (net_ktc=-500).
    assert captured_rows[1][owner_col] == "Winner", (
        f"First data row should be 'Winner', got {captured_rows[1][owner_col]!r}"
    )
    assert captured_rows[2][owner_col] == "Loser", (
        f"Second data row should be 'Loser', got {captured_rows[2][owner_col]!r}"
    )


# ---------------------------------------------------------------------------
# _render_asset — resolved pick (via_pick) and ordinal helpers
# ---------------------------------------------------------------------------


def test_render_asset_resolved_pick_shows_pick_origin():
    via = PickAsset(season=2024, round=1, original_owner_user_id="u_tom")
    asset = PlayerAsset(player_id="p_mhj", name="Marvin Harrison Jr.", via_pick=via)
    rendered = _render_asset(asset, display_names={"u_tom": "Tom"})
    assert "Marvin Harrison Jr." in rendered
    assert "2024" in rendered
    assert "1st" in rendered
    assert "Tom" in rendered
    # Pick info must appear BEFORE the player name.
    assert rendered.index("2024") < rendered.index("Marvin")


def test_render_asset_unresolved_pick_uses_ordinal_round():
    asset = PickAsset(season=2025, round=2, original_owner_user_id="u_jim")
    rendered = _render_asset(asset, display_names={"u_jim": "Jim"})
    assert "2nd" in rendered
    assert "Jim" in rendered


def test_render_asset_plain_player_no_pick_info():
    asset = PlayerAsset(player_id="p_bijan", name="Bijan Robinson")
    rendered = _render_asset(asset, display_names={})
    assert rendered == "Bijan Robinson"
