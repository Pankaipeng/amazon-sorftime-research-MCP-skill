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


def test_copy_reviews_current_scores_and_translation(tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from check_copy import audit_bullet_translations, audit_selected_points, read_selling_point_scores

    library = tmp_path / "library.csv"
    library.write_text("sp_id,M\nSP03,29.1\n", encoding="utf-8")
    scores = read_selling_point_scores(library)
    point = {"sp_id": "SP03", "fact_status": "CONFIRMED", "claim": "Two ways to mount", "M": 23.1}
    selection = {"selected": [point]}
    copy = {"bullet_sp_ids": ["SP03"], "bullets": ["Two ways to mount"]}

    status, detail = audit_selected_points(selection, copy, 1, selling_point_scores=scores)
    assert status == "FAIL" and "与卖点库 v2 的 29.1 不一致" in detail
    point["M"] = 29.1
    assert audit_selected_points(selection, copy, 1, selling_point_scores=scores)[0] == "PASS"
    assert audit_bullet_translations(copy, required=True)
    assert audit_bullet_translations({**copy, "bullet_translations": ["Two ways to mount"]}, required=True)
    assert audit_bullet_translations({**copy, "bullet_translations": ["两种安装方式"]}, required=True) is None


def test_search_term_limits_and_frontend_deduplication(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from check_copy import search_term_issues

    limits = {"max": 250, "strict_max": True, "target_min_ratio": 0.5, "unique_words": True}
    previous = search_term_issues("essentials organization decor", "Sponge Holder", limits)
    assert any("低于交付目标 125 字节" in issue for issue in previous)
    assert any("须小于" in issue for issue in search_term_issues("x" * 250, "", limits))
    assert any("与前台重复" in issue for issue in search_term_issues("caddy drain", "Sink Caddy", limits))
    assert not search_term_issues("x" * 125, "", limits)


def test_semantic_review_blocks_duplicate_or_stale_bullets(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "SKILLS/scripts"
    monkeypatch.syspath_prepend(str(scripts))
    from check_copy import audit_bullet_semantics

    ids = ["SP11", "SP13"]
    bullets = ["Sponge and brush in one holder", "A separate spot for each washing tool"]
    copy = {"bullet_sp_ids": ids, "bullets": bullets}
    assert "缺失" in audit_bullet_semantics(copy, required=True)
    pair = {"sp_ids": ids, "verdict": "duplicate", "reason": "两条均讲洗刷工具的分区收纳"}
    review = {"sp_ids": ids, "bullets": bullets, "buyer_benefits": ["洗刷工具集中收纳", "洗刷工具分区放置"],
              "pairs": [pair]}
    copy["bullet_semantic_review"] = review
    assert "需去重" in audit_bullet_semantics(copy, required=True)
    assert "已变动" in audit_bullet_semantics({**copy, "bullets": [bullets[0], "Open drainage"]}, required=True)

    review = {"sp_ids": ["SP11", "SP17"], "bullets": [bullets[0], "Bottom openings let water drain"],
              "buyer_benefits": ["洗刷工具集中收纳", "湿工具滴水有出口"], "pairs": []}
    copy = {"bullet_sp_ids": review["sp_ids"], "bullets": review["bullets"], "bullet_semantic_review": review}
    assert "1 对未检查" in audit_bullet_semantics(copy, required=True)
    review["pairs"].append({"sp_ids": review["sp_ids"], "verdict": "distinct", "reason": "分区收纳与排水各有用途"})
    assert audit_bullet_semantics(copy, required=True) is None
