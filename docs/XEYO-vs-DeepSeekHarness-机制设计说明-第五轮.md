# XEYO × DeepSeek Harness 实现机制设计说明（第五轮）

> 产物：机制设计说明（Mechanism Design Spec）。不是功能清单，不是字段枚举，而是**逐个机制讲清"为什么这样设计 / 不变量是什么 / 算法怎么走 / 失败怎么办"**。
> 证据口径：每条结论带 `文件:行号`，全部由主代理直读源码得出（`Read` 精读 + Python 切片；本机 `awk` 有兼容问题，已弃用）。
> 前置四轮：功能面 `XEYO-vs-DeepSeekHarness-全量对比.md`（605 行）、设计面 `…设计级对比-第二轮.md`（1307 行）、实现面 `…实现级对比-第三轮.md`（2246 行）、逐字段面 `…逐字段级对比-第四轮.md`（1505 行）。**本轮不重复它们**。

---

## §0 本轮的定位：从"有什么"转向"怎么运转"

第四轮回答了"每个类型有哪些字段"。本轮回答的是再往下一层的问题：

| 第四轮问的 | 第五轮问的 |
|---|---|
| `SessionEvent` 有几个字段 | 一条事件从 `append()` 到进入模型上下文，经过哪几次验证、哪几次转换？ |
| 沙箱有哪些模式 | `confine(argv, policy)` 怎么把政策变成 argv？后端查不到时为什么不能"裸跑"？ |
| T_now 有 20 个块 | 20 个块怎么塞进一次请求而不破坏 KV 前缀缓存？塞不进去时砍谁？ |
| 有 `rewind` | 一次 rewind 从 preview 到 execute 到崩溃恢复，状态机怎么走？ |

**机制 ≠ 功能**。同一条功能在两端可以是完全不同的机制（例如"产物落盘"：dsh 是**写后缓冲 + 单写者 + 撕裂尾修复**，XEYO 是**追加 + fsync 开关 + 部分行容忍**）。本轮专门抓这种机制级差异。

**一个重要的取值修正**：本轮首次系统阅读 `D:\lea\XenYon code\python\rewind\` —— **12 个文件、5343 行**（`service.py` 1800 / `hotpath.py` 1024 / `index.py` 684 / `blob_gc.py` 531 / `journal.py` 321 / `models.py` 233 / `revision.py` 212 / `locks.py` 166 / `snapshot.py` 115 / `checkpoint.py` 115 / `context.py` 111 / `__init__.py` 31）。前四轮把它压缩成"rewind v2/v3"一句话，**低估了它的规模**——它比 dsh 的整个 `session-persistence-jsonl` 包还大，且自带 GC、租约、崩溃标记、后台恢复线程。

---

## §1 机制总目录

| # | 机制 | 侧 | 关键实现 | 一句话设计意图 |
|---|---|---|---|---|
| A-1 | 事件溯源日志 | dsh | `core/session/src/{index,surface,types}.ts` | 日志是唯一真值，模型上下文是它的**投影**（`surfaceOp` 决定投影形状） |
| A-2 | 崩溃恢复（日志闭合） | dsh | `core/session/src/repair.ts` | 崩溃尾不算数据损坏；**合成闭合事件**使其可继续 |
| A-3 | 请求纪元快照 | dsh | `core/session/src/request-header.ts`、`agent.ts:488-563` | 每次请求的 system+tools+config 逐字节记档，事后可**逐字重建** |
| A-4 | System prompt 组装 | dsh | `core/system-prompt/src/index.ts` | 有序插槽 + 作用域遮蔽 + `complete` 还原 + 专家瀑布 |
| A-5 | 运行上下文快照 | dsh | `core/agent-loop/src/runtime-context.ts` | 易变事实做成**可替换的 user 消息**（差异才发、被替换即撤销） |
| A-6 | 工具执行瀑布 | dsh | `core/tools/src/index.ts:144-199,1454-1637` | 5 个可拦截事件；调度器三段返回值决定"后置阶段还能不能改写" |
| A-7 | 工具并发调度 | dsh | `core/agent-loop/src/tool-calls.ts` | 独占=屏障，并发=滚动池；**派发可重叠，提交必按模型序** |
| A-8 | 沙箱 confine | dsh | `sandbox/sandbox/src/{index,escalation}.ts` | 单函数把政策编译成 argv；无后端**拒绝运行**（fail-closed） |
| A-9 | 压缩事务 | dsh | `compaction/compaction-basic/src/region.ts`、`compaction/src/tool-pairing.ts` | 括号事务 + 工具配对平衡 + 影子计价；压缩是 **surface replace** 不是删日志 |
| A-10 | 会话持久化（JSONL） | dsh | `session/session-persistence-jsonl/src/storage.ts` | 写后缓冲 200ms + 单写者链 + 撕裂尾修复 + 跨进程租约 |
| A-11 | 会话 fork / 继承 | dsh | `core/session/src/index.ts:451-620,887-1010` | 用 `inheritedEventCount` 一刀切开"继承的"与"我自己的" |
| B-1 | T_now 注入管线 | XEYO | `prompt/pre_llm_inject.py` | 三类块 + 预算 + 裁剪 + **登记表机器执法** |
| B-2 | env_channel 声道 | XEYO | `prompt/turn_context.py:115-160`、`prompt/t_now_strategy.py` | 伪造一对**只存在于投影**的 tool 对，把注入与用户意图结构隔离 |
| B-3 | 权限判定链 | XEYO | `permissions/policy.py:1319-1700` | 先硬拦（不可被授权穿越）再分派（按工具类别） |
| B-4 | Bash 策略 | XEYO | `permissions/bash_policy.py` | 只读白名单**正向**放行；复合命令**否定式**拒绝 |
| B-5 | 授权指纹 | XEYO | `permissions/store.py:415-490` | 身份与参数分离：指纹只哈希身份，参数永不参与 |
| B-6 | 审批挂起 | XEYO | `permissions/store.py`、`engine/permission_coordinator.py` | 风险分级 TTL + 幂等 resolve + 状态机回写 |
| B-7 | rewind v2（内容寻址） | XEYO | `rewind/{snapshot,journal,index,revision}.py` | 日志只存哈希与引用，文件体走 **SHA-256 内容寻址库** |
| B-8 | rewind v3（热路径） | XEYO | `rewind/hotpath.py` | 事件日志 + orphan 先落盘 + 崩溃标记 + 后台恢复线程 |
| B-9 | rewind 存储回收 | XEYO | `rewind/blob_gc.py` | 可达性计算 + 预算驱动 + **dry-run 永不触盘** |
| B-10 | 影子 git 与工作区指纹 | XEYO | `engine/{shadow_git,workspace_revision}.py` | 独立 `GIT_DIR` 版本化 + **只读元数据指纹**（不读内容） |
| B-11 | 写入通道 | XEYO | `engine/write_store.py` | 内容哈希 + 分片锁 + 原子替换 + 未读拒绝 |
| B-12 | 预算与收尾窗口 | XEYO | `engine/budget.py` | 多软上限**共享一个** grace 窗口；防"单轮爆发烧光余轮" |
| B-13 | 成本账本 | XEYO | `usage/{ledger,pricing,attribution}.py` | 按**真实厂商**计价 + 四桶分离 + 请求级归因 |

---

# Part A — dsh 实现机制设计说明

## A-1 事件溯源日志机制：日志是唯一真值，上下文是它的投影

### 设计意图

dsh 把"发生了什么"与"模型看到什么"**彻底分离**：

- **日志**（`Session.log: SessionEvent[]`）只追加，永不变更，是唯一真值；
- **表面**（`surface`）是日志的一个**有序子序列视图**，只包含"能产生 LLM 消息"的事件；
- **模型历史**（`deriveMessages()`）是表面按节点投影的结果。

分离的关键是一个字段：**`surfaceOp`**。每个"消息产出型"事件必须显式声明它如何加入表面（`append`）或替换表面的一段（`{op:'replace', start, end}`）。于是"压缩"这种本来会破坏只追加语义的操作，变成了**再追加一条替换事件**——日志仍是只追加的，表面却被改写了。

### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | `seq === log.length`（从 0 连续） | `index.ts:723`；seed 校验 `:567` |
| I2 | 只有三类事件可进表面：`user/message`、`assistant/message`、`tool/result` | `surface.ts:22-26` |
| I3 | 表面型事件**必须**带 `surfaceOp`；非表面型事件**不得**带 | `surface.ts:195-218` |
| I4 | `sourceEventSeqs` 必须全部指向**更早**的 seq，无重复，且**必须覆盖全部被遮蔽节点** | `surface.ts:221-256` |
| I5 | `tool/result` 的替换只能改 `content`，其余字段必须逐字节相等 | `surface.ts:299-331` |
| I6 | 事件 `data` 必须可**无损 JSON 化**（拒绝 BigInt/函数/Map/Set/Date/负零/非有限数/稀疏数组） | `index.ts:709-716` |
| I7 | append 不可重入（发布期间再 append 抛错） | `index.ts:717-720` |

### 算法：一次 append 的完整路径

```
append(type, data, opts)                                  index.ts:699
 ├─ snapshotJsonValue(data)  → 不可序列化即抛            :709-712
 ├─ snapshotJsonValue(surfaceMetadata) → 同上             :713-716
 ├─ 重入检查（entry.appending）                            :717-720
 ├─ deepFreeze({type, seq=log.length, time=Date.now(), data, ...meta})  :721-727
 ├─ surfaceManager.validateNext(event)  ← 只"计划"，不改状态  :728
 │    └─ planSurfaceEvent：seq 连续性 → surfaceOp 合法性 → 来源校验 → 范围定位 → tool_result 改写校验
 ├─ entry.appending = true                                 :730
 ├─ log.push(event)；eventsSnapshot 失效                    :737-738
 ├─ 同步派发 session/event（逐监听器 try/catch 隔离）        :739-741
 └─ finally: appending=false；若期间请求过 detach 则此时执行  :743-747
```

注意 **validateNext 是"两段提交"**（`surface.ts:440-448`）：候选事件先被**计划**（`planSurfaceEvent`）但不改状态，只有当它真的进入 `log` 后，`_processDelta` 才在遍历到它时**执行**该计划（`surface.ts:463-478`）。这保证"验证失败的事件不会留下半更新的表面状态"。

### 算法：模型历史的投影

```
deriveMessages()                                          index.ts:820
 ├─ surface.nodes（当前表面 seq 序列）
 ├─ 若 replaceGeneration 变了 → 清空缓存从头重建             :824-828
 ├─ 对新增节点逐个 deriveEventMessage(event)：
 │    user/message      → event.data（原文透传）
 │    assistant/message → event.data.message，但 content 为空时返回 null :110
 │    tool/result       → event.data.message
 │    其他              → null（边界/尝试/错误都只是复现数据）:116-120
 └─ 返回 [...this.derived]（新数组，元素是共享的深冻结 Message）:840
```

**关键设计注释**（`surface.ts:94-102`）：投影层故意**不做任何加框**（不给你加 `<context>` 之类），框由**生产者**自己烤进 `content`。理由写在 deferred design note 里——投影层一旦开始加框，它就不再是"逐字节复现"，重建能力就没了。

### 失败路径

- 验证失败 → 抛在 **append 点**，而不是落盘时（`index.ts:693-697` 注释：日志是耐久真值，坏事件必须在入日志前失败）。
- 监听器失败 → 逐监听器包含（contained），**不改变返回值、不阻断后续监听器**（`index.ts:669-668`, `invokeContainedSessionObservers`）。

### 对照提示

XEYO 的对应物是 `~/.xeyo/sessions/<id>.jsonl`（transcript 直出）。XEYO **没有表面层**：写进 JSONL 的就是模型历史，压缩/裁剪是**在内存里对消息数组做投影**（`engine/compact.py::project`），不写回日志。这带来一个结构性后果：**XEYO 无法从日志逐字重建"模型当时看到什么"**——因为投影是即时的、不落盘的。

---

## A-2 崩溃恢复机制：把中断的尾巴补成合法 transcript

### 设计意图

进程被杀会留下"半个 turn"：模型已经请求了工具，但工具结果没落盘。如果直接把这个日志喂回 provider，会被拒绝（悬空 tool call）。dsh 的选择是**不删、不改**，而是**合成闭合事件**追加在后面。

注释写得很直白（`repair.ts:1-5`）：*"preserves a fully written final turn and supplies the missing tool, step, and turn boundaries needed to resume with a provider-valid transcript."*

### 算法：`interruptedTurnClosers(events)`

```
单趟扫描日志，维护三个游标：openTurn / openStep / pendingCalls: Map<callId, {step, callSeq?}>
 ├─ turn/start  → openTurn=…，openStep=null，清空 pendingCalls   repair.ts:37-41
 ├─ turn/end    → 全部清空                                        :42-46
 ├─ step/start  → openStep=…                                      :47-49
 ├─ step/end    → 清空 pendingCalls，openStep=null                :50-53
 ├─ assistant/message → 把每个 tool-call 块记入 pendingCalls      :54-59
 ├─ tool/call   → 给对应 pendingCalls 条目补 callSeq              :61-69
 └─ tool/result → pendingCalls.delete(callId)                     :70-72

若 openTurn === null → 返回 []（日志本来就是平衡的）              :82
否则从 last.seq+1 开始合成，时间戳复用 last.time（不发明"未来时间"）:87-88
 1) 先给每个未匹配的 call 合成 tool/result（Map 插入序=transcript 序）:93-126
      started？→ 文案"已记录但结果未落盘，结果未知"（劝模型按语义决定是否重试）
      未 started？→ 文案"在记录为已开始之前就中断了，需要的话重试"
 2) 再补 step/end（若 step 仍开）                                  :130-132
 3) 最后补 turn/end，reason={kind:'interrupted'}                    :133
