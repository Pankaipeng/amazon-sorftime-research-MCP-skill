#!/usr/bin/env python3
"""五路关键词合并 → 分层 → 优先级 → 打法象限。

设计约束：
  * 本文件不允许出现任何硬编码的词或阈值——全部从 config.yaml 取。
  * 输入必须包含「搜索量底表」，补量结果不能再写死在代码里。
  * 输出除词库外，必须附 00-五路合并追踪.csv，证明每条路真的被消费。

v3.7 起纳入四件事：
  1. 分层用「绝对锚优先 + 分位兜底」，不再纯分位（避免词库扩容后阈值漂移）
  2. 竞争度独立成一维（多指标归一后等权），与量档交叉出四象限
  3. 词根六分类（共性/属性/品牌/品类/受众/否定），属性带维度
  4. 品牌双分类（本品 / 竞品 / 兼容生态），本品品牌词绝不能当竞品截流

用法：
  python merge.py <项目目录> [--config config.yaml]
"""
import argparse
import csv
import io
import json
import os
import re
import statistics
import sys

try:
    import yaml
except ImportError:
    sys.exit("需要 pyyaml：pip install pyyaml")


def norm(k):
    return re.sub(r"\s+", " ", (k or "").lower().strip())


def read_csv(path):
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_float(v):
    try:
        return float(str(v).replace("'", "").strip())
    except (TypeError, ValueError):
        return None


def minmax(vals):
    """把一组数值压到 0-1；全等或空时返回 None 列表。"""
    xs = [v for v in vals if v is not None]
    if len(xs) < 2 or max(xs) == min(xs):
        return [None for _ in vals]
    lo, hi = min(xs), max(xs)
    return [None if v is None else (v - lo) / (hi - lo) for v in vals]


def pct_rank(vals):
    """百分位秩（0-1），抗重尾——商品数这类指标 min-max 会被极端值吃干。"""
    idx = [i for i, v in enumerate(vals) if v is not None]
    if len(idx) < 2:
        return [None for _ in vals]
    order = sorted(idx, key=lambda i: vals[i])
    out = [None] * len(vals)
    n = len(order)
    for pos, i in enumerate(order):
        out[i] = pos / (n - 1)
    return out


def load_cfg(path):
    with io.open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_candidates(P, cfg):
    """把五路产出 + 搜索量底表并成候选集，每个词记来源字母。"""
    cand, produced = {}, {}

    def mark(tag, word):
        produced.setdefault(tag, set()).add(norm(word))

    min_words = cfg["sample"].get("min_words_in_keyword", 1)

    def add(word, tag, **extra):
        k = norm(word)
        if not k or len(k.split()) < min_words:
            return
        c = cand.setdefault(k, {"src": set()})
        c["src"].add(tag)
        c.update({kk: v for kk, v in extra.items() if v is not None})

    for r in read_csv(os.path.join(P, cfg["inputs"]["search_table"])):
        mark("S", r["keyword"])
        add(r["keyword"], "S", searches=int(float(r["searches"])) if r["searches"] else None)

    for r in read_csv(os.path.join(P, cfg["inputs"]["a_traffic"])):
        mark("A", r["keyword"])
        add(r["keyword"], "A")

    min_hits = cfg["sample"]["min_asin_hits_in_title"]
    for r in read_csv(os.path.join(P, cfg["inputs"]["b_title"])):
        if int(r["asin_count"]) >= min_hits:
            mark("B", r["word"])
            add(r["word"], "B", cov_b=float(r["coverage"]))

    for r in read_csv(os.path.join(P, cfg["inputs"]["c_listing"])):
        mark("C", r["词/词组"])
        add(r["词/词组"], "C", cov_c=float(r["覆盖率"]))

    for r in read_csv(os.path.join(P, cfg["inputs"]["d_autocomplete"])):
        mark("D", r["联想词"])
        add(r["联想词"], "D", ac=float(r["ac_score"] or 0))

    bj = os.path.join(P, cfg["inputs"]["backend_json"])
    if os.path.exists(bj):
        with io.open(bj, encoding="utf-8") as f:
            d = json.load(f)
        for r in d.get("niche", []):
            mark("N", r.get("搜索词"))
            add(r.get("搜索词"), "N")
        for r in d.get("aba", []):
            mark("E", r.get("搜索词"))
            add(r.get("搜索词"), "E")

    return cand, produced


