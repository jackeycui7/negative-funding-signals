# 数据接入与完整前瞻

## 当前来源

已有授权Datahub提供已结算资金费、已收盘现货/永续/溢价K线及5分钟OI。币安官方data.binance.vision日档提供原生OI和四类多空指标。原始响应、checksum、provider接收时间和我方实际接收时间分别留痕。

Datahub的OI time_ms是5分钟区间结束，减5分钟还原原生采样时点，再由原模型沿用1小时预滞后。四币1152个原值对照通过；最初未映射的失败对照保留。预测资金费不当已结算费率；未定稿K线、空字段和供应商不支持的币保留缺失。

## 外部资产与初始化

`data/EXTERNAL_ASSETS.json`按原路径和SHA256列出历史矩阵、跨所缓存和实际库存文件。资产根目录应包含outputs/...及neg-funding-strategy-v1/private/...。这些文件由有权接触的人另行交付；脚本不下载、猜测或修改资产。输入缺失/哈希不符时bootstrap失败并列出缺项。

```sh
.venv/bin/python -B scripts/bootstrap_forward.py --asset-root /path/to/authorized/project
.venv/bin/python -B scripts/run_forward.py
```

bootstrap核验完整原334项，并将路径映射到本克隆；期望SHA完全不变。它保留provenance内的原清单，生成本克隆专用清单和Python入口软链接，创建空数据/状态目录。它不会导入旧预测台账，也不创建定时任务。

Datahub凭证需由账户所有者自行放在本机 `~/.datahub/api_key`，权限600；仓库没有密钥。运行保持GET白名单、403/418/429/451与Retry-After冷却，不换主机/代理绕过限制。先持久化历史缺口，再读最新值，超时后续续采。原始v3脚本和新来源适配器均保持原字节。

完整采集入口在bundle/outputs/neg-funding-v3-source-recovery-20261109；原始冻结特征和台账入口在bundle/outputs/neg-funding-v3-forward-20261109。bundle是为保持冻结相对路径而保留的源码布局，使用者从scripts/入口运行即可。

本机的真实采集与本仓库的新克隆互相独立。克隆后默认空台账，只有未来按时发出的新预测才计数；不能把交付快照或历史例子导入作为自己的前瞻成绩。
