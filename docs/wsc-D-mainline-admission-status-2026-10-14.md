# 有证实进展直接接主路：当前实施与历史改动分类

用户本次明确授权：之前和之后有进展的修复直接成为真实实现。此要求取代旧“新机制只旁路/等待整个Goal后并入”的流程。每项仍先三轮复审并验证正确性；有对应收益且正确就接主路，无需再次确认。完整Goal、质量底线和冻结头不变。

## 本轮已接入真实生产路径

### 1. 专用交接原助手帧

路径：engine/query_loop（及手动压缩入口）→memory/wsc_handoff_prepare.prepare→wsc_handoff_generation.generate→读取/拒绝续接。

新 `memory/wsc_handoff_frame.py` 复用主模型已有assistant_text_message和native signature校验；generate直接把原正文、思考/签名块与同一工具调用放进请求数组。读来源及被Guard拒绝后的下一轮都修复。无需ReplayModel/评测transport包装，无新增flag，发送前计数也看到完整原帧，避免“计数小、实际发送大”。不新增语义总结、持久化authority、模型提示或冻结头文本。

接口原JSON参数格式仍按底层既有parser/main-model构造处理，本修复不声称保留原argument字符串所有空格。DeepSeek普通reasoning与Anthropic签名块按各自编码验证；没有占位思考。

定向41/41通过：新帧7项、真实query_loop容量/恢复/失败连续性既有合同。第一次测试2项失败源于把Anthropic签名块要求成DeepSeek reasoning_content字段，保留XML，改为检查各自原生编码。不是删签名或改生产数据过测。测试不依赖ignored experiment目录，可在新checkout执行。

再离线重放280已付费的6个provider响应，直接通过改后production generate、不经过ReplayModel/ProviderFrameModel：配置4次、素材2次，最终candidate及usage序列与原记录一致；7次历史帧检查的正文/思考、调用身份及解析参数一致。新API0。这是实际生产函数重放，不是现场SSE服务部署证明。

### 2. U1机械/语义校验结果分责

路径：wsc_handoff_transaction.commit→prepare返回→working.wsc_timing_state.last_handoff_commit。

保留call_id/source_fingerprint/committed_source/task_count，新增mechanical_status=VALIDATED、validation_scope=handoff_structure_source_identity_and_commit、semantic_status=SEMANTIC_UNVERIFIED。只指既有机械合同与实际提交成功，不宣称source语义支持objective，不宣称完整新registry/file版本合同已实现。

实际事务10/10正反例通过，含没有语义支持的自然语言objective仍机械接受但SEMANTIC_UNVERIFIED；失败来源/取消/发布失败不返回成功。随后真实query_loop定向4/4通过，状态随实际提交返回，未消费结果与重启仍保住。原41套中的4项在此次状态变化后重跑，不计成额外4个独立新场景。

源码已默认使用上述逻辑，未自动重启或中断正在运行的XEYO。当前实际服务是否重载新模块尚未现场核实，不能称为已验证现场会话采用。既有模块/事务/测试的其他修改保留，未提交混合工作树。

## 之前的修改如何处理

| 类别 | 具体改动 | 当前处理 |
|---|---|---|
| 原生已有能力 | 来源/引用、原子TodoWrite事务、phase声明、80%/85%、失败原文/旧状态恢复、未消费结果保护 | 已在对应生产路径；本次不重复重写，已执行定向入口验证 |
| 本次已接主路 | 原助手帧保留及统一计数；机械校验与语义未验证返回 | 默认生产逻辑，无新增开关 |
| 评测入口修复 | ExactArtifactSink、durable actor、未压缩/压缩后文件oracle | 已在279/280评测实际使用；生产文件工具有自己的安全/rewind/事务，不导入eval替代它 |
| 原型局部修复 | AD phase身份22/22、SEMANTIC_UNVERIFIED原型结果 | 留在AD测试实现；native已有phase检查，完整runtime registry未做，不能用原型快照代替它 |
| 局部正向，待直接生产准入验证 | 239精确新来源呈现；冷完整回执/locator/record读取 | 优先评审真实入口和增量收益后直接接入，不再要求等待整个Goal。原生HandoffSource当前已返回tool block JSON含execution；payload解码漏metadata属于eval cold候选，不能重复修复一个生产已有的信息 |
| 未有稳定增益 | 237仅tool_choice、253语义句、254fact-id退休、260metadata自动展开、263默认为热层物化 | 不启用；合法输出/一例字段改善不能覆盖已知失败与额外热开销，不把接主路指令解释成全部flag置开 |
| 待完成真实机制 | epistemic、显式transition/version/关系、原anchor呈现、runtime phase registry、薄生产投影 | 与U2–U6按完整Goal继续，源码/范围/旧状态兼容三轮后逐项落地并接主路 |
| 验收/模型问题 | A1 2048截断、短任务调用上限、Scope/目标调用用途污染、多代稳定性 | 保留原失败，用实际任务同条件对照；不会成为未经证明的产品补丁 |

