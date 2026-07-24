# 现场 Demo · 标的应对速查表

> 生成模式：模型 `mock` · 数据 `mock` · 审计 `mock`。
> ⚠️ 换模式（尤其 `DATA_MODE=panda` 真数据）结论会变——**用你现场要用的模式重跑本表**。

| 标的 | 名称 | 标红数 | 审计结论 |
|---|---|---|---|
| `600519` | 贵州茅台 | 2 | bear:bad_data、risk:bad_data |
| `000858` | 五粮液 | 0 | 全部通过 |
| `601318` | 中国平安 | 3 | bear:bad_data、bull:selection_bias、risk:bad_data |
| `000001` | 平安银行 | 3 | bear:bad_data、bull:selection_bias、risk:bad_data |
| `600036` | 招商银行 | 2 | bear:bad_data、risk:bad_data |
| `300750` | 宁德时代 | 0 | 全部通过 |
| `002594` | 比亚迪 | 0 | 全部通过 |
| `688981` | 中芯国际 | 2 | bear:bad_data、risk:bad_data |
| `000002` | 万科A | 3 | bear:bad_data、bull:suspected_overfit、risk:bad_data |
| `601899` | 紫金矿业 | 1 | bull:suspected_overfit |
| `600030` | 中信证券 | 0 | 全部通过 |
| `000651` | 格力电器 | 0 | 全部通过 |
| `AAPL` | Apple | 2 | bear:bad_data、risk:bad_data |
| `TSLA` | Tesla | 0 | 全部通过 |
| `NVDA` | Nvidia | 1 | bull:suspected_overfit |
| `MSFT` | Microsoft | 0 | 全部通过 |
| `GOOG` | Google | 2 | bear:bad_data、risk:bad_data |
| `META` | Meta | 3 | bear:bad_data、bull:suspected_overfit、risk:bad_data |
| `AMZN` | Amazon | 1 | bull:suspected_overfit |

## 主持人应对（按结论类型）

- **全部通过**（如五粮液/宁德/茅台外的多数）→ “这只票它挑不出毛病，就放行——证明审计是真的在分辨，不是逢多必红。这本身就是可信度。”
- **bull:selection_bias** → “看，多头的因子被审计当场标红：小样本高 IC，像只挑赢家来吹。”
- **bull:suspected_overfit** → “多头这条被判过拟合——像背答案考试，换套题就不灵，还被打回重证。”
- **bear/risk:bad_data** → “空头/风控引用的价格序列被查出未复权跳空——证据本身带病，先修数据。”
- **多条混合**（如中国平安/万科/Meta）→ 最有戏：多空两边都被挑出不同毛病，分歧地图最丰富。

## 稳妥选择
- 想**必现标红**演高光：中国平安 `601318`、平安银行 `000001`、万科 `000002`、Meta（三条混合）。
- 想演**审计会放行**（证明不唬人）：宁德 `300750`、五粮液 `000858`、中信证券 `600030`、Tesla。
- 评委给的票不在表内也不慌——同样的引擎当场跑，结论可解释、带溯源。
