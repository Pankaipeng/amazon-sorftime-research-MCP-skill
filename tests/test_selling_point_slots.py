"""Regression coverage for assigning A grades after the fact check."""

from pathlib import Path
import runpy


def test_fact_check_reallocates_a_grade_slots(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    apply_slots = runpy.run_path(str(scripts / "check_facts.py"))["apply_a_grade_slots"]
    source = {
        "SP01": {"sp_id": "SP01", "G机会分": "0.90", "等级": "A"},
        "SP02": {"sp_id": "SP02", "G机会分": "0.70", "等级": "A"},
        "SP03": {"sp_id": "SP03", "G机会分": "0.60", "等级": "B"},
        "SP04": {"sp_id": "SP04", "G机会分": "0.70", "等级": "B"},
        "SP05": {"sp_id": "SP05", "G机会分": "0.55", "等级": "B"},
    }
    # SP01 failed fact review. SP04 can now use its slot.
    facts_grades = [("SP03", "A"), ("SP01", "D"), ("SP05", "A"), ("SP04", "A"), ("SP02", "A")]
    judgments = [{"sp_id": point_id, "等级_v2": grade} for point_id, grade in facts_grades]
    library = [{"sp_id": point_id, "等级": grade, "等级_note": ""} for point_id, grade in facts_grades]

    apply_slots(judgments, library, source, slots=2)

    expected = {"SP01": "D", "SP02": "A", "SP03": "B", "SP04": "A", "SP05": "B"}
    assert {row["sp_id"]: row["等级_v2"] for row in judgments} == expected
    assert {row["sp_id"]: row["等级"] for row in library} == expected
    assert all("名额已满" in row["等级_note"] for row in library if row["等级"] == "B")

    apply_slots(judgments, library, source, slots=1)
    assert next(row for row in library if row["sp_id"] == "SP02")["等级"] == "A"
    assert next(row for row in library if row["sp_id"] == "SP04")["等级"] == "B"
