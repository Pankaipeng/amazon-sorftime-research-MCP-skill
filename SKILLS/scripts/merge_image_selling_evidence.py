"""Merge reviewed secondary-image evidence into an existing selling-point library."""

import argparse
import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from csv_io import read_csv


def write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evidence_path(source, output):
    source = source.resolve()
    output = output.resolve()
    if source.drive.casefold() != output.drive.casefold():
        return source.as_posix()
    return Path(os.path.relpath(source, output)).as_posix()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("base", "secondary", "manifest", "plan", "out"):
        parser.add_argument(f"--{flag}", required=True, type=Path)
    args = parser.parse_args()
    if args.out.resolve() == args.base.resolve():
        parser.error("Use a separate output directory")
    library = read_csv(args.base / "SP-01-卖点库_v2.csv")
    facts = {r["sp_id"]: r for r in read_csv(args.base / "SP-10-FAB卖点卡.csv")}
    original = read_csv(args.base / "SP-02-证据链.csv")
    plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
    sp_ids = {row["sp_id"] for row in library}
    if not plan or any(not entry["sp_ids"] for entry in plan):
        raise ValueError("Each image task needs a primary selling-point ID")
    ranked = [sid for entry in plan for sid in entry["sp_ids"]]
    if len(ranked) != len(set(ranked)) or not set(ranked) <= sp_ids & facts.keys():
        raise ValueError("Image plan contains duplicate or unknown selling-point IDs")
    manifest = {(r["marketplace"], r["asin"], r["pos"], r["file"]): r
                for r in read_csv(args.manifest) if r["status"] == "ok" and r["slot"] == "副图"}
    rows = read_csv(args.secondary)
    seen = set()
    image_by_id = defaultdict(list)
    reviewed = set()
    image_root = args.manifest.parent.resolve()
    for row in rows:
        key = tuple(row[k] for k in ("marketplace", "asin", "pos", "file"))
        if key not in manifest or int(row["副图位次"]) != int(row["pos"]) - 1:
            raise ValueError(f"Invalid secondary image locator: {key}")
        source = (image_root / row["file"]).resolve()
        if not source.is_relative_to(image_root) or not source.is_file():
            raise ValueError(f"Invalid evidence file for {key}")
        expected_digest = manifest[key].get("sha256")
        if key not in reviewed and expected_digest:
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != expected_digest.lower():
                raise ValueError(f"Evidence hash mismatch for {key}")
        reviewed.add(key)
        if row["展示任务"] != "卖点转化" or not row["SP_ID"].strip():
            continue
        tagged = re.fullmatch(r"(SP\d+)(?:（[^）]+）)?", row["SP_ID"].strip())
        if not tagged or tagged[1] not in sp_ids:
            raise ValueError(f"Unknown selling-point mapping: {row['SP_ID']}")
        sid = tagged[1]
        record_key = (sid, key, row["主题"])
        if record_key in seen:
            continue
        seen.add(record_key)
        row = dict(row, 原图=evidence_path(source, args.out))
        image_by_id[sid].append(row)
    image_denominator = len({(key[0], key[1]) for key in reviewed})
    if not image_denominator:
        raise ValueError("No reviewed secondary images")

    def location(row):
        return f"{row['marketplace']} {row['asin']}#图{row['pos']}（副图{row['副图位次']}）"

    extra = ("主题", "原图", "画面事实", "竞品声称", "视觉证据", "本品核验", "效果状态")
    ledger = [dict(row, **{field: "" for field in extra}) for row in original if row["维度"] != "图片"]
    summaries = []
    for point in library:
        sid = point["sp_id"]
        hits = image_by_id[sid]
        card = facts[sid]
        for row in hits:
            ledger.append(dict(sp_id=sid, 卖点名=point["卖点名"], 维度="图片", 来源类型="keepa_info 副图判读",
                               **{"来源文件/sheet": args.secondary.name, "定位": location(row),
                                  "原文/计数": row["竞品声称"] or row["画面事实"]}, n=1, confidence="JUDGED",
                               **{field: row[field] for field in extra}))
        locators = list(dict.fromkeys(location(row) for row in hits))
        first_by_asin = {}
        for row in sorted(hits, key=lambda row: int(row["副图位次"])):
            first_by_asin.setdefault((row["marketplace"], row["asin"]), location(row))
        if locators:
            card["市场证据定位"] += " / 图片 " + " / 图片 ".join(locators)
        summaries.append(dict(point, 图片观察条数=len(hits),
                              图片覆盖=f"{len({(r['marketplace'], r['asin']) for r in hits})}/{image_denominator}",
                              前三张副图覆盖=f"{len({(r['marketplace'], r['asin']) for r in hits if int(r['副图位次']) <= 3})}/{image_denominator}",
                              图片主题=" / ".join(dict.fromkeys(row["主题"] for row in hits)),
                              图片首次图位=" / ".join(first_by_asin.values()),
                              图片证据定位=" / ".join(locators),
                              图片观察状态="有映射" if hits else "样本中未记录可映射证据",
                              本品使用状态=card["使用状态"], 本品事实=card["本品事实"]))

    order = []
    checks = []
    for rank, entry in enumerate(plan, 1):
        ids = entry["sp_ids"]
        evidence = " / ".join(f"{sid} {row['图片覆盖']}" for sid in ids for row in summaries if row["sp_id"] == sid)
        order.append(dict(优先级=rank, 主卖点=ids[0], 支撑卖点=" / ".join(ids[1:]),
                          图片任务=entry["task"], 副图覆盖=evidence, 排序依据=entry["why"], 状态="待确认排序"))
        for sid in ids:
            card = facts[sid]
            checks.append(dict(优先级=rank, sp_id=sid, 图片任务=entry["task"],
                               市场证据=card["市场证据定位"], 本品事实=card["本品事实"],
                               使用状态=card["使用状态"], 核对项=entry["checks"][sid],
                               验证缺口=card["验证缺口"], 自检结果="待图稿核验"))

    args.out.mkdir(parents=True, exist_ok=True)
    for name, output in (
        ("SP-01-卖点库-三路汇总.csv", summaries), ("SP-02-证据链.csv", ledger),
        ("SP-04-图片卖点排序.csv", order), ("SP-10-FAB卖点卡.csv", list(facts.values())),
        ("SP-11-图片卖点自检.csv", checks),
    ):
        write(args.out / name, output)


if __name__ == "__main__":
    main()
