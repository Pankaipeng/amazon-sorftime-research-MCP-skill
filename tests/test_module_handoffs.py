"""Offline regression tests for the module file handoffs."""

import csv
import json
import os
from pathlib import Path
import subprocess
import sys

import openpyxl
import yaml


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "SKILLS/scripts"


def run(script, *args, expect=0, console_encoding="utf-8"):
    env = {**os.environ, "PYTHONIOENCODING": console_encoding}
    env.pop("PYTHONUTF8", None)
    proc = subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=REPO,
        env=env,
        capture_output=True,
        encoding=console_encoding,
        timeout=30,
    )
    assert proc.returncode == expect, (script.name, proc.stdout, proc.stderr)
    return proc.stdout


def write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def load_config(name):
    return yaml.safe_load((SCRIPTS / name).read_text(encoding="utf-8"))


def write_config(path, value):
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_keyword_handoff(tmp_path):
    config = load_config("config.yaml")
    paths = {key: tmp_path / name for key, name in config["inputs"].items()}
    keyword = "suction sponge holder"
    write_csv(paths["search_table"], ["keyword", "searches", "source"],
              [[keyword, 20000, "fixture 2026-01"]])
    write_csv(paths["a_traffic"], ["keyword"], [[keyword]])
    write_csv(paths["b_title"], ["word", "asin_count", "coverage"], [[keyword, 3, 0.5]])
    write_csv(paths["c_listing"], ["词/词组", "覆盖率"], [[keyword, 0.5]])

    autocomplete = REPO / "SKILLS/modules/10-keyword/scripts/ac.py"
    suggestions = tmp_path / "suggestions.json"
    write_json(suggestions, [{"value": keyword, "position": 1, "prefix": "suction"}])
    run(autocomplete, "merge", "--in", suggestions, "--out", paths["d_autocomplete"])
    write_json(paths["backend_json"], {"niche": [{"搜索词": keyword}], "aba": [{"搜索词": keyword}]})

    run(SCRIPTS / "merge.py", tmp_path)
    assert "0 未通过" in run(SCRIPTS / "check.py", tmp_path)
    paths["backend_json"].unlink()
    run(SCRIPTS / "merge.py", tmp_path)
    assert "后台未提供" in run(SCRIPTS / "check.py", tmp_path)
    row, = read_csv(tmp_path / config["outputs"]["library"])
    assert row["keyword"] == keyword
    assert row["search_source"] == "fixture 2026-01"


def test_selling_point_and_facts(tmp_path):
    keywords = tmp_path / "keywords.csv"
    write_csv(keywords, ["keyword", "prio", "W", "R"], [["suction sponge holder", "P0", 100, 1]])
    bullets = tmp_path / "bullets.json"
    write_json(bullets, [{
        "asin": "B000000001",
        "title": "Sponge holder",
        "bullets": ["Suction cups mount securely; removable drain tray"],
    }])

    reviews = tmp_path / "reviews.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "03_一级频次"
    workbook.active.append(["情感", "一级", "频次"])
    workbook.active.append(["差评", "安装", 100])
    review_sheet = workbook.create_sheet("04_二级频次")
    review_sheet.append(["字段"] * 7)
    review_sheet.append([None, "差评", "安装", "吸附", None, None, 1])
    workbook.save(reviews)
    workbook.close()

    config = load_config("sp_config.yaml")
    config["sp_defs"] = config["sp_defs"][:1]
    config["sp_defs"][0].update(bullet_patterns=["suction"], review_l2=["吸附"])
    config["inputs"].update(
        bullets_json=str(bullets), review_xlsx=str(reviews), keyword_library=str(keywords),
    )
    selling_config = tmp_path / "selling.yaml"
    write_config(selling_config, config)
    output = tmp_path / "selling"
    run(SCRIPTS / "build_selling_points.py", "--config", selling_config, "--out", output)
    run(SCRIPTS / "check_sp.py", "--config", selling_config, "--dir", output)
    run(SCRIPTS / "check_sp.py", "--config", selling_config, "--dir", tmp_path / "missing", expect=1)

    library = output / "SP-01-卖点库.csv"
    assert len(read_csv(library)) == 1
    facts = tmp_path / "facts.json"
    write_json(facts, {"material": {"suction": {"qty": 1, "material": None, "dia_in": None}}})
    config = load_config("fact_schema.yaml")
    config["meta"].update(library_v1=str(library), fact_card=str(facts))
    config["sp_rules"] = config["sp_rules"][:1]
    config["outputs"] = {key: str(tmp_path / Path(name).name) for key, name in config["outputs"].items()}
    fact_config = tmp_path / "facts.yaml"
    write_config(fact_config, config)
    result = run(SCRIPTS / "check_facts.py", "--config", fact_config, expect=1)
    assert "SP01" in result and "C1" in result
    row, = read_csv(Path(config["outputs"]["library_v2"]))
    assert row["英文主张"] == "Suction cup mounting"
    write_json(facts, {})
    run(SCRIPTS / "check_facts.py", "--config", fact_config, expect=2)


