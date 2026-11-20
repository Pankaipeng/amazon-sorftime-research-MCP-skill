"""Synthetic regression fixtures for the issues found in an end-to-end run."""

import csv
import json
from pathlib import Path
import sys

from openpyxl import load_workbook
from PIL import Image

from test_module_handoffs import SCRIPTS, load_config, run, write_config, write_csv, write_json

sys.path.insert(0, str(SCRIPTS))
from collect_sellersprite import collect, page_arguments
from image_brief import MAIN_REQUIREMENTS
from numeric_claims import bottle_issues, dimension_issues


ASIN = "B000000001"


def product_facts():
    return {
        "sku": "SMOKE-SKU",
        "dims": {"outer_in": {"l": 12.3, "w": 8.6, "h": 10.9},
                 "outer_cm": {"l": 31.2, "w": 21.8, "h": 27.7}},
        "specs": {"bottle_tiers": 2, "standard_red_wine_bottles_lower_tiers": 8},
        "structure": {"shape": "open shelf"},
    }


def test_numeric_claims_respect_units_and_scope():
    facts = product_facts()
    assert not dimension_issues("31.2 x 21.8 x 27.7 cm", facts)
    assert not dimension_issues("12.3 in W × 8.6 in D × 10.9 in H", facts)
    assert dimension_issues("8.6 in wide by 12.3 in deep by 10.9 in high", facts)
    assert dimension_issues("19.3 x 8.6 x 10.9 in", facts)
    assert not bottle_issues("8 Standard Red Wine Bottles\n4 per lower tier", facts)
    assert bottle_issues("8 Standard Red Wine Bottles\n6 per lower tier", facts)
    assert bottle_issues("Holds 2 bottles on the top shelf", facts)
    assert bottle_issues("Holds 6 wine bottles", {})
    assert not bottle_issues("Open top shelf for select unusual bottles", facts)


def test_c9_rejects_wrong_numeric_values(tmp_path):
    config = load_config("copy_config.yaml")
    config["inputs"].pop("fab_cards", None)
    config["inputs"].pop("selling_point_library", None)
    config.pop("bullet_selection", None)
    config["decisions"]["bullet_translation_required"] = False
    config["decisions"]["bullet_semantic_review_required"] = False
    config["fields"]["st"].pop("target_min_ratio", None)
    data = {
        "title": "Countertop Wine Rack for 8 Standard Bottles",
        "highlights": "Open shelf, iron rails, assembly hardware",
        "bullets": [
            "Two Lower Tiers: Store four standard red wine bottles on each of the two lower tiers; use the front slots",
            "Measure First: The rack measures 12.3 in wide by 8.6 in deep by 10.9 in high; check the counter",
            "Top Shelf: Use the open shelf for select unusual bottles; keep the lower rows accessible",
            "Panel Finish: A two-tone finish shows the wood grain; match it to the room",
            "Hardware Included: Seven fasteners come in the box; review the instructions before assembly",
        ],
        "bullet_sp_ids": [f"SP{i}" for i in range(1, 6)],
        "search_terms": "tabletop sideboard",
    }
    selection = {"selected": [{"sp_id": point, "claim": "Synthetic claim", "M": 1,
                               "fact_status": "CONFIRMED"} for point in data["bullet_sp_ids"]]}
    for key, value in [("copy", data), ("facts", product_facts()), ("selected_sp", selection)]:
        file = tmp_path / f"{key}.json"
        config["inputs"][key] = str(file)
        write_json(file, value)
    keywords = tmp_path / "keywords.csv"
    write_csv(keywords, ["keyword", "prio", "W", "R"], [["wine rack", "P0", 100, 1]])
    config["inputs"]["keyword_library"] = str(keywords)
    config["outputs"]["dir"] = str(tmp_path)
    cfg = tmp_path / "copy.yaml"
    write_config(cfg, config)
    args = ("--category", "synthetic", "--config", cfg, "--no-write")
    baseline = run(SCRIPTS / "check_copy.py", *args)
    assert "[PASS] C9" in baseline
    for index, old, new, expected in [
        (1, "12.3 in", "19.3 in", "dims.outer_in.l=12.3 in"),
        (0, "four standard", "six standard", "单层"),
    ]:
        changed = {**data, "bullets": list(data["bullets"])}
        changed["bullets"][index] = changed["bullets"][index].replace(old, new)
        write_json(Path(config["inputs"]["copy"]), changed)
        output = run(SCRIPTS / "check_copy.py", *args, expect=1)
        assert "[FAIL] C9" in output and expected in output


