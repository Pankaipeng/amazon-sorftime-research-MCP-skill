"""Verify the keyword dashboard using synthetic keyword data."""

from pathlib import Path

from generate_html_dashboard import generate_html_dashboard


def test_generate_html_dashboard(tmp_path):
    keywords = [{"keyword": "desk organizer", "search_volume": 1200, "cpc": 0.82}]
    categorized = {"CORE": ["desk organizer"]}

    output = Path(generate_html_dashboard("B000000001", "US", keywords, categorized, tmp_path))
    assert output == tmp_path / "dashboard.html"
    html = output.read_text(encoding="utf-8")
    assert "B000000001" in html
    assert "{{KEYWORD_TABLE_ROWS}}" not in html
    assert "<tbody" in html
    assert "desk organizer" in html
