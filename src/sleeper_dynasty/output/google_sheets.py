"""Google Sheets output for the trades subcommand.

Generates a shareable Google Sheets workbook with two tabs:
  - Trade Ledger: one row per trade-side (easy filtering/pivoting/sorting)
  - Owner Standings: one row per owner, sorted by Trade Value descending

Uses the Sheets v4 API (spreadsheets.values.update) for data, plus a single
batchUpdate per sheet for header formatting. No rate-limit gymnastics needed
— Google Sheets write quotas are much more generous than Docs (300 writes/min
vs. 60/min), and we issue at most a handful of API calls regardless of league
size.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from sleeper_dynasty.models.trade import FaabAsset, PickAsset, PlayerAsset

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Google API OAuth scopes — Sheets (full r/w) and Drive (only files we create).
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# OAuth credential/token storage — same directories as google_docs.py so the
# user only ever has one token file. If the user previously authenticated with
# the Docs-only scopes, the OAuth flow will re-issue a token with the new
# Sheets scope the first time they run `trades`.
CONFIG_DIR = Path.home() / ".sleeper-dynasty"
CREDENTIALS_PATH = CONFIG_DIR / "google_credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"

# Headers for each sheet tab.
_LEDGER_HEADERS = [
    "Trade Date", "Week", "Season", "League", "Owner",
    "Received", "Gave",
    "Trade Value", "Total Points", "Points Started", "Playoff Points", "Toilet Bowl Points",
    "Trade ID",
]

_STANDINGS_HEADERS = [
    "Owner", "Trades",
    "Trade Value", "Total Points", "Points Started", "Playoff Points", "Toilet Bowl Points",
    "Best Trade", "Worst Trade",
]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ordinal(n: int) -> str:
    """Convert an integer to an ordinal string: 1 -> '1st', 2 -> '2nd', etc."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _render_asset(asset: Any, display_names: dict[str, str]) -> str:
    """Render a single TradeAsset as a plain-text string (no bullet prefix).

    For spreadsheet cells, we join multiple assets with "; " — bullets
    are not idiomatic in cell text. Pick origin user_ids are resolved to
    display names via ``display_names``.

    When a PlayerAsset carries ``via_pick``, the pick origin is shown
    prominently before the resolved player name so it is obvious the
    asset was acquired via a pick, not a direct player swap.
    """
    if isinstance(asset, PlayerAsset):
        if asset.via_pick is not None:
            orig = display_names.get(
                asset.via_pick.original_owner_user_id,
                asset.via_pick.original_owner_user_id,
            )
            round_label = _ordinal(asset.via_pick.round)
            return (
                f"{asset.via_pick.season} {round_label} pick "
                f"(orig: {orig}) → {asset.name or asset.player_id}"
            )
        return asset.name or asset.player_id
    if isinstance(asset, PickAsset):
        owner_name = display_names.get(
            asset.original_owner_user_id, asset.original_owner_user_id
        )
        round_label = _ordinal(asset.round)
        return f"{asset.season} {round_label} pick (orig: {owner_name})"
    if isinstance(asset, FaabAsset):
        return f"${asset.amount} FAAB"
    return "?"


# ---------------------------------------------------------------------------
# GoogleSheetsReport
# ---------------------------------------------------------------------------