def test_copy_scoring_and_delivery(tmp_path):
    config = load_config("copy_config.yaml")
    del config["inputs"]["fab_cards"]
    del config["inputs"]["selling_point_library"]
    del config["decisions"]["bullet_translation_required"]
    del config["fields"]["st"]["target_min_ratio"]
    data = {
        "title": "Acme Stainless Steel Sponge Holder",
        "highlights": "Rust resistant steel",
        "bullets": ["Material: Stainless steel construction; for daily use"] * 5,
        "search_terms": "kitchen sink organizer",
        "_meta": {"brand": "Acme"},
    }
    point_ids = ["SP%02d" % index for index in range(1, 6)]
    selection = {"selected": [
        {"sp_id": point_id, "claim": "Stainless steel frame", "M": 10 - index,
         "fact_status": "CONFIRMED"}
        for index, point_id in enumerate(point_ids)
    ]}
    facts = {
        "dims": {"outer_in": {"l": 8.5, "w": 3.31, "h": 3.27}},
        "_source_detail": {"dims.outer_in": "单品尺寸未填，故用包装外尺寸作保守值"},
    }
    for key, value in [("copy", data), ("facts", facts), ("selected_sp", selection)]:
        path = tmp_path / (key + ".json")
        write_json(path, value)
        config["inputs"][key] = str(path)
    library = tmp_path / "keywords.csv"
    write_csv(library, ["prio", "keyword", "R", "W", "searches", "search_source"],
              [["P0", "sponge holder", 0.8, 2000, 2500, "fixture 2026-01"]])
    config["inputs"]["keyword_library"] = str(library)
    config["outputs"]["dir"] = str(tmp_path)
    outputs = {key: tmp_path / name for key, name in config["outputs"].items()}
    write_csv(outputs["placement"], ["词位", "关键词"], [["标题", "sponge holder"]])
    copy_config = tmp_path / "copy.yaml"
    write_config(copy_config, config)
    args = ["--config", copy_config, "--category", "sponge-holder"]

    run(SCRIPTS / "build_copy.py", *args, expect=2)
    assert "旧稿缺 bullet_sp_ids" in run(SCRIPTS / "check_copy.py", *args, expect=1)
    data["bullet_sp_ids"] = point_ids[::-1]
    write_json(tmp_path / "copy.json", data)
    assert "须按 M 降序排列" in run(SCRIPTS / "check_copy.py", *args, expect=1)
    data["bullet_sp_ids"] = point_ids
    write_json(tmp_path / "selected_sp.json", {})
    assert "须包含 selected 数组" in run(SCRIPTS / "check_copy.py", *args, expect=1)
    write_json(tmp_path / "selected_sp.json", selection)
    data["description"] = "The frame is 8.5 in long"
    write_json(tmp_path / "copy.json", data)
    result = run(SCRIPTS / "check_copy.py", *args, expect=1)
    assert "定稿卖点和五点 ID 对齐且按 M 降序" in result
    assert "事实卡三围取自包装" in result
    del data["description"]
    write_json(tmp_path / "copy.json", data)
    run(SCRIPTS / "check_copy.py", *args, expect=1)
    run(SCRIPTS / "score_copy.py", *args, console_encoding="gb18030")
    raw = outputs["score_raw"]
    report = json.loads(raw.read_text(encoding="utf-8"))
    assert "compliance_report" in report and "cdq_score" in report

    run(SCRIPTS / "build_copy.py", *args, "--sku", "SMOKE-SKU", expect=1)
    workbook = openpyxl.load_workbook(outputs["xlsx"], read_only=True)
    assert workbook["04_评分"]["A2"].value == "CDQ"
    workbook.close()
    assert "fixture 2026-01" in outputs["sources"].read_text(encoding="utf-8-sig")

    data["bullets"] = []
    write_json(tmp_path / "copy.json", data)
    run(SCRIPTS / "check_copy.py", *args, expect=1)
    run(SCRIPTS / "build_copy.py", *args, "--sku", "SECOND-SKU", expect=1)
    first, second = read_csv(outputs["mult_sku"])
    assert first["sku"] == "SMOKE-SKU" and second["sku"] == "SECOND-SKU"
    assert second["bullet5"] == "" and second["search_terms"] == data["search_terms"]

    run(SCRIPTS / "score_copy.py", *args, "--offline")
    assert not raw.exists()
    invalid_tool = tmp_path / "invalid_tool.py"
    invalid_tool.write_text('print("bad report")\n', encoding="utf-8")
    config["score"]["tool"] = str(invalid_tool)
    write_config(copy_config, config)
    write_json(raw, {})
    assert "评分失败" in run(SCRIPTS / "score_copy.py", *args)
    assert not raw.exists()
