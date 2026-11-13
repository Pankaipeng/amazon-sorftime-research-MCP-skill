# 50 · 文案生成

> 导图最后一块。规则草稿已写在 `vendor/amazon-listing-builder/reference/ranking-rules.md`，等前面模块稳定后搬过来。

## 输入
- `10-keyword/handoff.md`（词 + W + R + 层级）
- `40-selling-point`（卖点库 + 权重 M）

## 输出
| 产物 | 排序依据 |
|---|---|
| 标题 + 亮点 | 标题按 W，亮点按 H = 差异×0.6 + W×0.4 |
| 五点 | 按 M |
| Search Terms | 前台未覆盖的 P2 |

## 待补
- [ ] 把 ranking-rules.md 搬进来并改成模块格式
- [ ] 字符数校验自动化（标题 75 / 亮点 125 / ST 250 字节）
