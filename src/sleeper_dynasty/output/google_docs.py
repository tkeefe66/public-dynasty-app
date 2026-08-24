"""Google Docs output for Sleeper dynasty league reports.

Generates a polished, shareable Google Doc containing three major sections:
  1. Projected Final Standings
  2. Team Reports (one sub-section per team)
  3. Weekly Matchup Forecasts

The document uses real Google Docs tables, heading styles, colors, page
breaks between sections, and bold text for emphasis. Because the public
``docs.v1`` API does not expose ``InsertDocumentTab`` for arbitrary client
use, we structure the document with Heading 1 titles and explicit
``insertPageBreak`` requests between sections. Google Docs auto-generates
a document outline from the headings which gives readers tab-like
navigation in the side panel.

Implementation pattern (chunked structural insert)
--------------------------------------------------
Google Docs API enforces a quota of 60 write requests per minute per user
where each ``batchUpdate`` HTTP call counts as one write — regardless of
how many sub-requests are packed inside it. To stay safely under that
quota for a 12-team league, we group work into **section flushes**:

  STRUCTURAL CHUNKING — Section writers buffer an ordered list of
            structural items (paragraphs, page breaks, blank lines,
            tables). The flush partitions that list into **chunks**
            where each chunk is a maximal run of non-table items
            optionally terminated by a single ``insertTable``. Each
            chunk is submitted as ONE ``batchUpdate``. Crucially, NO
            ``insertText`` request in any batch ever targets an index
            that comes AFTER a previously-inserted table in the SAME
            batch. This eliminates the fragile dependency on the
            empty-table footprint formula to predict where text after
            a table will land — the previous implementation hit
            "insertion index must be inside the bounds of an existing
            paragraph" errors when that formula drifted from the API's
            actual table footprint.

  BETWEEN CHUNKS — After each chunk that ends in a table (except the
            last), one ``documents.get()`` learns the real new document
            end position; the next chunk's cursor starts there. This
            replaces formula-based offset prediction with ground truth.

  POPULATE PHASE — After all structural chunks are submitted, one
            ``documents.get()`` walks ``body.content`` via
            ``_walk_tables`` to find each table's actual ``startIndex``
            and the actual ``startIndex`` of the first paragraph inside
            every cell. Then one ``batchUpdate`` populates every cell
            across every table in the section, applies header-row
            bold-white text, and applies any caller-supplied cell
            background colors. Cell inserts are emitted in REVERSE
            document order so each insert does not shift the indices
            of later inserts.

Per section the write cost is therefore ``T + 1`` batches plus
``T`` GETs, where ``T`` is the number of tables in the section. The
module wraps every API call in ``_call_with_retry`` which retries
``HttpError 429`` with exponential backoff so transient bursts past
the 60/min limit recover gracefully.

The whole module is conservative about API errors: cell-population
failures log a warning but do not crash the run, so the doc always
exists with some content.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from sleeper_dynasty.engine.dynasty import DynastyOutlook
    from sleeper_dynasty.engine.simulator import SimulationResult
    from sleeper_dynasty.models.league import Roster

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Google API OAuth scopes — Docs (full doc r/w) and Drive (only files we create).
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]

# Where we store OAuth credentials and tokens on disk.
CONFIG_DIR = Path.home() / ".sleeper-dynasty"
CREDENTIALS_PATH = CONFIG_DIR / "google_credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"

# Thresholds for the outlook label shown in the per-team report.
_CONTENDER_PLAYOFF_PCT = 60.0
_BUBBLE_PLAYOFF_PCT = 30.0

# Cell background colors (Google Docs API uses 0.0-1.0 RGB floats).
COLOR_GREEN = {"red": 0.70, "green": 0.95, "blue": 0.70}
COLOR_YELLOW = {"red": 1.00, "green": 0.95, "blue": 0.60}
COLOR_RED = {"red": 1.00, "green": 0.70, "blue": 0.70}
COLOR_HEADER_BLUE = {"red": 0.23, "green": 0.40, "blue": 0.65}
COLOR_WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
# Slightly off-black (Google Docs default-text-color shade) used to ensure
# readable text on any caller-supplied colored cell background.
COLOR_BLACK = {"red": 0.1, "green": 0.1, "blue": 0.1}


# ---------------------------------------------------------------------------
# Request builders (pure functions; unit-tested)
# ---------------------------------------------------------------------------


def build_heading_request(text: str, index: int) -> dict[str, Any]:
    """Build an ``insertText`` request for a heading.

    The returned request inserts the text; styling it as a heading requires
    a follow-up ``updateParagraphStyle`` request on the inserted range.
    """
    return {
        "insertText": {
            "text": f"{text}\n",
            "location": {"index": index},
        }
    }


def build_text_request(text: str, index: int) -> dict[str, Any]:
    """Build an ``insertText`` request for a single line of body text."""
    return {
        "insertText": {
            "text": f"{text}\n",
            "location": {"index": index},
        }
    }


def build_table_request(rows: int, columns: int, index: int) -> dict[str, Any]:
    """Build an ``insertTable`` request.

    Args:
        rows: Total number of rows (including header).
        columns: Number of columns.
        index: Document insert location.
    """
    return {
        "insertTable": {
            "rows": rows,
            "columns": columns,
            "location": {"index": index},
        }
    }


def build_page_break_request(index: int) -> dict[str, Any]:
    """Build an ``insertPageBreak`` request."""
    return {"insertPageBreak": {"location": {"index": index}}}


def build_paragraph_style_request(
    start: int, end: int, named_style: str
) -> dict[str, Any]:
    """Build an ``updateParagraphStyle`` request for a range."""
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": named_style},
            "fields": "namedStyleType",
        }
    }


def build_text_style_request(
    start: int,
    end: int,
    *,
    bold: bool | None = None,
    font_size_pt: float | None = None,
    foreground_color: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build an ``updateTextStyle`` request for a range.

    Only sets the fields explicitly passed; ``fields`` mask is built
    dynamically so unspecified properties are left untouched.
    """
    text_style: dict[str, Any] = {}
    fields: list[str] = []
    if bold is not None:
        text_style["bold"] = bold
        fields.append("bold")
    if font_size_pt is not None:
        text_style["fontSize"] = {"magnitude": font_size_pt, "unit": "PT"}
        fields.append("fontSize")
    if foreground_color is not None:
        text_style["foregroundColor"] = {
            "color": {"rgbColor": foreground_color}
        }
        fields.append("foregroundColor")
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": text_style,
            "fields": ",".join(fields),
        }
    }


