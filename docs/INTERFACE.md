# 信号输入与输出

输入为 `nfb.signal-input.v3`。必填：request_id、symbol、asof_utc、feature_hour_start_utc、conditional_arrival_fraction、inventory_status、raw24_known、information_mode和完整125字段features。

asof_utc固定每日00UTC；feature_hour_start_utc必须为前一完整小时起点。UTC时间带时区，特征值为有限数或null。最新已结算资金费必需。数量特征必须与0.5—1.0到账情景一致。实际收到的快照用 observed_asof_snapshot；历史小时代理用 historical_hourly_proxy。

输出为 `nfb.signal-output.v3`，关联request_id、symbol、时点、有效期、fit_month、model_version、数据质量和训练窗口元数据。forecasts：

| 字段 | 目标 | 成熟窗口 |
|---|---|---|
| p_new_negative_within72h | 当前非负时首次出现负的实际结算；不等于跨过−0.1%/8h | 72h |
| p_no_raw24_exit_next168h | 当前负且raw24已知时，未来不触发raw24严格转正退出 | 168h |
| p_qualified_entry_after72h_within7d | 币72h后到账，在[t+72,t+240)存在冻结策略合格入场 | 240h |
| conditional_30d_reference_net_usdt | 假设三天到账，30天入场窗口及后续完整退出的参考净价值 | 1008h |

不适用的事件头返回null；数据或时间不足标DATA_OR_TIMING_LIMITED。全部输出保持research_only=true、submission_allowed=false、execution_actions=[]。已有库存不会被当作新的72h到账情景产生经济价值。

固定预警门槛0.5、每日最多Top10、同币同目标72h冷却属于前瞻选择层；单次score输出概率，不会直接创建预警或写前瞻账本。把实际输入、输出、源文件哈希和模型哈希交给原前瞻记录器，只有网格后5分钟内实际发出的预测才能进入真实统计。


非法输入返回status=INVALID_INPUT、error及submission_allowed=false，CLI退出码2；合法输出/错误输出均由OUTPUT_SCHEMA.json定义。文件哈希异常在加载模型前停止，不能以错误模型继续评分。

公开入口 `scripts/score.py` 在冻结模型外验证根目录Schema、重复JSON键、非有限常量和未来快照；非法输入退出码2。`schemas/INPUT_SCHEMA.json`为公共接口合同，`interface/INPUT_SCHEMA.json`同步。数量情景特征不可为null。直接调用bundle中的研究CLI不会自动获得这些包装校验。

公开样例使用历史公开行情加合成库存；不能把样例经济头输出解释为真实到账金额对应的结果。
