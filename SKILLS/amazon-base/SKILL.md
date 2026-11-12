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
| `keyword-research` | 关键词调研 + 8 维分类 |
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

**关键词调研（最常用）**
1. 读 `keyword-research/SKILL.md` 拿 8 维分类模型和报告结构
2. 数据采集按映射表换成：`traffic_keyword`（自家流量词）→ `traffic_listing` + `keyword_order`（竞品布局）→ `traffic_extend`（长尾扩展，Top 30 核心词各跑一次）→ `keyword_miner`（补搜索量/竞争度/SPR）
3. 分类照 8 维：NEGATIVE / BRAND / MATERIAL / SCENARIO / ATTRIBUTE / FUNCTION / CORE / OTHER
4. 输出：Markdown 报告 + CSV 词库 + 否定词清单

**单 ASIN 深度调研**
读 `sellersprite-amazon-research/skill.md`，按它的综合工作流选子文档（`comprehensive/*.md`），数据走 `asin_detail` / `traffic_keyword` / `review` / `market_research`。

**选品战术扫描**
读 `sellersprite-amazon-research/tactical/*.md`，16 张战术卡（新品爆发、隐形爆款、ABA 高增长词、低品牌垄断、标题密度缺口、热销低评分等），每张卡都写了筛选条件，直接对应 `product_research` / `aba_research_*` 的参数。

## 硬性规矩

1. **先读映射表再调工具。** 本机只存在卖家精灵前缀 `mcp__ss_mcp__*`。Sorftime / Sif / 西柚 / 旧卖家精灵前缀的工具在本机都不存在，照抄会失败。
2. **区分"已验证数据"和"推断"。** 搜索量、点击份额、SPR 是数据；"这个词有机会"是判断。报告里分开写。
3. **口径不可混用。** 卖家精灵和 Sorftime 的搜索量来自不同样本，同一份报告里不要一半一半拼。
4. **报告三件套**：Markdown 正文 + CSV 词库 + HTML/表格看板。词库要能直接导入广告后台。

## 后续改造路径

上游那 9 个 skill 目录是只读参照，不要就地改。要定制时，把某个 skill 目录复制一份到 `skills/<你的名字>/`，改完就是一个自建 skill，上游更新时还能 diff。

当前待改造项，按优先级：
1. 关键词调研：把 8 维分类改成本类目实际用得到的维度，补上 `keyword_miner` 的 SPR / 标题密度字段
2. 选品：把 16 张战术卡裁剪成真正跑得通的 5–8 张，每张绑定具体工具参数
3. Listing：八步工作流里第 2 步「用户问题库」和第 8 步「QA 设计」是 Rufus/COSMO 时代最值钱的部分，值得单独抽出来