候选导入静态扫描显示13个memory candidate；扫描中的5处引用均是候选之间相互引用，不是生产入口证明。此结论只限静态import，不声称穷尽所有动态加载或当前有效flags。报告保留在281/candidate-import-audit.json。

## 后续固定准入

1. 具体三轮复审、必要前后与失败/恢复验证，证明该修改正确且有对应收益。
2. 验证通过即接入所属真实路径，测试/评测修复接评测主流程，生产修复接引擎主流程。不再以“旁路”作为长期终点。
3. 不把语义未验证当PASS，不削弱旧Guard、不重写既有冻结前缀；重要用途/事实/状态所有者继续分开。
4. 逐项注明源码接入、实际服务加载、现场行为三种证据。当前Goal仍active，长期/冷/媒体/原228/泛化/A1质量目标未完成。

本轮新API0、费用0；新原模块为HandoffFrame，原generate/feedback/transaction是必要接入口；新增/增量测试为frame/transaction/capacity-loop。旧报告、旧模型调用、Goal附件及台账只追加最新政策，不覆盖历史。


## 2026-10-14：283来源增量已默认接生产，282真实热层差距已记录

落实最新授权：验证正确且有收益即接所属主路，过去和未来均同；不启用失败候选。281原助手帧/计数及机械/语义状态分责已接入，本轮wsc_handoff_delta经generate默认调用，无新flag。纠正历史命名：239提交后全部完整文本增量不等于recent每角色八条。真实请求在预计数前纳入增量，容量不够整条defer，空包及metadata自身无空间不增加失败；呈现ledger只认实际发送。

最终91/91定向合同；初次55通过/2空包兼容失败已保留并修复，未修改旧断言。239两会话衍生受控事件四份历史请求payload4/4相等。API新增0、费用0；历史24/24只适用原required通道两样本，不转记为当前auto已全面通过。源码接入，当前XEYO进程未重启，现场重载未验。

282直接调用生产project发现task_handoff仍9444/9695估算tokens，完整热头13693/12627（同UTF8估算器，非旧tokenizer）；来源和验收回执再次展开。280直接JSON任务行为不能替代生产renderer验收，薄生产投影仍未完成。详细结果/三轮评审见docs/wsc-D-source-delta-mainline-results-2026-10-14.md及wsc-D-source-delta-mainline-review-2026-10-14.md，证据282/283。

固定未完成：U2–U6、控制请求污染objective/scope数组来源资格问题、薄生产热层/精确冷恢复、原228质量底线及跨域长任务1/3/5/10代和重启/迟到/取消/重开，最后经济指标；不缩Goal，仍active。旧冻结头和台账前缀保持字节一致，仅追加。


## 2026-10-14：284–289原始anchor与明确截断恢复已接入默认主路

完整结果见docs/wsc-D-original-anchor-and-truncation-results-2026-10-14.md，三轮评审见original-anchor-three-reviews/output-exhaustion-three-reviews。generate默认用精确quote ancestry重新呈现工作集遗漏的原始普通文本，16KB整条/容量准入、去掉重复呈现；父引用与延期anchor的呈现账本同时保留，metadata不等于语义理解。真实239原始根5/4个均已在工作集，本项额外原文0/0，不假报提升。

厂商length/max_tokens给兼容原父类的机械类型，handoff不提交截断帧，额度在原6次调用内倍增至原8192上限；完整预计数/caller预算/account先执行，HTTP/拒绝/断流不重试。默认生产调用，沿用原显式关闭配置，无新增旁路开关；达到上限仍按原状态/原文续接。源码默认接入，未重启现场XEYO，现场重载未验。