def build_cell_background_request(
    table_start_index: int,
    row: int,
    column: int,
    color: dict[str, float],
) -> dict[str, Any]:
    """Build an ``updateTableCellStyle`` request that colors a single cell."""
    return {
        "updateTableCellStyle": {
            "tableCellStyle": {
                "backgroundColor": {"color": {"rgbColor": color}}
            },
            "fields": "backgroundColor",
            "tableRange": {
                "tableCellLocation": {
                    "tableStartLocation": {"index": table_start_index},
                    "rowIndex": row,
                    "columnIndex": column,
                },
                "rowSpan": 1,
                "columnSpan": 1,
            },
        }
    }


def build_header_row_bold_request(
    table_start_index: int, columns: int
) -> dict[str, Any]:
    """Build an ``updateTextStyle`` request scoped to a table's header row.

    We use ``tableRange`` semantics via ``updateTableCellStyle`` for cell
    backgrounds, but bolding the header row is best done by targeting a
    range over the header row's content. That requires knowing each cell's
    content range, which we'll do post-GET. This helper is kept for
    documentation/back-compat: see ``_style_table_header`` for the real flow.
    """
    return build_cell_background_request(
        table_start_index, 0, columns - 1, COLOR_HEADER_BLUE
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outlook_label(playoff_pct: float) -> str:
    """Classify a team's season outlook by playoff probability."""
    if playoff_pct >= _CONTENDER_PLAYOFF_PCT:
        return "Contender"
    if playoff_pct >= _BUBBLE_PLAYOFF_PCT:
        return "Bubble"
    return "Rebuilding"


def _playoff_color(playoff_pct: float) -> dict[str, float]:
    """Cell background color for a playoff-probability cell."""
    if playoff_pct >= 70.0:
        return COLOR_GREEN
    if playoff_pct >= 30.0:
        return COLOR_YELLOW
    return COLOR_RED


# ---------------------------------------------------------------------------
# Retry helper (defensive against 429 quota errors)
# ---------------------------------------------------------------------------


# Empty-table footprint per Google Docs API: 1 marker for the table itself,
# plus per row 1 row marker + 2 per cell (cell wrapper + empty paragraph
# newline). The trailing newline that the doc already had at the insertion
# point sits AFTER the table after the insert completes — so to compute the
# next safe insertion index after inserting a table at I, use
# ``I + _empty_table_footprint(R, C) + 1``.
def _empty_table_footprint(rows: int, cols: int) -> int:
    return 1 + rows * (1 + 2 * cols)


# Retry parameters for HTTP 429 (Quota exceeded). Each batchUpdate counts
# as one write; restructuring keeps us well under 60/min normally, but if
# the user re-runs frequently we may transiently hit the limit.
_RETRY_MAX_ATTEMPTS = 5
_RETRY_MAX_BACKOFF_SEC = 60.0


def _call_with_retry(
    operation: Callable[[], Any],
    *,
    context: str,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Invoke ``operation()`` retrying HTTP 429 with exponential backoff.

    Backoff schedule (seconds): 1, 2, 4, 8, 16, capped at 60.
    Other ``HttpError`` statuses and unrelated exceptions are re-raised
    immediately. After ``_RETRY_MAX_ATTEMPTS`` consecutive 429s the final
    error is re-raised.
    """
    from googleapiclient.errors import HttpError  # local import — only needed at runtime

    last_err: Exception | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return operation()
        except HttpError as err:
            status = getattr(getattr(err, "resp", None), "status", None)
            if status != 429:
                raise
            last_err = err
            if attempt == _RETRY_MAX_ATTEMPTS - 1:
                break
            wait = min(2**attempt, _RETRY_MAX_BACKOFF_SEC)
            logger.warning(
                "Google Docs 429 quota in %s (attempt %d/%d); sleeping %.1fs",
                context,
                attempt + 1,
                _RETRY_MAX_ATTEMPTS,
                wait,
            )
            sleep(wait)
    assert last_err is not None
    raise last_err


# ---------------------------------------------------------------------------
# GoogleDocsReport
# ---------------------------------------------------------------------------


class _PendingTable:
    """Records a table queued for population in the current section flush.

    Combined with the post-flush GET, we can locate the table's actual
    structure and discover each cell's content-paragraph index. The
    ``insert_index`` is informational only — population uses the GET-
    discovered ``startIndex`` rather than this value.
    """

    __slots__ = ("insert_index", "headers", "rows", "cell_backgrounds")

    def __init__(
        self,
        insert_index: int,
        headers: list[str],
        rows: list[list[str]],
        cell_backgrounds: dict[tuple[int, int], dict[str, float]] | None,
    ) -> None:
        self.insert_index = insert_index
        self.headers = headers
        self.rows = rows
        self.cell_backgrounds = cell_backgrounds or {}


# Each buffered item is one of these kinds. Items are stored as
# ``(kind, payload)`` tuples in ``_pending_items``. The flush walks
# the list to assemble structural batches.
#
#  - ``("paragraph", {"text", "named_style", "bold", "font_size_pt",
#                       "foreground_color"})``
#  - ``("page_break", None)``
#  - ``("blank", None)``
#  - ``("table", _PendingTable)``
_ItemKind = str


class GoogleDocsReport:
    """Builds and writes a Google Docs report for a Sleeper dynasty league."""

    def __init__(self, league_name: str, season: int | None = None) -> None:
        self.league_name = league_name
        self.season = season
        self.title = f"{league_name} - Dynasty Analysis"
        self.today = date.today()
        self._docs_service: Any | None = None
        self._drive_service: Any | None = None

        # Per-section buffers: populated as section writers call _buffer_*
        # methods, then drained by ``_flush_section``. ``_pending_items``
        # is an ordered list of (kind, payload) tuples — see ``_ItemKind``.
        # ``_pending_tables`` lists table items in buffer order for the
        # post-structural populate phase.
        self._pending_items: list[tuple[_ItemKind, Any]] = []
        self._pending_tables: list[_PendingTable] = []
        # Diagnostic: number of batchUpdate HTTP calls submitted so far.
        # Tests use this to verify the call-reduction refactor.
        self._batch_update_call_count: int = 0

        # Proactive rate limiter state — tracks wall-clock timestamps of
        # recent ``batchUpdate`` calls so we can sleep BEFORE issuing a
        # request that would burst past Google's 60 writes/min quota. We
        # set the self-imposed cap slightly under 60 for safety. The retry
        # helper still covers transient network errors and any 429s that
        # slip through (e.g., very first writes of a session with no
        # history yet, or quota changes).
        self._write_timestamps: list[float] = []
        self._WRITES_PER_MINUTE = 55
        self._WINDOW_SECONDS = 60.0

    # -- Authentication ---------------------------------------------------

    def authenticate(self) -> None:
        """Run the OAuth 2.0 flow and build Docs/Drive service clients."""
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
                logger.info("Refreshing expired Google OAuth token")
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise FileNotFoundError(
                        f"Google OAuth client credentials not found at "
                        f"{CREDENTIALS_PATH}. Download an OAuth client ID "
                        f"(installed app) from Google Cloud Console and "
                        f"save it there."
                    )
                logger.info("Starting Google OAuth installed-app flow")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), SCOPES
                )
                creds = flow.run_local_server(port=0)

            TOKEN_PATH.write_text(creds.to_json())
            logger.info("Saved Google OAuth token to %s", TOKEN_PATH)

        self._docs_service = build("docs", "v1", credentials=creds)
        self._drive_service = build("drive", "v3", credentials=creds)

    # -- Document lifecycle ----------------------------------------------

    def create_document(self) -> str:
        """Create a new Google Doc and return its ID."""
        if self._docs_service is None:
            raise RuntimeError("authenticate() must be called first")

        full_title = f"{self.title} - {self.today.isoformat()}"
        logger.info("Creating Google Doc: %s", full_title)
        doc = (
            self._docs_service.documents()
            .create(body={"title": full_title})
            .execute()
        )
        doc_id = doc["documentId"]
        logger.info("Created Google Doc id=%s", doc_id)
        return doc_id

    def set_sharing(self, doc_id: str, private: bool = False) -> None:
        """Set sharing permissions on the doc."""
        if self._drive_service is None:
            raise RuntimeError("authenticate() must be called first")
        if private:
            logger.info("Leaving doc %s private", doc_id)
            return

        logger.info("Setting doc %s to 'anyone with link can view'", doc_id)
        self._drive_service.permissions().create(
            fileId=doc_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

    def get_doc_url(self, doc_id: str) -> str:
        """Return the human-facing URL for a Google Doc."""
        return f"https://docs.google.com/document/d/{doc_id}/edit"

    # -- Low-level API plumbing -------------------------------------------

    def _throttle_before_write(self) -> None:
        """Block until making a write request is safe (under the rate limit).

        Maintains a sliding window of recent write timestamps. If we've
        already hit our self-imposed budget within the window, sleep just
        long enough for the oldest write to fall out of the window (plus
        a small safety margin), then record the new write's timestamp.

        This is proactive — it prevents 429s instead of reacting to them.
        """
        now = time.time()
        cutoff = now - self._WINDOW_SECONDS
        self._write_timestamps = [t for t in self._write_timestamps if t > cutoff]

        if len(self._write_timestamps) >= self._WRITES_PER_MINUTE:
            # We've hit our self-imposed budget; sleep until the oldest
            # write expires.
            oldest = self._write_timestamps[0]
            sleep_for = max(0.0, (oldest + self._WINDOW_SECONDS) - now) + 0.1
            logger.info(
                "Rate limiter: sleeping %.1fs before next write "
                "(already made %d writes in last %ds)",
                sleep_for,
                len(self._write_timestamps),
                int(self._WINDOW_SECONDS),
            )
            time.sleep(sleep_for)
            now = time.time()
            cutoff = now - self._WINDOW_SECONDS
            self._write_timestamps = [
                t for t in self._write_timestamps if t > cutoff
            ]

        self._write_timestamps.append(now)

    def _batch_update(
        self, doc_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Submit a batchUpdate (with 429 retry), returning the API response."""
        if self._docs_service is None:
            raise RuntimeError("authenticate() must be called first")
        if not requests:
            return {}
        self._throttle_before_write()
        self._batch_update_call_count += 1
        return _call_with_retry(
            lambda: (
                self._docs_service.documents()
                .batchUpdate(documentId=doc_id, body={"requests": requests})
                .execute()
            ),
            context=f"batchUpdate ({len(requests)} sub-requests)",
        )

    def _safe_batch_update(
        self, doc_id: str, requests: list[dict[str, Any]], context: str
    ) -> None:
        """Submit a batchUpdate, logging (not raising) any failure.

        Used for styling/cell-content passes where we'd rather the doc
        survive with degraded formatting than crash mid-run.
        """
        try:
            self._batch_update(doc_id, requests)
        except Exception as exc:  # noqa: BLE001 - we want broad robustness
            logger.warning(
                "batchUpdate failed in %s (continuing): %s", context, exc
            )

    def _get_doc(self, doc_id: str) -> dict[str, Any]:
        """Fetch the current document state (with 429 retry)."""
        if self._docs_service is None:
            raise RuntimeError("authenticate() must be called first")
        return _call_with_retry(
            lambda: self._docs_service.documents().get(documentId=doc_id).execute(),
            context="documents.get",
        )

    def _get_end_index(self, doc_id: str) -> int:
        """Return the current end index of the doc body (where to insert next).

        Google Docs returns ``endIndex`` *past* the final newline; we
        subtract 1 so callers can insert before it.
        """
        doc = self._get_doc(doc_id)
        body = doc.get("body", {})
        content = body.get("content", [])
        if not content:
            return 1
        end_index = content[-1].get("endIndex", 1)
        return max(1, end_index - 1)

    # -- Section buffering primitives -------------------------------------
    #
    # The section writers call these to QUEUE structural items; nothing is
    # sent to the API until ``_flush_section`` runs. The primitives do NOT
    # compute document indices — they merely append to ``_pending_items``.
    # The flush partitions the buffered list into per-table chunks so no
    # batch ever contains a text insert whose index depends on a previous
    # ``insertTable`` in the same batch.

    def _begin_section(self, doc_id: str) -> None:  # noqa: ARG002 - kept for API symmetry
        """Reset the per-section buffer.

        The doc-id argument is retained for API symmetry; the new chunked
        flush model discovers the document end via GET right before each
        chunk that needs it, so no initial GET is required.
        """
        self._pending_items = []
        self._pending_tables = []

    def _buffer_paragraph(
        self,
        text: str,
        *,
        named_style: str = "NORMAL_TEXT",
        bold: bool = False,
        font_size_pt: float | None = None,
        foreground_color: dict[str, float] | None = None,
    ) -> None:
        """Queue a styled paragraph onto the current section buffer."""
        self._pending_items.append(
            (
                "paragraph",
                {
                    "text": text,
                    "named_style": named_style,
                    "bold": bold,
                    "font_size_pt": font_size_pt,
                    "foreground_color": foreground_color,
                },
            )
        )

    def _buffer_page_break(self) -> None:
        """Queue a page break."""
        self._pending_items.append(("page_break", None))

    def _buffer_blank_line(self) -> None:
        """Queue a blank paragraph for vertical spacing."""
        self._pending_items.append(("blank", None))

    def _buffer_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        *,
        cell_backgrounds: dict[tuple[int, int], dict[str, float]] | None = None,
    ) -> None:
        """Queue a table insertion and record it for post-flush population."""
        if not headers:
            return
        pt = _PendingTable(
            insert_index=0,  # filled in by flush after the chunk's cursor is known
            headers=list(headers),
            rows=[list(r) for r in rows],
            cell_backgrounds=cell_backgrounds,
        )
        self._pending_items.append(("table", pt))
        self._pending_tables.append(pt)

    # -- Chunk assembly helpers -------------------------------------------

    def _build_chunk_requests(
        self, items: list[tuple[_ItemKind, Any]], start_cursor: int
    ) -> list[dict[str, Any]]:
        """Build the batchUpdate sub-requests for one structural chunk.

        ``items`` is a list of buffered items: zero or more non-table items
        optionally followed by a single ``("table", _PendingTable)`` item.
        The cursor advance is computed locally for text-only items (which
        is reliable — each ``insertText`` advances by ``len(text)`` and
        each ``insertPageBreak`` advances by 1). The terminal table — if
        present — is the LAST request, so no later sub-request in this
        batch needs to predict the table's footprint.
        """
        requests: list[dict[str, Any]] = []
        cursor = start_cursor
        for kind, payload in items:
            if kind == "paragraph":
                text = payload["text"]
                text_with_nl = f"{text}\n"
                start = cursor
                end = start + len(text_with_nl)
                requests.append(
                    {
                        "insertText": {
                            "text": text_with_nl,
                            "location": {"index": start},
                        }
                    }
                )
                requests.append(
                    build_paragraph_style_request(
                        start, end, payload["named_style"]
                    )
                )
                style_kwargs: dict[str, Any] = {}
                if payload["bold"]:
                    style_kwargs["bold"] = True
                if payload["font_size_pt"] is not None:
                    style_kwargs["font_size_pt"] = payload["font_size_pt"]
                if payload["foreground_color"] is not None:
                    style_kwargs["foreground_color"] = payload["foreground_color"]
                if style_kwargs:
                    requests.append(
                        build_text_style_request(start, end - 1, **style_kwargs)
                    )
                cursor = end
            elif kind == "page_break":
                requests.append(build_page_break_request(cursor))
                cursor += 1
            elif kind == "blank":
                requests.append(
                    {
                        "insertText": {
                            "text": "\n",
                            "location": {"index": cursor},
                        }
                    }
                )
                cursor += 1
            elif kind == "table":
                pt: _PendingTable = payload
                total_rows = len(pt.rows) + 1
                cols = len(pt.headers)
                pt.insert_index = cursor
                requests.append(
                    build_table_request(total_rows, cols, cursor)
                )
                # Table MUST be the last item in the chunk; we therefore do
                # not need to advance ``cursor`` beyond it.
            else:
                raise ValueError(f"Unknown buffered item kind: {kind!r}")
        return requests

    def _flush_section(self, doc_id: str) -> None:
        """Execute the section's chunked structural + populate writes.

        STRUCTURAL — partition ``_pending_items`` into chunks where each
        chunk is a maximal prefix of non-table items optionally terminated
        by exactly one ``insertTable``. Submit each chunk as one
        ``batchUpdate``. Between chunks (except after the last), GET the
        doc to refresh the cursor — this avoids relying on the empty-table
        footprint formula, which has proven fragile against real Google
        Docs structure.

        POPULATE — one ``documents.get()`` finds every table's real
        ``startIndex`` and per-cell first-paragraph index; one
        ``batchUpdate`` writes cell text (REVERSE document order),
        applies header bold-white styling, and applies background colors.
        """
        if not self._pending_items:
            return

        # Partition items into chunks.
        chunks: list[list[tuple[_ItemKind, Any]]] = []
        current: list[tuple[_ItemKind, Any]] = []
        for item in self._pending_items:
            current.append(item)
            if item[0] == "table":
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        # Determine the starting cursor: the current end of the document
        # body before this section's first write. ``_get_end_index``
        # returns the index just before the trailing newline.
        cursor = self._get_end_index(doc_id)

        # Submit each chunk; between table-terminated chunks, GET to
        # discover the new end (which the formula can't reliably predict).
        for chunk_idx, chunk in enumerate(chunks):
            requests = self._build_chunk_requests(chunk, cursor)
            if requests:
                self._batch_update(doc_id, requests)
            # If chunk ended with a table and there are more chunks to
            # come, refresh the cursor from the actual doc state. The
            # final chunk doesn't need a refresh — the populate phase
            # discovers indices via its own GET.
            is_last = chunk_idx == len(chunks) - 1
            ended_with_table = chunk[-1][0] == "table"
            if ended_with_table and not is_last:
                cursor = self._get_end_index(doc_id)

        # Populate phase only runs if we inserted any tables.
        if self._pending_tables:
            self._populate_tables(doc_id)

        self._pending_items = []
        self._pending_tables = []

    def _populate_tables(self, doc_id: str) -> None:
        """Discover each pending table's real layout and fill its cells.

        This is the post-structural pass. It's split out so the structural
        flush remains easy to read.
        """
        doc = self._get_doc(doc_id)
        actual_tables = _walk_tables(doc.get("body", {}).get("content", []))

        n_pending = len(self._pending_tables)
        if len(actual_tables) < n_pending:
            logger.warning(
                "Walked %d tables in doc body but expected at least %d; "
                "some cells will be skipped",
                len(actual_tables),
                n_pending,
            )
        # The N most recent tables in the body correspond to this section.
        section_tables = actual_tables[-n_pending:] if n_pending else []

        populate_requests: list[dict[str, Any]] = []
        # Across ALL tables we batch every cell insertText in REVERSE
        # document order so each insert leaves earlier indices stable.
        all_cell_inserts: list[tuple[int, str]] = []
        header_style_requests: list[dict[str, Any]] = []
        # Black-foreground requests for cells with caller-supplied non-blue
        # backgrounds (e.g. playoff% green/yellow/red). The
        # default text color would otherwise inherit something the reader
        # can't see against a light fill (e.g., a leaked white from header
        # styling). We explicitly set BLACK on every such cell so colored
        # backgrounds always render with readable text.
        colored_cell_text_style_requests: list[dict[str, Any]] = []
        cell_background_requests: list[dict[str, Any]] = []

        for pt, actual_table in zip(self._pending_tables, section_tables):
            table_start = actual_table["startIndex"]
            cols = len(pt.headers)

            cells: list[tuple[int, int, int]] = []
            for r_idx, row_indices in enumerate(actual_table["rows"]):
                for c_idx, p_start in enumerate(row_indices):
                    cells.append((r_idx, c_idx, p_start))

            all_rows = [list(pt.headers)] + [list(r) for r in pt.rows]

            for (r_idx, c_idx), color in pt.cell_backgrounds.items():
                cell_background_requests.append(
                    build_cell_background_request(
                        table_start, r_idx, c_idx, color
                    )
                )
                # Match-up the text styling: any cell with a custom
                # background gets BLACK foreground text. Header cells are
                # handled separately below (blue background + bold white).
                if r_idx == 0:
                    continue
                if r_idx >= len(all_rows):
                    continue
                p_start = next(
                    (
                        p
                        for r, c, p in cells
                        if r == r_idx and c == c_idx
                    ),
                    None,
                )
                if p_start is None:
                    continue
                text = (
                    all_rows[r_idx][c_idx]
                    if c_idx < len(all_rows[r_idx])
                    else ""
                )
                if not text:
                    continue
                colored_cell_text_style_requests.append(
                    build_text_style_request(
                        p_start,
                        p_start + len(text),
                        bold=False,
                        foreground_color=COLOR_BLACK,
                    )
                )

            for c_idx in range(cols):
                cell_background_requests.append(
                    build_cell_background_request(
                        table_start, 0, c_idx, COLOR_HEADER_BLUE
                    )
                )

            for r_idx, c_idx, p_start in cells:
                if r_idx >= len(all_rows):
                    continue
                text = (
                    all_rows[r_idx][c_idx]
                    if c_idx < len(all_rows[r_idx])
                    else ""
                )
                if not text:
                    continue
                all_cell_inserts.append((p_start, text))

            for c_idx in range(cols):
                header_cell = next(
                    (
                        (r, c, p)
                        for r, c, p in cells
                        if r == 0 and c == c_idx
                    ),
                    None,
                )
                if header_cell is None:
                    continue
                _, _, p_start = header_cell
                text = pt.headers[c_idx]
                if not text:
                    continue
                header_style_requests.append(
                    build_text_style_request(
                        p_start,
                        p_start + len(text),
                        bold=True,
                        foreground_color=COLOR_WHITE,
                    )
                )

        populate_requests.extend(cell_background_requests)
        all_cell_inserts.sort(key=lambda t: t[0], reverse=True)
        for p_start, text in all_cell_inserts:
            populate_requests.append(
                {
                    "insertText": {
                        "text": text,
                        "location": {"index": p_start},
                    }
                }
            )
        populate_requests.extend(header_style_requests)
        populate_requests.extend(colored_cell_text_style_requests)

        if populate_requests:
            self._safe_batch_update(
                doc_id, populate_requests, context="table population"
            )

    # -- Tab writers ------------------------------------------------------

    def write_tab_projected_standings(
        self,
        doc_id: str,
        sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> None:
        """Write the Projected Final Standings section.

        This is now the FIRST section of the doc, so it leads with a small
        subtitle (league name, season, generated timestamp) for context.
        Because it is the first section, no preceding page break is needed
        — the title sits at the top of page 1.

        1 table → 1 structural batch (the table is the only/final chunk) +
        1 populate GET + 1 populate batch = 2 batchUpdate calls.
        """
        logger.info("Writing Projected Standings section to doc %s", doc_id)
        self._begin_section(doc_id)

        # Section title.
        self._buffer_paragraph(
            "Projected Final Standings",
            named_style="HEADING_1",
            bold=True,
        )
        # Subtitle line: league name · season · generated timestamp. Single
        # NORMAL_TEXT paragraph, no table, just context for the reader since
        # the old League Overview section that carried this info is gone.
        generated_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        subtitle_parts = [f"League: {self.league_name}"]
        if self.season is not None:
            subtitle_parts.append(f"Season: {self.season}")
        subtitle_parts.append(f"Generated: {generated_ts}")
        self._buffer_paragraph(
            " · ".join(subtitle_parts),
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )
        self._buffer_paragraph(
            "Sorted by Monte Carlo playoff probability. "
            "Green cells = playoff lock (≥70%), yellow = bubble (30–70%), "
            "red = long shot (<30%).",
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )
        self._buffer_blank_line()

        sorted_teams = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.playoff_pct,
            reverse=True,
        )

        headers = ["Rank", "Team", "Proj W-L", "Win Range", "Playoff%", "Champ%"]
        rows: list[list[str]] = []
        cell_bg: dict[tuple[int, int], dict[str, float]] = {}
        playoff_col_idx = headers.index("Playoff%")

        for rank, t in enumerate(sorted_teams, start=1):
            roster = roster_map.get(t.roster_id)
            team_name = roster.owner_name if roster else f"Roster {t.roster_id}"
            proj_record = f"{t.avg_wins:.1f}-{t.avg_losses:.1f}"
            win_range = f"{t.win_low:.0f}–{t.win_high:.0f}"
            rows.append(
                [
                    str(rank),
                    team_name,
                    proj_record,
                    win_range,
                    f"{t.playoff_pct:.1f}%",
                    f"{t.championship_pct:.1f}%",
                ]
            )
            # Row index in the rendered table is rank (1-indexed) because
            # row 0 is the header.
            cell_bg[(rank, playoff_col_idx)] = _playoff_color(t.playoff_pct)

        self._buffer_table(headers, rows, cell_backgrounds=cell_bg)

        self._flush_section(doc_id)

    def write_tab_team_reports(
        self,
        doc_id: str,
        rosters: list[Roster],
        sim_result: SimulationResult,
        dynasty_outlooks: dict[int, DynastyOutlook],
        player_projections: dict[str, tuple[str, float]],
        player_names: dict[str, str],
        player_ages: dict[str, int | None],
    ) -> None:
        """Write per-team report sub-sections.

        Strategy: each team is one section flush, and the section-heading
        preamble is flushed as a separate section. Per-team write count is
        ``T+2`` batchUpdates (one per chunk plus populate). A team report
        contains up to 5 tables, so a 12-team league emits at most
        ``1 + 12 × 7 ≈ 85`` writes for this tab. Spread across the run
        time (and behind the 429-backoff retry helper) this stays within
        the Docs API's 60/min quota.
        """
        logger.info("Writing Team Reports section to doc %s", doc_id)

        # First flush: section header preamble (no tables → 1 API call).
        self._begin_section(doc_id)
        self._buffer_page_break()
        self._buffer_paragraph(
            "Team Reports", named_style="HEADING_1", bold=True
        )
        self._buffer_paragraph(
            "Per-team breakdown of roster, season outlook, draft capital "
            "and draft needs. Teams ordered by projected playoff probability.",
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )
        self._flush_section(doc_id)

        roster_map = {r.roster_id: r for r in rosters}
        sorted_team_results = sorted(
            sim_result.team_results.values(),
            key=lambda t: t.playoff_pct,
            reverse=True,
        )

        for idx, team_result in enumerate(sorted_team_results):
            rid = team_result.roster_id
            roster = roster_map.get(rid)
            if roster is None:
                continue

            # One section per team — 3 API calls.
            self._begin_section(doc_id)

            # Page break between teams (but not before the first one).
            if idx > 0:
                self._buffer_page_break()
            else:
                self._buffer_blank_line()

            self._buffer_single_team_report(
                roster,
                team_result,
                dynasty_outlooks.get(rid),
                player_projections,
                player_names,
                player_ages,
            )

            self._flush_section(doc_id)

    def _buffer_single_team_report(
        self,
        roster: Roster,
        team_result: Any,
        outlook: DynastyOutlook | None,
        player_projections: dict[str, tuple[str, float]],
        player_names: dict[str, str],
        player_ages: dict[str, int | None],
    ) -> None:
        """Queue a single team's report onto the current section buffer."""
        # H2 = owner name (the report's identifying header per team).
        self._buffer_paragraph(
            roster.owner_name, named_style="HEADING_2", bold=True
        )

        # Record line.
        #
        # No Dynasty Window cell: the stage is a band on the Franchise Rating
        # (engine/gm_rating.py::rating_to_stage) and the CLI's Monte-Carlo
        # pipeline has no rating in scope. Giving this export its own second
        # derivation would rebuild the two-models problem the Assets-led
        # Outlook redesign exists to delete.
        record = f"{roster.wins}-{roster.losses}"
        if roster.ties:
            record += f"-{roster.ties}"

        # Header info table: 1-row, 2-col row.
        self._buffer_table(
            ["Record", "Outlook"],
            [[record, _outlook_label(team_result.playoff_pct)]],
        )
        self._buffer_blank_line()

        # --- Roster Analysis sub-heading ---
        self._buffer_paragraph(
            "Roster Analysis", named_style="HEADING_3", bold=True
        )

        # Top projected players.
        scored_players: list[tuple[str, str, int | None, float]] = []
        for pid in roster.players:
            if pid in player_projections:
                pos, proj = player_projections[pid]
                name = player_names.get(pid, pid)
                age = player_ages.get(pid)
                scored_players.append((name, pos, age, proj))
        scored_players.sort(key=lambda x: x[3], reverse=True)

        self._buffer_paragraph(
            "Top Projected Players",
            named_style="NORMAL_TEXT",
            bold=True,
        )
        top_rows = []
        for name, pos, age, proj in scored_players[:8]:
            age_str = str(age) if age is not None else "-"
            top_rows.append([name, pos, age_str, f"{proj:.1f}"])
        if top_rows:
            self._buffer_table(
                ["Player", "Pos", "Age", "Proj Pts/Wk"],
                top_rows,
            )
        self._buffer_blank_line()

        # Age profile table.
        if outlook is not None and outlook.age_profile.avg_age_by_position:
            ap = outlook.age_profile
            self._buffer_paragraph(
                "Age Profile by Position",
                named_style="NORMAL_TEXT",
                bold=True,
            )
            young_by_pos: dict[str, list[str]] = {}
            risks_by_pos: dict[str, list[str]] = {}
            for p in ap.core_young:
                young_by_pos.setdefault(p.position, []).append(p.full_name)
            for p in ap.aging_risks:
                risks_by_pos.setdefault(p.position, []).append(p.full_name)

            age_rows = []
            for pos, avg in sorted(ap.avg_age_by_position.items()):
                young_names = ", ".join(young_by_pos.get(pos, [])) or "—"
                risk_names = ", ".join(risks_by_pos.get(pos, [])) or "—"
                age_rows.append(
                    [pos, f"{avg:.1f}", risk_names, young_names]
                )
            self._buffer_table(
                ["Position", "Avg Age", "Aging Risks", "Core Young"],
                age_rows,
            )
            self._buffer_blank_line()

        # --- Dynasty Outlook sub-heading ---
        self._buffer_paragraph(
            "Dynasty Outlook", named_style="HEADING_3", bold=True
        )

        # Season projection paragraph.
        self._buffer_paragraph(
            (
                f"Projected record: {team_result.avg_wins:.1f}-"
                f"{team_result.avg_losses:.1f}  •  "
                f"Playoff odds: {team_result.playoff_pct:.1f}%  •  "
                f"Championship odds: {team_result.championship_pct:.1f}%"
            ),
            named_style="NORMAL_TEXT",
        )

        if outlook is not None:
            dc = outlook.draft_capital

            # Draft capital table.
            self._buffer_paragraph(
                "Draft Capital",
                named_style="NORMAL_TEXT",
                bold=True,
            )
            dc_rows = []
            # Group picks_by_season_round into season-level rows.
            by_season: dict[int, list[tuple[int, int]]] = {}
            for (season, rnd), count in sorted(dc.picks_by_season_round.items()):
                by_season.setdefault(season, []).append((rnd, count))
            for season, total in sorted(dc.picks_by_season.items()):
                round_notes = (
                    ", ".join(
                        f"R{rnd}: {count}"
                        for rnd, count in by_season.get(season, [])
                    )
                    or "—"
                )
                dc_rows.append([str(season), str(total), round_notes])
            if not dc_rows:
                dc_rows = [["—", "—", "No draft pick data"]]
            self._buffer_table(
                ["Season", "Picks Owned", "Breakdown"],
                dc_rows,
            )
            self._buffer_paragraph(
                (
                    f"Status: {dc.status}  •  "
                    f"Net vs league avg: {dc.net_vs_average:+.1f}  •  "
                    f"Traded away: {dc.picks_traded_away}  •  "
                    f"Acquired: {dc.picks_acquired}"
                ),
                named_style="NORMAL_TEXT",
                foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
            )
            self._buffer_blank_line()

            # Draft needs.
            self._buffer_paragraph(
                "Draft Needs",
                named_style="NORMAL_TEXT",
                bold=True,
            )
            if outlook.draft_needs:
                need_rows = [
                    [n.position, n.urgency, n.reason]
                    for n in outlook.draft_needs
                ]
                self._buffer_table(
                    ["Position", "Urgency", "Reasoning"],
                    need_rows,
                )
            else:
                self._buffer_paragraph(
                    "No immediate positional needs identified.",
                    named_style="NORMAL_TEXT",
                    foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
                )
            self._buffer_blank_line()

    def write_tab_matchup_forecasts(
        self,
        doc_id: str,
        sim_result: SimulationResult,
        roster_map: dict[int, Roster],
    ) -> None:
        """Write the Weekly Matchup Forecasts section.

        All weeks share one section flush. With ~14 weekly tables this
        emits ``14 + 1 = 15`` structural batchUpdates plus one populate
        batchUpdate, interleaved with ~14 inter-chunk GETs. Each chunk
        ends with a single ``insertTable``, so no batch contains a text
        insert whose index depends on a previously-inserted table — the
        invariant that prevents the "insertion index must be inside the
        bounds of an existing paragraph" error.
        """
        logger.info("Writing Matchup Forecasts section to doc %s", doc_id)
        self._begin_section(doc_id)

        self._buffer_page_break()
        self._buffer_paragraph(
            "Weekly Matchup Forecasts",
            named_style="HEADING_1",
            bold=True,
        )
        self._buffer_paragraph(
            "Per-week head-to-head forecasts. Win% reflects the favored team.",
            named_style="NORMAL_TEXT",
            foreground_color={"red": 0.4, "green": 0.4, "blue": 0.4},
        )

        by_week: dict[int, list[Any]] = {}
        for m in sim_result.matchup_results:
            by_week.setdefault(m.week, []).append(m)

        for week in sorted(by_week.keys()):
            self._buffer_blank_line()
            self._buffer_paragraph(
                f"Week {week}",
                named_style="HEADING_2",
                bold=True,
            )
            rows = []
            for m in by_week[week]:
                team1 = roster_map.get(m.roster_id_1)
                team2 = roster_map.get(m.roster_id_2)
                name1 = team1.owner_name if team1 else f"Roster {m.roster_id_1}"
                name2 = team2.owner_name if team2 else f"Roster {m.roster_id_2}"

                if m.win_pct_1 >= m.win_pct_2:
                    favored = name1
                    favored_pct = m.win_pct_1
                else:
                    favored = name2
                    favored_pct = m.win_pct_2

                rows.append(
                    [
                        f"{name1} vs {name2}",
                        favored,
                        f"{favored_pct:.1f}%",
                        f"{m.avg_score_1:.1f} – {m.avg_score_2:.1f}",
                    ]
                )

            self._buffer_table(
                ["Matchup", "Favored", "Win%", "Proj Score"],
                rows,
            )

        self._flush_section(doc_id)



# ---------------------------------------------------------------------------
# Internal: structure inspection
# ---------------------------------------------------------------------------


def _walk_tables(doc_body_content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk a document body's content and return one entry per table.

    For each table element encountered (in document order), returns a dict
    with:
      - ``startIndex``: the table's start index (its ``tableStartLocation``)
      - ``rows``: a list of rows, each a list of cell start-of-content
        paragraph indices (where ``insertText`` should target)

    Cell start-of-content paragraph index is the ``startIndex`` of the
    first ``paragraph`` element inside the cell's ``content``. This is the
    only safe insertion target for cell text — relying on
    ``cell.startIndex + 1`` is fragile because the API may insert
    non-paragraph structural markers immediately after the cell open.

    Falls back to ``cell.startIndex + 1`` when the API response omits cell
    ``content`` entirely (e.g., in synthetic test fixtures).
    """
    tables: list[dict[str, Any]] = []
    for elem in doc_body_content:
        if "table" not in elem:
            continue
        rows: list[list[int]] = []
        for table_row in elem["table"].get("tableRows", []):
            row_indices: list[int] = []
            for cell in table_row.get("tableCells", []):
                first_para_start: int | None = None
                for inner in cell.get("content", []) or []:
                    if "paragraph" in inner:
                        first_para_start = inner.get("startIndex")
                        if first_para_start is not None:
                            break
                if first_para_start is None:
                    first_para_start = cell.get("startIndex", 0) + 1
                row_indices.append(first_para_start)
            rows.append(row_indices)
        tables.append(
            {"startIndex": elem.get("startIndex", 0), "rows": rows}
        )
    return tables


