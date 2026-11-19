"""FAB export must gate claims on both permission and current product facts."""

import csv
from pathlib import Path
import runpy


def test_fab_export_excludes_structure_and_stale_claims(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    write = runpy.run_path(str(scripts / "check_facts.py"))["write_fab_cards"]
    entries = [
        {"sp_id": "SP01", "卖点名": "吸附", "主张角色": "仅结构素材"},
        {"sp_id": "SP03", "卖点名": "双安装", "主张角色": "主卖点"},
        {"sp_id": "SP13", "卖点名": "分区"},
    ]
    checks = [{"fact_status": "CONFIRMED", "依赖字段": "qty", "事实取值": "qty=2"}] * 3
    card = {"feature": "双件", "advantage": "可选择", "benefit": "顺手", "copy": "Two options",
            "requires": {"qty": 2}}
    config = {"SP01": card, "SP03": card, "SP13": {**card, "requires": {"qty": 3}}}
    evidence = tmp_path / "SP-02-证据链.csv"
    evidence.write_text("sp_id,维度,定位\nSP03,五点,TEST#2\n", encoding="utf-8")
    output = tmp_path / "fab.csv"

    write(output, entries, checks, {"qty": 2}, config, evidence)

    with output.open(encoding="utf-8-sig", newline="") as stream:
        structure, publishable, stale = csv.DictReader(stream)
    assert structure["使用状态"] == "仅结构素材" and structure["可用措辞"] == ""
    assert publishable["使用状态"] == "可用" and publishable["可用措辞"] == "Two options"
    assert "TEST#2" in publishable["市场证据定位"]
    assert stale["使用状态"] == "待编写或复核" and stale["可用措辞"] == ""


def test_copy_rejects_unapproved_fab_claims(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from check_copy import audit_selected_points, load_yaml, unsupported_fab_claim

    cards = {
        "SP01": {"使用状态": "仅结构素材", "可用措辞": ""},
        "SP02": {"使用状态": "待验证", "可用措辞": ""},
        "SP03": {"使用状态": "可用", "可用措辞": "Two ways to mount"},
    }
    copy = {"bullet_sp_ids": ["SP03"], "bullets": ["Use two suction cups or the adhesive mount"]}
    selection = {"selected": [{"sp_id": "SP03", "fact_status": "CONFIRMED",
                               "claim": "Two ways to mount", "M": 22}]}
    patterns = load_yaml(scripts / "copy_config.yaml")["fab_claim_patterns"]

    assert audit_selected_points(selection, copy, 1, cards)[0] == "PASS"
    assert unsupported_fab_claim(copy, cards, patterns) is None
    for point_id, phrase in [("SP01", "Strong suction"), ("SP02", "Long-lasting hold")]:
        row = {**selection["selected"][0], "sp_id": point_id, "claim": phrase}
        assert audit_selected_points({"selected": [row]}, copy, 1, cards)[0] == "FAIL"
        assert point_id in unsupported_fab_claim({**copy, "highlights": phrase}, cards, patterns)
