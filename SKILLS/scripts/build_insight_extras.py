#!/usr/bin/env python3
"""评论高频词 + 竞品痛点矩阵：补 vendor/amz-review-analysis 交付簿里缺的两块。

vendor 的 build_delivery 出的是「语义分类频次」（一级/二级命中条数），
不是逐词统计；品牌切片也只到差评一级，没有 ASIN 级痛点归属。
本脚本读 reviews_master.xlsx，单独出一本，不改 vendor 产出。

输出 sheet:
    00_说明
    01_高频词_全样本     全样本 n-gram 词频
    02_高频词_差评       差评组词频
    03_高频词_好评       好评组词频
    04_高频词_差异度     差评相对好评的超额倍数（lift），找差评驱动词
    05_竞品痛点_ASIN_L1  每个 ASIN 的差评一级分布 + 差评率
    06_竞品痛点_ASIN_L2  长表：ASIN × 二级，带占本 ASIN 差评比与专属度
    07_竞品痛点_品牌_L2  长表：品牌 × 二级，同上
    08_痛点归属           每个痛点归谁最重

用法:
    python build_insight_extras.py --master "<cat>/3 Data/reviews_master.xlsx" \
        --out "<cat>/4 Reports/Sponge-Holder-洞察补充-20261113.xlsx" \
        --root-map "<cat>/../07b-词根映射.csv"
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True, name="PingFang SC", size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
ALT_FILL = PatternFill("solid", fgColor="F7F9FC")

STOP = set("""
a an the and or but if then than that this these those there here
i me my mine we us our you your he she it its they them their
is are was were be been being am do does did doing done have has had having
will would can could should may might must shall
of to in on at by for with from into onto over under about as up down out off
not no nor so very too just also only even still yet again ever never
one two three first second
it's i'm don't doesn't didn't isn't aren't wasn't weren't can't couldn't won't wouldn't
im ive id ill youre youve theyre thats whats dont doesnt didnt isnt wasnt
get got gets getting got make makes made making
really quite pretty much more most less least
thing things something anything everything nothing way lot bit
like want wanted need needed buy bought purchase purchased use used using
product item order ordered amazon
after all see thought times past same ok okay within back now once every any
some own other another both each few many whatever
last tried put well back around enough something
""".split())

# 差评里高频但不指向具体痛点的词，单独标类，方便过滤
EMOTION = {
    "broke", "broken", "break", "breaks", "poor", "weak", "disappointed", "disappointing",
    "waste", "junk", "trash", "sucks", "suck", "horrible", "bad", "terrible", "annoying",
    "frustrating", "cheap", "flimsy", "unhappy", "regret", "return", "returning",
    "returned", "useless", "worthless", "sad", "bummed", "hate", "fail", "failed",
    "fails", "problem", "problems", "issue", "issues",
}
TIME = {
    "within", "minutes", "minute", "month", "months", "day", "days", "week", "weeks",
    "year", "years", "hour", "hours", "overnight", "daily",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
BR_RE = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return BR_RE.sub(" ", text or "").replace("&amp;", "&")


def tokens(text: str) -> list[str]:
    """抽词 → 弯引号归一 → 先过停用词 → 再去复数。

    停用词必须在去复数之前判：否则 does→doe、works→work 会绕过停用表。
    """
    out = []
    for t in TOKEN_RE.findall(clean(text).lower()):
        t = t.strip("'’-").replace("’", "'").replace("‘", "'")
        if len(t) < 2 or t in STOP:
            continue
        if len(t) >= 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "es", "'s")):
            t = t[:-1]
        if t in STOP:
            continue
        out.append(t)
    return out


def word_class(tok: str, root_map: dict[str, str]) -> str:
    if tok in EMOTION:
        return "情绪词"
    if tok in TIME:
        return "时间词"
    if tok in root_map:
        return {"共性": "品类共性词", "品类": "品类词", "属性": "属性词"}.get(root_map[tok], "其他")
    return ""


def ngrams(toks: list[str], n: int) -> list[tuple[str, ...]]:
    """n-gram；含停用词或纯数字的直接丢弃，保证短语可读。"""
    res = []
    for i in range(len(toks) - n + 1):
        g = tuple(toks[i : i + n])
        if any(w in STOP for w in g):
            continue
        res.append(g)
    return res


def load_root_map(path: Path | None) -> dict[str, str]:
    """读项目既有的词根映射，给高频词打「共性/品类/属性」标签。"""
    if not path or not path.exists():
        return {}
    out = {}
    try:
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                tok = (r.get("token") or "").strip().lower()
                if tok:
                    out[tok] = (r.get("root_type") or "").strip()
    except Exception:
        return {}
    return out


def read_master(path: Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["reviews_master"]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = [str(h) if h is not None else "" for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    neg_cols = [h for h in header if h.startswith("差评|")]
    pos_cols = [h for h in header if h.startswith("好评|")]
    recs = []
    for r in rows[1:]:
        if not r or r[idx.get("row_id", 0)] is None:
            continue
        rec = {
            "row_id": r[idx["row_id"]],
            "asin": r[idx.get("ASIN", 0)],
            "brand": r[idx.get("品牌", 0)] or "（未标注）",
            "star": r[idx.get("星级", 0)],
            "mix": r[idx.get("sentiment_mix", 0)] or "",
            "content": clean(r[idx.get("内容", 0)] or ""),
            "title": clean(r[idx.get("标题", 0)] or ""),
        }
        rec["neg"] = {c: r[idx[c]] for c in neg_cols if r[idx[c]]}
        rec["pos"] = {c: r[idx[c]] for c in pos_cols if r[idx[c]]}
        recs.append(rec)
    return recs, neg_cols, pos_cols


def freq_table(recs, field: str):
    """返回 {ngram: (doc_freq, polarity)}，doc_freq = 命中该词的评论条数。"""
    df = Counter()
    n = 0
    for rec in recs:
        text = (rec["title"] + ". " + rec["content"]).strip()
        if not text or len(text) < 4:
            continue
        n += 1
        toks = tokens(text)
        seen = set()
        for k in (1, 2, 3):
            for g in ngrams(toks, k):
                seen.add(g)
        for g in seen:
            df[g] += 1
    return df, n


def write_sheet(wb, title: str, header: list[str], rows: list[list]):
    ws = wb.create_sheet(title)
    ws.append(header)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in r:
            c.alignment = WRAP
        if r[0].row % 2 == 0:
            for c in r:
                c.fill = ALT_FILL
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        longest = 8
        for c in col[:120]:
            if c.value is None:
                continue
            longest = max(longest, min(48, len(str(c.value))))
        ws.column_dimensions[letter].width = longest + 2
    return ws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root-map", default="")
    ap.add_argument("--min-df", type=int, default=3, help="差异度页的最小命中条数")
    args = ap.parse_args()

    master = Path(args.master).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    root_map = load_root_map(Path(args.root_map).expanduser() if args.root_map else None)

    recs, neg_cols, pos_cols = read_master(master)

    neg_recs = [r for r in recs if r["mix"] == "差评"]
    pos_recs = [r for r in recs if r["mix"] == "好评"]

    df_all, n_all = freq_table(recs, "all")
    df_neg, n_neg = freq_table(neg_recs, "neg")
    df_pos, n_pos = freq_table(pos_recs, "pos")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # ---------- 00 说明 ----------
    write_sheet(
        wb,
        "00_说明",
        ["项目", "内容"],
        [
            ["数据源", f"{master.name}；共 {len(recs)} 条评论"],
            ["口径", "词频按「命中该词的评论条数（document frequency）」计，不是出现次数；同一评论内重复出现只算 1"],
            ["分词", "英文按 [A-Za-z] 抽词，去停用词；n-gram 取 1–3 词，含停用词的短语直接丢弃"],
            ["分组", "差评组 = sentiment_mix 为「差评」的评论；好评组 = 「好评」；「混合」与「信息不足」不进入差异度对比"],
            ["差异度(lift)", "差评组覆盖率 ÷ 好评组覆盖率。>1 表示该词在差评里更常出现，>2 视为强差评驱动词"],
            ["词类", "沿用 07b-词根映射.csv 的 共性/品类/属性 标注；情绪词与时间词由本脚本另标"],
            ["注意", "样本为分层抓取（1–3 星与 4–5 星 1:1），覆盖率不可当类目大盘；看相对差异，不看绝对值"],
            ["差异度注意", "不要把 lift 高但命中只有 1–2 条的词当结论；默认只看 >= 3 条且按差评命中排序"],
            ["痛点口径", "「差评命中条数」= 该 ASIN 下任意差评列非空的评论数，含 sentiment_mix 为「混合」的评论"],
            ["占比不互斥", "一条评论可同时命中多个痛点，所以「占本 ASIN 差评比」逐行相加会超过 1，这是正常的"],
            ["专属度", "= 该 ASIN 该痛点占本 ASIN 差评点的比例 ÷ 该痛点占全样本差评点的比例。>1.5 视为该 ASIN 的招牌问题"],
            ["样本量提醒", "B0G82BCVKN 仅 29 条（负面总量只有 9 条），专属度易被小样本放大，读的时候打个折"],
        ],
    )

    hdr_freq = ["词/短语", "词数", "命中条数", "覆盖率", "词类"]

    def rows_of(df: Counter, n: int, limit: int = 200):
        out_rows = []
        for g, c in df.most_common(limit):
            phrase = " ".join(g)
            rtype = word_class(g[0], root_map) if len(g) == 1 else ""
            out_rows.append([phrase, len(g), c, round(c / n, 4) if n else 0, rtype])
        return out_rows

    write_sheet(wb, "01_高频词_全样本", hdr_freq + ["组样本数"], [[*r, n_all] for r in rows_of(df_all, n_all)])
    write_sheet(wb, "02_高频词_差评", hdr_freq + ["差评组条数"], [[*r, n_neg] for r in rows_of(df_neg, n_neg)])
    write_sheet(wb, "03_高频词_好评", hdr_freq + ["好评组条数"], [[*r, n_pos] for r in rows_of(df_pos, n_pos)])

    # ---------- 04 差异度 ----------
    lift_rows = []
    for g, c_neg in df_neg.items():
        if c_neg < args.min_df:
            continue
        c_pos = df_pos.get(g, 0)
        r_neg = c_neg / n_neg if n_neg else 0
        r_pos = c_pos / n_pos if n_pos else 0
        # 加 0.5 平滑，避免零命中时 lift 变成无意义的哨兵值
        lift = ((c_neg + 0.5) / n_neg) / ((c_pos + 0.5) / n_pos) if n_neg and n_pos else 0
        if lift < 1.2:
            continue
        wclass = word_class(g[0], root_map) if len(g) == 1 else ""
        lift_rows.append(
            [" ".join(g), len(g), c_neg, round(r_neg, 4), c_pos, round(r_pos, 4), round(lift, 2), wclass]
        )
    lift_rows.sort(key=lambda x: (-x[2], -x[6]))
    write_sheet(
        wb,
        "04_高频词_差异度",
        ["词/短语", "词数", "差评命中", "差评覆盖率", "好评命中", "好评覆盖率", "差异度lift", "词类"],
        lift_rows[:200],
    )

    # ---------- 竞品痛点 ----------
    neg_l1 = sorted({c.split("|")[1] for c in neg_cols})
    neg_l2 = sorted({c for c in neg_cols})

    asins = sorted({r["asin"] for r in recs if r["asin"]})
    brands = sorted({r["brand"] for r in recs})

    # 05: ASIN × L1
    hdr5 = ["ASIN", "品牌", "评论数", "差评命中条数", "差评率"] + neg_l1
    rows5 = []
    for a in asins:
        ar = [r for r in recs if r["asin"] == a]
        hit = [r for r in ar if r["neg"]]
        row = [a, ar[0]["brand"], len(ar), len(hit), round(len(hit) / len(ar), 3) if ar else 0]
        for l1 in neg_l1:
            row.append(sum(1 for r in hit if any(k.split("|")[1] == l1 for k in r["neg"])))
        rows5.append(row)
    write_sheet(wb, "05_竞品痛点_ASIN_L1", hdr5, rows5)

    # 06/07: 长表 L2
    def l2_long(group_field: str, keys: list[str]):
        total_hits = sum(1 for r in recs if r["neg"])
        total_by_col = Counter()
        for r in recs:
            for c in r["neg"]:
                total_by_col[c] += 1
        rows = []
        for key in keys:
            grp = [r for r in recs if r[group_field] == key]
            grp_hit = [r for r in grp if r["neg"]]
            if not grp_hit:
                continue
            n_grp = len(grp_hit)
            by_col = Counter()
            for r in grp_hit:
                for c in r["neg"]:
                    by_col[c] += 1
            for c, cnt in by_col.most_common():
                pol, l1, l2 = (c.split("|") + ["", ""])[:3]
                share = cnt / n_grp
                base = total_by_col[c] / total_hits if total_hits else 0
                own = (share / base) if base else 0
                rows.append([key, n_grp, l1, l2, cnt, round(share, 3), round(base, 3), round(own, 2)])
        rows.sort(key=lambda x: (x[0], -x[4], -x[7]))
        return rows

    hdr6 = ["ASIN", "该 ASIN 差评命中条数", "一级", "二级", "命中条数", "占本 ASIN 差评比", "占全样本比", "专属度"]
    write_sheet(wb, "06_竞品痛点_ASIN_L2", hdr6, l2_long("asin", asins))

    hdr7 = ["品牌", "该品牌差评命中条数", "一级", "二级", "命中条数", "占本品牌差评比", "占全样本比", "专属度"]
    write_sheet(wb, "07_竞品痛点_品牌_L2", hdr7, l2_long("brand", brands))

    # 08: 痛点归属 —— 每个二级归谁最重
    rows6 = l2_long("asin", asins)
    by_pain = defaultdict(list)
    for r in rows6:
        by_pain[(r[2], r[3])].append((r[4], r[0], r[5], r[7]))
    rows8 = []
    for (l1, l2), items in sorted(by_pain.items(), key=lambda kv: -sum(i[0] for i in kv[1])):
        items.sort(reverse=True)
        top = items[0]
        total = sum(i[0] for i in items)
        rows8.append([l1, l2, total, top[1], top[0], round(top[2], 3), round(top[3], 2)])
    write_sheet(
        wb,
        "08_痛点归属",
        ["一级", "二级", "全样本命中", "最集中 ASIN", "该 ASIN 命中", "占该 ASIN 差评比", "专属度"],
        rows8,
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"wrote {out}")
    print(f"  评论 {len(recs)} 条 / 差评组 {n_neg} / 好评组 {n_pos}")
    print(f"  词表 全样本 {len(df_all)} · 差评 {len(df_neg)} · 好评 {len(df_pos)}")
    print(f"  差异词（>= {args.min_df} 条且 lift>1）{len(lift_rows)}")


if __name__ == "__main__":
    main()