最终定向180/180，包含实际provider httpx/stdlib边界、取消/事务/容量/引用链/父引用呈现；1/3/5/10层只是机械引用链，不是同代模型任务验收。免费12份真实已付费请求前部反事实：没有截断恢复时接受1/4，实际新实现接受4/4并四个文件正确，不改Guard或oracle；不是新采样或A1胜负。

原285/287自己发现todo夹具是旧WSC第二批/report.json而goal是支付/result.json，原数据降为混合状态压力，不覆盖失败/来源/调用/费用。独立289修正准备层：两臂各2/2接受、2/2压缩后文件且正常结束；无anchor交接11/主任务8调用，有anchor交接9/主任务9调用；费用各估算0.20813648/0.12684088元。仅两同领域构造任务，不声称anchor提高成功率。四例热头缺完整必需值后都从精确冷返回恢复并正确交付；SourceCatalog完整preview也算实际读取，不仅按SourceRead名称计。仍为native JSON组件表示，不是282生产full renderer。

本轮96新HTTP/96usage，费率估算0.97553896元、单次最高0.06611176元、输入cache hit86.33%；未当作97%或长期经济验收。免费重放不再付费、不计新模型样本，旧未知费用预留不丢，无HTTP重试。287资源准入停止后在既有无限累计授权下延续，仅新请求外发，前四份响应核对body/hash后离线重放。

固定未完成：U2 epistemic、U3显式transition/fact版本关系、U4重要变化强制原anchor检查、U5边界完整落实、U6真正runtime phase registry；当前独立fact_scopes数组仍出现2/3事实各1scope、phase/context与disposition层次错误。下一步同一fact记录携scope、无损接旧持久格式并复用Guard，不能自动补猜scope；objective受控制请求污染也保留。原228底线、A1新对照、真实1/3/5/10代/重启/迟到/过期/范围/取消/重开、跨域及生产薄热头/实际冷Read/媒体、最后经济性全部待验，Goal仍active。旧冻结头和台账前缀未改，只追加。


## 2026-10-14: 290/292

# D 同项 scope：主路协议实现与两域实际产物对照

## 结果与准入边界

原始来源、quote 与 scope 在专用生成接口中成为同一记录；编译到既有持久格式后仍由原 native Guard 校验。默认入口已接入，没有新 flag、持久化格式或迁移；没有重启现场 XEYO，所以源码默认生效不等于现场长会话已经重载。

本项收益是表示层消除独立 scope 数组的错配入口、缩小 schema。不是 Guard 判断语义，也不是任务成功率提升。本轮两域两臂均成功，没有证明 D 超过 A1，不能代替原228或多代验收。


146/146 targeted checks; 31 HTTP/31 usage; estimated CNY 0.28982992; HTTP retries=0.

Evidence: [290/292](wsc-D-inline-scope-results-2026-10-14.md).

## 固定方向 TODO

- [x] 同项scope编码及无损旧格式提交；默认主路，无新增开关。
- [x] 原始响应重放、原Guard拒绝、真实持久化恢复与冻结头局部合同。
- [x] 新两域同源对照与实际文件成功；保留所有调用、费用及原失败。
- [ ] 控制请求与原任务状态的身份边界，三轮评审后独立消融；不靠关键词删除模型生成的objective，不把控制请求当用户新目标。
- [ ] U2–U6完整状态协议；不得用同项scope代替事实生命周期、版本或registry。
- [ ] 模型自身实际1/3/5/10次压缩、重启/迟到/过期/范围/取消/重开/失败恢复及独立留出任务。
- [ ] 生产薄投影与实际Read/媒体精确冷恢复、必要信息误删、原228质量底线。
- [ ] 同条件A1最终质量对照；质量相同后再验收开销、缓存及成功任务成本。

完整Goal保持active，不缩小六轴、不把协议改进当作整体完成。旧冻结头和账本既有字节不改。


## 2026-10-15: 293–302 协议恢复与载体对照

完整结果：docs/wsc-D-protocol-recovery-and-control-results-2026-10-15.md。专用完整声明 merge=false 与 Guard 对齐；非法声明/未知工具批次原子拒绝、0执行，复用原六次额度中性反馈，纯读并行和原始帧保持。已接默认源码入口，无新flag，未重启现场XEYO。185个不同定向检查通过。

