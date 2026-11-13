# 30 · 用户洞察（输出型模块）

承接架构图处理层的「用户洞察」整格，产出输出层的用户画像 / 使用场景 / 痛点。

## 现状：已跑通，主干预用 `amz-review-analysis`

2026-11-13 用 sponge-holder（8 ASIN / 309 条）全流程验证通过，产出 14 sheet Excel + HTML 看板。
见 `调研/sponge-holder/review-analysis/`。

### 为什么用它当主干
六张总结卡与导图里的六个小方块几乎 1:1 对应：

| 导图格子 | 交付物里的位置 |
|---|---|
| 好评原因占比 | 03/04_二级频次，好评一级+二级计数 |
| 差评原因占比 | 同上，差评侧 |
| 使用场景分析 | 09_评论总结「使用场景」+ 10_详细分析 03/04 |
| 购买动机 | 09_评论总结「购买理由」 |
| 未满足需求 | 09_评论总结「买家期待」+ 10_详细分析 05 |
| 用户画像 | 09_评论总结「人群画像」 |
| 痛点 → 新品方向 | 11_产品方向 |
| 评论高频词 | **不在 vendor 交付簿里**，由 `build_insight_extras.py` 另出，见下 |
| 竞品痛点分析 | 06/07_切片只有计数与一句话，痛点归属由 `build_insight_extras.py` 另出 |

> 注意：vendor 的 03/04_二级频次是「语义分类命中条数」，**不是逐词统计**。
> 两者不能互相替代——它回答「哪类问题多」，不回答「买家具体怎么说」。

### 补充输出：`scripts/build_insight_extras.py`

vendor 不改，另出一本 `<类目>-洞察补充-<日期>.xlsx`，9 个 sheet：

| sheet | 内容 |
|---|---|
| 01/02/03_高频词 | 全样本 / 差评组 / 好评组 的 1–3 词 n-gram，按「命中该词的评论条数」计 |
| 04_高频词_差异度 | 差评覆盖率 ÷ 好评覆盖率（加 0.5 平滑），找差评驱动词；带情绪词/时间词/属性词标注 |
| 05_竞品痛点_ASIN_L1 | 每个 ASIN 的差评一级分布 + 差评率 |
| 06_竞品痛点_ASIN_L2 | 长表：ASIN × 二级，带占本 ASIN 差评比与专属度 |
| 07_竞品痛点_品牌_L2 | 同上，按品牌 |
| 08_痛点归属 | 每个二级痛点「归谁最重」，直接回答竞品痛点 |

专属度 = 该对象该痛点占其差评点的比例 ÷ 该痛点占全样本差评点的比例，>1.5 视为该对象的招牌问题。

**词频口径注意**：`suction` 这种品类属性词在好评差评里都高频出现（sponge-holder 实测 lift 只有 1.25），
单看词频会得出「吸盘是主因」的浅结论；真正有区分力的是 `adhesive`(7.09)、`broke`(24.95)、
`month`(3.39)、`fell`/`falling`(5.85) 这类。**词频负责找线索，语义分类负责定性。**

### 数据来源：走 MCP，不走手工导出

vendor skill 原始流程要求卖家精灵后台导出 xlsx。我们改用 `mcp__ss_mcp__review` 直采，
中间用两个适配脚本落成它认的同构表：

```
1. 抓取      mcp__ss_mcp__review（1–3 星 / 4–5 星分层，单页上限 20 条）
             → 5 Work/*.jsonl（紧凑格式：asin,t,c,s,d,a,k,l,v,vi,img）
2. 落表      scripts/jsonl_to_review_xlsx.py   → 2 Reviews/<ASIN>-US-<n>.xlsx
3. 产品表    scripts/build_products_xlsx.py    → 1 Products/US.xlsx（可从竞品库 CSV + overrides 补字段）
4. 未覆盖字段  评论链接 / 评论人主页 / 头像地址 / 所属国家 / 红人计划链接
              MCP 不返回，落空值。merge_reviews.py 对空评论链接有 sha1 兜底，
              空 所属国家 不会被误判为「非美」。
```

然后照 vendor SKILL 跑：merge_reviews → sample_reviews → apply_annotations →
export_pending → merge_columns → taxonomy_stats → build_delivery。

### 实测经验（下次直接照做）

- **单页上限是 20 条**，不是 20 以上的任意值。想拿 40 条负评要翻 2 页。
- **一级分类一开始写了 128 个二级，平均命中 1 次**，等于没聚类。做完第一波必须跑一次
  `merge_columns`，把「同一语义的不同措辞」并到保留列。sponge-holder 从 128 收敛到 48，
  这才是可读的分类树。**这一步不能省。**
- 每个 ASIN 取 20 负 + 20 正即够建立稳定树；样本要声明是分层抓取，差评占比不可外推。
- 分类树的 L1 建议控制在 20 个以内（sponge-holder 收在 19 个：差评 10 + 好评 9）。

## 两个明确缺口

### 1. QA 分析（购买顾虑）——完全没覆盖
vendor skill 只处理评论。导图里的「QA分析 → 购买顾虑」要另做。可选来源：
`mcp__ss_mcp__review` 里 1–2 星提到的「买之前担心什么」；ss_mcp 目前无 Q&A 接口，
站内 Q&A 需要用户上传。

### 2. 评论图片不参与分析
vendor 只存 `图片地址` / `图片数量` 做切片统计，Agent 没有读图环节。
导图要的「使用场景分析（结合评论图片）」需要自己加一步：把 `flag_has_image=Y` 的行
筛出来，逐张读图补充场景证据。

## 输出层映射

- 用户画像 / 使用场景 / 痛点 → 09_评论总结三张卡
- 痛点占比 → `40-selling-point` 的 P 分量（taxonomy 的 n_reviews 直接可用）
- 已验证卖点 → `50-copy` 标题与五点
- 新品方向 → `90-main-image` 主图 brief

## License 边界

这个 skill 是自定义协议（非 MIT）：个人与团队内部免费，禁止转卖、改名贴牌、
打包进付费课或对客交付包。它已原样收录进仓库的 `SKILLS/skills/amz-review-analysis`
（本地对应 `skills/vendor/amz-review-analysis`），作者信息与 LICENSE 一并保留、未做删改。
若产出要进对客交付，需向作者（微信 andylee610）拿书面授权。
