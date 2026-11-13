---
name: "keyword-research"
description: "亚马逊关键词调研 v2：四路采集（竞品ASIN库反查 / 竞品标题词频 / 竞品Listing词频 / 前台自动补全）→ 合并补齐指标 → 权重打分 → 输出可直接喂给文案的交接单。用户提供 /keyword-research {ASIN} {SITE}，或说“调研这个词”“挖竞品词”“给我词库做标题”时触发。"
---

> **本机适配说明（重要）**
> 本 skill 原本基于 **Sorftime MCP** 编写。本机只接入卖家精灵 MCP（`mcp__ss_mcp__`）。
> 文中所有数据工具已改为卖家精灵等价工具；Sorftime 专有接口见 `../amazon-base/MCP映射表.md`。
> 口径差异（搜索量样本、字段名）必须在报告中注明，不要混用两套数据。

# 关键词调研 v2：四路采集 → 权重打分 → 直接喂给文案

## 0. 这个版本解决什么问题

旧版只在「一个 ASIN 的流量词」里打转，产出是"一堆词"，没法回答"哪个该放标题第一位"。

v2 改成**四路采集 + 统一打分**，输出是一张**按权重排序的词表**和一份**交接单**，文案环节直接照着填，不需要二次判断。

一句话：**词库不是词表，是排好序的投放清单。**

---

## 1. 输入

| 输入 | 必填 | 说明 |
|---|---|---|
| 竞品 ASIN | ✅ 1-3 个 | 这些是**锚点**，权重最高（L0，×3） |
| 站点 | ✅ | US / UK / DE / FR / IT / ES / JP / CA |
| 自家 ASIN | 可选 | 有就一起跑，用来对比"我有它没有"的词 |
| 核心卖点 | 可选 | 供应链给的差异化点，用来算相关性 R2 |
| 类目 nodeIdPath | 可选 | 没有就用竞品 ASIN 反推 |

缺竞品 ASIN 时，先问用户要，或从自家 ASIN 的关联商品里找 3 个。**不要凭空生成 ASIN。**

---

## 2. 总流程

```
① 竞品库反查 ──┐
② 标题词频   ──┤
③ Listing词频 ──┼→ 合并去重 → 补指标(keyword_miner) → 权重打分 → 输出三件套
④ 自动补全   ──┘
```

四路是**并集关系**，不是替代关系。任何一路缺数据就标 `DATA_MISSING`，不要用其它路的词硬凑。

---

## 3. 方法一：竞品 ASIN 库反查

**目的**：以用户给的 ASIN 为锚点，向外扩出一个竞品池。池子越大，后面词频越可靠。

### 步骤

```python
# L0：用户提供的 ASIN，权重 3
anchors = [用户给的 ASIN]

# L1：锚点的直接竞品
for a in anchors:
    mcp__ss_mcp__asin_competitor({"marketplace":"US","asin":a,"size":20})

# L2：L1 里销量最高的 3 个，再往下扩一层（只扩一层，别递归）
for a in top3_of_L1:
    mcp__ss_mcp__asin_competitor({"marketplace":"US","asin":a,"size":20})
```

**筛选条件**（进池子前先过滤，避免噪声）：

- 同站点、同品类（类目路径前 3 段一致）
- 月销 ≥ 100（`units` 字段）
- 排除：明显不同形态的（如本品是 wall mount，竞品是 freestanding）→ 但**保留**，标记为"形态差异"，用于后面算差异化
- 排除：品牌自有变体（同品牌不同 ASIN）→ 单独归组，不参与词频

### 输出：竞品池表

| ASIN | 品牌 | 层级 | 月销 | 价格 | 评分 | 评分数 | 形态 | 备注 |
|---|---|---|---|---|---|---|---|---|

层级：L0 = 用户提供（权重 3），L1 = 一等关联（权重 1），L2 = 二等关联（权重 0.5）。

**池子规模建议 8-15 个**。少于 5 个，词频不可信，要在报告里注明样本不足。

---

## 4. 方法二：竞品标题词频

**目的**：标题是竞品最浓缩的关键词选择，词频 = 行业共识。

### 步骤

1. 对池子里每个 ASIN 调 `mcp__ss_mcp__asin_detail`，拿 `title`
2. 汇总成 JSON：

```json
[
  {"asin":"B0XXXX","level":0,"title":"..."},
  {"asin":"B0YYYY","level":1,"title":"..."}
]
```

3. 跑词频脚本：

```bash
python scripts/freq.py products.json --weight-l0 3 --weight-other 1 --min-asin 2 --top 100
```

### 权重规则（关键）

| 来源 | 权重 |
|---|---|
| 用户提供的 ASIN（L0） | **×3** |
| 其它竞品（L1） | ×1 |
| 二等关联（L2） | ×0.5 |

即：**用户给的 ASIN 说三遍，别人说一遍。** 这样既尊重用户判断，又不至于被单个 ASIN 带偏。