294四臂三任务：D三种载体严格文件3/3、A1为2/3（其内容3/3，多余嵌套副本导致strict失败，不等于摘要错）。296和300独立对照均legacy3/3、split2/3；split仍候选，不拼接分数。299免费回放4份旧付费body后1次新交接接受，文件正确但错误路径请求导致strict0/1；302回放2份后1次新交接接受且一次正确写文件，strict1/1。均在原六次额度内，不改原响应、不重试HTTP、不覆盖旧失败。

174新HTTP/174usage，旧费率情景估算1.54404896元，单次最大0.06513248元、输入cache hit84.01%；包括298评测准备错误额外5次/0.0216612元，未伪称D恢复成功。历史未知费用预留不丢，免费6份重放不计新样本。native JSON任务证据不代替生产完整renderer或真实长任务。

固定TODO：完整schema↔Guard机械矩阵（step id已经required，不能误报缺少存在性）、控制调用与原任务边界、U2–U6、生产薄热层及真正Read/媒体恢复、1/3/5/10次模型压缩/重启/迟到/未消费/范围/取消/重开/失败与留出任务、228底线和同条件A1。仍不能宣称超过A1或全部治本，完整Goal active。旧冻结头与账本前缀不改。


## 2026-10-15: 303–304 持久身份与fallback发布闭环

结果、文件及固定TODO：docs/wsc-D-shape-and-fallback-results-2026-10-15.md。默认已修：最终持久ID归一化碰撞；已有活跃声明必需形状与Guard对齐/有界中性恢复；收益门fallback代复用同一head_store发布验证与_emit，显式无收益沿用原头时持久化本代身份。旧冻结头字节和旧冷对象不改；无新flag/状态存储/迁移/模型调用，未重启现场XEYO。

最终20文件定向277/277，隔离Draft2020-12同15输入对照；API0/费用0。原失败回归在旧302validator下仍失败，新实现原断言通过。304本地真实工具提交/落盘/fold/hydrate重建：cursor18→20、region_end保持18、头和旧冷对象SHA不变。来源是构造fixture，不伪称真实长会话/模型续接；第二次没有多吸收历史。

303中226通过1失败及实施首次重启失败均保留；11项新夹具错误是隔离后忘开WSC，另有1项旧默认OFF断言与现有恒True主路政策矛盾，保存旧测试后校正测试，不改生产开关。最终完整277通过，旧失败不抹、不重复累计。303合同矩阵中fallback未完成行按本追加闭环，本地范围已完成，不升级成现场/六轴通过。

固定未完成方向不变：控制用途污染/split仍候选；U2–U6完整状态协议；生产薄投影/模型按需精确Read与媒体/UsefulLoss；实际1/3/5/10代与异常/独立留出/现场重建；228底线和同条件A1；最后经济性。仍不能宣称超过A1或全面治本，完整Goal active。


## 2026-10-15: 306入口收尾及新对话三轮复审

收到用户此前待提供的A1/Prompt/结构化handoff/Hybrid对话。已完成正在做的生产验收入口，结果见docs/wsc-D-production-entry-results-2026-10-15.md：9/9定向测试（其中实际执行13/13旧actor合同，不重复相加）；两份真实206来源及各自已付费D声明，经真实commit/fold/project/原生Read/restart重建2/2。无新模型生成或continuation、API0/费用0。只是评测入口收尾，不称全query_loop/现场或语义质量验收。

当前同一token估算器两例checkpoint2252/2082，生产头18740/17048，完整本评测请求34843/29204；不能与282不同估算器直接相减。原body/头/来源/源码hash和Read均保存在306。现有actor默认支持原生ToolResult，老字典shape及未知副作用恢复保持；生产WSC行为未因本项改变。

三轮策略见docs/wsc-semantic-format-factorial-three-reviews-2026-10-15.md。当前封存A1 Prompt本身也是handoff，不能把问题误称为交接vs不交接。第一轮拆semantic要求、输出契约与最终投影并保留原版锚点，明确派生Prompt非原版；第二轮否决Runtime自行理解lifecycle和隐瞒额外提取调用，H0最小硬状态/证据层、H1按需语义sidecar分开；第三轮同源实际续接/自身多代与独立留出决定架构，原228与A1质量后再经济性。

不预设D定制格式必须赢，也不预设自然语言必胜。新实验尚未API执行；不将已有Guard通过或合法存档当语义证据。原六轴/U2–U6/未完成TODO不删除，候选选择凭证据；完整Goal active，不缩范围、不宣布D>A1。旧账本与冻结前缀只追加，当前真实会话未重启。


