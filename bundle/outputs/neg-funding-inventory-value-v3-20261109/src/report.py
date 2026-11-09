from common import *
import zipfile

def main():
 f=pd.read_csv(OUT/'summary.csv');val=json.loads((OUT/'VALIDATION.json').read_text());audit=json.loads((OUT/'LABEL_AUDIT.json').read_text());event=json.loads((OUT/'EVENT_RESULTS.json').read_text());diag=json.loads((OUT/'TURN_VS_BORROW_VALUE.json').read_text());sub=json.loads((OUT/'PRE_TURN_ARRIVAL_RESULTS.json').read_text());gate=json.loads((OUT/'FIXED_05_GATE_DIAGNOSTIC.json').read_text());decision=json.loads((ROOT/'ADOPTION_DECISION.json').read_text());causal=json.loads((OUT/'CAUSALITY_AUDIT.json').read_text());con=pd.read_csv(OUT/'incremental_concentration.csv');fit=json.loads((OUT/'TRAINING_AUDIT.json').read_text());cols=['hurdle_full','old_short_net','EMA72','capacity_EMA72','EMA720','MLP64_32'];t=f[(f.scope=='long_period')&(f.refresh_days==15)&f.method.isin(cols)].pivot(index='method',columns='period',values='closed_net_usdt')/1e4
 taskrows=[]
 for x in event['summary']:
  if x['method'] in ['fixed_HGB_full','fixed_HGB_base90','EMA72_calibrated']:taskrows.append({'目标':x['task'],'方法':x['method'],'已知分母':x['cooldown_observed'],'命中':x['cooldown_hits'],'已知结果命中率%':100*x['cooldown_precision'],'未成熟/删失':x['cooldown_alerts']-x['cooldown_observed'],'AP':x['AP'],'Brier':x['Brier']})
 tasktable=pd.DataFrame(taskrows);tasktable.to_csv(OUT/'信号预测对比.csv',index=False,encoding='utf-8-sig');t.to_csv(OUT/'组合净收益对比_万U.csv',encoding='utf-8-sig')
 text='''负资金费率信号预测 v3：升级迭代与独立检验
生成时间：'''+now()+'''

结论
本轮完成了四类目标、125项经济特征/116项事件特征、月度按时点训练、独立币种检验、神经网络对照和164组组合回放。新模型适合作为研究候选，暂不替换正式RC2，也不修改交易门槛、退出或加仓规则。
最应修改的是“我们到底预测什么”：出现一次负费率、到账后出现合格机会、已经为负还能维持多久、库存能带来多少净价值，必须分开。不能用一个漂亮命中率代表借币或实盘收益。

一、为什么改目标
上一轮2026年7月至10月回放的321笔已平仓交易中，持仓超过14天的55笔贡献1,202,965U，占1,286,020U已平仓净收益约93.5%。7天以内182笔合计亏损约22,754U。这个按事后持仓时长分组的结果只是来源诊断，不是可用于入场的已知特征，也不能证明未来每次持仓越长越好。
全库存回放中，前一时期最高成本本金约555.34万U，后一时期约362.24万U；总资金成为建仓绑定约束的候选小时均为0。当前样本的主要问题是库存覆盖、负费率持续时间、单币容量和成本，不能先假定1,000万U共享资金挤占是低收益主因。未来规模改变仍需重新检验组合资金约束。

二、四个输出，各自回答不同问题
A. p_new_negative_within72h：目前最新已结算费率非负，未来72小时会不会出现一次负的结算。可以只是很浅、很短的一次转负，不等于−0.1%/8h交易门槛。
B. p_qualified_entry_after72h_within7d：今天提出借币，72小时后到账，在其后7天是否至少出现一次符合冻结策略条件的首笔机会，包括严格费率门槛、基差、成本、已知成交量/OI、存续和数据条件。不是盈利概率。
C. p_no_raw24_exit_next168h：目前最新结算为负、已知最近24小时原始合计<=0，接下来7天是否不出现严格转正的原始24h合计或交割。不是每一笔结算都为负。
D. conditional_30d_reference_net_usdt：假设72小时后借到指定数量，30天允许入场，再给9天按成交量约束退出的独立币种参考净值。零交易保留0，未完成回购或数据缺失保留删失。它不是组合边际收益，不可把各币预测值相加当成组合收益，也不是实盘预期。
借来的币可以长期保留。30天是本次有限估值窗口，不是新增强制还币或持仓上限。真实可交易库存仍以实际到账数量为准。0.5/1.0是给定币量的条件场景，不是借币到账概率。

三、数据与模型
市场价格/成交量/OI/结算数据覆盖339个币，小时研究数据从2025年7月开始，观察至2026年11月8日。90项原特征保留；新增过去已完成负费率周期、现金费率EMA、数量/容量、成本与跨交易所已结算现金费率差。跨所接入306条缓存映射，实际按文件哈希逐条核验；有效样本约90.8%有近期Bybit结算观测。缺失保留标记/NaN，没有编造链上持仓、控制人、盘口历史或真实借币到货记录。1/4/8小时合约均保留，费率门槛按8小时归一化，现金流按真实结算原始值累计。历史新鲜度仍沿用最长8小时代理，可能不能识别小时合约漏打印；“已知”与删失均相对这一保留代理而言，不是逐笔到达时间证明。
长期价值标签31,256条，31,234条完整，22条尾仓删失。每条从决策至标签成熟需要完整1,008小时。数据包括零、正、负结果，不能只挑已赚钱的长期负币。
经济主模型事前固定为两阶段HGB：P(|参考净值|>1U)×E[有活动条件下的有符号参考净值]。另比较直接HGB、Ridge、64×32 MLP神经网络、原90特征消融、去跨所消融、旧短期模型、最新费率、EMA72、EMA720和容量加权EMA。事件模型比较固定HGB、原90特征HGB、逻辑回归和简单规则。
315个实际训练组件包含99个经济模型组件和216个事件/校准组件；不是315次参数搜索。没有看到测试收益后改选模型家族。事件任务最后60天只用于概率校准，不参与早期训练。普通转负诊断后新增“到账后合格机会”任务，已单列登记为探索性扩展，未伪装成最初盲测方案。

四、高命中率的陷阱
2026年3月至10月，每日最多10条、同币72小时冷却的同额预警比较：普通转负新模型2,284/2,450命中，93.22%；EMA1,996/2,449，81.50%，另1条未知。已命中的首次转负中位数都只有4小时，均发生在72小时借币到货之前。
更重要的是，普通转负新模型挑出的预警，到账后7天真正出现冻结策略合格机会的仅354/2,408，14.70%；EMA对应548/2,408，22.76%。它学会了找“容易很快轻微转负”的币，不能据此说借币更有用。
直接改为到账后机会目标，并只在“现在尚未转负”的同一币池排名，新模型609/2,400，25.375%；EMA548/2,408，22.757%；原90项特征模型605/2,404，25.166%。各2,450条预警，其余50/42/46条未知仍保留，未当失败或删除后再选信号。
这是约2.62个百分点的历史提升，尚不能认定有稳健实盘增益。固定概率>=0.5并允许不发信号时，新全特征模型仅242条，108命中（44.63%），有122天不发；原90特征模型284条147命中（51.76%）；EMA160条82命中（51.25%）。更复杂版本没有稳定优势。固定前10只是同预算诊断，不是要求每天必须借10个币。

五、事件模型对照
下面各任务的当前适用币池不同，不可横向比较百分比。转负只在当前非负池；7天延续只在当前负且原始24h合计非正池；到账后机会使用全部当前有效池。不同日期的标签也会重叠，不能当成独立2450次抛硬币来计算显著性。
'''+tasktable.round(4).to_string(index=False)+'''

六、真正放回组合后怎样
统一1,000万U、0借币息、B1x、给定原币数量、借币72小时到货且退出后保留库存，使用冻结费用、冲击、容量、退出规则和精确整数资金费合计。15天一批最多20个新币，用同样预算比较；不是假设真实借币有确定总额度。
前一时期：2026-03-01开始信号，06-22停止新增，观察/退出至06-30；后一时期：2026-07-01开始，10-30停止新增，观察/退出至11-07。两段独立冷启动，不是一条连续收益曲线。单位万U，表内为已平仓净收益：
'''+t.round(2).to_string()+'''
新模型对旧短期模型分别增加约16.47万、7.27万U，但也改了标签、训练节奏和模型结构，不能全部归因于某一项修改。
相对EMA72，前一时期少赚约9.61万；后一时期多赚约25.43万。后一时期DEXE单币增益约30.18万，扣除该项贡献后其他币合计约−4.75万。这里是贡献表减法，不是删除DEXE后重新跑组合的反事实结果。
30天一批40个币的匹配请求强度诊断，新模型前/后约101.72万、103.26万，对比EMA约90.70万、75.13万。它比15天20个在部分周期更好，说明不能事后改用最好的一组频率宣称主模型通过。事前主口径仍是15天20个，未通过稳定性门槛。
下半年主表新模型和EMA都仍有1个未全部回购的币种，尾仓与未平仓损益分别记录在summary.csv；已平仓净收益不包含尾仓估值，不是全部还币后的已兑现策略收益。本报告不把它们换算为可兑现年化。
半量库存与k=0外生历史费率对照均已完成。它们没有扭转前一时期新模型输给EMA的事实。k=4仍无法由公开行情识别为自身永久费率影响系数；本轮冻结它只用于一致比较，另保留k=0对照，不赋予因果含义。
神经网络前/后约89.56万、99.43万，未稳定胜出。它只代表这个有限MLP对照，不能概括所有深度学习模型。新增跨所和周期等特征的消融同样没有跨时期一致增益，不因特征数量增加就升级正式模型。

七、经济含义与“庄操盘”
交易所资金费率受溢价指数、利息/夹限和结算周期规则影响。预测应拆成现货相对紧缺、永续贴水持续、跨所套利是否顺畅、反向交易者的资本/借币/保证金限制，再用可观测变量检验。资金费率为负本身不能证明某个控制人在操纵。
OI是未平仓合约规模，不是净空仓数量；每份合约都对应多空。账户多空人数比也不是资金加权净持仓。现货上涨、OI增加和负费率共同出现，可以支持特定市场结构假设，但不能单凭这些给出操盘身份或动机标签。跨所差只说明相对分割/错位的候选证据，链上持仓也需要地址归属和实体去重。
BIS的Crypto carry研究支持套利资本和保证金摩擦会使价差持续，但该研究主要是BTC/ETH及正向carry，不能直接当作我们山寨币负费率因果证明或冲击参数标定。

八、怎么防止过拟合，本轮实际做了什么
先固定主模型、参数、基线和验收门槛；月份向前推进，只用标签完全成熟的数据；未来1,008小时长期标签不能混入训练。预处理只在训练集拟合，关闭随机早停，不用随机切分替代时间检验。
保留简单规则、所有家族、所有消融、零收益、亏损、尾仓及删失；对同一批预测也计算共同有分数样本的比较，避免长EMA缺失导致机会池不同而误归因。
哈希固定20%币种从经济模型训练中排除，专门检查陌生币；不把持仓结果、未来深费率或币名写入特征。币种留出仍共享市场和冻结成本表，不等于完全独立市场检验。
对新特征做未来市场扰动：修改2026-07-01及之后价格、成交量、费率、OI等，之前的特征、条件数量参数和可用状态逐值不变，之后确实改变，源文件不改写。这证明计算时点性质，不能代替真实received_at记录。
分币增益、8个月冷启动、半量库存、不同请求节奏及外生费率对照全部保留。历史数据已经被看过，多次扩展的选择偏差仍存在，因此不把本轮称为新的盲测或承诺实盘收益。

九、采用决定与交付边界
经济主模型未通过事前跨时期稳定性/集中度门槛，保持WATCH_ONLY。正式策略、JSON交易决策包和暂停任务不改。新JSON输出只是辅助研究分数，没有下单、借币、划转或执行动作；若库存已经到账，不把72小时新到货价值模型误用于现有库存。
可以保留：四个分离目标、到账后机会的直接建模、长期价值标签、因果时点校验、允许无预警的评估，以及原90特征的简化对照。
尚不能确认：新增复杂特征稳定提高命中或净收益、深度网络更优、操盘因果、真实借币供给、真实自冲击、盘口和费率在我们介入后的反馈、当前时刻有效信号。样例截至2026年11月5日，是已过期历史快照，明确标记STALE，不能当今日借币名单。
下一轮应在这份冻结候选上做不调参的人工/现有系统观察记录，逐条核对预计到货时点、实际到货数量、当时可见行情与后来合格机会/净值；先收集真正独立的新结果，再决定是否升级正式信号。没有恢复或创建定时任务。

十、验证与文件
15项接口/时点/数量/JSON检查通过；155个正式清单文件、5项固定研究输入哈希不变；8组旧引擎控制收益逐值差0；164组组合账本/到货/库存检查通过。最大联合账本恒等误差约'''+str(val['max_cash_identity_error_usdt'])+'''U。1x仅检查小时收盘代理，不等于盘中清算风险检验。22条长期价值尾仓删失保留；事件任务先对全部当前有效币选预警，再按可观测结果计分，未来未知不提前剔除。
本次捕获并保留了一次建标签参数名错误和一次重评分入口错误日志；事件打分发现提前排除删失样本后，使用同一144个已拟合组件重评分，未重训或改阈值。随后新增到账后机会任务的72个组件均单独登记。旧错误诊断放在diagnostic-before-censor-selection-fix，不属于最终结果。
完整组合结果：results/portfolio_comparison.csv、summary.csv、RESULTS.json
事件结果：results/EVENT_RESULTS.json、信号预测对比.csv
借币目标诊断：results/TURN_VS_BORROW_VALUE.json、PRE_TURN_ARRIVAL_RESULTS.json、FIXED_05_GATE_DIAGNOSTIC.json
币种和月份：results/*_coin_delta.csv、monthly_cold_start_comparison.csv、coin_generalization_same_rows.csv
验证：results/VALIDATION.json、CAUSALITY_AUDIT.json、LABEL_AUDIT.json
模型和样例：data/models.joblib、data/event_models.joblib、interface/*.json

公开一手资料
Binance资金费率定义与周期/公式：https://www.binance.com/en/support/faq/detail/360033525031
BIS Crypto carry及适用范围：https://www.bis.org/publications/working-paper-1087-crypto-carry
scikit-learn时间序列验证：https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
固定HGB与缺失值支持：https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html
'''
 (ROOT/'研究报告.txt').write_text(text)
 readme='''负费率信号 v3 离线研究接口
此包只提供研究侧特征快照到研究分数的JSON协议。执行方只消费结果时，不需要部署训练环境。这不替代正式策略账户/订单输入输出协议，不生成订单，不连接交易所。
状态：WATCH_ONLY；submission_allowed恒为false；execution_actions恒为空。
输入125项冻结特征，事件模型使用前116项；四项分数分别定义于输出forecast_definitions。输入须00UTC日决策，特征截止上一完整小时；数量场景必须落在训练0.5..1.0支持范围并与特征一致。
已有可用库存时，72小时新到货的30天参考价值返回null；生存概率只对当前负且已知raw24<=0适用。币种数量/真实到账记录仍需执行方/账户事实输入；此包没有借币供给预测。
历史样例不是当日信号，输出内有过期标记。任何零至十条预警门槛需独立验收，研究固定前10只用于等预算比较。

本机运行示例（工作目录为本研究目录）：
'''+str(PHASE2/'forward_validation_v2_20261107/.venv/bin/python')+''' src/signal_cli.py interface/historical-nonnegative-input.json
也支持从标准输入传JSON。输出一行JSON；非法输入返回INVALID_INPUT并以2退出。

新环境离线评审：使用Python3.12和requirements-research.txt中冻结版本。环境安装/内网接入不属于本包已完成的现场验收。INPUT_SCHEMA.json与FEATURES.json供协议核对；完整特征构造和因果验证在研究源目录src/features.py、audit_causality.py，不要依特征名自行猜单位或从当前数据回填历史。

研究重跑依赖本机冻结源市场数据和原始项目文件，顺序：
python src/build.py
python src/train.py
python src/replay.py
python src/signal_heads.py
python src/signal_heads.py --add-arrival
python src/event_diagnostics.py
python src/arrival_subgroups.py
python src/gated_alerts.py
python src/analyze.py
python src/audit_causality.py
python src/verify.py
python src/report.py
PROTOCOL及后续任务扩展登记保留，不重新执行register脚本覆盖。

正式RC2未修改，未部署站点、未推送仓库、未恢复定时、未借币、未转账、未下单。
'''
 (ROOT/'接口与复跑说明.txt').write_text(readme)
 decision['signal_event_status']='RETROSPECTIVE_RESEARCH_WATCH_ONLY';decision['candidate_added_features_beats_base90_consistently']=False;decision['actual_new_component_fits']=fit['component_fits']+event['component_fits'];decision['final_validation_passed']=val['passed'];decision['formal_files_unchanged_verified']=val['frozen_files_verified'];decision['borrow_advisory_focus']='arrivalqualification after72h, not anyturnwithin72h';save(ROOT/'ADOPTION_DECISION.json',decision)
 package=[ROOT/'接口与复跑说明.txt',ROOT/'requirements-research.txt',ROOT/'ADOPTION_DECISION.json']+[ROOT/'src'/n for n in ['common.py','model.py','signal_cli.py']]+[ROOT/'data'/n for n in ['models.joblib','event_models.joblib']]+list((ROOT/'interface').glob('*.json'))
 with zipfile.ZipFile(ROOT/'信号v3_离线研究接口.zip','w',zipfile.ZIP_DEFLATED) as z:
  for p in package:z.write(p,p.relative_to(ROOT))
 files=[p for p in ROOT.rglob('*') if p.is_file() and p.name not in ['FILE_HASHES.json'] and not p.name.endswith('.log') and '__pycache__' not in str(p) and '/scratch/' not in str(p)];save(ROOT/'FILE_HASHES.json',{str(p.relative_to(ROOT)):sha(p) for p in files});print(json.dumps({'report':str(ROOT/'研究报告.txt'),'interface_zip':str(ROOT/'信号v3_离线研究接口.zip'),'files_hashed':len(files),'component_fits':decision['actual_new_component_fits']}))
if __name__=='__main__':main()