def load_brands(P, cfg):
    """竞品品牌 = 竞品池的 brand 列 + config 补充。返回 (短语集, 单词集)。"""
    phrases, tokens = set(), set()
    for r in read_csv(os.path.join(P, cfg["inputs"]["pool"])):
        b = norm(r.get("brand"))
        if not b:
            continue
        phrases.add(b)
        if " " not in b and len(b) >= 3:
            tokens.add(b)
    for b in cfg.get("brand_extra", []):
        phrases.add(norm(b))
    return phrases, tokens


def match_brand(k, phrases, tokens):
    if k in phrases:
        return True
    if any(k.startswith(p + " ") or (" " + p + " ") in (" " + k + " ") or k.endswith(" " + p)
           for p in phrases):
        return True
    return any(t in k.split() for t in tokens)


STOP = {"for", "and", "the", "with", "of", "in", "on", "to", "a", "an"}


def title_tokens(t, fold_plural=True):
    """标题分词：去标点、去连字符，可选把复数折回单数（sponges→sponge）。"""
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower().replace("-", " "))
    toks = set(t.split())
    if fold_plural:
        toks |= {x[:-1] for x in toks if len(x) > 3 and x.endswith("s")}
    return toks


def load_titles(P, cfg):
    """竞品标题原文，用于"完整包含"式的精确覆盖率（不再受 n-gram 长度限制）。"""
    fold = cfg["sample"].get("fold_plural", True)
    return [title_tokens(r.get("title", ""), fold)
            for r in read_csv(os.path.join(P, cfg["inputs"]["b_titles"]))
            if r.get("title")]


def exact_coverage(k, titles):
    """30 个竞品标题里，有几个完整包含该词的全部实词（顺序不限）。"""
    toks = {t for t in k.split() if t not in STOP}
    if not toks or not titles:
        return None
    hit = sum(1 for ts in titles if toks <= ts)
    return hit / len(titles)


def load_competition(P, cfg):
    """竞争度底表：keyword -> {spr, monopoly_click_rate, title_density, products}"""
    out = {}
    for r in read_csv(os.path.join(P, cfg["inputs"]["competition_table"])):
        out[norm(r["keyword"])] = {
            "spr": to_float(r.get("spr")),
            "monopoly_click_rate": to_float(r.get("monopoly_click_rate")),
            "title_density": to_float(r.get("title_density")),
            "products": to_float(r.get("products")),
        }
    return out


def load_aba_rank(P, cfg):
    """ABA 搜索频率排名：全站统一标尺，用来算"绝对层级"。"""
    out = {}
    for r in read_csv(os.path.join(P, cfg["inputs"]["backend_table"])):
        v = to_float(r.get("ABA搜索频率排名"))
        if v:
            out[norm(r["关键词"])] = int(v)
    return out


