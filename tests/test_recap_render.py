from pathlib import Path

from sleeper_dynasty.output.recap_render import (
    render_recap_html, HtmlFileDelivery,
)


def test_render_wraps_markdown_in_html():
    html = render_recap_html(
        "# Week 9\n\n**Team A** got smoked.", league_name="Bros", week=9
    )
    assert "<html" in html.lower()
    assert "Team A" in html
    assert "Week 9" in html


def test_html_file_delivery_writes_file(tmp_path):
    delivery = HtmlFileDelivery(out_dir=tmp_path)
    path = delivery.deliver(
        "# Hi", league_name="Dynasty Bros", week=9
    )
    p = Path(path)
    assert p.exists()
    assert p.suffix == ".html"
    assert "Dynasty Bros" in p.read_text()


def test_html_file_delivery_honors_explicit_out_path(tmp_path):
    target = tmp_path / "sub" / "myrecap.html"
    delivery = HtmlFileDelivery(out_path=target)
    path = delivery.deliver("# Hi", league_name="Dynasty Bros", week=9)
    assert Path(path) == target
    assert target.exists()
    assert "Dynasty Bros" in target.read_text()
