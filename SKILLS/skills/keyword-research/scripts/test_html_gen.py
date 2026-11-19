"""Verify the keyword dashboard using a checked-in report fixture."""

import json
from pathlib import Path

from generate_html_dashboard import generate_html_dashboard


def test_generate_html_dashboard(tmp_path):
    fixture = (
        Path(__file__).resolve().parents[4] / "REPORTS-ALL" /
        "keyword-reports" / "B0FMRTXKF6_US_20260314"
    )
    keywords = json.loads((fixture / "keywords_raw.json").read_text(encoding="utf-8"))
    categorized = json.loads((fixture / "categorized_result.json").read_text(encoding="utf-8"))

    output = Path(generate_html_dashboard("B0FMRTXKF6", "US", keywords, categorized, tmp_path))

    assert output == tmp_path / "dashboard.html"
    html = output.read_text(encoding="utf-8")
    assert "B0FMRTXKF6" in html
    assert "{{KEYWORD_TABLE_ROWS}}" not in html
    assert "<tbody" in html
