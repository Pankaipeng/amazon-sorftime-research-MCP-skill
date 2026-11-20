"""Verify that the keyword workflow reloads saved classifications."""

import json

from workflow import KeywordResearchWorkflow


def test_load_categorized_result(tmp_path):
    categorized = {"CORE": ["desk organizer"], "FUNCTION": ["document storage"]}
    saved = json.dumps(categorized)
    (tmp_path / "categorized_result.json").write_text(saved, encoding="utf-8")
    workflow = KeywordResearchWorkflow("B000000001", "US", claude_code_env=False)
    workflow.output_dir = tmp_path

    result = workflow._load_categorized_result()

    assert result
    assert result == json.loads(saved)
