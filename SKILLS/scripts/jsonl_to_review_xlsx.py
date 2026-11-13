#!/usr/bin/env python3
"""把 MCP `review` 抓下来的紧凑 JSONL 落成 vendor/amz-review-analysis 认的评论 xlsx。

JSONL 每行一个对象，字段：
    asin, t(标题), c(内容), s(星级), d(评论时间ms), a(评论人),
    k(skus 合并串), l(赞同数), v(verified), vi(vine), img(图片 url 数组)

输出: <out-dir>/<ASIN>-US-<n>.xlsx
文件名形如 <ASIN>-US-<n>.xlsx，因为 merge_reviews.py 用 `文件名.split('-')[0]` 当 listing ASIN。

字段缺口（MCP 拿不到，落空值）：
    评论链接 / 评论人主页 / 头像地址 / 所属国家 / 红人计划链接 / 无图时的图片地址
merge_reviews.py 对空评论链接有 sha1 兜底；空 所属国家 不会被误判成非美。

用法:
    python jsonl_to_review_xlsx.py --jsonl a.jsonl b.jsonl --out-dir "2 Reviews"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import openpyxl

# 与 merge_reviews.py 的 REVIEW_COLS 对齐
REVIEW_COLS = [
    "ASIN",
    "标题",
    "标题(翻译)",
    "内容",
    "内容(翻译)",
    "VP评论",
    "Vine Voice评论",
    "型号",
    "星级",
    "赞同数",
    "图片数量",
    "图片地址",
    "是否有视频",
    "视频地址",
    "评论链接",
    "评论人",
    "头像地址",
    "所属国家",
    "评论人主页",
    "红人计划链接",
    "评论时间",
]


def ms_to_date(v) -> str:
    if not v:
        return ""
    try:
        return dt.datetime.utcfromtimestamp(int(v) / 1000).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return ""


def to_row(rec: dict) -> list:
    imgs = rec.get("img") or []
    n_img = len(imgs)
    return [
        rec.get("asin", ""),
        (rec.get("t") or "").strip(),
        "",
        (rec.get("c") or "").strip(),
        "",
        "Y" if rec.get("v") else "",
        "Y" if rec.get("vi") else "",
        rec.get("k") or "",
        rec.get("s"),
        rec.get("l") or 0,
        n_img,
        " | ".join(imgs),
        "Y" if rec.get("video") else "",
        "",
        "",  # 评论链接：MCP 不返回
        rec.get("a") or "",
        "",
        "",  # 所属国家：留空
        "",
        "",
        ms_to_date(rec.get("d")),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    by_asin: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for p in args.jsonl:
        for line in Path(p).expanduser().read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec.get("asin"), rec.get("t"), rec.get("c"), rec.get("d"))
            if key in seen:
                continue
            seen.add(key)
            by_asin.setdefault(rec["asin"], []).append(rec)

    total = 0
    for asin, recs in sorted(by_asin.items()):
        recs.sort(key=lambda r: (r.get("s") or 0, r.get("d") or 0))
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "US"
        ws.append(REVIEW_COLS)
        for rec in recs:
            ws.append(to_row(rec))
        out = out_dir / f"{asin}-US-{len(recs)}.xlsx"
        wb.save(out)
        wb.close()
        total += len(recs)
        stars: dict[int, int] = {}
        for r in recs:
            stars[r.get("s") or 0] = stars.get(r.get("s") or 0, 0) + 1
        st = " ".join(f"{k}★{v}" for k, v in sorted(stars.items(), reverse=True))
        print(f"{asin}: {len(recs):>3} 条 [{st}] -> {out.name}")
    print(f"\n合计 {total} 条 / {len(by_asin)} 个 ASIN")


if __name__ == "__main__":
    main()