def test_brief_template_round_trip_and_rejects_missing_image(tmp_path):
    facts = tmp_path / "facts.json"
    write_json(facts, product_facts())
    Image.new("RGB", (32, 32), "white").save(tmp_path / "reference.png")
    write_csv(tmp_path / "manifest.csv", ["marketplace", "asin", "pos", "status", "file"],
              [["US", ASIN, 1, "ok", "reference.png"]])
    kinds = ["main_a", "feature", "feature", "scenario", "feature", "dimensions", "package", "main_b"]
    rows = []
    for index, kind in enumerate(kinds, 1):
        row = {
            "slot": None if kind == "main_b" else index,
            "kind": kind,
            "name": kind,
            "pixels": "1500 × 1500",
            "style": "实拍",
            "goal": "CTR" if kind.startswith("main") else "详情页购买转化",
            "selling_point": "SP01",
            "copy": "无" if kind in {"main_a", "main_b", "scenario"} else "Storage",
            "design": "主体居中",
            "evidence": "合成事实",
            "acceptance": "手机可辨",
            "reference": {"asin": ASIN, "position": 1, "technique": "合成参考"},
        }
        if kind.startswith("main"):
            row["main_checks"] = sorted(MAIN_REQUIREMENTS)
        rows.append(row)
    rows[5]["copy"] = "12.3 in W × 8.6 in D × 10.9 in H"
    decision = {"sp_id": "SP01", "copy_candidate": "文案第 1",
                "image_candidate": "图片第 2", "evidence": {"image": "图1", "review": "评论1", "bullet": "五点1"},
                "levels": [2, 1, 0], "decision": "保留", "validation": "手机试读"}
    experiment = {"hypothesis": "缩略图可辨", "variable": "角度", "controls": "光线",
                  "baseline": "尚无", "minimum_change": "10%", "metrics": "CTR",
                  "sample_or_end": "14 天", "decision": "按分组比较", "status": "待线上验证"}
    spec = {"sku": "SMOKE-SKU", "marketplace": "US", "facts": facts.name, "image_manifest": "manifest.csv",
            "rows": rows, "decisions": [decision], "experiments": {"main": experiment, "secondary": experiment}}
    source = tmp_path / "brief.json"
    write_json(source, spec)
    output = tmp_path / "brief.xlsx"
    args = ("--spec", source, "--workbook")
    assert "7 个正式图位" in run(SCRIPTS / "image_brief.py", "build", *args, output)
    run(SCRIPTS / "image_brief.py", "check", *args, output)
    markdown = tmp_path / "brief.md"
    markdown.write_text("draft", encoding="utf-8")
    assert "Excel 模板" in run(SCRIPTS / "image_brief.py", "check", *args, markdown, expect=1)
    workbook = load_workbook(output)
    workbook.active._images.pop()
    workbook.save(output)
    workbook.close()
    assert "参考缩略图" in run(SCRIPTS / "image_brief.py", "check", *args, output, expect=1)
    rows[5]["copy"] = "99.3 in W × 8.6 in D × 10.9 in H"
    write_json(source, spec)
    assert "数字主张不一致" in run(SCRIPTS / "image_brief.py", "build", *args, output, expect=1)


def test_traffic_pagination_deduplicates_and_records_gap(tmp_path):
    filters = {"asin": ASIN, "marketplace": "US",
               "order": {"field": "trafficPercentage", "desc": True}}
    responses = []
    for keyword, pages, total in [(None, [["Alpha", "beta"], ["beta"], ["BETA"]], 5),
                                  ("gamma", [["beta", "gamma"]], 2)]:
        for page, values in enumerate(pages, 1):
            params = {**filters, **({"keyword": keyword} if keyword else {})}
            responses.append({"tool": "traffic_keyword",
                              "arguments": page_arguments("traffic_keyword", params, page, 2),
                              "response": {"code": "OK", "data": {"total": total,
                                                                  "items": [{"keyword": v} for v in values]}}})
    response_file = tmp_path / "replay.json"
    write_json(response_file, responses)
    groups = tmp_path / "groups.json"
    write_json(groups, {"marketplace": "US", "groups": {"head": [ASIN]}})
    run(SCRIPTS / "collect_sellersprite.py", "--groups", groups, "--out", tmp_path,
        "--tool", "traffic_keyword", "--page-size", 2, "--root", "gamma",
        "--transcript", response_file, expect=2)
    ledger = json.loads((tmp_path / "collection-traffic.json").read_text(encoding="utf-8"))["collections"][0]
    assert (ledger["status"], ledger["unique"], ledger["gap"]) == ("partial", 3, 2)
    assert ledger["base"]["stop"] == "repeated_page" and ledger["fallback"][0]["unique"] == 2
    with (tmp_path / "0A-竞品流量词.csv").open(encoding="utf-8-sig") as f:
        assert [r["keyword"] for r in csv.DictReader(f)] == ["Alpha", "beta", "gamma"]


def test_review_duplicate_is_not_counted_and_short_page_can_continue():
    items = [
        {"id": "1", "content": "Synthetic", "star": 2},
        {"id": "2", "content": "Another synthetic review", "star": 2},
    ]
    def call(tool, args):
        assert tool == "review" and args["starList"] == [1, 2, 3]
        reviews = [items[0]] if args["page"] == 1 else items
        return {"code": "OK", "data": {"total": 2, "items": reviews}}
    results, ledger = collect(call, "review", {"starList": [1, 2, 3]}, max_pages=4, page_size=20)
    assert [r["id"] for r in results] == ["1", "2"]
    assert (ledger["received"], ledger["unique"], ledger["status"]) == (3, 2, "complete")
