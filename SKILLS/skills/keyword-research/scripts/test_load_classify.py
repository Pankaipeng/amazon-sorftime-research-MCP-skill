"""Verify that the keyword workflow reloads saved classifications."""

import json
from pathlib import Path

from workflow import KeywordResearchWorkflow


def test_load_categorized_result(tmp_path):
    fixture = (
        Path(__file__).resolve().parents[4] / "REPORTS-ALL" /
        "keyword-reports" / "B0FMRTXKF6_US_20260314" / "categorized_result.json"
    )
    saved = fixture.read_text(encoding="utf-8")
    (tmp_path / fixture.name).write_text(saved, encoding="utf-8")
    workflow = KeywordResearchWorkflow("B0FMRTXKF6", "US", claude_code_env=False)
    workflow.output_dir = tmp_path

    result = workflow._load_categorized_result()

    assert result
    assert result == json.loads(saved)
