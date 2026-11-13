#!/usr/bin/env python3
"""竞品标题 / 五点 / 描述 词频统计（带 ASIN 权重）。

输入：一个 JSON 文件，内容是产品数组：
[
  {
    "asin": "B0XXXXXXX",
    "level": 0,                     # 0 = 用户提供，1 = 关联一层，2 = 关联二层
    "title": "...",
    "bullets": ["...", "..."],       # 可选
    "description": "..."             # 可选
  }
]

用法：
  python freq.py products.json                       # 默认 L0 权重 3
  python freq.py products.json --weight-l0 3 --weight-other 1
  python freq.py products.json --min-asin 2          # 至少出现在 2 个 ASIN 里
  python freq.py products.json --out freq.csv

输出：CSV，列见 --help。
"""
import argparse
import csv
import io
import json
import math
import re
import sys
from collections import defaultdict

# 英文常见停用词（按需增补）
STOP = set("""
a an the and or but if then than that this these those of for with without to from by on in at as is are was were be been being
it its it's you your yours we our ours they their them he she his her
not no nor so very too also just only more most much many some any all each every
can could will would should may might must do does did doing done have has had having
get got make made use used using new good great best perfect easy
""".split())

# 这些泛词单独出现时信息量低，但组合成短语可能有用，所以只在 n>1 时保留
GENERIC = set("""
product products item items set pack pcs piece pieces kit style type design quality
""".split())

FIELD_WEIGHT = {"title": 3.0, "bullets": 2.0, "description": 1.0}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def normalize(text):
    text = (text or "").lower()
    text = text.replace("&amp;", " & ").replace("&quot;", '"')
    text = re.sub(r"[^a-z0-9' +\-/]", " ", text)
    text = text.replace("/", " ").replace("-", " ")
    return text


def ngrams(text, max_n=3):
    toks = [t for t in TOKEN_RE.findall(normalize(text)) if t not in STOP and len(t) > 1]
    out = []
    for n in range(1, max_n + 1):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i:i + n])
            if n == 1 and gram in GENERIC:
                continue
            out.append((gram, n))
    return out


def load(path):
    with io.open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "products" in data:
        data = data["products"]
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--weight-l0", type=float, default=3.0,
                    help="用户提供 ASIN 的权重（默认 3）")
    ap.add_argument("--weight-other", type=float, default=1.0,
                    help="其它竞品 ASIN 的权重（默认 1）")
    ap.add_argument("--max-n", type=int, default=3, help="最大词组长度（默认 3）")
    ap.add_argument("--min-asin", type=int, default=1,
                    help="至少出现在几个 ASIN 里才输出（默认 1）")
    ap.add_argument("--top", type=int, default=200, help="输出前 N 条（默认 200）")
    ap.add_argument("--out", help="输出 CSV 路径，不填则打印到屏幕")
    args = ap.parse_args()

    products = load(args.input)
    if not products:
        print("输入为空", file=sys.stderr)
        sys.exit(1)

    # gram -> field -> {weighted, raw, asins:set, l0:count}
    stats = defaultdict(lambda: defaultdict(lambda: {
        "weighted": 0.0, "raw": 0, "asins": set(), "l0_asins": set(), "n": 1
    }))
    n_asin = len(products)
    l0_asin = sum(1 for p in products if p.get("level", 1) == 0)

    for p in products:
        asin = p.get("asin", "?")
        w = args.weight_l0 if p.get("level", 1) == 0 else args.weight_other
        sources = []
        if p.get("title"):
            sources.append(("title", p["title"]))
        if p.get("bullets"):
            b = p["bullets"]
            sources.append(("bullets", " ".join(b) if isinstance(b, list) else str(b)))
        if p.get("description"):
            sources.append(("description", p["description"]))

        for field, text in sources:
            for gram, n in ngrams(text, args.max_n):
                cell = stats[gram][field]
                cell["weighted"] += w * FIELD_WEIGHT[field]
                cell["raw"] += 1
                cell["asins"].add(asin)
                if p.get("level", 1) == 0:
                    cell["l0_asins"].add(asin)
                cell["n"] = n

    rows = []
    for gram, fields in stats.items():
        total_weighted = sum(c["weighted"] for c in fields.values())
        all_asins = set()
        all_l0 = set()
        raw = 0
        for c in fields.values():
            all_asins |= c["asins"]
            all_l0 |= c["l0_asins"]
            raw += c["raw"]
        if len(all_asins) < args.min_asin:
            continue
        coverage = len(all_asins) / n_asin
        # 文档频率加权：覆盖越广的词越像"行业通用词"
        idf = math.log((n_asin + 1) / (len(all_asins) + 1)) + 1
        rows.append({
            "word": gram,
            "n_gram": fields[next(iter(fields))]["n"],
            "weighted_score": round(total_weighted * idf, 2),
            "raw_count": raw,
            "asin_count": len(all_asins),
            "coverage": round(coverage, 3),
            "l0_asin_count": len(all_l0),
            "in_title": round(fields.get("title", {}).get("weighted", 0), 1),
            "in_bullets": round(fields.get("bullets", {}).get("weighted", 0), 1),
            "in_description": round(fields.get("description", {}).get("weighted", 0), 1),
        })

    rows.sort(key=lambda r: r["weighted_score"], reverse=True)
    rows = rows[:args.top]

    header = ["word", "n_gram", "weighted_score", "raw_count", "asin_count",
              "coverage", "l0_asin_count", "in_title", "in_bullets", "in_description"]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=header)
    w.writeheader()
    for r in rows:
        w.writerow(r)

    text = out.getvalue()
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(text)
        print(f"已写入 {args.out}（{len(rows)} 条）")
        print(f"样本：{n_asin} 个 ASIN，其中用户提供 {l0_asin} 个，"
              f"L0 权重 {args.weight_l0} / 其它 {args.weight_other}")
    else:
        print(text)


if __name__ == "__main__":
    main()