脚本内部还会叠加：
- 字段权重：标题 ×3、五点 ×2、描述 ×1
- IDF：覆盖越广的词越像行业通用词，权重适度回收

### 输出

`freq.csv`，列：`word / weighted_score / asin_count / coverage / l0_asin_count / in_title / in_bullets / in_description`

**怎么读**：
- `l0_asin_count ≥ 1` 且 `coverage` 高 → 核心词，必进标题
- `l0_asin_count = 0` 但 `coverage` 高 → 行业通用词，进 Highlights 或五点
- `coverage < 0.3` 且 `l0_asin_count ≥ 1` → **差异化词**，这是 Highlights 的料（见第 8 节）

---

## 5. 方法三：竞品 Listing 词频

**目的**：标题只有 75 字符，装不下竞品真实的表达方式。五点 + 描述里藏着"买家语言"。

### 步骤

同样用 `asin_detail`，但这次取 `bullets`（五点）和 `description`：

```json
[
  {"asin":"B0XXXX","level":0,
   "title":"...",
   "bullets":["...","..."],
   "description":"..."}
]
```

跑同一个脚本，字段权重会自动生效（标题 3 / 五点 2 / 描述 1）。

### 与标题词频的区别（重要）

| | 标题词频 | Listing 词频 |
|---|---|---|
| 反映 | 竞品的**关键词取舍** | 竞品的**卖点表达** |
| 高频词偏向 | 品类词、属性词 | 痛点词、场景词、证据词 |
| 主要用途 | 标题、Highlights | 五点、A+、QA |

**只看标题会漏掉一半**：一个竞品可能标题里写 "Heavy Duty"，五点里才说 "holds up to 30 lbs"——后者才是买家真正搜的。

---

## 6. 方法四：前台自动补全

**目的**：拿到真实买家正在输入的词，尤其是长尾和问题型搜索。这是唯一能反映"当下搜索行为"的免费数据源。

### 接口

```
https://completion.amazon.com/api/2017/suggestions?mid={市场ID}&alias=aps&prefix={前缀}
```

用 `web_fetch` 调用（**bash 里没有外网，只能用 web_fetch**）。

### 市场 ID

| 站点 | mid |
|---|---|
| US | ATVPDKIKX0DER |
| UK | A1F83G8C2ARO7P |
| DE | A1PA6795UKMFR9 |
| FR | A13V1IB3VIYZZH |
| IT | APJ6JRA9NG5V4 |
| ES | A1RKKUPIHCS9HS |
| JP | A1VC38T7YXB528 |

CA / AU / IN / MX 的 mid 需实测确认后再补进本表，未确认前不要猜。

### 前缀策略（每次只回 10 条，所以要组合）

对**核心种子词**（取方法二/三的 Top 3-5 个词）分别跑：

| 前缀类型 | 示例 | 捕获什么 |
|---|---|---|
| 纯种子 | `coat rack` | 主干长尾 |
| best + 种子 | `best coat rack` | 比价/决策型 |
| 种子 + for | `coat rack for` | 场景/人群型 |
| 种子 + 字母 | `coat rack w` / `coat rack s` | 补充长尾 |

**调用预算**：单次调研建议 8-15 次 `web_fetch`。优先跑：3 个种子 × (纯种子 + best + for) = 9 次。不够再补字母后缀。

### 结果处理

- 记录**返回顺序**：位置越靠前 = 搜索热度越高，这是免费的排序信号
- 去重（跨前缀会有重复）
- 记录来源前缀，便于回溯

输出表：

| 联想词 | 来源前缀 | 位次 | 备注 |
|---|---|---|---|

### 局限（必须在报告里写）

- 只有 10 条/次，覆盖有限
- 不返回搜索量，只能当"存在性 + 相对热度"证据
- 联想词含竞品品牌词时，单独归到 BRAND，不当机会词

---

## 7. 合并、补指标、打分

### 7.1 合并去重

四路结果合并成一张总表，`keyword` 归一化后去重（小写、去标点、统一空格）。

每个词记录**来源标记**：`A`=竞品反查、`B`=标题词频、`C`=Listing词频、`D`=自动补全。一个词可能多源，多源本身就是强信号。

### 7.2 补指标

把总表里**搜索量未知**的词，批量丢给 `keyword_miner` 精准查询：

```python
mcp__ss_mcp__keyword_miner({
  "request": {
    "marketplace": "US",
    "keywordList": ["词1","词2","..."]   # 一次最多建议 50 个
  }
})
```

取回：`searches`（月搜索量）、`purchases`、`purchasesRate`、`spr`、`titleDensity`、`monopolyClickRate`、`bid`、`avgPrice`、`supplyDemandRatio`。

**拿不到搜索量的词**（长尾、拼写变体、自动补全独有词）标 `EST`，不要编数字。

### 7.3 相关性 R（0-1）

