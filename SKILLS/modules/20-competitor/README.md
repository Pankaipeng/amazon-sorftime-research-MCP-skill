# 20 · 竞品分析（输出型模块）

> 导图原在处理层，按用法归到输出层：**它交付的就是"竞品怎么打"这份结论，不是中间数据。**

## 输入
- `00-input/竞品asin组`（同一份池子，和 10-keyword 共用）
- `10-keyword/handoff.md`（词的分布能反推竞品打法）

## 输出（成品报告）
| 产物 | 说明 |
|---|---|
| 竞品拆解表 | 逐个竞品的定位、价格带、卖点结构、词覆盖 |
| 竞品痛点表 | 差评归因 + 频次 + 严重度 |
| 竞争格局图 | 价格带 × 卖点数 的二维分布 |

## 离线生成

```bash
python SKILLS/scripts/build_competitor.py --asin-pool <ASIN-CSV> --bullets <五点-JSON> --insight <30-洞察补充-xlsx> --marketplace US --currency USD --price-band-width 5 --out <输出目录>
```

竞品按输入池的唯一 ASIN 输出。价格带为左闭右开区间，缺价单列。五点证据使用 40 的词表，保留 ASIN、原句和位置。竞品痛点复用 30 的二级标签，并保留采样分母和组内占比。

## 待补
- 图片卖点采集与拆解见 [竞品图片卖点拆解](competitor-image-research/SKILL.md)，输出供 40 审阅。
- [ ] 痛点严重度打分，供 `40-selling-point` 的 M 公式使用
