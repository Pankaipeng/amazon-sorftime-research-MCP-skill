#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
50-copy · 文案交付前自检

十五项（C0-C12，含 C2b），退出码非 0 即失败（与 check.py / check_sp.py / check_facts.py 同一套规矩）：
  C0  输入齐备     copy.json / 事实卡 / 词库 / 定稿卖点 都在
  C1  字段边界     标题 75 / 亮点 125 / 五点 150-255-500 / 描述 2000 / ST 250 字节
  C2  五点结构     恰好 5 条，冒号开头 + 含分号 + 句末无标点 + 首字母大写
  C2b 亮点结构     3-5 段短语，第 1 段 ≤40 字符且 ≤6 词（移动端展示位）
  C3  禁用表       红线 FAIL / AI 腔 FAIL / 空话 WARN / 品类禁写 FAIL
  C4  短语重复     同一整短语全篇 ≤3 次，最多出现在 1 条五点上
  C5  词根重复     P0 词根 ≤8 次/≤4 条，P1 词根 ≤3 次/≤2 条
  C6  可读性       连续名词 ≥4 个、单子句 >20 词（描述 ≤30）
  C7  覆盖         P0 未覆盖 FAIL / P1 未覆盖必须「归因可核」否则 FAIL（2026-11-18 升）
                   / ST 为空而词库仍有 R≥0.6 未覆盖词 FAIL / P2 只报数
  C8  HTML 检查    四个字段零标签、零实体
  C9  事实越权     ① 无实测承重禁 lbs/pound/kg ② 事实卡无尺寸时禁 in/cm/mm/oz
                   ③ slots/zones/cups 前的数字须等于事实卡实值 ④ 每条五点须有事实锚点
  C10 亮点重复     与标题重复的实义词 ≤2 个，且须过删除测试
  C11 描述密度     只报数，不评分（口径本身不成立）
  C12 官方边界     全大写 / 特殊字符 / 句末标点 / 单词 ≤2 次 / emoji / 占位 / 缩写 / 单位空格

用法：
  python check_copy.py --category sponge-holder
  python check_copy.py --category sponge-holder --no-write
  python check_copy.py --file path/to/copy.json --category sponge-holder
"""

import argparse
import csv
from itertools import combinations
import json
import math
import re
import sys
from pathlib import Path

import yaml

from csv_io import read_csv

from fact_provenance import outer_dimensions_from_packaging

ROOT = Path(__file__).resolve().parent.parent.parent
# emoji 与常见符号图形，官方要点 requirements 页明列禁项
EMOJI_RE = r"[\U0001F000-\U0001FAFF☀-➿️⬀-⯿←-⇿]"
# C12 各命中类别 → severity 键 / issue 定位（2026-11-17 扩到 emoji、占位、缩写、单位空格）
HARD_SEV = {"全大写": "title_format", "特殊字符": "title_format", "句末标点": "title_format",
            "单词重复": "title_word_repeat", "促销语": "promo", "卖家信息": "promo",
            "emoji": "emoji", "占位内容": "placeholder"}
HARD_LOC = {"促销语": "全篇", "卖家信息": "全篇", "emoji": "全篇", "占位内容": "全篇"}
SOFT_SEV = {"尺寸重量": "title_measure", "颜色词": "title_color", "非拉丁字符": "title_measure",
            "不必要缩写": "abbrev", "单位缺空格": "unit_space"}
CASES = []
COVER = []
ISSUES = []


def ok(item, msg):
    CASES.append(("PASS", item, msg))


def fail(item, msg):
    CASES.append(("FAIL", item, msg))


def warn(item, msg):
    CASES.append(("WARN", item, msg))


def issue(level, check, loc, text, problem, fix):
    ISSUES.append({"level": level, "check": check, "位置": loc,
                   "原文": (text or "")[:120], "问题": problem, "建议": fix})


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------- 文本工具 ----------------

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def tokens(text, stop=()):
    """切词 + 小写。stop 为空时不去停用词。"""
    out = []
    for m in TOKEN_RE.finditer((text or "").lower()):
        w = m.group(0)
        if w in stop:
            continue
        out.append(w)
    return out


def stem(w):
    """极简词干化：只处理复数与 -ing，够用且不引依赖。"""
    w = w.lower().strip(".,;:!?()[]{}\"'")
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ss"):
        return w
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s"):
        return w[:-1]
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    return w


def stems(text, stop=()):
    return [stem(t) for t in tokens(text, stop)]


def norm_phrase(s):
    return " ".join(tokens(s))


def count_literal(term, text):
    """按原文匹配（保留 % # 等符号）。
    norm_phrase 会丢符号，导致红线 `100%` 命中裸数字 100 —— 文案写「holds 100 sponges」
    会被判红线 FAIL。含符号的词必须走这里。"""
    t = (text or "").lower()
    return len(re.findall(r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])", t))


SYMBOLIC = re.compile(r"[%#]")

# 官方 GX5L8BF8GLMML6CX 要求「Add a header with a colon followed by a description」，
# 冒号必须在段首的 Header 之后，不能藏在句中——只判「含冒号」会放过长句里随便一个冒号。
HEADER_RE = re.compile(r"^[^:;]{2,60}:")


def hit_count(term, text):
    """词表命中次数：带 % / # 的词按原文匹配，其余走归一化短语匹配。"""
    if SYMBOLIC.search(term or ""):
        return count_literal(term, text)
    return count_phrase(term, text)


FAM_TAIL = {"s", "es", "ed", "ing", "er", "ers", "or", "ors", "ly", "y"}


def same_family(a, b):
    """同族判定。stem('organizing')='organiz' 与 stem('organizer')='organizer'
    互不相等，覆盖判定会把 organizer 簇判成未覆盖（本品类核心簇，会造成下一轮白补词）。
    规则：短的一方必须是长一方的前缀，且多出的尾缀只能是派生后缀。
    2026-11-18 收紧：先用「前缀 + 长度差 ≤3」，结果 counter 把 countertop 判成已覆盖——
    而 countertop 对本品是形态冲突词，假覆盖比假未覆盖危险得多（会把台面流量引进来）。"""
    if a == b:
        return True
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return long_.startswith(short) and long_[len(short):] in FAM_TAIL


def in_stems(want, sset):
    return any(same_family(want, s) for s in sset)


