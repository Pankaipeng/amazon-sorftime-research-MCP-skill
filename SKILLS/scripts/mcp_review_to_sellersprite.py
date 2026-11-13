#!/usr/bin/env python3
"""把卖家精灵 MCP `review` 的返回 JSON 落成 vendor/amz-review-analysis 认可的评论 xlsx。

用法:
    python mcp_review_to_sellersprite.py --raw-dir <raw> --out-dir <2 Reviews>

raw 目录下每个 *.json 是一次 MCP review 调用的完整返回，文件名需形如
    <ASIN>__<star|all>__<page>.json
脚本会把同一 ASIN 的多份返回合并成一份 xlsx，文件名 <ASIN>-US-<n>.xlsx，
因为 merge_reviews.py 用 `文件名.split('-')[0]` 作为 listing ASIN。

字段缺口（MCP 拿不到，落空值）:
    评论链接 / 评论人主页 / 头像地址 / 所属国家 / 红人计划链接 / 图片地址(无图时)
merge_reviews.py 对空评论链接有 sha1 兜底，空 所属国家 不会被误判成非美。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import openpyxl

# merge_reviews.py 认的 19 个列，顺序与 REVIEW_COLS 对齐
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


def join_skus(skus) -> str:
    if not skus:
        return ""
    if isinstance(skus, str):
        return skus
    return " / ".join(str(s) for s in skus if s)


def image_urls(images) -> tuple[int, str]:
    if not images:
        return 0, ""
    urls = []
    for it in images:
        if isinstance(it, str):
            urls.append(it)
        elif isinstance(it, dict):
            for k in ("url", "imageUrl", "src", "large"):
                if it.get(k):
                    urls.append(str(it[k]))
                    break
    return len(urls), " | ".join(urls)


def to_row(asin: str, it: dict) -> dict:
    n_img, img_url = image_urls(it.get("images"))
    return {
        "ASIN": asin,
        "标题": (it.get("title") or "").strip(),
        "标题(翻译)": "",
        "内容": (it.get("content") or "").strip(),
        "内容(翻译)": "",
        "VP评论": "Y" if it.get("verified") else "",
        "Vine Voice评论": "Y" if it.get("vine") else "",
        "型号": join_skus(it.get("skus")),
        "星级": it.get("star"),
        "赞同数": it.get("likes") or 0,
        "图片数量": n_img,
        "图片地址": img_url,
        "是否有视频": "Y" if (it.get("video") or it.get("videos")) else "",
        "视频地址": "",
        "评论链接": "",  # MCP 不返回 permalink
        "评论人": it.get("author") or "",
        "头像地址": "",
        "所属国家": "",  # 空值不会被判成非美
        "评论人主页": "",
        "红人计划链接": "",
        "评论时间": ms_to_date(it.get("date")),
    }


def load_raw(raw_dir: Path) -> dict[str, list[dict]]:
    """按 ASIN 聚合所有 raw json，按 (标题,内容,日期) 去重。"""
    by_asin: dict[str, list[dict]] = {}
    seen: set[tuple] = set()
    for f in sorted(raw_dir.glob("*.json")):
        asin = f.name.split("__")[0]
        payload = json.loads(f.read_text(encoding="utf-8"))
        items = (payload.get("data") or {}).get("items") or []
        for it in items:
            key = (
                asin,
                (it.get("title") or "").strip(),
                (it.get("content") or "").strip(),
                it.get("date"),
            )
            if key in seen:
                continue
            seen.add(key)
            by_asin.setdefault(asin, []).append(it)
    return by_asin


def write_xlsx(asin: str, items: list[dict], out_dir: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "US"
    ws.append(REVIEW_COLS)
    for it in items:
        row = to_row(asin, it)
        ws.append([row.get(c, "") for c in REVIEW_COLS])
    out = out_dir / f"{asin}-US-{len(items)}.xlsx"
    wb.save(out)
    wb.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    by_asin = load_raw(raw_dir)
    total = 0
    for asin, items in sorted(by_asin.items()):
        items.sort(key=lambda x: (x.get("star") or 0))
        out = write_xlsx(asin, items, out_dir)
        stars = {}
        for it in items:
            s = it.get("star") or 0
            stars[s] = stars.get(s, 0) + 1
        total += len(items)
        st = " ".join(f"{k}★{v}" for k, v in sorted(stars.items(), reverse=True))
        print(f"{asin}: {len(items):>3} 条 [{st}] -> {out.name}")
    print(f"\n合计 {total} 条 / {len(by_asin)} 个 ASIN -> {out_dir}")


if __name__ == "__main__":
    main()
