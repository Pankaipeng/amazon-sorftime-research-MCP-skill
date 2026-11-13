---
name: amazon-base-skills
description: 亚马逊选品与关键词调研的底层技能库入口。当用户要做亚马逊选品分析、关键词调研与拓展、竞品拆解、类目市场分析、评论痛点分析、Listing 优化、广告关键词优化时使用。内含 9 个上游 skill 的完整方法论与脚本，并映射到已接入的卖家精灵 MCP（mcp__ss_mcp__）。用户说"/keyword-research"、"调研这个 ASIN"、"挖关键词"、"这个词值不值得做"、"分析这个类目"时触发。
---

# 亚马逊底层技能库（amazon-base）

这是一层**上游方法论底座 + 本机 MCP 适配**。后续的自建 skills 应该从这里复制、改写，而不是从零写。

## 里面有什么

9 个上游 skill，各自一个目录：

| 目录 | 内容 |
|---|---|
| `keyword-research` | 关键词调研 v2：四路采集 + 权重打分 + 交接单 |
| `sellersprite-amazon-research` | 43 工具全链路 + 10 工作流 + 16 战术卡 |
| `amazon-analyse` | 单 Listing 全维度穿透 |
| `category-selection` | 类目选品 + 五维评分 |
| `product-research` | 选品深度调研 |
| `review-analysis` | 评论 6 维痛点 |
| `amazon-listing-builder` | 八步 Listing 工程 |
| `sif-amazon-research` | 需 Sif MCP，当前不可用 |
| `xiyou-insight` | 需西柚 MCP，当前不可用 |

两处存放位置，内容一致：
- 本机工作区：`skills/vendor/<目录>/`
- GitHub 仓库：`SKILLS/skills/<目录>/`

本 skill 自己（路由层 + 映射表）在本机是 `skills/amazon-base/`，仓库里是 `SKILLS/amazon-base/`。

## 使用前必读

**本机只有卖家精灵 MCP（`mcp__ss_mcp__`）。** 调用任何 vendor 下的 skill 之前，先读 `amazon-base/MCP映射表.md`，把 Sorftime 工具名换成卖家精灵等价工具。

两个例外：`sif-amazon-research` 和 `xiyou-insight` 依赖的 MCP 未接入，只能借用它们的方法论框架，不要假装拿到了数据。

## 路由表

| 用户意图 | 读这个 |
|---|---|
| 挖关键词、扩词、做词库、否词清单 | `keyword-research/SKILL.md` |
| 一个 ASIN 做到底（选品/竞品/流量/广告/Lising/评论） | `sellersprite-amazon-research/skill.md` |
| 单个竞品 Listing 全维度穿透 | `amazon-analyse/SKILL.md` |
| 整个类目 Best Sellers 扫描 | `category-selection/SKILL.md` |
| 从关键词出发做选品调研 | `product-research/SKILL.md` |
| 差评归因、痛点提炼 | `review-analysis/SKILL.md` |
| 写/改 Listing、标题、五点、A+、ST、QA | `amazon-listing-builder/skill.md` |
| 要"证据链 → 商业决策"的严谨口吻 | `sif-amazon-research/SKILL.md`（借框架，不用其工具） |
| 流量缺口、竞品流量拆解 | `xiyou-insight/SKILL.md`（借框架，用 `traffic_keyword` 复现） |

## 三个最常用的执行入口

**关键词调研（最常用，v2）**
1. 读 `keyword-research/SKILL.md` 拿四路采集流程和打分公式
2. 四路并集：`asin_competitor`（竞品扩池）→ `asin_detail` + `freq.py`（标题/五点词频）→ `web_fetch` 调 Amazon 自动补全（长尾）
3. `keyword_miner` 的 `keywordList` 批量补搜索量/SPR/标题密度/PPC
4. 算 R（相关性）→ 算 W（权重）→ 分 P0/P1/P2/NEG
5. 输出：`keyword_library.csv` + `negative_words.txt` + `handoff.md`（交给文案环节）

**单 ASIN 深度调研**
读 `sellersprite-amazon-research/skill.md`，按它的综合工作流选子文档（`comprehensive/*.md`），数据走 `asin_detail` / `traffic_keyword` / `review` / `market_research`。

**选品战术扫描**
读 `sellersprite-amazon-research/tactical/*.md`，16 张战术卡（新品爆发、隐形爆款、ABA 高增长词、低品牌垄断、标题密度缺口、热销低评分等），每张卡都写了筛选条件，直接对应 `product_research` / `aba_research_*` 的参数。

## 硬性规矩

1. **先读映射表再调工具。** 本机只存在卖家精灵前缀 `mcp__ss_mcp__*`。Sorftime / Sif / 西柚 / 旧卖家精灵前缀的工具在本机都不存在，照抄会失败。
2. **区分"已验证数据"和"推断"。** 搜索量、点击份额、SPR 是数据；"这个词有机会"是判断。报告里分开写。
3. **口径不可混用。** 卖家精灵和 Sorftime 的搜索量来自不同样本，同一份报告里不要一半一半拼。
4. **报告三件套**：Markdown 正文 + CSV 词库 + HTML/表格看板。词库要能直接导入广告后台。

## 改造方式（2026-11-13 起）

**直接改 `vendor/` 里的文件**，不再另建自建层。理由：仓库已 fork 到自己账号，只服务一个用户，分层的收益抵不过维护成本。上游若更新，用 diff 手工挑。

当前改造进度：
1. ✅ 关键词调研 v2：四路采集 + 权重打分 + `handoff.md` 交接单
2. ✅ 文案排序规则：`amazon-listing-builder/reference/ranking-rules.md`（标题按 W、Highlights 按差异、五点按 M）
3. ⬜ 用真实 ASIN 跑一轮，校准 R / W 的阈值
4. ⬜ `review-analysis` 的痛点结论接进五点排序（M 公式里的 P 分量目前靠人工估）
5. ⬜ 自动补全的 mid 表补齐 CA / AU / IN / MX
