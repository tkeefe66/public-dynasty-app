"""Render recap markdown to deliverable formats.

The Delivery protocol decouples WHAT we generate (recap text) from WHERE it
goes. v1 ships HtmlFileDelivery; a future ChatDelivery (Telegram/Discord) can
implement the same interface without touching the writer or engine.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Protocol

from jinja2 import Environment, select_autoescape

logger = logging.getLogger(__name__)

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{{ league_name }} — Week {{ week }} Recap</title>
<style>
  body { max-width: 760px; margin: 2rem auto; padding: 0 1rem;
         font: 17px/1.6 -apple-system, system-ui, sans-serif; color: #1a1a1a; }
  h1, h2, h3 { line-height: 1.25; }
  hr { border: none; border-top: 1px solid #ddd; margin: 2rem 0; }
  .meta { color: #888; font-size: 14px; text-transform: uppercase;
          letter-spacing: .05em; }
</style></head>
<body>
<p class="meta">{{ league_name }} · Week {{ week }}</p>
{{ body }}
</body></html>
"""


def _markdown_to_html(md: str) -> str:
    """Minimal, dependency-free markdown -> HTML for headings, bold, hr, and
    paragraphs. We control the input (LLM markdown), so we keep this small
    rather than pulling a markdown lib.
    """
    html_lines = []
    for block in md.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block == "---":
            html_lines.append("<hr>")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", block)
        if m:
            level = len(m.group(1))
            text = _inline(m.group(2))
            html_lines.append(f"<h{level}>{text}</h{level}>")
            continue
        html_lines.append(f"<p>{_inline(block)}</p>")
    return "\n".join(html_lines)


def _inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text.replace("\n", "<br>")


def render_recap_html(markdown: str, league_name: str, week: int) -> str:
    env = Environment(autoescape=select_autoescape(["html"]))
    template = env.from_string(_TEMPLATE)
    # body is pre-rendered HTML we trust (our own converter) -> mark safe via
    # Markup is overkill; disable autoescape only for the body by passing it
    # already-escaped at the inline layer. Here input is LLM text; we accept it.
    from markupsafe import Markup
    return template.render(
        league_name=league_name, week=week,
        body=Markup(_markdown_to_html(markdown)),
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class Delivery(Protocol):
    def deliver(self, markdown: str, league_name: str, week: int) -> str:
        """Deliver the recap. Returns a locator (file path, URL, message id)."""
        ...


class HtmlFileDelivery:
    """Writes the recap to a standalone HTML file and returns its path.

    Pass ``out_path`` to write to an exact file (honors a user's
    ``--out report.html``); otherwise a ``<league>_week<N>_recap.html`` name
    is generated inside ``out_dir`` (default: cwd).
    """

    def __init__(
        self, out_dir: Path | None = None, out_path: Path | None = None
    ) -> None:
        self.out_dir = Path(out_dir) if out_dir else Path.cwd()
        self.out_path = Path(out_path) if out_path else None

    def deliver(self, markdown: str, league_name: str, week: int) -> str:
        html = render_recap_html(markdown, league_name, week)
        if self.out_path is not None:
            path = self.out_path
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            path = self.out_dir / f"{_slug(league_name)}_week{week}_recap.html"
        path.write_text(html)
        logger.info("Wrote recap to %s", path)
        return str(path)
