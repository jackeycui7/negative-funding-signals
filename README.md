# Negative Funding Signals · 信号识别与真实前瞻

冻结候选 **`nfb.inventory-value.v3.20261109`**，125特征；状态 **WATCH_ONLY**。模型用于发现候选，不直接开仓。正式策略和执行方交接在 [negative-funding-strategy](https://github.com/leslieshen1/negative-funding-strategy)。

最近检查：[2026-11-10接口审计与公开说明](docs/MOCK_REVIEW_20261110.md)。修复4类包装入口边界问题；不代表前瞻命中率已通过。

## 阅读顺序

| 内容 | 入口 |
|---|---|
| 大白话和模型表达 | [模型说明](docs/MODEL.md) |
| 输入/输出和字段定义 | [接口说明](docs/INTERFACE.md)、[输入Schema](schemas/INPUT_SCHEMA.json)、[输出Schema](schemas/OUTPUT_SCHEMA.json) |
| 安装与离线打分 | 下方命令、[固定样例](examples/) |
| 数据接入、补采、时间映射 | [数据与前瞻运行](docs/DATA_AND_FORWARD.md) |
| 防过拟合与成熟结果 | [验证协议](docs/VALIDATION.md) |
| 当前缺口和采集快照 | [状态说明](docs/STATUS.md)、[证据目录](evidence/) |

## 从空目录克隆即可离线打分

模型文件随公开仓库交付，加载前核对哈希。Python3.12；只加载本仓库已验证模型。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B scripts/verify_release.py
.venv/bin/python -B scripts/score.py --input examples/historical-negative-input.json
```

输入是按时点构造的125特征向量。公开样例的116项行情特征来自历史公开市场，9项数量特征使用合成的10,000 USDT到账情景，不是原始私有库存；见 [样例来源](examples/PROVENANCE.json)。样例保留历史代理/过期标志，不写入真实预测账本。离线打分不联网，不下单。

## 完整特征与采集

大历史矩阵、Bybit历史缓存、实际库存、API凭证和SQLite台账不进Git。完整特征构造需要 [外部资产清单](data/EXTERNAL_ASSETS.json)；可在有权访问这些资产的机器上按哈希接入：

```sh
.venv/bin/python -B scripts/bootstrap_forward.py --asset-root /path/to/authorized/project
.venv/bin/python -B scripts/run_forward.py
```

bootstrap仅为此克隆建立路径映射；先验证原334项哈希，原模型和源码字节保持不变。凭证只从本机已有授权文件读取。完整复跑对外部资产有明确依赖，缺失时停止并列出缺项；不自动训练或临时生成库存。

## 两个边界

- 预测概率不是交易许可。实际到账库存、RC2和风控仍决定是否可交易。
- 经济头是按冻结成本与k=4计算的条件参考净价值，不是已实现利润，也不能直接跨币相加。

`evidence/`是有明确时点的交付快照，GitHub页面不会随本机自动采集实时刷新。2026-12-01后停止新预测，继续收集和跟踪已发预测结果；不自动重训。
