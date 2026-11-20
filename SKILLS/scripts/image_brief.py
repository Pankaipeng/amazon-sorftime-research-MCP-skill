#!/usr/bin/env python3
"""Build and verify the module 60 designer workbook from its original template."""

import argparse
from copy import copy
import hashlib
import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.drawing.image import Image

from csv_io import read_csv
from fact_provenance import outer_dimensions_from_packaging
from numeric_claims import SIZE, TRIPLE, bottle_issues, dimension_issues, fact_at


TEMPLATE = Path(__file__).resolve().parents[1] / "modules/60-image-brief/templates/image-design-brief.xlsx"
ROW_FIELDS = ("name", "pixels", "style", "goal", "selling_point", "copy",
              "design", "evidence", "acceptance")
EXPERIMENT_FIELDS = ("hypothesis", "variable", "controls", "baseline", "minimum_change",
                     "metrics", "sample_or_end", "decision", "status")
MAIN_REQUIREMENTS = {
    "white_rgb", "fill", "actual_item", "complete_frame", "single_view",
    "no_overlay", "included_only",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text_fields(value, fields, label):
    require(isinstance(value, dict), f"{label}须为对象")
    for field in fields:
        require(isinstance(value.get(field), str) and value[field].strip(), f"{label}缺 {field}")


def load_inputs(path):
    def relative(name):
        return path.parent / name

    spec = json.loads(path.read_text(encoding="utf-8-sig"))
    text_fields(spec, ("sku", "marketplace", "facts", "image_manifest"), "Brief")
    facts = json.loads(relative(spec["facts"]).read_text(encoding="utf-8-sig"))
    fact_sku = facts.get("sku") or (facts.get("meta") or {}).get("sku")
    require(fact_sku == spec["sku"], "事实卡 SKU 与 Brief 不一致")
    manifest = relative(spec["image_manifest"])
    index = {}
    for item in read_csv(manifest):
        if item["status"] != "ok":
            continue
        key = (item["marketplace"], item["asin"], int(item["pos"]))
        require(key not in index, f"竞品图清单重复 {key}")
        index[key] = item
    return spec, facts, index, manifest.parent.resolve()


def reference_image(row, spec, index, root):
    ref = row.get("reference")
    text_fields(ref, ("asin", "technique"), row["name"] + "竞品参考")
    pos = ref.get("position")
    require(type(pos) is int and pos > 0, f"{row['name']}的竞品图位无效")
    key = (spec["marketplace"], ref["asin"], pos)
    record = index.get(key)
    caption = f"{key[0]} {key[1]}#图{key[2]}\n{ref['technique']}"
    if not record:
        require(ref.get("status") in {"待补", "待核"}, f"无有效竞品原图 {key}")
        text_fields(ref, ("note",), "参考图缺口")
        return f"{caption}\n{ref['status']} · {ref['note']}", None
    require(ref.get("status") not in {"待补", "待核"}, f"已有竞品原图 {key}，须嵌入")
    image = (root / record["file"]).resolve()
    require(image.is_relative_to(root) and image.is_file(), f"无本地竞品原图 {key}")
    checksum = record.get("sha256")
    if checksum:
        require(hashlib.sha256(image.read_bytes()).hexdigest() == checksum, f"竞品图摘要不符 {key}")
    return caption, image


def validated_rows(spec, facts, index, images_root):
    rows = spec.get("rows")
    require(isinstance(rows, list) and 8 <= len(rows) <= 10, "需要 7–9 个正式图位及独立 MAIN B")
    require(all(isinstance(row, dict) for row in rows), "每个图位须为对象")
    require([row.get("slot") for row in rows] == [*range(1, len(rows)), None]
            and all(type(row.get("slot")) is int for row in rows[:-1]), "正式图位须连续，仅 MAIN B 不计数")
    kinds = [row.get("kind") for row in rows]
    require(kinds[0] == "main_a" and kinds[-1] == "main_b", "首行 MAIN A、末行独立 MAIN B")
    allowed = {"scenario", "feature", "dimensions", "package", "dimensions_and_package"}
    require(not (set(kinds[1:-1]) - allowed), "存在未知副图类型")
    require(kinds.count("scenario") == 1, "须有一张无字核心场景")
    combined = kinds.count("dimensions_and_package") == 1 and not ({"dimensions", "package"} & set(kinds))
    split = kinds.count("dimensions") == kinds.count("package") == 1 and "dimensions_and_package" not in kinds
    require(combined or split, "尺寸和清单须合图一次或各一张")
    require((4 if combined else 3) <= kinds.count("feature") <= (6 if combined else 5), "自由卖点图配额错误")

    experiments = spec.get("experiments") or {}
    for kind in ("main", "secondary"):
        text_fields(experiments.get(kind), EXPERIMENT_FIELDS, kind + "验证计划")
    decisions = spec.get("decisions")
    require(isinstance(decisions, list) and decisions, "缺图片侧与文案侧取舍")
    for decision in decisions:
        text_fields(decision, ("sp_id", "copy_candidate", "image_candidate",
                               "decision", "validation"), "图文取舍")
        require(isinstance(decision.get("evidence"), dict)
                and set(decision["evidence"]) == {"image", "review", "bullet"}
                and all(isinstance(decision["evidence"][k], str) and decision["evidence"][k].strip()
                        for k in decision["evidence"]), "须交代图片、评论、五点三路证据")
        levels = decision.get("levels")
        require(isinstance(levels, list) and len(levels) == 3
                and all(type(x) is int and 0 <= x <= 2 for x in levels), "证据等级须分别为 0–2")

    result = []
    for row in rows:
        text_fields(row, ROW_FIELDS, f"图位 {row.get('slot')}")
        require(re.fullmatch(r"[1-9]\d*\s*[×x]\s*[1-9]\d*", row["pixels"]), "图片像素格式无效")
        require("手机" in row["acceptance"], f"{row['name']}缺手机端验收")
        if row["kind"] in {"main_a", "main_b", "scenario"}:
            require(row["copy"].strip() == "无", f"{row['name']}须无字")
        if row["kind"] in {"main_a", "main_b"} and spec["marketplace"] == "US":
            require(set(row.get("main_checks", [])) == MAIN_REQUIREMENTS,
                    f"{row['name']}缺美国站 MAIN 检查项")
        copy_text = row["copy"]
        has_dimensions = SIZE.search(copy_text) or TRIPLE.search(copy_text)
        if row["kind"] in {"dimensions", "dimensions_and_package"}:
            require(has_dimensions, f"{row['name']}缺图片尺寸单位与数值")
        if has_dimensions:
            require(all(fact_at(facts, "dims.outer_in." + axis) is not None for axis in "lwh")
                    and not outer_dimensions_from_packaging(facts), f"{row['name']}缺商品实测尺寸")
        problems = dimension_issues(copy_text, facts) + bottle_issues(copy_text, facts)
        require(not problems, f"{row['name']}数字主张不一致：{'、'.join(problems)}")
        caption, image = reference_image(row, spec, index, images_root)
        result.append((row, caption, image))
    return result


def sheet_values(spec, row, caption):
    return [row["slot"], row["name"], spec["sku"], row["pixels"], row["style"],
            row["goal"], row["selling_point"], row["copy"], row["design"],
            row["evidence"], caption, row["acceptance"]]


def footer_lines(spec):
    lines = ["文案与图片候选对照 · 证据顺序为图片 / 评论 / 五点 · 50/30/20 与 40/40/20"]
    for item in spec["decisions"]:
        scores = [sum(n * w for n, w in zip(item["levels"], weights)) / 2
                  for weights in ((50, 30, 20), (40, 40, 20))]
        lines.append(
            f"{item['sp_id']} · 文案 {item['copy_candidate']} · 图片 {item['image_candidate']}\n"
            f"证据 {' / '.join(item['evidence'][k] for k in ('image', 'review', 'bullet'))} · "
            f"等级 {item['levels']} · 得分 {scores[0]:g} / {scores[1]:g}\n"
            f"取舍 {item['decision']} · 验证 {item['validation']}"
        )
    for key, label in (("main", "MAIN A/B 验证"), ("secondary", "副图顺序验证")):
        item = spec["experiments"][key]
        lines.append(label + "\n" + " · ".join(item[field] for field in EXPERIMENT_FIELDS))
    lines.append("Brief 文件验收、实际成图验收、线上指标验证分别记录。")
    return lines


def workbook_rows(rows):
    return [*zip(range(5, 5 + len(rows) - 1), rows[:-1]), (22, rows[-1])]


def check_workbook(path, spec, rows):
    require(path.suffix.lower() == ".xlsx", "正式交付必须使用 Excel 模板")
    with TEMPLATE.open("rb") as template_stream, path.open("rb") as workbook_stream:
        template = load_workbook(template_stream)
        workbook = load_workbook(workbook_stream)
        try:
            sheet = workbook.active
            require(sheet.title == template.active.title and
                    [x.value for x in sheet[4]] == [x.value for x in template.active[4]], "模板表名或列被更改")
            require(sheet["D3"].value == "=COUNT(A5:A13)", "正式图数公式丢失")
            require([sheet[f"A{i}"].value for i in range(5, 14)] ==
                    [*range(1, len(rows)), *[None] * (10 - len(rows))], "正式图数或轮替稿计数错误")
            row_slots = workbook_rows(rows)
            require(len(sheet._images) == sum(original is not None for _, _, original in rows),
                    "竞品参考缩略图未全部嵌入")
            images = {(i.anchor._from.row + 1, i.anchor._from.col + 1): i for i in sheet._images}
            for n, (row, caption, original) in row_slots:
                actual = [sheet.cell(n, col).value for col in range(1, 13)]
                require(actual == sheet_values(spec, row, caption), f"图位行 {n} 与已审核输入不一致")
                image = images.get((n, 11))
                if original is not None:
                    require(image is not None and image._data() == original.read_bytes(),
                            f"图位行 {n} 的参考图缺失或串图")
                else:
                    require(image is None, f"图位行 {n} 标为待补却放入来源未核的图")
            for n, line in enumerate(footer_lines(spec), 24):
                require(sheet[f"A{n}"].value == line, f"表尾取舍或验证计划第 {n} 行缺失")
        finally:
            workbook.close()
            template.close()


def build_workbook(path, spec, rows):
    require(path.suffix.lower() == ".xlsx", "正式交付必须使用 Excel 模板")
    workbook = load_workbook(TEMPLATE)
    sheet = workbook.active
    sheet["A1"] = f"{spec['sku']} | {spec['marketplace']} 图片设计 Brief"
    sheet["A2"] = "正式图片与 MAIN B 分开计数。逐图要求、竞品参考与验收见对应行。"
    for n in range(5, 14):
        for col in range(1, 13):
            sheet.cell(n, col).value = None
    for n, (row, caption, original) in workbook_rows(rows):
        sheet.row_dimensions[n].height = 125
        for col, value in enumerate(sheet_values(spec, row, caption), 1):
            cell = sheet.cell(n, col)
            if n == 22:
                # MAIN B uses the existing MAIN A row style.
                cell._style = copy(sheet.cell(5, col)._style)
            cell.value = value
            if isinstance(value, str):
                cell.data_type = "s"
        if original is not None:
            img = Image(original)
            scale = 90 / max(img.width, img.height)
            img.width, img.height = max(1, round(img.width * scale)), max(1, round(img.height * scale))
            sheet.add_image(img, f"K{n}")
        alignment = copy(sheet[f"K{n}"].alignment)
        alignment.vertical = "bottom"
        sheet[f"K{n}"].alignment = alignment
    for n, line in enumerate(footer_lines(spec), 24):
        sheet.merge_cells(start_row=n, start_column=1, end_row=n, end_column=12)
        cell = sheet.cell(n, 1)
        cell.value = line
        cell._style = copy(sheet["A17"]._style)
        sheet.row_dimensions[n].height = 58
    for column, width in {"B": 16, "G": 23, "H": 26, "I": 40, "J": 26, "K": 21, "L": 41}.items():
        sheet.column_dimensions[column].width = max(width, sheet.column_dimensions[column].width)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(suffix=".xlsx", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        workbook.save(staged)
        check_workbook(staged, spec, rows)
        staged.replace(path)
    finally:
        workbook.close()
        staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    args = parser.parse_args()
    try:
        spec, facts, index, root = load_inputs(args.spec)
        rows = validated_rows(spec, facts, index, root)
        if args.command == "build":
            build_workbook(args.workbook, spec, rows)
        else:
            check_workbook(args.workbook, spec, rows)
    except (ValueError, OSError, KeyError, TypeError, BadZipFile) as error:
        print(f"FAIL · {error}")
        return 1
    references = sum(original is not None for _, _, original in rows)
    print(f"PASS · {len(rows)-1} 个正式图位，MAIN B 单列，{references} 张竞品参考缩略图"
          f"，{len(rows)-references} 个参考图缺口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
