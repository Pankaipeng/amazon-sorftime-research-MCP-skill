#!/usr/bin/env python3
"""交付前自检——不过就不许交。

检的是"这轮有没有偷工"这类结构性问题，不是词好不好：
  1. 词库字段是否齐
  2. 五路是不是每路都有贡献（某一路为 0 说明那一路没跑对）
  3. EST 占比是否超上限
  4. 否定清单里有没有过泛词（会误伤正常流量）
  5. P0 是否为空或超出名额
  6. BRAND 层有没有混进 P0/P1
  7. 层级/优先级取值是否合法

用法：
  python check.py <项目目录> [--config config.yaml]
退出码 0 = 全部通过；1 = 有 FAIL。
"""
import argparse
import io
import json
import os
import sys

from csv_io import read_csv

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml")

REQUIRED_COLS = ["keyword", "tier", "prio", "est", "W", "R", "R1", "R2", "R3",
                 "searches", "sources"]
ALLOWED_PRIO = {"P0", "P1", "P2", "BRAND", "OBSERVE", "NEG", "NODATA"}
ALLOWED_TIER = {"大词", "中词", "小词", "长尾", "-", ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.yaml"))
    ap.add_argument("--require-collection", action="store_true",
                    help="生产交付必须提供完整流量词采集台账")
    args = ap.parse_args()
    P = os.path.abspath(args.project)
    cfg = yaml.safe_load(io.open(args.config, encoding="utf-8"))

    def p(key):
        return os.path.join(P, cfg["outputs"][key])

    lib = read_csv(p("library"))
    neg = [l.strip() for l in io.open(p("negatives"), encoding="utf-8") if l.strip()]
    trace = read_csv(p("trace"))

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    # 1 字段
    missing = [c for c in REQUIRED_COLS if lib and c not in lib[0]]
    check("词库字段完整", not missing, "缺列：" + ",".join(missing) if missing else f"{len(REQUIRED_COLS)} 列齐")

    # 2 五路贡献
    backend_present = os.path.isfile(os.path.join(P, cfg["inputs"]["backend_json"]))
    required_sources = {"A", "B", "C", "D", "S"}
    if backend_present:
        required_sources.update({"N", "E"})
    contributions = {r["来源"].split()[0]: int(r["进候选"] or 0)
                     for r in trace if r["来源"] and r["来源"] != "合计"}
    zero = sorted(source for source in required_sources if not contributions.get(source))
    detail = "零贡献：" + ",".join(zero) if zero else f"{len(required_sources)} 路全部非零"
    if not backend_present:
        detail += "；后台未提供（可选）"
    check("采集来源贡献", not zero, detail)

    ledger = os.path.join(P, "collection-traffic.json")
    if args.require_collection or os.path.isfile(ledger):
        try:
            with io.open(ledger, encoding="utf-8-sig") as stream:
                collected = json.load(stream)["collections"]
            traffic = read_csv(os.path.join(P, "0A-竞品流量词.csv"))
            observed = {}
            for row in traffic:
                observed.setdefault(row["asin"], set()).add(row["keyword"].strip().casefold())
            problems = []
            expected = {row["asin"] for row in collected}
            for row in collected:
                asin = row["asin"]
                count = len(observed.get(asin, ()))
                if (row["status"] != "complete" or row["gap"] != 0
                        or row["api_total"] != row["unique"] or count != row["unique"]):
                    problems.append(f"{asin} {count}/{row['api_total']}，缺口 {row['gap']}，{row['base']['stop']}")
            if len(expected) != len(collected) or set(observed) - expected or not expected:
                problems.append("输入 ASIN 与采集台账不一致")
            if sum(map(len, observed.values())) != len(traffic):
                problems.append("采集底表存在重复 ASIN × 词")
            check("流量词采集完整度", not problems, "；".join(problems) if problems else f"{len(expected)} 个 ASIN 对齐")
        except (OSError, KeyError, ValueError, TypeError) as error:
            check("流量词采集完整度", False, f"无法核对台账：{error}")

    # 3 EST 比例
    est_n = len([r for r in lib if r["est"] == "EST"])
    ratio = est_n / len(lib) if lib else 0
    ack = bool(cfg["est"].get("ratio_acknowledged"))
    check("EST 占比", ratio <= cfg["est"]["max_ratio"] or ack,
          f"{ratio:.1%}（上限 {cfg['est']['max_ratio']:.0%}）" + ("，已配置确认" if ack else ""))

    # 4 否定清单不含过泛词
    no_neg = {x.strip().lower() for x in cfg["no_neg"]}
    bad = sorted(no_neg & {x.lower() for x in neg})
    check("否定清单无过泛词", not bad, "含：" + ",".join(bad) if bad else f"{len(neg)} 条")

    # 5 P0 名额
    p0 = [r for r in lib if r["prio"] == "P0"]
    slots = cfg["priority"]["p0_slots"]
    check("P0 名额", 0 < len(p0) <= slots, f"{len(p0)} 个 / 配置 {slots} 个")

    # 6 BRAND 不混入 P0/P1
    brands = {l.strip().lower() for l in io.open(p("brands"), encoding="utf-8") if l.strip()}
    mix = [r["keyword"] for r in lib if r["prio"] in ("P0", "P1") and r["keyword"].lower() in brands]
    check("BRAND 未混入 P0/P1", not mix,
          "混入：" + ",".join(mix[:3]) if mix else f"{len(brands)} 个品牌词单列")

    # 7 取值合法
    bad_prio = {r["prio"] for r in lib} - ALLOWED_PRIO
    bad_tier = {r["tier"] for r in lib} - ALLOWED_TIER
    check("层级/优先级取值合法", not bad_prio and not bad_tier,
          f"非法 prio={bad_prio} tier={bad_tier}" if (bad_prio or bad_tier) else "合法")

    # 输出
    lines = ["交付自检 — " + os.path.basename(P), ""]
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {detail}")
    fails = [r for r in results if not r[1]]
    lines += ["", f"结果：{len(results) - len(fails)} 通过 / {len(fails)} 未通过"]
    text = "\n".join(lines)
    print(text)
    io.open(os.path.join(P, "08-交付自检.txt"), "w", encoding="utf-8").write(text + "\n")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