```

### 设计细节（三个值得记的）

1. **两个恢复码区分"未知"与"未开始"**（`repair.ts:15-18`）：`TOOL_NOT_STARTED` 与 `TOOL_OUTCOME_UNKNOWN`。这对模型的行动语义完全不同——前者可放心重试，后者可能已有副作用。
2. **合成结果必须引用 `tool/call` 的 seq**（`sourceEventSeqs: [callSeq]`，`:124`）——这样表面不变量 I4 仍然成立，合成事件也是"合法的溯源事件"。
3. **闭合顺序不可换**（注释 `:128-129`）：step 开着时直接写 turn/end 是不变量违规，所以必须先 step/end 再 turn/end。

### 挂载点

`AgentLoop.resumeWith` 在读盘后立刻调：`const closers = interruptedTurnClosers(persisted); if (closers.length>0) await handle.append(closers)`（`agent-loop/src/index.ts:876-879`）。注释写明职责边界：**持久化层只保证物理有效，语义修复是 agent 层的活**。

### 对照提示

XEYO 的对应物是 `engine/turn_snapshot.py`（`.turn.json` 快照，含 `status/incomplete_tool_uses/active_agent_ids/waiting_permission`）——**它是状态记录，不是日志修复**。XEYO 恢复的是"我该不该继续"，dsh 修复的是"日志能不能被 provider 接受"。两者不在同一层。另外 XEYO 有 `_repair_unpaired_tool_calls`（在 submit 入口执行一次），思路接近但**不是从持久日志反推**，而是在组装请求时修。

---

## A-3 请求纪元快照机制：让"模型当时看到什么"可逐字重建

### 设计意图

`deriveMessages()` 能重建**消息**，但重建不出**system prompt 与 tools**。而压缩、缓存、问题复现全都要这两样。dsh 的解法是把每次请求的 system + tools + config 做成一条日志事件：`request/header`。

注释（`request-header.ts:1-6`）：*"Anyone holding a session log reconstructs the EpochHeader any request was built under by taking the latest canonical snapshot."*

### 数据结构与规范化

`canonicalHeader()`（`request-header.ts:21-31`）做一件事：**空的东西变成"不存在"**——空 system、空 tools 一律删除字段，`adapterDefaults` 只有在真的标记了覆盖时才保留。理由：记录、折叠、比较必须用**同一个表示**，否则"字段存在但为空"和"字段不存在"会被判为不同，产生假的 header 变更。

`headerEquals()`（`:44-54`）逐字段比：config（用 `callConfigEquals`）、`adapterDefaults` 两个标记、`system` 字符串、tools 数组**按位逐 JSON 比较**（`sameSchema`，`:34-36`）。

### 算法：什么时候写 header 事件

`buildRequest` 里的判定链（`agent.ts:548-563`）：

```
startsSeries = startsRequestSeries || (上次请求的 surfaceGeneration !== 当前)
if (!requestHeaderLogged)                      → append(reason = baseline===undefined ? 'initial' : 'resume')
else if (baseline===undefined || !headerEquals(baseline, header)) → append(reason='change', 可能带 startsSeries:true)
else if (startsSeries)                         → append(reason='series')
else                                           → 不写
```

三种 reason 各有含义：`initial/resume` 是纪元起点；`change` 是内容真的变了（**KV 缓存前缀在这里断**）；`series` 是内容没变但表面被改过（例如压缩 replace 之后需要重新确认请求序列起点）。

同步还有 `request/context`（`:565-576`）：provider/model/contextWindow 变了才写——这是给 token 计量用的路由元数据。

### 折叠与读取

`foldRequestHeader(events, from?)`（`request-header.ts:65-71`）是一个**纯离线折叠**：扫一遍日志，取最后一个 `request/header`。同时 `Session` 侧有**增量版**（`index.ts:764-774`），用 `headerFoldSeq` 记录已折叠到哪，每步只处理新事件，代价 O(新增)。

### 设计取舍（注释原文值得引）

- header 折叠结果 **deepFreeze**，注释（`index.ts:766-769`）：*"a consumer mutating it in place (instead of building a replacement) would desync every later comparison against the log, so mutation throws instead."* —— 防的不是恶意，是**别名共享导致的静默失同步**。
- `requestProposal()`（`agent.ts:61-67`）：把 adapter 推导出来的 `reasoningEffort`/`maxTokens` 从"下一轮提案"里删掉，只留用户/插件真正声明的，否则推导值会被当成"用户要求"固化下来。

### 对照提示

XEYO **完全没有对应物**。XEYO 的 system prompt 由 `python/prompt/system_prompt.py` 每轮拼装，**拼完即用、不落档**；T_now 块只在内存投影层存在。这意味着 XEYO 事后无法回答"第 37 轮那次请求，system prompt 到底长什么样"。这是 dsh 相对 XEYO **最硬的一处结构性领先**，也是第二轮/第三轮反复指出的"缺一层"的具体形态。

---

## A-4 System Prompt 组装机制：有序插槽 + 作用域遮蔽 + complete 还原

### 设计意图

system prompt 不是字符串模板，而是一个**注册表**：各插件往注册表里放"片段"，组装时按 `order` 排序拼接。目的有二：①插件可以增删自己的片段而不动别人的；②排序是**确定性**的（`order` 相同则按名字 code-unit 比较），跨机器结果一致。

### 三个注册面 + 一个保留语义

| 面 | 注册 API | 排序 | 注入位置 |
|---|---|---|---|
| sections | `systemPrompt.section()` | `order` 升序 → 名字 | system prompt 正文，`\n\n` 连接 |
| contexts | `systemPrompt.context()` | `order` 升序 | **作为 user 消息**（运行上下文快照，见 A-5） |
| tools | `systemPrompt.tools()` | canonical 排序（或 `toolOrder`） | 请求的 tools 数组 |
| variables | `systemPrompt.variable()` | — | `{{name}}` 插值（严格：未注册/无值即抛） |

**顺序是集中分配的**（`index.ts:121-152` 的 `SECTION_ORDERS`）：`HARNESS_IDENTITY(-1000)` → `HARNESS_SOURCE(-900)` → … → 每个工具自己的说明（`TOOL_BASH=1000`、`TOOL_READ=1100` …）→ `TOOLS_SDK(5000)` → `STRUCTURED_OUTPUT(9900)`。`CONTEXT_ORDERS`（`:157-161`）只有三个：`SANDBOX_POLICY=110`、`APPROVAL_POLICY=115`、`SUBAGENT_DELEGATION=120`。

**注意 115 与 110 的相邻**：审批策略紧挨沙箱策略——因为在模型看来它们是同一类事实（"我这个执行环境被限制到什么程度"）。

### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | 同一层内片段名不得重复（重名抛错，且错误文案区分"全局重名"与"作用域内重名"） | `index.ts:366-376` |
| I2 | `order` 必须有限数 | `:433-435`, `:468-470` |
| I3 | 至多一个 `complete` 片段；多于一个组装失败 | `:574-577` |
| I4 | `toolOrder` 必须**恰好一次**含 `TOOL_ORDER_REST` 标记 | `:187-198` |
| I5 | `toolOrder` 中的未知名字在组装期失败 | `:211-214` |
| I6 | 变量名必须匹配 `^[a-z][a-z0-9_]*$`；引用未注册变量抛错；`{{}}` 走 malformed 路径 | `:309-346` |
| I7 | 变量解析**不做二次扫描**（插值结果里的 `{{...}}` 不会被再解释） | `:343` 注释 |

### 作用域遮蔽（ScopedLayers）

`assemble()`（`:536-611`）的合并顺序：

```
变量：先全局，再按作用域链"从远到近"覆盖 → 最近的赢                :542-551
片段/上下文：merge(scope, layer=>layer.sections) —— 同名的 scoped 遮蔽 global  :553-554
工具：全局 provider + 作用域链上所有 provider **都参与**（工具是累加不是遮蔽）    :556-559
```

工具与片段的合并语义**故意不同**：片段是"同一块内容的替换关系"，工具是"能力集合的累加关系"。

### 协作瀑布与 complete 还原

组装完成后跑 `system-prompt/assemble` 瀑布（`:601-604`），监听器可以整体改写 assembly。但**如果注册了 complete 片段**，瀑布跑完之后会把 sections **还原成那一个片段**（`:605-610`）。注释（`:69-71`）：之所以还要跑瀑布，是因为 tools/contexts/variables 仍需要被解析。

### 渲染期的严格性

`renderPrompt`（`:263-268`）：逐片段插值 → **丢弃空片段** → `\n\n` 连接。`interpolate`（`:309-346`）对畸形引用（`{{` 后面还有 `}}` 但没有合法名字）**抛错**；但孤立的 `{{` 没有后续 `}}` 时当**普通文本**（`:319-326`）。注释解释了原因：误报比漏报更伤——散文里出现 `{{` 是合法的。

### 对照提示

XEYO 的 system prompt 是 `python/prompt/system_prompt.py` 单文件拼装，**没有插槽注册机制**，因此第三方无法增删片段；易变内容一律走 T_now 注入管线（这反而是 XEYO 设计上更克制的地方——它把"能改 system prompt"的口子彻底关掉了）。

两端的取舍正好相反：dsh 要**可替换性**（所以开注册面），XEYO 要**前缀稳定性**（所以关注册面）。这就是第二轮说的"镜像"关系在 prompt 层的具体体现。

---

## A-5 运行上下文快照机制：让"易变事实"既进上下文又不破坏缓存

### 设计意图

有一类事实每轮都可能变：沙箱策略、审批策略、委派策略。它们必须让模型知道，但**不能进 system prompt**——因为 system prompt 在最前面，改一个字就毁掉整个 KV 前缀缓存。

dsh 的解法（`runtime-context.ts`）很巧：把这类事实做成**一条可被替换的 user 消息**。

- 它是 user 角色 → 位置在历史**尾部附近**，改动不影响前面的前缀；
- 它可以被**替换** → 用 surface 的 `replace` 操作换掉旧版本，而不是无限追加；
- 它**只在内容真的变了**才发 → 相同内容重复组装不产生新事件。

### 数据结构

```ts
class RuntimeContextProjection {
  private retained: { seq; text } | null | undefined
  //  undefined = 从未有过快照；null = 有过但当前没有保留
}
```

三种状态是刻意的：`undefined` vs `null` 区分了"首次组装"与"快照已被压缩替换掉"，`project()` 的首行判断依赖这个区分（`:65`）。

### 算法

**构造期（从日志恢复）**（`:34-44`）：从日志末尾往前扫，找**最后一个属于本插件**（`source.kind==='plugin' && plugin==='@deepseek-ai/dsh-system-prompt'`）且**仍在当前表面上**的 `user/message`，认作当前保留值。注意"仍在表面上"这个条件——被压缩替换掉的旧快照不算数。

**运行期（跟随事件）**（`:46-55`）：
```
session/event:
  ├─ user/message 且是本插件产的 → retained = {seq, text}
  └─ 是替换型表面事件 且 sourceEventSeqs 包含 retained.seq → retained = null
```

**投影决策**（`:64-75`）：
```
if (retained === undefined && current === '')      → 不发（从未有过、现在也没有）
snapshot = current==='' ? CLEARED : current         ← 清空也必须发一条"清空声明"
if (retained?.text === snapshot)                   → 不发（内容没变）
否则 → 生成 user 消息，source 带 sections 归因
```

### 三个设计细节

1. **清空也要发消息**（`:13`）：`CLEARED = 'Current runtime context: none. Earlier runtime-context snapshots no longer apply.'` —— 否则模型会继续按上一轮的策略行动。这是"信息正确性"问题，不是"节省 token"问题。
2. **归因随消息走**（`:70-73`）：`source.sections` 保留"这段快照由哪几块拼成"，供 UI 归因展示——但注释强调**不能重新切分 joined 文本**（`system-prompt/index.ts:296-301`），所以 sections 是原样带下来的，不是事后解析的。
3. **快照文本带头**（`system-prompt/index.ts:290`）：`'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.'` —— 显式声明"我取代之前的"，避免模型把新旧两份当叠加。

### 对照提示

**这是 XEYO 与 dsh 最接近、又最不同的一处。**

| | dsh | XEYO |
|---|---|---|
| 机制名 | 运行上下文快照 | T_now 注入 |
| 载体 | **一条可替换的 user 消息** | **一对伪造的 tool_use/tool_result**（env_channel）或尾插 user（legacy） |
| 变更方式 | surface `replace`（旧版本真的从历史消失） | 每轮重新投影（旧版本本来就不在持久历史里） |
| 是否落日志 | **是**（是正常 session 事件） | **否**（投影-only，绝不进 MessageStore/JSONL） |
| 相同点 | 都在尾部、都"变了才发"、都避免动 system prompt | 同 |

一句话：**dsh 的上下文是"日志里的一条可替换记录"，XEYO 的上下文是"从不落地的投影"。** 前者可复现，后者更纯净但不可复现。

---

## A-6 工具执行瀑布机制：5 个可拦截点 + 三段返回值

### 设计意图

dsh 的 tool call 执行不是"调用函数"，而是一条**可被第三方逐段拦截的瀑布**。每个阶段都是独立的 waterfall 事件，插件可以改写决策或结果。

### 5 个拦截点（事件声明见 `core/tools/src/index.ts:144-199`）

| 事件 | 模式 | 时机 | 能做什么 |
|---|---|---|---|
| `tools/pre-execute` | waterfall | 参数物化之后、派发之前 | 返回 `allow / ask / deny` 决策 |
| `tools/execute` | waterfall | 包裹工具体（around） | 完全替换执行（可换 signal、可换结果） |
| `tools/post-execute` | waterfall | 结果产生后 | 可替换 `value` 或 `content`（有约束） |
| `tools/result` | emit | 结果定型后 | 只通知（**不能改结果**，逐监听器隔离） |
| `tools/change` | emit | 注册表变化 | 通知（prompt 重算据此类事件） |

### 三段返回值：为什么需要三态

调度器接口（`:444-453`）：

```ts
prepare(exec) → { kind:'dispatch'; exec }
              | { kind:'post-result'; exec; result }   ← 还要跑 post-execute
              | { kind:'final-result'; exec; result }  ← 跳过 post-execute

dispatch(exec) → { kind:'post-result'; result } | { kind:'final-result'; result }
```

三态的语义差别就是注释说的那句话（`:420-422`）：**"A `post-result` still receives post-execute; a `final-result` bypasses it."**

为什么要在**prepare 阶段**就区分？因为某些结果是在前置阶段产生的（例如被 who 在 pre-execute 里 deny 了、工具不存在、参数非法），这些结果**不应该再走 post-execute**——否则一个"被拒绝的调用"还会经过结果改写管线，第三方插件可能把它"改写成功"。

### 算法：`prepareExecution` 的判定顺序（`:1454-1498`）

```
createExecution(input)                                    :1355
 ├─ 名称解析（get(name, agent)）+ 折叠判定（collapses）      :1371-1372
 ├─ 快照 arguments（必须无损 JSON，否则 final-result）        :1403-1406
 ├─ 记录 contentFinalizers / cancellationStates             :1409-1413
 ├─ 若被折叠（ptc 模式下只允许 run_code）→ final-result      :1414-1434
 └─ 否则 kind:'ready'

prepareExecution 主体：
 ├─ 调用方已取消？→ final-result(ABORTED_BEFORE_DISPATCH)   :1461-1463
 ├─ await waterfall('tools/pre-execute', exec)              :1466-1469
 ├─ gate.kind==='ask' → serviceAsk()（走审批 seam）          :1470-1472
 ├─ 取消 && 审批被取消 → post-result(aborted)                :1474-1476
 ├─ denialReason = allow ? guardReason(exec) : decision.reason
 │    ← 注意：guard 只在 allow 之后跑，deny 理由优先于 guard    :1477-1479
 ├─ denialReason 存在 → post-result（错误结果）               :1480-1490
 ├─ 再次检查取消 → post-result(aborted)                      :1491-1493
 └─ kind:'dispatch'                                        :1494
```

### 三处值得记的设计

1. **折叠调用在策略管线**之前**终止**（`:1364-1370` 注释原文）：*"pre-execute listeners, approval `ask`, and guards must never observe — or worse, approve — a call that can only fail."* —— 不给"能被批准但必然失败"的调用任何被批准的机会。
2. **`finishScheduledExecution` 的双层 try/catch**（`:1622-1637`）：先物化结果（失败则转错误结果），再做工具自有内容变换（失败则转错误结果），最后**才**通知。注释（`:1647-1648`）：通知时把 exec **冻结**——防止观察者改掉注册表的活对象。
3. **取消结果的语义由"工具体是否已开始"决定**（`:1508-1516`）：`bodyInvoked ? ABORTED : ABORTED_BEFORE_DISPATCH`。两个不同错误码让模型能区分"可能已有副作用"与"肯定没跑"。

### 对照提示

XEYO 的工具执行链在 `engine/query_loop.py` 内联完成，**扩展点为 0**（没有对应 `tools/pre-execute` 这类事件）。XEYO 的可拦截性靠"工具实现内部调 policy"，即**每个工具自己调用权限判定**，而不是有一个统一的管线钩子。这就是第三轮说的"dsh 是层，XEYO 是函数或约定"。

---

## A-7 工具并发调度机制：派发可重叠，提交必按模型序

### 设计意图

一个 assistant 消息可能带多个 tool call。它们有的能并行（读文件），有的不能（写文件、问用户）。dsh 的调度器要在保证**结果顺序与模型输出顺序一致**（否则 transcript 无法复现）的前提下，尽可能并行。

### 核心数据结构（`tool-calls.ts:26-39`, `:133-141`）

```ts
Slot[]          // 按模型序的槽位，index 对齐 group
callSeqs[]      // 每个已启动调用的 tool/call seq（供结果引用）
nextToStart     // 下一个待启动
committed       // 已提交的前缀长度（只沿连续槽位推进）
started         // 已启动数
inFlight: Map<index, Promise<index>>
```

### 算法：分组 → 池 → 屏障

```
executeToolCalls:                                        tool-calls.ts:60
 while next < planned.length:
   mode = ctx.tools.executionMode(planned[next])
   group = mode==='parallel' ? planned.slice(next) : [planned[next]]
   outcome = await runGroup(group, mode)
   next += outcome.consumed
   if (outcome.aborted) { 给剩余调用补合成 tool/call+result；return }
```

```
runGroup（并发模式）:                                     :122
 fillPool(): while 未中止 && 有剩余 && inFlight.size < maxParallelToolCalls:
   ├─ 若 nextToStart>0 且后续调用的 mode 变成非 parallel → break（形成屏障）
   ├─ await startCall(nextToStart)      ← 含 prepare（有序！可 await 策略/审批）
   ├─ await commitReady()               ← 按序提交已完成的结果与上下文
   └─ 检查中止
 while inFlight.size>0:
   ├─ await Promise.race(inFlight.values())  ← 谁先完成先收
   ├─ await commitReady()                    ← 但只提交"连续的"前缀
   └─ fillPool()
```

### 三条关键不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | `committed` 只跨**连续**模型序槽位推进（后续完成但前面没完成 → 不提交） | `:147-161` |
| I2 | 并发上限每次从 `ctx.agentLoop.config` **重读**（配置变更对下一个 group 生效，不打扰在飞的 group） | `tool-calls.ts:132` + `agent-loop/index.ts:393-398` |
| I3 | 中止时：已启动的调用**提交真实结果**，未启动的补**合成错误结果** | `:238-243`, `:250-260` |

I2 的实现细节很讲究：`config` 上用了一个 **getter**（`index.ts:396-398`）而不是快照字段，注释说明原因是"tool-calls.ts 在每个 group 开始时解构它"。

### 调度器失败 vs 中止：两种收场（`:232-236` vs `:238-243`）

- **中止**（abort）：给未启动的调用合成结果 → 保证日志可复现；
- **调度器内部失败**：`Promise.allSettled(inFlight)` 等已启动的排干，**不合成任何结果** → 保留已记录的 `tool/call` 事件，如实暴露"有调用被记录了但没有结果"。

这个区别的实质是：**中止是预期事件（要能续），失败是异常（不能粉饰）**。

### `executionMode` 的 fail-closed 设计（`:1267-1276`）

```ts
const tool = this.resolveExecution(...)
if (!tool?.isConcurrencySafe) return { kind:'exclusive' }   // 未声明即独占
try { return tool.isConcurrencySafe(args) === true ? parallel : exclusive }
catch { return { kind:'exclusive' } }                        // 判定抛错也独占
```

**只有精确返回 `true` 才并行**。默认、未知、抛错一律独占。这是典型的 fail-closed。

### 对照提示

XEYO 的并发在 `python/tools/orchestration`（信号量，默认 10，对应 `maxParallelToolCalls`）。XEYO 的 `TOOL_META` 里有 `concurrency_safe` 字段（第四轮已列），注册期有硬失败校验。差别在**屏障语义**：dsh 允许"前面并行、遇到独占调用即形成屏障"，XEYO 是整批并发。另外 XEYO 没有"中止时补合成结果"这一层——它的 `incomplete_tool_uses` 记录在 `.turn.json` 里（见 A-2 对照）。

---

## A-8 沙箱 confine 机制：一个函数把政策编译成 argv

### 设计意图

沙箱的全部抽象只有一个方法（`sandbox/src/index.ts:158-176`）：

```ts
abstract confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv
```

输入是**调用方本来要 spawn 的精确 argv**（注释强调：不是 shell 字符串，shell 型调用方应传 `['bash','-c',command]`），输出是**应该改 spawn 的 argv** + 强制完整度 + 拒绝签名 + runner 失败规则。

### 不变量：静默裸跑被禁止

类注释（`:152-157`）原文：

> *"{@link confine} must return enforcing argv or fail closed at wrap or runner-execution time; **silent unconfined passthrough is forbidden**."*

强制手段（`:126-144`）：无后端可用时抛 `SandboxUnavailableError`，携带 code `SANDBOX_UNAVAILABLE` 经 `tool/result` 的结构化错误通道传给调用方。错误文案直接告诉用户怎么办（装 bwrap / 用 Landlock 内核 / 检查 sandbox-exec / 检查 Windows ACL runner / 或者显式切到 `danger-full-access`）。

### 政策结构（`:39-72`）

```ts
SandboxExecutionPolicy {
  mode: 'read-only' | 'workspace-write' | 'danger-full-access'
  workspaceRoot: string          // 即使当前模式不用也带着（调用方先解析一次再选路径）
  sessionId?: SessionId          // 后端据此挂每会话状态（Windows ACL 的随机私有临时目录+SID）
}
```

注释（`:61-68`）明确：政策是**每次调用携带**的，不是固定在后端上——因为"两个消费者可能同时用不同政策 confine"（bash 只读，同时受限子 agent 需要自己的状态目录可写），且"一次被批准的升级重试是新的一次调用"。

### 平台后端与拒绝方言

`ConfinedArgv` 返回的 `denialSignatures`（`:100-108`）是一处很细的设计：**每个后端有自己的拒绝方言**——bwrap 用 EROFS 文案、Landlock 用 EACCES、Seatbelt 用 EPERM。注释强调消费方必须匹配**本后端的方言**而不是跨后端并集：*"the union claims denials a given backend never produces."*

`enforcement` 字段（`:54-59`）区分 `full / partial`：`partial` 表示"当前后端或较老内核 ABI 无法治理所有承诺的文件效果"——注释提醒需要绝对边界的调用方**不能把 partial 当 full**。

### runner 失败判定（`:74-88`）

`RunnerFailureRule` 的顺序被明确固定：
1. 先按 `allowedExitCodes` 过滤（缺省允许任意非零）；
2. 再按 `informationalLines` **逐行精确相等**剔除无害输出；
3. 最后在每个剩余 stderr 行里**大小写不敏感**匹配 `fatalSignatures`。

注释（`:79-80`）：*"Exit status alone never proves runner failure."* —— 退出码非零可能是被沙箱**正确拒绝**了，不一定是沙箱自己坏了。区分这两者是"沙箱没装上"与"沙箱装上了并且拦住了"的分界。

### 升级阶梯（`escalation.ts`）

```ts
WIDER_MODES = {
  'read-only':       ['workspace-write', 'danger-full-access'],
  'workspace-write': ['danger-full-access'],
}
ESCALATION_TARGETS = ['workspace-write', 'danger-full-access']   // 封闭词汇，不因默认档而裁剪
```

`approveEscalation`（`:157-189`）是**有序的 fail-closed 序列**：

```
1. 严格放宽检查（对"本次调用的有效模式"检查，不是对 schema）→ 不满足即抛，且不提示人工
2. 无审批服务 → 抛
3. 无 agent（无会话可审计/可路由）→ 抛
4. 走审批请求
5. outcome 映射：allowed-once → 放行；rejected/cancelled/unavailable → 三种不同文案
```

三处设计理由（注释原文）：

- `:22-27`：宽化表"**在 EXECUTION 检查，绝不烤进工具 schema**"——因为 schema 是**注册表全局**的，而有效模式是**每次调用**的真值。
- `:33-40`：`ESCALATION_TARGETS` 是封闭词汇，不裁成"比默认档更宽的那些"——否则默认 `danger-full-access` 的部署会**什么都广告不出来**，而会话切窄之后就没有杠杆了。
- `:44-61`：`sandbox_permissions` 与 `justification` **必须同时出现**（"无理由的审批提示，或驱动不了任何东西的理由，都是畸形提问"），且理由必须是非空句子。

### 面向模型的标记（`:63-86`）

```
sandboxDenialMarker(mode)  = '[sandbox: file access denied under <mode> mode]'
escalationHintMarker(s)    = '[sandbox: escalation available — retry this exact <s> once with sandbox_permissions …]'
```

注释（`:75-83`）：同轮升级提示**骑在被拒结果上**，"so the sanctioned retry does not depend on the model recalling the tool description"——把提示放在决策点，而不是指望模型记住工具描述。**这是 dsh 唯一一处明确的"模型可见文本带行动指引"**，但它的对象是"被拒绝的动作该走哪条合法路径"，属于对拒绝事实的补全，不是路线编排。

### 对照提示

XEYO **没有这一层**。全仓 `landlock|seatbelt|bubblewrap|bwrap|sandbox-exec` 零命中（第四轮已复核）。XEYO 只有：
- Windows Job Object（资源限额，**非隔离**）——用于 TUI/终端；
- TerminalBench 场景的 docker 容器路由（评测旁径，`TerminalBench/xeyo_harbor_agent.py`）；
- `permissions/filesystem.py` + `write_scope.py` 的**路径级**写范围限制（在 Python 进程内，不是内核级）。

即：XEYO 的"隔离"是**协商式的**（进程自己遵守），dsh 的是**强制式的**（内核/ACL 执行）。

---

## A-9 压缩事务机制：括号事务 + 工具配对平衡 + 影子计价

### 设计意图

上下文满了要压缩。dsh 的压缩不是"删几条消息"，而是**一次日志事务**：写入 `compaction/start` → `compaction/summary` → 替换表面 → `compaction/end`。整个过程可中断、可重入检测、可失败回滚。

### 为什么必须是事务

因为**总结是一次 LLM 调用**——异步、可能几十秒。在这期间会话可能又有新事件、表面可能被改写。如果总结基于旧表面却应用到新表面，就会覆盖掉新内容。所以必须有"开括号 / 闭括号"和一个**稳定性检查**。

### 算法：`compactSurfaceRegion`（`region.ts:154-256`）

```
1. 只读校验（同步）：validateSurfaceRegion           ← 起止 seq 在表面上、起止是"工具配对平衡"的切点
2. 入口态检查：inspectCompactionEntryState            ← 从日志尾部倒扫，取 openTurn / 未匹配 start / 最新 seed 边界
3. assertCompactionInactive                            ← 有未匹配 start 且无更新的 seed 边界 → busy 拒绝
4. owner 判定：current-turn 必须有开着 turn；null 不许有开着 turn
5. append('compaction/start')  ← ★ 同步紧跟校验，它就是"压缩锁"
6. try:
     ├─ prepareCompaction：用 token meter 量表面，切片，比对阴影 seq 是否仍一致（SurfaceChangedError）
     ├─ await summarize(...)  ← 唯一的长异步
     ├─ assertStable（whole-surface 或 selected-span 二选一）
     ├─ append('compaction/summary')
     ├─ append('user/message'(checkpoint), { surfaceOp:{op:'replace',start,end},
     │                                        sourceEventSeqs:[start,summary,...shadowed] })
     ├─ append('compaction/end')
     └─ completeCompaction
7. catch: 记录 stage（summary/commit），若未在关闭中则 append('compaction/end', {error}) 
8. 可选 flush（耐久性检查点）
9. 按 owner 类型抛不同错误（manual 走 ManualCompactionError 分类）
```

### 压缩锁的实现（`:191` 注释原文）

> *"Idle/log validation and `compaction/start` are synchronously adjacent, so the durable opening marker is the compaction lock before summarization yields."*

即：**没有单独的锁文件**——"日志里有一条未匹配的 `compaction/start`"本身就是锁。崩溃后这个未匹配标记还在，下次启动就能检测到（`assertNoActiveCompaction` 供异步决策后重新检查，`:307-314`）。

### 工具配对平衡（`tool-pairing.ts`）

压缩切点不能切在"模型刚请求了工具、结果还没来"的中间。判定用**增量计数**：

```ts
eventDelta(event):
  assistant/message → +该消息里 tool-call 块的数量
  tool/result       → -1
  其他              → 0

沿表面折叠，任何时候计数 < 0 → 抛"corrupt surface"
每次计数回到 0 → 这个"切"是平衡的
```

缓存按 `(session, replaceGeneration)` 组织（`:26, :71-91`），表面被替换（generation 变）就整体重建。注释（`:48-49`）：看不见的尾部**先验证再落缓存**，"so a corrupt append cannot leave a partially advanced state behind"。

### 影子计价（`region.ts:340-364`）

```ts
shadowedTokenCount      = Σ heuristicTokens    ← 固定启发式价
shadowedRouteTokenCount = Σ tokens             ← 路由实价
```

注释（`:356-359`）：*"The shadow-price protocol prices replacements with the fixed heuristic so the O(1) projection fold stays in agreement with its own appends; retention, range selection, and the shrink comparison read the route-priced `tokens` instead."*

即：**投影折叠必须用固定价**（因为要 O(1) 且与 append 一致），但**决策**（保多少、切哪里、够不够小）用**路由实价**（更准）。

收缩判据（`:383-388`）：
```
framedSummaryTokenCount >= shadowedRouteTokenCount → 抛"summary is not smaller than the shadowed content"
```
注释（`:380-382`）：checkpoint 是纯文本，所以它的启发式价**就是**路由价，直接比就回答了真问题——"替换后下次请求压力是不是更小"。

### 稳定性检查的两种模式

| 模式 | 含义 | 用途 |
|---|---|---|
| `whole-surface` | 整张表面必须与总结前**深相等** | 手动压缩（会话空闲，要求严格） |
| `selected-span` | 只要求被选中的那一段仍存在、连续、等价的替换目标 | 自动压缩（开着 turn，允许别处新增） |

`selected-span` 的注释（`:408-412`）：*"Nodes added outside it remain visible and do not invalidate the summary."* —— 这是为了让自动压缩能在 turn 进行中工作。

### 对照提示

XEYO 的对应物是 `engine/compact.py`（353 行）：`tool_pair_ranges` / `keep_tail_cut` / `project` / `project_incremental`。XEYO 也有**工具配对**概念（`_assistant_tool_ids` / `_tool_result_ids`）——两端独立演化出了同一条约束。

差别在**事务性**：XEYO 的压缩是**内存投影 + 可选 LLM 摘要**（C2），**不写日志、不落锁、无括号**。所以 XEYO 在压缩过程中崩溃 → 没有痕迹，下次从头再压；dsh 崩溃 → 留下未匹配的 start，下次能识别并处理。

这是"事件溯源"给压缩带来的直接红利。

---

## A-10 会话持久化机制（JSONL）：写后缓冲 + 单写者 + 撕裂尾修复

### 设计意图

`Session.append()` 的注释（`core/session/src/index.ts:664-668`）写明：**热路径绝不阻塞在 I/O 上**，持久化插件异步缓冲。于是有了"写后缓冲"这个机制。

### 算法：一条事件怎么走到磁盘

```
Session.append → log.push → 同步派发 session/event
                              ↓
JsonlBackendTracker.install 里注册的监听器：        storage.ts:501-505
  writers.get(session.id)?.enqueueLive(event, ...)
                              ↓
JsonlSessionHandle.enqueueLive:                      storage.ts:240-247
  buffered.push(structuredClone(event))             ← 存"持久化自己的副本"
  if (无 batchTimer && 未暂停) batchTimer = setTimeout(drainLive, 200ms)
                              ↓
drainLive / drainBuffered:                           storage.ts:254-282
  单飞（this.draining ??= …）
  while buffered.length > 0:
    enqueueChain(async () => {
      batch = buffered.splice(0)      ← 只有这个单飞 drain 会 splice
      try  persistContiguous(batch)
      catch { buffered = batch.concat(buffered); drainPaused = true; throw }
    })
                              ↓
persistContiguous:                                   storage.ts:285-309
  1. 非写句柄 → SessionReadOnlyError
  2. ensureLease()  ← 首次写前拿跨进程写锁
  3. assertContiguous(id, batch, cursor)
  4. 若有待处理撕裂尾：truncateTornTail → 再 persistBatch(recoveredTail)
  5. persistBatch(batch)
  6. materialized = true; cursor += batch.length; primed = undefined; observedLength = cursor
```

### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | 一个 session id 在进程内**只有一个写句柄**（`writers` map + `SessionAlreadyOwnedError`） | `storage.ts:395-398, 450` |
| I2 | 一个句柄的**所有变更串在一条 promise 链上**（`chain`），永不 reject（`chain = next.catch(()=>{})`） | `:323-327` |
| I3 | 读操作的返回长度**不得变小**（`observedLength` 单调） | `:141-144` |
| I4 | 批次必须与 `cursor` 连续（`assertContiguous`） | `:289` |
| I5 | 关闭是幂等的（`this.closing ??=`），且关闭前必须 drain 到缓冲为空（循环，因为别的 fiber 可能还在 publish） | `:189-206` |

### 撕裂尾（torn tail）修复机制

崩溃可能留下"半行 JSON"。处理方式是**三段式**（`:290-303`）：

1. `tornTruncateTo` → 先截断坏字节；
2. `recoveredTail` → 把从坏行里**恢复出来的完整事件**重新写一遍；
3. 然后才写新批次。

每一步完成后才清掉对应状态（注释 `:290-293`：*"clearing each step's state only once it lands so a failed step retries on the next mutation"*）——即**幂等重试**，不怕中途再崩。

### 跨进程写租约

`ensureLease()`（`:318-320`）在**第一次真正落盘前**拿锁（不是构造时）。注释（`:311-317`）：*"a create handle acquires it here — immediately before the first log bytes publish — and keeps it through close even when materialization then fails, so a materializing session stays exclusively owned across retries."*

这条设计防的是竞态：两个进程同时 create 同一个 id，谁先写出第一个字节谁拥有。

### 对照提示

| 维度 | dsh | XEYO |
|---|---|---|
| 热路径 | 不阻塞，200ms 批量 | 直接写（`session/persistence.py`）+ 可选 fsync |
| 并发保护 | 单写者句柄 + promise 链 + 跨进程租约 | 进程内 RLock（`rewind/revision.py:20-26`） |
| 撕裂行 | **显式修复**（截断+重写恢复事件） | **静默跳过**（`journal.py:97-115`：坏行 `continue`） |
| 副本策略 | `structuredClone` 存自己的副本 | 无（直接序列化当前对象） |
| 关闭语义 | drain 循环直到空 + 聚合失败 | 无显式 drain |

两端对"坏行"的态度是两种哲学：dsh **尽量救回**（能解析出的部分重写），XEYO **直接放弃**（注释说"进程被杀可能留下最后一行残页：解析失败的行直接跳过即可"）。

---

## A-11 会话 fork / 继承机制：用一条计数切开"父的"与"我的"

### 设计意图

fork 一个会话（从某个点分叉）在事件溯源系统里很微妙：子会话的日志包含父会话的前缀。如果子会话把整段前缀当"自己的"，那"我这个会话一共发生了什么"就答不出来，`firstLiveSeq`/压缩/审计全都会算错。

dsh 用**两个不同的计数**分别回答两个不同的问题（`index.ts:479-502` 的注释值得整段引用）：

| 字段 | 回答的问题 | 语义 |
|---|---|---|
| `firstLiveSeq` | **本进程**从哪个 seq 开始写 | 构造种子（replay/fork/resume）的长度；**不持久化**，靠 `session/end-seed` 事件投影到日志 |
| `inheritedEventCount` | **fork 血缘**切在哪 | 持久化在 header 里；resume 时保持原 fork 值不变 |

注释明确点出两者的差别：*"a resumed session's constructor seed is its full stored log, while the inherited count keeps the original fork value — this field is the in-process construction fact."*

### 算法：构造时的多重校验（`:541-608`）

```
1. restore 模式 → validateRestoredSessionHeader
2. 逐个 seed 事件：
   ├─ snapshotJsonValue（无损 JSON）
   ├─ assertSessionEventEnvelope
   ├─ seq 必须 == index（从 0 连续）
   └─ surfaceManager.validateNext（表面合法性）
3. firstLiveSeq = log.length
4. seeded 但没有 seed → 抛
5. seeded 但没有 inheritedEventCount → 抛
6. 非 seeded 但 inheritedEventCount !== 0 → 抛
7. inheritedEventCount > log.length → 抛
8. snapshot 模式 && seeded && inherited !== log.length → 抛
9. 补 session/end-seed 标记（fresh seeded child 必带；restore 只在末尾不是该类型时补）
```

第 8 条是核心约束：**fresh fork 的种子必须恰好等于继承前缀**（不能"多拷贝一段又不认它是继承的"）。

### fork 的拒绝码（`:857-870`）

```ts
SessionForkErrorCode = 'SESSION_NOT_FOUND' | 'SESSION_NOT_LIVE' | 'SESSION_ALREADY_EXISTS'
                     | 'INVALID_BOUNDARY' | 'OPEN_TURN'
```

`OPEN_TURN` 单列一条：**不能在 turn 中间分叉**——否则 fork 出来的历史里有一个没有结尾的 turn，provider 会拒绝。

### `session/end-seed` 的用途

它是一个**日志里的界碑**，让"只读存储历史"的消费者（没有内存对象）也能找到"种子到哪结束"。压缩的入口态检查就读它（`region.ts:535-537`）：`latestEndSeedSeq > 未匹配start.seq` 说明那个未匹配的 start 属于**上一个生命周期**，不是当前这把锁。

### 对照提示

XEYO 有 `rewind/revision.py::truncate_to`（"创建新 head 恰好包含目标 revision"），语义接近"分叉到某个点"，但它是**revision 层面**的，不是会话 ID 层面的。XEYO **没有会话级 fork**（第四轮已复核）。XEYO 的 `rewind/revision.py` 保存了 `parent_revision_id`，形成一棵 revision 树——这是"分叉"的另一种表达。

---

# Part B — XEYO 实现机制设计说明

## B-1 T_now 注入管线：把易变内容挡在 system 前缀之外

### 设计意图

system prompt 是 KV 前缀缓存的头部，一次字节变化整段缓存失效。但 Agent 每轮都有易变事实（预算水位、工具面变更、文件冲突、续跑指令）——既必须让模型看到，又不能写进 system。

`prompt/turn_context.py:1-7` 的模块 docstring 就是这条设计的原始表述：

```
"""本轮易变上下文：挂到投影最后一个 user 的尾部（T_now），不进 system 左段。

模式说明、已批准计划、预算提示、MEMORY 索引等易变内容放这里，
避免打爆 system 前缀的 KV 缓存。
```

### 三类块（为什么要分类）

`prompt/pre_llm_inject.py:1039-1040` 注释原文：

> P1/F3：所有块以 (类别, 文本) 装配；类别决定放置（A1）、门控（D1）与预算（F1）。新增块必须声明 `KLASS_*`，遗漏按 INVENTORY 处理（最保守）。

| 类别 | 常量（`pre_llm_inject.py:80-82`） | 预算待遇 | 门控 |
|---|---|---|---|
| directive | `KLASS_DIRECTIVE = "directive"` | **永不裁剪**（构造处各自有界，`:996-997`） | 绝不静默 |
| event | `KLASS_EVENT = "event"` | 永不裁剪 | **绝不静默**（drain 语义，静默即永久丢） |
| inventory | `KLASS_INVENTORY = "inventory"` | 填 `min(2500, 6000-已用)` 配额 | 模糊指代轮**整体静默** |

### 装配：唯一入口

`_tag_block(tagged, name, block)`（`:922-930`）是所有装配点的唯一通路：

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

它同时承担两件事：把**登记名**写进代码（供机器执法解析），以及消费 `XEYO_T_NOW_SKIP` 消融名单（`:917-919`）。实测 20 个装配点与登记表 20 条一一对应；执法测试直接断言源码里不存在裸 `tagged.append(`——这正是"登记名必须出现在代码里"的意义。

### 三层预算

| 常量 | 值 | 作用 |
|---|---|---|
| `T_NOW_TOTAL_BUDGET` | `6_000` | 全部块总量硬顶 |
| `T_NOW_INVENTORY_MAX` | `2_500` | inventory 类配额上限 |
| `T_NOW_EXTRA_BUDGET` | `6_000` | 旧路径 `_trim_blocks_to_budget` 的独立预算 |
| `NESTED_MAX_CHARS` | `4_000` | 嵌套 XEYO.md 单块上限 |
| `T_NOW_BLOCK_HARD_CAP` | `21` | 登记条数硬顶（注释记 **23→21**：裁决 5 删 `stale_xeyo_md`/`nested_change` 两块） |

`_trim_tagged_blocks`（`:990-1027`）算法：

```
1. 遍历 tagged：inventory 归 inv；其余归 kept 并累加 used
2. room = max(0, min(inventory_max, total - used))
3. 按装配序填 inv：
   ├─ len(b) <= room → 收，room -= len(b)
   ├─ room >= 64       → 截断到 room + "…"，room = 0 后停止
   └─ 否则             → break（剩余不足 64 → 整块丢弃）
```

**"剩余 < 64 整块丢弃"是本机制最见功夫的一处**：宁可整块不给，也不给模型一个 20 字的残块——残块比没有更坏（模型会把它当完整事实）。

### D1 模糊指代轮门控

`:1312-1315` 注释原文：

> P1/D1：模糊指代轮静默全部 INVENTORY。事件/指令绝不静默：notices / settlements / reconcile 有 drain 语义，静默即永久丢失。

识别在 `_is_vague_referent_turn`（`:966`）：仅 fresh-user 轮 + 确有上文才判；`_VAGUE_ACK` 24 个确认词 + `_VAGUE_MARKERS` 24 个模糊动词 + 长度 ≤ `_VAGUE_MAX_CHARS=24` + 无 `_VAGUE_CODE_MARKERS`。注释写明 fail-open：*"误判只丢一轮参考数据；指令/事件永不受影响"*。

### 失败路径

- `XEYO_T_NOW_SKIP` 命中块名 → 该块不装配（消融测试用，`:922-929`）
- `forced_wrap_up` 兜底（`:1320-1327`）：trim 之后若 wrap_up 块被裁则**强挂一次**（去重）——注释解释挤掉它的后果：*"模型只看到'没有工具'却不知道要立即作答，空响应/硬停概率上升"*

### 对照提示

dsh 没有等价物。最接近的是 A-5 运行上下文快照——也是"易变事实进上下文不破坏缓存"，但形态相反：dsh 是 **seam 插件 + 差异才发 + 被替换即撤销**（`runtime-context.ts`），XEYO 是**单管线 + 分类预算 + 登记表执法**。dsh 用类型系统约束结构，XEYO 用测试断言约束纪律。

---

## B-2 env_channel 声道：伪造一对只存在于投影的 tool 对

### 设计意图

`prompt/turn_context.py:119-129` 的 docstring 是这条机制的完整自陈，整段引用：

```
方案 A（环境声道）：内部格式为 assistant(tool_use 块) → user(tool_result
块)，经 normalize_messages_for_openai 转成标准 assistant(tool_calls)
→ tool 消息。tool_result 是模型训练出的「环境数据声道」——注入内容与
用户意图在消息结构上隔离，说话人混淆无从发生。工具名（xeyo_env_notice）
不注册进 tools 数组（schemas 冻结红线不受影响）；尾部追加不改前缀字节，
KV 缓存语义与 legacy 尾插等价。

copy-on-write：不修改入参列表与既有消息对象，绝不进 MessageStore / JSONL。
```

一句话：**引擎的注入文本不能伪装成用户说的话**。tool_result 在模型训练分布里就是"环境回传的数据"，用它承载注入，结构上就不可能与用户意图混淆。

### 算法：一对消息的构造（`:130-160`）

```python
t = (text or "").strip()
if not messages or not t:
    return messages                       # 空则原样返回，不产生半态
from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id
call_id = new_env_tool_call_id()
pair = [
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
]
return [*messages, *pair]                  # 尾插，不改既有对象
```

三个不变量：
1. `ENV_TOOL_NAME` **不注册进 tools 数组**（`:124-125` 明写：schemas 冻结红线不受影响）
2. 尾插不改前缀字节 → KV 缓存语义与 legacy 尾插等价
3. copy-on-write，**不进 MessageStore / JSONL**（投影-only）

### 策略分派（`:1336-1358`）

```
strategy = ctx.strategy or t_now_strategy()      # 显式 > 环境变量 > 默认
├─ STRATEGY_PREFILL → 回落 STRATEGY_ENV_CHANNEL（预留档，实测未过）
├─ STRATEGY_SKIP    → return out（本轮不注入）
└─ STRATEGY_ENV_CHANNEL → format_env_notice(kept) → append_env_notice_pair
legacy 路径（仅 after_tools 与合成分仓）：
   ├─ after_tools → append_text_blocks_to_last_user（Continue 在前）
   └─ fresh-user  → inventory 前插（prepend_text_blocks_to_last_user）
                    directive/event 尾插（append_text_blocks_to_last_user）
```

优先级链：会话/请求显式（`set_t_now_strategy`）> `XEYO_T_NOW_STRATEGY` > 默认 `env_channel`。

### 失败路径：不落回 legacy

`:1340-1344` 注释是这条机制最重要的安全边界：

> L2（2026-09-09）：厂商拒绝伪造 tool 对时本轮不注入，**绝不落回 legacy 用户尾插**（引擎文本进用户角色 = 说话人混淆源）。执行层硬约束（预算/回合/wrap 门）不依赖提示文本。

也就是说：`SKIP` 档的代价是"模型这轮看不到易变块"，而不是"悄悄退回一个已知有缺陷的声道"。厂商侧结构类 4xx（400/404/413/415/422）被拒且未吐 chunk 时，引擎记进程级备忘并当场以 legacy 重建重试——但那是**厂商兼容**路径，不是默认降级。

### 对照提示

dsh 的对应机制是 A-5：把易变事实做成**可替换的 user 消息**（`runtime-context.ts`）。两侧都独立得出"不能碰 system 前缀"，但载体选择相反——dsh 用 user 角色（可替换、有撤销语义），XEYO 用伪造的 tool 对（结构隔离、只追加）。**这是同一问题的两种不同答案，不是同一答案的两种实现。**

---

## B-3 权限判定链：先硬拦（不可被授权穿越）再分派

### 设计意图

`evaluate_policy`（`:1319-1388`）与 `evaluate_policy_impl`（`:1391-...`）被刻意拆成两层：

- **内层 `_impl`**：纯判定，含全部 DENY 硬拦。终态返回，不看 grant。
- **外层**：只有内层给出 `ASK` 时才叠加 always-allow grant。

`:1327-1332` docstring：

```
评估工具是否允许 / 需要确认 / 拒绝（T10：外层叠加 grant store）。

ASK 先查 always-allow 授权（"don't ask again"）：命中 → ALLOW(matched_rule=
"grant_store")。守卫：DENY 不可被 grant 触碰（impl 已终态返回）；worker
写作用域 / 远程会话 / permission_mode=always（显式逐条确认意图）一律跳过。
```

**"DENY 不可被 grant 触碰"是结构性的，不是靠分支判断的**——因为 `:1336` 第一行就是 `if decision.decision != PermissionDecision.ASK: return decision`。

### 判定顺序（`evaluate_policy_impl`，逐分支）

| # | 条件 | 结果 | 行 |
|---|---|---|---|
| 1 | `raw_name in pol.deny_tools` | DENY `policy_deny_tool` | `:1404-1410` |
| 2 | `raw_name.startswith("mcp__")` | 转 `_evaluate_mcp` | `:1413-1414` |
| 3 | `raw_name == "Mcp"` | 转 `_evaluate_mcp_gateway` | `:1418-1419` |
| 4 | `raw_name in _ALWAYS_ALLOW` | ALLOW `tool_unrestricted_p0` | `:1421-1426` |
| 5 | `raw_name in _OUTBOUND_ASK_TOOLS` | 路径校验 → DENY / max 档 ALLOW / 否则 ASK | `:1429-1474` |
| 6 | `raw_name in _UI_ASK_TOOLS` | 转 `_evaluate_ui_ask` | `:1477-1478` |
| 7 | `raw_name == "Agent"` | always 档 ASK，否则 ALLOW | `:1481-1493` |
| 8 | `raw_name == "Bash"` | 转 `_evaluate_bash` | `:1495-1500` |

### Bash 的 11 级链（`:822-1013`）

docstring 自己就是顺序表（`:828`）：

> 黑名单 DENY → 密钥 DENY → 规则 DENY(T7) → 策略文件 DENY → 仓库/远程策略 → peer git → 只读白名单(规则驱动) → 规则 ASK(T7) → 写目标证明 → 默认 ASK

| 级 | 判定 | 结果 |
|---|---|---|
| 1 | `bash_deny_reason` / `bash_deny_extra` | DENY（黑名单 / 仓库 `deny_commands`） |
| 2 | `bash_secret_read_reason` | DENY（密钥路径） |
| 3 | `bash_rule_ask_deny == "deny"` | DENY（T7 前缀规则） |
| 4 | `_bash_touches_policy_file` | DENY（Bash 不得改写 `.xeyo-policy.json`） |
| 5 | `_peer_bash_conflict` | 三选 ASK（多会话交叉） |
| 6 | `bash_mode == "deny"` 或 remote deny | DENY |
| 7 | `get_write_scope() is not None`（worker） | remote→DENY / 只读→ALLOW / 其余 DENY，**永不 ASK** |
| 8 | `bash_mode == "ask"` 或 remote | ASK |
| 9 | `rule_ask_deny == "ask"` | ASK |
| 10 | `bash_readonly_allow` | ALLOW |
| 11 | `_bash_writes_file` → 写目标证明 | 证明失败 DENY / 越界拦 / 危险路径 ASK / 否则 ALLOW |
| 12 | `is_max_permission_mode()` | ALLOW（max 档免确认） |
| 13 | 兜底 | ASK |

第 6 级旁还有一个**安全默认**（`:874-881`）：`bash_mode == "allow"` 时若既无 `XEYO_BASH_UNSAFE_ALLOW=1` 也不是 `full` profile，**自动降回 `default`**。注释：*"无 OS jail 时不允许 bash:allow 自动放行一切"*——这是"没有沙箱就不给全权"的直接代码化。

### grant 叠加的 5 条守卫（`:1338-1370`）

| 守卫 | 理由 | 行 |
|---|---|---|
| `get_write_scope() is not None` | worker 沙箱：grant 不得放宽 | `:1342-1343` |
| `is_remote_session(...)` | 远程会话不得静默放行（§34 不变量） | `:1344-1345` |
| `permission_mode() == "always"` | 用户显式要求逐条确认 | `:1346-1347` |
| Bash 且 `bash_command_is_composite(cmd)` | G29：`git status && curl x\|sh` 不能蹭 `git status` 授权 | `:1350-1362` |
| `fp` 为空 | fail-safe，不落 grant | `:1369-1370` |

### 对照提示

dsh 的权限是**预设驱动的策略档**（A-6/A-8），判定在工具瀑布的 pre-execute 阶段；XEYO 的权限是**按工具名分派的长链**，判定在工具运行时之前，且链上有 11 级"越往后越松"的阶梯。差异的根源：dsh 有沙箱兜底，所以策略可以粗；XEYO 没有沙箱，所以策略必须细——**XEYO 的 11 级链是"没有沙箱"这个事实的补偿物**。

---

## B-4 Bash 策略：正向白名单 + 否定式复合拒绝

### 设计意图

Bash 是唯一"内容不可静态解析"的工具，所以策略只能是**模式匹配 + 否定式收紧**：黑名单拦已知破坏，白名单放已知安全，中间地带一律 ASK。

### 18 条黑名单正则（`permissions/bash_policy.py:20-106`）

按原因分类（每类都是"能一次干掉机器/数据"的动作）：

| 原因 | 覆盖 | 代表模式 |
|---|---|---|
| `destructive_root_delete` | 5 条 | `rm -rf /`、`del /s`、`rd /s`、`Remove-Item -Recurse`、UNC 破坏 |
| `disk_format` | 2 条 | `format X:`、`mkfs*` |
| `disk_wipe` | 2 条 | `cipher /w`、`dd of=/` |
| `system_power` | 1 条 | `shutdown`/`reboot`/`poweroff` |
| `registry_system` | 1 条 | `reg delete hklm` |
| `remote_exec` | 4 条 | `curl\|sh`、`wget\|sh`、`iwr\|iex`、`iex`、`bash -c $(curl)` |
| `fork_bomb` | 1 条 | `:(){ :\|:& };:` |
| `encoded_powershell` | 1 条 | `powershell -EncodedCommand` |
| `certutil_decode` | 1 条 | `certutil -decode` |
| `unc_destructive` | 1 条 | `rm \\\\host\share` |

`_normalize_command`（`:561-565`）先压空白与统一换行——*"降低简单空格绕过"*。

### 密钥路径拦截（`:543-558`）

`_SECRET_TOKEN_RX` 覆盖 `.env*` / `.gitconfig` / `id_rsa|id_ed25519|id_ecdsa` / `credentials*` / `.npmrc|.pypirc` / `*.pem|key|p12|pfx` / `.ssh/*`。命中即 DENY（`bash_secret_read_reason`，`:599-609`）。

### 只读白名单：正向放行（`:631-648`）

```python
def bash_readonly_allow(command, *, cwd=None) -> bool:
    if not isinstance(command, str): return False
    text = _normalize_command(command)
    if not text or _COMPOSITE_RX.search(text): return False   # 复合/管道 → 不放行
    if re.search(r"(?:>>?|2>>?|&>>)", text): return False     # 重定向写出 → 非只读
    if bash_secret_read_reason(text): return False            # 密钥 → 不放行
    return bash_rule_decision(text, cwd=cwd) == "allow"       # 前缀规则驱动
```

放行面由**前缀规则引擎**驱动（默认规则 = 原 `_READONLY_BASES` 迁移），工作区 `.xeyo/bash_rules.json|toml` 可追加（`:634-637`）。

### 复合命令的否定式拒绝（`:612-628`）

`_COMPOSITE_RX = re.compile(r"[|;&`\n\r]|\$\(|&&|\|\|")` —— 命中即 `True`。用途不只是"不放行只读"，更是**禁止吃 grant**：

> G29：组合命令（`&&`/`;`/`|`/换行/`$(`/反引号等）不得用「前缀 token」的 always-allow grant 静默放行——`git status && curl x|sh` 不能蹭 `git status` 的授权。

这条机制的设计很值得记：**授权单元是"命令前缀"，但放行判断看整条命令是否复合**——两个粒度分离，堵住了"用安全前缀裹挟危险尾巴"。

### 远程会话更严（`:651-654`）

`is_remote_session` 识别 `ilink:` / `filehelper:` 前缀（微信 / 文件助手）。远程会话强制 `pol.remote_bash ∈ {ask, deny}`，**不允许 default/allow 自动放行**（`:882-884`）——注释：*"远程工人无法弹窗确认 → 一律 DENY"*。

### 对照提示

dsh 的 shell 是 capability seam（A-6/A-8），安全边界交给**沙箱**而非命令文本分析；XEYO 没有沙箱，只能把安全边界放在**文本分析**上。所以 XEYO 的 bash 策略比 dsh 复杂一个量级，但**它的安全性依赖"正则足够全"这个假设，而 dsh 的安全性依赖内核强制**——这是两种完全不同等级的可信度。

---

## B-5 授权指纹：身份与参数分离

### 设计意图

"don't ask again"要能复用授权，又要不能过度复用。XEYO 的答案：**指纹只哈希身份，参数永不参与**（`permissions/store.py:419-424`）：

```
§15.1② args 规范化纯函数：键序排序、紧凑分隔、ASCII 转义。

身份与参数分离（§15.1①）：v2 指纹**不含** args —— 本函数服务于
repeat_guard / 网关 describe 校验 / 审计去重等「参数规范化」消费方。
```

注意 `canonical_args` 存在，但**不参与指纹**——这是一个刻意的分工：`canonical_args` 服务 repeat_guard 与审计去重，指纹服务授权身份。

### MCP 指纹 v2（`:440-456`）

```python
_MCP_FP_VERSION = "v2"

def mcp_grant_fingerprint(registered_tool_name: str) -> str:
    tool = (registered_tool_name or "").strip()
    if not tool.startswith("mcp__") or len(tool) <= len("mcp__"):
        return ""                                    # 身份不可用 → 空串，fail-safe
    canon = json.dumps(["mcp-tool", tool], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
    return f"{_MCP_FP_VERSION}:{digest}"
```

逐字说明：输入是 `["mcp-tool", 注册名]` 的紧凑 JSON，SHA-256 后取前 32 hex，前缀 `v2:` 参与比对。**v1 旧授权结构上不可能命中**（`:440-441`）。

docstring 记了 v1 的过放缺陷与修复（`:471-475`）：

> 修复 v1 过放：v1 对所有 MCP 工具共用 `mcp_outbound_ask`，放行一个即放行全部 —— v2 按注册名隔离。

还有一个安全细节：**注册名必须来自网关的已知工具集解析**（`resolve_tool`），绝不从 args 读取（`:447-448`：*"身份经已知工具集校验，绝不从 args 读取，注入免疫"*）。

### Bash 指纹（`:483-496`）

```python
if name == "bash":
    toks = raw.split()
    if not toks: return ""
    if len(toks) == 1: return toks[0].lower()
    return f"{toks[0].lower()} {toks[1].lower()}"    # program + 首参数
```

对应 UI 文案 *"don't ask again for commands starting with …"*。但这条指纹有个已知的粒度问题，由 B-3 的复合命令守卫补齐——**指纹可以是前缀，授予必须是整条命令**。

### 其他工具（`:497`）

回落 `matched_rule`（同类原因聚合）。拒绝类规则在 policy 层先于 grant 生效，所以"同类聚合"不会把 DENY 洗成 ALLOW。

### 对照提示

dsh 侧未见等价的 grant 指纹机制（第四轮已复核其审批结果只有 `allowed-once` 等封闭四值，**唯一授予值就是"这一次"**）。**这是两端审批哲学最硬的一处分歧**：dsh 只给"这一次"，XEYO 给"这一类，且带版本隔离"。XEYO 的复杂度（v2 指纹、身份/参数分离、五条守卫）是为"授权可复用"付出的代价。

---

## B-6 审批挂起：风险分级 TTL + 幂等 resolve

### 设计意图

`engine/permission_coordinator.py:1-10` 的 docstring 说清了职责缝合：

> 把 `SessionTaskState` 与 `PendingPermissionStore` 缝合起来：
> - request：创建 pending 请求、状态转 `waiting_permission`、发布 `PermissionPendingEvent`
> - wait：等待确认（超时按拒绝处理），状态回 `running`、发布 `PermissionResolvedEvent`
> - resolve：外部（前端/微信）确认或拒绝（审计由 `store.resolve` 统一写）
> 三选 peer ASK：wait 返回 `allow / deny / remind / timeout`

### 挂起项结构（`permissions/store.py:33-58`，18 字段）

| 字段 | 类型 | 语义 |
|---|---|---|
| `request_id` / `session_id` / `turn_id` | str | 三级定位 |
| `tool_name` / `tool_input` | str / dict | 待执行动作 |
| `reason` / `prompt` | str | 判定原因 / 展示文案 |
| `expires_at` / `created_at` | float \| None | TTL 两端（`None` = 不超时） |
| `matched_rule` | str | 命中的规则名 |
| `command_summary` | str | Bash 摘要 |
| `choices` | tuple | 三选时非空 |
| `peer_summary` | str | 多会话冲突说明 |
| `resolved` / `approved` / `user_choice` | bool / bool\|None / str | 裁决态（`allow/deny/remind`） |
| `actor` | str | 谁裁决的 |
| `outcome` | str | `user_decided` / `timeout` / `aborted`（供 wait 侧区分结束原因） |
| `workspace` | str | 创建时工作区根（grant 落 workspace 维度） |
| `mcp_target` | str | 网关解析出的目标注册名（v2 指纹用） |

### 风险分级 TTL（`permissions/pending_ttl.py`）

| 场景 | TTL | 依据 |
|---|---|---|
| AskUserQuestion（交互式提问） | **不超时**（`None`） | 由用户显式关闭结束 |
| 普通权限确认 | `PENDING_PANEL_TTL_SECONDS = 180.0` | `:26` |
| 危险操作（reason/matched_rule 命中 `danger`/`secret`/`protected`） | `PENDING_DANGER_TTL_SECONDS = 60.0` | `:27,32` |
| 到期前提醒 | `PENDING_REMINDER_BEFORE_S = 30.0` | `:28` |

**危险操作给更短的 TTL**——这条反直觉但正确：危险操作不应该在屏幕上停三分钟等人误点。

### 生命周期算法

```
request (:56-114)
 ├─ store.create → 风险分级 TTL → PendingPermission + asyncio.Event
 ├─ task_state.set_status("waiting_permission", interruptible=False)
 ├─ audit_log.record("permission.pending", ...)
 └─ emit PermissionPendingEvent（含 intent_for(choices) → choice|confirm）

wait (:137-...)
 ├─ 起 _remind_before_expiry 协程（到期前 30s 推 PermissionExpiringEvent）
 ├─ await asyncio.wait_for(ev.wait(), timeout=expires_at-now)
 └─ 返回 allow / deny / remind / timeout

resolve (:136-183)
 ├─ 幂等：item.resolved 已 True → return False
 ├─ choice 合法则按 choice；否则按 approved 推导
 ├─ ev.set()（唤醒 wait）
 └─ audit_log.record("permission.resolved", approved/user_choice/actor/outcome)
```

### abort 时的唤醒（`:185-206`）

注释点出一个不显眼的坑：

> abort 不会唤醒挂在 `wait` 上的 `asyncio.Event`——回合等待审批时点停止，租约要等面板 TTL（180s）到期才释放。interrupt 路径调用本方法让等待者即刻返回。

所以 `cancel_pending_for_session` 把该会话所有未决请求按"已取消（拒绝）"处理并 `ev.set()`，`outcome="aborted"`。

### 面向模型的三态文案（`pending_ttl.py:29-42`）

| 常量 | 触发 |
|---|---|
| `REJECTED_COPY` | 用户显式拒绝 |
| `CANCELLED_COPY` | 面板关闭 / Esc / 停止（`outcome=aborted`） |
| `UNAVAILABLE_COPY` | 超时或协调器缺失 |

注意 `REJECTED_COPY` 的措辞：*"Permission denied: the user explicitly rejected this action. Do not retry the same call; adjust the approach or ask the user."* —— 这是**结果型**表述（拒绝是事实 + 不重试是可执行约束），不是劝导。

### 审计配对

`pending_ttl.py:18-19` 明写：*"审计配对：`permission.pending` ↔ `permission.resolved`（allow/deny 都记），即计划中的 `approval.asked/decided` 对——命名以 `permission.*` 为准，不再双写。"*

### 对照提示

dsh 的审批（A-6）是**封闭四值 + 唯一授予值 `allowed-once` + 无 answerer 即 `unavailable`（fail-closed）**，且把审批策略写成**动态 context 而不写事件**以保缓存前缀。XEYO 是**三态（含 remind）+ 可复用 grant + 风险分级 TTL + 审计配对**。dsh 的设计目标是"结构上不可能过度授权"，XEYO 的设计目标是"确认频率可调且授权可复用"——**前者的失败模式是"太啰嗦"，后者的失败模式是"太宽松"，两端各自把失败模式选在了自己更能承受的一侧。**

---

## B-7 rewind v2：内容寻址 + 事件日志 + 括号事务

### 设计意图

`rewind/models.py:1-8` 的模块 docstring 是这套设计的纲领：

```
Durable data contracts for enterprise rewind.

These models deliberately contain metadata and content-addressed references,
not raw file bodies.  File bodies belong to a snapshot store introduced by the
operation-integration phase.  Keeping the contracts as dataclasses makes them
compatible with XEYO's existing JSONL persistence style without coupling the
backend to Pydantic or the GUI.
```

三个决策写在第一段：**契约里只有元数据与内容寻址引用**（文件体不进 JSONL）、**用 dataclass 不用 Pydantic**（不耦合后端与 GUI）、**沿用 JSONL 风格**。

### 八个数据契约（`models.py:74-221`）

| 契约 | 关键字段 | 语义 |
|---|---|---|
| `SessionRevision` | `parent_revision_id` / `turn_ids` / `message_ids` / `transcript_hash` | 不可变的时间点视图（**有 parent → 天然成树**） |
| `TurnRecord` | `status` / `operation_ids` / `stop_reason` | 一次用户提交引发的全部工作 |
| `OperationRecord` | `before_hash` / `after_hash` / `inverse_kind` / `inverse_payload` | 一次可逆变更（`inverse_payload` 只含引用与参数） |
| `SnapshotManifest` | `content_hash` / `size_bytes` / `line_endings` / `storage_path` | 内容寻址快照的元数据 |
| `RollbackPlan` | `plan_hash` / `conflicts` / `requires_confirmation` | dry-run 结果，绑定源 revision 与不可变 plan hash |
| `ApprovalRecord` | `plan_id` + `plan_hash` + `decision` | **对某一个确切 plan hash** 的显式批准 |
| `RecoveryJob` | `idempotency_key` / `applied_operation_ids` / `status` | 可幂等寻址的执行态 |
| `AuditEvent` | `event_type` / `actor` / `revision_id` / `turn_id` | 追加式审计 |

契约注释里两处拒止值得记：`OperationRecord` 的 *"It must never be populated with complete file contents"*（`:117-119`），`SnapshotStore` 的 *"A snapshot manifest is returned even when the content already exists, so journal entries can retain stable references without copying file contents into JSONL"*（`snapshot.py:18-20`）。

### 快照存储：原子 + 幂等 + 校验读（`rewind/snapshot.py`）

`put_bytes`（`:39-79`）算法：

```
1. 未启用 → None（不产生半态）
2. content_hash = sha256(data).hexdigest()
3. target = root / content_hash；已存在 → 直接返回 manifest（幂等，不重写）
4. 否则：mkstemp 同目录 → write + flush + fsync → os.replace → 异常时 unlink 临时文件
```

`get_bytes`（`:99-109`）**读时重算哈希并比对**：*"snapshot hash mismatch: expected X, got Y"* —— 磁盘损坏不会被静默吞掉。

### 操作日志：追加式状态机 + latest-wins 折叠（`rewind/journal.py`）

两张转移表（`:28-39`）是硬约束，非法转移直接抛：

```python
_OPERATION_TRANSITIONS = {
    "started":   frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
}
_TURN_TRANSITIONS = {
    "running":   frozenset({"committed", "failed", "aborted"}),
    "committed": frozenset(), "failed": frozenset(), "aborted": frozenset(),
}
```

`:203-204`：`raise ValueError(f"invalid operation transition {current.status!r} -> {status!r}")` —— **终态不可复活**。

追加实现（`:70-81`）：一行 JSON + `flush`，**fsync 默认关**，理由写在 `:64-65`：

> 每次 append 后 fsync；默认关闭（flush 已保证进程内顺序完整，读端本就容忍 partial line）。审计要求落盘即持久时设 `XEYO_REWIND_FSYNC=1`。

读侧容忍坏行（`:101-110`）：*"进程被杀可能留下最后一行残页：解析失败的行直接跳过即可，无需（也不应该）为每个坏行重新打开文件数总行数。"*

读缓存按 `(path, mtime_ns, size)` 键（`:123`），上限 64 条后整体清空（`:130-131`）——缓存键含 mtime+size，所以**写后必失效**，不会读到旧态。

### revision 树：truncate 不删旧记录（`rewind/revision.py:175-209`）

```python
def truncate_to(self, target_revision_id, *, metadata=None) -> SessionRevision:
    """Create a new head containing exactly the selected target revision.
    Existing records are never deleted.  The new revision is a branch from
    the target and carries a reason in metadata, which makes a later
    rollback auditable and permits recovery if execution fails."""
```

这是"回溯"与"删除"的分界线：**回溯 = 从目标点再开一个分支**，旧 revision 永久留在树里。与 dsh 的 fork（A-11）在**语义上相通**（都是"从某点分叉"），但 XEYO 分叉的是 **revision**，dsh 分叉的是 **session**。

### 检查点：消息发出瞬间的 blob 图（`rewind/index.py`）

`FileCheckpoint`（`:191-198`）是 `path → content_hash` 的 COW 图；id 由 `_hash_entries`（`:215-220`）生成：

```python
digest.update(f"{session_id}|{user_message_id}".encode())
for path in sorted(entries):
    digest.update(f"{path}:{entries[path]}".encode())
return f"cp3_{digest.hexdigest()[:32]}"
```

`cp3_` 前缀 + 排序保证**同 (session, message, 图) 幂等**——`freeze_checkpoint`（`:223-262`）先查再写。

路径归一化有一处防坑注释（`:206-208`）：

> 不能用 `lstrip("./")`：那是按字符集剥离，会把根目录点文件 `.gitignore`/`.env` 改写成 `gitignore`/`env`，restore/undo 落到错误路径。

### 三把锁（`rewind/locks.py`）

| 类 | 语义 | 关键 |
|---|---|---|
| `ResourceLease` | 进程内短期租约，TTL 默认 300s | `validate()` 检查 released + 过期 + lease_id 仍是当前（`:56-64`）——**三重校验** |
| `ProcessWorkspaceLock` | 工作区作用域租约 | `:135-138` 命名去混淆注释：跨进程锁是 `engine.workspace_lock.WorkspaceLock`，**两者不可混用** |
| `SessionLock` | 会话作用域租约 | 与 chat busy lease 独立 |

`release()` 的防御（`:73-78`）值得记：`self._state.lock.release()` 包 try/except RuntimeError，注释 *"防御性：获取失败或进程关闭时，清理绝不能变成第二次失败"*。

### Turn 上下文：contextvars 传播（`rewind/context.py`）

`RewindExecutionContext`（`:21-95`）用 `contextvars` 传播到并发工具任务（注释 `:25-27`：*"can be propagated to concurrently executed tool tasks through contextvars. Operation IDs are collected in call-completion order; the journal itself remains the source of truth."*）。

`record_file_mutation`（`:41-95`）的核心是"**先写快照再写日志，任一失败即抛**"：

```python
before_manifest = self.snapshots.put_text(old_content, ...) if existed_before else None
after_manifest  = self.snapshots.put_text(new_content, ...)
if after_manifest is None or (existed_before and before_manifest is None):
    raise RuntimeError("rewind snapshot persistence failed")
record = self.journal.start_operation(..., inverse_kind="restore_snapshot" if existed_before else "delete_file", ...)
if record is None:
    raise RuntimeError("rewind operation journal is disabled")
completed = self.journal.transition_operation(record.operation_id, "completed")
if completed is None:
    raise RuntimeError("rewind operation transition was not persisted")
```

`inverse_kind` 只有两个值：`restore_snapshot`（文件本来存在 → 恢复旧内容）/ `delete_file`（文件本不存在 → 删除）。**"删除"是一个明确的逆操作，不是一个默认行为**。

### 回滚服务四段（`rewind/service.py`，1800 行）

| 阶段 | 入口 | 关键约束 |
|---|---|---|
| `preview` | `:768-983` | dry-run；`plan_hash` 由 payload 计算（`:743-747`）；不落任何变更 |
| `_check_file_preconditions` | `:649-700` | **simulated 状态机**逐 op 模拟；`after_hash` 必须等于磁盘现状，否则 conflict |
| `execute` | `:1363-1694` | 要求 `plan_id` + `plan_hash` + `idempotency_key` + `confirmed` 四件套（`:1377-1400`） |
| `resolve_recovery` | `:1695-1760` | `retry_checkpoint` / `abandon` 二选一；abandon 走 `WorkspaceRestoreTransaction.reconcile()` |

`_check_file_preconditions` 的逐 op 校验链（`:656-697`）：

```
1. 路径缺失 → conflict
2. _safe_path 越界 → RollbackBlockedError → conflict
3. symlink → conflict（明确不支持）
4. state.exists != (after_hash is not None) 或哈希不符 → conflict
5. inverse_kind 不在 {restore_snapshot, delete_file} → conflict（不可逆）
6. restore_snapshot 但无 before_hash → conflict（旧快照丢失）
7. delete_file 但 after_exists 为假 → conflict
8. status != "completed" → conflict
9. 通过 → simulated[path] = 反向状态（供下一个 op 校验链式效果）
```

**第 9 步是这套校验的精髓**：同一批 ops 里前面 op 的效果会反映到后面的前置校验里，所以"预览通过"和"执行成功"是同一个状态机推导出来的。

### 对照提示

dsh 没有"回滚工作区文件"这套东西——它的可逆性建立在**会话日志**上（回溯 = 换一个 surface 投影），而不是**工作区内容寻址**上。这是两端最本质的能力错位：**dsh 能撤销"对话"，XEYO 能撤销"对磁盘做的事"。** 对编码 Agent 来说后者更贵也更难，XEYO 在这块投入了 12 个文件 5343 行。

---

## B-8 rewind v3 热路径：崩溃顺序合同 + orphan 先落盘

### 设计意图

`rewind/hotpath.py:1-13` 整段是设计自陈：

```
回溯 v3 热路径事务：``POST /rewind`` 的 orphan → 原子重写 → 异步恢复。

崩溃顺序合同：**orphan → fsync → 原子替换 transcript → 再改工作区**。

- ``continue``：整轮（target user 消息及其回复/工具轨迹）写入
  ``orphans/{rewind_id}.jsonl``，随后原子重写 transcript 前缀；工作区恢复
  在后台线程执行，恢复前逐文件记录 ``pre_rewind_index`` 供 Undo。
- ``restore``：不改 transcript，仅后台恢复文件 + 审计。
- Undo：orphan 追加回 transcript + 按 ``pre_rewind_index`` 写回文件；
  有新消息落盘或路径被再次修改时拒绝/跳过（评审 #5）。

不依赖 shadow-git、不走 preview。v2 ``rewind.service`` 保持原样作降级路径。
```

**"崩溃顺序合同"是这套机制的灵魂**：写盘顺序被设计成"无论在哪一步崩溃，系统都停在一个可解释的状态"。orphan 先落盘 → 即使随后崩溃，那一轮对话已可找回。

### 一个重要的实现演进（`:427-430`）

```
replace 事件化（46 号）：读合并日志（含轮转归档）→ surface fold →
在「模型可见面」中定位 target → 追加一条 rewind marker。
transcript 永不重写、不落 orphan；被回溯行留在原文件被影子化，
崩溃最坏结果是 marker 半行写坏被读侧跳过 = 回溯视为未发生。
```

**v3.1 已经不再重写 transcript 了**（尽管文件头注释仍描述旧合同）——改为追加一条 marker 行，由 surface fold 在读取时生效。崩溃最坏结果从"transcript 损坏"降级为"回溯未发生"。这是"崩溃合同"再收紧一档：**从"可恢复"进化到"崩溃即无事发生"**。

### 状态机

```
continue:  transcript_committed ──┐
restore:   restoring ─────────────┴→ committed / partial / recovery_required / failed
```

`_spawn_restore`（`:530-560`）处理**没有 checkpoint 的情况**，注释（`:535-542`）写得非常具体：

> 无 checkpoint 也必须给终态：事件停在 `transcript_committed`/`restoring` 会让前端 `pollSettled` 只能等超时（然后误判「未确认」并回滚列表）。
> - continue：对话确实截断了，但**没有文件检查点**可恢复。不能置 committed（前端会当作「文件已恢复」而给误导文案）；置 `partial` + `no_checkpoint` 标记，让前端明确提示「仅截断对话，文件未回滚」。
> - restore：没有可恢复对象 → `failed`。

**"每个状态都必须是前端可渲染的终态"** —— 这是把 UI 语义当成状态机约束来设计的写法。

### 崩溃恢复：启动扫描 + 对账（`:180-212`, `:215-302`）

```python
IN_FLIGHT_REWIND_STATUSES = frozenset({"transcript_committed", "restoring"})

def mark_crashed_rewinds(sessions_dir=None) -> int:
    """启动扫描：把「进行中但未达终态」的 rewind 事件标记为 recovery_required（§9.2）。
    进程崩溃会打断后台恢复线程，transcript 已提交、工作区可能处于中间态。
    重启后把这些 in-flight 事件提升为可处理状态（重试/放弃），避免被当作已完成。"""
```

外加 `_reconcile_orphan_surface_markers`（`:215-226`）处理一个更细的**半写坏**：

> transcript 里有 rewind marker、事件文件却没有对应事件。marker 追加成功但事件落盘前崩溃 → 该回溯在 fold 生效却无 pill/undo 入口。为其合成 `transcript_committed` 事件，让对话层有可撤销入口。

**这是"两个持久物之间的对账"**：marker 与 event 是两次独立写盘，中间崩溃会产生"生效但不可撤销"的状态，启动扫描把它补成一个合法终态。

### 并发：按会话串行闸（`:45-50`, `:561-574`）

```python
#: 后台文件恢复 worker 的按会话串行闸：两个 restore 并发写同一工作区
#: 会产生混合终态、且后提交者的 pre_rewind_index 会拍到前者的中间态。
_RESTORE_LOCKS: dict[str, threading.Lock] = {}
```

`_restore_worker` 包 `_restore_lock_for(self.session_id)`，注释点出后果：*"undo 的哈希守卫还会把混合态判 `skipped_dirty`"*——即**串行不是为了性能正确，是为了语义正确**。

### 终态判定（`:593-602`）

```python
skipped = report.get("skipped_dirty") or []
failures = report.get("failed") or []
if failures:      status = "recovery_required"   # 部分文件未恢复 → 工作区中间态
elif skipped:     status = "partial"             # 仅用户手改路径被跳过（预期行为）
else:             status = "committed"
```

**"用户手改过"被归为正常终态（partial），"恢复失败"才是异常（recovery_required）** —— 引擎尊重并发的人工修改，不把它当故障。

### 一个数据丢失防线（`:613-620`）

`_journal_before_hash` 的注释记录了一个已修的真实 BUG：

> 删除分支的防御（BUG-1 数据丢失）：一个检查点冻结前**从未被索引、但本轮被 agent 首次修改**的既有用户文件，不在 `checkpoint.entries`、却在 `index.entries`，会落入删除分支被 `unlink`。这类文件在 mutation 时 `existed_before=True`，journal 里 `before_hash` 非空（`inverse_kind='restore_snapshot'`）。凡是存在此类记录，就应**恢复 before 内容**而非删除。

这是"两个索引不一致时，优先相信更保守的那个"的实例——防的是一个真实的删用户文件事故。

### 对照提示

dsh 侧没有工作区回溯，但它的 A-2 崩溃恢复（`interruptedTurnClosers`）与 B-8 是**同构问题**：都要求"崩溃后的尾巴能被补成合法结构"。差别在修复对象——dsh 补的是**会话日志的对话结构**，XEYO 补的是**工作区文件 + transcript 的双向一致**。

---

## B-9 rewind 存储回收：可达性 + 预算驱动 + dry-run 永不触盘

### 设计意图

内容寻址库只增不减，必须回收。但回收的风险是删掉仍被引用的 blob（回溯就废了）。XEYO 的答案：**先算可达集，再只在超预算时删不可达项**。

### 可达性计算（`rewind/blob_gc.py:305-370`）

```python
def collect_reachable_blobs(sessions_root=None, *, keep_recent=None) -> set[str]:
    """跨会话把「仍被任何 rewind 记录引用的 blob 哈希」收集成集合。

    - ``keep_recent`` 为空 → 最保守：任何 rewind 记录引用的都算可达。
    - ``keep_recent`` 给定 → 按「最近 N turn + 基线 + 锚点 turn」划分保留集：
      - operations 只计保留 turn 内（否则按 turn 老化）；
      - checkpoints 只计保留 user 消息（否则按 checkpoint-id 保留）；
      - ``agent_file_index`` / ``rewind_events`` / ``orphans`` 仍**全量**保留（安全兜底）。
    """
```

**安全兜底的设计值得记**：`agent_file_index` / `rewind_events` / `orphans` 三类**永远全量保留**，无论 `keep_recent` 多小。因为这三类是"撤销/恢复的安全底座"（`:326` 注释）。

### GC 算法（`:410-488`）

```
1. 读开关：enabled（XEYO_BLOB_GC_ENABLED，默认 False）
           dry_run（XEYO_BLOB_GC_DRY_RUN，默认 True）
           max_bytes / keep_recent（配置文件 > 环境变量）
2. 枚举快照目录（只认 64 位 sha256 文件名，忽略临时文件）
3. reachable = collect_reachable_blobs(...)
4. deletable = blobs - reachable，按 (mtime, hash) 排序（最旧优先）
5. if not enabled:        return result          # 只报告
6. if 未超预算:            return result          # 保守，有不可达也不清
7. if dry_run:            return result          # 绝不触盘
8. 按 mtime 最旧优先删除，直到 freed_bytes >= need_to_free
```

`:471-472` 注释记录了一个真实事故：

> dry_run=True：deletable/over_budget 已在 result 中（报告面），不计 deleted、**绝不触盘（曾经漏判 dr 导致真删——`test_dry_run_and_disabled_never_delete` 钉死）**。

**三重默认安全**：`enabled=False` + `dry_run=True` + "未超预算不动手"。要真删必须同时满足三个条件——这是"删除类机制"应有的默认姿态。

### 对照提示

dsh 侧没有等价的 blob 生命周期管理（它的 spill 文件是会话作用域且无跨会话回收需求）。这条机制是**内容寻址存储的必然配套**，XEYO 这里做得比多数实现保守（默认三重关）。

---

## B-10 影子 git 与工作区指纹：只读元数据，不读内容

### 设计意图

要判断"工作区在 preview 与 execute 之间有没有被改动"，需要一个指纹。XEYO 的选择是**只用元数据**（`engine/workspace_revision.py:11-20`）：

```python
class WorkspaceRevision:
    """Calculate a conservative, metadata-only workspace fingerprint.

    When ``paths`` is provided, only those relative paths are fingerprinted
    (plus shadow HEAD).  That keeps Vite/test churn outside the rollback plan
    from invalidating ``expected_workspace_revision``.

    Without ``paths``, git status identifies changed paths and we add ``lstat``
    metadata rather than reading file contents.
    """
```

**"不读文件内容"是刻意的**：大工作区全量读内容成本不可接受，而 lstat 元数据足以检测"变了没有"。

### 指纹 token（`:47-74`）

```python
return (
    f"{status}\0{relative.as_posix()}\0{kind}\0{stat.st_size}"
    f"\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_mode}"
)
```

七段：git status / 相对路径 / 类型（file|directory|symlink:target）/ size / mtime_ns / ctime_ns / st_mode。`\0` 分隔防拼接歧义。`kind` 对 symlink 记 `symlink:<target>`——**符号链接目标变化也算变化**。

`calculate`（`:76-109`）的语义分档：

- `paths=()`（空可迭代）→ **只指纹 shadow HEAD**——*"suitable for chat-only rollback where unrelated worktree noise must not block"*
- `paths=None` → 保留旧的 full porcelain 指纹
- `paths=[...]` → 只指纹指定路径 + HEAD

返回 `rev_<sha256[:16]>`（`:109`）。

### 影子 git（`engine/shadow_git.py`）

独立 `GIT_DIR=.xy-shadow-git` + `GIT_WORK_TREE=<workspace>`（`:82-84`），**不污染用户的 `.git`**。`init_if_needed`（`:94-116`）配置 `core.autocrlf=false` + `core.ignorecase=true`，并把 `.xy-shadow-git/`、`.xy-trash/` 写进 `info/exclude`，同时更新用户主 git 的 exclude（`:118-120`）。

一处很实在的工程细节（`:12-26`）：

```python
def decode_git_bytes(data: bytes) -> str:
    """Decode git stdout/stderr without locking to a single codec.
    Modern git often emits UTF-8 paths, but Windows locales (GBK/cp936) and
    older tooling may emit other encodings. Try strict candidates in order;
    fall back to UTF-8 with surrogateescape so restore never sees empty trees."""
```

`_git_text_encodings`（`:29-51`）构造候选序列：utf-8 → locale 首选编码 → gb18030 → gbk → cp936 → mbcs → cp1252 → latin-1，最后兜底 surrogateescape。**"绝不空树"**是这条兜底的验收标准——编码问题不能导致备份内容丢失。

### 对照提示

dsh 没有"影子 git + 工作区指纹"这套东西（它的版本化完全在会话日志侧）。XEYO 这里是**双轨版本化**：会话侧 `rewind`（内容寻址）+ 工作区侧 `shadow_git`（git 对象），两条轨服务于不同的恢复场景。

---

## B-11 写入通道：每文件单写者 + 内容哈希版本校验 + 未读拒绝

### 设计意图

`engine/write_store.py:1-9` 的模块 docstring 是完整设计陈述：

```
每文件单写者写路径（write-through store）。

设计（多 Agent 协同落地 #29 §2.1）：
- **每文件一把锁**：同文件串行 apply，不同文件可并行（submit 走 to_thread）。
- **content-hash 版本校验**：base vs 磁盘哈希，不一致 -> stale，不覆盖。
- **原子写**：temp + os.replace。
- **P0 单文件事务**；多文件走 _apply_multi 预检。
- **语法校验**：Python/JSON 增量（新文件引入错误才记 syntax_valid=false）。
```

### 分片锁：一个内存有界的修正（`:170-180`）

```python
def __init__(self, root, *, shards: int = 64) -> None:
    self._shards = max(1, shards)
    # 分片锁：路径哈希映射到固定数量的锁。曾按"每文件一把锁"实现，
    # 锁表只增不减（长会话内存无界）；分片同样保证同文件串行。
    self._shard_locks = [threading.Lock() for _ in range(self._shards)]

def _lock_for(self, path: str) -> threading.Lock:
    return self._shard_locks[hash(path) % self._shards]
```

**"曾经每文件一把锁"是一个真实的内存泄漏**，改为 64 分片——同文件仍然串行（同路径必同分片），锁表有界。

### 写路径的三道门

| 门 | 位置 | 行为 |
|---|---|---|
| 路径越界 | `_canon`（`:198-216`） | `relative_to(self._root)` 失败 → `PermissionError` |
| 写作用域 | `_canon` 内调 `write_scope_deny_reason` | 子 Agent 沙箱二次硬门禁 |
| 版本校验 | `_apply_core`（`:236-285`） | base ≠ current → `stale`；有文件但 base 空 → `missing_read` |

`missing_read` 的措辞正是 AGENTS.md 里点名的中性结果型（`:284`）：

```
"missing_read: no prior Read for this path in this session"
```

**"未读拒绝"这条机制的设计意图很清楚**：防的不是"模型看不到内容"，而是"模型基于过期理解盲写覆盖"。所以拒绝理由要给出可核实的事实（本会话没有该路径的 Read 记录），而不是警告。

### 原子写（`:399-422`）

```python
tmp = path.with_name(path.name + ".xeyo.write.tmp")
write_encoding = encoding or "utf-8"
if write_encoding == "utf-16-le":
    data = b"\xff\xfe" + content.encode("utf-16-le")   # BOM 特殊处理
else:
    data = content.encode(write_encoding, errors="replace")
try:
    with open(tmp, "wb") as handle: handle.write(data)
    os.replace(tmp, path)
except OSError:
    try:
        if tmp.exists(): tmp.unlink()                  # Windows 目标被占用是常态，不留垃圾
    except OSError: pass
    raise
```

注释（`:403-405`）说明为什么不复用 `write_text_file`：*"绕过它的 line_endings 逻辑：换行形态由调用方在 content 里定稿，此处只做原子替换，禁止平台翻译。"*

### 编辑应用：与 Read 同源的归一化（`:433-449`）

```python
# 与 Read 同源的归一化文本：模型的 old_string 来自 Read（CRLF→LF），
# 若按原始字节读盘，CRLF 文件的 old_string 永远匹配不上 → 假 conflict。
content, _endings, _enc = read_text_file(str(path))
```

**"读与写必须走同一个归一化"**——否则 CRLF 文件永远冲突。

### journal 失败不阻断写（`:313-327`）

```python
# journal 只是审计：文件已成功落盘，记录失败不得让工具报错——
# 否则调用方 read_state 不更新，下一轮反而误报 modified-since-read。
# T28：但「假 ok」不可接受——显式记日志并把警示带回工具结果。
```

于是 `ApplyResult` 带 `journal_warning`，文案是事实陈述（`:324-327`）：*"本次写操作已落盘但未进入可回溯日志"*。

### 对照提示

dsh 的文件写入走 fs seam（A-6 的 `fs/policy`），策略由 seam 提供、沙箱兜底；XEYO 的写入走 `WriteStore` 单点，**自己实现版本校验、原子性、审计**。XEYO 这条路径的设计密度更高（三道门 + 版本校验 + 语法增量），但那是因为它没有沙箱——**所有安全责任都在这一层**。而 AGENTS.md 记的另一件事是：这条通道**并非唯一**，`server/workspace_fs.py` 与后台 bash job 是绕开它的旁路。

---

## B-12 预算与收尾窗口：多软上限共享一个 grace

### 设计意图

`engine/budget.py:1-6` 先定义了度量单位：

```
一次 submit 内，一次 Turn = 一次模型 API 请求/响应周期。
每一次实际进入 Agent tool interface 的工具执行尝试 = 1 个 Tool Call。
同一 Turn 可以包含多个 Tool Call；Tool Call 不会自动增加 Turn。
```

`BudgetTracker` 的 docstring（`:102-112`）说明了核心机制：

> 任一软上限首次触发后建立共享的 `MAX_GRACE_TURNS` 模型 Turn 收尾窗口，只发送一次对应的临时提醒，不写入消息历史。两个上限不会各自再提供一组 grace Turn；用户中断、token 和 USD 预算仍然优先硬停止。

**"共享一个 grace 窗口"是关键**：如果每个上限各自给 3 轮，三个上限触发就是 9 轮。共享之后收尾窗口恒定。

### 常量（`:19-34`）

| 常量 | 值 | 说明 |
|---|---|---|
| `DEFAULT_MAX_TURNS` | 256 | 模型 API 请求次数上限 |
| `DEFAULT_MAX_TOOL_CALLING` | 64 | 每回合进入工具接口的执行次数（**并发上限另由编排层信号量 10 控制**，`:20-23`） |
| `MAX_GRACE_TURNS` | 3 | 共享收尾窗口长度 |
| `MAX_TOOL_CAP_STREAK` | 2 | 连续顶满才算失控（见下） |

### grace-cliff 修复（`:26-30`, `:289-300`）

注释是这次修复的完整记录：

```
工具态共享收尾窗口的触发：先前只要单轮爆发(一个大并行批次)达到单轮工具
配额就立刻开启 3 轮倒计时，会把整个 submit 的剩余轮次烧光(grace-cliff)。
现改为"连续 MAX_TOOL_CAP_STREAK 轮持续顶满/超出单轮配额"才进入收尾，单轮
爆发只拒绝溢出调用、不影响整轮窗口；单轮配额依然按每回合重置。
```

实现：

```python
if self._turn_hit_tool_cap:
    self.tool_cap_streak += 1
else:
    self.tool_cap_streak = 0
self._turn_hit_tool_cap = False
self.turn_count += 1
self.current_turn_tool_calls = 0
if not self.grace_started and self.tool_cap_streak >= MAX_TOOL_CAP_STREAK:
    self._start_grace("max_tool_calling")
```

**"单轮爆发不是失控，连续两轮才是"** —— 这是把"失控"定义从"瞬时强度"改成"持续性"。

### 墙钟与 USD 水位（`:148-249`）

两条正交的时间/成本感知：

| 机制 | 阈值 | 默认 |
|---|---|---|
| 墙钟 | 80% / 90% 播报；100% + `wall_hard_stop` 才进 grace | `wall_hard_stop` 默认 False（`XEYO_WALL_HARD_STOP=1` 才武装，`:37-44`） |
| USD | 80% / 90% 播报 | `usd_limit` 为正才武装 |

`:171-173` 注释：*"产品会话即使设了死线（仅时间感播报）也不会被引擎硬停；只有宿主显式要求'到点收尾'（评测适配器/用户时间预算）才生效。"*

播报文案刻意是纯事实（`:192-193`）：*"时间预算已用 {label}，剩余约 {remain_min} 分钟。"* + 注释 *"C6 裁决：预算信息纯事实，不加行动指令。"*

### 硬停返回（`:267-279`）

```python
if self.grace_started:
    if self.turn_count >= self.max_turns: self._queue_notice("max_turns")
    if self.grace_turns_used < MAX_GRACE_TURNS: return True
    self._hard_stop_reason = self.grace_reason or "max_turns"
    return False
if self.turn_count < self.max_turns: return True
self._start_grace("max_turns")
return True
```

注意 `prepare_next_turn` **不增加 Turn 计数**（`:253-255`：*"该方法不增加 Turn。只有真正调用 `begin_turn` 时才会计入"*）——判定与计数分离，避免"判定失败也消耗轮次"。

### 对照提示

dsh 侧有 workspace 级的 request budget（用于 compaction/spill 的 token 预算），但**没有"回合/工具调用/墙钟/USD"这类会话级执行预算**。XEYO 这套机制的存在理由很直接：**要能对一次长任务给出"什么时候该收尾"的确定性判定**，并且这个判定必须是引擎侧、不依赖模型自觉。

---

## B-13 成本账本：按真实厂商计价 + 请求级归因

### 设计意图

`usage/pricing.py:1-9` 的 docstring 记录了口径与两个易错点：

```
按厂商 / 模型估算消费金额（人民币）。

DeepSeek V4 官方价（2026-08-17 起，元 / 百万 token）：
  高峰 09:00–12:00、14:00–18:00（北京时间）；空闲 = 高峰 × 1/2。
  flash 空闲 命中 0.05 / 未命中 1.5 / 输出 4.5；高峰 0.10 / 3.0 / 9.0
  pro   空闲 命中 0.15 / 未命中 4.5 / 输出 13.5；高峰 0.30 / 9.0 / 27.0
```

数据表（`:26-29`）：`_DEEPSEEK = {"flash": ((0.05,1.5,4.5),(0.10,3.0,9.0)), "pro": (...)}` —— 外层是低峰/高峰两档，内层是 `(cache_hit, cache_miss, output)`。

峰谷配置（`:51-58`）可用 `XEYO_TIME_TIERS_JSON` 整体覆盖，注释说明理由（`:49`）：*"厂商改窗口或折扣不用发版"*。

### 账本事件（`usage/ledger.py:99-130`）

字段分两段：**基础段**（每次都写）与 **schema v2 归因段**（仅 `request_id` 非空时写）。

基础段：

| 字段 | 说明 |
|---|---|
| `ts` / `day` | 时间戳 + 北京时区日（跨天聚合用） |
| `provider` | **接入通道**（deepseek/openai preset），保持"通道"语义 |
| `vendor` | **模型真实厂商**（`canonical_vendor`） |
| `model` / `session_id` / `key_fp` | 定位 |
| `prompt_tokens` / `completion_tokens` / `cache_hit` / `cache_miss` / `output` / `tokens` | 四桶 + 合计 |
| `cost_cny` / `cost_source` | 金额 + 来源（`api` 或 `estimate`） |

归因段（`:116-129`）：`request_id` / `attempt` / `kind` / `cache_write` / `reasoning_tokens`。

`provider` 与 `vendor` 分离的理由写在 `:63-64`：*"统计 / 计价 / 分组一律按 vendor —— 修 P0-1（provider 与模型错位导致套错价目与分组错乱）"*。

### 记账纪律（`:66-76`，注释原文）

```
对齐 DeepSeek Harness 记账纪律（v4 设计，S2/S4）：
- ``request_id``：逻辑模型调用唯一 id（engine 在每个请求前生成，跨 attempt 不变）。
  **只在 request_id 非空时**才把 request_id/attempt/kind 写进行——其余调用点
  （CLI/评测/无 meta 场景）保持旧行结构，零扰动。
- ``attempt``：同一逻辑调用的第几次尝试（dsh S4：重试 attempt 各自入账——
  provider 对每次 HTTP 请求独立计费，死 attempt 若真的烧了 token 就该留下）。
- ``kind``：回合类型。``turn`` 主循环；``compact_summary`` C2 LLM 摘要旁路
  （dsh D-3 教训：压缩走模型的调用必须可归因、不得静默消失）。
- 每个 ``stream()`` 内的双写防御由模型适配器 ``_usage_recorded_this_stream``
  布尔完成（同一次尝试只记一次 = dsh S2 的流内单结算）。
```

**这段注释是罕见的"跨项目对齐"痕迹**：XEYO 明确引用了 dsh 的 S2/S4/D-3 条目来校准自己的记账纪律。这跟前四轮"两端对着干"的印象不同——在成本记账这一块，XEYO 主动向 dsh 学了两条（重试各自入账、压缩调用可归因）。

### 记账优先链（`:89-98`）

```python
api_cost = official_cost_cny(usage)
if api_cost is not None:
    cost_cny = api_cost; cost_source = "api"        # API 返回金额直接采用
else:
    cost_cny = estimate_cny(provider=vendor, model=model, usage=usage, ts=now)
    cost_source = "estimate"                        # 本地价表估算
```

**"API 说多少就是多少"优先于本地估算** —— 本地价表只在 API 不给金额时兜底。这解释了 `:44-46` 那条边界注释：*"usage 自带金额直接采用，不经过这里"*。

### 容量与聚合

`_MAX_LINES = 80_000`（`:16`）——事件文件上限，超出后由聚合侧处理。追加实现（`:133-139`）用 `_lock` + append，不做 fsync（成本记账可容忍丢最后一行）。

### 对照提示

dsh 侧有 token 计量与 compaction 的影子计价（A-9 `region.ts:340-364`），但**没有成本金额统计、没有峰谷价、没有请求级归因、没有四桶分离**。XEYO 这套（pricing/ledger/attribution 三文件 + 8 万行上限 + 峰谷可配置）是**运营性资产**：它服务于"这个产品跑起来有多贵"这个只有产品方关心的问题。**注意 `usage/pricing.py` 当前仍是 2026-08-17 价表，尚未同步新价**（第四轮已记，本轮维持）。

---

# Part C — 机制对照矩阵

## C-1 同构问题：两端在解同一道题，答案不同

下面六组机制**解的其实是同一道题**，但两端的答案在结构层就分岔了。这是本轮最核心的产出——前面四轮比的是"有什么 / 怎么设计 / 什么字段"，本轮比的是"同一个问题两边怎么解"。

### ① 崩溃后的尾巴怎么办

| | dsh（A-2） | XEYO（B-8） |
|---|---|---|
| 机制名 | `interruptedTurnClosers(events)` | `mark_crashed_rewinds` + `_reconcile_orphan_surface_markers` |
| 处理对象 | 会话日志的**对话结构** | 工作区文件 + transcript 的**双向一致** |
| 手段 | **合成闭合事件**（补一个合法的 turn 结尾） | **状态提升 + 事件合成**（in-flight → `recovery_required`；marker 无事件 → 补 `transcript_committed`） |
| 崩溃语义 | "崩溃尾不算数据损坏" | "崩溃最坏结果 = 这件事没发生过"（v3.1 marker 化后） |
| 用户可见 | 不需要（自动修复） | 需要（`recovery_required` 要用户选 retry/abandon） |

**分歧点**：dsh 自动补齐就够了，因为它的"坏尾"只影响模型上下文；XEYO 的"坏尾"可能意味着磁盘处于中间态，引擎**不能替用户决定**是重试还是放弃。

### ② 易变内容如何进上下文而不破坏缓存

| | dsh（A-5） | XEYO（B-1/B-2） |
|---|---|---|
| 载体 | 可替换的 **user 消息** | 伪造的 **assistant(tool_use) → user(tool_result) 对** |
| 变更语义 | **差异才发 + 被替换即撤销** | **每轮重建 + 尾插只增** |
| 保护缓存的机制 | 内容替换而非追加 | 尾部追加不改前缀字节 |
| 结构约束 | seam 插件 + 类型系统 | 登记表 20 块 + 机器执法测试 |
| 预算 | 无显式分块预算 | 三层预算 6000/2500 + 分类（directive/event/inventory） |

**分歧点**：dsh 的选择要求"能被替换"（所以放 user 角色），XEYO 的选择要求"不可能被误认为用户"（所以放 tool_result）。**dsh 优化的是缓存与去重，XEYO 优化的是说话人隔离。**

### ③ 变更如何变得可逆

| | dsh（A-1/A-9/A-11） | XEYO（B-7/B-8/B-9/B-10/B-11） |
|---|---|---|
| 可逆对象 | **对话**（surface 投影 + 压缩事务 + fork） | **工作区文件**（内容寻址 + orphan + 影子 git） |
| 存储 | 会话日志（事件溯源） | SHA-256 blob 库 + JSONL journal + `revision` 树 |
| 回溯实现 | 换一个 surface 投影（不删日志） | 从目标 revision 开新分支（`truncate_to` 不删旧记录） |
| 粒度 | 事件级 | 文件级（before/after 双快照） |
| 前置校验 | 无（投影天然一致） | simulated 状态机逐 op 校验（`_check_file_preconditions`） |
| 回收 | 压缩 + spill | 可达性 GC（三重默认关） |

**分歧点**：这是两端**能力覆盖最不对称**的一组。dsh 能做"逐字重建模型当时看到什么"（A-3），XEYO 能做"把磁盘恢复到某个时刻"。**前者是研究/审计能力，后者是产品/安全能力。**

### ④ 授权如何既可用又不越界

| | dsh（A-6 审批） | XEYO（B-5/B-6） |
|---|---|---|
| 授予值 | 封闭四值，唯一授予 = `allowed-once` | 三态（allow/deny/remind）+ **可复用 grant** |
| 复用 | **不支持** | 指纹 v2，身份/参数分离 |
| 超时 | 单档 | **风险分级**（180s / 60s / 不超时） |
| 无审批方 | `unavailable`（fail-closed） | `UNAVAILABLE_COPY`（超时按拒绝） |
| 模型可见 | 审批策略**不进 transcript**（保缓存） | `runtime_mode_snapshot` 块**告诉模型**当前模式 |

**分歧点**：dsh 把"过度授权"当作必须结构上排除的风险；XEYO 把"确认频率"当作可调的产品参数。**两端的失败模式选择相反**（见 B-6 对照）。

### ⑤ 执行隔离在哪里

| | dsh（A-8） | XEYO（B-3/B-4/B-11） |
|---|---|---|
| 机制 | `ctx.sandbox.confine(argv, policy)`，4 平台后端 | 权限链 11 级 + Bash 18 条黑名单 + `WriteStore` 三门 |
| 强制力 | **内核**（bwrap/Landlock/Seatbelt/Windows-ACL） | **文本分析 + 路径校验** |
| 失败姿态 | fail-closed（无后端拒绝运行） | 没有沙箱，只有"没有 jail 就不给全权"（`bash:allow` 自动降回 `default`，`:874-881`） |
| 可信度前提 | "内核不骗我" | "我的正则足够全" |

**分歧点**：这是全项目最硬的一处差距，第五轮结论与第三轮一致。XEYO 的 `_evaluate_bash` 有 11 级分支、`bash_policy` 有 18 条正则与密钥拦截、`WriteStore` 有内容哈希校验——**这些工作量加起来仍然不是隔离**，它们只是让"误用"变难。

### ⑥ 什么时候该收尾

| | dsh | XEYO（B-12） |
|---|---|---|
| 回合/工具上限 | 无（靠 compaction 与 spill 处理上下文压力） | `max_turns=256` / `max_tool_calling=64` |
| 收尾窗口 | — | 共享 grace 3 轮 + `MAX_TOOL_CAP_STREAK=2` 防 grace-cliff |
| 时间/成本感知 | — | 墙钟 80/90% + USD 80/90% 纯事实播报 |
| 硬停 | — | `wall_hard_stop` 显式武装才生效 |

**分歧点**：dsh 不设执行预算（它的假设是"会话可以一直开下去，压力交给上下文管理"），XEYO 设（它的假设是"一次 submit 必须有确定的结束"）。这直接来自两端的应用形态差异——**dsh 是常驻会话运行时，XEYO 是产品级单次任务**。

## C-2 单侧独有机制

### dsh 独有（本轮 Part A 里 XEYO 无对应物的）

| 机制 | 为什么 XEYO 做不了（不是不想） |
|---|---|
| A-1 事件溯源 + `surfaceOp` 投影 | XEYO 的 transcript 是**直出**的，没有投影层——加投影层等于重写会话层 |
| A-2 `interruptedTurnClosers` | XEYO 的崩溃恢复对象是文件（B-8），不是对话结构 |
| A-3 请求纪元快照（`request/header`） | XEYO 没有"逐次请求记账"的概念，只有消息历史 |
| A-8 沙箱 confine | 无内核级隔离原语可用（Windows 侧只有 Job Object，且是资源限额非隔离） |
| A-9 压缩事务（括号事务 + 工具配对平衡） | XEYO 无压缩层（C0/C1/C2 是截断，不是事务） |
| A-10 JSONL 写后缓冲 + 撕裂尾修复 + 跨进程租约 | XEYO 的 session JSONL 是**直接追加**，无缓冲/租约 |
| A-11 会话级 fork | XEYO 有 revision 树（B-7），但没有会话 ID 级 fork |

### XEYO 独有（本轮 Part B 里 dsh 无对应物的）

| 机制 | 为什么 dsh 不需要 |
|---|---|
| B-1 T_now 分类预算管线 | dsh 的 runtime-context 是 seam 插件，不需要"20 块 + 硬顶 + 登记表"这种纪律设施 |
| B-2 伪造 tool 对声道 | dsh 用可替换 user 消息就解决了，不需要结构隔离 |
| B-3 权限 11 级链 | dsh 有沙箱兜底，策略可以粗 |
| B-4 Bash 18 条黑名单 + 前缀规则引擎 | 同上 |
| B-5 可复用授权指纹 v2 | dsh 明确不给复用 |
| B-6 风险分级 TTL + 审计配对 | dsh 单档 TTL、无审计配对 |
| B-7/B-8/B-9/B-10/B-11 工作区可逆性五件套 | dsh 的可逆性作用在对话侧 |
| B-12 会话执行预算 + 收尾窗口 | dsh 无执行预算概念 |
| B-13 成本账本 + 峰谷计价 | dsh 无成本统计（这是产品运营需求） |

## C-3 一个值得单独说的反向事实

第四轮与前三轮的叙事是"两端互为镜像、各走各路"。本轮在 B-13 里发现了**一处例外**：`usage/ledger.py:66-76` 的注释明确写着 *"对齐 DeepSeek Harness 记账纪律（v4 设计，S2/S4）"*，并逐条引用了 dsh 的 S2（流内单结算）、S4（重试 attempt 各自入账）、D-3（压缩走模型的调用必须可归因）。

**也就是说：XEYO 在成本记账这一块主动向 dsh 抄了作业，并且把出处写进了注释。** 这说明两端并非"互不相干"，至少在一个方向上有明确的知识流动。

对照来看，XEYO 在注释里引用 dsh 的地方还有几处（记忆里 09-08 至 09-10 的整改中也有引用），但**这次是本轮直接读到的、最明确的一条**。这个事实让"两端关系"的结论需要修正：不是"完全独立演化"，而是**"架构独立、局部借鉴"**。

## C-4 五轮累计结论

| 轮次 | 文件 | 行数 | 视角 | 主要产出 |
|---|---|---|---|---|
| 一 | `XEYO-vs-DeepSeekHarness-全量对比.md` | 605 | 功能面 | 有什么 / 没什么 |
| 二 | `...设计级对比-第二轮.md` | 1307 | 设计面 | 32 系统，抽象与取舍 |
| 三 | `...实现级对比-第三轮.md` | 2246 | 实现面 | 函数签名 / 算法步骤 / 常量 |
| 四 | `...逐字段级对比-第四轮.md` | 1505 | 枚举面 | 每个类型每字段每键名 |
| 五 | `...机制设计说明-第五轮.md` | 本文件 | **机制面** | 同一问题两端的解法与不变量 |

**五轮读下来，"两端差距"的最终表述**：

1. **dsh 强在"层"**：事件溯源、沙箱、类型化协议、组合层（profile/bundle/preset）、质量门——这五处是**可复用的架构层**，换一个产品也能用。
2. **XEYO 强在"纪律与运营"**：注意力治理（T_now 管线 + 登记表执法）、工作区可逆性（rewind 五件套）、权限细化（11 级链 + 指纹 v2）、成本治理（峰谷 + 账本 + 归因）——这四块是**把一件事做到底的产品能力**，换一个产品不好复用。
3. **两端最根本的分岔是"可信边界放在哪"**：dsh 放在内核（沙箱）与类型系统；XEYO 放在文本分析与测试断言。这决定了 dsh 的策略可以粗而 XEYO 必须细。

**如果要给 XEYO 排一个借鉴优先级**（第五轮视角，与第三轮结论一致但理由更具体）：

1. **沙箱**（A-8）——不是"加一个功能"，而是把可信边界从"正则"换到"内核"。这会连带简化 B-3/B-4 两层（策略可以变粗）。
2. **事件溯源会话日志**（A-1 + A-3）——让"模型当时看到什么"可逐字重建。当前 XEYO 的 transcript 直出是多个机制（投影一致性、缓存保护、审计）难以统一的根因。
3. **压缩事务**（A-9）——XEYO 的 C0/C1/C2 是截断，遇到"截断边界切断工具配对"这类问题只能靠事后修补；事务化是结构性解法。
4. **JSONL 写入的撕裂尾与租约**（A-10）——单点收益不大但成本最低，可以单独做。

## C-5 取证边界（本轮）

- **dsh 侧**：A-1…A-11 全部基于**直接读源码**（`Read` 精读 + `sed/grep` 切片），引用行号均为本机 `D:\lea\dsh-src`（commit `d347e70`）实测。A-11 中 `SessionEventMap` 的 51 个事件名以 Python 花括号计数法复核（修正了 awk 在该机器上的静默失败）。
- **XEYO 侧**：B-1…B-13 全部基于**直接读源码**，引用行号基于 `D:\lea\XenYon code`。`rewind/` 12 文件 5343 行中，`models/snapshot/journal/revision/locks/context` 六文件**全文精读**；`hotpath/service/index/blob_gc` 四文件**按函数切片精读**（未逐行读完全部 1800 + 1024 行）。
- **未逐行读的**：`rewind/service.py` 的 `_operation_details` 与 `_journal_ops_for_target_message`（约 130 行）、`hotpath.py` 的 `_restore_checkpoint_files`（约 200 行）、`engine/budget.py` 的 `to_dict/from_dict`（约 100 行）。这些是"实现的执行细节"，不影响本轮"机制设计"层面的结论。
- **数字口径**：本文件所有数字（常量值、行号、字段数）均为本轮实测；若与前四轮冲突，**以第四轮（逐字段级）与本轮为准**——前两轮部分依赖子代理转述。
- **本轮的自我更正**：B-8 的 `hotpath.py:1-13` 文件头注释描述的是 **v3.0 旧合同**（orphan → 原子重写 transcript），而 `:427-430` 的实际代码是 **v3.1 的 marker 方案**（transcript 永不重写）。**注释与代码不一致，以代码为准**——这一点在第一至第四轮均未发现，是第五轮"读机制而非读清单"的直接收益。

---

*第五轮报告完。五份报告可并列查阅：功能面（605 行）→ 设计面（1307 行）→ 实现面（2246 行）→ 逐字段级（1505 行）→ 机制设计说明（本文件）。*
