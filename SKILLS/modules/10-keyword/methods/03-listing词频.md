# 方法 C：竞品 Listing 词频

> 导图子项：竞品 listing 高频词

标题只有 75 字符，装不下竞品真实的表达方式。**五点 + 描述里藏着"买家语言"**——那些买家真会搜、但竞品没往标题里塞的词。

---

## 和方法 B 的区别

| | 方法 B 标题词频 | 方法 C Listing 词频 |
|---|---|---|
| 反映 | 竞品的**关键词取舍** | 竞品的**卖点表达** |
| 高频词偏向 | 品类词、属性词 | 痛点词、场景词、证据词、规格词 |
| 噪声 | 低 | 高（长句多，含水量大） |
| 主要用途 | 标题、Highlights | 五点、A+、QA、Search Terms |

一个典型例子：竞品标题写 "Heavy Duty"，五点里才说 "holds up to 30 lbs"。后者才是买家会搜的词，也是转化依据。

---

## 步骤

### 1. 取字段

```python
for p in pool:
    d = mcp__ss_mcp__asin_detail({"marketplace":"US", "asin":p["asin"]})
    # 需要 title / bullets / description 三个字段
```

### 2. 落 JSON

```json
[
  {"asin":"B0XXXX","level":0,
   "title":"...",
   "bullets":["...","..."],
   "description":"..."}
]
```

### 3. 跑同一个脚本

```bash
python scripts/freq.py products.json \
  --weight-l0 3 --weight-other 1 \
  --min-asin 2 --max-n 3 --top 200 --out listing_freq.csv
```

**字段权重自动生效**：标题 3 / 五点 2 / 描述 1。所以这一次跑完，方法 B 和 C 的结果都有了——只是看不同的列。

### 4. 只看 Listing 贡献的词

```bash
# 用 python 过滤：in_bullets + in_description > 0 且 in_title 为 0
```

这些是"竞品写了但没放进标题"的词。它们要么是装不下，要么是竞品觉得优先级低——**两种情况对你都是机会**。

---

## 三种词要单独拎出来

| 类型 | 识别方式 | 用途 |
|---|---|---|
| **痛点词** | 含 "won't / no / easy to / without / prevents" 等 | 喂给 `30-insight` 和五点第 2 点（痛点解决） |
| **证据词** | 含数字、"tested / certified / rated / holds up to" | 喂给 `40-selling-point` 的证据库 |
| **限制词** | 含 "only / not for / indoor / do not" | 直接进 Highlights 的限制条件，降低退货率 |

**限制词最容易被忽略，但它是转化率工具**。竞品写了 "indoor use only" 你没写，买家买错场景就会差评。

---

## 噪声怎么处理

Listing 文本含水量大，不处理会得到一堆垃圾：

| 处理 | 做法 |
|---|---|
| 停用词 | `freq.py` 内置表，不够就补 |
| 泛词 | `product / item / set / pack` 等单字丢弃（`GENERIC` 表） |
| 品牌词 | 统计前剔除所有竞品品牌名 |
| 长句 | `--max-n 3` 限制最长 3 词，避免整句成词 |
| 单 ASIN 独有词 | `--min-asin 2` 过滤，除非专门做差异化分析 |

---

## 输出

`listing_freq.csv`，列同方法 B。重点看 `in_bullets` 和 `in_description`：

| 现象 | 含义 |
|---|---|
| `in_bullets` 高、`in_title` 低 | 竞品认为这是卖点但不是搜索词 → 五点素材 |
| `in_title` 高、`in_bullets` 低 | 只用来占搜索位，竞品自己也不当真 → 可能是个虚火词 |
| 两者都高 | 真正的核心卖点词 → 进卖点库，权重给满 |

---

## 和方法 B 合并

两个方法跑的是同一个脚本、同一份输入，**不要跑两次**。直接在一次输出里按列区分：

- 看 `in_title` 列 → 方法 B 的结果
- 看 `in_bullets + in_description` 列 → 方法 C 的结果
- 三列加起来 → 综合词表

合并规则见 `methods/05-合并打分输出.md`。
