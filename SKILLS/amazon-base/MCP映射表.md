# MCP 依赖映射表

本目录下的 skill 原生于作者的 MCP 配置（Sorftime / Sif / 西柚 / 卖家精灵）。
你当前环境**只接了卖家精灵**（工具前缀 `mcp__ss_mcp__`），因此按本表替换工具名后再执行。

> 原则：**工具名可以换，分析框架和评分模型不要换。**
> 口径差异要说明——Sorftime 的「流量词」和卖家精灵的 `traffic_keyword` 都来自各自爬取样本，绝对值不可直接互比。

## 一、卖家精灵（已接入，可直接用）

`mcp__ss_mcp__*` 与 skill 里写的 `mcp__ss_mcp__*` 完全一致，无需改写。

常用工具速查：

| 用途 | 工具 |
|---|---|
| 商品检索/选品筛选 | `product_research` |
| 单 ASIN 详情 | `asin_detail` / `asin_detail_with_coupon_trend` |
| ASIN 销量预测、14 个月走势 | `asin_prediction` / `asin_sales_trend` |
| Keepa 全维度历史 | `keepa_info` |
| ASIN 流量词（自然+广告+推荐） | `traffic_keyword` |
| 流量结构占比 | `traffic_source` / `traffic_keyword_stat` |
| 关联/竞品商品 | `traffic_listing` / `asin_competitor` |
| 关键词拓展（以 ASIN 拓词） | `traffic_extend` |
| 关键词反查（以词找词/竞品转化词） | `keyword_order` |
| 关键词调研（搜索量/购买量/供需比） | `keyword_research` / `keyword_research_trends` |
| 关键词挖掘（竞争度/SPR/标题密度） | `keyword_miner` |
| 关键词转化率 | `keyword_conversion` |
| ABA 研究 | `aba_research_weekly` / `aba_research_monthly` / `aba_research_trend` |
| 类目节点 | `product_node` |
| 类目市场分析 | `market_research` / `market_research_statistics` |
| 市场结构分布 | `market_price_distribution` / `market_brand_concentration` / `market_seller_concentration` / `market_rating_distribution` / `market_listing_date_distribution` 等 |
| BSR 销量预测 | `bsr_prediction` |
| 评论 | `review` |
| Google 趋势 | `google_trend` |
| 商标查询 | `trademark_list` / `trademark_detail` / `trademark_stats` |

## 二、Sorftime → 卖家精灵 等价映射

`vendor/` 下的 keyword-research、amazon-analyse、category-selection、product-research、review-analysis 五个 skill 原本调用 Sorftime。按此表替换：

| Sorftime 工具 | 卖家精灵等价 | 口径提示 |
|---|---|---|
| `product_detail` / `product_info` | `asin_detail` | 字段名不同，需重新映射 |
| `product_trend` | `asin_sales_trend` 或 `keepa_info` | Keepa 更长、更细 |
| `product_reviews` / `competitor_reviews` | `review` | 单次返回条数不同 |
| `product_traffic_terms` | `traffic_keyword` | 都能拿到自然排名/广告排名 |
| `competitor_product_keywords` | `traffic_listing` + `keyword_order` | 建议两个都跑再取并集 |
| `product_search` | `product_research` | 参数结构差异较大，按 `product_research` 的 schema 重写 |
| `category_name_search` | `product_node`（keyword 参数） | — |
| `category_report` | `market_research`（nodeIdPath + topNum） | — |
| `category_tree` | `product_node`（nodeIdPath 逐层） | 无一次性整树接口 |
| `category_trend` | `market_research` + `aba_research_trend` | 趋势口径不同，需在报告注明 |
| `category_keywords` | `keyword_research`（departments）或 `keyword_miner` | — |
| `keyword_related_words` | `traffic_extend` | 卖家精灵需先有 ASIN |
| `keyword_extends` | `traffic_extend` | 同上 |
| `keyword_detail` | `keyword_miner`（keywordList 精准查询） | — |
| `products_1688` | **无** | 1688 采购成本这段跳过或人工补 |
| `tiktok_*` | **无** | TikTok 相关分析跳过 |

## 三、无法替代的两个 skill

| Skill | 依赖 | 现状 |
|---|---|---|
| `sif-amazon-research` | Sif MCP | 未接入，**暂不可用**。其「证据链 → 商业决策」框架可手工套用 |
| `xiyou-insight` | 西柚洞察 MCP | 未接入，**暂不可用**。其「流量缺口」场景可用 `traffic_keyword` 两个 ASIN 对比手工复现 |

其余 7 个 skill 均可通过上表映射到卖家精灵执行。

## 四、如果你之后要接其他 MCP

`.mcp.json` 模板（**不要用作者仓库里的共享密钥**，那是公开的演示 key，随时可能失效或限流）：

```json
{
  "mcpServers": {
    "sorftime": {
      "type": "streamableHttp",
      "url": "https://mcp.sorftime.com?key=<你自己的 key>"
    },
    "sif-mcp": {
      "type": "http",
      "url": "https://mcp.sif.com/mcp",
      "headers": { "secret-key": "<你自己的 key>" }
    },
    "xydc-mcp": {
      "type": "http",
      "url": "https://mcp.xydc.com/mcp",
      "headers": { "Authorization": "Bearer <你自己的 token>" }
    }
  }
}
```