## 2026-10-15 307–309：交接内容/形式与投影首轮实测

用户要求连我的倾向一并实测。完成两历史检查点+一新合成交付任务的四格及A1提示词/native D参考：生成14/18；修正评测器后6/6新任务文件正确，已生成真实QA精确冷摘录0/8，不能宣称H0/D/A1全面获胜。NA与A1参考均出现第二批范围丢失，自然摘要来源ID不可靠；D/固定结构在长例出现来源/协议额度内未完成。307评测器权限cwd和Windows换行错误保留原始结果，308复用已有ExactArtifactSink并修正Read cwd，14份交接原样续接，没有重新生成挑分。309同一SD产物：薄头1411 vs生产14953，完整本评测请求8169 vs21711，事实7/8和精确召回0/1均相同；单配对不证明长期非劣。113次HTTP全有usage，历史价格情景估算约0.91813元，无HTTP重试。原始归档哈希保持。

结果：docs/wsc-semantic-format-pilot-results-2026-10-15.md；原始失败307、修正续接308、同产物投影309分开保留。没有新增产品语义机制或默认替换；后续评测用308正确的原生读取/字节适配。优先把精确恢复链与生成来源/协议成本拆开验证，投影精简按质量收益准入，再进入多代/独立留出；原六轴、U2–U6、原228底线、现场容量与失败续接要求不删除。Goal仍active，本阶段不等于全Goal验收。


## 2026-10-15 310：SourceRead综合续接负结果与评分审查

完整结果docs/wsc-source-read-continuation-results-2026-10-15.md。14份交接原样，首请求messages与308相同，只增已有SourceRead能力；真实QA精确冷摘录仍0/8，新交付6/6→5/6，消费者模型请求23→31，候选不准入，不新增生产机制。31API/31usage，旧价情景估算0.21901272元，无HTTP重试。2份原文直接读取/重开/8个坏地址、execution身份、seal及沙箱根边界免费核查通过，存档哈希保持。

重要解释修正：307–309把batch2_in_current_scope称为确定范围丢失说重了；228早已将其列为范围措辞歧义并排除主分数。原208 raw grade及所有旧报告行保留，不能据该项单独判scope错误，后续使用明确授权/范围转换事件。实际native D首请求也确实含msg_muykk1jd_mdii7o完整用户原文，不能归因输入漏掉“包括第二批”。来源ID不可靠、具体值/冷召回缺口仍存在，不因评分审查变成已修。

下一步明确状态事件的实际多代任务与有效恢复，不继续围绕旧歧义QA加工具/提示。原六轴、U2–U6、228底线、多代/异常/独立留出/现场容量/媒体等未完成项全部保留；Goal active，未宣称超过A1或治本完成。


## 2026-10-15 311–314：十代实际交付与事实角色默认修复

结果docs/wsc-ten-generation-results-2026-10-15.md。新transit-coral明确10事件两方法自身状态链；313修正事实外层角色后，A1生成10/10、状态80/80、任务10/10，D生成3/10、状态80/80、任务6/10，成功压缩并任务成功仅2/10。真实恢复3/3各臂通过；D实际生产发布退休边界13→30→36，不伪称十次生产fold。D重开/子集/资料刷新后文件停留revision2，最新输入revision4；没有实际写调用，不靠QA满分当任务完成。

312同一付费D产物、同输入只改source_record外层角色：assistant4观察状态0/32、真实任务0/4；user4观察状态32/32、真实任务2/4。313完整复验支持将评测外部事实载体修正接默认：新增evals/wsc_source_observation.py，公共wsc_elimination_chain.carrier重导出，非生产消息改动；33个真实wire载体相同。内部原始role/id/content与活动user原文不改。旧公共源码及所有原请求/原分数封存；幂等正确文件无需重复写的行为评分单列，明确不写仍严格0尝试/hash不变。

本轮146API/146usage，旧价情景估算1.14083616元，无HTTP重试；87个密封文件哈希保持。API余额未返回402，本轮无未知费用。未更改WSC生产语义/配置/冻结头；不能宣布D达到A1。优先继续查D声明协议修正循环及最终呈现/实际交付，不继续加检索工具。U2–U6、原228、独立留出、现场/媒体/UsefulLoss、完整异常等仍未完成，全Goal active不缩范围。