| 分量 | 权重 | 判定 |
|---|---|---|
| R1 品类相关 | 0.5 | 1 = 直接指向本品品类；0.5 = 相关品类；0 = 不相关 |
| R2 属性匹配 | 0.3 | 1 = 属性与本品一致；0.5 = 部分一致；0 = **冲突**（如本品 wall mount，词是 freestanding） |
| R3 市场共识 | 0.2 | = 竞品覆盖率 `coverage`（来自方法二/三） |

`R = 0.5×R1 + 0.3×R2 + 0.2×R3`

**R1=0 或 R2=0 的词，直接进否定清单，不参与打分。**

### 7.4 权重分 W

```
W = 月搜索量 × R          （有搜索量）
W = 词频权重 × R × 1000   （EST 词，用词频当代理，量级对齐到千级）
```

用乘积而不是加和：搜索量再大，相关性为 0 就是 0 分。

### 7.5 分档

| 档位 | 条件 | 去向 |
|---|---|---|
| **P0** | W 排名前 10 且 R ≥ 0.8 | 标题 / Highlights |
| **P1** | W 排名 11-40 或 R 0.6-0.8 | 五点 / A+ |
| **P2** | 其余 R ≥ 0.5 | ST / QA |
| **NEG** | R1=0 或 R2=0 | 否定清单 |
| **BRAND** | 竞品品牌词 | 单独列出，不进机会词 |

---

## 8. 输出：三件套

### 8.1 `keyword_library.csv`（排序后的词表）

```
keyword, tier, W, R, searches, purchases, spr, title_density, monopoly_click_rate,
bid, avg_price, sources, l0_hit, coverage, est_flag
```

按 W 降序。这就是主交付物。

### 8.2 `negative_words.txt`

一行一个，直接粘广告后台。

### 8.3 `handoff.md`（交接单，给文案环节）

这份是 v2 的核心产出，直接对应 `amazon-listing-builder` 的输入：

```markdown
## 交接单

### 标题槽位
| 槽位 | 候选词（按 W 降序） | 词数 | 备注 |
|---|---|---|---|
| 品牌 | — | — | 固定 |
| 核心品类词 | coat rack, wall mounted coat rack | — | 必占 |
| 差异化属性 | heavy duty, 5 hooks | — | 见差异化清单 |
| 主场景 | entryway | — | 单一场景 |
| 规格 | wood, 16 inch | — | 有空间才放 |

### 差异化词（Highlights 用）
| 词 | 本品有 | 竞品覆盖 | 差异强度 |
|---|---|---|---|
| solid wood | ✅ | 0.2 | 高 |
| 5 hooks | ✅ | 0.3 | 中 |

### 五点素材
| 卖点 | 支撑词 | 搜索量合计 | 覆盖竞品数 |
|---|---|---|---|

### 否定词
（见 negative_words.txt）
```

---

## 9. 工具映射（本机实际可用）

| 用途 | 工具 |
|---|---|
| 竞品扩池 | `mcp__ss_mcp__asin_competitor` / `traffic_listing` |
| ASIN 详情（标题/五点/描述） | `mcp__ss_mcp__asin_detail` |
| 自家流量词 | `mcp__ss_mcp__traffic_keyword` |
| 竞品出单词 | `mcp__ss_mcp__keyword_order` |
| 指标补齐 | `mcp__ss_mcp__keyword_miner`（`keywordList` 精准查询） |
| 关键词趋势 | `mcp__ss_mcp__keyword_research_trends`（扁平参数） |
| 前台联想 | `web_fetch` → `completion.amazon.com` |
| 类目节点 | `mcp__ss_mcp__product_node` |

**已知陷阱**：`keyword_research` 会忽略 keyword 参数，返回全局热词，不要用它做精准查询，用 `keyword_miner` 的 `keywordList`。

---

## 10. 执行顺序（照抄即可）

1. 确认输入，缺竞品 ASIN 先问
2. 跑方法一，出竞品池（8-15 个），检查样本量
3. 批量拉 `asin_detail`，落成 `products.json`
4. 跑 `freq.py`，得标题 + Listing 词频
5. 取 Top 3-5 种子，跑自动补全（8-15 次）
6. 合并四路，去重，标来源
7. `keyword_miner` 批量补指标
8. 算 R → 算 W → 分档
9. 输出三件套
10. 把 `handoff.md` 交给 `amazon-listing-builder`

---

## 附：8 维分类（广告分组用，可选）

调研完成后如果要做广告结构，再按 8 维分类一次。它是**下游环节**，不影响词库排序。

| 维度 | 应用策略 |
|---|---|
| NEGATIVE 否定/敏感 | 直接否定 |
| BRAND 品牌 | 竞品打法或否定 |
| MATERIAL 材质 | 精准词组 |
| SCENARIO 场景 | 按场景拆广告组 |
| ATTRIBUTE 属性 | 长尾精准 |
| FUNCTION 功能 | 广泛匹配扩流 |
| CORE 核心 | 大词占坑 |
| OTHER | 补充埋词 |

---

## 版本

v2.0（2026-11-13）：四路采集 + 权重打分 + 交接单。替代 v1.3 的单 ASIN 流量词方案。
