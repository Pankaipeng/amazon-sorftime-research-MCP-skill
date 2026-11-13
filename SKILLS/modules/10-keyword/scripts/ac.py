#!/usr/bin/env python3
"""Amazon 前台自动补全：生成请求清单 + 合并结果。

接口硬性每次只回 10 条，所以要靠前缀组合凑量。
方法来自 nexscope 的 amazon-keyword-research：
    原词 1 次 + best/cheap/top 前缀 3 次 + a-z 后缀 26 次 = 29 次 → 去重后约 100-200 词

两个子命令：

  1) 生成清单
     python ac.py plan --seed "coat rack" --marketplace US --out plan.json
     python ac.py plan --seed "coat rack" --marketplace US --mode fast --out plan.json

  2) 合并结果（把每次 web_fetch 拿到的 suggestions 收进一个 JSON 后跑）
     python ac.py merge --in results.json --out suggestions.csv

results.json 格式：
[
  {"prefix":"coat rack",   "position":1, "value":"coat rack"},
  {"prefix":"coat rack w", "position":1, "value":"coat rack wall mount"},
  ...
]
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict

MIDS = {
    "US": "ATVPDKIKX0DER",
    "UK": "A1F83G8C2ARO7P",
    "DE": "A1PA6795UKMFR9",
    "FR": "A13V1IB3VIYZZH",
    "IT": "APJ6JRA9NG5V4",
    "ES": "A1RKKUPIHCS9HS",
    "JP": "A1VC38T7YXB528",
}

# 未实测确认，不要默认使用
UNVERIFIED = {"CA", "AU", "IN", "MX", "BR", "AE"}


def build_prefixes(seed, mode="full"):
    """返回 [(标签, 前缀)]"""
    seed = seed.strip()
    items = [("原词", seed)]
    for p in ("best", "cheap", "top"):
        items.append((f"前缀:{p}", f"{p} {seed}"))
    letters = list("abcdefghijklmnopqrstuvwxyz")
    if mode == "fast":
        # 只取高信息量字母，单词首字母分布决定的经验值
        letters = list("swcmbpfhdt")
    for c in letters:
        items.append((f"后缀:{c}", f"{seed} {c}"))
    return items


def cmd_plan(args):
    mp = args.marketplace.upper()
    if mp in UNVERIFIED:
        print(f"⚠️ {mp} 的 mid 未实测确认，先别用", file=sys.stderr)
        sys.exit(2)
    mid = MIDS.get(mp)
    if not mid:
        print(f"未知站点 {mp}，已支持：{', '.join(MIDS)}", file=sys.stderr)
        sys.exit(2)

    items = build_prefixes(args.seed, args.mode)
    plan = []
    for label, prefix in items:
        from urllib.parse import quote
        url = (f"https://completion.amazon.com/api/2017/suggestions"
               f"?mid={mid}&alias=aps&prefix={quote(prefix)}")
        plan.append({"label": label, "prefix": prefix, "marketplace": mp, "url": url})

    payload = {"seed": args.seed, "marketplace": mp, "mode": args.mode,
               "count": len(plan), "requests": plan}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(text + "\n")
        print(f"已生成 {len(plan)} 条请求 → {args.out}")
        print(f"模式 {args.mode}，预计去重后 "
              f"{'100-200' if args.mode == 'full' else '40-80'} 个词")
    else:
        print(text)


def norm(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def cmd_merge(args):
    with io.open(args.input, encoding="utf-8") as f:
        rows = json.load(f)
    if isinstance(rows, dict) and "results" in rows:
        rows = rows["results"]

    agg = defaultdict(lambda: {"best_pos": 99, "hits": 0, "prefixes": set()})
    for r in rows:
        v = norm(r.get("value"))
        if not v:
            continue
        pos = int(r.get("position") or 99)
        a = agg[v]
        a["best_pos"] = min(a["best_pos"], pos)
        a["hits"] += 1
        a["prefixes"].add(r.get("prefix", ""))

    out_rows = []
    for v, a in agg.items():
        # 位次越靠前、被越多前缀命中 → 越可能是真实高频词
        score = round((11 - min(a["best_pos"], 10)) * 10 + len(a["prefixes"]) * 3, 1)
        out_rows.append({
            "keyword": v,
            "best_position": a["best_pos"],
            "hit_count": a["hits"],
            "prefix_count": len(a["prefixes"]),
            "ac_score": score,
            "prefixes": "|".join(sorted(a["prefixes"]))[:200],
        })

    out_rows.sort(key=lambda r: (-r["ac_score"], r["keyword"]))
    header = ["keyword", "best_position", "hit_count", "prefix_count", "ac_score", "prefixes"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header)
    w.writeheader()
    for r in out_rows:
        w.writerow(r)

    if args.out:
        io.open(args.out, "w", encoding="utf-8").write(buf.getvalue())
        print(f"已写入 {args.out}（{len(out_rows)} 个去重词）")
    else:
        print(buf.getvalue())


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("plan", help="生成请求清单")
    p1.add_argument("--seed", required=True)
    p1.add_argument("--marketplace", default="US")
    p1.add_argument("--mode", choices=["full", "fast"], default="full")
    p1.add_argument("--out")
    p1.set_defaults(func=cmd_plan)

    p2 = sub.add_parser("merge", help="合并结果并去重排序")
    p2.add_argument("--in", dest="input", required=True)
    p2.add_argument("--out")
    p2.set_defaults(func=cmd_merge)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
