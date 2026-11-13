#!/usr/bin/env python3
"""从竞品 ASIN 库 CSV 生成 merge_reviews.py 认的产品表 xlsx。

merge_reviews.load_products() 优先读名为 "US" 的 sheet，并按 PRODUCT_KEEP
的 12 个列名取值；本脚本把库里能拿到的字段映射过去，拿不到的空着。

用法:
    python build_products_xlsx.py --csv <01-竞品ASIN库.csv> --out <1 Products/US.xlsx>
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import openpyxl

# 与 merge_reviews.py 的 PRODUCT_KEEP 左键对齐
COLUMNS = [
    "ASIN",
    "品牌",
    "商品标题",
    "父ASIN",
    "价格($)",
    "小类BSR",
    "月销量",
    "月销售额($)",
    "评分",
    "评分数",
    "#",
    "上架时间",
    # 以下为自留字段，merge_reviews 不读，但方便回查分层
    "层级",
    "安装方式",
]


def num(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--asins", default="", help="逗号分隔；给了就只导这些 ASIN")
    ap.add_argument(
        "--overrides",
        default="",
        help="JSON 文件，补库里缺的字段，形如 {ASIN: {brand, ratings, rating, price, bsr}}",
    )
    args = ap.parse_args()

    src = Path(args.csv).expanduser().resolve()
    keep = {a.strip() for a in args.asins.split(",") if a.strip()}
    ov = {}
    if args.overrides:
        ov = json.loads(Path(args.overrides).expanduser().read_text(encoding="utf-8"))

    rows = []
    with src.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            asin = (r.get("asin") or "").strip()
            if not asin:
                continue
            if keep and asin not in keep:
                continue
            o = ov.get(asin, {})
            rows.append(
                [
                    asin,
                    (r.get("brand") or "").strip() or o.get("brand", ""),
                    (r.get("title") or "").strip(),
                    "",
                    num(r.get("price")) or o.get("price"),
                    o.get("bsr", ""),
                    num(r.get("monthly_units")),
                    "",
                    o.get("rating", ""),
                    num(r.get("ratings")) or o.get("ratings"),
                    "",
                    "",
                    (r.get("layer") or "").strip(),
                    (r.get("mount") or "").strip(),
                ]
            )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "US"
    ws.append(COLUMNS)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "B2"

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"products={len(rows)} -> {out}")


if __name__ == "__main__":
    main()
