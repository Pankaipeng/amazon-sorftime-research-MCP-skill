"""Check installation claim matching and unique review counts."""

from pathlib import Path
import runpy

from openpyxl import Workbook
import yaml


SCRIPTS = Path(__file__).resolve().parents[1] / "SKILLS/scripts"


def test_installation_claims_exclude_related_but_different_statements():
    match = runpy.run_path(str(SCRIPTS / "build_selling_points.py"))["match_bullets"]
    config = yaml.safe_load((SCRIPTS / "sp_config.yaml").read_text(encoding="utf-8"))
    cases = [
        ("SP01", "Strong suction for a secure hold", "Includes two suction cups"),
        ("SP02", "Suction stays firmly in place for six months", "Built to last for years; includes a suction cup"),
        ("SP03", "Comes with suction cups and an adhesive strip", "Includes an adhesive strip with stronger grip than suction cups"),
        ("SP04", "Tool-free installation; no drilling", "Peel and stick in seconds"),
    ]
    definitions = {item["id"]: item for item in config["sp_defs"]}
    for point_id, claim, adjacent_claim in cases:
        item = definitions[point_id]
        asins = [{"asin": "sample", "bullets": [claim, adjacent_claim]}]
        assert match(asins, item["bullet_patterns"], item.get("bullet_exclude_patterns", [])) == {"sample": [1]}


def test_theme_counts_each_review_key_once(tmp_path):
    build = runpy.run_path(str(SCRIPTS / "build_selling_points.py"))["build_theme_rows"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "reviews_master"
    sheet.append(["review_key", "好评|安装省事|安装简单", "好评|吸附牢固|牢固", "差评|吸附失效|脱落"])
    sheet.append(["review-1", "Easy", "Sturdy", "Came off once"])
    sheet.append(["review-1", "duplicate", None, None])
    sheet.append(["review-2", None, "Holds well", None])
    path = tmp_path / "master.xlsx"
    workbook.save(path)
    workbook.close()
    definitions = [
        {"id": "SP03", "theme": "固定与安装", "claim_role": "主卖点", "review_l2": ["安装简单"]},
        {"id": "SP04", "theme": "固定与安装", "claim_role": "操作利益", "review_l2": ["安装简单", "牢固", "脱落"]},
    ]
    theme, = build(definitions, path)
    assert theme[1] == "SP03"
    assert theme[3:6] == [2, 1, 2]
    missing, = build(definitions, None)
    assert missing[3:6] == ["", "", ""]
