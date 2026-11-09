# v3真实前瞻采集：冻结运行口径

注册时间见PROTOCOL.json。模型仍为nfb.inventory-value.v3.20261109，WATCH_ONLY。

## 每轮运行

工作目录：/Users/leslie/Documents/同花顺/outputs/neg-funding-v3-forward-20261109。

使用已存在的量化Python环境：

```sh
/Users/leslie/Documents/同花顺/outputs/neg-funding-strategy-phase2-20261107/forward_validation_v2_20261107/.venv/bin/python -B /Users/leslie/Documents/同花顺/outputs/neg-funding-v3-forward-20261109/run_once.py
```

进程有独占锁，每次采集有时间和页数预算；遇ALREADY_RUNNING保留现有运行，不重复启动。随后读回data/health.json、data/metrics-latest.json及本轮data/runs/run-*.json。SQLite的requests和records保存源时间、实际请求/接收时间、原始响应哈希以及同时间点的修订版本。

## 固定预测与不做的事

- 每日00:00UTC（北京时间08:00）是唯一预测网格，必须在网格之后5分钟内实际记录。只使用此前完整小时及实际收到的数据。迟到则记MISSED_FIXED_GRID，不能回填、平移预测窗口，不能伪造issued_at。
- 首个可尝试网格为2026-11-10 00:00UTC；启动当天此前的网格记MISSED_AT_START。历史一致性/评分测试放tests目录，绝不计入真实预测数。
- 模型、特征、阈值、币池、历史输入由PROTOCOL.json、RUNTIME_BINDING.json及原v3绑定锁定。阈值0.5、每日Top10、同币同目标72小时冷却保持固定；这些是观察诊断规则，不是实盘开仓指令。缺失过多等DATA_OR_TIMING_LIMITED预测保留，但不进入Top10观察信号。0.5/1.0数量场景不作为两个独立事件样本。
- EVALUATION_PROTOCOL.json在第一笔真实预测前锁定评估口径。主模型与原冻结EMA72/最新费率或年龄基线在同一时点保存，观察完整已发预测群的Brier/AP及固定分箱；选中信号的命中率另列。14个成熟日、100条已观察选中信号仅作为首次描述性检查门槛，不能凭此自动采用新策略。
- 原策略−0.1%/8h、三天到币、到币后七天入场机会等定义均未改。不会根据前瞻命中结果调整特征、模型、阈值或币池。
- 2026-12-01起现有月度模型过期，停止新预测，继续公开数据和已发预测的结果追踪；不自动训练下一月模型。
- 未知行情不填价格/成交量/OI/多空比；没有支付记录不臆造一笔资金费。最新已结算费率的前向保持仅作为状态变量，仍受原8小时新鲜度判断。

## 来源与节流

只读币安现货/USDT永续公开K线、溢价、实际结算费率、合约/费率规格、5分钟OI与四类多空指标，以及Bybit实际结算费率。未使用账户API、API密钥或链上控盘身份推断。

所有请求GET且端点白名单；全局请求至少间隔180ms，资金费组最多440次/5分钟，指标组最多850次/5分钟。HTTP403/418/429/451持久化冷却；无Retry-After时403等默认等待1小时、429至少10分钟；不切换地址、代理或连接器绕过限制。冷却过后由后续正常周期尝试，失败继续留证。

原历史特征中OI有一小时预滞后、多空指标取所属小时最后一个实际观测。实时计算保留该差异，记录观测时间与缺口；5分钟采集未齐的小时可能仅有较早观测，不能视为原始历史归档的完整覆盖。

## 结果与限制

72小时转负和168小时不触发raw24退出使用真实结算整数精度及覆盖检查独立重算；首次缺失之后的未知结果不计失败。早期事件仍需等完整固定窗口成熟。迟到补齐只追加修订、标记late_data，排除主结果，不能覆写首次记录。

到币后7天“合格入场”和30天完整退出参考净额，成熟后仍需按冻结策略成本/容量/生命周期引擎完整重算。本采集版会明确记PENDING_FROZEN_STRATEGY_RECOMPUTATION，不用“出现负费率”替代合格入场或利润，不将这两类待复核标签计入命中率。费用/自身冲击仍有模型假设，前瞻信号验证不等于实盘收益验真。

不重训、不优化阈值、不更新站点、不恢复旧v2或其他暂停任务、不下单、不借币、不转账、不向外发送消息；旧数据库只读。

## 运行依赖

这是本机采集任务，须保持电脑开机、网络可用、Codex应用运行。应用调度、休眠或交易所中断造成的漏采/漏发如实记录；不承诺每个网格一定发出预测。模型或代码哈希不一致时保留失败证据，停止评分，不能自动改绑定绕过。

官方来源：

- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
- https://bybit-exchange.github.io/docs/v5/market/history-fund-rate
- https://bybit-exchange.github.io/docs/v5/rate-limit
- https://learn.chatgpt.com/docs/automations?surface=app
