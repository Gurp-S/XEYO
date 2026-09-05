# DeepSeek Harness（DSH）可借鉴机制对照报告

> 调研对象：`E:\nodejs\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\` 下约 150 个 `dsh-*` 包（均附高质量 README，为本报告主要依据；核心包另行精读源码级 README）。
> 对照目标：XEYO（`python/` engine + FastAPI server，`gui/` React+TS+Tauri，`cli-ts/` Ink TUI）。
> 方法：7 个并行子代理分簇调研 + XEYO 后端机制盘点 + 人工精读（agent-loop / session-persistence-jsonl / plan-mode / goal / fs-observation-policy / output-retention / repeat-tool-reminder / skill / mcp-client）。
> 每节格式：**DSH 做法 → XEYO 现状 → 建议（P0/P1/P2）**。P0=高价值低成本，P1=高价值中成本，P2=参考性质。

---

## 0. 总体判断

DSH 与 XEYO 是同一物种（单进程 agent harness + 桌面 GUI），但 DSH 的工程重心明显在四件事上，恰好都是 XEYO 的短板：

1. **日志是唯一真相**：一切状态（goal、plan、标题、调度、权限档位、投影缓存）都是 append-only 事件流上的纯函数投影；恢复 = 重放，不需要额外的状态文件。
2. **失败语义协议化**：审批、重试、超时、沙箱拒绝、工具截断都有结构化错误码 + 精确 marker 文本 + 内嵌恢复指令，模型和 UI 都不必"猜"。
3. **输出经济学成体系**：pruner → retention 库 → spill 落盘三层，截断永远带"省略了多少、全文在哪"的元数据。
4. **能力边界诚实**：沙箱如实报 `enforcement: 'partial'`、token 组成标注"近似"、completion 标注"worker 自我声明"——不把估计值当决策依据。

XEYO 的 T_now 管线与 DSH 的 runtime-context 是两种哲学（投影 vs 落史），**各有适用域，不必互相取代**（见 §9）。cordis 插件内核不建议照搬（见 §13）。

---

## 1. 会话持久化与事件溯源

**DSH 做法**
- `Session` 是 append-only 唯一真相，LLM 消息历史是**派生投影**；压缩/剪枝通过 `surfaceOp:{op:'replace',start,end}` 影子化旧条目，raw log 永不改写；`sourceEventSeqs` 溯源、`ignorable` 未标记的未知事件类型拒绝重建（前向兼容 fail-loud）。
- `request/header` 事件记录完整请求信封快照（provider/model/adapterDefaults），可逐字节重建请求。
- JSONL 后端：首行不可变 `SessionHeader`（含 `delegationDepth`、`agentPreset`——因其决定 resume 后的工具与提示）；≥3 条连续 chunk delta 打包一行（seq0/time0+dt 差值，实测省 ~60%）；zstd 分帧 + 每帧 checksum；lazy 首写发布（Windows `MOVEFILE_WRITE_THROUGH` rename，no-overwrite）；写失败回滚到先前字节长度。
- 写协调器：固定 200ms 批写窗（后到事件不重置 deadline）、`flush` 为 quiescence 屏障、后台失败保留批次暂停重试。
- **语义检查点**（checkpoint-policy）：模型请求前、顶层副作用工具体执行前、每 pre-step 边界强制 flush；flush 失败则请求/工具不运行（fail-closed）。
- 崩溃修复（仅冷启动）：保留中断 turn 真实事件，为每个未应答 tool call 合成 `TOOL_NOT_STARTED` / `TOOL_OUTCOME_UNKNOWN` 结果（后者文本按风险分级指导重试），再补 step/end、turn/end{interrupted}。
- 投影缓存：行 `(sessionId,key,ver,seq,val)`，语义"可能过时但永不错误"；log leads, cache follows；冷读从最低水位 anchor 增量重放。

**XEYO 现状**：`session/persistence.py` + MessageStore + copy-on-write 投影已经稳固；有 32MB 轮转（保留 2 代）、后台写线程 + flush 屏障；但没有事件级 `surfaceOp` 投影、没有请求头快照、没有崩溃尾修复与语义检查点；compact 是投影层截断（不删历史，方向正确）。

**建议**
- P0：**崩溃尾修复 + tool call/result 配对合成**。resume 时扫描尾部未闭合的 tool call，合成 `TOOL_OUTCOME_UNKNOWN` 风格结果（文本按只读/写副作用分级），补齐配对后关闭 turn。落点：`session/persistence.py` 的加载路径。
- P0：**语义检查点**。在 `engine/query_loop.py` 调 LLM 前、副作用工具执行前强制 `flush_transcript`（已有屏障，只差 fail-closed 接线）。
- P1：事件流加 `request/header`（每轮记录 provider/model/参数快照），为「请求可重建」打底；这是实现 DSH 式重试与 invariant 检查的前提。
- P2：chunk 打包行（stream token 密集的会话体积收益大）；`agentPreset` 类元数据落 header。

## 2. Compaction

**DSH 做法**
- 协议：`compaction/start`（同步落盘即锁）→ 摘要 → `compaction/summary` → **唯一** surface 变更（一条 user/message replace，锁内）→ `compaction/end`；崩溃留下可检测的孤儿锁而非假完成；失败恰好一次 `compaction/end{error}`；range 是 surface 位置区间而非 seq 区间。
- 默认 backend：`thresholdRatio:0.8`、`retainRatio:0.16`、`maxTokens:8192`、配置矛盾 load 时拒绝；先跑无模型 pruner，重测后仍高压才摘要。
- **摘要调用的 KV 技巧**：直接 `llm.stream()` 逐字节重放会话自己的 system prompt、tools 与被影子化区域的消息，把压缩指令作为最后一条 user message——命中 provider warm prefix cache，只有指令与输出 uncached。
- tool-result pruner：`thresholdChars:8192 / headChars:4096 / tailChars:1024`，不变量 head+marker+tail ≤ threshold（保证二遍零再写、替换恒缩小），`sourceEventSeqs` 溯源，码点切片保 surrogate pair。

**XEYO 现状**：C0/C1/C2 三层投影已做（方向对），C2 是确定性抽取 + 类型配额；无 LLM 摘要旁路；无 durable bracket；C0 的 tool_result 截断是 16k 硬截。

**建议**
- P0：**给 C2 加 LLM 摘要旁路，且摘要请求用"前缀重放"式**（重放 system + 现存投影消息 + 追加指令），只收纯文本。这是 XEYO 长会话语义保真的最大单点改进（盘点缺口 6）。
- P1：tool_result pruner 常数（8192/4096/1024 + 固定 marker + tail 保留错误聚尾）可直接替换 C0 的 16k 硬截——成本最低、立刻减压。
- P1：compaction 过程落成 durable bracket（start/end 事件 + 孤儿锁检测），配合 §1 的崩溃修复。

## 3. 工具输出经济（直击盘点缺口 3）

**DSH 做法**
- 三层栈：**pruner**（常数预算 head+tail）→ **retention 库**（`ItemRetainer`/`TextRetainer`，head/tail/headTail，字节预算、finish 保 UTF-8 边界；核心纪律：`truncated` 是预算事实，绝不与"上游不完整/失败"混淆；`Omitted: none|exact|unknown`）→ **spill seam**（超限完整文本落盘 `0600` 私有目录，`SpillRef{locator, bytes, retrievalHint}`，替换为"预算内预览 + `full output: <path>` 指针"，spill 失败原样返回不 isError）。
- 各工具统一默认：内存 64000B（保尾）/spill 64MiB/grace 3000ms/timeout 120s cap 600s；搜索"双预算两工件"（inline cap 与 raw cap 分离，超限存完整格式化结果仅替换 presentation）。
- 精确 footer 词汇：`(Output capped…)` / `(Showing lines X-Y of N. Use offset=…)` / `(End of file - total N lines)`；错误消息内嵌恢复动作（`— re-read the file, then retry`）。

**XEYO 现状**：工具输出 >16k 字符直接截断丢弃，长命令结果不可恢复；截断与失败未区分。

**建议**
- P0：**spill-to-file + locator**。新建 `python/tools/spill.py`（saveText → 引用对象；`wx` 独占创建、0600、会话命名空间），工具结果超阈值时改为「预览 + `full output: <path>`」。规避 read→spill→read 循环：read 工具跳过 spill。
- P0：统一 truncation 元数据（省略子句 + 恢复指引），区分"预算截断"与"工具失败"。
- P1：`TextRetainer` 等价物（Python 版 head/tail/headTail + UTF-8 边界）放 `python/common/`，bash/grep/read 共用。

## 4. Goal 机制（直击盘点缺口 1）

**DSH 做法**
- `dsh-goal`：事件溯源的单当前目标。动词 create/edit/pause/resume/complete/block/clear；`GoalRef{id,revision}` CAS 拒 stale；**block 是唯一 stopped 相**（provider 限额/预算/执行错误/求人都记 policy code+说明，不增状态）；每次 mutation 追加全量快照事件（clear 是 revisioned tombstone）。
- **激活权（armed）绝不持久化**：session-start 必 disarm；重启只恢复目标不恢复"自动继续"，续跑必须显式 resume。
- `dsh-goal-round-driver`：idle + armed + 有余量 → 先 flush（durability obligation，失败即 disarm）→ 复检 revision 与竞争输入 → 预约 `roundsStarted+1` → 排队 `<goal_round>` prompt；round 只由 goal-sourced user/message 递增（人类消息不占 cap）；混合批次有人类输入则自动 prompt 让位；取消带预约的目标先 pause（失败兜底 disarm）。
- `maxGoalRounds` 默认 256；"State, not scheduling"——状态与调度分离。

**XEYO 现状**：「继续」= resume cue + turn_snapshot 拼增强 prompt；无跨轮权威目标、无完成判定、无轮次预算。

**建议**
- P1：按双层模型落 `python/engine/goal.py`：durable 状态写进现有 sidecar/JSONL（全量快照 + revision），**激活权只在内存**（进程重启绝不自动续跑）；轮次驱动挂在 turn 结束钩子（对应 idle checkpoint），「flush→复检→预约→入队」顺序照抄。与现有 BudgetTracker 天然兼容（goal rounds 独立计数）。
- P1：`blocked` 作为统一停止相收纳预算耗尽/需人输入/连续失败，`blocked_reason` 结构化（code + 说明）。

## 5. 审批与权限（直击盘点缺口 2、8）

**DSH 做法**
- `dsh-user-approval`：`request()` → `allowed-once/rejected/cancelled/unavailable` 四值，**fail-closed**（无 answerer = 拒）；`approval/asked` + `approval/decided` 成对 log-only 审计；模型只见最终 tool outcome；政策变化追加 runtime-context 快照（不重写 system）。
- `dsh-user-questions`：`{questions:[{id,question,header,options,multiSelect,intent}]}` → `{answers:[{id,selected,custom}]}`；**intent 只改呈现不改协议**（`plan-review` 用命名标签判定批准，不靠选项顺序）；无内建超时——由 caller signal 决定。
- `dsh-permission-presets`：preset 名捆绑 knobs；`set()` 先写 log-only 事件再逐 knob（净零不写）；**session 创建时 pin，后续改动不溯及既有 session**；`custom` 只显示不可选。
- DSH 刻意**不做** allow-always/grant store；XEYO 反而需要它（缺口 8）——组合方案：approval 四值 + 独立 grant store（per-command/per-rule，含 TTL 与 workspace 维度）。

**XEYO 现状**：三态 + ASK 挂起回合 + resolve 路由已稳；但 180s TTL 一刀切（超时=deny）、确认不记忆、无 preset 概念。

**建议**
- P0：**分级超时**：交互面板（AskUserQuestion）长 TTL 或无限（等 signal）；权限确认中 TTL + 到期前提醒；危险操作短 TTL。超时语义区分 `rejected` 与 `unavailable/cancelled`（模型文案不同）。
- P0：**grant store**（缺口 8）：`permissions/store.py` 已有底子，落 per-(tool, 规则指纹) 的 always-allow，事件化（写审计流），permission_mode 之外的第二维。
- P1：permission preset（如 `readonly / workspace-write / full`）= 命名 bundle，**创建会话时 pin**，切换只影响新会话。
- P1：审批问题带 `intent`（`plan-review` / `confirm` / `choice`），GUI 按意图渲染决策卡而不是通用问答。

## 6. 循环健壮性与防空转

**DSH 做法**
- turn/step 两级边界；pre-step 原子 claim（pending 输入 + 一个 queued prompt）；`agent/request-error` 恢复 waterfall（重试 = 关失败 turn、从 durable history 重建同一请求，失败 chunk 永不进史）；取消打断流但已有非空前缀 → 补 `interrupted:true` anchor（"用户看到的必须入史"）；未派发 tool call 补 `tool/call`+`ABORTED_BEFORE_DISPATCH` 合成结果对；取消收敛后迟到唤醒被 `wakeRequested` latch 重放。
- 工具调度：exclusive 成 barrier、parallel-safe 走 bounded rolling pool（默认 10）；`isConcurrencySafe` 必须精确 `true` 才并行（fail-closed）。
- **repeat-tool-reminder**：chain key=(tool, 深排序规范化 args)；untracked 工具对链透明（防 bookkeeping 工具洗白循环）；**denied 调用也计数**；阈值 [3,5,8] 升级提醒（首短后详，args 预览截断但检测用全量串）；纯建议不 veto；提醒作为 source-attributed 注入。

**XEYO 现状**：`engine/repeat_guard.py` 已有等价物（同 submit 内同工具+等价输入 → hint/拒；零命中建议）——但语义弱于 DSH：无 untracked 透明、无升级阈值、拒绝而非建议、无 per-agent 隔离（当前单会话模型下可接受）。`_repair_unpaired_tool_calls` 已做配对修复（好）。预算系统四维比 DSH 还全。

**建议**
- P1：repeat_guard 升级为**递进建议制**：阈值 [3,5,8]，第一次短提示，后续详细（点名 tool/count/args 预览），改成经 T_now 注入的 source-attributed 块而不是改写 ToolResult 后缀；denied 调用也计数。
- P1：借鉴"重试 = 新 turn 重建历史"：LLM 请求失败重试时从投影重建请求，失败的部分 chunk 不进 MessageStore；中断流已有非空前缀时补 `interrupted` 标记。
- P2：并行工具滚动池（XEYO early-readonly 已有投机执行，DAG scheduler 已废弃；rolling pool 是更简单的替代）。

## 7. LLM 适配层

**DSH 做法**
- 流协议 chunk 归一 + 所有失败归一为 terminal `finish{kind:'error'|'aborted', failure}`（不跨流抛错）；稳定错误码集（`NO_ADAPTER/AUTH/RATE_LIMIT/CONTEXT_WINDOW_EXCEEDED/EMPTY_RESPONSE/INVALID_CREDENTIAL…`）。
- `dsh-llm-retry`：重试不包 stream——每次调用=一次尝试，重试=新编号 turn 重建请求（保 KV prefix）；`llm/retry`（调度决策）与 `llm/retry-started`（实际开始）两个非 surface 事件分离，供 UI 渲染倒计时；退避 500ms→10s + 10% jitter；`providerRetryAfterMs` 有效时替换本地退避。
- deepseek 适配器 wire 细则：usage 恒先于 finish；reasoning passback（带 reasoning 的 assistant turn 原样回传 `reasoning_content`，tool-call turn 必需）；5min stream idle watchdog（只计 provider 读，SSE 注释 rearm）；空内容 `stop` 归 `EMPTY_RESPONSE`（默认可重试）；key 格式预校验不泄漏内容。

**XEYO 现状**：`model/` 多 provider（deepseek/openai_compat/local/fake）已可用；错误处理靠异常；无事件化重试状态。

**建议**
- P1：错误码归一 + `finish{kind,failure}` 形状；`reasoning passback` 与 usage-before-finish 的 wire 细则对照现有 `ModelClient` 校验。
- P1：`llm/retry` / `llm/retry-started` 两个 SSE 信封帧（retryId/provider/mode/延迟），GUI 渲染倒计时条；策略键含全部影响行为字段。
- P2：stream idle watchdog（长思考防饿死）。

## 8. Plan mode

**DSH 做法**：`plan/mode` 是 log-only 会话事件（resume/fork/compact 天然恢复）；运行中改状态挂 pending 到下一个 pre-step 提交（`get()` 返回 `{active, pending?}`）；`exit_plan_mode` schema **恒注册**（catalog 稳定，模式切换不抖 KV cache），仅 active 可执行；批准必须经 userQuestions 的 `plan-review` intent；**sandbox/审批完全独立读写，不读 plan 状态**（强制约束不寄生在软引导上）。

**XEYO 现状**：`engine/plan.py` + `_EXIT_PLAN_MODE_SCHEMA` 动态追加 + approved_plan 走 T_now（截 4000 字符）。动态追加 schema 在模式切换时会改变 tool catalog（KV cache 视角欠佳）。

**建议**
- P1：ExitPlanMode schema 恒注册（inactive 时执行报错），保持 tool catalog 稳定。
- P1：批准交互加 plan-review intent；「已批准计划 → 允许写」的授权落在权限层（grant store / 会话内 preapproval），不把 plan 状态当权限来源。

## 9. System prompt / T_now 对照（最重要的哲学差异）

**DSH 做法**
- `system-prompt` 注册表：`PromptSection{name,order,text,complete?}`；order bands（-100 identity / 0 persona / 100-199 工具指引）；scope 同名阴影（agent 级覆盖全局）；`system-prompt/assemble` waterfall；**严格变量插值**（`Object.hasOwn` 查表防原型污染，注册但无值即 throw）；`toolOrder` + 恰一个 rest 项（fail-loud）。
- runtime context（`form:'snapshot'` 的 sourced user 消息**进 durable history**）——与 T_now 同位竞争：DSH 换 KV 前缀稳定、可审计、可重建；T_now 换"关闭后历史干净"。
- `agent-instructions`（AGENTS.md 加载）：分层（home→项目根→cwd）、`trimmedDigest`（SHA-1）去重（CLAUDE.md 复制 AGENTS.md 只渲染一次）、**touch-driven 增量**（成功的 first-party read/write/edit 触发新增/更新/移除墓碑，无 watcher）、`maxBytes` 预算内「先整份丢宽文件再截最具体文件」+ 可见 budget notice。
- `time-context`：节流注入（`refreshIntervalMs` 扫 durable log 判断，resume 正确）、时钟倒退强制刷新、mixed-zone 明确让模型向用户澄清。
- `token-meter`：4 chars/token 启发式 + provider usage anchor（复用条件苛刻）+ delta 重定价；`projectedTokens` 专治 compaction 后的滞留；**组成项显式标注为近似、计量不作 gating**。

**XEYO 现状**：T_now 管线（6000 字符预算、裁剪后强制追加开关类、contextvar 范式）已经是同类机制中相当成熟的实现；system 左段锁序 + soft budget。盘点确认 T_now 候选 15+ 块，是 XEYO 的特色资产。

**建议（不是替换，是互借）**
- P0：**T_now 预算从字符截断升级为 anchor+delta 估算**：用厂商 usage 的 input tokens 当 anchor，对 T_now 增量做启发式定价；`T_NOW_EXTRA_BUDGET` 保持字符上限作为第二道闸。
- P1：**agent-instructions 三件套移植进 XEYO.md/AGENTS.md 加载器**：trimmedDigest 去重、touch-driven 增量（嵌在现有 nested-XEYO.md T_now 块逻辑里）、预算渲染次序（先丢宽文件再截最具体 + notice）。stale 检测已经有，补「变更即 diff 通知」。
- P1：time-context 块加节流（同分钟内多轮不重复注入完整时间读数）+ 时钟倒退强制刷新。
- P1：`system_prompt.py` 借鉴 order bands + 声明式 section 注册（现在是硬编码顺序，可读性尚可，但 append/custom 的去重逻辑可声明化）；变量插值若引入 `{{var}}` 必须抄严格插值。
- 注意：**不要**把 T_now 块改成 DSH 式落史。XEYO 的"关掉后历史干净"红线（AGENTS.md）与 T_now 管线是自洽的；半持久内容（如项目指令）才考虑一次进 history。

## 10. Sub agent → 真 multi-agent

**DSH 做法**
- 委托固定权限：快照父 sandbox 覆盖、**approval 钉死 'never'**、以 `source:'delegation'` 事件写子日志（冷恢复可重建）；子提示带 delegation-scope statement（拒绝即报告、不重试）；中断权限刻意宽于投递权限（仅 exact live direct parent 可投递）。
- 双生命周期：one-shot（`SubagentRun`，publication 即所有权转移，结果用 stopReason 表达失败）vs continuable（持久 Session + 至多一个 Activation；inbox 是唯一 FIFO turn queue，不建第二状态机）；**settlement 无条件通知父**（busy→最近 step 边界 steer / idle→新 turn / teardown→inject 不唤醒）；durable descriptor（显式字段，禁止 merge-extensible）支撑冷恢复。
- fork = 父「到最后 `turn/end` 的连续前缀」快照 + `seedLength`（避免拷入未闭合 tool-call）。
- 报告通道：穿透 toolFilter 的专用 report 工具（返回通道不可被 allow-list 移除），收件人由 durable `parentSession` 推导（无 recipient 参数）；交付策略（steer/inject）是部署配置不是模型参数。
- jobs 通知经济学：busy 注入 inbox（inbox 非空 turn 不关，多 job 同 settle 只花一个 step）/ idle 唤醒新 turn；`maxConsecutiveWakes=3` 防自激励唤醒循环，仅用户输入回填预算。
- 子 agent 不能问人（`DELEGATED_CALLER`），未决问题写进最终结果。

**XEYO 现状**：Agent 工具 = 主循环普通工具（MAX_DEPTH=1、并发 8、子预算 8/8、scope 写门禁 + WriteStore 冲突检测、独立 query_loop + SUBAGENT_APPEND）——已经是"委托固定权限 + 有界子预算"的朴素版，缺：settlement 通知、continuable 常驻、durable descriptor、jobs 通道。

**建议**
- P0：**fork seed 语义**用于现有旁路/子代理：截到最后闭合 turn + 记 seedLength，防不平衡会话（立即可用于 turn_snapshot 恢复逻辑的加固）。
- P1：子 agent 完成时的 **settlement 通知**（主循环在 turn 边界注入一条 source-attributed 的「子任务 X 已结束：status+摘要」，busy 用 T_now 注入、idle 开新 turn）；比模型自己轮询干净。
- P1：若做多代理并发，先抄「inbox 是唯一队列、从静默度推导状态」——不建第二状态机；`running/idle/ready` 三态词表。
- P2：continuable 常驻子代理（durable descriptor 落 sidecar）。

## 11. Skills / MCP / 扩展层

**DSH 做法（人工精读 + extension 簇调研）**

*skill 体系*
- `dsh-skill`：来源中立 provider registry（`registerProvider` + registration-scoped `signal/invalidate`）；scope 层叠阴影（宿主/插件层 + agent preset 层，最近层同名获胜，层内 rank→注册序）；**invocation policy 四组合**（`{modelInvocable, userInvocable}` 是必填 typed 对象，模型工具目录与用户 `/命令` 目录共用一次发现但不混淆）；summary/body 分离、`get()` 每次现读正文（body 编辑零失效成本）；加载名与发现名不符→拒绝并 invalidate 该 provider；`renderSkillContent()` 是 `<skill_content>` 渲染**单一真相**。
- `dsh-skill-filesystem`：roots 硬 rank（project `.dsh/skills` → `.agents/skills` → custom → home，project root=最近 `.git` 祖先）；只扫一层、刻意排除嵌套；**frontmatter fail-closed**（坏值丢整个 skill 并 warning，绝不降级为 permissive）；失败三态：缺路径=合法空态、malformed=warn+skip、意外 I/O=snapshot incomplete **保 last-good catalog**；watch 路径 canonicalize 防 Windows 8.3 别名错配；自家 write/edit 同步 invalidate（模型下一步即见自己的修改）。
- `dsh-tool-skill`：**digest 驱动的 append-only catalog replacement**——首个非空视图追加 durable `<available_skills>` 目录（仅 name+description，description cap 500、XML-escaped），digest 变化→追加完整 replacement（清空时显式 retire 旧名），历史只追加、KV-cache 友好；错误三态（invalid name / unknown / not available for model invocation）；`/名字` 用户手势是 `disable-model-invocation` skill 的唯一入口；catalog 结尾固定"勿再调工具"防双载。

*MCP client*
- 命名 `mcp__<serverName>__<rawName>`（与 Claude Code 同形）；公开名是 `(serverName,rawName)` 纯函数，规范化截断时追加确定性 12-hex 哈希防折叠；server 内重名整个拒绝；外来注册抢占命名空间→**整代回滚，绝不部分集合**。
- 生命周期：激活 await `listTools()` 注册完才放行首 turn；`failOnStartupError:false`（默认）→初始失败仅 log、以 no tools 激活（=XEYO skip-and-log）；`list_changed`→整代替换（fetch 失败保旧代）；outage 中旧代保持注册但调用失败。
- **重连预算**：500ms 指数退避至 30s、每断线 maxAttempts=10；耗尽→unregister 并停止；**uptime 越过 maxDelayMs 重置预算**（偶发崩溃无限自愈、crash-loop 必然收敛）；`toolCallTimeoutMs:60000`；stdio env 先 scrub 再合并；图片批次整批先验证后存（全进或全不进）。

*settings / presets / workspace*
- `dsh-settings`：三层解析（schema defaults < manifest/插件 base < user 覆盖，清空=重新继承）；`expectedRevision` 乐观并发；boot 坏配置 fail-loud vs live 坏 section **keep last-good + warn**；写路径四件套：re-read 再写（不复活 stale 文档/不丢兄弟 section）+ `wx` 0600 temp + atomic rename + **self-write suppression by content**（防 watcher 自触循环）；`mutate(ops)` op 级删除（防把 wire 未返回的 secret 整段抹掉）；wire 面 `describe({redactSecrets:true})`。
- `dsh-agent-presets`：**broken-but-listed**——坏 preset 带原因出现在可见名册（id 占用显性化、可删可审计），比"跳过并记录"更进一步；id 即目录名 `[a-z0-9][a-z0-9-]*`（`../escape` 天然被拒）；composition stamp(mtime+size)；仅空白会话可 recompose（防 logged tool calls 失配）；preset 文件是输入非持久化 target。
- `dsh-workspace`：marker-first 持久化（先写 pending-mutation marker 再改数据，崩溃后只完成被标记 mutation）；`dsh-launch-environment`：env 三层快照并记录来源层，`getFrom` **省略层=拒绝而非降级**；`dsh-home-paths`：display 用符号名永不泄漏绝对路径。
- cordis 启示：**插件=生命周期对象**——`inject` 声明依赖（未就绪 pending）、一切副作用（MCP 子进程树、定时器、监听器）随 dispose 撤回、HMR 最小重载面（仅受影响插件，框架级变更才进程重启）、模型请求型动态代码"默认挂起等人批准+取消即超时+每包只留最后错误"。

**XEYO 现状**：extension 层规则已经想清楚（workspace > home > plugin、禁覆盖、坏 manifest 跳过）；**MCP 只有壳（缺口 4）**；skill 加载已有；settings 是扁平启停表。

**建议**
- P0：**实现 MCP stdio client 时直接抄全套**：命名纯函数 + 12-hex 哈希后缀、generation 整体替换/回滚、重连预算（uptime 重置语义）、`failOnStartupError:false`、env scrub、每 callTool 60s 超时 + abort；工具仍走 `outbound_ask` 权限三态。工具名与 Claude Code 同形（`mcp__server__tool`）保生态兼容。
- P1：`skill_loader.discover_skills` 升级四件套：**fail-closed frontmatter 校验**（坏值丢整个 skill，代替静默跳过）、rank 根表、body 现读（不缓存正文）、意外 I/O 保 last-good；Skill 目录注入改 **digest 驱动 append-only replacement**（首注入 + 变更时全量替换，digest 不变则该 T_now 块整体跳过），消除每轮重复注入。
- P1：skill 声明补 `modelInvocable/userInvocable` 双面 policy（`/skill` 用户菜单与模型 Skill 工具分离目录）；`disable-model-invocation` skill 仅用户手势可载。
- P1：settings 升级三层（`.xeyo/settings.json` 只存覆盖，plugin.json 带 base 默认，清空=回默认）+ `expectedRevision` CAS；写路径四件套照抄。
- P1：插件健康模型改 **broken-but-listed**：坏 manifest 插件以 `broken + 原因` 出现在 GUI 名册（保留 id 占用、可删可审计），而非只进日志。
- P1：`~/.xeyo` 路径展示统一符号名脱敏（home→`~`）；插件/MCP 定时器与子进程挂生命周期对象、停用即撤回（含子进程树清理）。

## 12. Web GUI 架构

**DSH 做法**
- **投影推拉协议**：历史尾页带 `projections` 水印块（`asOfSeq`）+ 网关广播 `session/projection` 帧（higher-seq-wins）——todos/标题/goal/tokenUsage 全走这对通用推拉；GUI 只渲染投影、动作只发命令（如 Plan 卡 = `command.execute('/plan off')`）。
- **事件→节点 Definition 注册模型**：业务插件注册"事件→稳定 `{kind,id}`"折叠器（start 建 State、按 seq 重放、分页不重算、全量重建仅限 resync）；行渲染走 keyed slot，不碰中央 switch；工具卡只吃冻结的 call/result 切片。
- **/api wire 纪律**：四象限 union + `rpcId` 回显 + 信封/业务双层校验 + 业务错误不占 HTTP status + 415 封跨站 + `expectedRevision` CAS 写 + loopback Host 栅栏。
- composer 接管：审批/提问/plan-review 共用 keyed 单席位；steering durable-order 收敛（Host 标 placement，durable 帧到达才 retire 乐观气泡）。
- 结构化 IndexInjection：`__DSH_BOOT__`/主题/语言在首帧前注入 index.html（防闪烁、配置进 DOM 的唯一显式通道）。

**XEYO 现状**：SSE 信封帧（xeyo envelope）+ zustand stores 已可用；审批/Ask/Plan 共用挂起面板（有 composer 接管雏形）；无投影推拉（前端折算 todo/usage 等存在双端漂移风险）。

**建议**
- P1：**投影推拉**：历史拉取响应带 projections 水印块 + 服务端广播帧（todos/标题/usage/goal），`useProjection` 式 store 接入——直接消除前端折算漂移，也为 goal 机制（§4）准备 UI 通道。
- P1：审批/Ask/Plan 挂起面板加 intent 字段按意图渲染（决策卡 vs 问答）。
- P2：工具卡 render intent 词汇（generic/terminal/diff/search/read/web）+ 冻结切片纪律；IndexInjection 式启动配置注入。

## 13. 沙箱（Windows 重点）与工具执行管线

**DSH 做法**
- **Windows ACL restricted-token 沙箱**（对 XEYO 最相关）：`CreateRestrictedToken` WRITE_RESTRICTED token；restricting SIDs = keep-alive（logon SID+Everyone）+ 写 SID；**workspace 写 SID 由 canonical 路径确定性派生 → standing ACE 每机器只物化一次**（精确命中即 skip 重传播，避开全树分钟级开销）；每会话一个**随机私有 temp 目录 + revocable tempWriteSid**；crash 残留因 SID 换代惰性失效；全 Win32 fail-closed；已验证边界（Everyone 必留、hard link 别名、NUL、named-pipe EPERM、FAT 卷）写成契约并如实报 `enforcement:'partial'`；**pwsh 联动**：read-only 下 AppLocker 探测写不进 temp → ConstrainedLanguage；workspace-write 私有 temp 可写 → FullLanguage。
- `confine(argv, policy)` 契约：不可 confine 即抛、绝不裸跑；policy 随调用走（bash 可 read-only、子代理同时 workspace-write）；**one-shot escalation**：`sandbox_permissions`+`justification` 成对校验，denial marker + 同轮 escalation hint 单点拥有；denial 是结果事实（结构化 `sandbox.denied/mode/enforcement`），与 runner 失败、命令失败三分。
- 工具管线：pre-execute 三态（无参数改写）→ 单调 guard → around（只换 signal）→ post-execute（换 content/value 之一 + additionalContexts）→ finalizeContent；`timeoutMs` 只是声明、执行归 timeout-policy（deadline 融合信号 + timeoutOf 区分 timeout/cancel）。
- shell 纪律：run() 只有基础设施失败才 reject（非零退出/超时/abort 都 resolve 成结果交模型解读）；`[exit code: N]` 标记契约单点拥有；pwsh UTF-8 preamble 须在 param 前、Windows 强杀=exit 1 无 signal 写进 prompt 教模型。

**XEYO 现状**：`permissions/filesystem.py` + `bash_policy.py` 是策略层（路径判定 + allowlist），无 OS 级沙箱；`session_presence.py` peer 冲突 ASK 已有；schema 精简、meta 单表登记是好底子。

**建议**
- P1：**Windows ACL 沙箱蓝本立项**（pywin32/ctypes 复刻）：桌面场景免管理员、非容器的写限制是 XEYO 独有可行方向；即便只做「工作区内可写 + 会话私有 temp」两档，价值已经很大；partial 边界如实上报。
- P1：escalation 三件套（schema 字段成对校验 + denial marker 单点 + "retry this exact command once" 提示）映射到 `outbound_ask`→`always_allow` 流程。
- P2：confine-argv 契约 + denial signatures（把沙箱拒绝从命令失败里分类）；工具管线分层（当前 ToolRegistry.run 一站式，够用，重构收益中等）。

## 14. 其他小而美（速查表）

| DSH 机制 | 一句话 | XEYO 落点 | 优先级 |
|---|---|---|---|
| `dsh-headless` | 一次性 bundle：task 作 user 消息、等静默、flush、退出码绑 turn 终态 | `xeyo run "task"` CI 入口（python/cli 已有雏形可对齐退出码语义） | P1 |
| `dsh-schedule` | 持久提醒：日志拥有状态（版本化 change 事件）、timer 只是可弃投影；flush-before-decide；prompt 明示不可信 | 若做定时/待办特性 | P2 |
| `dsh-atomic-write` | `wx` 建 temp 防 symlink 劫持、同目录 rename、锁文件竞争者绝不删既有锁、atomic ≠ durable | `permissions/store.py`、`.xeyo/settings.json`、working.json 写盘纪律 | P1 |
| `dsh-storage-domain` | 内存权威 + per-domain 串行写链（先落盘后改内存再广播） | todo/tasks/settings 等会话外状态 | P2 |
| `dsh-session-title` 三态 | 确定性 fallback 即时 + LLM 异步增强 + 用户 rename 即 pin | **LLM 标题生成**（缺口 5）：旁路请求先记档再派发、`purpose:'session-title'` 关 thinking、输出空/非 stop 拒绝 | P0 |
| `dsh-attachment` | sha256 内容寻址、事件只存 ref 不存 base64、准入限制 + 归一化、批量先全部 prepare 再按序 commit | 图片/文件附件进会话时 | P2 |
| `dsh-file-reference` | `@file` 只在 token 起始激活、选中不读内容、有界索引、工具结果事件即失效 | GUI @ 引用 | P2 |
| `dsh-shell-env` | 子进程身份通道：先剔除继承的 `XEYO_*` 再合并受管值（env 不能顶掉 managed） | bash/pwsh 工具 env 组装 | P1 |
| `dsh-invariants` | 可选伴随模块对日志做独立 fold 校验（goal/审批/流配对） | debug 工具或测试期断言 | P2 |
| `dsh-typert` | descriptor 驱动的 typed RPC | FastAPI↔GUI 类型化的远期方向 | P2 |
| projection-cache 水印 | GUI 重连从最低水位增量重放而非全量 | 会话历史分页/重连 | P2 |

## 15. 不建议照搬的部分

1. **cordis 内核**（scope/fiber/service 生命周期）：DSH 整个架构建立在 cordis 依赖注入 + fiber 生命周期上，收益来自 150 个包的规模；XEYO 单体 Python 重写它得不偿失。只借"注册可见性=生命周期"的思想（per-session 注册随会话销毁）。
2. **runtime-context 落史**：DSH 把易变上下文作为 sourced user 消息写进 durable history——与 XEYO T_now 红线冲突（关闭后历史不干净、compact 误读）。维持 T_now，只互借细节（节流、预算定价、强追溯）。
3. **TypeScript 单包单 README 的文档纪律**虽好，但 XEYO 是 Python 单仓，等效做法是每个子系统模块 docstring + `docs/` 主题文档（本报告可作起点）。
4. **重试不包 stream 的完整事件溯源版**依赖 request/header 重建；XEYO 可先做简化版（同投影重建请求），事件化后补全。

## 16. 建议落地顺序（两周视角）

| 周 | 主题 | 条目 |
|---|---|---|
| W1 | 止血类（P0） | spill+locator（§3）、工具输出截断元数据统一（§3）、LLM 标题三态（§14）、审批分级超时（§5）、崩溃尾修复（§1） |
| W1 | 顺手 | tool-result pruner 常数替换 C0 硬截（§2）、repeat_guard 递进建议制（§6） |
| W2 | 结构类（P1） | grant store（§5）、compaction durable bracket + LLM 摘要前缀重放（§2）、goal 双层状态机（§4）、ExitPlanMode 恒注册（§8）、MCP client 按 DSH 语义实现（§11）、skill_loader 四件套 + digest 目录注入（§11） |
| W2+ | 演进类（P1/P2） | 投影推拉（§12）、LLM 错误码归一 + retry 事件（§7）、agent-instructions 三件套（§9）、Windows ACL 沙箱立项（§13）、headless 退出码（§14） |

---

### 附：资料索引

DSH 包 README 一律在 `E:\nodejs\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\<包名>\README.md`（中文版 README.zh.md 同目录）。本报告高频引用：

- 循环与控制：`dsh-agent` `dsh-agent-loop` `dsh-plan-mode` `dsh-goal` `dsh-goal-round-driver` `dsh-user-approval` `dsh-user-questions` `dsh-permission-presets`
- 会话与压缩：`dsh-session` `dsh-session-persistence(-jsonl)` `dsh-session-checkpoint-policy` `dsh-session-projection(-cache)` `dsh-compaction(-basic/-tool-result-pruner)` `dsh-output-retention` `dsh-spill(-local/-policy)`
- 提示与上下文：`dsh-system-prompt` `dsh-agent-instructions` `dsh-time-context` `dsh-token-meter` `dsh-repeat-tool-reminder`
- 工具与沙箱：`dsh-tools` `dsh-tool-fs` `dsh-tool-fs-search` `dsh-fs` `dsh-fs-observation-policy` `dsh-fs-sandbox` `dsh-sandbox(-policy/-local/-windows-acl)` `dsh-shell(-env)` `dsh-bash-local/-sandbox` `dsh-pwsh-local/-sandbox` `dsh-subprocess` `dsh-tool-call-timeout-policy` `dsh-terminal(-bash)` `dsh-tool-bash-persistent` `dsh-tool-pwsh-persistent`
- 多代理与任务：`dsh-subagent(-in-process-driver/-fork-in-process/-spawn-in-process)` `dsh-tool-subagent(-control/-report)` `dsh-jobs(-local)` `dsh-tool-jobs` `dsh-workflow(-worker-thread)` `dsh-tool-ralph` `dsh-schedule` `dsh-headless`
- 扩展与模型：`dsh-skill(-filesystem)` `dsh-tool-skill` `dsh-mcp-client` `dsh-settings(-file)` `dsh-agent-presets` `dsh-workspace` `dsh-launch-environment` `dsh-home-paths` `dsh-llm(-retry/-deepseek)` `dsh-credentials` `dsh-atomic-write` `dsh-storage(-domain/-json)`
- GUI：`dsh-host-webserver` `dsh-host-frontend-static` `dsh-host-apiproxy` `dsh-client-runtime` `dsh-client-modules` `dsh-client-connection` `dsh-client-hmr` `dsh-client-ui-conversation` `dsh-client-ui-tool` `dsh-client-ui-plan` `dsh-client-ui-workspace`