def load_word_root(P, cfg):
    """词根映射：从本次词库 token 分布现场归纳的产物，不是预置品类词表。"""
    path = os.path.join(P, cfg["word_root"]["map_file"])
    rows = read_csv(path)
    return {norm(r["token"]): (r["root_type"], r.get("dimension", "")) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.yaml"))
    args = ap.parse_args()
    P = os.path.abspath(args.project)
    cfg = load_cfg(args.config)

    cand, produced = build_candidates(P, cfg)
    conv = {}
    bj = os.path.join(P, cfg["inputs"]["backend_json"])
    if os.path.exists(bj):
        with io.open(bj, encoding="utf-8") as f:
            for r in json.load(f).get("niche", []):
                v = r.get("搜索转化率（过去 360 天）")
                if v not in (None, ""):
                    conv[norm(r.get("搜索词"))] = to_float(v)

    phrases, tokens = load_brands(P, cfg)
    own_brand = norm(cfg.get("own_brand", ""))
    comp_data = load_competition(P, cfg)
    titles = load_titles(P, cfg) if cfg["sample"].get("exact_coverage") else []
    aba_rank = load_aba_rank(P, cfg)
    root_map = load_word_root(P, cfg)

    z = {norm(x) for x in cfg["r1_zero"]}
    h = {norm(x) for x in cfg["r1_half"]}
    mat = [norm(x) for x in cfg["r2_conflict_material"]]
    no_neg = {norm(x) for x in cfg["no_neg"]}
    w = cfg["weights"]
    full = cfg["r3"]["full_mark_coverage"]
    neutral = cfg["r3"]["default_when_missing"]
    form_on = bool(cfg.get("form", {}).get("enabled"))
    wall = [norm(x) for x in cfg.get("form", {}).get("wall", [])]
    ctr = [norm(x) for x in cfg.get("form", {}).get("counter", [])]

    def r1_of(k):
        return 0.0 if k in z else (0.5 if k in h else 1.0)

    def form_of(k):
        if not form_on:
            return ""
        s = " " + k + " "
        a, b = any(x in s for x in wall), any(x in s for x in ctr)
        if a and not b:
            return "壁挂精准"
        if b and not a:
            return "台面冲突"
        return "泛词（形态混合）"

    def r2_of(k, f):
        if any(m in k for m in mat):
            return 0.0
        if f == "台面冲突":
            return 0.0
        if f == "壁挂精准":
            return 1.0
        return 0.5 if form_on else 1.0

    def root_of(k):
        """词根六分类：品牌 > 否定 > 属性 > 品类(替代叫法) > 共性(基础叫法) > 受众。"""
        if match_brand(k, phrases, tokens) or (own_brand and own_brand in k.split()):
            return "品牌", ""
        if r1_of(k) == 0:
            return "否定", ""
        toks = k.split()
        attr = [t for t in toks if t in root_map and root_map[t][0] == "属性"]
        if attr:
            t = max(attr, key=len)
            return "属性", root_map[t][1]
        cat = [t for t in toks if t in root_map and root_map[t][0] == "品类"
               and root_map[t][1] == "替代叫法"]
        if cat:
            return "品类", ""
        core = [t for t in toks if t in root_map and root_map[t][0] == "共性"]
        if core:
            return "共性", ""
        aud = [t for t in toks if t in root_map and root_map[t][0] == "受众"]
        if aud:
            return "受众", root_map[aud[0]][1]
        cat2 = [t for t in toks if t in root_map and root_map[t][0] == "品类"]
        if cat2:
            return "品类", ""
        return "共性", ""

    out = []
    for k, c in cand.items():
        f = form_of(k)
        r1, r2 = r1_of(k), r2_of(k, f)
        cands = [c.get("cov_b"), c.get("cov_c")]
        if titles:
            cands.append(exact_coverage(k, titles))     # 精确覆盖率：长短语不再失联
        cov = max([v for v in cands if v is not None], default=None)
        r3 = neutral if cov is None else round(min(1.0, cov / full), 3)
        R = 0.0 if (r1 == 0 or r2 == 0) else round(w["r1"] * r1 + w["r2"] * r2 + w["r3"] * r3, 3)
        s = c.get("searches")
        ac = c.get("ac") or 0
        if s:
            est, W = "MEASURED", round(s * R, 0)
        elif ac:
            est, W = "EST", round(ac * R * cfg["est"]["weight_scale"], 0)
        else:
            est, W = "NODATA", ""
        root, dim = root_of(k)
        out.append(dict(keyword=k, form=f, R1=r1, R2=r2, R3=r3, R=R, W=W,
                        searches=s, ac_score=ac or "", coverage_raw=cov if cov is not None else "",
                        est=est, sources="".join(sorted(c["src"])), tier="-", prio="",
                        conv=conv.get(k, ""), root=root, root_dim=dim, tier_abs=""))

    # ---- 品牌双分类 ----
    for r in out:
        k = r["keyword"]
        if own_brand and own_brand in k.split():
            r["brand_role"] = "own"
            r["prio"] = ""                      # 本品品牌词按语义成分正常参评，不当竞品
            r["root"] = "共性" if r["root"] == "品牌" else r["root"]
        elif match_brand(k, phrases, tokens):
            r["brand_role"] = "competitor"
            r["prio"] = "BRAND"
        else:
            r["brand_role"] = ""

    for r in out:
        if r["prio"]:
            continue
        if r["R1"] == 0 or r["R2"] == 0:
            r["prio"] = "OBSERVE" if r["keyword"] in no_neg else "NEG"

    # ---- 分层：绝对锚优先，分位兜底 ----
    meas = [r for r in out if r["est"] == "MEASURED" and not r["prio"]]
    tm = cfg["tiers"]
    if meas:
        vals = sorted(r["searches"] for r in meas)
        pcts = tm["percentile_fallback"]
        cut = [statistics.quantiles(vals, n=100)[p - 1] for p in pcts]
        bounds = tm.get("volume_bounds", [])
        for r in out:
            if r["est"] != "MEASURED" or r["prio"]:
                continue
            if tm["mode"] == "head_relative":
                ratios = tm["head_ratios"]
                head = max(vals)
                s = r["searches"]
                r["tier"] = ("大词" if s >= head * ratios[0] else
                             "中词" if s >= head * ratios[1] else
                             "小词" if s >= head * ratios[2] else "长尾")
            elif tm["mode"] == "volume_absolute" and bounds:
                s = r["searches"]
                r["tier"] = ("大词" if s >= bounds[0] else
                             "中词" if s >= bounds[1] else
                             "小词" if s >= bounds[2] else "长尾")
            else:
                s = r["searches"]
                r["tier"] = ("大词" if s >= cut[0] else
                             "中词" if s >= cut[1] else
                             "小词" if s >= cut[2] else "长尾")
        # 绝对层级：全站标尺（ABA 排名），没有排名时退回类目内层级
        ab = tm["aba_bounds"]
        for r in out:
            if r["prio"]:
                continue
            rk = aba_rank.get(r["keyword"])
            if rk:
                r["tier_abs"] = ("大词" if rk <= ab[0] else "中词" if rk <= ab[1]
                                 else "小词" if rk <= ab[2] else "长尾")
            else:
                r["tier_abs"] = r["tier"] if r["tier"] != "-" else ""
    else:
        cut = [0, 0, 0]

    # ---- 竞争度 ----
    cc = cfg["competition"]
    keys = cc["indicators"]
    cols = {kk: [] for kk in keys}
    for r in out:
        c = comp_data.get(r["keyword"], {})
        for kk in keys:
            cols[kk].append(c.get(kk))
    unit_cols = {"monopoly_click_rate"}          # 本身 0-1，直接用
    normed = {kk: (cols[kk] if kk in unit_cols else pct_rank(cols[kk])) for kk in keys}
    hi_t, lo_t = cc.get("any_high_threshold", 0.8), cc.get("all_low_threshold", 0.3)
    for i, r in enumerate(out):
        vals = [normed[kk][i] for kk in keys if normed[kk][i] is not None]
        if not vals:
            r["comp_score"], r["comp_level"] = "", ""
            continue
        r["comp_score"] = round(100 * sum(vals) / len(vals), 0)
        # 档位用「任一高=高 / 全低=低 / 否则中」——均值会被三项低拉平，掩盖单项极端值
        rule = cc.get("level_rule", "mean_with_override")
        hi, mid = cc["level_bounds"]
        if rule == "any_high":
            r["comp_level"] = "高" if max(vals) >= hi_t else ("低" if max(vals) <= lo_t else "中")
        else:
            r["comp_level"] = "高" if r["comp_score"] >= hi else ("中" if r["comp_score"] >= mid else "低")
            # 单项极端值覆盖：均值会被其余三项拉平，掩盖"商品数爆表"这类硬壁垒
            if max(vals) >= cc.get("override_threshold", 0.95):
                r["comp_level"] = "高"

    # ---- 优先级：W 降序名额制 ----
    ranked = sorted(meas, key=lambda r: -r["W"])
    p0n, p1n = cfg["priority"]["p0_slots"], cfg["priority"]["p1_slots"]
    veto = cfg["priority"]["use_conversion_veto"]
    idx = 0
    for r in ranked:
        if veto:
            cv = r.get("conv")
            if cv is not None and cv != "" and cv < cfg["priority"]["conversion_veto_below"]:
                r["prio"] = "P1"
                continue
        idx += 1
        r["prio"] = "P0" if idx <= p0n else ("P1" if idx <= p0n + p1n else "P2")
    for r in out:
        if not r["prio"]:
            r["prio"] = cfg["est"]["highest_tier"] if r["est"] == "EST" else "NODATA"

    # ---- 四象限（量档 × 竞争档）----
    for r in out:
        lvl, q = r.get("comp_level"), ""
        if lvl and r["tier"] in ("大词", "中词"):
            q = "蓝海主攻" if lvl == "低" else ("精准控预算" if lvl == "高" else "精准+词组")
        elif lvl and r["tier"] in ("小词", "长尾"):
            q = "长尾广泛" if lvl == "低" else ("不建议打" if lvl == "高" else "长尾捡量")
        r["quadrant"] = q

    order = {"P0": 0, "P1": 1, "P2": 2, "NODATA": 3, "BRAND": 4, "OBSERVE": 5, "NEG": 6}
    est_order = {"MEASURED": 0, "EST": 1, "NODATA": 2}
    out.sort(key=lambda r: (est_order[r["est"]], order[r["prio"]],
                            -(r["W"] if isinstance(r["W"], (int, float)) else 0)))

    def path(key):
        return os.path.join(P, cfg["outputs"][key])

    hdr = ["keyword", "tier", "tier_abs", "prio", "est", "W", "R", "R1", "R2", "R3",
           "searches", "conv", "coverage_raw", "ac_score", "sources",
           "root", "root_dim", "brand_role", "comp_score", "comp_level", "quadrant", "form"]
    with io.open(path("library"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=hdr, extrasaction="ignore")
        wr.writeheader()
        for r in out:
            wr.writerow(r)

    with io.open(path("negatives"), "w", encoding="utf-8") as f:
        for r in out:
            if r["prio"] == "NEG":
                f.write(r["keyword"] + "\n")
    with io.open(path("brands"), "w", encoding="utf-8") as f:
        for r in out:
            if r["prio"] == "BRAND":
                f.write(r["keyword"] + "\n")

    contrib = [("A 竞品流量词", "A"), ("B 竞品标题词频", "B"), ("C 竞品Listing词频", "C"),
               ("D 前台自动补全", "D"), ("S 搜索量底表", "S"),
               ("N 商机探测器", "N"), ("E ABA热门搜索词", "E")]
    with io.open(path("trace"), "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["来源", "产出词数", "进候选", "进词库", "P0/P1", "否定", "单源"])
        for name, tag in contrib:
            inlib = [r for r in out if tag in r["sources"]]
            wr.writerow([name, len(produced.get(tag, ())),
                         len([c for c in cand.values() if tag in c["src"]]),
                         len(inlib),
                         len([r for r in inlib if r["prio"] in ("P0", "P1")]),
                         len([r for r in inlib if r["prio"] == "NEG"]),
                         len([r for r in inlib if r["sources"] == tag])])
        wr.writerow(["合计", "", len(cand), len(out),
                     len([r for r in out if r["prio"] in ("P0", "P1")]),
                     len([r for r in out if r["prio"] == "NEG"]), ""])

    from collections import Counter
    cnt = Counter(r["prio"] for r in out)
    print(f"候选 {len(cand)} → 词库 {len(out)}")
    anchor = ("头部比例 " + str(tm.get("head_ratios")) if tm["mode"] == "head_relative"
              else "绝对锚 " + str(tm.get("volume_bounds")) if tm["mode"] == "volume_absolute"
              else "分位 " + str(cut))
    print("分层锚 " + anchor)
    print("层级 " + " / ".join(f"{k} {v}" for k, v in
                              Counter(r["tier"] for r in out).most_common()))
    print("优先级 " + " / ".join(f"{k} {cnt[k]}" for k in
                              ["P0", "P1", "P2", "BRAND", "OBSERVE", "NEG", "NODATA"] if cnt[k]))
    print("四象限 " + " / ".join(f"{k} {v}" for k, v in
                              Counter(r["quadrant"] for r in out if r["quadrant"]).most_common()))
    print("\nP0:")
    for r in [x for x in out if x["prio"] == "P0"]:
        print(f'  W={r["W"]:>8.0f} R={r["R"]:.2f} {r["tier"]:3} 竞争={r["comp_score"] or "-":>4} '
              f'{r["comp_level"] or "-"} {r["quadrant"] or "":8} {r["keyword"]}')


if __name__ == "__main__":
    main()
