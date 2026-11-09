# v3独立数据源采集补充

本补充只恢复数据输入。模型、125特征、概率门槛0.5、每日Top10、72小时冷却、每日00UTC网格及5分钟实际记录期限沿用原冻结版；原334个绑定文件及5个模型文件未改。

## 运行一次

```sh
/Users/leslie/Documents/同花顺/outputs/neg-funding-strategy-phase2-20261107/forward_validation_v2_20261107/.venv/bin/python -B /Users/leslie/Documents/同花顺/outputs/neg-funding-v3-source-recovery-20261109/run_sources_once.py
```

先用已有授权Datahub批量取已收盘现货/永续/溢价K线和已结算资金费，补足中断期间的历史及5分钟OI，再调用原冻结run_once.py。记录仍追加到原v3的market.sqlite和forward.sqlite，旧记录不改写。原API直连冷却不解除、不切换主机绕过。

检查本目录RECOVERY_HEALTH.json、run-*.json、datahub-latest.json，以及原目录data/health.json、data/metrics-latest.json。原health仍会显示直连来源冷却；能否得到新数据，要同时查看独立来源的实际接收时间和逐类覆盖，不能只看HTTP200或定时任务COMPLETED。

00UTC周期只用批量最新值，避免串行查询全币池错过5分钟期限。在原5分钟期限内为上一小时K线定稿留出有限等待，并刷新一次；如果本轮尚未定稿，该币缺失照常保留，不能把未收盘数据或旧价格填成当时已知。如果整个调度迟到，原版拒绝补造预测。

SOURCE_CONTRACT.json记录字段及时间口径，SOURCE_BINDING.json校验本补充代码；原模型及原管线绑定也同时核对。自动任务不得改模型、阈值或绑定。

## 官方日档补采

启动时已校验并导入2026-11-06至08日的996个币日metrics文件。最初995个成功，SENTUSDT并发数据库错误已修复并单独成功重试，原失败证据保留；其余21个404文件单独留证，不当作零。日档只对已发布的UTC自然日有效，当天的多空比不会由日档伪装成实时数据。

自动周期在每日预测窗口之外续采前两个已结束UTC日期的日档；已完成项跳过，404至少等待6小时再试。历史Datahub缺口先持久化再取最新值，超时留到后续周期，不会被最新记录掩盖。也可手动运行src/independent_sources.py --days YYYY-MM-DD。校验和不符不导入。完整5分钟原文保留在data/raw，OI接口规范化为每小时最后一个真实观测，因为冻结模型本来就按该口径聚合；已导入记录不删除。

## 保留限制

- Datahub当前规范没有Bybit和四类多空比接口；这些字段的当天缺口如实保留。模型仍用原来的缺失处理，不重新训练或临时替代字段。
- 实际结算只认/v1/funding，不把/v1/funding/predicted或funding/current预测值当结算。特殊结算隔离留证，不默默合并进常规资金费。
- 小时K线只取complete且已定稿的trade/premium相应值。OI只取原生quote价值，不用当前价格反推历史OI。
- Datahub的OI time_ms标记5分钟区间结束；映射为原生采样时间时减5分钟，后续原冻结模型的1小时预滞后不变。逐币原值核对见OI_OVERLAP_VALIDATION.json；最初未映射导致的失败对照另行保留。旧错误时间记录不删除，只追加修订并从原响应按正确时间重放。
- 保留meta.covered/unavailable和所有修订；实际已返回的完整K线与covered边界不一致时，也保留原响应，不夸大提供方的覆盖保证。
- 供应商明确不支持的单个instrument隔离留证，同批其他币继续读取，不改变339币研究池。官方日档空数字按缺失编码供原读取器处理；此前已导入的空字段只追加规范化修订，原记录和ZIP保留，不填0、不沿用前值。
- 到账后240h合格机会、1008h完整退出参考收益仍需冻结引擎独立重算，待复核状态不计入已验证命中率。
- 本机磁盘少于2GiB时停止新采集并报错，不自动删除研究历史。定时任务需要电脑和应用持续运行。
- 不新增付费订阅、不交易、不借币、不转账、不发送外部消息，不恢复其他暂停任务。2026-12-01模型过期后继续采集及成熟追踪，停止新预测，不重训。
