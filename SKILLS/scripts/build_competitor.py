"""Build the offline competitor report from the ASIN, bullet and insight inputs."""

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl
import yaml

from build_selling_points import load_bullets, match_bullets, write_csv


def price_band(value, width):
    try:
        price = Decimal(value)
    except (InvalidOperation, TypeError):
        return ""
    if not price.is_finite() or price <= 0:
        return ""
    lower = price // width * width
    return f"[{lower:g}, {lower + width:g})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asin-pool", required=True, type=Path)
    parser.add_argument("--bullets", required=True, type=Path)
    parser.add_argument("--insight", required=True, type=Path)
    parser.add_argument("--marketplace", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--price-band-width", required=True, type=Decimal)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sp-config", type=Path, default=Path(__file__).with_name("sp_config.yaml"))
    args = parser.parse_args()
    if not args.price_band_width.is_finite() or args.price_band_width <= 0:
        parser.error("--price-band-width must be positive")

    with args.asin_pool.open(encoding="utf-8-sig", newline="") as stream:
        pool = {row["asin"]: row for row in csv.DictReader(stream) if row["asin"]}
    if not pool:
        parser.error("ASIN pool is empty")
    products = {row["asin"]: row for row in load_bullets(args.bullets) if row["asin"] in pool}
    definitions = yaml.safe_load(args.sp_config.read_text(encoding="utf-8"))["sp_defs"]
    themes = {asin: [] for asin in pool}
    excerpts = []
    for point in definitions:
        matches = match_bullets(
            products.values(), point.get("bullet_patterns", []), point.get("bullet_exclude_patterns", [])
        )
        for asin, positions in matches.items():
            themes[asin].append(point["id"])
            excerpts.extend(
                [asin, point["id"], point["name"], position, products[asin]["bullets"][position - 1],
                 args.bullets.name]
                for position in positions
            )

    insight = openpyxl.load_workbook(args.insight, read_only=True, data_only=True)
    pain_sheet = "06_竞品痛点_ASIN_L2"
    try:
        rows = insight[pain_sheet].values
        pain_header = next(rows)
        pains = [row for row in rows if row[0] in pool]
    finally:
        insight.close()
    comment_asins = {row[0] for row in pains}

    detail = []
    bands = Counter()
    for asin, item in pool.items():
        product = products.get(asin, {})
        band = price_band(item.get("price"), args.price_band_width)
        matched = len(themes[asin]) if product.get("bullets") else "缺五点"
        bands[(band or "缺价", item.get("layer", ""), matched)] += 1
        detail.append([
            asin, args.marketplace, item.get("layer", ""), item.get("brand") or product.get("brand", ""),
            item.get("mount") or product.get("mount", ""), item.get("title") or product.get("title", ""),
            item.get("price") if band else "", args.currency, band, item.get("monthly_units", ""),
            item.get("ratings", ""), len(product.get("bullets", [])), " / ".join(themes[asin]),
            "有痛点记录" if asin in comment_asins else "无匹配痛点记录", args.asin_pool.name,
        ])

    write_csv(args.out / "竞品拆解.csv",
              ["ASIN", "站点", "竞品层级", "品牌", "安装定位", "标题", "价格快照", "币种", "价格带",
               "月销量", "评分数", "五点原句数", "五点命中卖点ID", "评论痛点覆盖", "竞品数据来源"], detail)
    write_csv(args.out / "五点证据.csv", ["ASIN", "卖点ID", "卖点口径", "五点位置", "原文", "来源"], excerpts)
    write_csv(args.out / "价格带竞争分布.csv", ["价格带", "竞品层级", "五点命中卖点数", "ASIN数", "币种"],
              ([*key, count, args.currency] for key, count in bands.items()))
    write_csv(args.out / "竞品痛点.csv", [*pain_header, "来源"], (
        [*row, f"{args.insight.name} / {pain_sheet}"] for row in pains
    ))


if __name__ == "__main__":
    main()