class GoogleSheetsReport:
    """Builds and writes a Google Sheets trade report for a Sleeper dynasty league."""

    def __init__(self, league_name: str, season: int | None = None) -> None:
        self.league_name = league_name
        self.season = season
        self.today = date.today()
        self._sheets_service: Any | None = None
        self._drive_service: Any | None = None

    # -- Authentication -------------------------------------------------------

    def authenticate(self) -> None:
        """Run the OAuth 2.0 flow and build Sheets/Drive service clients."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        creds: Credentials | None = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                log.info("Refreshing expired Google OAuth token")
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Google OAuth client credentials not found at "
                        f"{CREDENTIALS_PATH}. Download an OAuth client ID "
                        f"(installed app) from Google Cloud Console and "
                        f"save it there."
                    )
                log.info("Starting Google OAuth installed-app flow")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.write_text(creds.to_json())
            log.info("Saved Google OAuth token to %s", TOKEN_PATH)

        self._sheets_service = build("sheets", "v4", credentials=creds)
        self._drive_service = build("drive", "v3", credentials=creds)

    # -- Spreadsheet lifecycle ------------------------------------------------

    def create_spreadsheet(self) -> str:
        """Create a new Google Sheets workbook with two pre-named tabs.

        Returns:
            The spreadsheet_id of the newly created spreadsheet.
        """
        if self._sheets_service is None:
            raise RuntimeError("authenticate() must be called first")

        title = f"{self.league_name} — Trade History - {self.today.isoformat()}"
        log.info("Creating Google Sheet: %s", title)

        body = {
            "properties": {"title": title},
            "sheets": [
                {"properties": {"title": "Definitions"}},
                {"properties": {"title": "Trade Ledger"}},
                {"properties": {"title": "Owner Standings"}},
            ],
        }
        result = (
            self._sheets_service.spreadsheets()
            .create(body=body)
            .execute()
        )
        spreadsheet_id = result["spreadsheetId"]
        log.info("Created Google Sheet id=%s", spreadsheet_id)
        return spreadsheet_id

    def set_sharing(self, spreadsheet_id: str, private: bool = False) -> None:
        """Set sharing permissions on the spreadsheet."""
        if self._drive_service is None:
            raise RuntimeError("authenticate() must be called first")
        if private:
            log.info("Leaving spreadsheet %s private", spreadsheet_id)
            return
        log.info(
            "Setting spreadsheet %s to 'anyone with link can view'",
            spreadsheet_id,
        )
        self._drive_service.permissions().create(
            fileId=spreadsheet_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

    def get_url(self, spreadsheet_id: str) -> str:
        """Return the human-facing URL for the spreadsheet."""
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    # -- Sheet writers --------------------------------------------------------

    def write_trade_ledger(
        self,
        spreadsheet_id: str,
        resolved_trades: list,
        grades_by_trade_id: dict,
        display_names: dict[str, str],
        league_name_by_id: dict[str, str],
    ) -> None:
        """Write the Trade Ledger tab — one row per trade-side.

        Each row captures the owner's perspective for a single trade: what they
        received, what they gave, and all grading metrics. Multiple rows per
        trade (one per participant) make it easy to filter by owner, season,
        or league in the sheet.

        Args:
            spreadsheet_id: Target spreadsheet.
            resolved_trades: Iterable of ResolvedTrade (newest-first ordering
                from build_trade_history is preserved).
            grades_by_trade_id: trade_id → TradeGrade (may be empty/missing
                for ungraded trades).
            display_names: user_id → human-readable display name.
            league_name_by_id: league_id → league name string.
        """
        log.info("Writing Trade Ledger to spreadsheet %s", spreadsheet_id)

        rows: list[list[str]] = [_LEDGER_HEADERS]

        for rt in resolved_trades:
            grade = grades_by_trade_id.get(rt.trade.transaction_id)
            trade_date = rt.trade.traded_at.strftime("%Y-%m-%d")
            week = str(rt.trade.week)
            season = str(rt.trade.season)
            league_name = league_name_by_id.get(
                rt.trade.league_id, rt.trade.league_id
            )
            trade_id = rt.trade.transaction_id

            for uid, side in rt.sides.items():
                owner = display_names.get(uid, uid)
                received = (
                    "; ".join(
                        _render_asset(a, display_names) for a in side.received
                    )
                    or "—"
                )
                gave = (
                    "; ".join(
                        _render_asset(a, display_names) for a in side.given
                    )
                    or "—"
                )

                if grade is not None:
                    trade_value = f"{grade.snapshot_value_swing.get(uid, 0):+.0f}"
                    total_points = f"{grade.production_total.get(uid, 0):+.1f}"
                    points_started = f"{grade.production_regular.get(uid, 0):+.1f}"
                    playoff_points = (
                        f"{grade.production_playoff.get(uid, 0):+.1f}"
                    )
                    toilet_points = (
                        f"{grade.production_toilet.get(uid, 0):+.1f}"
                    )
                else:
                    trade_value = total_points = points_started = playoff_points = toilet_points = ""

                rows.append([
                    trade_date, week, season, league_name, owner,
                    received, gave,
                    trade_value, total_points, points_started, playoff_points, toilet_points,
                    trade_id,
                ])

        self._write_values(spreadsheet_id, "Trade Ledger!A1", rows)
        self._format_header_row(spreadsheet_id, sheet_title="Trade Ledger")

    def write_owner_standings(
        self,
        spreadsheet_id: str,
        records: dict,
    ) -> None:
        """Write the Owner Standings tab — one row per owner, Net KTC desc.

        Args:
            spreadsheet_id: Target spreadsheet.
            records: dict of user_id → OwnerTradeRecord.
        """
        log.info("Writing Owner Standings to spreadsheet %s", spreadsheet_id)

        sorted_records = sorted(
            records.values(), key=lambda r: r.net_ktc, reverse=True
        )

        rows: list[list[str]] = [_STANDINGS_HEADERS]
        for r in sorted_records:
            rows.append([
                r.display_name,
                str(r.trades),
                f"{r.net_ktc:+.0f}",
                f"{r.production_total:+.1f}",
                f"{r.production_regular:+.1f}",
                f"{r.production_playoff:+.1f}",
                f"{r.production_toilet:+.1f}",
                r.best_trade_id or "—",
                r.worst_trade_id or "—",
            ])

        self._write_values(spreadsheet_id, "Owner Standings!A1", rows)
        self._format_header_row(spreadsheet_id, sheet_title="Owner Standings")

    def write_definitions(self, spreadsheet_id: str) -> None:
        """Write the Definitions tab — a built-in legend for both data tabs."""
        log.info("Writing Definitions to spreadsheet %s", spreadsheet_id)

        rows: list[list[str]] = [
            # Trade Ledger section
            ["TRADE LEDGER COLUMNS", ""],
            ["Column", "Definition"],
            ["Trade Date", "Date the trade was completed in Sleeper."],
            ["Week", "Sleeper week (1-18) the trade was completed in."],
            ["Season", "NFL season the trade was made in."],
            ["League", "Sleeper league name for the season."],
            ["Owner", "This row's participant."],
            [
                "Received",
                'Assets this owner received in the trade. Picks shown as '
                '"<season> round <N> (from <original drafter>)".',
            ],
            ["Gave", "Assets this owner gave up in the trade."],
            [
                "Trade Value",
                "Today's KTC value swing — (sum of values of assets received) "
                "- (sum of values given). Positive = won the trade on current "
                "market value. Uses Superflex KTC values. Unresolved future "
                "picks and FAAB contribute 0.",
            ],
            [
                "Total Points",
                "Net fantasy points swing since the trade. (Points the received "
                "players scored for this team) - (points the given players scored "
                "anywhere they ended up, post-trade). Counts ALL points scored — "
                "bench or starter — since the trade.",
            ],
            [
                "Points Started",
                "Same as Total Points, but counting points only in weeks the player "
                "was in the starting lineup. Bench weeks contribute 0.",
            ],
            [
                "Playoff Points",
                "Same as Points Started, but counting only playoff weeks (week >= "
                "the league's playoff start). Highest-leverage scoring.",
            ],
            [
                "Trade ID",
                "Sleeper transaction ID. All sides of the same trade share this ID "
                "— use it to filter the sheet to a single trade.",
            ],
            # Blank separator
            ["", ""],
            # Owner Standings section
            ["OWNER STANDINGS COLUMNS", ""],
            ["Column", "Definition"],
            ["Owner", "League member."],
            [
                "Trades",
                "Total number of trades this owner participated in across the "
                "entire dynasty chain.",
            ],
            [
                "Trade Value",
                "Sum of Trade Value swings across all this owner's trades. "
                "Positive = net winner on today's market value.",
            ],
            [
                "Total Points",
                "Sum of Total Points swings across all trades. Positive = "
                "received players have outscored given players in aggregate post-trade.",
            ],
            [
                "Points Started",
                "Sum of Points Started swings across all trades — production counted "
                "only in weeks the player was in the starting lineup.",
            ],
            [
                "Playoff Points",
                "Sum of Playoff Points swings across all trades — started production "
                "counted only in playoff weeks.",
            ],
            [
                "Best Trade",
                "Sleeper transaction ID of this owner's single best trade by "
                "Trade Value swing.",
            ],
            [
                "Worst Trade",
                "Sleeper transaction ID of this owner's single worst trade by "
                "Trade Value swing.",
            ],
            # Blank separator
            ["", ""],
            # Notes section
            ["NOTES", ""],
            ["KTC values reflect today's snapshot; they evolve as the market moves.", ""],
            [
                "Points figures only count games played after the "
                "trade date, in this league chain only.",
                "",
            ],
            [
                "FAAB included in trades is recorded but not valued "
                "(counts as 0 in Trade Value).",
                "",
            ],
            [
                "KTC matches by normalized name; retired players or name-mismatch "
                "cases contribute 0 to Trade Value.",
                "",
            ],
        ]

        self._write_values(spreadsheet_id, "Definitions!A1", rows)

        # Determine section-header and sub-header row indices (0-based).
        # Row 0:  "TRADE LEDGER COLUMNS"   → bold
        # Row 1:  "Column" / "Definition"  → bold
        # Row 18: "OWNER STANDINGS COLUMNS" → bold
        # Row 19: "Column" / "Definition"  → bold
        # Row 30: "NOTES"                  → bold
        bold_row_indices = [0, 1, 18, 19, 30]

        sheet_id = self._sheet_id_by_title(spreadsheet_id, "Definitions")
        if sheet_id is None:
            return

        bold_requests = []
        for row_idx in bold_row_indices:
            bold_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_idx,
                            "endRowIndex": row_idx + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.bold",
                    }
                }
            )

        requests = [
            *bold_requests,
            # Wrap text in column B so long definitions are readable.
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startColumnIndex": 1,
                        "endColumnIndex": 2,
                    },
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                    "fields": "userEnteredFormat.wrapStrategy",
                },
            },
            # Auto-resize both columns to fit content.
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 2,
                    },
                },
            },
        ]

        try:
            self._sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Formatting failed for 'Definitions' (%s); continuing", exc
            )

    # -- Internal API plumbing ------------------------------------------------

    def _sheet_id_by_title(
        self, spreadsheet_id: str, sheet_title: str
    ) -> int | None:
        """Return the numeric sheetId for a sheet given its title, or None."""
        if self._sheets_service is None:
            raise RuntimeError("authenticate() must be called first")
        try:
            meta = (
                self._sheets_service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id)
                .execute()
            )
            for sheet in meta.get("sheets", []):
                if sheet.get("properties", {}).get("title") == sheet_title:
                    return sheet["properties"]["sheetId"]
            log.warning(
                "Could not find sheetId for '%s'; skipping format", sheet_title
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Failed to fetch sheet metadata for '%s' (%s); skipping",
                sheet_title,
                exc,
            )
        return None

    def _write_values(
        self, spreadsheet_id: str, range_: str, rows: list[list[str]]
    ) -> None:
        """Write a 2-D array of values to a sheet range (USER_ENTERED)."""
        if self._sheets_service is None:
            raise RuntimeError("authenticate() must be called first")
        self._sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body={"values": rows},
        ).execute()

    def _format_header_row(
        self, spreadsheet_id: str, sheet_title: str
    ) -> None:
        """Bold and freeze the header row of a named sheet.

        Retrieves the sheetId by title from the spreadsheet metadata, then
        submits a single batchUpdate with bold + freeze requests. Failures
        are logged but do not crash the run — formatting is cosmetic.
        """
        if self._sheets_service is None:
            raise RuntimeError("authenticate() must be called first")

        sheet_id = self._sheet_id_by_title(spreadsheet_id, sheet_title)
        if sheet_id is None:
            return

        requests = [
            # Bold header row (row index 0, all columns).
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {
                                "red": 0.23,
                                "green": 0.40,
                                "blue": 0.65,
                            },
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)",
                }
            },
            # Freeze header row.
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]

        try:
            self._sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Header formatting failed for '%s' (%s); continuing",
                sheet_title,
                exc,
            )