def fpath(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def audit_selected_points(selection, copy, expected_count, fab=None, selling_point_scores=None, bullet_rules=None):
    if not isinstance(selection, dict) or not isinstance(selection.get("selected"), list):
        return "FAIL", "定稿卖点须包含 selected 数组"
    points = selection["selected"]
    if len(points) != expected_count:
        return "FAIL", "定稿卖点应有 %d 条，实际 %d 条" % (expected_count, len(points))

    scores = {}
    for point in points:
        if not isinstance(point, dict):
            return "FAIL", "selected 的每一项须为卖点对象"
        point_id, claim, score = (point.get(key) for key in ("sp_id", "claim", "M"))
        if not isinstance(point_id, str) or not re.fullmatch(r"SP\d+", point_id) or point_id in scores:
            return "FAIL", "定稿卖点 ID 无效或重复：%s" % point_id
        if not isinstance(claim, str) or not claim.strip() or claim.strip() == "—":
            return "FAIL", "%s 缺可用主张" % point_id
        if point.get("fact_status") not in ("CONFIRMED", "REWRITE", "DOWNGRADE"):
            return "FAIL", "%s 的事实核对状态不允许作为定稿卖点" % point_id
        if fab is not None:
            card = fab.get(point_id, {})
            if card.get("使用状态") != "可用":
                return "FAIL", "%s 的 FAB 状态为 %s" % (point_id, card.get("使用状态", "无卡片"))
            if claim.strip() != card.get("可用措辞", "").strip():
                return "FAIL", "%s 的定稿主张须与 FAB 卡可用措辞一致" % point_id
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            return "FAIL", "%s 缺有效 M 分" % point_id
        if selling_point_scores is not None:
            source = selling_point_scores.get(point_id)
            if source is None:
                return "FAIL", "%s 在卖点库 v2 中没有 M 分" % point_id
            if score != source:
                return "FAIL", "%s 的定稿 M 分 %g 与卖点库 v2 的 %g 不一致" % (point_id, score, source)
            score = source
        scores[point_id] = score

    if "bullet_sp_ids" not in copy:
        if fab is not None or selling_point_scores is not None or bullet_rules is not None:
            return "FAIL", "关联卖点库的文案须记录每条五点的 bullet_sp_ids"
        return "WARN", "旧稿缺 bullet_sp_ids，需逐点人工回查卖点 ID 和主张"
    assigned = copy["bullet_sp_ids"]
    if (not isinstance(assigned, list) or len(assigned) != len(copy.get("bullets") or [])
            or len(assigned) != expected_count
            or any(not isinstance(point_id, str) or point_id not in scores for point_id in assigned)
            or len(set(assigned)) != expected_count):
        return "FAIL", "bullet_sp_ids 须与五点及定稿卖点一一对应"
    if bullet_rules is not None:
        try:
            score_bullet_plan(copy, bullet_rules)
        except ValueError as exc:
            return "FAIL", str(exc)
        return "PASS", "定稿卖点和五点 ID 对齐，已按 50 的五点计划核对"
    if any(scores[left] < scores[right] for left, right in zip(assigned, assigned[1:])):
        return "FAIL", "五点的 bullet_sp_ids 须按 M 降序排列"
    return "PASS", "定稿卖点和五点 ID 对齐且按 M 降序；主张措辞仍须逐点复核"


def score_bullet_plan(copy, rules):
    plan = copy.get("bullet_plan")
    ids = copy.get("bullet_sp_ids", [])
    if not isinstance(plan, list) or len(plan) != len(ids) or len(ids) != len(rules["slots"]):
        raise ValueError("五点计划须覆盖所有五点及位置")
    results = []
    for row, point_id in zip(plan, ids):
        if not isinstance(row, dict) or row.get("sp_id") != point_id:
            raise ValueError("五点计划须与最终五点的 SP ID 和顺序一致")
        if row.get("role") not in rules["slots"]:
            raise ValueError("%s 缺有效五点职责" % point_id)
        for key in ("buyer_question", "new_information", "placement_reason"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("%s 的五点计划缺 %s" % (point_id, key))
        score = 0
        for key, weight in rules["weights"].items():
            value = row.get(key)
            if type(value) is not int or not 0 <= value <= rules["max_rating"]:
                raise ValueError("%s 的 %s 评分超出范围或缺失" % (point_id, key))
            score += value * weight
        if row["new_information_value"] == 0:
            raise ValueError("%s 没有新增信息，应合并或换点" % point_id)
        results.append(round(score / rules["max_rating"], 1))
    return results


def read_fab(path):
    cards = {}
    for row in read_csv(path):
        point_id = row.get("sp_id")
        if (not point_id or point_id in cards or not row.get("使用状态")
                or (row["使用状态"] == "可用" and not (row.get("可用措辞") or "").strip())):
            raise ValueError("FAB 卡缺必填字段或存在重复 SP ID")
        cards[point_id] = row
    if not cards:
        raise ValueError("FAB 卡没有数据")
    return cards


def read_selling_point_scores(path):
    scores = {}
    for row in read_csv(path):
        point_id = row.get("sp_id")
        if not point_id or point_id in scores:
            raise ValueError("卖点库 v2 缺 SP ID 或 ID 重复")
        score = float(row.get("M") or "nan")
        if not math.isfinite(score):
            raise ValueError("%s 在卖点库 v2 中缺有效 M 分" % point_id)
        scores[point_id] = score
    if not scores:
        raise ValueError("卖点库 v2 没有数据")
    return scores


def audit_bullet_translations(copy, required):
    if not required and "bullet_translations" not in copy:
        return None
    translations = copy.get("bullet_translations")
    if (not isinstance(translations, list)
            or len(translations) != len(copy.get("bullets") or [])
            or any(not isinstance(text, str) or not re.search(r"[\u3400-\u9fff]", text) for text in translations)):
        return "bullet_translations 须按五点原文顺序逐条提供中文对照"
    return None


def audit_bullet_semantics(copy, required):
    if not required and "bullet_semantic_review" not in copy:
        return None
    review = copy.get("bullet_semantic_review")
    ids = copy.get("bullet_sp_ids") or []
    bullets = copy.get("bullets") or []
    if (not isinstance(review, dict) or len(ids) != len(bullets)
            or review.get("sp_ids") != ids or review.get("bullets") != bullets):
        return "五点语义审查缺失或成稿已变动，须按当前英文五点和 SP ID 重审"
    benefits = review.get("buyer_benefits")
    if (not isinstance(benefits, list) or len(benefits) != len(ids)
            or any(not isinstance(text, str) or not text.strip() for text in benefits)):
        return "五点语义审查须逐条提炼买家主要利益"
    if len({text.strip().casefold() for text in benefits}) != len(ids):
        return "两条五点使用了相同的买家主要利益"
    pairs = review.get("pairs")
    pending = set(combinations(ids, 2))
    if not isinstance(pairs, list):
        return "五点语义审查缺少逐对判断"
    for row in pairs:
        keys = row.get("sp_ids") if isinstance(row, dict) else None
        if not isinstance(keys, list) or len(keys) != 2 or any(not isinstance(key, str) for key in keys):
            return "五点语义审查中的 SP ID 对无效"
        pair = tuple(keys)
        if pair not in pending:
            return "五点语义审查存在重复、逆序或无效的 SP ID 对"
        if row.get("verdict") != "distinct":
            return "%s 与 %s 的买家利益需去重后再交付" % pair
        reason = row.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return "%s 与 %s 缺少独立利益的判断依据" % pair
        pending.remove(pair)
    if pending:
        return "五点语义审查尚有 %d 对未检查" % len(pending)
    return None


def unsupported_fab_claim(copy, fab, patterns):
    for field in ("title", "highlights", "bullets", "description", "search_terms"):
        value = copy.get(field) or ""
        if isinstance(value, list):
            value = " \n".join(value)
        for point_id, pattern in patterns.items():
            if fab.get(point_id, {}).get("使用状态") != "可用" and re.search(pattern, value, re.I):
                return "%s 出现 %s 尚未获准的性能主张" % (field, point_id)
    return None


PATH_RE = re.compile(r"\b[a-z_]+(?:\.[a-z_]+){1,}\b")


def audit_reason(reason, facts):
    """归因可核判定：返回 (layer, 是否可核, 原因)。
    2026-11-18 补：原先只看 L0/L1/L2 前缀，编一句「L0 事实：随便写的」就能让
    P1 缺失整项变绿，SKILL 硬规则 3「写不出归因不算理由」从未被强制。
      L0 事实层 → 必须指回事实卡里真实存在的字段路径（如 structure.zone_use）
      L1 表达层 → 必须给出 R 值或门槛，否则无法复核「读不通」是不是托词
      L2 重复层 → 必须点明重复对象（词根 / 短语 / 上限）
    """
    if not (reason or "").strip():
        return "", False, "无归因"
    if reason.startswith("L0"):
        paths = PATH_RE.findall(reason)
        real = [p for p in paths if fpath(facts, p) is not None]
        if real:
            return "L0 事实", True, "引用 %s" % real[0]
        return "L0 事实", False, "没有指回事实卡真实字段（写出的路径查不到：%s）" % (", ".join(paths[:3]) or "无")
    if reason.startswith("L1"):
        if re.search(r"R\s*=\s*0\.\d+|门槛|slot_min_w_gain", reason):
            return "L1 表达", True, "给了 R 或门槛"
        return "L1 表达", False, "未给 R 值或门槛，无法复核"
    if reason.startswith("L2"):
        if re.search(r"重复|超限|词根|上限", reason):
            return "L2 重复", True, "点明重复对象"
        return "L2 重复", False, "未点明重复对象"
    return "", False, "前缀不是 L0/L1/L2"


def count_phrase(phrase, text):
    """整短语出现次数（词边界匹配，避免 cup 命中 occupy）。"""
    p = norm_phrase(phrase)
    if not p:
        return 0
    t = norm_phrase(text)
    if not t:
        return 0
    return len(re.findall(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", t))


def bytes_len(s):
    return len((s or "").encode("utf-8"))


def search_term_issues(search_terms, front_text, limits):
    size = bytes_len(search_terms)
    upper = limits["max"]
    issues = []
    if size > upper or (size == upper and limits.get("strict_max", False)):
        bound = "须小于" if limits.get("strict_max", False) else "不得超过"
        issues.append("ST %d 字节，%s %d 字节" % (size, bound, upper))
    lower = math.ceil(upper * limits.get("target_min_ratio", 0))
    if size < lower:
        issues.append("ST %d 字节，低于交付目标 %d 字节" % (size, lower))
    if search_terms and limits.get("unique_words", False):
        if not re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+)*", search_terms):
            issues.append("ST 仅用小写字母或数字，词间用单个空格")
        words = tokens(search_terms)
        if len(words) != len(set(words)):
            issues.append("ST 内含重复词")
        overlap = sorted(set(words) & set(tokens(front_text)))
        if overlap:
            issues.append("ST 与前台重复：%s" % "、".join(overlap))
    return issues


def clauses(text):
    """按句末与分号切子句，用于句长检查。"""
    parts = re.split(r"[.!?;:]", text or "")
    return [p.strip() for p in parts if p.strip()]


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True, help="品类目录名，如 sponge-holder")
    ap.add_argument("--file", default=None, help="copy.json 路径，默认按配置推导")
    ap.add_argument("--config", default=str(Path(__file__).parent / "copy_config.yaml"))
    ap.add_argument("--no-write", action="store_true", help="只算不落盘")
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    sev = cfg["severity"]
    inp = {k: v.replace("{category}", args.category) for k, v in cfg["inputs"].items()}
    outdir = ROOT / cfg["outputs"]["dir"].replace("{category}", args.category)

    copy_path = Path(args.file) if args.file else ROOT / inp["copy"]
    facts_path = ROOT / inp["facts"]
    lib_path = ROOT / inp["keyword_library"]
    sp_path = ROOT / inp["selected_sp"]
    fab_path = ROOT / inp["fab_cards"] if inp.get("fab_cards") else None
    scores_path = ROOT / inp["selling_point_library"] if inp.get("selling_point_library") else None

    # ---------- C0 输入齐备 ----------
    missing = [str(p) for p in (copy_path, facts_path, lib_path, sp_path, fab_path, scores_path)
               if p is not None and not p.is_file()]
    if missing:
        fail("C0 输入齐备", "缺文件：" + "；".join(missing))
        # 输入不全时一律不落盘，避免在建错的目录里生出一堆空产物
        report(outdir, cfg, True)
        return 2
    copy = json.load(open(copy_path, encoding="utf-8"))
    facts = json.load(open(facts_path, encoding="utf-8"))
    library = read_csv(lib_path)
    try:
        selection = json.loads(sp_path.read_text(encoding="utf-8-sig"))
        fab = read_fab(fab_path) if fab_path is not None else None
        scores = read_selling_point_scores(scores_path) if scores_path is not None else None
        bullet_rules = cfg.get("bullet_selection")
        status, detail = audit_selected_points(selection, copy, cfg["fields"]["bullet_count"]["max"], fab, scores, bullet_rules)
        if status == "PASS" and fab is not None:
            problem = unsupported_fab_claim(copy, fab, cfg.get("fab_claim_patterns", {}))
            if problem:
                status, detail = "FAIL", problem
            else:
                detail += "；定稿主张与 FAB 卡一致"
        if status == "PASS" and scores is not None:
            detail += "；M 参考分已与卖点库 v2 核对"
        if status != "FAIL":
            problem = audit_bullet_translations(copy, cfg.get("decisions", {}).get("bullet_translation_required", False))
            if problem:
                status, detail = "FAIL", problem
        if status != "FAIL":
            semantic_required = cfg.get("decisions", {}).get("bullet_semantic_review_required", False)
            problem = audit_bullet_semantics(copy, semantic_required)
            if problem:
                status, detail = "FAIL", problem
            elif copy.get("bullet_semantic_review"):
                detail += "；五点语义审查已覆盖最终成稿"
    except (ValueError, OSError) as exc:
        status, detail = "FAIL", "无法读取定稿卖点、FAB 卡或卖点库 v2：%s" % exc
    CASES.append((status, "C0 输入与定稿卖点", detail))
    if status == "FAIL":
        issue("FAIL", "C0", sp_path.name, "", detail, "核对选定卖点文件和文案中的卖点 ID")

    title = copy.get("title") or ""
    high = copy.get("highlights") or ""
    bullets = copy.get("bullets") or []
    desc = copy.get("description") or ""
    st = copy.get("search_terms") or ""
    frontend = " \n".join([title, high, " ".join(bullets), desc])

    stop = set(cfg["stopwords"])
    f = cfg["fields"]

    # ---------- C1 字段边界 ----------
    bad = []
    # 大纲输出层四个字段（标题/亮点/五点/ST）里，标题与亮点为空直接 FAIL。
    # 2026-11-18 补：原先只判上限，空字段能整项通过；亮点为空时 C2b 还会整项静默跳过，
    # 检查项从 15 掉到 14 且全绿。ST 为空由 C7 单独判（要看词库里还有没有可入后台的词）。
    if not title.strip():
        bad.append("标题为空")
        issue(sev["field_limit"], "C1", "title", "", "Item Name 为空", "按 07 §2.0 四段组标题")
    if not high.strip():
        bad.append("亮点为空")
        issue(sev["field_limit"], "C1", "highlights", "", "Item Highlights 为空（大纲四字段之一）",
              "按 07 §3.0 先平铺六个信息类目再定顺序")
        warn("C2b 亮点结构", "亮点为空，本项未评估（不是通过）")
    if len(title) > f["title"]["max"]:
        bad.append("标题 %d 字符 > %d" % (len(title), f["title"]["max"]))
        issue(sev["field_limit"], "C1", "title", title, "超 %d 字符" % f["title"]["max"], "先做词干压缩，再按序砍")
    if len(high) > f["highlights"]["max"]:
        bad.append("亮点 %d 字符 > %d" % (len(high), f["highlights"]["max"]))
        issue(sev["field_limit"], "C1", "highlights", high, "超 %d 字符" % f["highlights"]["max"], "挪词到五点")

    b = f["bullet"]
    short, long_ = [], []
    for i, bl in enumerate(bullets, 1):
        n = len(bl)
        if n > b["hard_max"]:
            bad.append("五点 %d 共 %d 字符 > %d" % (i, n, b["hard_max"]))
            issue(sev["field_limit"], "C1", "bullets[%d]" % (i - 1), bl,
                  "超官方硬上限 %d" % b["hard_max"], "删场景句，保证据")
        elif n > b["recommend_max"]:
            long_.append("第 %d 点 %d 字符" % (i, n))
            issue(sev["field_limit"] + "/建议", "C1", "bullets[%d]" % (i - 1), bl,
                  "超建议上限 %d" % b["recommend_max"], "压到 %d 字符内" % b["target_max"])
        elif n < b["target_min"]:
            short.append("第 %d 点 %d 字符" % (i, n))

    if long_:
        warn("C1 字段边界", "%d 条超建议上限 %d：%s" % (len(long_), b["recommend_max"], "、".join(long_)))
    if short:
        warn("C1 字段边界", "%d 条低于目标下界 %d：%s" % (len(short), b["target_min"], "、".join(short)))

    if len(desc) > f["description"]["max"]:
        bad.append("描述 %d 字符 > %d" % (len(desc), f["description"]["max"]))
        issue(sev["field_limit"], "C1", "description", "", "超 %d 字符" % f["description"]["max"], "压段")
    elif len(desc) > f["description"]["recommend_max"]:
        warn("C1 字段边界", "描述 %d 字符，超建议上限 %d" % (len(desc), f["description"]["recommend_max"]))

    for problem in search_term_issues(st, frontend, f["st"]):
        bad.append(problem)
        issue(sev["field_limit"], "C1", "search_terms", st, problem, "按前台、词库和本品事实核对后台词")

    if bad:
        fail("C1 字段边界", "；".join(bad))
    else:
        ok("C1 字段边界", "标题 %d/%d，亮点 %d/%d，五点 %d-%d 字符，描述 %d，ST %d 字节"
           % (len(title), f["title"]["max"], len(high), f["highlights"]["max"],
              min([len(x) for x in bullets], default=0),
              max([len(x) for x in bullets], default=0), len(desc), bytes_len(st)))

    # ---------- C2 五点结构 ----------
    cnt = f["bullet_count"]
    problems = []
    if not (cnt["min"] <= len(bullets) <= cnt["max"]):
        problems.append("五点 %d 条，应为 %d-%d 条" % (len(bullets), cnt["min"], cnt["max"]))

    st_cfg = cfg["structure"]
    for i, bl in enumerate(bullets, 1):
        loc = "bullets[%d]" % (i - 1)
        if not bl.strip():
            problems.append("五点 %d 为空" % i)
            continue
        if st_cfg["bullet_requires_colon"] and not HEADER_RE.match(bl):
            problems.append("五点 %d 缺段首冒号（官方要求 Header: description）" % i)
            issue(sev["bullet_structure"], "C2", loc, bl, "冒号不在段首，Header 结构不成立",
                  "写成 Header: phrase; phrase，冒号前 2-60 字符")
        if st_cfg["bullet_requires_semicolon"] and ";" not in bl:
            problems.append("五点 %d 缺分号" % i)
            issue(sev["bullet_structure"], "C2", loc, bl, "缺官方要求的分号", "用分号分隔短语")
        if st_cfg["bullet_forbid_end_punct"] and re.search(r"[.!?]\s*$", bl):
            problems.append("五点 %d 句末有标点" % i)
            issue(sev["bullet_structure"], "C2", loc, bl, "句末标点违反官方 requirements 页", "删掉句末标点")
        if bl[:1] and not bl[:1].isupper():
            problems.append("五点 %d 首字母未大写" % i)
            issue(sev["bullet_structure"], "C2", loc, bl, "官方要求 Begin with a capital letter", "首字母大写")

    if st_cfg["highlights_forbid_sentence"] and re.search(r"[.!?]", high):
        problems.append("亮点含完整句子标点")

    if problems:
        fail("C2 五点结构", "；".join(sorted(set(problems))))
    else:
        ok("C2 五点结构", "%d 条，冒号 + 分号 + 句末无标点 + 首字母大写" % len(bullets))

    # ---------- C2-b 亮点短语结构（2026-11-17 补，WARN 级）----------
    # 依据：官方 Item Highlights 示例为逗号分隔的短语，不是主谓句。
    # 短语内部列举也用逗号（fits glass, tile and steel），所以段数按切分数算、区间放宽。
    if high.strip():
        dec = cfg.get("decisions") or {}
        pmin = int(dec.get("highlight_phrase_min", 3))
        pmax = int(dec.get("highlight_phrase_max", 5))
        wmax = int(dec.get("highlight_phrase_max_words", 8))
        vis = int(dec.get("highlight_mobile_visible_chars", 40))
        phrases = [p.strip() for p in high.split(",") if p.strip()]
        hp = []
        if not (pmin <= len(phrases) <= pmax):
            hp.append("%d 段短语，应在 %d-%d 段" % (len(phrases), pmin, pmax))
        if phrases and len(phrases[0]) > vis:
            hp.append("第 1 段 %d 字符，超移动端可见位 %d" % (len(phrases[0]), vis))
        for i, p in enumerate(phrases, 1):
            if len(p.split()) > wmax:
                hp.append("第 %d 段 %d 词，超 %d" % (i, len(p.split()), wmax))
        if hp:
            warn("C2b 亮点结构", "；".join(hp))
            issue("WARN", "C2", "highlights", high, "亮点短语结构不合规则", "拆成 3-5 段短语，每段 ≤8 词，第 1 段 ≤40 字符")
        else:
            ok("C2b 亮点结构", "%d 段短语，第 1 段 %d 字符，最长 %d 词"
               % (len(phrases), len(phrases[0]), max(len(p.split()) for p in phrases)))

    # ---------- C3 禁用表 ----------
    dis = cfg["disallowed"]
    hits = {"redline": [], "ai_cliche": [], "vague": []}
    for name in hits:
        for w in dis[name]:
            n = hit_count(w, frontend)
            if n:
                hits[name].append("%s×%d" % (w, n))
    cat_forbidden = []
    for item in (cfg.get("categories", {}).get(args.category, {}) or {}).get("forbidden", []):
        if hit_count(item["word"], frontend):
            cat_forbidden.append(item["word"])
            issue(sev["category_forbidden"], "C3", "全篇", item["word"], item["reason"], "删词并回查卖点库")

    if hits["redline"] or hits["ai_cliche"]:
        fail("C3 禁用表", "红线：%s｜AI 腔：%s"
             % ("、".join(hits["redline"]) or "无", "、".join(hits["ai_cliche"]) or "无"))
        for w in dis["redline"]:
            if hit_count(w, frontend):
                issue(sev["redline"], "C3", "全篇", w, "红线词",
                      dis["replacements"].get(w, "改为可验证表述"))
        for w in dis["ai_cliche"]:
            if hit_count(w, frontend):
                issue(sev["ai_cliche"], "C3", "全篇", w, "营销腔，无信息量", "换成具体动作或条件")
    elif cat_forbidden:
        fail("C3 禁用表", "品类禁写：%s" % "、".join(cat_forbidden))
    else:
        ok("C3 禁用表", "红线 0 / AI 腔 0 / 品类禁写 0；空话 %d"
           % len(hits["vague"]))
    if hits["vague"]:
        warn("C3 禁用表", "空话：%s（占掉了能写事实的位置）" % "、".join(hits["vague"]))
        for w in dis["vague"]:
            if hit_count(w, frontend):
                issue(sev["vague"], "C3", "全篇", w, "无证据的形容词", "换成材料/尺寸/场景事实")

    # ---------- C4 短语重复 ----------
    emb = cfg["embedding"]
    cand = [r for r in library if (r.get("prio") or "") in ("P0", "P1")]
    over_total, over_bullet = [], []
    for r in cand:
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        total = count_phrase(kw, title) + count_phrase(kw, high) + count_phrase(kw, desc) \
            + sum(count_phrase(kw, x) for x in bullets)
        n_bul = sum(1 for x in bullets if count_phrase(kw, x))
        if total > emb["phrase_total_max"]:
            over_total.append("%s×%d" % (kw, total))
        if n_bul > emb["phrase_max_bullets"]:
            over_bullet.append("%s 占 %d 条" % (kw, n_bul))
    if over_total or over_bullet:
        warn("C4 短语重复", "全篇超限：%s｜跨条超限：%s"
             % ("、".join(over_total) or "无", "、".join(over_bullet) or "无"))
        for kw in over_total + over_bullet:
            issue(sev["phrase_repeat"], "C4", "全篇", kw, "同一短语重复", "删一处，或换同义变体")
    else:
        ok("C4 短语重复", "P0/P1 短语全篇 ≤%d 次、每条五点 ≤%d 条短语"
           % (emb["phrase_total_max"], emb["phrase_max_bullets"]))

    # ---------- C5 词根重复 ----------
    # 注意：词库的 root 列是语义维度（共性/品类/属性），不是词根。
    # 词根一律从 P0/P1 关键词的实义 token 现推，否则这条检查会静默变成空跑。
    # 分两档（2026-11-17）：P0 是品类核心词，一篇讲"水槽海绵架"的文案里 sink 出现 7 次是必然；
    # P1 是长尾修饰词，重复才是堆词。
    core_roots, long_roots = set(), set()
    for r in cand:
        bucket = core_roots if (r.get("prio") or "") == "P0" else long_roots
        for t in tokens(r.get("keyword") or "", stop):
            bucket.add(stem(t))
    long_roots -= core_roots          # 已被 P0 认领的词根不再按 P1 计
    front_tokens = stems(frontend, stop)
    root_hit = []
    checks = [(x, emb["root_core_total_max"], emb["root_core_max_bullets"], "P0")
              for x in sorted(core_roots)]
    checks += [(x, emb["root_total_max"], emb["root_max_bullets"], "P1")
               for x in sorted(long_roots)]
    for rt, t_max, b_max, tier in checks:
        total = front_tokens.count(rt)
        if total <= 0:
            continue
        nb = sum(1 for x in bullets if rt in stems(x, stop))
        if total > t_max or nb > b_max:
            root_hit.append("%s[%s] 全篇%d次/五点%d条" % (rt, tier, total, nb))
    if root_hit:
        warn("C5 词根重复", "超限 %d 个词根：%s（P0 上限 全篇%d/五点%d；P1 上限 %d/%d）"
             % (len(root_hit), "；".join(root_hit[:6]),
                emb["root_core_total_max"], emb["root_core_max_bullets"],
                emb["root_total_max"], emb["root_max_bullets"]))
        for x in root_hit:
            issue(sev["root_repeat"], "C5", "全篇", x.split(" ")[0], x, "换同义变体或删一处")
    else:
        ok("C5 词根重复", "P0 词根 ≤%d次/≤%d条；P1 词根 ≤%d次/≤%d条"
           % (emb["root_core_total_max"], emb["root_core_max_bullets"],
              emb["root_total_max"], emb["root_max_bullets"]))

    # ---------- C6 可读性 ----------
    lexicon = set()
    for r in library:
        for t in tokens(r.get("keyword") or "", stop):
            lexicon.add(stem(t))
    noun_runs = []
    for loc, text in [("title", title), ("highlights", high), ("description", desc)] + \
                     [("bullets[%d]" % i, x) for i, x in enumerate(bullets)]:
        # 按标点切段，避免 "Kitchen Sink, Sink Caddy" 跨逗号连成一串
        for seg in re.split(r"[,;:.!?()\[\]|/]", text):
            run = []
            for t in tokens(seg):
                if stem(t) in lexicon:
                    run.append(t)
                    if len(run) == emb["noun_run_warn"]:
                        noun_runs.append((loc, " ".join(run)))
                else:
                    run = []
    noun_runs = list(dict.fromkeys(noun_runs))

    long_clauses = []
    # 描述天然比五点句子长，用单独阈值（2026-11-17 加）
    desc_max = emb.get("desc_sentence_max_words", emb["sentence_max_words"])
    for loc, text, cap in [("bullets[%d]" % i, x, emb["sentence_max_words"])
                           for i, x in enumerate(bullets)] + [("description", desc, desc_max)]:
        for c in clauses(text):
            n = len(tokens(c))
            if n > cap:
                long_clauses.append((loc, n, c, cap))

    if noun_runs or long_clauses:
        msg = []
        if noun_runs:
            msg.append("名词串联 %d 处（%s：%s）" % (len(noun_runs), noun_runs[0][0], noun_runs[0][1]))
            for loc, run in noun_runs:
                issue(sev["noun_run"], "C6", loc, run, "连续名词 ≥%d 个" % emb["noun_run_warn"], "插介词或拆分")
        if long_clauses:
            msg.append("长句 %d 处（%s）" % (len(long_clauses), "、".join("%s %d词" % (a, b) for a, b, _, _ in long_clauses[:3])))
            for loc, n, c, cap in long_clauses:
                issue(sev["sentence_len"], "C6", loc, c, "单子句 %d 词 > %d" % (n, cap), "断句")
        warn("C6 可读性", "；".join(msg))
    else:
        ok("C6 可读性", "无 ≥%d 个连续名词，无 >%d 词的单子句（描述 ≤%d）"
           % (emb["noun_run_warn"], emb["sentence_max_words"], desc_max))

    # ---------- C7 覆盖 ----------
    rule = cfg["coverage"]["missing_rule"]
    ignore = set(cfg["coverage"]["ignore_prio"])
    reasons = copy.get("coverage_reasons") or {}
    field_texts = [("title", title), ("highlights", high)] + \
                  [("bullets[%d]" % i, x) for i, x in enumerate(bullets)] + [("description", desc)]
    all_stems = set()
    for _, t in field_texts:
        all_stems.update(stems(t, stop))
    backend_stems = set(stems(st, stop))
    combined_stems = all_stems | backend_stems

    p0_miss, p1_miss, p1_noreason, p1_fake, counted = [], [], [], [], 0
    st_pool = []          # 未覆盖且 R≥0.6 的词：本该进 ST 的候选
    for r in library:
        prio = (r.get("prio") or "").strip()
        if prio in ignore or prio not in ("P0", "P1", "P2"):
            continue
        kw = (r.get("keyword") or "").strip()
        if not kw:
            continue
        need = [stem(t) for t in tokens(kw, stop)]
        # 同族匹配：stem('organizing')='organiz' 与 organizer 不相等，硬判相等会假「未覆盖」
        covered = all(in_stems(nt, all_stems) for nt in need) if need else False
        where, form = "", ""
        if covered:
            exact_hit, stem_hit = "", ""
            for loc, t in field_texts:
                if count_phrase(kw, t):
                    exact_hit = exact_hit or loc
                elif all(in_stems(stem(x), set(stems(t, stop))) for x in tokens(kw, stop)):
                    stem_hit = stem_hit or loc
            if exact_hit:
                where, form = exact_hit, "EXACT"
            elif stem_hit:
                where, form = stem_hit, "STEM"
            else:
                # 所有词都在，但分散在不同字段：算覆盖，标拆词
                where, form = "跨字段", "SPLIT"
        elif prio == "P2" and need and all(in_stems(nt, combined_stems) for nt in need):
            covered = True
            where = "search_terms" if all(in_stems(nt, backend_stems) for nt in need) else "前台+search_terms"
            form = "STEM" if where == "search_terms" else "SPLIT"
        verdict = "PASS" if covered else rule.get(prio, "IGNORE")
        reason = reasons.get(kw, "")
        layer, audited, why = audit_reason(reason, facts)
        if not covered:
            counted += 1
            try:
                if float(r.get("R") or 0) >= 0.6:
                    st_pool.append(kw)
            except (TypeError, ValueError):
                pass
            if prio == "P0":
                p0_miss.append(kw)
            elif prio == "P1":
                p1_miss.append(kw)
                if not layer:
                    p1_noreason.append(kw)
                elif not audited:
                    p1_fake.append((kw, why))
        COVER.append({"keyword": kw, "prio": prio, "W": r.get("W", ""),
                      "covered": "是" if covered else "否", "where": where, "form": form,
                      "layer": layer, "reason": reason, "verdict": verdict,
                      "audit": "可核" if audited else ("不可核：" + why if layer else "无归因")})

    p0_rule = rule.get("P0", "FAIL")
    if p0_miss and p0_rule == "FAIL":
        fail("C7 覆盖", "P0 未覆盖 %d 个：%s" % (len(p0_miss), "、".join(p0_miss)))
        for kw in p0_miss:
            issue("FAIL", "C7", "全篇", kw, "P0 必放词未覆盖", "补词或改文案")
    else:
        ok("C7 覆盖", "P0 全覆盖（%d 个 P0 词）"
           % sum(1 for r in library if (r.get("prio") or "") == "P0"))

    # 2026-11-18 升级：P1 未覆盖且无归因 / 归因不可核，从 WARN 升 FAIL。
    # 原实现只 WARN、退出码仍 0，等于「写不出归因不算理由」这条硬规则没有闸门。
    if p1_noreason or p1_fake:
        lvl = sev.get("coverage_p1", "FAIL")
        msg = "P1 未覆盖 %d 个，其中无归因 %d 个、归因不可核 %d 个" % (
            len(p1_miss), len(p1_noreason), len(p1_fake))
        # 判定级别由 severity.coverage_p1 决定，不在代码里写死——否则又变成「配置说一套、脚本做一套」
        (fail if lvl == "FAIL" else warn)("C7 覆盖", msg)
        for kw in p1_noreason:
            issue(lvl, "C7", "全篇", kw, "P1 未覆盖且无归因", "写 L0/L1/L2 理由，或补词")
        for kw, why in p1_fake:
            issue(lvl, "C7", "全篇", kw, "归因不可核（%s）" % why,
                  "L0 须指回事实卡真实字段，L1 须给 R 值或门槛，L2 须点明重复对象")
    elif p1_miss:
        ok("C7 覆盖", "P1 未覆盖 %d 个，归因均可核" % len(p1_miss))

    # ST 为空但词库里还有 R≥0.6 的未覆盖词 → 漏判修复：空 ST 原先整项通过
    if not st.strip():
        if st_pool:
            fail("C7 覆盖", "ST 为空，但词库有 %d 个未覆盖且 R≥0.6 的词可入后台（示例：%s）"
                 % (len(st_pool), "、".join(st_pool[:3])))
            issue(sev["coverage_p0"], "C7", "search_terms", "", "ST 为空",
                  "按 07 §六 取未覆盖词，≤250 字节")
        else:
            warn("C7 覆盖", "ST 为空，且词库无未覆盖的 R≥0.6 词（罕见，请复核词库）")

    # ---------- C8 HTML（2026-11-17 扩到全字段，原来只看描述）----------
    # 官方标题指南与要点指南都禁止 HTML/script 标签；描述自 2021 起不支持 HTML。
    # 所以不是「描述例外」，而是四个前台字段一律不允许标签与 HTML 实体。
    html_hits = []
    scan = [("title", title), ("highlights", high)]
    scan += [("bullets[%d]" % i, b) for i, b in enumerate(bullets)]
    if cfg["structure"].get("description_allow_html", False):
        scan_desc = []
    else:
        scan_desc = [("description", desc)]
    for loc, txt in scan + scan_desc:
        for h in re.findall(r"</?[a-zA-Z][^>]*>", txt):
            html_hits.append((loc, h))
        for e in re.findall(r"&[a-zA-Z]+;|&#\d+;", txt):
            html_hits.append((loc, e))
    if html_hits:
        fail("C8 HTML 检查", "含标签/实体：%s"
             % "、".join("%s:%s" % (l, h) for l, h in html_hits[:5]))
        for loc, h in html_hits[:10]:
            issue(sev["html_tag"], "C8", loc, h, "亚马逊全字段不支持 HTML", "删标签，用空行或标点分段")
    else:
        ok("C8 HTML 检查", "标题/亮点/五点/描述 零标签、零实体")

    # ---------- C9 事实越权 ----------
    # 2026-11-18 扩容。原实现只拦重量单位、且只在 load.tested=false 时拦，
    # 实测往五点塞「8.5 in / 3 slots / 12 oz」整项照样 PASS——事实卡 dims 三项为 null
    # 时尺寸类数值同样是无据声明。现拆三层：
    #   ① 重量：load.tested=false → 禁 lbs/pound/kg
    #   ② 尺寸与净重：事实卡对应字段为 null → 禁 in/cm/mm/oz（不管 tested）
    #   ③ 件数：slots/zones/suction cups 前的数字必须等于事实卡实值
    load_tested = bool((facts.get("load") or {}).get("tested"))
    unit_hits = re.findall(r"\b\d+(?:\.\d+)?\s*(?:lbs?|pounds?|kgs?|kilograms?)\b", frontend, re.I)
    over = []
    if unit_hits and not load_tested:
        over.append("无实测承重却出现重量：%s" % "、".join(unit_hits[:5]))

    dims_missing = [p for p in ("dims.outer_in.l", "dims.outer_in.w", "dims.outer_in.h")
                    if fpath(facts, p) is None]
    dim_hits = re.findall(r"\b\d+(?:\.\d+)?\s*(?:in|inch|inches|cm|mm)\b", frontend, re.I)
    if dim_hits and dims_missing:
        over.append("事实卡 %s 为 null，文案却出现尺寸：%s"
                    % ("、".join(p.split(".")[-1] for p in dims_missing), "、".join(dim_hits[:5])))
    if dim_hits and not dims_missing and outer_dimensions_from_packaging(facts):
        over.append("事实卡三围取自包装，文案却出现商品尺寸：%s" % "、".join(dim_hits[:5]))
    oz_hits = re.findall(r"\b\d+(?:\.\d+)?\s*(?:oz|ounces?)\b", frontend, re.I)
    if oz_hits and fpath(facts, "dims.net_weight_oz") is None:
        over.append("事实卡无净重，文案出现：%s" % "、".join(oz_hits[:5]))

    NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    NUM_RE = r"\b(?:%s|\d+)\b" % "|".join(NUMW)

    def num_val(s):
        s = s.lower()
        return NUMW.get(s, None) if not s.isdigit() else int(s)

    for m in re.finditer(r"(?i)\b(%s)\s+(?:divided\s+)?(slots?|zones?)\b" % NUM_RE, frontend):
        want = num_val(m.group(1))
        fact = fpath(facts, "structure.zones")
        if want is None:
            continue
        if fact is None:
            over.append("件数声明 %s %s，但事实卡 structure.zones 为 null" % (m.group(1), m.group(2)))
        elif want != int(fact):
            over.append("件数声明 %s %s，事实卡 structure.zones=%s" % (m.group(1), m.group(2), fact))
    for m in re.finditer(r"(?i)\b(%s)\s+(?:suction\s+)?cups?\b" % NUM_RE, frontend):
        want = num_val(m.group(1))
        fact = fpath(facts, "material.suction.qty")
        if want is None:
            continue
        if fact is None:
            over.append("吸盘件数声明 %s，但事实卡 material.suction.qty 为 null" % m.group(1))
        elif want != int(fact):
            over.append("吸盘件数声明 %s，事实卡 material.suction.qty=%s" % (m.group(1), fact))

    # 每条五点至少一个事实锚点（数字 / 材质 / 结构 / 边界）。
    # 依据 07 §4.3 与 copy_config 的 bullet_fact_anchor_min——原先该键无人读，
    # 「整条只有形容词 FAIL」只存在于文档。锚点词表不新造：取事实卡各字段的值，
    # 再经 fact_schema.yaml 的 enums 翻成英文措辞（事实卡是中文填的，不翻的话
    # 英文文案里一个都命中不了，会把每条正常文案误判成空话——2026-11-18 实测踩过）。
    anchor_min = int((cfg.get("decisions") or {}).get("bullet_fact_anchor_min", 1))
    enums = {}
    fs_path = Path(__file__).parent / "fact_schema.yaml"
    if fs_path.exists():
        enums = (load_yaml(fs_path) or {}).get("enums") or {}
    entities = set()
    for p in ("material.body", "material.finish", "material.color", "material.suction.material",
              "material.clip.material", "material.stainless.grade", "structure.drain",
              "structure.shape", "install.methods", "install.positions", "structure.zone_use",
              "surfaces.ok", "surfaces.not_ok", "surfaces.scenes", "trust.warranty"):
        v = fpath(facts, p)
        vals = v if isinstance(v, list) else ([v] if v else [])
        for x in vals:
            words = str(enums.get(str(x), x)).split("/") if isinstance(x, str) else [str(x)]
            for w in words:
                for tok in re.findall(r"[A-Za-z][A-Za-z'\-]+|\d+", str(w)):
                    entities.add(tok.lower())
    # 品类核心词不算事实锚点：'kitchen' / 'sink' 这种词在任何一句水槽文案里都出现，
    # 把它当锚点等于「整条只有形容词」也能过检（2026-11-18 反例实测）。
    # 锚点必须是事实卡里的具体属性值，所以从 P0 词根里剔一遍。
    p0_roots_for_anchor = set()
    for r in library:
        if (r.get("prio") or "").strip() == "P0":
            p0_roots_for_anchor.update(stem(t) for t in tokens(r.get("keyword") or "", stop))
    entities = {e for e in entities if stem(e) not in p0_roots_for_anchor}
    no_anchor = []
    for i, bl in enumerate(bullets, 1):
        if not bl.strip():
            continue
        has_num = re.search(r"(?i)\b(?:%s|\d+)\b" % "|".join(NUMW), bl)
        has_ent = any(e in bl.lower() for e in entities if len(e) >= 2)
        if (1 if has_num else 0) + (1 if has_ent else 0) < anchor_min:
            no_anchor.append("第 %d 点" % i)
    if no_anchor:
        over.append("整条只有形容词、无事实锚点：%s" % "、".join(no_anchor))

    if over:
        fail("C9 事实越权", "；".join(over[:6]))
        for msg in over[:8]:
            issue(sev["facts_units"], "C9", "全篇", "", msg, "删数值，或补事实卡后重跑 check_facts")
    else:
        ok("C9 事实越权", "重量%s｜尺寸与件数与事实卡一致｜五点事实锚点均 ≥%d 个"
           % ("含实测" if load_tested else "已禁 lbs/kg", anchor_min))

    # ---------- C10 亮点重复标题 ----------
    # 用户 2026-11-17 裁决：允许重复，上限 2 个，且每个须过「删除测试」（删掉后句子是否还成立）
    t_stems = set(stems(title, stop))
    h_stems = set(stems(high, stop))
    overlap = sorted(t_stems & h_stems)
    allow = int((cfg.get("decisions") or {}).get("highlight_repeat_max", 2))
    if len(overlap) > allow:
        warn("C10 亮点重复", "重复标题实义词 %d 个，超上限 %d：%s"
             % (len(overlap), allow, "、".join(overlap[:8])))
        issue(sev["highlights_overlap"], "C10", "highlights", high,
              "重复标题实义词 %d 个，超上限 %d" % (len(overlap), allow), "换同义词变体或删掉凑数词")
    elif overlap:
        ok("C10 亮点重复", "重复标题实义词 %d 个（上限 %d）：%s｜删除测试脚本不判，需人工核（08 §六）"
           % (len(overlap), allow, "、".join(overlap)))
    else:
        ok("C10 亮点重复", "亮点与标题零实义词重叠")

    # ---------- C11 描述密度（只报数，不判 WARN，2026-11-17 改）----------
    # 为什么不再判：target 收的是 P0/P1 全部 token，而这些恰恰是描述里的普通名词
    # （sponge / holder / sink / kitchen）。一篇 100 词的描述出现 20 个是品类必然，
    # 不是堆词。真正的堆词由 C4（整短语重复）和 C5（词根重复）兜住。
    target = set()
    for r in library:
        if (r.get("prio") or "") in ("P0", "P1"):
            target.update(stem(t) for t in tokens(r.get("keyword") or "", stop))
    d_tokens = stems(desc, stop)
    hits = sum(1 for t in d_tokens if t in target)
    min_words = emb.get("desc_density_min_words", 100)
    if len(d_tokens) < min_words:
        ok("C11 描述密度", "描述仅 %d 词 < %d，不评估（小样本会失真）"
           % (len(d_tokens), min_words))
    else:
        density = hits / (len(d_tokens) / 100.0)
        ok("C11 描述密度", "%.1f 个目标词/100 词，描述 %d 词（仅报数，堆词看 C4/C5）"
           % (density, len(d_tokens)))

    # ---------- C12 官方标题与促销边界（2026-11-17 新增）----------
    # 依据：官方标题指南 GYTR6SYGFA5E3EQC + 要点指南 GX5L8BF8GLMML6CX
    # 官方口径：不得全大写、不得含特殊字符、须为名词短语（非完整句子）、
    #          不得含促销与卖家信息、尺寸与颜色不得进标题（除非是变体）。
    # 「规格槽」专指变体规格（尺码/件数/容量），不是产品尺寸——本品无变体，
    # 所以尺寸进标题属违规，只能进五点或描述作适配说明。
    brand = str(((facts.get("meta") or {}).get("brand") or "")).strip().lower()
    hard, soft = [], []

    if st_cfg.get("title_forbid_all_caps", True):
        minlen = st_cfg.get("title_all_caps_min_len", 4)
        # caps_allow 原先无人读：RV / PC / UV / BPA / ABS 这类行业通用缩写会被告警。
        # 豁免表在 copy_config.disallowed.caps_allow，与颜色词同属配置真源。
        allow_caps = set(str(x).lower() for x in dis.get("caps_allow", []))
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", title):
            core = re.sub(r"[^A-Za-z]", "", w)
            if len(core) >= minlen and core.isupper() and core.lower() != brand:
                if core.lower() in allow_caps:
                    continue
                hard.append(("全大写", w))

    for ch in st_cfg.get("title_forbid_special_chars", []):
        if ch in title:
            hard.append(("特殊字符", ch))

    if st_cfg.get("title_forbid_end_punct", True) and re.search(r"[.!?,;:]\s*$", title.strip()):
        hard.append(("句末标点", title.strip()[-1:]))

    if st_cfg.get("bullet_forbid_promo", True):
        for w in dis.get("promo", []):
            if re.search(r"\b" + re.escape(w) + r"\b", frontend, re.I):
                hard.append(("促销语", w))

    # 卖家信息：URL / 邮箱 / 电话，官方明列不得进标题
    if re.search(r"https?://|www\.|\S+@\S+\.\w+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", title, re.I):
        hard.append(("卖家信息", re.search(
            r"https?://\S*|www\.\S*|\S+@\S+\.\w+|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
            title, re.I).group(0)))

    # 非拉丁字符：美国站英文标题不应出现（emoji 已单列 FAIL，此处不重复报）
    if st_cfg.get("title_ascii_only", True):
        for ch in sorted(set(re.findall(r"[^\x00-\x7F]", title))):
            if not re.match(EMOJI_RE, ch):
                soft.append(("非拉丁字符", ch))

    if st_cfg.get("title_measure_warn", True):
        for m in re.findall(r"\b\d+(?:\.\d+)?\s*(?:in|inch|inches|cm|mm|oz|lbs?|kg|qt|gal)\b", title, re.I):
            soft.append(("尺寸重量", m.strip()))

    if st_cfg.get("title_color_warn", True):
        for w in dis.get("title_color_words", []):
            if re.search(r"\b" + re.escape(w) + r"\b", title, re.I):
                soft.append(("颜色词", w))

    # 标题内同一单词超限。依据：官方 2025 标题政策「同一单词不超过两次，冠词介词连词除外」
    wmax = st_cfg.get("title_same_word_max", 2)
    if wmax:
        exempt = set(str(w).lower() for w in st_cfg.get("title_exempt_words", []))
        if brand:
            exempt.add(brand)
        seen = {}
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", title):
            lw = w.lower()
            if lw in exempt:
                continue
            seen[lw] = seen.get(lw, 0) + 1
        for w, n in sorted(seen.items(), key=lambda x: -x[1]):
            if n > wmax:
                hard.append(("单词重复", "%s×%d" % (w, n)))

    # emoji：官方要点 requirements 页明列禁项，全字段扫
    if st_cfg.get("frontend_forbid_emoji", True):
        for ch in sorted(set(re.findall(EMOJI_RE, frontend))):
            hard.append(("emoji", ch))

    # 占位内容（N/A、TBD）：官方要点 requirements 页明列
    for w in dis.get("placeholder", []):
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", frontend, re.I):
            hard.append(("占位内容", w))

    # 不必要缩写（qty / pkg / approx.）：官方要点 requirements 页明列
    for w in dis.get("abbrev", []):
        if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", frontend, re.I):
            soft.append(("不必要缩写", w))

    # 数字与单位之间缺空格（8.5in → 8.5 in）：官方要点 requirements 页
    if st_cfg.get("unit_space_required", True):
        for m in re.findall(r"\b\d+(?:\.\d+)?(?:in|inch|inches|cm|mm|oz|lbs?|kg|qt|gal|ft)\b", frontend):
            soft.append(("单位缺空格", m))

    if hard:
        msg = "；".join("%s %s" % (k, v) for k, v in hard[:6])
        if soft:
            msg += "｜另有 %d 处待确认：%s" % (len(soft), "、".join("%s %s" % (k, v) for k, v in soft[:4]))
        fail("C12 官方边界", msg)
        for k, v in hard[:12]:
            issue(sev.get(HARD_SEV.get(k, "title_format"), "FAIL"), "C12",
                  HARD_LOC.get(k, "title"), v, k, "官方明列禁项")
        for k, v in soft[:8]:
            issue(sev.get(SOFT_SEV.get(k, "title_measure"), "WARN"), "C12",
                  "title" if k in ("尺寸重量", "颜色词", "非拉丁字符") else "全篇", v, k,
                  "非变体请移到五点或描述" if k in ("尺寸重量", "颜色词") else "按官方写法改")
    elif soft:
        warn("C12 官方边界", "含 %d 处需确认：%s"
             % (len(soft), "、".join("%s %s" % (k, v) for k, v in soft[:6])))
        for k, v in soft[:8]:
            issue(sev.get(SOFT_SEV.get(k, "title_measure"), "WARN"), "C12",
                  "title" if k in ("尺寸重量", "颜色词", "非拉丁字符") else "全篇", v, k,
                  "非变体请移到五点或描述" if k in ("尺寸重量", "颜色词") else "按官方写法改")
    else:
        ok("C12 官方边界", "标题无全大写/特殊字符/句末标点/单词超限，无促销语、尺寸与颜色；全篇无 emoji、占位内容")

    return report(outdir, cfg, args.no_write)


def report(outdir, cfg, no_write):
    name = cfg["outputs"]["selfcheck"]
    lines = ["文案交付自检", "=" * 60, ""]
    for level, item, msg in CASES:
        lines.append("[%s] %s  %s" % (level, item, msg))
    fails = sum(1 for c in CASES if c[0] == "FAIL")
    warns = sum(1 for c in CASES if c[0] == "WARN")
    lines.append("")
    lines.append("合计 %d 项：PASS %d / WARN %d / FAIL %d"
                 % (len(CASES), sum(1 for c in CASES if c[0] == "PASS"), warns, fails))
    if fails:
        lines.append("结论：不许交付，先改 FAIL 项。")
    elif warns:
        lines.append("结论：可交付，WARN 项需在口径声明里逐条说明。")
    else:
        lines.append("结论：全部通过。")

    print("\n".join(lines))

    if no_write:
        return 1 if fails else 0

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / name).write_text("\n".join(lines), encoding="utf-8")

    with open(outdir / cfg["outputs"]["coverage"], "w", encoding="utf-8-sig", newline="") as f:
        # 表头中文、机器键英文（与 SP-01 一致：id/指标用英文，说明列用中文）
        cols = [("keyword", "keyword"), ("prio", "prio"), ("W", "W"), ("covered", "是否覆盖"),
                ("where", "落位字段"), ("form", "命中形式"), ("layer", "词层级"),
                ("reason", "未覆盖归因"), ("audit", "归因可核"), ("verdict", "判定")]
        w = csv.writer(f)
        w.writerow([c[1] for c in cols])
        for row in COVER:
            w.writerow([row.get(c[0], "") for c in cols])

    with open(outdir / cfg["outputs"]["issues"], "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "check", "位置", "原文", "问题", "建议"])
        w.writeheader()
        w.writerows(ISSUES)

    print("\n产物：%s / %s / %s" % (outdir / name, cfg["outputs"]["coverage"], cfg["outputs"]["issues"]))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
