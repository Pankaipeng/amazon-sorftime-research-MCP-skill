#!/usr/bin/env python3
"""Collect read-only SellerSprite traffic/review pages and reconcile unique rows."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def identity(tool, item):
    if tool == "traffic_keyword":
        return str(item.get("keyword") or "").strip().casefold()
    review_id = item.get("reviewId") or item.get("id")
    if review_id:
        return str(review_id)
    fields = ("title", "content", "date", "star", "author")
    values = [str(item.get(key) or "").strip() for key in fields]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest() if any(values) else ""


def page_arguments(tool, filters, page, page_size):
    args = {**filters, "page": page, "size": page_size}
    return {"request": args} if tool == "traffic_keyword" else args


def collect_pages(call, tool, filters, max_pages, page_size, existing):
    received = 0
    totals = []
    pages = []
    seen = set()
    unchanged = 0
    stop = "page_budget"
    for page in range(1, max_pages + 1):
        args = page_arguments(tool, filters, page, page_size)
        response = call(tool, args)
        data = response.get("data") if isinstance(response, dict) and response.get("code") == "OK" else None
        if not isinstance(data, dict):
            pages.append({"page": page, "status": "api_error"})
            stop = "api_error"
            break
        total = data.get("total")
        if type(total) is int and total >= 0:
            totals.append(total)
        items = data.get("items")
        if items is None and total == 0:
            items = []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            pages.append({"page": page, "status": "bad_payload"})
            stop = "bad_payload"
            break
        received += len(items)
        before = len(seen)
        global_before = len(existing)
        for position, item in enumerate(items, 1):
            key = identity(tool, item)
            if key:
                seen.add(key)
                existing.setdefault(key, {**item, "_page": page, "_in_page": position,
                                          "_filter": filters.get("keyword", "")})
        added = len(seen) - before
        pages.append({"page": page, "reported_total": total, "received": len(items),
                      "new_unique": added, "new_in_union": len(existing) - global_before})
        if totals and len(seen) >= max(totals):
            stop = "reconciled"
            break
        if not items:
            stop = "empty_page"
            break
        unchanged = 0 if added else unchanged + 1
        if unchanged >= 2:
            stop = "repeated_page"
            break
        if data.get("hasNextPage") is False:
            stop = "api_end"
            break
    return {"filters": filters, "requested_page_size": page_size, "reported_totals": sorted(set(totals)),
            "api_total": max(totals, default=None), "received": received, "unique": len(seen),
            "stop": stop, "pages": pages}


def collect(call, tool, filters, max_pages, page_size, roots=()):
    rows = {}
    base = collect_pages(call, tool, filters, max_pages, page_size, rows)
    extra = []
    total = base["api_total"]
    if tool == "traffic_keyword" and base["stop"] not in {"reconciled", "api_error", "bad_payload"}:
        for root in dict.fromkeys(roots):
            if total is not None and len(rows) >= total:
                break
            extra.append(collect_pages(call, tool, {**filters, "keyword": root}, max_pages, page_size, rows))
    gap = max(0, total - len(rows)) if total is not None else None
    status = "complete" if len(rows) == total and len(base["reported_totals"]) == 1 and base["stop"] not in {
        "api_error", "bad_payload"
    } else "partial"
    return list(rows.values()), {"tool": tool, "status": status, "api_total": total,
                                  "received": base["received"] + sum(x["received"] for x in extra),
                                  "unique": len(rows), "gap": gap, "base": base, "fallback": extra}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transcript_call(path):
    records = json.loads(path.read_text(encoding="utf-8-sig"))
    index = {(r["tool"], json.dumps(r["arguments"], sort_keys=True)): r["response"] for r in records}
    if len(index) != len(records):
        raise ValueError("MCP 回放含重复请求")

    def call(tool, args):
        return index.get((tool, json.dumps(args, sort_keys=True)), {"error": "missing replay page"})
    return call


def live_call():
    location = Path(__file__).resolve().parents[1] / "skills/sellersprite-amazon-research/scripts"
    sys.path.insert(0, str(location))
    from mcp_call import call_tool
    return call_tool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tool", choices=("traffic_keyword", "review"), required=True)
    parser.add_argument("--month", help="固定月 yyyyMM，默认保持接口近期窗口")
    parser.add_argument("--stars", type=int, nargs="+", choices=range(1, 6))
    parser.add_argument("--root", action="append", default=[], help="基础分页不足时，用同口径词根补查")
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--transcript", type=Path)
    args = parser.parse_args()
    size = args.page_size if args.page_size is not None else (100 if args.tool == "traffic_keyword" else 20)
    if args.max_pages < 1 or not 1 <= size <= (100 if args.tool == "traffic_keyword" else 20):
        parser.error("页数或页长无效")
    if args.month and (args.tool != "traffic_keyword" or not re.fullmatch(r"\d{4}(?:0[1-9]|1[0-2])", args.month)):
        parser.error("固定月份仅用于流量词，格式 yyyyMM")
    if (args.stars and args.tool != "review") or (args.root and args.tool != "traffic_keyword"):
        parser.error("评论使用 --stars，流量词使用 --root")
    if not args.transcript and not os.environ.get("SELLERSPRITE_API_KEY"):
        parser.error("设置 SELLERSPRITE_API_KEY 或传入已授权 MCP 回放 --transcript")
    source = json.loads(args.groups.read_text(encoding="utf-8-sig"))
    marketplace = source["marketplace"]
    entries = [(asin, group) for group, asins in source["groups"].items() for asin in asins]
    groups = dict(entries)
    if not groups or len(groups) != len(entries) or any(not re.fullmatch(r"[A-Z0-9]{10}", asin) for asin in groups):
        parser.error("缺竞品 ASIN、格式错误或同一 ASIN 重复分组")
    args.out.mkdir(parents=True, exist_ok=True)
    call = transcript_call(args.transcript) if args.transcript else live_call()
    ledger = []
    output_rows = []
    for asin, group in groups.items():
        filters = {"asin": asin, "marketplace": marketplace}
        if args.tool == "traffic_keyword":
            filters["order"] = {"field": "trafficPercentage", "desc": True}
            if args.month:
                filters["month"] = args.month
        elif args.stars:
            filters["starList"] = sorted(set(args.stars))
        rows, summary = collect(call, args.tool, filters, args.max_pages, size, args.root)
        ledger.append({"asin": asin, "group": group, **summary})
        if args.tool == "review":
            band = "-".join(map(str, filters.get("starList", []))) or "all"
            write_json(args.out / f"{asin}__{band}__1.json", {
                "code": "OK", "data": {"items": rows, "total": summary["api_total"]},
            })
        else:
            output_rows.extend({**row, "asin": asin, "group": group, "marketplace": marketplace,
                                "month": args.month or "recent"} for row in rows)

    band = "-".join(map(str, sorted(set(args.stars or [])))) or "all"
    suffix = f"review-{band}" if args.tool == "review" else "traffic"
    write_json(args.out / f"collection-{suffix}.json", {"marketplace": marketplace, "collections": ledger})
    if args.tool == "traffic_keyword":
        fields = ["asin", "group", "marketplace", "month", "keyword", "searches", "purchases",
                  "trafficPercentage", "_page", "_in_page", "_filter"]
        with (args.out / "0A-竞品流量词.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(output_rows)
    for row in ledger:
        print(f"{row['asin']} · {row['status']} · unique={row['unique']} / total={row['api_total']}"
              f" · gap={row['gap']} · stop={row['base']['stop']}")
    return 0 if all(row["status"] == "complete" for row in ledger) else 2


if __name__ == "__main__":
    raise SystemExit(main())
