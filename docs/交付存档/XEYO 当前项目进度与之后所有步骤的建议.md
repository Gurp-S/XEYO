# XEYO 当前项目进度与之后所有步骤的建议

> 更新时间：2026-08-20  
> 依据：XEYO 当前生产源码、Python/前端测试、启动与构建配置，以及 XEYO 自有 `docs/` 设计文档和本计划书中已归档的代码事实。后续实施不以外部项目源码或设计文档作为前置依赖。  
> 本版目标：在跳过已经确认的结论、不重复重读已核对实现的前提下，把增量源码事实与项目从当前阶段到完整落地的周期路线统一写入一份**面向企业级上线的长期计划书**。企业级完成的定义不仅是功能可运行，还包括秘密治理、可重复构建、最小权限、真实端到端验收、可观测运行、数据保留、升级回滚和安全响应均具备可审计证据。
>
> 覆盖审计基准为 437 个项目文件；本轮已完成剩余高价值实现源码、入口、工具、权限、会话、回溯、用量和测试边界的核对。审计队列中仍未逐一展开的项目主要是 IDE 配置、空 `__init__.py`、已确认的 `not_implemented` 工具壳、JSON/fixture 数据和 Android 图标资源，它们不构成新的 Agent 运行事实；因此本版将“高价值源码研读完成”与“非实现资源无需重复研读”明确区分。

## 一、结论先行

XEYO 已经不是等待“把 Agent 主循环写出来”的 Demo，而是进入了**核心运行能力已经存在、跨入口契约和工程化落地仍需收口**的阶段。`QueryEngine`、`query_loop`、上下文投影、预算、停止、消息持久化、SessionPool、iLink、File Helper、前端聊天主链路、IndexedDB、设置/profile 和 rewind 后端骨架均已形成可工作的基础。[1] [2] [3] [4] [5] [6] [7] [8]

从现在到完整 XEYO 落地，正确顺序不是不断增加未实现工具，而是先把**同一轮 `session_id + turn_id` 在本地桌面、FastAPI、HTTP bridge、JSONL bridge、remote runner、iLink 和 File Helper 中的身份、状态、权限、事件和恢复语义统一**。之后再完成审计、回溯事务补偿、发布工程化、memory/L5 的证据门禁、Java 工具运行时，以及 MCP/LSP、多 Agent 和更多工具等平台扩展。所有扩展均以 XEYO 已定义的核心状态、事件、权限、数据和发布契约为唯一前置条件。

本轮增量研读还确认：当前 remote API 实际上只是单一 token 保护的 submit + poll 薄接口，`channels.auth` 使用进程级 `XEYO_REMOTE_TOKEN`，没有 session、peer 或 role 粒度；Tauri capability manifest 也只有 main window 的 core/window/shell-open/dialog 权限，没有自定义文件系统 capability 分区。因此“remote 已可访问”和“桌面/远程已具备产品级安全边界”必须分开判断。[65] [66] [67]

同时，新增的 `gui/src/pasture/` 已接入 `ChatPage`，并由 `chatStore` 的 usage、压缩开始/完成、成功/错误回调驱动上下文草地、植物和动物的视觉变化；但它通过 `window` 级 `xy-pasture-event` 自定义事件总线运行，装饰状态通过单一全局 localStorage key 持久化，不按 workspace/session 隔离。因此 pasture 是已有的展示层增强，不是新的 Agent、TaskState、memory 或核心事件事实源；长期工作只需在统一事件投影后提供适配器，并明确其装饰状态边界。[7] [70] [71] [72] [73]

本计划要求落实的职责边界不是文件名迁移：入口负责输入、事件传输和控制命令；QueryEngine/Session 持有会话生命周期；工具通过统一上下文执行；权限询问可以挂起并恢复；任务状态独立于 Todo 文本；远程和平台能力复用同一会话核心。基于 XEYO 自身代码事实和契约，本计划把工作拆成连续周期，而不是只列下一周的短期 TODO。

> **最高优先级判断：** P0 先完成统一 EngineEvent envelope、SessionTaskState、workspace/cwd 作用域、Permission ASK pending/resolve/resume、工具能力矩阵与默认 registry contract，以及 remote/iLink 和前端事件投影接线；不得以增加未实现工具数量替代这些基础契约。P1 完成审计、回溯事务补偿、安全治理、跨入口验收和可重复发布。P2/P3 才推进 memory/L5 evidence gate、Java 最小 RPC、MCP/LSP、多 Agent 和更多工具。

> **关键修正：** memory/L5 不是 P0 空白。`memory/simulator`、`memory_stack_eval.py`、`p2_full_campaign.py`、`formula_live_ab.py`、质量计划测试、黄金轨迹、AB gate、theta/r 探针和每日 ledger/C2 监控已经构成较完整的离线/旁路评估控制面；当前缺口是生产 runtime 接线、真实 shadow/AB、回滚门禁和长期观测闭环，默认生产模式仍为 `project`，C2 gate 默认关闭。[24] [25] [26]

## 二、XEYO 自洽目标架构与职责边界

| Claude 设计原则 | XEYO 对应代码与事实 | 完整落地要求 |
|---|---|---|
| 入口不重新实现 Agent 主循环 | `QueryEngine`、`query_loop`、FastAPI、HTTP bridge、JSONL bridge、iLink | 保留一个引擎事实源；所有入口只做适配、鉴权、事件传输和控制命令 |
| QueryEngine/Session 持有会话生命周期 | `engine/query_engine.py`、`server/session_pool.py` | 在引擎或 Session 层增加统一 task state、事件发布、恢复和权限等待；不重写主循环 |
| query loop 负责模型—工具—权限回流 | `engine/query_loop.py`、`tools/tool_registry.py`、`permissions/*` | ASK 必须成为真正可等待、可恢复、可超时收口的运行时状态 |
| Context 与 UI transcript 分离 | `prompt/*`、`memory/*`、`engine/compact.py`、前端 transcript | 固化 context 输入输出；前端 transcript 只能是事件投影，不能成为唯一事实源 |
| 展示层可以增强体验但不能成为事实源 | `gui/src/pasture/*`、`chatStore.ts`、`ChatPage.tsx` | `ContextPasture` 只消费统一状态投影；自定义 UI 事件和装饰性 localStorage 不得替代 EngineEvent、TaskState 或 workspace/session 持久化 |
| 工具执行上下文包含取消与权限回调 | `tools/*`、`permissions/gate.py`、`ToolUseContext` 相关实现 | 先冻结工具结果、取消、错误、权限和审计契约，再增加新工具 |
| `canUseTool` 是可挂起的权限协议 | `permissions/filesystem.py`、`permissions/gate.py` | 增加 request id、pending store、resolve API、resume、超时和重启恢复 |
| TaskState 不等于 Todo 文本 | `TodoWrite`、`TodoStore`、`JobStore`、`chatStore` | 新建会话级 `SessionTaskState`；TodoWrite 仅作为兼容写入器和 UI 辅助 |
| schema 数量不等于可执行工具能力 | `tools/catalog.py`、`tools/stub.py`、scaffold 工具、`test_catalog.py` | `ENABLED_TOOLS`、`SCAFFOLD_TOOLS` 和默认 registry 形成可回归的能力矩阵 |
| Python 编排与 Java 工具后端分离 | `java/pom.xml`、Java RPC/ToolRuntime 类 | Java 只执行工具；Python 保留模型、上下文、权限和任务生命周期 |
| Remote/MCP/Multi-agent 在核心状态成熟后平台化 | `channels/runner.py`、`channels/ilink/*`、MCP/Agent/Task 空壳 | 先统一状态、权限、workspace 和预算，再做平台扩展 |

## 三、当前实际状态：已完整、已有基础与真正缺口

“已完整”表示已有实现和测试，或已经明确产品化边界；“已有基础”表示主路径可用但还需接入统一协议；“真正缺口”表示必须新建的语义、安全或交付闭环。以下判断仅使用真实代码与测试事实，不把设计文档中的目标误写成当前能力。

| 领域 | 状态等级 | 真实代码事实 | 不应再写成什么 | 对路线的影响 |
|---|---|---|---|---|
| Agent 主循环 | 已完整 | `QueryEngine` 负责会话提交、事件流、恢复和 rewind 接缝；`query_loop` 负责模型—工具循环、预算和停止 | “需要重写主循环” | 不重写；围绕引擎补统一状态和事件 |
| Context/compact | 已有基础且可用 | 已有 C0/C1/C2、上下文投影、压缩决策和 memory runtime | “compact 尚未实现” | 收口契约、边界测试和各入口一致性 |
| SessionPool busy/lease | 基础能力已完整，企业级拓扑未完成 | 已有 lease、busy、interrupt、pending interrupt、stale 回收、drop 和跨重启 hydrate 语义；但协调状态仍是进程内，缺少持久 job lease、分布式锁和跨实例聚合 | “SessionPool 缺少基本 busy/lease”或“SessionPool 已是高可用调度器” | 保留基础实现；补 task state 映射、支持矩阵和多实例边界 |
| 会话恢复 | 消息续聊基础已完整，任务级恢复未完成 | per-session JSONL、原 message id、session 隔离、坏行容忍、禁用持久化开关、model 变更历史保留、set_cwd stash 恢复均有回归。[32]；但 task/turn/permission/revision/event cursor 和完整性结论不在同一恢复契约内 | “重启续聊尚未支持”或“恢复已达到企业级” | 保留消息续聊；补恢复后的 task、permission、revision、event cursor、schema/integrity 和并发写策略 |
| 前端本地持久化 | 已完整但权威范围有限 | IndexedDB `xeyo-web` 当前 schema version 4，已有 `spaces`、`sessions`、`messages`、`kv`，按 space/session 分区并覆盖旧 session/space 迁移、级联删除和 rollback UI state；但没有 job/turn/event cursor/permission/task state store，rollback KV 也不是后端事务权威。[71] [72] | “前端没有持久化”或“IndexedDB 已是后端任务账本” | 将 task snapshot、cursor、schema version 接入现有 DB，不新建第二套数据库；后端统一状态仍为权威 |
| 设置与 profile | 已完整 | 多 profile、provider/model/apiKey/baseUrl、thinking、budget、remoteChannel、主题和布局设置均有 store/UI/持久化；profiles 测试覆盖迁移、切换和禁止删除最后 profile | “设置面板仍待建设” | 只补与后端 schema、审批和安全配置的对齐 |
| 前端聊天与投影 | 已有稳定测试 | `chatStore`、`groupTranscript`、`toolActivity`、`streamMarkdown`、`remoteStore`、MessageList、typewriter、chatScroll 等已有稳定回归 | “前端主链路未验证”或“需要重做聊天 UI” | 改为统一事件 reducer、版本、断线和权限/task 投影；保留现有测试为基线 |
| ContextPasture 展示层 | 已接入但不具核心权威性 | `Pasture.tsx` 已挂载在 `ChatPage`，由 `chatStore` 的 usage/压缩/agent 事件驱动视觉状态；`PastureEvents` 是 window 自定义事件总线，`PastureStorage` 是全局 `xeyo-pasture-state` localStorage 装饰状态，不按 workspace/session 隔离。[101] [102] [103] | “pasture 已实现 workspace/session 记忆或任务状态”或“需要把 pasture 纳入后端核心” | 保持为可替换的展示 adapter；统一事件后只消费 context/task 投影，若未来需要跨 workspace 保存再单独定义 scope 和 schema |
| 工作区导航与二维码登录 | 已完整且产品化 | `Sidebar` 已有 workspace/session 分组、搜索、新建、打开/删除 workspace 和宽度持久化；`RemoteQrPanel` 已区分 iLink/File Helper，覆盖启动、二维码、扫描、错误、重轮询和停止；`explorerStore` 负责 workspace API 的目录/文件投影，但不持有 root authority、revision、锁或冲突状态。[73] [74] | “Sidebar/二维码登录 UI 仍是缺口”或“Explorer 已等于安全文件服务” | 只让既有 UI 消费统一状态和错误；把路径越界、写回冲突、revision 和审计留在后端/跨端验收 |
| 用量与成本 | 已有较完整策略，治理边界仍未完成 | vendor/local/mixed 三态合并已有回归：vendor 权威、vendor 为空时 local fallback、vendor 有总计但无模型细分时保留 mixed；本地 ledger 可按日/厂商/模型聚合，价格层已有静态价、峰谷、环境覆盖、24 小时网络缓存和离线过期回退。[33] [95] [96] [97] | “usage 只有本地估算”或“预算/价格已具备跨任务治理” | 保留双源策略和 submit 级预算门禁；补 session/turn/job 归因、跨 workspace/peer 配额、并发治理、价格版本/不确定性、时间范围和审计可见性 |
| iLink | 已有较完整契约 | 按 peer 隔离 session、context token、长轮询、入站排队、超时恢复、服务层事件游标和镜像已有；`session_id_for` 按 userId 映射 `ilink:<uid>` | “iLink 只是简单壳” | 保留契约；接统一事件、permission/task/stop/retry |
| File Helper | 有意保持薄实现 | 作为 intentionally thin 的 final-only 通道，页面层有二维码、DOM 探测、消息过滤、文件发送和回声前缀处理；其状态/事件来自进程内广播，没有持久 cursor/replay；`remote_deliver.py` 只是异步副作用投递层，后台调度失败仅记录 warning，无 job/event/task 审计。[6] [64] [100] | “File Helper 需要镜像所有工具事件”或“文件投递已具备可靠任务状态” | 只维护 final-only、错误、投递重试、告警和优雅关停，不复制 iLink 复杂度或另建任务状态机 |
| EngineEvent | 已有基础但不完整 | 已有 delta/tool/usage/final/stopped/result 七类事件；其中 `stopped` 是当前代码事实中的 legacy 事件名，不等于目标 Task 的 `canceled` 状态；仍缺少统一 envelope、permission/task/approval 等状态事件 | “没有事件系统” | 扩展统一 envelope 和状态事件，并将 legacy `stopped` 转为独立 stop reason + 权威 Task/Turn 状态 |
| 三套入口协议 | 真正缺口 | FastAPI/8000、HTTP bridge/8765、JSONL stdin/stdout 各自有入口或协议；没有统一 `session_id + turn_id + event_id` envelope，HTTP bridge 还自持独立 EnginePool | “只需再补一个前端事件类型” | P0 统一核心发布器、适配器、身份和重放 |
| Permission ASK | 真正缺口 | `ALLOW/DENY/ASK` 已有，但 `enforce_decision` 把 ASK 在执行边界降为拒绝；无 pending store、resolve API、resume | “需要新增三态策略” | P0 做挂起—确认—恢复闭环 |
| SessionTaskState | 真正缺口 | TodoWrite 是进程内、默认 `DEFAULT_TODO_KEY = "default"` 的三态清单；JobStore 是远程投递状态；chatStore 是 UI 投影 | “把 TodoStore 改名即可” | 新建会话级状态并发布事件 |
| remote job 对齐 | 已有基础但未统一 | 三路薄路由共享进程级 `JobStore`/`FinalOnlyRunner`；`JobStore` 只有 `queued/running/done/error`，记录 `job_id/session_id` 和结果/错误，没有 `turn_id`、revision、permission、停止原因、event cursor 或 task state 版本；SSE 广播没有持久游标/replay，进程内队列满时可丢事件。[63] [64] [98] [99] | “远程执行完全没有队列”或“remote API 已具备完整控制面” | 映射到 SessionTaskState，补 turn/cursor/原因和可恢复投递，并在 P1 收紧鉴权，不把 JobStore 扩成第二套 Agent 状态机 |
| remote API/auth | 有基础但安全粒度不足 | `channels/api.py` 暴露 health、message submit 和 job poll；`channels/auth.py` 从单一进程级 `XEYO_REMOTE_TOKEN` 读取共享 secret，用 Bearer 或 `X-Remote-Token` 比对，没有 per-session/per-peer/per-role scope | “有 token 就等于有完整远程权限模型” | P1 做身份、scope、resolve/stop 授权和审计 |
| workspace/cwd 作用域 | 真正缺口，桌面入口有额外风险 | `session/cwd.py` 通过模块级全局变量保存 cwd，`set_cwd` 不做 `os.chdir`，多 session 并发仍可能串目录；Tauri `lib.rs` 固定注入 `XEYO_CWD=<Python 根>`，不是用户当前 workspace，需验证覆盖关系；`capabilities/default.json` 仅给 main window core/window/shell-open/dialog 权限，没有自定义 filesystem capability 分区。[36] [67] | “工作区权限已经完全按 session 隔离” | P0/P1 交界的并发、桌面 capability 和入口作用域修复 |
| 工具能力矩阵 | 已有禁用基础，能力矩阵仍需固化 | Echo、GetTime、Screenshot、SendToWeChat、Bash、Read/Write/Edit、Glob/Grep、TodoWrite、MemoryWrite/Forget/Search 有真实实现；Task*/AskUser/Plan/MCP/LSP/Web/Agent/Skill/Notebook/SendMessage 主要是 schema + `not_implemented`，`test_catalog.py` 证明 scaffold 不进入默认 registry | “工具目录有 schema 就等于已实现”或“要一次性实现所有 Claude 工具” | P0 固化能力矩阵、contract tests 和用户可见能力声明 |
| 活动日志与审计 | 已有 UI、缺后端审计 | `ActivityLog` 能展示参数、输出和 diff，但数据来自 transcript/toolActivity 投影，不是后端不可篡改审计日志 | “需要新建活动日志面板” | 保留 UI，新增后端 audit/event/revision 对齐 |
| rewind/rollback | 后端骨架成熟、端到端未收口 | `RollbackService` 有 preview、execute、幂等、冲突、recovery_required；默认 feature flag 关闭，入口/API/UI/补偿和可观测性仍需补 | “回溯后端尚不存在” | P1 补开放、事件、恢复和前端事务补偿 |
| memory/L5 | 已有完整评估控制面，生产接线 evidence-gated | simulator 有不变量、1000 次确定性、黄金轨迹、theta/r 探针、AB gate；campaign/replay、每日 ledger/C2 监控和 docs/12 表 D 写回存在；默认 `XEYO_L5=project`、C2 gate 关闭；`kv_cache_probe.py` 只是脚本级在线探针，simulator 不接 query_loop | “L5/memory 是 P0 空白”或“v6.1 已默认线上” | P2/P3 做 parity、shadow/AB、真实任务质量、回滚和持续观测，不重写离线基础设施 |
| Java/RPC | 前基础设施阶段 | `pom.xml` 仅 Java 21 compiler plugin；Java RPC、ToolRuntime、ToolRegistry 多为空壳，无 RPC/JSON/test/package wiring | “已有 Java RPC 接缝” | P2 独立完成最小协议和一个真实工具 |
| 构建、CI 与发布工程 | 有本地入口，缺完整交付闭环 | Python `pyproject.toml` 没有生产锁定、CI、服务管理或打包配置；CLI 有 `build/typecheck/test/tauri:build`，但尚未形成签名、版本、制品校验和发布流水线；Tauri 前端在桌面固定请求 `127.0.0.1:8000` | “能本地启动就等于可发布” | P1 建立 CI、依赖锁定、健康检查、Tauri release 资源、端口冲突和制品验收 |

### 3.1 不应混淆的边界

**第一，SessionPool 已解决资源占用，不等于已经解决任务语义。** 它能够阻止同一 session 的并发执行、接收 interrupt 并回收 stale lease，但还不是 `SessionTaskState`，也不负责向所有入口发布 waiting permission、stopping、revision 和可恢复状态。后续应做状态映射，而不是重写 busy/lease。[3] [4]

**第二，iLink 与 File Helper 必须分开。** iLink 已具备 peer 隔离、长轮询、排队和事件游标；后续目标是消费统一事件并增加审批、任务状态、停止和重试。File Helper 则是有意设计成 final-only，只需使用统一的最终结果、错误和投递标识。[5] [6]

**第三，ActivityLog、Todo dock、usage panel、Sidebar 和 RemoteQrPanel 是已有产品界面，不是空白页面。** 真正缺的是它们与后端权威状态的关系：ActivityLog 目前是 transcript 的活动投影，Todo dock 依赖 Todo 快照，usage 已有 vendor/local/mixed 解释，Sidebar/QR 面板已有产品化交互。下一步应替换数据来源和语义边界，而不是重复建 UI。[7] [8] [9] [27] [28] [29] [34] [35] [38] [39]

**第四，memory/L5 的“已有”与“上线”不是同一件事。** 评估脚本、模拟器和质量计划已经存在并且有 gate，但生产默认仍关闭 C2，在线 KV 探针也没有自动写入持续账本或运行时门禁。因此 memory 后续工作是证据驱动的接入和验收，不是把实验代码直接改成默认生产策略。[24] [25] [26]

**第五，本地开发可运行与产品可交付不是同一件事。** 当前已有 Vite、Vitest、Tauri 和 Python 测试命令，但依赖锁定、CI、后端健康检查、端口冲突处理、Windows 签名、制品校验、升级/回滚和运行监控仍需作为独立落地阶段，不应被一次 `build` 命令替代。[42] [43] [44] [45]

**第六，remote token 和 Tauri capability manifest 都只是最小边界，不是最终安全模型。** remote 目前是单一共享 token；Tauri capability 目前没有按功能或 workspace 划分的 filesystem scope。P1 应先建立最小权限和审计，再决定是否开放更多桌面或远程能力，不能把新增 shell/dialog 权限当作产品功能完成。[65] [66] [67]

**第七，ContextPasture 是展示层，不是状态层。** `chatStore` 已经把 usage、压缩和 agent 成功/错误事件接到 pasture，因此它可以继续作为上下文压力和运行反馈的可视化增强；但 `xy-pasture-event` 只是浏览器自定义事件，`xeyo-pasture-state` 只是全局装饰性 localStorage，且不按 workspace/session 隔离。不得从 pasture 的植物、动物、解锁或折叠状态推断任务完成、记忆持久化、workspace 隔离或后端事件可靠性；统一协议完成后应让 pasture 订阅标准投影，而不是让核心协议依赖 pasture。[7] [101] [102] [103]

## 3.2 本轮增量事实对路线的修正

本轮补读没有推翻既有 P0/P1/P2/P3 判断，而是把几个容易被高估或误判的边界写实。下表只记录新增事实对应的路线修正，不重复前文已确认的主结论。

| 新增源码事实 | 为什么重要 | 涉及文件 | 优先级与范围 | 预期收益 |
|---|---|---|---|---|
| `OfflineReplayRoute` 直接向 `chatStore` 注入 fixture 状态，并用固定 replay message 完成回放，不经过 EngineEvent、API、JobStore、TaskState 或真实模型。[70] | 它可以稳定测 UI 首屏、滚动、流式 Markdown 和 pasture 视觉变化，但不能证明权限、取消、远程重放或真实任务终态；若混入 E2E 统计会高估系统可靠性。 | `gui/src/bench/OfflineReplayRoute.tsx`、`gui/src/lib/streamSignal.ts`、`gui/src/stores/chatStore.ts` | P0/P1；测试架构，前端 bench 与全栈 E2E 分开 | 保留低成本性能夹具，同时避免把离线回放误报为协议验收；让真实跨入口测试覆盖核心生命周期 |
| 前端 IndexedDB 只有 `spaces/sessions/messages/kv` 四类 store，schema version 4；可做 workspace/session 迁移和级联删除，但 rollback KV 只是浏览器投影，没有 job/turn/cursor/permission/task state。[71] [72] | 说明前端持久化已经成熟，但不能代替后端任务账本；新增状态应复用现有迁移机制，而不是新建第二套数据库。 | `gui/src/lib/db.ts`、`gui/src/stores/chatStore.test.ts` | P0；前端持久化接线，后端权威 | 刷新/切换/重启恢复更一致，避免浏览器状态与服务器状态各自演化 |
| remote、File Helper、iLink 三路由共享进程内 JobStore/FinalOnlyRunner；SSE 只有初始 state 和进程广播，无持久 cursor/replay，JobStore 没有 turn/revision/permission/stop reason。[63] [64] [98] [99] | 远程目前是可用的薄控制面，不是完整任务协议；广播丢失和进程重启会直接暴露可恢复性缺口。 | `python/channels/api.py`、`filehelper/api.py`、`ilink/api.py`、`jobs.py`、`runner.py`、各 broadcast | P0；统一 envelope/task/cursor；P1 补恢复与观测 | 同一 turn 在本地、remote、iLink、File Helper 具有一致身份和可解释状态，减少丢事件与重复投递 |
| `auth.py` 只校验单一进程级 `XEYO_REMOTE_TOKEN`；`remote_deliver.py` 只做异步微信文件投递，失败仅 warning，无持久投递审计/重试/关停 drain。[66] [100] | submit、poll、resolve 一旦共用单 token 将无法表达 session/peer/role 授权；副作用层失败也不能被误当作任务失败或成功。 | `python/channels/auth.py`、`channels/remote_deliver.py`、`channels/api.py`、`server/app.py` | P1；安全、审计、运维 | 最小权限、可撤销授权、可追责投递失败和优雅关停，避免把通道副作用混入核心任务状态 |
| `engine/budget.py` 已有 submit 级 turns/tokens/USD/CNY 门禁；`usage/pricing.py` 有实时价格 24h 缓存和离线回退，但 usage ledger 仍是本地 JSONL/进程缓存，价格存在未知模型回退。[95] [96] [97] | P0 不应重复实现单次预算；长期应解决跨 session/workspace/peer 配额、并发竞态、价格版本和成本不确定性，而不是误报“没有预算”。 | `python/engine/budget.py`、`python/usage/ledger.py`、`python/usage/pricing.py`、`usage/combine.py` | P1；后端/运维，前端展示 | 防止跨任务成本失控，让预算、价格来源和未知成本可解释、可告警、可审计 |
| `FilesChanged`、`TodoList`、`StreamingMarkdown`、`DiffPreview`、`EditableMarkdown`、`ErrorBanner`、`MessageBubble`、`TextFileEditor`、`WorkspaceImg` 与高亮/Mermaid/RAF helper 均是下游展示或编辑辅助；它们不生成 turn/task/revision/permission 权威状态。[75]–[94] | 这些组件已有较好的交互和性能基础，新增工作应聚焦 HTML/Markdown round-trip、worker 输出清理、workspace-aware 图片缓存和真实运行时测试，不应重做聊天 UI 或把展示提示当任务终态。 | `gui/src/components/*`、`gui/src/lib/*`、`gui/src/hooks/*`、`gui/src/test/setup.ts` | P1/P2；前端质量与安全验收 | 降低展示层误导与潜在跨 workspace 缓存/HTML 风险，同时保持现有产品化 UI 投资 |

| Session 事实源与持久化 | Session JSONL 已能续聊，但 `SessionState` 没有 `task_id/turn_id/permission` 身份字段；`MessageStore` 是进程内 list，没有 message id/revision/并发锁；hydrate 对坏行静默跳过；transcript append 虽按 message id 去重，但没有文件锁、`fsync`、加密或完整审计字段。[157]–[161] | “能恢复消息”不能等于“能恢复企业任务”。保留现有续聊能力，并把任务快照、事件游标、permission pending、revision、schema/integrity 和并发写策略接入同一生命周期 | `python/session/state.py`、`persistence.py`、`message_store.py`、`hydrate.py`、`record_transcript.py`、`engine/query_engine.py` | P0/P1；后端为主，前端同步投影 | 重启、并发、坏盘和升级后仍能判断状态是否完整，避免消息、任务、事件和回溯各自恢复 |
| SessionPool 横向边界 | `SessionPool` 只在单进程用 `threading.Lock` 管理 session、engine、busy lease、history stash 和 600 秒 stale reclaim；没有分布式锁、持久 job lease 或跨实例预算聚合。[162] | 现有串行与 stale reclaim 应保留，但不能把它当作多实例调度器；开放多 worker/副本前必须引入持久队列/租约/幂等接管，或明确单实例部署矩阵 | `python/server/session_pool.py`、`channels/jobs.py`、`channels/runner.py`、部署与 readiness 配置 | P1；后端/运维 | 避免多副本同时执行同一 turn、stale lease 误接管和成本重复累计，支持可解释故障恢复 |
| Provider 与错误可靠性 | `DeepSeek V4 Flash` SSE 客户端已有 httpx/stdlib 双路、tool_call 缓冲和 usage 接收，但没有 retry/backoff/熔断/provider 抽象；`common/errors.py` 主要做中文友好映射，没有稳定 `error_code`、`retryable`、`request_id` 和结构化日志字段。[163] [164] | 模型网络短暂失败、限流、半流断开和未知异常不能靠 UI 文案处理；先统一 provider/error contract，再做绑定 turn/event 幂等的重试，不能重复工具副作用 | `python/model/deepseek.py`、`model/client.py`、`model/openai_compat.py`、`python/common/errors.py`、`engine/query_loop.py`、`server/app.py` | P1；后端为主，前端/运维消费 | 模型失败可分类、可重试、可告警、可追踪，避免把供应商故障误报为任务失败或重复执行工具 |

## 四、P0：先收口跨入口的身份、状态、安全与可执行能力边界

### P0-1：统一 EngineEvent envelope，并收口三套入口协议

这是第一优先级，因为任务状态、权限审批、远程镜像和前端恢复都必须共享同一个事件身份。目前 `msgtypes/events.py` 已有事件联合类型，但 FastAPI、HTTP bridge、JSONL bridge 和前端 parser 没有统一的 `session_id + turn_id + event_id` 外壳；`BridgeEvent` 也缺少身份、顺序、权限和任务字段。需要特别保留三路 remote/File Helper/iLink 已有的薄入口与 final-only 边界，只把它们接到同一权威发布器，不把进程内 JobStore 或 SSE 广播升级为第二套事件真相。[14] [15] [16] [17] [30] [63] [64] [98] [99]

| 项目 | 具体建议 |
|---|---|
| envelope | 每条事件至少包含 `schema_version`、`session_id`、`turn_id`、递增 `event_id`、`type`、`created_at` 和结构化 `payload`；同一 turn 的事件支持去重、排序以及断线后的 reset/replay |
| 事件类型 | 保留 delta/tool/usage/final/stopped/result；新增 `task_state_changed`、`permission_pending`、`permission_resolved`、`job_queued`、`job_started`、`job_finished` 等统一表达；状态变化不能埋在 UI 文案中 |
| 权威发布点 | QueryEngine/Session 创建并发布事件；FastAPI、HTTP bridge、JSONL bridge、remote runner、iLink 和 File Helper 只做传输适配 |
| 三套入口 | FastAPI 8000 作为主 HTTP/SSE；HTTP bridge 8765 作为兼容适配器；JSONL bridge 作为命令行适配器；如果保留独立端口，必须共享 session/event 语义，不能继续各自持有权威状态 |
| 前端兼容 | `api.ts` 先接受新 envelope，同时兼容旧 OpenAI delta 和 `xy` side-channel；未知事件跳过并记录诊断，不破坏旧客户端。现有 split frame、malformed JSON、trailing frame、HTTP error 和 usage 解析测试保留为回归基线。[43] |
| 完成标准 | 同一 turn 从本地桌面、remote API、HTTP bridge、JSONL bridge 和 iLink 观察到相同身份；乱序和重复事件不会生成第二个工具行或第二次最终回复 |
| 预期收益 | 消除多套协议和多处状态猜测，为所有后续周期提供唯一接缝 |

**涉及文件：** 后端重点为 `python/msgtypes/events.py`、`python/server/app.py`、`python/bridge/http.py`、`python/bridge/__main__.py`、`python/engine/query_engine.py`、`python/channels/runner.py`；前端重点为 `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts`、`remoteStore.ts`；通道只修改适配和游标处理，不重写已有 peer/session 隔离。

### P0-2：建立 SessionTaskState，并修复 session/workspace 作用域

`TodoWrite`、`JobStore` 和 `chatStore` 解决的是三个局部问题，不能代替会话级任务状态。建议在 QueryEngine 或 Session 层增加权威 `SessionTaskState`，同时处理 cwd 的模块全局问题和 Tauri 启动注入问题。否则多 session 并发时仍可能把一个会话的工作目录带入另一个会话，桌面壳还可能把 Python 根误当作用户 workspace。[3] [36] [40] [41] 另外，当前 `SessionState` 本身没有 `task_id/turn_id/permission` 字段，`MessageStore` 也没有 message revision 或并发契约；新状态必须成为向后兼容的扩展，并明确消息恢复、任务恢复和事件恢复不是同一件事。[157]–[162]

| 项目 | 具体建议 |
|---|---|
| 任务状态 | 区分 `queued/running/waiting_permission/stopping/stopped/succeeded/failed` 与 Todo item 的 `pending/in_progress/completed`；两者不能共用枚举 |
| 身份与版本 | 包含 `session_id`、`turn_id`、可选 `job_id`、`revision`、`updated_at`、`current_tool`、`interruptible` 和 `error`；每次变化产生可去重事件 |
| 状态归属 | QueryEngine/Session 为权威；SessionPool 负责 lease/interrupt；JobStore 只保存 remote 投递和结果；chatStore、iLink、Todo dock 只保存投影 |
| Todo 迁移 | `TodoWrite` 继续支持现有调用和 UI，先增加结构化 snapshot 到 TaskState 的兼容写入，逐步停止让 UI 从 `<todo_list>` 文本反解析唯一状态 |
| cwd/workspace | 将 cwd 从模块级变量改为 session/workspace context，显式传递到 query loop、tool permission、filesystem 和 workspace_fs；每个 session 建立可验证 workspace identity |
| Tauri 注入 | 检查并修复 `gui/src-tauri/src/lib.rs` 固定注入 `XEYO_CWD=<Python 根>` 的覆盖关系；桌面启动链应把用户 `activeSpace.rootPath` 映射到后端 session/workspace；dev/release 两种 resource_dir 路径都要有回归 |
| 会话数据契约 | 为 `SessionState` 增加 `session_id/task_id/turn_id/revision/permission` 等可恢复身份；`MessageStore` 维护稳定 message id、版本和并发写策略；transcript 记录 schema/integrity/audit 元数据 |
| 恢复 | JSONL hydrate 后恢复任务快照、事件游标、revision 和必要 permission 状态，不能只恢复 messages；坏行必须产生告警/完整性结果，不能静默丢弃 |
| 完成标准 | 两个并行 session 各自使用自己的 cwd；Tauri 打开两个 workspace 时后端 root 与前端 activeSpace 一致；刷新、切换、排队、停止、异常和重启恢复后均能按 `session_id + turn_id + revision` 查询状态 |
| 预期收益 | 将资源占用、任务进度和工作目录从 UI 猜测变成可验证事实，降低串 session、桌面误用 Python 根和错误执行风险 |

**涉及文件：** 新增 `python/engine/task_state.py` 或等价模块；修改 `python/engine/query_engine.py`、`python/engine/query_loop.py`、`python/server/session_pool.py`、`python/session/cwd.py`、`python/permissions/filesystem.py`、`python/server/workspace_fs.py`、`python/channels/jobs.py`、`python/tools/todowritetool/store.py`、`todo_write_tool.py`、`gui/src-tauri/src/lib.rs`；前端修改 `gui/src/lib/types.ts`、`chatStore.ts`、`SessionTodoDock.tsx`、`db.ts`、`explorerStore.ts` 以存储任务投影、游标和 workspace 关联。

### P0-3：实现 Permission ASK 的 pending/resolve/resume 闭环

当前已经有 `ALLOW/DENY/ASK` 三态，缺口不是策略枚举，而是 ASK 没有成为可挂起的运行时状态：请求没有可靠 request id，入口没有统一 pending 事件，query loop 不能等待 resolve 后恢复，超时和重复 resolve 也没有统一收口。`types/permissions.py` 目前只有 `PendingClassifierCheck` 占位模型，没有 pending record、resolver 或 resume API；它不足以表达 decision、资源、审批主体、租户/peer scope 和审计关联。[31]

| 项目 | 具体建议 |
|---|---|
| 请求对象 | `permission_request_id`、`session_id`、`turn_id`、工具名、脱敏参数摘要、风险等级、过期时间和可选修改后输入；不得把原始 secret 或完整 API key 放进事件 |
| 后端流程 | ToolRegistry 调用 gate；ASK 时写入 pending store、发布 `permission_pending`、暂停 turn；resolve API 按 request id 原子写入 decision；query loop 恢复、拒绝或超时结束 |
| 入口行为 | 桌面端提供确认/拒绝；remote API 提供查询和 resolve；iLink 支持带 request id 的明确命令；File Helper 不承担审批交互，只收最终结果 |
| 安全规则 | 单个 request 只能 resolve 一次；默认超时拒绝；session 停止或重启后 pending 可查询且不会重复执行；resolve 必须认证并校验 session |
| 审计 | pending、resolved、tool started、tool result 和拒绝原因写入后端审计事件；前端 ActivityLog 只展示投影 |
| 完成标准 | Write/Bash、Screenshot、SendToWeChat 等副作用工具能在桌面与 iLink 被确认、拒绝或超时；拒绝后会话继续可用；并发 session 的 pending request 不串线 |
| 预期收益 | 这是从本机 Agent 走向可远程安全使用 Agent 的底座，也是 Claude `canUseTool` 设计的关键落地 |

**涉及文件：** `python/permissions/gate.py`、`filesystem.py`、`types/permissions.py`、`tools/tool_registry.py`、`engine/query_loop.py`、`engine/query_engine.py`、`msgtypes/events.py`、`server/app.py`、`channels/ilink/service.py`；前端为 `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts` 和新增确认组件。

### P0-4：冻结工具能力矩阵、默认禁用策略与 contract tests

工具目录明确区分可执行工具和 scaffold 工具，默认 registry 不注册 `SCAFFOLD_TOOLS`，`test_catalog.py` 已对此做回归。P0 的目标不是一次性实现所有工具，而是让“可见能力 = 可执行能力”成为可验证规则。[22] [23]

| 项目 | 具体建议 |
|---|---|
| 真实可用矩阵 | 持续测试 Echo、GetTime、Screenshot、SendToWeChat、Bash、Read/Write/Edit、Glob/Grep、TodoWrite、MemoryWrite/Forget/Search 的 schema、权限、取消、并发安全和副作用边界 |
| scaffold 矩阵 | 将 TaskCreate/Get/List/Output/Stop/Update、AskUserQuestion、Enter/ExitPlanMode、MCP resource、LSP、WebFetch/WebSearch、Agent、Skill、Notebook、SendMessage 等标记为未实现；空文件和 `not_implemented` 返回不得进入默认 registry |
| registry 契约 | `ENABLED_TOOLS`、`SCAFFOLD_TOOLS`、`DEFAULT_TOOLS` 只允许通过显式变更进入默认目录；每个启用工具必须有 execute contract、错误/取消/权限测试和能力说明 |
| 副作用审计 | Screenshot 会异步向远程发送图片，SendToWeChat 会发送文件，Bash/Write/Edit 有本地副作用；不能因 schema 标为 read-only 就跳过 permission、event、audit 和失败可见性 |
| 模型可见性 | system prompt、catalog API、前端工具状态和实际 registry 必须来自同一矩阵；未实现工具要隐藏或返回机器可识别 unsupported，而不是伪装成功 |
| 完成标准 | contract test 能证明默认 registry 不含 scaffold；每个真实工具有最小执行/错误/取消/权限边界测试；新增工具没有完整契约就不能进入默认目录 |
| 预期收益 | 防止模型调用空壳工具，降低错误路径和危险副作用不确定性，为 MCP/LSP/Task 扩展建立边界 |

**涉及文件：** `python/tools/catalog.py`、`python/tools/stub.py`、`python/tools/tool_registry.py`、`python/tools/*`、`python/tests/test_catalog.py`、各真实工具测试；前端补 capability/unsupported 类型，协议同步 `gui/src/lib/types.ts` 和 `api.ts`。

### P0-5：把 remote job 与 SessionTaskState 对齐，分别处理 iLink 与 File Helper

`FinalOnlyRunner`、`JobStore` 和 iLink 入站队列已经有可用基础：它们能按 session 串行执行，记录 `queued/running/done/error`，在 busy 时排队，并镜像部分 delta、tool 和 final；但三路由实际共享的是进程内存状态，SSE 广播没有持久游标/replay，`JobStore` 也没有 turn、revision、permission 或停止原因。下一步不是重建远程执行，而是把它们接到引擎权威状态并补可恢复游标。[5] [63] [64] [98] [99]

| 通道/层 | 保留现状 | 只补什么 | 明确不做什么 |
|---|---|---|---|
| `FinalOnlyRunner` | 继续负责远程一次执行和最终回复回调 | 创建 job 时绑定 `session_id + turn_id`；将 legacy `queued→accepted`、`running→running`、`done→completed`、`error→failed` 映射到权威 TaskState；`permission→waiting_permission`；`timeout` 默认进入 `failed`，若副作用结果不确定则进入 `recovery_required`；legacy `stopped` 仅作为原因，只有确认未继续执行后才由 `task.stop` 形成 `canceled` | 不在 runner 内再做一套模型—工具主循环 |
| iLink | 保留 peer 隔离、context token、长轮询、InboundQueue、事件游标和超时恢复 | 消费统一 envelope；增加 task status、permission confirm、stop/retry；按 cursor/idempotency 镜像 | 不推倒重写通道契约 |
| File Helper | 保留 final-only 和 intentionally thin 边界 | 统一为 Delivery 状态投影；legacy `final/error/job` 仅作传输标签：`final` 在实际送达确认前只能映射为 `pending/sending`，收到明确 ack 才能映射为 `delivered`；错误按重试策略进入 `retry_wait/failed/dead_letter` | 不镜像所有 delta、tool call、tool result 和审批过程，也不把 final 事件直接当作 delivered |
| JobStore | 保留远程投递记录 | 增加 `turn_id`、状态版本、取消/失败原因和恢复查询 | 不把 JobStore 改成 SessionTaskState 权威 |

**完成标准：** `/v1/remote/jobs/{job_id}`、iLink `status_payload`、桌面端和统一事件流对同一 turn 给出一致的状态与原因；File Helper 仍只输出最终结果；同一 remote event 重放不会重复发送最终回复。

**涉及文件：** `python/channels/runner.py`、`python/channels/jobs.py`、`python/channels/ilink/service.py`、`python/channels/filehelper/service.py`、`python/channels/filehelper/bridge.py`、`python/server/session_pool.py` 以及统一事件和 API 类型文件。

### P0-6：让前端从“拼 transcript”升级为“消费事件投影”

前端主链路和核心投影已有稳定测试，不应把它描述成需要重写。当前真正的问题是 `chatStore` 同时承载 transcript、流式锁、工具活动、remote 镜像和 rollback 局部状态；`api.ts` 又混合解析 OpenAI delta 与 `xy` side-channel；新增的 `chatStore -> PastureEvents -> ContextPasture` 还形成了一条独立的展示事件旁路。应在不破坏现有 UI 和测试的前提下，让统一事件 reducer 成为核心投影入口，并让 pasture 只作为其下游展示 adapter。[27] [28] [29] [34] [35] [43] [70] [71]

| 项目 | 具体建议 |
|---|---|
| reducer 输入 | 只接受统一 envelope；按 session、turn、event id/version 去重和排序；未知事件安全跳过 |
| 状态分层 | 分离 transcript、stream projection、SessionTaskState、permission pending、remote mirror 和 rollback state；不要求一次性拆成多个 store，但必须有清晰 reducer 边界 |
| 持久化 | 复用 `db.ts` 现有 IndexedDB，增加 task snapshot、last event cursor 和 schema version；不新增第二套本地数据库 |
| 远程镜像 | 保留 `remoteStore` 的 session gating、seenEventIds、seenToolIds 和 stream accumulation；切换 session 时禁止旧 stream 投影到当前对话 |
| 展示层适配 | `ContextPasture` 可继续显示 usage、compression 和 agent 成功/错误反馈，但只订阅统一 reducer 输出；`xy-pasture-event` 不得成为任务事实源，global localStorage 只保存装饰状态 |
| 活动面板 | `ActivityLog` 继续展示工具活动和 diff，后端审计事件作为可选权威字段；不新做第二套审计面板 |
| 回溯联动 | rollback、resend、stop 都更新同一 task state；保留 preview/execute，补 commit 后 send 失败的明确状态 |
| 测试策略 | 保留 groupTranscript 的回合/工具配对、toolActivity 的文件/Todo/回合分段、streamMarkdown 的 fence/math、remoteStore 的 gating/去重、settings profiles 和基础聊天测试；新增统一 envelope 的跨入口 contract/E2E，并验证 pasture 只接受标准投影、装饰状态不污染 task/workspace/session 状态 |
| 完成标准 | 重复、乱序、断线、刷新、切换 session、本地与 remote 同时运行时，UI 能按 event id/version 丢弃旧事件或请求 reset/replay |
| 预期收益 | 消除幽灵 loading、孤儿 tool 行、重复 outbound 和远程镜像串 session，同时复用现有前端实现 |

**涉及文件：** `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts`、`gui/src/stores/remoteStore.ts`、`gui/src/lib/db.ts`、`groupTranscript.ts`、`toolActivity.ts`、`streamMarkdown.ts`、`ActivityLog.tsx`、`SessionTodoDock.tsx` 及现有 store/API/投影测试。

## 五、P1：治理、回溯、安全与可交付性

P0 解决谁是事实源、如何传输、能否暂停和恢复、哪些工具真的可用。P1 解决发生过什么、能否安全回溯、能否限制风险、能否稳定交付。以下工作在 P0 接口冻结后推进，部分可以并行。

| 优先级 | 工作项 | 为什么现在做 | 主要文件 | 范围 | 预期收益 |
|---|---|---|---|---|---|
| P1-1 | 后端审计与 ActivityLog 对齐 | ActivityLog 已有参数、输出和 diff 展示，但只是 transcript 投影；permission、tool、task transition、rollback 和 Screenshot/SendToWeChat 等外部副作用需要后端可查询记录 | 新增 `python/audit/log.py`；修改 `tool_registry.py`、`gate.py`、`query_engine.py`、`runner.py`；前端补事件字段 | 后端为主，前端投影 | 可追责、可复盘、可诊断，能解释危险操作为何发生 |
| P1-2 | 回溯提交—本地截断—重发事务补偿 | `RollbackService` 后端事务骨架已成熟，但前端在 commit 后还要截断 transcript、重新发送；中间失败需要明确部分成功状态 | `python/rewind/service.py`、revision/snapshot/journal/context；`chatStore.ts`、`api.ts` | 前后端 | 避免历史消息、workspace revision 和 resend 状态不一致，支持重试或人工恢复 |
| P1-3 | rollback 统一事件与 task state | preview/execute/幂等/冲突已有后端能力，但还未完全进入通用事件序列和任务投影 | `rewind/*`、`server/app.py`、`api.ts`、`chatStore.ts` | 前后端 | 回溯可观察、可取消、可恢复，和普通 turn 使用同一状态语义 |
| P1-4 | 项目级 policy 与 workspace 安全边界 | gate、Bash policy、filesystem 和 workspace_fs 已有基础；危险 Bash、写文件、截图及外部副作用还需要仓库级可审查策略与统一 root authority | `permissions/gate.py`、`bash_policy.py`、`filesystem.py`、`server/workspace_fs.py`；新增 `.xeyo-policy.json` 与测试 | 后端为主 | 同一 Agent 在不同仓库使用不同安全策略，降低默认放行风险 |
| P1-5 | 收紧 CORS、remote 鉴权、Tauri capability 和 resolve API | 远程 API 当前仅由进程级共享 token 保护，submit/poll 没有 per-session/per-peer/per-role scope；审批 API 增加后攻击面更敏感；Tauri capability 只有 main window 的 core/window/shell-open/dialog，缺少 workspace/filesystem 分区 | `server/app.py`、`channels/api.py`、`channels/auth.py`、`channels/base.py`、`gui/src-tauri/capabilities/default.json`、`gui/src-tauri/src/lib.rs`、前端请求头和配置 | 前后端与桌面壳 | 将“能连上 remote”收口为可授权、可审计、可撤销的远程控制面，并限制桌面能力越权 |
| P1-6 | 跨入口端到端测试与真实验收 | 单测已覆盖不少基础能力，但协议统一后仍需验证长轮询、跨 session、刷新恢复、权限等待和断线重放；`wait_health.py` 只验证 HTTP 2xx，不能代替端到端验收 | Python engine/channel/server tests；CLI API/store tests；iLink/File Helper fixture 与手测记录 | 前后端与通道 | 证明连续可用，而不是只证明单个函数能运行 |
| P1-7 | 依赖锁定、CI、启动健康检查和桌面发布工程 | `pyproject.toml` 没有生产依赖锁定、CI、服务管理或打包配置；CLI 只有本地 build/test/tauri build 脚本；Tauri 请求固定 127.0.0.1:8000，Windows 签名、资源打包、端口冲突、capability 审查和制品校验尚未形成闭环。[42] [43] [44] [45] [67] | `python/pyproject.toml`、`gui/package.json`、`gui/src-tauri/src/lib.rs`、`gui/src-tauri/capabilities/default.json`、`tauri.conf.json`、Cargo 配置、启动 bat、README、CI/release 配置 | 前后端/桌面/交付 | 可重复构建、可诊断启动、可验证安装、可审计发布，避免“开发环境能跑、用户环境不能用” |
| P1-8 | 运维观测与数据保留策略 | iLink/File Helper 进程内广播可丢失；`remote_deliver.py` 以后台 asyncio task 做微信文件投递，失败只 warning，没有持久投递 job、重试队列、shutdown drain 或审计；凭据文件缺原子写入/权限/schema 版本，媒体解密失败仍可能落盘；需要日志、指标、保留和脱敏规则 | `channels/*/broadcast.py`、`channels/jobs.py`、`channels/remote_deliver.py`、`ilink/store.py`、`ilink/media.py`、新增 metrics/retention/audit 配置 | 后端/运维 | 发现断线、队列丢弃、投递失败、媒体失败和凭据损坏，并区分“任务完成”与“文件副作用完成”，控制敏感数据留存 |

| P1-9 | 会话持久化一致性与恢复完整性 | 当前 JSONL 只保证消息级续聊：`SessionState` 缺 task/turn/permission，`MessageStore` 缺版本/并发契约，hydrate 坏行静默跳过，transcript 没有锁、`fsync`、加密和完整审计字段；现有测试只覆盖 roundtrip/dedupe/坏行容忍 | `session/state.py`、`persistence.py`、`message_store.py`、`hydrate.py`、`record_transcript.py`、`msgtypes/message.py`、`tests/test_resume_from_disk.py`、`test_record_transcript.py`、`test_message_store.py` | 后端为主，前端接收 snapshot/cursor/schema | 重启、并发写、磁盘故障和版本迁移都有完整性结论；避免恢复出“消息看似存在但任务不可判断”的半状态 |
| P1-10 | Provider retry 与统一错误契约 | `deepseek.py` 没有 retry/backoff/熔断/provider 抽象；`common/errors.py` 没有稳定 `error_code/retryable/request_id`，未知异常可能无法安全分类；真实 provider 断流、限流和半流场景未形成统一验收 | `model/client.py`、`model/deepseek.py`、`model/openai_compat.py`、`common/errors.py`、`engine/query_loop.py`、`server/app.py`、模型与 SSE contract tests | 后端为主，前端错误展示和运维告警同步 | 短暂网络故障可安全重试，永久错误可明确终止；日志、UI、remote 和审计使用同一错误身份，避免重复工具副作用 |
| P1-11 | SessionPool 单实例支持矩阵与持久租约决策 | 当前 SessionPool 的锁、busy lease、stale reclaim、engine/history stash 均为进程内；多 worker/多副本会造成重复执行、租约误接管和预算重复归因 | `server/session_pool.py`、`channels/jobs.py`、`channels/runner.py`、`server/__main__.py`、启动脚本、readiness/部署配置、并发与故障注入测试 | 后端/运维 | 在引入持久队列或分布式 lease 前明确“单实例受限上线”；若开放横向扩展，具备幂等接管、shutdown drain 和跨实例可诊断性 |

## 六、P2/P3：memory/L5 以证据门禁推进

memory 方向已有相对完整的离线控制面：simulator 覆盖不变量、确定性、黄金轨迹、theta/r 探针、成本/质量拆分和 AB gate；`memory_stack_eval.py`、`p2_full_campaign.py`、`formula_live_ab.py` 能运行合成场景、真实 session JSONL replay、可选真实 provider A/B、命中率扫描、每日 ledger/C2 监控并回写 docs/12 表 D；`test_quality_plan.py` 验证默认 `XEYO_L5=project`、C2 gate 默认关闭和质量验收规则。[24] [25] [26]

这条路线尚未成为生产默认优化：`memory/simulator/__init__.py` 明确 simulator 不接 `query_loop`；`kv_cache_probe.py` 已通过真实 QueryEngine 采集 prompt-cache hit/miss、usage 和成本，但只是脚本级在线探针，不是持续账本、运行时门禁或自动 shadow/AB；报告仍可能是 `verdict_ready=False`。因此下一步是把评估证据与生产 runtime、事件、任务结果和回滚接起来，而不是直接打开 v6.1。

| 优先级 | 工作项 | 为什么现在做 | 主要文件 | 范围 | 预期收益 |
|---|---|---|---|---|---|
| P2-M1 | simulator/production projection parity 与运行时观测接线 | simulator 的 segment/token/cost 投影和 `engine/compact.py` 生产投影尚未由统一 parity contract 约束；在线探针未进入持续账本 | `memory/simulator/projection.py`、`state_model.py`、`decision.py`、`engine/compact.py`、`working.py`、`scripts/kv_cache_probe.py`、usage ledger | 后端/评估 | 防止仿真节省与线上送模内容漂移，形成可审计的 hit/miss、token、cost 和 action 观测 |
| P2-M2 | 真实 session replay + provider-neutral shadow/AB gate | 现有 campaign 和 live A/B 已有成本、命中、质量代理和 gate，但 task_success、用户 correction、permission/abort/rewind、任务状态仍未完整关联 | `scripts/memory_stack_eval.py`、`p2_full_campaign.py`、`formula_live_ab.py`、`memory/simulator/replay.py`、`report.py`、`tests/simulator/*`、docs/12 | 后端/评估，前端只消费结果 | 在不改变默认生产策略的前提下获得可解释 shadow 证据，并支持失败自动回滚 |
| P2-M3 | C2/L5 feature flag、回滚与长期监控闭环 | 当前 `XEYO_L5=project` 且 C2 gate 默认关闭，已有每日 ledger+C2 监控但还没有与 SessionTaskState、EngineEvent、真实发布门禁绑定 | `memory/l5_flag.py`、`memory_stack_eval.py`、`memory/working.py`、`msgtypes/events.py`、`engine/task_state.py`、usage ledger、docs/12 | 后端为主，前端展示指标 | 让 L5 从实验配置变成可灰度、可观测、可回滚的生产策略 |
| P3-M1 | provider-specific cache contract、overlay 版本和质量校准 | `cache_model.py` 的 DeepSeek profile 较真实，OpenAI profile 仍是 future stub；参数 overlay、theta/r 校准和质量模型存在但不是线上自适应闭环 | `memory/simulator/cache_model.py`、`params.py`、`calibration.py`、`quality_model.py`、`metrics.py`、`report.py` | 后端/评估 | 为多厂商缓存与参数演进建立可复现、可审计、不污染生产公式的校准边界 |

**memory 阶段出口：** 只有当真实 replay 的任务结果、用户修正、权限/中断/回溯事件、usage/cost 和 compression action 能按 `session_id + turn_id` 对齐，且 shadow/AB 通过既定 gate 并具备回滚路径时，才考虑扩大 feature flag；在此之前保持 `project` 默认模式和 C2 gate 关闭。

## 七、P2：Java ToolRuntime 的正确实施方式

Java 当前不是已有接缝等待接入，而是**前基础设施阶段**。`pom.xml` 只有 Java 21 编译插件；`JsonRpcServer.java`、`RpcRequest.java`、`RpcResponse.java`、`ToolRequest.java`、`ToolResult.java`、`ToolRuntimeServer.java` 和 `ToolRegistry.java` 尚未形成可执行 RPC、schema、测试和打包链路。[18] [19] [20] [21]

Claude 的 Java 方向应被保留为工具后端替换层：Python 继续负责 QueryEngine、上下文、权限和任务生命周期，Java 只负责工具执行和资源隔离。建议严格按下表推进。

| 阶段 | 只实现什么 | 不实现什么 | 通过标准 |
|---|---|---|---|
| P2-J1 协议 | 定义单一 request/result/error/cancel/ready schema，明确 stdout JSONL、stderr 日志和退出码 | 不维护 Python/Java 两份不兼容 schema；不让 Java 做模型循环 | Python 能启动 Java 子进程并完成 health check |
| P2-J2 工具 | 先实现一个低风险 Read 或 Glob 工具 | 不一开始迁移 Bash、Write、Screenshot 或全部工具 | 相同输入产生结构化结果和错误 |
| P2-J3 接入 | 在 Python ToolRegistry 增加可配置 Java adapter | 不修改 QueryEngine turn 循环和上下文模型 | QueryEngine 不知道工具由哪种后端执行 |
| P2-J4 取消与权限 | 透传 request id、cancel、timeout 和权限上下文；权限仍由 Python gate 决定 | 不让 Java 自己决定是否允许工具 | 停止、拒绝和超时可正确收口 |
| P2-J5 可靠性 | 测试进程重启、坏 JSON、超时、半关闭 stdout 和版本不兼容 | 不急于做多租户、Kubernetes 或插件市场 | Java 崩溃不会让 QueryEngine 永久 busy |

## 八、P3：微信深化、MCP、LSP、多 Agent 与更多工具

iLink 应继续作为“入口适配器 + 事件镜像 + peer 队列”维护；File Helper 仍只输出最终结果。扩展能力必须服从统一事件、SessionTaskState、permission、workspace 和预算语义。

| 能力 | 当前真实状态 | 建议顺序 |
|---|---|---|
| iLink | 已有 peer session、context token、长轮询、队列、事件游标、超时恢复和测试 | P0 事件统一后补审批、任务状态、停止、重试和断线恢复 |
| File Helper | intentionally thin final-only，浏览器适配层较完整 | 只补最终结果/错误/投递可靠性、DOM fixture 和告警，不做完整生命周期镜像 |
| MCP | 工具目录有接缝或空壳，但不是当前稳定性阻塞项 | P0/P1 稳定、能力矩阵和权限契约冻结后，先接入一个真实 MCP，并复用 Tool contract |
| LSP | 当前为 schema/空壳接缝 | 等工具协议、任务状态和 workspace 作用域稳定后再做一个真实诊断/跳转能力 |
| 多 Agent | `AgentTool`、`SendMessage`、Task 工具未实现，缺父子任务、取消传播和资源预算 | 先完成 parent/child TaskState、预算、权限继承和 workspace 隔离，再做单一子 Agent 场景 |
| 更多脚手架工具 | 主要是 schema + `not_implemented` | 暂停新增；只有真实用户任务和完整 contract test 证明收益时才实现 |

## 九、从当前到完整落地的周期化路线

以下周期是**工作时间盒和依赖顺序**，不是对日历日期的承诺。若只有一名开发者，可把每个周期拆成两个子周期；若有前后端并行人员，仍必须按阶段出口推进，不能因为 UI 已完成就绕过后端状态协议。每个周期都要求先补契约测试，再改实现，并保留可回滚提交。

| 周期 | 建议时间盒 | 优先级 | 目标与主要工作 | 依赖 | 周期出口 |
|---|---:|---|---|---|---|
| C0：基线冻结与工程准备 | 0.5–1 周 | P0 | 固定当前真实工具矩阵、事件旧协议兼容范围、现有测试基线、Python/Node/Java 版本；明确 `OfflineReplayRoute` 仅为 UI 性能 bench，建立真实协议 E2E 与 bench 的分层；补依赖锁定策略、最小 CI 检查、源码/配置清单和 feature flag 清单 | 无 | 在干净环境可重复运行核心 Python/前端测试；bench 与真实 E2E 报告分开；任何新增工具、事件和配置都有变更记录；旧文档目标与当前代码状态分离 |
| C1：事件协议基线 | 1–2 周 | P0 | 设计并实现 EngineEvent envelope、schema version、session/turn/event id、排序、去重、未知事件策略；由 QueryEngine 发布，FastAPI、HTTP bridge、JSONL bridge、iLink、remote 和前端适配 | C0 | 同一 turn 在所有入口可关联；旧 SSE/JSONL 客户端仍可用；重复和乱序事件有 contract test |
| C2：任务状态与 workspace authority | 2–3 周 | P0 | 新建 SessionTaskState；将 queued/running/waiting_permission/stopping/stopped/succeeded/failed 与 Todo 三态分离；消除模块全局 cwd；验证 Tauri `XEYO_CWD` 与 active workspace 的覆盖、端口和 dev/release resource 路径；为 SessionState/MessageStore 增加向后兼容的 task/turn/revision 身份、任务快照和事件 cursor 接缝 | C1 | 两个并行 session 不串 cwd；Tauri workspace 与后端 root 一致；刷新、重启、排队、停止、异常均能恢复任务快照和 cursor；坏行、版本不兼容和半恢复状态有显式结果 |
| C3：权限回流与工具边界 | 2–3 周 | P0 | 实现 pending store、permission request id、resolve/resume/timeout；冻结 ENABLED/SCAFFOLD/default registry；为真实工具补 execute/error/cancel/permission contract | C2 | Write/Bash/Screenshot/SendToWeChat 可确认、拒绝、超时；默认 registry 不暴露 scaffold；拒绝后 turn 可继续 |
| C4：远程通道与前端事件投影 | 2–3 周 | P0 | 把 FinalOnlyRunner/JobStore 映射到 TaskState；补 `turn_id`、状态版本、停止/权限原因和 cursor/replay；iLink 增加 status/permission/stop/retry；File Helper 保持 final-only，并将 `remote_deliver` 作为可观测的副作用投递层；前端以统一 reducer、task snapshot 和 cursor 替代多处局部猜测；ContextPasture 作为下游展示 adapter 接收标准 context/task 投影，不再依赖独立旁路解释核心状态 | C1–C3 | 本地、remote、iLink 和 File Helper 对同一 turn 给出一致结果；刷新、切 session、断线、重复事件不会串投影；进程重启和广播丢失时可 reset/replay；文件投递失败不伪装成任务失败或成功；pasture 等展示组件不改变权威状态；现有前端测试全通过 |
| C5：治理、回溯和安全 | 2–4 周 | P1 | 后端审计日志、ActivityLog 对齐、rollback 事务补偿、policy/workspace 安全、CORS、从单一 remote token 演进到 session/peer/role scope、resolve 鉴权、Tauri capability 分区、凭据原子写入和敏感媒体保留策略；冻结 provider/error contract，补错误码、request id、retryable 分类、退避/熔断和安全重试边界 | C2–C4 | 危险操作可解释、可限制、可追溯；rollback 部分失败可恢复；remote API 按 session/peer/role 受控；桌面 capability 最小化；Provider 断流/限流/未知异常能分类并且不重复工具副作用 |
| C6：端到端验收与可重复交付 | 2–3 周 | P1 | 补跨入口 E2E、断线 replay/reset、权限等待、重启恢复、File Helper/iLink fixture；为 JSONL session/transcript 做并发写、损坏、`fsync`/恢复和 schema migration 验收；建立 CI、依赖锁定、分层 readiness、端口冲突处理、Tauri 资源打包、capability 审查、Windows 签名/制品校验和发布说明；明确 SessionPool 只能单实例还是具备持久 lease 的支持矩阵 | C5 | 干净机器或标准环境可安装、启动、健康检查、升级/回滚；核心场景有自动验收报告，不依赖手工判断；多 worker/副本不会在未验收时被误开放 |
| C7：memory 生产 parity 与 shadow | 3–5 周 | P2 | 建立 simulator/production projection parity；把 `kv_cache_probe`、usage、compression action、EngineEvent、TaskState 和真实 session replay 关联；provider-neutral shadow，不改变默认策略 | C4、C6 | 仿真与生产投影可对账；每个 turn 可解释 token、hit/miss、cost、action 和任务结果；shadow 失败不影响默认路径 |
| C8：L5/C2 evidence gate | 3–6 周 | P2/P3 | 将真实任务成功率、用户 correction、permission/abort/rewind、usage/cost 纳入 gate；补持续 ledger、灰度 flag、自动回滚和 provider calibration；只有 gate 通过才扩大 L5 | C5、C7 | `verdict_ready`、成本、质量、任务结果、回滚信号均可审计；默认 `project`/C2 off 仍是安全回退；扩大 flag 有明确门槛 |
| C9：Java 最小 ToolRuntime | 3–5 周 | P2 | 定义统一 JSONL/RPC ready/request/result/error/cancel；Java 实现 Read 或 Glob；Python adapter 透传权限、取消、超时和版本；补坏 JSON、崩溃和重启测试 | C3、C6 | Java 工具可插拔、可停止、可超时；Java 崩溃不会让 QueryEngine 永久 busy；QueryEngine 不感知执行后端 |
| C10：MCP/LSP 首个真实集成 | 4–6 周 | P3 | 先接一个真实 MCP 或 LSP；复用 Tool catalog、permission、workspace、event、audit、cancel；验证进程隔离和能力声明 | C3、C5、C9 | 新平台能力不改变主循环和统一状态；未授权、超时、断线、工具失败均有统一事件和审计 |
| C11：多 Agent 与 Task 能力 | 6–10 周 | P3 | 设计 parent/child session、TaskState 树、取消传播、预算、权限继承、workspace 隔离、结果回传和子任务恢复；先实现一个受限单子 Agent场景 | C2、C3、C5、C9、C10 | 父子任务可观察、可停止、可恢复、预算不越界；子 Agent 不能绕过 parent policy 或 workspace authority |
| C12：完整产品化与持续运营 | 持续迭代 | P1/P3 | 版本兼容、迁移、反馈、回滚、性能预算、崩溃诊断、可观测指标、文档、示例、发行渠道、备份恢复和安全响应；按真实用户任务继续增加工具 | C6 及所有核心出口 | XEYO 可安装、可升级、可回滚、可诊断；新版本有兼容策略和发布门禁；功能扩展不破坏统一协议 |

### 9.1 周期开发的固定节奏

每个周期建议采用“基线—契约—最小实现—故障注入—跨入口验收—文档收口”的固定节奏。第一步固定已有测试、日志和 feature flag；第二步先写 schema、状态转移表和 contract test；第三步只实现一条最小可用路径；第四步主动注入重复、乱序、超时、取消、重启、坏 JSON、权限拒绝和部分失败；第五步在本地、remote、iLink 和 Tauri 至少选择两种入口验收；最后把事实、非目标和下一周期出口写回 docs，而不是把实验结论留在聊天记录中。

每个周期必须保留四类交付物：实现提交、契约/回归测试、可观察的验收报告和回滚说明。若某周期没有达到出口，应冻结在当前 feature flag，不得通过修改文档把未完成能力写成已完成。

### 9.2 周期之间的硬依赖

| 后续能力 | 必须先完成 | 原因 |
|---|---|---|
| Permission ASK | EngineEvent、SessionTaskState、workspace/session identity | pending 请求必须能绑定到唯一 turn，并且 resolve 不能串 workspace |
| remote/iLink 状态镜像 | EngineEvent、TaskState、JobStore 映射 | 通道不能继续猜测 queued/running/permission/stopped 的含义 |
| 前端 reducer | EngineEvent、event cursor、task snapshot | 没有稳定身份就无法处理乱序、断线和刷新恢复 |
| rollback 端到端 | TaskState、revision、审计事件 | 回溯的部分成功、重试和恢复必须有权威状态 |
| memory L5 灰度 | 真实任务结果、usage、permission/rewind 事件、回滚 | 仅有 token 节省和代理 Q/D 不能证明任务质量不下降 |
| Java/MCP/LSP | Tool contract、permission、workspace、cancel、audit | 扩展后端不能绕过 Python 的安全和生命周期控制 |
| 多 Agent | parent/child TaskState、预算、权限继承、workspace 隔离 | 没有这些约束会把一个 session 问题扩大为多 Agent 资源和安全问题 |

## 十、分阶段的最终验收定义（Definition of Done）

| 验收层 | 必须证明什么 | 典型证据 |
|---|---|---|
| 核心运行 | QueryEngine 继续完成模型—工具回流、停止、异常和恢复 | Python 单测、跨重启测试、任务状态转移测试 |
| 协议一致性 | 所有入口能关联同一 session/turn/event，重复和乱序不造成重复副作用 | envelope contract、HTTP/SSE/JSONL/iLink fixture、replay 测试 |
| workspace 与安全 | 并行 session 不串 cwd；permission 默认拒绝超时；危险工具经过可审计授权 | 并发测试、权限 pending/resolve 测试、路径逃逸与 policy 测试 |
| 前端可靠性 | UI 是事件投影，刷新/切换/断线后不出现孤儿 loading、重复工具行或错误 session 内容；bench 回放不得被当作真实协议证明 | 现有 store/projection 测试、IndexedDB hydrate 测试、跨入口真实 E2E、独立 `OfflineReplayRoute` 性能报告 |
| 通道可靠性 | iLink 可恢复、可停止、可镜像；File Helper final-only；远程文件投递失败可见、可重试或明确进入副作用失败状态 | channel fixture、长轮询/队列/回声/二维码、cursor/replay、投递重试与 shutdown drain 测试 |
| 回溯与数据 | rollback 的 preview/execute/冲突/部分失败可恢复，消息、revision、事件和审计一致 | `rewind` 集成测试、故障注入、恢复报告 |
| memory 质量 | L5/C2 只有在真实任务质量、成本、命中和回滚 gate 通过后才灰度 | replay/shadow/AB report、每日 ledger、docs/12 gate 记录 |
| 发布交付 | 干净环境可构建、安装、健康检查、升级和回滚；制品可校验、签名状态明确；运行日志和副作用投递状态可诊断 | CI artifact、Tauri build、版本清单、安装测试、release notes、metrics/retention 验收 |
| 平台扩展 | Java/MCP/LSP/Multi-Agent 复用同一工具、权限、workspace、事件和 task state 契约 | adapter contract、取消/超时/崩溃测试、父子任务验收 |

## 十一、现在明确不应做什么

现在不应重新实现 compact，因为 C0/C1/C2、投影和压缩决策已经存在；应把工作改为契约收口和测试。也不应把 TodoStore 简单改名为 TaskState，因为任务生命周期、权限等待、远程 job、停止和恢复都超出了 Todo 文本范围；TodoStore 当前的精确边界是进程内、默认 key 为 `default` 的三态清单，未来才需要更细的 agent 隔离。[40] [41]

现在不应把 SessionPool busy/lease 当作大缺口，也不应重写已经有稳定测试的 chatStore 主链路、IndexedDB、Settings/profile、Sidebar、RemoteQrPanel、usage 双源策略、`groupTranscript`、`toolActivity`、`streamMarkdown`、`remoteStore` 或 iLink 基本通道。应在这些能力之上补统一事件和权威状态。[27] [28] [29] [33] [34] [35] [38] [39]

现在不应把 File Helper 改造成 iLink 的完整镜像；这会扩大通道复杂度而不增加其 final-only 产品价值。也不应在三套入口协议尚未统一、cwd 仍是模块级全局变量、Tauri workspace 注入关系未验证、Tauri capability 尚未按最小权限审查、remote 仍使用单一共享 token、ASK 尚不能恢复、默认工具能力矩阵未冻结之前，继续增加 MCP、LSP、多 Agent、更多工具或完整 Java runtime。

memory/L5 也不应被当作“已有算法就直接上线”：离线控制面和在线 probe 是证据资产，不是生产默认策略。没有真实任务质量、持续 ledger、统一事件关联、shadow/AB gate 和回滚路径时，保持 `XEYO_L5=project` 与 C2 gate 默认关闭。[24] [25] [26]

最后，不应把“本地能启动”当作“项目已落地”。缺少依赖锁定、CI、健康检查、Tauri 资源与签名、制品校验、升级/回滚、数据迁移和运行监控时，XEYO 仍处于可开发状态而非可持续交付状态。[42] [43] [44] [45]

## 十二、可执行工作包与 PR 拆分

建议每个 PR 都先写契约测试，再改实现；每个工作包都必须有明确非目标和回滚方式。PR-S1 至 PR-S9 保留上一版已确认的主线，新增工程化和长期平台 PR，避免把短期稳定性工作与远期实验混成一次大改。

| PR | 内容 | 主要文件 | 前端/后端范围 | 验收与收益 |
|---|---|---|---|---|
| PR-S0 | 基线、依赖、秘密卫生和 CI 冻结 | `python/pyproject.toml`、`python/requirements.txt`、`gui/package.json`、`gui/package-lock.json`、启动脚本、`.env.example`、`.gitignore`、README、CI 配置、SBOM/secret-scan 配置 | 全栈/交付/安全 | 干净环境可重复运行核心测试；建立版本、feature flag、依赖锁定、秘密扫描、平台矩阵和制品基线；运行时凭据不进入源码、日志或测试附件 |
| PR-S1 | 统一事件 envelope 与三套入口适配 | `python/msgtypes/events.py`、`server/app.py`、`bridge/http.py`、`bridge/__main__.py`、`engine/query_engine.py`、`gui/src/lib/api.ts`、类型与事件测试 | 前后端 | 所有入口关联同一 turn/event；旧协议兼容、未知事件安全 |
| PR-S2 | SessionTaskState 与 session/workspace/Tauri 作用域 | 新增 `python/engine/task_state.py`；修改 `query_engine.py`、`query_loop.py`、`session/state.py`、`session/persistence.py`、`session/message_store.py`、`session/hydrate.py`、`session/record_transcript.py`、`session_pool.py`、`session/cwd.py`、`workspace_fs.py`、`jobs.py`、`gui/src-tauri/src/lib.rs` | 前后端 | 并行 session 不串 cwd；Tauri workspace 不被 Python 根覆盖；任务、message revision、事件 cursor 和恢复完整性可查询；坏行不再静默成为未知状态 |
| PR-S3 | Permission ASK pending/resolve/resume | `permissions/gate.py`、`filesystem.py`、`types/permissions.py`、`tool_registry.py`、`query_loop.py`、`server/app.py`、`chatStore.ts`、iLink service | 前后端与微信 | request 单次处理；桌面/iLink 可确认拒绝；超时默认拒绝；拒绝后 session 可继续 |
| PR-S4 | 工具能力矩阵、模型适配、文件事务和 contract tests | `tools/catalog.py`、`stub.py`、`tool_registry.py`、`tools/orchestration.py`、`tools/fileio/*`、`model/client.py`、`model/chunks.py`、`model/openai_compat.py`、`model/deepseek.py`、`common/errors.py`、真实/空壳工具、`tests/test_catalog.py`、模型/文件工具测试、前端 capability 类型 | 后端为主，前端同步 | 默认 registry 不暴露 scaffold；真实工具执行/错误/取消/权限边界可回归；模型适配通过 py_compile、fake/真实 SSE contract；建立稳定 error_code/retryable/request_id，Provider 断流/限流重试不重复副作用；文件写入、rewind journal 半失败、hash/mtime/line-ending 和 abort 语义可回归 |
| PR-S5 | 前端事件 reducer、远程投影、本地游标持久化和真实 API 验收 | `api.ts`、`api.stream.test.ts`、`types.ts`、`chatStore.ts`、`remoteStore.ts`、`db.ts`、`ActivityLog.tsx`、`SessionTodoDock.tsx`、`OfflineReplayRoute.tsx` | 前端为主，依赖 S1/S2 | 现有 SSE 解析、store/projection 测试继续通过；新增统一 envelope、乱序、重复、断线、刷新、切 session、权限 pending 和任务终态测试；`api.stream.test.ts`、bench 回放报告与真实协议 E2E 分层，IndexedDB 只保存投影快照/cursor，不冒充后端任务账本 |
| PR-S6 | remote/iLink 对齐与 Todo 兼容写入 | `channels/api.py`、`channels/runner.py`、`channels/jobs.py`、`channels/ilink/api.py`、`ilink/service.py`、`channels/filehelper/api.py`、`filehelper/service.py`、`todo_write_tool.py`、task/todo 投影 | 前后端与通道 | iLink 支持 status/stop/permission；File Helper 仍 final-only；JobStore 映射 turn/job；SSE 丢失后可按 cursor/replay 恢复，且不把 JobStore 扩成第二套权威 TaskState |
| PR-S7 | rewind 事务补偿、审计、policy、remote auth 与桌面 capability 安全边界 | `rewind/service.py`、revision/snapshot/journal/context、`server/app.py`、`channels/api.py`、`channels/auth.py`、`channels/remote_deliver.py`、`chatStore.ts`、`gui/src-tauri/capabilities/default.json`、新增 `audit/log.py` 和 policy 配置 | 前后端/桌面壳 | rollback 部分失败可恢复；ActivityLog 可追溯后端事件；单一 remote token 不再承担全部权限；危险操作受 policy/auth/capability 保护；文件投递副作用有独立状态、失败原因和审计，不改变核心任务终态 |
| PR-S8 | memory projection parity、shadow/AB 和 evidence gate | `memory/simulator/*`、`engine/compact.py`、`memory/working.py`、`l5_flag.py`、memory scripts、`kv_cache_probe.py`、docs/12 与测试 | 后端/评估，前端消费结果 | 默认 project/C2 off 不变；真实 replay、usage、任务结果、权限/回溯事件按 session/turn 对齐 |
| PR-S9 | Java 最小 JSONL/RPC 真实链路 | `java/pom.xml`、Java rpc/tools、Python ToolRegistry adapter、Java/Python 集成测试 | 后端为主 | 一个 Read/Glob 工具支持 ready/result/error/cancel/timeout；Java 崩溃不会造成永久 busy |
| PR-S10 | 发布工程、真实 readiness、桌面硬化与运维闭环 | Tauri 配置、Cargo、`src-tauri/src/lib.rs`、`src-tauri/capabilities/default.json`、生成 ACL schema、`tauri.ts`、`wait_health.py`、`smoke_engine.py`、启动脚本、CI、签名、SBOM、artifact manifest、metrics/retention、通道广播/投递观测、`session/*`、`server/session_pool.py` | 全栈/桌面/交付 | 可重复构建、依赖与制品可追溯、安装、真实 readiness、升级/回滚、故障诊断、capability 审查和制品校验；能区分广播丢失、任务失败、会话恢复不完整与微信文件投递失败，并在关停时不遗失可追踪状态；固定坐标截图只作为辅助证据；未完成持久 lease 前明确单实例支持矩阵 |
| PR-S11 | 首个真实 MCP 或 LSP 集成 | tool catalog、permission、workspace、event、audit、adapter 和集成 fixture | 后端为主，前端投影 | 扩展能力不绕过核心权限、状态、取消和审计契约 |
| PR-S12 | 受限多 Agent/Task 能力 | 新增 parent/child TaskState、预算、取消传播、权限继承、workspace 隔离、结果回传 | 前后端 | 单一受限子 Agent 可观察、停止、恢复且不越过 parent policy |
| PR-S13 | 持续产品化与兼容迁移 | session/task/event/message schema migration、版本策略、备份恢复、凭据轮换、崩溃诊断、Provider/错误契约兼容、文档、发行渠道 | 全栈/运营 | 新版本可升级、回滚和迁移；用户数据、任务快照、事件 cursor、错误码和供应商状态兼容策略明确；恢复演练能区分可修复数据损坏与必须人工介入的 recovery_required |

## 十三、企业级上线强化门禁（本轮新增事实）

本轮继续核对了构建配置、启动脚本、Tauri 生成权限、运行时状态文件、依赖锁文件、桌面验证脚本和源码清单脚本。它们没有推翻前文对核心引擎、事件、任务状态和通道的判断，但把“可上线”的工程边界进一步具体化：**源码能运行不等于制品可交付，脚本能截图不等于功能已验收，工作树存在凭据不等于具备秘密管理，HTTP 2xx 不等于服务已就绪，生成 schema 也不等于最小权限已实施**。

### 13.1 本轮新增企业级阻断项

| 优先级 | 上线要求 | 当前真实事实 | 主要涉及文件 | 范围 | 为什么必须处理 | 预期收益与出口 |
|---|---|---|---|---|---|---|
| P0 | 秘密、凭据和运行数据脱离源码工作树 | `python/.xeyo_ilink/credentials.json` 属于运行时凭据文件；`.env.example` 同时覆盖本地、模型、远程通道和 File Helper 配置；`.gitignore` 只是版本控制层的忽略意图，不能提供注入、轮换、审计或泄漏检测闭环；File Helper 的 `seen_index.json` 也只是本地去重状态，不是审计日志 | `python/.xeyo_ilink/credentials.json`、`python/channels/ilink/store.py`、`python/.xeyo_filehelper/seen_index.json`、`.env.example`、`.gitignore`、启动脚本 | 后端/运维/安全 | 一旦凭据、用户内容或通道状态进入备份、日志、截图或错误上报，企业级租户就无法证明最小暴露和可撤销性 | 采用秘密管理器或受保护凭据存储、原子写入、schema/version、轮换/吊销、启动时泄漏扫描和脱敏；源码树与备份中不再承载可复用生产凭据 |
| P0 | 依赖可重复构建与供应链证明 | `requirements.txt`、`pyproject.toml`、`gui/package-lock.json`、`gui/src-tauri/cargo.toml` 分别描述 Python、Node 和 Rust 依赖，但当前还没有统一的锁定、SBOM、license/CVE、来源和制品 provenance 门禁；`list-source.ps1` 也只列部分源码扩展名，不能证明完整覆盖 | `python/requirements.txt`、`python/pyproject.toml`、`gui/package.json`、`gui/package-lock.json`、`gui/src-tauri/cargo.toml`、`list-source.ps1` | 全栈/CI/发布 | 没有依赖与制品证明，无法复现构建、定位漏洞、判断许可证风险或确认发布包是否来自审查过的提交 | C0 生成锁定依赖清单、SBOM、license/CVE 报告、源码与制品 manifest；依赖漂移、未审查二进制和高危漏洞阻断发布 |
| P0 | 桌面最小权限、来源隔离和签名 | 手写 `default.json` 只配置 main window 的 `core:default`、window、shell-open、dialog；生成 ACL/capability schema 是格式规则，不是项目已实施的安全策略；当前还缺 workspace/filesystem 分区，CSP/签名/升级链仍需在制品阶段验证 | `gui/src-tauri/capabilities/default.json`、`gui/src-tauri/gen/schemas/acl-manifests.json`、`capabilities.json`、`windows-schema.json`、`gui/src-tauri/tauri.conf.json`、`gui/src-tauri/src/lib.rs` | 桌面/前端/发布 | 桌面壳同时拥有本地文件、后端启动和远程配置入口时，过宽 capability 或未签名更新会把 workspace 风险扩大为终端风险 | 按窗口和功能拆分 capability，显式列出允许命令、来源和路径；CSP、签名、更新通道和安装包完整性均有自动验收 |
| P1 | 真实 readiness、进程治理和故障退出 | `wait_health.py` 主要轮询 HTTP 2xx；`smoke_engine.py` 使用 fake backend/echo；`start-xeyo.bat`、`xeyoq.bat` 和 `start-remote-tunnel.bat` 是开发/本地包装脚本，不是服务管理、端口租约、依赖探活、优雅关停和日志轮转系统 | `python/scripts/wait_health.py`、`python/scripts/smoke_engine.py`、`start-xeyo.bat`、`xeyoq.bat`、`start-remote-tunnel.bat`、`gui/src-tauri/src/lib.rs` | 后端/桌面/运维 | “端口响应”可能掩盖模型、持久化、通道或迁移未就绪；进程残留和端口冲突会造成错误实例、数据串线和难以诊断的发布故障 | 分离 liveness/readiness/startup probe，检查依赖、迁移、协议版本和 workspace；建立服务托管、PID/实例身份、超时、shutdown drain、结构化日志和非零退出码 |
| P1 | 真实 E2E 与视觉采样分层 | `capture-xy-*.ps1` 主要通过固定坐标、SendKeys 和截图验证；没有稳定 selector、业务断言、退出码治理或秘密脱敏。`OfflineReplayRoute`/chat replay fixture 直接注入前端 store，不含真实 event envelope、模型或远程依赖 | `capture-xy-*.ps1`、`inspect-node.ps1`、`inspect-scroll.ps1`、`gui/src/bench/OfflineReplayRoute.tsx`、`gui/public/bench/chat-replay.json`、`gui/scripts/fixtures/chat-replay.json` | 前端/桌面/测试 | 截图可以证明局部视觉状态，不能证明发送、流式完成、权限恢复、文件写回、升级或协议一致性；测试截图还可能泄露凭据和用户内容 | 视觉采样保留为辅助证据；新增基于稳定 selector/API 的真实 E2E、断言、失败诊断、敏感数据脱敏和制品保留策略；bench 报告与协议 E2E 分开 |
| P1 | 远程副作用与本地缓存可诊断、可清理 | `remote_deliver.py` 是异步文件投递副作用层，失败仅 warning；File Helper `seen_index.json`、CRX/extension cache 元数据和通道状态文件没有统一保留、清理、租户隔离和审计策略 | `python/channels/remote_deliver.py`、`python/.xeyo_filehelper/seen_index.json`、`component_crx_cache/metadata.json`、`extensions_crx_cache/metadata.json`、`channels/*/broadcast.py`、`channels/jobs.py` | 后端/通道/运维 | 任务完成、消息送达、文件投递、缓存存在和审计完成不是同一件事；若不区分，企业用户无法判断数据是否真的离开系统或是否应重试 | 为副作用建立独立 delivery state、重试/死信、shutdown drain、保留期限、清理任务、审计关联和告警；缓存只保存必要元数据并支持按 workspace/租户清除 |
| P2 | 平台与资源支持矩阵可证明 | `gui/src-tauri/icons/android/mipmap-anydpi-v26/ic_launcher.xml` 等资源存在，并不代表 Android 或其他平台已构建、签名和验收；`gen_icons.py` 的资源输出还需要制品清单和格式检查 | `gui/src-tauri/icons/*`、`gui/src-tauri/gen_icons.py`、`tauri.conf.json`、CI/release 配置 | 桌面/发布 | 隐含支持未验证平台会造成安装、更新和客户预期风险 | 建立“支持/实验/不支持”平台矩阵；每个平台均有资源、构建、签名、安装、升级、回滚和 smoke 证据，未达标平台不进入发行说明 |

| P1 | 会话恢复完整性与数据一致性 | 当前会话恢复只重建 JSONL messages；`SessionState`、`MessageStore`、hydrate 和 transcript 不能共同证明 task/turn/event/permission/revision 的完整恢复，坏行还可能静默丢失，写入缺少文件锁与 `fsync` | `python/session/*`、`python/msgtypes/message.py`、`engine/query_engine.py`、恢复/并发/损坏注入测试 | 后端/数据/测试 | 企业用户重启、升级或故障恢复后必须知道任务是否继续、重复或需要人工介入；半恢复状态不能进入 GA | schema/integrity/repair report、消息版本与幂等写入、任务快照和事件 cursor 可恢复；损坏显式告警并可人工修复 |
| P1 | Provider 可靠性与错误可观测性 | `DeepSeek` 客户端无重试/退避/熔断和抽象 provider contract；错误映射无稳定 code/retryable/request_id，无法统一驱动 UI、审计、告警与安全重试 | `python/model/deepseek.py`、`model/*`、`common/errors.py`、`query_loop.py`、SSE/故障注入测试 | 后端/运维/前端 | 模型断流、限流和服务端错误是上线常态；若没有错误身份和副作用幂等，自动重试可能重复写文件或外发数据 | 错误分类、请求关联、供应商退避和断流恢复有可复核证据；重试只作用于安全边界内的 provider 请求 |
| P1 | SessionPool 与部署拓扑边界 | SessionPool 的锁和 lease 是进程内，不能支撑多 worker/副本；当前启动链也没有持久任务租约、实例身份和关闭 drain | `server/session_pool.py`、`channels/jobs.py`、`channels/runner.py`、启动脚本、部署/readiness、故障注入测试 | 后端/运维/发布 | 未明确拓扑就横向扩展会导致同一 turn 重复执行、stale lease 误接管、预算重复累计和重启丢状态 | 在 durable lease 完成前以单实例矩阵限制发布；完成后提供幂等接管、排空关停、实例级指标和多副本验收 |

### 13.2 企业级上线的分层门禁

| 门禁层 | 必须满足的事实 | 必须保存的证据 | 未满足时的处理 |
|---|---|---|---|
| G0：源代码与秘密卫生 | 工作树无可复用凭据；秘密只通过受控注入；源码清单、运行数据、构建目录和资源范围明确 | secret scan、`.gitignore` 检查、配置 schema、轮换记录、源码范围报告 | 禁止打包、发布和上传诊断制品 |
| G1：依赖与制品供应链 | Python/Node/Rust 依赖可重建；提交、依赖、构建环境和制品一一对应；漏洞与许可证风险有结论 | SBOM、lockfile 校验、CVE/license 报告、构建日志、artifact manifest、provenance | 标记阻断或经批准的风险例外，不得以本地成功构建替代 |
| G2：运行与协议 | readiness 不仅是 HTTP 2xx；真实模型/持久化/通道依赖可诊断；统一事件、任务、权限、cwd 和 cursor 验收通过 | 启动日志、健康探针报告、跨入口 contract/E2E、故障注入和恢复报告 | 只能进入内部测试，不能作为企业生产版本 |
| G3：桌面安全与用户数据 | capability 按最小权限配置；CSP、签名、更新、工作区路径和本地数据加密/清理策略明确 | capability review、签名验证、安装升级回滚、路径隔离和数据清理测试 | 禁止面向不受控终端发布 |
| G4：运维与响应 | 指标、结构化日志、审计、告警、保留、备份恢复、投递重试和 shutdown drain 可运行 | dashboard/alert 规则、审计查询、备份恢复演练、delivery/retention 报告 | 只能灰度，且必须有人工值守与明确回退 |
| G5：业务验收 | 至少一个真实企业任务在本地、远程和桌面入口完成；危险操作、权限拒绝、断线、升级和回滚均有证据 | 脱敏 E2E 报告、用户验收记录、已知限制、回滚演练和发布说明 | 只发布给内部试点，不宣称企业级 GA |

### 13.3 新增事实对应的周期与工作包

本轮新增事项不另起一条脱离主线的功能路线，而是嵌入既有 C0–C12 和 PR-S0–S13。C0 必须把 `list-source.ps1` 降级为源码盘点辅助，同时建立 SBOM、secret scan、依赖锁定、支持平台矩阵和真实 E2E/bench 分类；C5 必须完成凭据轮换、Tauri capability 分区、CORS/remote scope、通道缓存与投递保留策略；C6 必须把 `wait_health.py` 的浅层轮询升级为分层 readiness，把 fake smoke 与真实服务烟测分离，并以稳定 selector/API 断言替代固定坐标截图作为主验收；C12 必须把升级/回滚、备份恢复、数据保留、漏洞响应、事故演练和制品 provenance 纳入持续运营。PR-S0、PR-S7、PR-S10 和 PR-S13 分别承载这些门禁，不得把它们留作发布前临时手工检查。

### 13.4 已验证成熟能力与不重复投资

后续周期应把已经有真实实现和回归证据的部分当作基线，围绕接缝做增量增强，而不是重新实现同一功能。当前应保留以下判断：

| 已确认基线 | 真实证据 | 后续只补什么 | 不应再做什么 |
|---|---|---|---|
| memory 治理、simulator 与 C1/C2 压缩边界已有离线控制面和大量回归 | `test_governance.py`、`test_runtime_c2.py`、memory simulator tests | 上下文投影契约、模型适配联测、证据门禁与生产观测 | 不把 memory 或 compact 重新列为 P0 空白 |
| rewind 后端事务骨架已经成熟 | `test_rewind_service.py`、`test_rewind_api.py`、`test_rewind_query_engine.py`、`test_rewind_file_tools.py` | 普通 turn 接入 revision/journal、入口/UI 状态、补偿可观测、与统一 approval/task 协议关联 | 不把 RollbackService 重新设计成全新事务系统 |
| 文件浏览与危险路径基础防护已有边界 | `workspace_fs.py`、`test_permissions.py`、文件工具测试 | 真实 pending approval、工具半失败补偿、跨进程 ReadFileState、abort/子进程终止和 contract tests | 不重复重写已有 containment、symlink 和危险路径基础规则 |
| 前端 IndexedDB、remoteStore、QR 面板和 SSE 解析已有产品化基础 | `db.ts`、`remoteStore.test.ts`、`remoteStream.test.ts`、`RemoteQrPanel.tsx`、`api.stream.test.ts` | 与后端统一 envelope、task/approval/revision、断线恢复和真实 E2E 对齐 | 不把前端投影或 QR 控制面当作后端任务状态机重做 |
| 工具 registry 与安全工具并发策略已有明确守卫 | `catalog.py`、`test_catalog.py`、`orchestration.py`、`test_tool_orchestration.py` | 扩展工具元数据、取消、权限、进度和审计字段 | 不把 scaffold 工具误报为默认能力，也不破坏未知工具默认串行 |
| Java ToolRuntime 目前确实仍为空壳 | `java/pom.xml`、`RpcRequest.java`、`RpcResponse.java`、`ToolRequest.java`、`ToolResult.java`、`Tool.java` | 在核心协议稳定后建设最小 JSONL/RPC、超时、取消和崩溃隔离 | 不把 Java 类名或 Maven 配置当作已完成基础设施 |
| File Helper/iLink 是通道适配和投递副作用，不是第二套 Agent 内核 | `channels/base.py`、`filehelper/service.py`、`filehelper/bridge.py`、`ilink/service.py`、`remote_deliver.py` | 统一 envelope、cursor、delivery state、审计、保留和多租户隔离 | 不把通道 busy、SeenIndex 或 JobStore 当作 SessionTaskState |
| 会话 JSONL 续聊与基础 transcript 是已有基线 | `session/persistence.py`、`session/hydrate.py`、`session/record_transcript.py`、`test_resume_from_disk.py`、`test_record_transcript.py` | schema/integrity、任务快照、事件 cursor、版本迁移、并发写与告警 | 不把会话持久化从零重做，也不把消息 roundtrip 误报为企业任务恢复 |
| DeepSeek SSE 的基础解析和 usage 接收已存在 | `model/deepseek.py`、`test_vendor_models.py`、SSE 测试 | provider 抽象、错误码、重试退避、熔断、断流和安全幂等 | 不重写已有 tool_call buffer 和基础 SSE 解析，不把一次成功请求当作可靠性完成 |
| SessionPool 已有同 session 串行、busy lease、history stash 和 stale reclaim | `server/session_pool.py`、`test_session_pool_busy.py` | 持久 job/lease、跨实例聚合、故障接管和拓扑支持矩阵 | 不重复实现已有进程内 busy 机制，也不把它升级为未验证的分布式调度器 |

### 13.5 企业级上线判定

在统一事件、SessionTaskState、Permission ASK、workspace authority 和远程 scope 尚未完成前，XEYO 不应宣称具备企业级生产能力；即使这些核心语义完成，只要 G0–G5 任一门禁没有可复核证据，状态也只能标记为开发版、内部试点或受限灰度。企业级上线不是把所有 Claude 工具一次性补齐，而是让已支持的核心任务在明确的租户/工作区边界内可重复运行、可停止、可审计、可恢复、可升级和可回滚，并能在故障发生后回答“发生了什么、影响了谁、数据在哪里、如何撤销和恢复”。

## 十四、独立实施化附录：把计划变成可直接执行的工程

前述路线已经回答“先做什么、后做什么”，本附录进一步回答“每一步必须写成什么、如何判定完成、失败后如何回退、谁负责运营”。本节中的阈值是**C0 需要在目标硬件、目标模型和目标部署拓扑上实测并冻结的初始门槛**，不是对当前代码已经达到的性能或可靠性做出的断言。若真实基线不支持某个阈值，必须在 C0 形成书面例外、补充影响评估并降低发布级别，不能静默放宽。

### 14.1 产品边界与发布通道先冻结

在实现更多工具之前，必须先把支持范围写成发布合同。否则同一个“可用”可能同时指本地开发、内部试点、远程单实例和企业 GA，最终导致测试、SLO、数据保留和支持责任都无法判定。

| 发布阶段 | 必须支持的范围 | 明确不承诺的范围 | 晋级条件 |
|---|---|---|---|
| 开发版 | Windows Tauri、本地 Python/Vite、fake/provider contract、单工作区和开发凭据注入 | 多副本、生产数据、企业 SLA、未验收平台 | C0 基线、最小 CI、秘密扫描和可重复本地启动通过 |
| 内部试点 | 一个明确版本的桌面入口、FastAPI/单实例远程入口、受控工作区、有限模型供应商、真实企业任务 | 未完成的多租户、未验收的多副本、MCP/LSP/多 Agent 全量能力 | G0-G3 通过；指定试点用户、数据范围、值守人员和回滚版本 |
| 受限灰度 | 已声明的角色、workspace、通道和工具子集；具备 kill switch、配额、审计和支持矩阵 | 未列入能力矩阵的工具、跨租户共享工作区、无恢复演练的数据类型 | G0-G5 通过，至少一个真实任务完成升级、断线、权限拒绝和恢复演练 |
| 企业 GA | 支持矩阵中声明的平台、入口、角色、模型和数据类型；具备版本兼容、备份恢复、SLO、事故响应和安全响应 | 任何未列入支持矩阵、没有 Owner 或没有证据保留策略的能力 | 发布委员会确认所有阻断门禁、例外和客户沟通材料均已归档 |

每一次发布必须携带一份机器可读的 `support-matrix.yaml` 或等价文件，至少声明 `release_channel`、平台、入口、允许工具、模型供应商、数据区域、租户模式、最大并发、最大文件大小、RPO/RTO、维护窗口和已知限制。支持矩阵不是文档装饰，而是 readiness、前端能力展示、远程授权和客服排障的共同输入。

### 14.2 需求、实现和证据追踪

从 C0 开始，每项不可妥协要求都必须拥有稳定 ID。推荐采用 `REQ-<domain>-<number>`，并维护一张不依赖聊天记录的追踪表；没有测试、指标或运行证据的需求不能标记为 Done。

| 需求 ID | 需求内容 | 权威实现 | 协议/配置 | 自动测试 | 运行证据 | Owner/周期 | 失败后的发布级别 |
|---|---|---|---|---|---|---|---|
| REQ-CORE-001 | 同一 turn 在所有入口可关联、去重和重放 | `engine/query_engine.py`、统一事件发布器 | EngineEvent schema | contract、replay、乱序/重复 E2E | cursor/replay 指标和脱敏样本 | Runtime / C1 | 禁止远程和 GA |
| REQ-SEC-001 | 危险工具的 ASK 可等待、解析、恢复和审计 | `permissions/*`、TaskState、pending store | PermissionRequest、AuditRecord | pending/resolve/timeout/restart | 审批耗时、拒绝率、孤儿请求告警 | Security / C3-C5 | 禁止危险工具灰度 |
| REQ-DATA-001 | 会话损坏不会静默变成错误成功 | `session/*`、repair service | snapshot/integrity schema | 损坏注入、fsync、迁移、恢复 | repair report、recovery_required | Data / C2,C6 | 禁止升级和 GA |
| REQ-OPS-001 | 发布包可复建、可校验、可回滚 | CI、Tauri、artifact pipeline | SBOM、manifest、provenance | clean build/install/upgrade | build and rollback report | Release / C0,C6,C12 | 禁止外部发布 |

实际项目应扩展上述模板，使每个 P0/P1 条目都有对应记录；计划书中的周期出口、PR 和 G0-G5 门禁只在追踪表已闭合时才算完成。

### 14.3 核心状态机、权威来源和不变量

实现前先冻结状态机，避免前端、JobStore、通道和后端各自发明状态名称。状态值可以采用现有兼容名称，但必须由核心定义唯一含义；旧客户端只能通过适配器看到旧投影，不能反向改变权威状态。

| 对象 | 推荐状态 | 合法终态或迁移原则 | 必须保持的不变量 |
|---|---|---|---|
| Task | `accepted`、`running`、`waiting_permission`、`waiting_provider`、`stopping`、`completed`、`failed`、`canceled`、`recovery_required` | `accepted→running`；`running→waiting_permission/waiting_provider/stopping/completed/failed`；`stopping→canceled/failed/recovery_required`；正常终态不可被普通重试覆盖 | 一个 `(tenant, session, task_id)` 只有一个权威 owner；终态带 `completed_at` 和原因；重试产生新 attempt，不覆盖历史事实 |
| Turn | `created`、`accepted`、`streaming`、`waiting_tool`、`waiting_permission`、`completed`、`failed`、`canceled` | 一个 turn 只提交一次；provider 重试不得重新执行已确认副作用工具 | `turn_id`、`attempt_id`、`event_seq` 单调可解释；消息、usage、revision 和审计都能关联到 turn |
| Permission | `pending`、`approved`、`denied`、`expired`、`canceled` | 只能由授权主体解析一次；过期默认拒绝；重启后只能恢复为可见 pending 或明确 `recovery_required` | request hash、资源范围、策略版本、审批人、时间和结果不可篡改；resolve 幂等 |
| Job/Lease | `queued`、`leased`、`running`、`succeeded`、`failed`、`canceled`、`dead_letter`、`recovery_required` | lease 需要 owner、heartbeat、期限和接管条件；部署关闭时先 drain，再释放 lease；丢失 lease 不得直接重跑副作用 | 不允许两个实例同时拥有有效 lease；接管必须有 fencing token；未持久化前只发布单实例 |
| Delivery | `pending`、`sending`、`delivered`、`retry_wait`、`failed`、`canceled`、`dead_letter` | 任务成功不自动等于 delivery 成功；delivery 可独立重试和人工补发；达到重试上限进入 dead letter | 目标 peer、内容 hash、幂等键和结果可审计；敏感媒体不因无限重试永久保留 |

上述状态集合与 14.21 的机器可读迁移表必须保持一一对应；`draining` 是部署排空信号，不是 Job 的持久状态，`queued` 属于 Job 而不是 Task；`Job.succeeded` 只表示 Job 自身成功，不能替代 `Task.completed`，其他对象也不得跨对象复用状态名；旧客户端若仍使用 `stopped`、`succeeded`、`sent`、`retrying` 等名称，只能由兼容 adapter 投影，不能写回权威状态。权威层必须明确为：后端核心状态和 append-only 事件/审计是事实源；数据库或受控持久层保存任务、lease、permission、revision、message 和 cursor；前端 IndexedDB、iLink/File Helper 缓存和 ContextPasture 只能保存投影或临时状态。恢复顺序应为“校验 schema 与完整性 → 读取任务/lease → 恢复 permission/revision/cursor → 重建事件投影 → 允许继续或明确人工介入”，不能先以 UI 中的 loading 状态推断任务是否仍在运行。

### 14.4 最小字段级协议契约

下表不是要求一次性实现全部高级字段，而是规定 C1-C5 必须冻结的最小语义。字段一旦进入持久化、日志或跨入口传输，就必须有 schema version、兼容策略和脱敏规则。

| 契约 | 必填字段 | 关键规则 |
|---|---|---|
| `EngineEvent` | `schema_version`、`event_id`、`tenant_id`、`session_id`、`task_id`、`turn_id`、`event_seq`、`type`、`occurred_at`、`payload` | `event_id` 全局唯一；同一 stream 的 `event_seq` 单调；未知类型可安全跳过但不能静默改变终态；payload 按 type 校验 |
| `TaskSnapshot` | `schema_version`、`task_id`、`session_id`、`state`、`state_version`、`attempt_id`、`owner_id`、`updated_at`、`last_event_seq`、`reason` | 状态更新需 compare-and-set 或等价版本检查；快照不是事件替代品；恢复报告记录缺失和修复 |
| `PermissionRequest` | `request_id`、`task_id`、`turn_id`、`tool_name`、`action`、`resource_scope`、`risk_class`、`request_hash`、`policy_version`、`expires_at` | request hash 绑定实际参数摘要；敏感参数只存脱敏摘要；审批结果只能写一次；默认拒绝超时 |
| `ErrorEnvelope` | `error_code`、`category`、`retryable`、`request_id`、`event_id`、`safe_message`、`provider_code`、`details_ref` | 前端只依赖稳定 code；原始 provider/path 信息进入受控 details；retryable 不能由 HTTP 状态单独推导 |
| `Cursor` | `stream_id`、`last_event_seq`、`snapshot_version`、`issued_at`、`expires_at` | reconnect 先校验 session/peer/role scope；不可用 cursor 必须返回 reset reason，不能默默从错误位置继续 |
| `Idempotency-Key` | `operation`、`scope`、`key`、`request_hash`、`created_at`、`expires_at`、`result_ref` | submit/resolve/stop/rollback/delivery/tool side effect 分别定义作用域；hash 不匹配必须拒绝复用 |

`tenant_id` 在单用户桌面版本也应有明确的单租户默认值，而不是省略字段后再依赖调用方猜测。若当前版本暂不支持真正多租户，应在支持矩阵中写成 `single-tenant`，并禁止通过增加 URL 参数假装完成隔离。

### 14.5 工具与供应商的统一执行合同

所有真实工具和后续 Java/MCP/LSP adapter 必须通过同一 Tool contract。工具合同应把“是否改变外部世界”与“模型是否能调用”分开描述，避免仅凭 schema 或工具名称决定安全性。

| 能力字段 | 规定 |
|---|---|
| 身份 | `tool_name`、`tool_version`、`capability_class`、`required_scope`、`risk_class`、`side_effect_class` |
| 输入输出 | JSON schema、结果 schema、最大结果字节数、artifact 引用、敏感字段路径和展示脱敏规则 |
| 生命周期 | `started/progress/completed/failed/canceled/timed_out`；每个调用绑定 task/turn/attempt/request id |
| 安全 | policy decision、workspace/resource scope、dry-run 支持、审批 request hash、审计事件和禁止自动重试条件 |
| 可靠性 | timeout、abort、子进程/网络终止、幂等策略、重试策略、部分成功和补偿动作 |
| 兼容 | schema version、向后兼容字段、未知字段策略、默认 registry 分层和 feature flag |

Provider contract 同样必须定义 connect、stream、usage、finish、retry、rate limit、timeout、circuit open、resume unsupported 和 unknown error。默认只有无外部副作用的模型读取请求允许自动重试；任何工具调用、文件写入、外发、审批解析和 rollback 操作必须由核心层通过 attempt/idempotency/fencing 明确保护后才可重试。

### 14.6 初始 SLO、容量和资源预算

性能基准不能只使用合成帧或前端 replay。C0 应在声明的硬件、网络、模型、工作区规模和单实例拓扑上建立基线；以下是建议的首个内部试点门槛，所有数值均须在真实基线后确认或调整。

| 指标 | 内部试点初始目标 | 测量范围 | 超标处理 |
|---|---:|---|---|
| readiness 完成时间 | P95 ≤ 30 秒 | 从启动命令到所有依赖可用 | 标记启动失败，禁止接收任务 |
| 首个可见事件延迟 | P95 ≤ 3 秒（不含供应商排队异常） | submit accepted 到首个合法 EngineEvent | 检查 provider、队列、事件发布和前端投影链路 |
| 事件端到端延迟 | P95 ≤ 500 ms | 核心发布到本地/远程消费 | 触发通道与广播告警，不伪造任务成功 |
| 任务终态可恢复率 | ≥ 99.9% 的注入样本有明确终态或 recovery_required | 重启、断线、超时、坏行和 provider 断流 | 阻止升级，生成恢复报告 |
| 重复副作用率 | 0 个未被幂等保护的重复写入/外发 | 故障注入和重试测试 | 立即阻断发布并回滚相关 retry flag |
| 事件丢失率 | 核心持久 stream 为 0；final-only delivery 单独计量 | 事件日志与消费 cursor 对账 | 核心事件丢失阻断；投递丢失进入 retry/dead letter |
| 单实例并发 | C0 以实测基线冻结，初始不承诺多副本 | session、文件工具、provider、内存和 CPU 组合压测 | 超过矩阵上限返回明确 overload，不排队失控 |
| 资源预算 | 建立 CPU、RSS、磁盘增长和日志增长 P95 基线 | 1 小时 soak 与典型企业任务 | 超过预算降级、限流或暂停新增功能 |

这些目标不应被写成营销 SLA。GA 前必须补充可用性、备份、数据恢复、供应商依赖和人工支持窗口，并把 error budget 分配给发布、provider、通道和数据恢复，而不是只测 HTTP 200。

### 14.7 测试、故障注入与证据保留矩阵

计划书已有单测和若干回归，但“企业级”需要把测试层、必测故障和发布门禁一一对应。每个失败测试都必须生成可定位到 commit、环境、schema 版本和脱敏输入的报告。

| 测试层 | 必测内容 | 最低证据 | 发布用途 |
|---|---|---|---|
| Unit/property | 状态迁移、schema 校验、cursor、幂等 hash、路径和权限策略 | JUnit/Vitest/pytest 报告与覆盖趋势 | 每次 PR |
| Contract | Python 核心与 FastAPI、HTTP bridge、JSONL、iLink、前端 reducer、Java adapter | 固定 fixture、版本兼容报告 | C1-C6、每次协议变更 |
| Integration | provider SSE、工具轮次、文件事务、rewind、持久化、真实 readiness | 可重复环境日志与事件/审计对账 | 每次 release candidate |
| E2E | 发送、流式、权限 pending/resolve、stop、刷新、断线、文件写回、delivery、rollback | 稳定 selector/API 断言和脱敏视频/截图 | 试点与 GA |
| Fault injection | provider 断流/限流、进程 kill、磁盘满、锁超时、坏 JSONL、重复事件、乱序、网络分区、秘密缺失 | recovery report、最终状态和无重复副作用证明 | C2-C6、GA 阻断 |
| Load/soak | 并发 session、长 turn、长轮询、文件大结果、日志/缓存增长和多小时运行 | p50/p95/p99、资源曲线、泄漏结论 | 发布容量矩阵 |
| Security | secret scan、SAST/SCA、路径/symlink、SSRF、prompt injection、越权、恶意工具/MCP、更新签名 | 风险清单、修复或例外审批 | G0-G3 |
| Upgrade/restore | 旧 JSONL/schema、版本升级、回滚、备份、部分损坏、recovery_required | migration/restore report 与人工介入记录 | C6、C12、GA |
| Accessibility/UX | 键盘、焦点、错误/权限可见性、中文/英文文本溢出、离线和低带宽投影 | 自动检查加人工验收 | 桌面和远程发布 |

固定坐标截图可以保留用于视觉回归，但不能作为业务成功的唯一证据。任何包含用户内容、token、二维码或工作区路径的报告必须先脱敏，并有保留期限和删除责任人。

### 14.8 发布、迁移、回滚和灾备操作顺序

所有持久化 schema、事件协议、Tauri 制品和 provider 错误契约的变更都必须采用可回退顺序。推荐执行 `expand → dual-read/dual-write（必要时）→ backfill/verify → switch flag → contract old path → cleanup`，禁止在同一版本中先删除旧字段再期待回滚自动恢复。

| 阶段 | 操作 | 必须确认 | 失败动作 |
|---|---|---|---|
| Preflight | 冻结 release commit、生成 SBOM/manifest、检查秘密、备份、迁移 dry-run、确认支持矩阵 | G0/G1、备份可读、回滚制品存在 | 不进入发布 |
| Staging | 执行迁移、contract/E2E/fault/restore、校验 provider 和通道 | 新旧客户端兼容、无重复副作用 | 删除 staging 数据或恢复快照，不带问题进入试点 |
| Pilot | 小范围租户/工作区、feature flag 默认关闭新能力、人工值守 | SLO、错误预算、审计、告警和用户验收 | 关闭 flag；必要时回到上一个制品 |
| GA | 分批发布，先只读/低风险能力，再开启副作用工具 | 每批次健康、错误、恢复、成本和支持信号 | 停止扩散并执行回滚 runbook |
| Rollback | 先停止新任务接入或 drain，再保护进行中的 lease，恢复兼容制品和 flag，验证数据 | 不重复执行、不丢审计、用户可见状态一致 | 进入 recovery_required，人工处理，不强行重试 |
| Restore | 校验备份、恢复权威数据、重建投影和 cursor、执行对账、开放只读观察 | RPO/RTO、hash、任务状态和审计链 | 隔离损坏数据，升级数据管理员 |

桌面单机版和服务部署版必须分别定义备份对象。单机版至少覆盖用户明确选择的 workspace、session/task/revision 元数据和凭据清除策略；服务版还要覆盖任务持久层、事件日志、审计、配置和制品。建议 C6 先冻结“可恢复到哪个时间点、允许丢什么、恢复后哪些任务必须人工确认”的产品语义，再决定具体存储技术。

### 14.9 数据分类、租户隔离与威胁控制

企业上线不能只写“加密”和“审计”，必须知道什么数据需要保护、谁能看、多久删除以及怎样证明删除完成。C5-C6 应形成数据目录和威胁控制矩阵。

| 数据/威胁 | 默认控制 | 必须测试或证据 |
|---|---|---|
| 用户消息、提示、工具参数 | 传输/静态加密、最小日志、字段脱敏、tenant/workspace scope、可配置保留 | 越权访问、导出/删除、日志扫描、备份清理 |
| 文件内容、snapshot、diff | workspace containment、symlink/TOCTOU 控制、版本/hash、敏感内容不进普通日志 | 路径逃逸、并发冲突、恢复和快照删除 |
| 凭据、token、二维码、provider key | 受控注入/凭据存储、轮换、不可进入截图/日志/错误详情 | secret scan、轮换/吊销演练、制品检查 |
| provider/网络返回 | 当作不可信输入，限制 URL、SSRF、防 prompt/tool injection、结果大小和 MIME | 恶意响应、内网地址、工具输出注入、超大结果 |
| MCP/LSP/Java 子进程 | 显式 capability、版本/来源校验、沙箱/资源限制、Python 权限为最终裁决 | 恶意插件、崩溃、超时、越权和供应链报告 |
| 远程身份与 peer | tenant/user/peer/role scope、短期凭证、重放保护、速率限制、审计 | token 重放、跨 session、跨 tenant、暴力请求 |
| 桌面更新和制品 | 签名、来源校验、CSP、最小 capability、回滚版本 | 篡改包、降级攻击、未签名更新、安装/卸载清理 |
| prompt injection/工具社会工程 | 不把模型文本当权限；危险操作必须 policy + 人工/管理员决策；外发和写入分类 | 注入样本、拒绝/审批链、审计和用户提示 |

默认租户模型建议先明确为 `single-tenant local` 或 `managed multi-tenant service` 二选一。若采用前者，所有 API 仍应携带可验证的 scope；若采用后者，必须在持久层、缓存、事件 cursor、日志、备份、usage 和 delivery 中都带 tenant boundary，而不是只在 HTTP middleware 添加一个字段。

### 14.10 运营职责、事件等级和持续改进

C12 不能只写“持续运营”。发布、权限、数据和事故处理必须拥有明确责任人。个人开发阶段可以由同一人兼任，但职责不能被省略。

| 角色 | 责任 | 关键操作权限 | 必须留下的证据 |
|---|---|---|---|
| Runtime owner | 引擎、事件、TaskState、provider 和性能 | 关闭 feature flag、暂停任务接入 | 版本、指标、故障复盘 |
| Security owner | 权限、秘密、供应链、桌面 capability、漏洞 | 吊销凭据、阻断工具/发布 | threat model、扫描、例外审批 |
| Data owner | retention、备份恢复、迁移、导出删除 | 冻结/恢复数据、标记 recovery_required | restore/retention/删除报告 |
| Release owner | CI、制品、签名、灰度和回滚 | 停止批次、切换制品 | manifest、promotion、rollback |
| Tenant/operator | 用户、workspace、配额和审计查询 | 管理 scope、限流、人工审批 | 操作审计、审批、配额变更 |
| Support/on-call | 告警、客户沟通、runbook 和升级 | 只读诊断、触发预案 | 工单、时间线、影响范围和复盘 |

建议至少定义 SEV-1（数据泄露、跨租户、重复外发、无法停止危险任务）、SEV-2（核心任务大面积不可用、恢复不确定、事件权威丢失）、SEV-3（单租户降级、投递延迟、非关键 UI 问题）三级事件。每级应有发现、确认、抑制/回滚、用户通知、恢复、根因和预防动作的时限；无值守能力的部署不得宣称 24×7 SLA。

### 14.11 计划书的停止条件与重新规划规则

“无比完美”不应被解释为无限增加内容，而应被解释为**每项重要承诺都有边界、依赖、Owner、测试、运行证据和失败处理**。当出现以下任一情况，必须暂停新增功能并重新规划：核心状态机存在两个权威来源；协议字段已经被客户端依赖但没有版本策略；任务终态与 delivery/rollback 结果混淆；没有办法证明恢复后的数据完整性；发布包无法从审查过的提交重建；高风险工具没有可撤销授权；性能或错误预算连续两个周期失守；或支持矩阵之外的用户/平台已经被接入。

完成本附录后，C0-C6 不再只是“实现目标”，而是同时交付产品边界、需求追踪、字段级契约、状态不变量、测试证据、发布 runbook 和运营责任。C7-C12 的 memory、Java、MCP/LSP、多 Agent 和持续产品化必须在这套基线之上演进；如果某项扩展无法复用核心契约，应先退回设计阶段，不允许以旁路状态或新入口继续扩大系统复杂度。

### 14.12 C0 必须落地的工程控制包

为了让本计划不依赖口头约定，C0 结束时必须在仓库中形成以下可审查产物。它们是后续 PR 的输入，不是可选文档；每项产物必须带版本、Owner、更新时间和对应的 REQ 编号。

| 产物 | 建议路径 | 内容和最小要求 | 使用周期 | 缺失时的处理 |
|---|---|---|---|---|
| 支持矩阵 | `docs/support-matrix.yaml` | release channel、平台、入口、角色、模型、工具、数据区域、并发、文件大小、RPO/RTO、已知限制 | C0、每次发布 | 只能保留开发版，禁止试点 |
| 需求追踪表 | `docs/requirements-traceability.csv` | REQ、风险等级、代码、schema、测试、指标、Owner、周期、发布级别 | C0 起持续维护 | 需求不得标记 Done |
| 状态与不变量 | `docs/contracts/task-state.md` | Task/Turn/Permission/Job/Delivery 状态、迁移、终态、幂等和恢复规则 | C1-C2 | 禁止跨入口实现 |
| 协议 schema | `docs/contracts/engine-event.schema.json`、`task-state.schema.json`、`error.schema.json` | JSON Schema、示例、版本兼容和未知字段规则 | C1-C5 | 禁止协议扩展合并 |
| API 操作目录 | `docs/contracts/api-operations.md` | submit、events、task、stop、permission、rollback、delivery、workspace、health 的请求/响应/授权/错误语义 | C1-C6 | 禁止新增旁路 endpoint |
| 权限策略 | `docs/security/policy-matrix.yaml` | 工具风险、资源范围、默认决策、审批角色、超时和审计字段 | C3-C5 | 高风险工具保持禁用 |
| 数据目录与保留 | `docs/security/data-classification.yaml` | 数据分类、存储位置、加密、保留、导出、删除、备份和法律留存 | C5-C6 | 禁止 GA |
| 威胁模型 | `docs/security/threat-model.md` | 威胁→控制→测试→告警→Owner→例外到期日 | C0、每次高风险变更 | 禁止远程和插件能力发布 |
| SLO/容量预算 | `docs/ops/slo-budget.yaml` | 指标、目标、采样、窗口、error budget、告警和降级动作 | C0、每次扩容 | 支持矩阵不允许宣称 SLA |
| 迁移与恢复 runbook | `docs/runbooks/migrate.md`、`restore.md`、`rollback.md`、`incident.md` | 逐命令/逐检查点、停止条件、人工接管和证据产物 | C2、C6、C12 | 禁止升级或扩散 |
| 制品清单 | `artifacts/manifest.json`、`sbom/*` | commit、构建环境、依赖、签名、hash、配置模板和来源证明 | C0 起每次发布 | 制品不得对外发布 |

### 14.13 API、事件和控制命令的最小操作目录

字段级 schema 仍不足以指导入口实现；C1 必须把当前 FastAPI、HTTP bridge、JSONL、iLink 和前端实际需要的操作统一到以下逻辑目录。URL、传输方式可以因入口不同而适配，但操作语义、授权、幂等和错误码不能分叉。

| 逻辑操作 | 作用 | 必填关联 | 成功证据 | 失败/重试规则 |
|---|---|---|---|---|
| `session.open/resume` | 创建或恢复 session | tenant、workspace、session、client capability | session snapshot + `session.ready` | schema/integrity 不通过则 `recovery_required`，不可静默新建 |
| `turn.submit` | 接受一次用户 turn | idempotency key、session、turn、input hash、model profile | `turn.accepted` 与 task snapshot | 相同 hash 返回原结果；不同 hash 拒绝复用 |
| `event.stream/replay` | 订阅或补发事件 | session/task/peer/role scope、cursor | 连续 event_seq 或明确 reset reason | 过期 cursor 只能从快照重建，不能从错误位置继续 |
| `task.get/list` | 查询任务权威状态 | tenant/workspace/session scope | versioned TaskSnapshot | 前端不得用本地 loading 状态代替 |
| `task.stop` | 请求停止 | task、reason、idempotency key、授权主体 | `stopping` 后到 `stopped/failed/recovery_required` | 重复 stop 返回同一结果；不得直接伪造 stopped |
| `permission.list/resolve` | 展示和处理审批 | request、request_hash、审批主体、decision、idempotency key | `approved/denied/expired` 事件 | 只处理一次；hash 不符或权限不足拒绝 |
| `rollback.preview/execute` | 预览和执行回溯 | revision、approval hash、conflict policy、idempotency key | preview hash、审计和最终 rollback state | 条件不符转 recovery_required，不自动重复副作用 |
| `delivery.get/retry/cancel` | 查询或补偿外发 | delivery、peer、content hash、scope | delivery state + attempt audit | 任务终态与 delivery 终态分离；达到上限进入 dead letter |
| `workspace.read/write` | 文件读取和写回 | workspace、path、revision/mtime、scope | content hash、revision 和审计 | 冲突返回可处理错误，不覆盖未知新版本 |
| `health/readiness/metrics` | 服务和依赖检查 | instance、protocol version | 结构化状态与依赖明细 | readiness 未通过时拒绝新任务；liveness 不代表可接单 |

旧版 `/api/chat` 或其他兼容入口只能作为 adapter 调用上述逻辑操作，并在响应中明确 `legacy_projection: true`。任何新功能不得只接入旧接口或某一个 bridge。

### 14.14 Feature flag、配置和兼容窗口登记

每个会改变状态、协议、外部副作用或数据格式的能力都必须先进入 flag/config registry。环境变量散落在代码中、没有默认值或没有回退动作的开关不得进入试点。

| Flag/配置 | 开发默认 | 试点默认 | GA 条件 | 关闭动作 | Owner |
|---|---|---|---|---|---|
| `EVENT_ENVELOPE_V2` | on | on | 全入口 contract/replay 通过 | 仅回退旧投影，不回退权威事件 | Runtime |
| `SESSION_TASK_STATE_V1` | on | on | task/recovery/refresh E2E 通过 | 停止新任务，保留只读查询 | Runtime |
| `PERMISSION_ASK_RESUME` | on | on（危险工具按矩阵） | restart/timeout/audit 通过 | 危险操作默认 deny | Security |
| `REMOTE_SCOPED_AUTH` | on | on | scope/replay/rate-limit 审计通过 | 关闭远程写操作，仅保留本地 | Security |
| `PROVIDER_RETRY_CIRCUIT` | on | on（副作用请求 off） | fault/usage/error contract 通过 | 关闭自动重试，返回可见错误 | Runtime |
| `DURABLE_JOB_LEASE` | off（单实例） | 按支持矩阵 | 多实例 fencing/接管/压测通过 | 回到单实例并拒绝副本接入 | Ops |
| `MEMORY_L5_RUNTIME` | off | off 或 shadow | 真实质量、成本、回滚 gate 通过 | 回退 `project` | Memory |
| `JAVA_TOOL_RUNTIME` | off | off | adapter/cancel/crash/security 通过 | 从 registry 移除 Java 工具 | Platform |
| `MCP_LSP_AGENT` | off | off | 单独威胁模型和支持矩阵批准 | 立即禁用入口和 registry 能力 | Security/Platform |

配置变更必须记录旧值、新值、操作者、理由、影响范围和回滚值；flag 不能绕过权限、审计、schema 校验或数据隔离。每次发布保留至少一个旧制品与兼容窗口，直到迁移和恢复验收完成。

### 14.15 首个内部试点的建议冻结值

以下不是当前代码已经达到的承诺，而是供 C0 在真实环境中确认的**初版支持矩阵候选**。如果实测不成立，必须修改矩阵、SLO 和发布级别，而不是继续沿用模糊的“支持”。

| 维度 | 建议初值 | 明确不支持 |
|---|---|---|
| 部署拓扑 | Windows 11 x64 Tauri 单机；受控 Linux/Windows 单实例 FastAPI 远程服务 | 多副本无共享持久层、自动跨实例接管 |
| 租户模型 | `single-tenant`；一个受控用户/组织边界 | 未完成隔离证明的多租户共享存储 |
| 入口 | Tauri、本地 FastAPI、受控 remote、iLink；File Helper 仅 final-only | 未通过统一 envelope 的独立 bridge |
| 工作区 | 用户明确选择的一个或少量受控 workspace，路径 containment 和 symlink 策略开启 | 网络盘/未知挂载/跨 workspace 写入 |
| 模型 | 已通过 provider contract 的 DeepSeek/OpenAI-compatible profile | 未完成 usage、错误、超时和数据处理评估的供应商 |
| 工具 | Read/Write/Edit/Glob/Grep/Bash（按 policy）；Todo/Memory 以已定义范围提供 | MCP/LSP/多 Agent/Agent/Notebook/Skill/未实现 scaffold |
| 文件与任务 | 文本文件为主；任务终态、permission、delivery 需可查询和可恢复 | 未定义大小、编码、二进制、长任务和外发边界的任务 |
| 数据 | 试点数据分类、保留、备份和删除责任人已确认 | 生产敏感数据、未批准个人信息和无法删除的数据 |
| 支持承诺 | 工作时段值守、明确维护窗口、内部响应目标 | 24×7 SLA、自动灾备和多区域高可用 |

### 14.16 可直接执行的 CI、发布和验收入口

现有测试和脚本是资产，但不能假设缺失的命令已经存在。C0 必须新增统一入口脚本或 Make/Taskfile，使开发者和 CI 使用同一命令，不允许“本地手工步骤”成为唯一证据。最低入口建议如下，具体命令以仓库最终脚本为准并写入 `CONTRIBUTING.md`：

| 命令类别 | 必须提供的统一入口 | 必须执行 | 失败处理 |
|---|---|---|---|
| Python | `python -m pytest`、`python -m compileall`、依赖审计 | 单测、contract、fault 前置检查、禁止未锁依赖 | PR 阻断 |
| CLI | `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm build` | reducer、IndexedDB、组件和协议测试 | PR 阻断 |
| Tauri | `pnpm tauri build` 或等价 release pipeline | clean build、资源、签名状态和安装检查 | 发布阻断 |
| Java | `mvn test`、`mvn package` | RPC/adapter contract、超时、取消、崩溃恢复 | 平台 PR 阻断 |
| Contract | `scripts/check_contracts` | schema、fixture、旧客户端兼容、未知字段 | 协议 PR 阻断 |
| Security | `scripts/security_gate` | secrets、SAST/SCA、SBOM、许可证、制品扫描 | G0/G1 阻断 |
| E2E | `scripts/e2e_gate --topology <name>` | 真启动、submit、stream、permission、stop、restart、rollback、delivery | RC/GA 阻断 |
| Release | `scripts/release_verify <manifest>` | provenance、hash、迁移 dry-run、备份恢复、回滚 | 禁止发布 |

每条命令都必须返回严格退出码、输出脱敏报告并记录 commit、环境、schema、feature flag 和输入 fixture。`memory_stack_eval`、`formula_live_ab` 等评估 harness 在接入 CI 前必须增加失败退出码和阈值模式；仅生成报告而返回 0 不能作为门禁。

### 14.17 Owner、依赖和“完成”的统一格式

每个 PR 开始前必须填写一页实施卡，避免计划书中的表格被误读成无人负责的愿望清单。

| 字段 | 必填内容 |
|---|---|
| Owner/Reviewer | 一个负责角色、一个复核角色；个人项目可由同一人兼任但仍需双重检查清单 |
| 输入 | 当前 commit、依赖 PR、schema/flag 版本、迁移和测试夹具 |
| 修改范围 | 文件/模块、API、前端投影、数据格式、配置和非目标 |
| 风险 | 数据损坏、重复副作用、权限绕过、性能、兼容和回滚风险 |
| 验收 | 自动命令、人工步骤、故障注入、指标阈值、证据路径 |
| 发布行为 | 默认 flag、灰度范围、支持矩阵变化、关闭动作和回滚版本 |
| Done | 代码、测试、文档、指标、runbook、审计、迁移和脱敏报告全部闭合 |
| 未完成处理 | 保持禁用、降级到旧投影、限制入口或退回设计，不允许半启用 |

实施卡必须链接到 `requirements-traceability.csv`；周期出口只有在所有关联 PR 的实施卡和证据链接齐全时才能签字。这样可把“计划完成”与“代码合并”明确分开。

### 14.18 权威存储与目标部署拓扑冻结

如果不冻结权威存储，JSONL、进程内对象、IndexedDB、通道队列和未来数据库会继续各自演化，最终无法判断哪个状态可以信任。C0 必须记录技术决策；以下是当前代码基础上最小、可迁移且不把缓存当事实源的默认方案。现有 session JSONL、SessionPool、前端 IndexedDB 和各通道 JobStore 只能作为迁移输入或投影，不能在新架构中继续承担跨入口的唯一任务权威。[1] [3] [4] [15] [16] [17] [71]

| 部署形态 | 权威元数据与状态 | 事件与审计 | 文件、快照和媒体 | 明确禁止 | 进入条件 |
|---|---|---|---|---|---|
| 本地桌面/单用户试点 | 单实例受锁保护的本地关系型持久层；保存 session、turn、task、permission、job、delivery、revision、usage 和 schema 版本 | append-only event log 与 audit log；每条提交事件必须可校验和重放 | workspace 文件仍由文件系统保存；rewind snapshot 使用内容寻址目录；大媒体不进入普通消息表 | 不以 React 状态、IndexedDB、进程内 list、SessionPool 内存或单个 JSONL 文件作为任务权威 | C0 冻结 schema；C2 完成迁移与恢复；C6 完成导出、备份和回滚 |
| 受限服务/单实例 | 与桌面相同的持久层，但服务进程不允许共享未加锁工作目录；后台任务必须有 lease 和 heartbeat | 事件、审计和 delivery attempt 独立保留；重启后先恢复权威状态，再开放写入 | 对象/文件存储与元数据分离；snapshot、artifact、upload 使用 hash 和生命周期策略 | 不允许第二副本接收写请求；不以内存 JobStore 宣称高可用 | readiness、排空关停、故障恢复和单实例容量测试通过 |
| 企业服务/多实例 | 托管关系型数据库保存权威状态和事务版本；实例只持有短期执行上下文 | 数据库/专用事件存储保存 event_seq、审计和游标；消息总线只能传递唤醒信号，不是最终事实 | 对象存储保存快照、artifact、媒体和备份；数据库只保存 hash、大小、类型和引用 | 不允许实例本地文件、缓存、Redis 或前端投影成为跨实例事实源 | durable lease、fencing token、接管、备份恢复、容量和租户隔离全部达标 |

C0 必须输出一份 ADR，至少比较“继续扩展 JSONL”“本地关系型持久层”“服务关系型持久层+对象存储”三种方案，明确迁移成本、并发、恢复、备份、租户隔离和回滚限制。默认安全选择是先完成单实例关系型持久化和 JSONL 导入导出，再以 repository 接口替换为服务数据库；不得在未有 repository 边界时直接把 SQL 调用散落到 `app.py` 或工具实现中。

### 14.19 当前代码到目标架构的迁移地图

后续实施不得重新设计一套与现有代码无关的系统。应先建立 adapter/repository/coordinator 边界，再逐步把现有能力迁入。下表是实施顺序的唯一主线；每一行都必须在 `requirements-traceability.csv` 中拥有对应 REQ、PR、测试和证据包。

| 当前代码资产 | 目标职责 | 第一迁移动作 | 完成证据 | 禁止事项 |
|---|---|---|---|---|
| `python/session/state.py`、`persistence.py`、`message_store.py`、`hydrate.py`、`record_transcript.py` | `SessionRepository`、`TranscriptRepository`、`SessionSnapshot` | 先引入版本化 repository 接口，再把 JSONL 读写改为 adapter | round-trip、坏数据隔离、并发写、fsync/校验、升级和恢复测试 | 新增模块继续直接读取全局 cwd 或 list |
| `python/server/session_pool.py` | `TaskCoordinator`、`LeaseRepository`、`RecoveryScanner` | 把 busy lease、stale reclaim、history stash 拆成可持久化接口 | 单实例重启、重复接管、fencing、多实例互斥报告 | 以 `threading.Lock` 作为服务级分布式锁 |
| `python/engine/query_engine.py`、`query_loop.py`、`abort.py`、`compact.py` | `TaskRunner`、`TurnExecutor`、`ContextProjector` | 让 runner 只通过状态仓储和事件发布器改变权威状态 | 任务状态轨迹、停止/权限挂起/压缩失败恢复、预算对账 | 在循环内部偷偷创建旁路任务状态 |
| `python/msgtypes/message.py`、`events.py`、`types/permissions.py` | 共享 schema 包和兼容 adapter | 先生成 JSON Schema 与 fixture，再由 Python/TypeScript/Java 校验 | contract、未知字段、版本兼容和 replay 通过 | 各入口复制自定义字段或依赖字符串判断 |
| `python/server/app.py`、`bridge/http.py`、`bridge/__main__.py` | transport adapter | 所有入口调用同一 application service；旧 `/api/chat` 仅做 legacy adapter | 三入口同 fixture、同事件序列、同错误码和权限结果 | 在 bridge 中自行创建 EnginePool 或改变任务语义 |
| `python/permissions/*`、`tools/tool_registry.py`、`tools/catalog.py` | `PolicyEvaluator`、`ApprovalService`、`ToolRuntime` | 统一 capability、scope、risk、approval、audit 和 side-effect class | ASK/resolve/restart、越权、超时、重复副作用测试 | 将 ASK 降级为 DENY 后宣称审批已完成 |
| `python/tools/*`、`workspace_fs.py`、`rewind/*` | 受策略约束的工具执行与文件事务 | 先封存高风险/空壳工具，再改造真实文件工具和 bash runner | dry-run、冲突、取消、审计、快照补偿、输出脱敏 | 为了扩大能力矩阵而提前启用 stub |
| `gui/src/stores/*`、`gui/src/lib/api.ts`、`gui/src/lib/types.ts` | 事件 reducer 和查询投影 | 前端只消费 TaskSnapshot/EngineEvent，IndexedDB 作为可重建缓存 | 刷新、断线、重放、旧协议和无序事件测试 | 用本地 `loading`/`streaming` 布尔值伪造任务权威 |
| `python/channels/*` | delivery adapter 与 peer projection | 将 iLink/File Helper 的已有排队能力接到 Delivery 状态机 | delivery attempt、重试、dead letter、cancel 和投递对账 | 将通道 done 当作 task completed |
| `python/memory/*`、`simulator/*` | 异步派生记忆投影和质量控制面 | 先保持 shadow/project 默认，绑定 evidence gate 和 rollback | 质量、成本、TTL、删除、重建和用户纠正报告 | 让 memory 派生写入阻塞主任务或成为唯一事实源 |
| `java/*` | 可选 adapter/runtime sidecar | 只在 Python contract 固定后实现 RPC、取消和沙箱 | Java contract、崩溃恢复、超时和供应链报告 | 在核心状态机稳定前扩张 Java 工具 |

### 14.20 首个支持版本的数值 SLO、容量、RPO 与 RTO

以下不是对所有 provider 延迟的承诺，而是首个受限服务版本的**控制面基线**。C0 必须把它们写入 `docs/ops/slo-budget.yaml`；如果实际部署资源或支持范围不同，必须修改支持矩阵和证据门禁，而不是继续沿用无数字的“高可用”表述。

| 指标 | 内部试点基线 | 企业 GA 基线 | 测量边界 | 未达标动作 |
|---|---:|---:|---|---|
| readiness 响应 p95 | ≤500 ms | ≤300 ms | 不含 provider 推理；包含数据库、事件存储和关键配置检查 | 拒绝新任务，保留 liveness 与诊断 |
| `turn.accepted` p95 | ≤1 s | ≤500 ms | 从合法请求到权威写入和 accepted 事件 | 限流、扩容或回退新入口 |
| 已确认事件丢失 | 0 | 0 | 已提交事件在重启、重放和恢复后必须存在；重复必须可去重 | 立即进入只读/恢复模式 |
| 事件重放恢复 | ≤30 s/10,000 events | ≤10 s/10,000 events | 从快照和事件日志恢复一个 session 投影 | 限制 session 大小并启动重建任务 |
| 进程故障后的任务判定 | ≤5 min | ≤2 min | 从进程失联到 `failed`、可接管或 `recovery_required` | 暂停接单，人工检查 lease |
| 控制面可用性 | 99.5%/月 | 99.9%/月 | 不把上游 provider 纯故障直接计为本系统控制面不可用 | 消耗 error budget 时冻结新功能 |
| 备份 RPO | ≤15 min | ≤5 min | 已纳入备份策略的权威元数据、事件和审计 | 降级为受限模式并告警 Data owner |
| 服务恢复 RTO | ≤60 min | ≤30 min | 从确认故障到可读、可审计、可接收新任务 | 进入灾备 runbook，不承诺自动恢复 |
| delivery enqueue p95 | ≤1 s | ≤500 ms | 只测写入 delivery 权威状态，不包含第三方送达 | 进入队列保护和 backoff |
| workspace 越界成功率 | 0 次 | 0 次 | 路径、symlink、TOCTOU 和并发测试全量 | 阻断发布 |
| 单实例试点容量 | 20 active sessions、100 queued tasks、单文件 10 MB | 由压测结果升级 | 明确 CPU、内存、磁盘和 provider 并发上限 | 超过上限拒绝/排队，不隐式扩容 |

首 token 延迟、provider 成功率和外部送达时间必须单独按供应商、模型和通道分桶；它们不能掩盖本系统 `accepted/stream/recovery/delivery` 控制面指标。任何容量数字都必须附带测试机型、模型、工具比例、消息大小、workspace 文件分布和持续时间，否则只能算临时实验结果。[25] [63] [70]

### 14.21 机器可读状态迁移表与不变量

`docs/contracts/task-state.md` 负责解释，`task-state.schema.json` 负责结构约束，`tests/contracts/state_machine.yaml` 负责生成正反例。以下迁移表是首版最小闭合模型；新增状态必须同时补 schema、事件、reducer、恢复动作和故障测试。

| 对象 | 状态集合 | 合法迁移触发 | 终态/恢复规则 |
|---|---|---|---|
| Task | `accepted`、`running`、`waiting_permission`、`waiting_provider`、`stopping`、`completed`、`failed`、`canceled`、`recovery_required` | submit、runner start、permission pending/resolve、provider result/error、stop、recovery scan | `completed/failed/canceled` 为正常终态；权威不确定或副作用不明只能进 `recovery_required` |
| Turn | `created`、`accepted`、`streaming`、`waiting_tool`、`waiting_permission`、`completed`、`failed`、`canceled` | turn.accept、event/tool/permission、model final、stop/error | 一个 turn 只能有一个 final；重试必须产生新 attempt，不复用 turn identity |
| Permission | `pending`、`approved`、`denied`、`expired`、`canceled` | policy decision、resolve、TTL、task stop/restart | resolve 只成功一次；`request_hash`、scope、审批主体和过期时间必须审计 |
| Job | `queued`、`leased`、`running`、`succeeded`、`failed`、`canceled`、`dead_letter`、`recovery_required` | enqueue、lease、heartbeat、worker result、cancel、retry limit、recovery scan | lease 丢失不能直接重跑副作用；必须 fencing 或人工确认 |
| Delivery | `pending`、`sending`、`delivered`、`retry_wait`、`failed`、`canceled`、`dead_letter` | enqueue、attempt、ack/error、backoff、cancel、limit | delivery 终态独立于 task；content hash、attempt 和 peer scope 必须可对账 |

所有状态写入必须满足：单调 `version`；事件 `event_seq` 在 scope 内唯一；重复命令返回原结果；不同 input hash 不得复用旧结果；前端投影可删除后重建；未知状态进入隔离而不是默认为完成；任何不可证明的外部副作用进入人工恢复。状态机验收必须包含乱序、重复、断线、进程 kill、时钟跳变、过期 lease 和旧 schema 输入。

### 14.22 版本兼容窗口与重建操作顺序

C0 需要发布一页版本日历，至少区分 `build_version`、`protocol_version`、`event_schema_version`、`data_schema_version`、`provider_adapter_version` 和 `feature_flag_revision`。服务端必须声明 `min_client_version` 与 `max_client_version`；客户端遇到不兼容协议时进入可解释的升级页，不得静默降级成错误文本。

| 版本类别 | 兼容规则 | 默认支持窗口 | 回滚限制 |
|---|---|---|---|
| 增加可选字段 | 旧读端忽略，生产者默认不依赖旧端 | 至少两个发布批次 | 可回退制品 |
| 改变必填字段/状态 | 新 schema 与新 flag 并行，完成 backfill 和 replay 后切换 | 至少一个完整试点窗口 | 未完成 contract 之前禁止清理旧字段 |
| 删除字段/旧 endpoint | 先公告、观测调用量、提供 adapter，再删除 | 服务版至少 90 天；桌面版随安装包升级但保留导入器 | 数据已迁移且旧制品不再接收写入 |
| provider 计费/错误语义 | adapter 版本化，usage 不确定性显式标记 | 以 provider 契约和对账周期为准 | 不得把未知成本伪装成零 |
| 数据迁移 | expand→dual-read/dual-write→backfill→verify→switch→contract→cleanup | 每步可独立停止 | 回滚前不得删除旧数据 |

投影、游标和前端缓存重建必须使用固定顺序：暂停受影响 scope 的写入；记录重建起点和目标 `event_seq`；校验 snapshot/hash；从权威事件日志重放 Task/Turn/Permission/Job/Delivery；重建审计索引和 delivery 对账；生成前端和通道投影；比较最终版本、hash、未完成任务和游标；只读观察通过后恢复写入。任何对账不一致都必须保留损坏投影、生成报告并进入 `recovery_required`，不可用“重新拉取最新消息”掩盖问题。

### 14.23 证据包、容量基线与事故时限

每个周期和发布批次必须生成 `artifacts/evidence/<release>/<gate>/manifest.json`，索引 commit、构建环境、制品 hash、schema/flag 版本、测试报告、故障注入报告、迁移/恢复报告、SLO 结果、人工验收、例外审批和删除日期。C0 增加 `scripts/check_traceability`，自动检查每个 `REQ-*` 是否同时存在代码路径、schema、测试、指标、runbook、Owner、PR 和发布级别；缺项返回非零退出码。

| 运营事件 | 确认目标 | 初步缓解目标 | 用户/内部更新 | 恢复与复盘 |
|---|---:|---:|---:|---|
| SEV-1：跨租户、数据泄露、重复外发、无法停止危险任务 | 15 分钟 | 30 分钟内关闭写入口/吊销凭据/停用工具 | 每 60 分钟或状态变化时更新 | 4 小时内形成时间线，5 个工作日内完成 RCA |
| SEV-2：核心任务不可用、恢复不确定、事件权威异常 | 30 分钟 | 2 小时内限流、回滚或进入恢复模式 | 每 2 小时更新 | 1 个工作日内初步报告，10 个工作日内完成预防项 |
| SEV-3：单租户降级、投递延迟、非关键 UI 故障 | 1 个工作日 | 下一发布窗口或 2 个工作日内处理 | 工单状态更新 | 下个周期纳入改进清单 |

无值守团队的本地部署只能提供“工作时间支持”和自助 runbook，不得使用上述目标宣称 24×7 SLA。首版容量测试固定为 4 vCPU、8 GB RAM、20 active sessions、100 queued tasks、10 MB 单文件、2 小时 soak；任何提升支持矩阵上限都必须重新执行 load、fault、restore 和成本测试，并在 manifest 中记录环境差异。

### 14.24 最终实施决策清单

在计划书允许进入 C1 之前，以下问题必须由 Owner 写出选择、理由、替代方案、回滚限制和决策日期；“以后再决定”不是有效依赖。默认值应选择更容易停止、更容易恢复、更不容易扩大数据副作用的方案。

| 决策 | 默认安全选择 | 最晚完成 | 影响 |
|---|---|---|---|
| 单机/服务权威存储 | 单机关系型持久层；服务关系型数据库+对象存储；JSONL 仅兼容导入导出 | C0 | 所有 session/task/event/recovery/backup |
| 首个支持入口 | FastAPI 主入口+Tauri；bridge/iLink/File Helper 只在 contract 通过后逐个启用 | C0 | 支持矩阵、E2E、发布范围 |
| 首个副作用工具 | 文件读写、受控 bash 的有限子集；联网、MCP、Agent、外发默认关闭 | C0/C3 | 权限、威胁、审计和试点风险 |
| 租户模式 | 先 single-tenant local 或受限单租户服务；未完成隔离不宣称多租户 | C0 | auth、数据、备份、usage、delivery |
| Provider 重试 | 只对无副作用、可证明未提交的请求重试；工具/外发默认不自动重试 | C2/C5 | 成本、重复副作用和错误契约 |
| 桌面更新 | 签名制品、可验证 manifest、上一版本回滚 | C6 | 安装、升级、降级和支持 |
| GA 判定 | G0–G5 全部有 evidence manifest，且无未到期 P0 阻断项 | C6 | 是否允许企业上线 |

### 14.25 目标工程布局与依赖方向

为了让计划书能够直接转化为目录、模块和 PR，而不是停留在架构名词层，C1 起按以下目标布局建立新边界。首版可以保留旧模块作为 adapter，但新增代码不得继续把领域状态、数据库访问和 HTTP 细节混在旧入口中。

| 目标目录 | 首版职责 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| `python/contracts/` | JSON Schema、Python 类型、错误码、事件和状态迁移契约 | 标准库、生成器 | FastAPI、数据库、具体 provider、工具实现 |
| `python/domain/` | Session、Turn、Task、Permission、Job、Delivery、Revision 的不变量和纯状态转换 | `contracts/` | HTTP、文件系统、ORM、provider、全局 cwd |
| `python/application/` | submit、stop、permission resolve、recovery、rollback、delivery、usage 用例编排 | `domain/`、repository interface、event publisher | 具体 SQL、FastAPI request 对象、前端类型 |
| `python/ports/` | `SessionRepository`、`TaskRepository`、`EventStore`、`LeaseRepository`、`BlobStore`、`ProviderGateway`、`DeliveryGateway` 接口 | `contracts/`、`domain/` | 具体数据库驱动和通道 SDK |
| `python/infrastructure/` | 关系型存储、JSONL adapter、事件日志、对象/文件存储、provider 和通道 adapter | `ports/`、第三方库 | 修改 domain 状态机、直接调用 UI |
| `python/execution/` | `TaskCoordinator`、`TaskRunner`、`TurnExecutor`、heartbeat、cancel、recovery scanner | `application/`、`ports/`、`domain/` | 直接写前端缓存、绕过 permission/audit |
| `python/transport/` | FastAPI v2、legacy adapter、HTTP bridge、JSONL adapter、认证和序列化 | `application/`、`contracts/` | 自行创建 EnginePool、复制业务规则 |
| `python/channels/` | iLink、File Helper、remote delivery 的投影与投递适配 | `ports/`、`contracts/` | 把送达状态当作 Task 完成 |
| `gui/src/protocol/` | 生成或校验的 TypeScript schema、事件 reducer、TaskSnapshot 投影和兼容层 | `contracts` 生成物 | 自定义第二套事件字段、直接猜测后端状态 |
| `java/src/main/java/xeyo/` | Python contract 稳定后提供可选 RPC/sidecar adapter | contract 生成物 | 在核心状态机稳定前承载唯一事实或权限裁决 |

依赖方向必须由 CI 检查：`domain → contracts`，`application → domain/ports`，`infrastructure → ports`，`transport → application/contracts`；反向导入、模块级单例状态、`os.chdir`、从 HTTP handler 直接访问数据库均应视为架构违规。旧 `engine/`、`session/`、`server/` 代码在迁移期间只允许通过 adapter 被调用，并在每个 PR 中记录删除条件。

### 14.26 首版关系模型、唯一约束和索引清单

C0 的 ADR 确认数据库后，C1 必须先建立迁移文件和 repository contract，再实现业务迁移。下面是单用户试点也应采用的最小实体集合；`tenant_id` 保留在所有业务表中，即使首版只有一个租户，也不能把未来隔离依赖在应用层字符串约定上。

| 表/实体 | 必要字段与约束 | 关键索引/用途 |
|---|---|---|
| `tenants`、`workspaces` | `tenant_id`、`workspace_id`、状态、根路径、policy_revision、created_at；workspace 根路径唯一且不能跨 tenant | `(tenant_id, status)`；所有查询先按 tenant/workspace 限定 |
| `sessions` | `session_id`、tenant/workspace、title、cwd、status、head_revision、version、created_at/updated_at | `(tenant_id, workspace_id, updated_at)`；`session_id` 不可复用 |
| `turns`、`tasks`、`task_attempts` | session/turn/task 关系、input_hash、状态、attempt、lease_owner、lease_expiry、fencing_token、version | `(session_id, created_at)`、`(status, lease_expiry)`、`(task_id, attempt_no)`；同一 task 的 input/idempotency 不得重复提交 |
| `permissions` | task/turn、request_hash、capability、scope、risk、decision、subject、expires_at、resolved_at | `(task_id, status)`、`(expires_at, status)`；同一 resolve 请求幂等 |
| `event_log` | scope、`event_id`、`event_seq`、event_type、schema_version、payload_hash、payload、occurred_at | `unique(scope, event_seq)`、`unique(event_id)`、`(scope, event_seq)`；事件只追加不更新 |
| `idempotency_keys` | tenant、actor、operation、key、request_hash、result_ref、expires_at | `unique(tenant_id, actor_id, operation, key)`；同 key 不同 hash 必须拒绝 |
| `revisions`、`file_operations`、`snapshots` | revision/head、父 revision、operation、before/after hash、path、snapshot_ref、approval_ref、状态 | `(workspace_id, created_at)`、`(revision_id, operation_no)`；快照内容放 blob，表只存 hash/size/type |
| `jobs`、`job_attempts` | job_type、payload_ref、状态、lease、retry_count、next_run_at、dead_letter_reason | `(status, next_run_at)`、`(lease_expiry, status)`；副作用 job 必须 fencing |
| `deliveries`、`delivery_attempts` | task/event、channel、peer、状态、attempt、remote_id、error_code、last_attempt_at | `(task_id, channel)`、`(status, next_attempt_at)`；delivery 与 task 终态分离 |
| `usage_ledger` | tenant/workspace/session/task/attempt、provider/model、input/output/cache tokens、unit price、cost、source、confidence、currency | `(tenant_id, occurred_at)`、`(task_id, attempt_no)`；未知费用不得写成 0 |
| `audit_log`、`outbox` | actor、request_id、decision、resource、before/after hash、reason、created_at；outbox event、publish status、attempt | `(tenant_id, created_at)`、`(status, next_attempt_at)`；审计不可由普通业务删除 |

所有业务表必须包含 schema/data version 或可推导版本；时间统一 UTC，展示层再转时区；金额使用定点数而非二进制浮点；payload 需要大小上限和敏感字段策略。迁移必须提供 `up`、可验证的 `down` 或明确不可逆说明、dry-run、backfill、校验 SQL 和恢复步骤。任何“先写数据库、再补事件”或“事件先写但没有 outbox 对账”的实现都不能通过 C1。

### 14.27 v2 API、Bridge 和前端操作映射

所有入口必须调用同一 application service。v2 协议推荐使用 `/api/v2` 前缀；旧 `/api/chat`、现有 bridge、iLink 和 File Helper 只作为兼容适配层，不能自行改变状态迁移或错误语义。

| 逻辑操作 | FastAPI v2 | HTTP/JSONL/通道适配 | 前端/证据要求 |
|---|---|---|---|
| 创建/读取 session | `POST/GET /api/v2/sessions`、`GET /api/v2/sessions/{id}` | HTTP bridge 同路径；JSONL `session.create/get`；通道只携带 session 引用 | 返回 tenant/workspace/session/version；刷新可重建 |
| 提交 turn/task | `POST /api/v2/sessions/{id}/turns`，要求 idempotency key | JSONL `turn.submit`；iLink/File Helper 入站统一转 InboundMessage | 先返回 `task_id`、`accepted` 和 cursor，不等待模型终态 |
| 查询状态/事件 | `GET /api/v2/tasks/{id}`、`GET /api/v2/tasks/{id}/events?after=` | JSONL `task.get/events`; 通道按 cursor 拉取 | 无序、断线、重复事件由 reducer 处理 |
| 停止/恢复 | `POST /api/v2/tasks/{id}/stop`、`POST /api/v2/tasks/{id}/recover` | JSONL `task.stop/recover`；通道只提交命令，不伪造终态 | stop/recover 都返回命令结果和新 version |
| 权限审批 | `GET /api/v2/permissions/{id}`、`POST /api/v2/permissions/{id}/resolve` | JSONL `permission.get/resolve`；远程审批必须绑定 peer/actor | approve/deny/expire/restart 全部可重放、可审计 |
| workspace/文件/回溯 | `GET/POST /api/v2/workspaces/{id}/files...`、`POST /api/v2/revisions/{id}/rollback` | 只允许受控 adapter；文件变更不直接写 transport | dry-run、冲突、快照、审计和 recovery_required 可查询 |
| delivery/usage/health | `GET /api/v2/tasks/{id}/deliveries`、`GET /api/v2/usage`、`GET /health/live`、`GET /health/ready` | 通道 delivery 使用同一状态机；legacy endpoint 只映射 v2 | readiness 失败不等于进程死亡；成本来源和置信度可见 |

协议必须定义认证、tenant/workspace scope、request_id、idempotency key、cursor、分页上限、错误码、retry-after、未知字段和最大 payload。禁止在 bridge 中直接调用 `SessionPool`、直接生成 `EngineEvent` 或通过字符串判断“done”。前端 `chatStore`、`remoteStore`、`explorerStore` 逐步改成 v2 adapter 的投影消费者；IndexedDB 只保存可删除、可重建的缓存。

### 14.28 从零开工的 PR 顺序和生成物

以下是对既有 PR-S0–S13 的开工级细化，不改变原有编号。每一项合并前必须同时提交代码、生成物、测试和证据；如果前置条件失败，功能保持关闭或继续使用旧 adapter，不能半切换。

| 顺序 | 对应 PR | 首先创建/修改 | 必须生成的文件或产物 | 合并门禁 |
|---:|---|---|---|---|
| 1 | PR-S0 | `CONTRIBUTING.md`、统一脚本目录、Owner/REQ 模板 | `scripts/check_traceability`、`scripts/check_contracts`、实施卡模板 | 现有测试基线、严格退出码、无秘密泄漏 |
| 2 | PR-S1 | `python/contracts/`、`gui/src/protocol/` | `*.schema.json`、Python/TS 类型、fixture、错误码表 | 三入口 schema round-trip、未知字段和兼容测试 |
| 3 | PR-S2 | `python/ports/`、migration 目录 | repository interface、首版迁移、seed、dry-run、rollback/readiness 检查 | 空库迁移、旧 JSONL 导入、重启恢复、并发写 |
| 4 | PR-S3 | `domain/`、`application/`、`execution/` | TaskState/Turn/Permission/Job/Delivery reducer、状态迁移 fixture | 乱序/重复/kill/lease/时钟跳变和非法迁移全部拒绝 |
| 5 | PR-S4 | `infrastructure/event_store.py`、transport adapter | envelope、event_seq、outbox、cursor API、replay 工具 | 主入口、bridge、JSONL 同事件序列和重放结果 |
| 6 | PR-S5 | `PolicyEvaluator`、`ApprovalService` | permission endpoint、审批 UI 状态、审计记录、TTL 扫描 | ASK/resolve/restart、越权、重复 resolve、过期和断线 |
| 7 | PR-S6 | `TaskCoordinator`、provider gateway、错误层 | lease/heartbeat/fencing、重试矩阵、稳定 error code、request_id | provider fault、不可重试请求、预算对账、故障恢复 |
| 8 | PR-S7 | workspace/file/rewind adapter | 原子写、版本冲突、symlink/TOCTOU 检查、snapshot/recovery | dry-run、并发编辑、取消、补偿、审计和恢复报告 |
| 9 | PR-S8 | `transport/` 与 channel adapter | v2 FastAPI、bridge、JSONL、iLink/File Helper adapter | 真实启动三入口 E2E、认证、scope、cursor、delivery 对账 |
| 10 | PR-S9 | 前端 protocol/reducer/store | TaskSnapshot reducer、权限/停止/恢复/重连 UI、迁移脚本 | 刷新、断线、无序事件、旧协议、IndexedDB 重建 |
| 11 | PR-S10 | delivery/usage/outbox worker | delivery attempt、backoff、dead letter、成本 ledger、对账报告 | 重复外发保护、第三方失败、取消、RPO/RTO 和脱敏 |
| 12 | PR-S11 | ops/release/security | readiness、metrics、dashboards、SBOM、签名、backup/restore、runbook | G0–G5 证据 manifest、安装/升级/回滚和演练 |
| 13 | PR-S12 | memory 生产投影 | shadow/project flag、删除/重建、质量/成本门禁 | 主任务不被阻塞、用户纠正、tombstone、rollback |
| 14 | PR-S13 | Java/MCP/LSP/Agent 等扩展 | 每个能力独立 adapter、权限 profile、contract 和禁用开关 | 单项能力通过完整 G0–G5 后才可进入支持矩阵 |

任何 PR 如果需要同时修改 `domain`、transport、UI 和迁移但没有先提交 contract/fixture，应拆分；任何 PR 不能把 `feature flag=true` 作为“完成”的替代。每个 PR 的证据目录至少包含 `manifest.json`、测试输出、schema hash、migration report、指标截图/导出、人工验收记录和回滚演练结果。

### 14.29 仓库、运行数据和诊断包边界

C0 必须把数据边界写成 `.gitignore`、发布脚本和诊断打包器的自动规则，而不是依赖开发者记忆。以下清单是默认策略：

| 类别 | 可以进入 Git | 只能进入受控 artifact | 永不进入 Git/普通诊断包 |
|---|---|---|---|
| 源码与契约 | Python/TS/Java 源码、schema、migration、fixtures、runbook、脱敏样例 | 发布 manifest、测试报告、性能结果 | — |
| 配置 | `.env.example`、默认非秘密配置、支持矩阵 | 环境校验摘要、flag 清单、部署参数 hash | token、私钥、真实 endpoint secret |
| 运行数据 | 无真实运行数据 | 脱敏事件样本、replay fixture、恢复报告 | `sessions/`、uploads、snapshots、JobStore、IndexedDB 导出、provider 原文 |
| 凭据 | 无 | 仅记录 secret fingerprint/存在性 | `credentials.json`、Bearer token、cookie、签名私钥 |
| 日志/诊断 | 测试期固定脱敏样例 | 按工单授权的脱敏日志、core dump 清单、SLO 指标 | prompt 原文、文件内容、个人信息、完整 request body |
| 临时资源 | 可复现脚本 | 截图、benchmark、安装包和 SBOM | 本地临时目录、开发者桌面路径、未审查二进制 |

`scripts/diagnostic_bundle` 必须默认 allowlist 字段，按 tenant/workspace/task scope 脱敏并记录操作者、原因、过期时间和删除时间；不得以“调试方便”为由全量压缩工作目录。CI 必须扫描 Git 历史、artifact、构建产物和诊断包，发现秘密或未批准数据时返回非零退出码并阻断发布。

### 14.30 计划书自检与“无隐藏前置条件”门禁

最终计划书自身也必须可被机器检查。C0 建立 `scripts/check_plan_consistency`，至少执行以下检查：

| 检查项 | 规则 | 失败结果 |
|---|---|---|
| 引用闭合 | 文中每个 `[n]` 都存在 References；每个源码路径存在或标记为迁移目标 | 非零退出，不能合并文档 |
| 需求追踪 | 每个 `REQ-*` 映射到 PR、代码路径、schema、测试、指标、runbook、Owner、release gate | 非零退出，周期不得签字 |
| 表格完整 | P0/P1、C0–C12、PR-S0–S13 每行具备优先级/输入/输出/验证/失败行为或明确 N/A | 非零退出 |
| 状态闭合 | 状态、事件、终态、恢复动作、前端 reducer、JSON Schema 一一对应 | 非零退出 |
| 迁移闭合 | 每个旧模块有 adapter、读写切换、backfill、verify、rollback、删除条件 | 非零退出 |
| 门禁可执行 | 每个 G0–G5 有命令、阈值、证据路径和阻断动作 | 非零退出 |
| 支持矩阵一致 | 明确支持入口、工具、数据、租户和不支持项与 flag/route 一致 | 非零退出 |
| 数值一致 | SLO、容量、RPO/RTO、事故时限在正文、`slo-budget.yaml`、dashboard 和 runbook 中一致 | 非零退出 |
| 语言与边界 | 不含未实现能力的完成式表述、不含 Claude 运行依赖、不含“以后决定” | 非零退出 |

当 `check_plan_consistency`、`check_traceability`、`check_contracts`、全量测试、security gate、E2E gate、release verify 都通过，且证据 manifest 可由另一台干净机器复核时，才可以认为计划书与实现之间不存在已知的隐藏前置条件；这仍不等于功能已经实现，代表的是“可以按此计划无歧义地开工并逐项验收”。

### 14.31 首发企业身份与租户管理冻结

本计划不把当前远程单 token 认证误写成企业身份能力。现有 `/v1/remote/health`、`/v1/remote/messages` 和 job poll 只具备受限远程兼容入口；`XEYO_REMOTE_TOKEN` 是进程级共享秘密，不包含 tenant、peer、role、session、过期、轮换或审计范围。[65] [66] [98] [99] 因此首发支持矩阵必须冻结如下边界：

| 范围 | 首发默认 | 明确不支持或关闭 | GA 前证据 |
|---|---|---|---|
| 企业登录 | OIDC Authorization Code + PKCE；服务端验证 issuer、audience、nonce、state、签名和 key rotation | SAML、SCIM、高级组织同步不进入首发支持矩阵 | OIDC conformance、token 过期/撤销、JWKS 轮换、错误 audience 和回调重放测试 |
| 本地模式 | 未配置 IdP 时仅允许 single-user local；桌面使用设备激活或短期 session，不复用远程共享 token | 不得以 local 模式宣称企业多租户 | clean-install、激活过期、退出、重新激活和本地数据清理证据 |
| 租户范围 | `tenant → user/group → role → workspace → session/task`；所有查询和事件 scope 均带 `tenant_id` | 未完成隔离、备份、审计和退出证明前，managed multi-tenant 保持 flag-off | 跨租户读写、事件、文件、usage、delivery、备份和诊断包全量越权测试 |
| 内置角色 | `tenant_admin`、`workspace_admin`、`operator`、`auditor`、`member`；deny-by-default | 不允许通过前端隐藏按钮代替服务端授权 | 每个 endpoint 的 allow/deny 矩阵、撤销即时生效和审计对账 |
| 兼容远程 token | 仅限受控内部试点、明确标记 legacy/compatibility；强制绑定已配置的默认 scope | 不得访问管理面、跨租户资源、导出/删除、支持视图或高风险工具 | scope、过期、轮换、重放、撤销和 legacy 隔离测试 |

首发身份代码必须集中在 `python/auth/`、`python/application/identity_service.py`、`python/transport/auth.py` 与生成的 `gui/src/protocol/auth.ts`；不得在 `channels/auth.py`、FastAPI handler、Tauri 前端或 bridge 中复制角色判断。所有身份变更、角色绑定、租户冻结、设备激活和 token 撤销都必须写入同一 `audit_log`，并使用稳定 `request_id` 与幂等键。

### 14.32 v2 管理面 API 与人工操作边界

管理面属于受保护的 application service 域，不是旁路服务。当前 remote API 只提供 health、submit、poll，没有 session 列表、停止/恢复、权限解决、支持视图、导出/删除或租户管理路径。[65] 因此 C4/C5 必须先完成下列 v2 API，再逐个接入前端管理视图和受控运维脚本：

| API 域 | 最小路径 | 必需 scope 与行为 | 审计/幂等要求 |
|---|---|---|---|
| auth/session | `GET /api/v2/auth/me`、`POST /api/v2/auth/device/activate`、`POST /api/v2/auth/revoke` | 只返回当前 actor 的最小身份；revoke 后旧 session 立即拒绝 | `request_id`、actor、device、reason、expires_at；重复 revoke 返回原结果 |
| tenant/membership | `POST/GET /api/v2/tenants`、`GET/PATCH /api/v2/tenants/{id}`、`POST/DELETE /memberships` | 仅 `tenant_admin`；冻结租户先阻止新写入再处理未完成任务 | 变更前后 hash、审批人、幂等键和审计事件 |
| roles/workspaces | `PUT/DELETE /api/v2/role-bindings`、`POST/GET/PATCH /api/v2/workspaces` | 角色绑定不得超出 actor 的 tenant scope；workspace 根路径不可跨租户 | 双重检查旧版本；撤销后下一请求即拒绝 |
| support view | `POST /api/v2/support/views`、`GET /api/v2/support/views/{id}` | 仅 `operator/auditor`，强制工单号、最小字段、短期 expiry；默认不含 prompt/file 原文 | `support-access.json`，字段 allowlist、reason、expiry、导出 hash |
| export/delete | `POST /api/v2/tenants/{id}/exports`、`POST /api/v2/tenants/{id}/deletion`、`GET /api/v2/jobs/{id}` | 异步 Job；删除必须处理 retention、legal hold、凭据撤销和未完成 delivery | 双人审批、对象清单、hash、operator、时间、失败隔离和完成证明 |
| task control | `POST /api/v2/tasks/{id}/stop`、`POST /api/v2/tasks/{id}/recover`、`POST /api/v2/permissions/{id}/resolve` | 只允许 scope 内 actor；不确定副作用不能伪造 completed | 使用统一 Task/Job/Delivery 状态机和审计 event_seq |

管理 API 的实现顺序固定为：先 contract/schema 和 scope matrix，再 application service，再 repository/event/outbox，再 transport，最后前端视图。任何未通过越权、撤销、重放、双人审批、过期、错误码和审计完整性测试的管理路径必须返回明确的 `feature_disabled` 或 `not_supported`，不能返回看似成功的空结果。

### 14.33 typed config、secret reference 与发布真相源

现有配置仍分散在 `.env.example`、启动脚本和远程 runner 的环境变量读取中；`runner.py` 直接读取 provider、model、base URL 与 API key，remote API 也只围绕单 token 工作。[65] [66] [99] C0 必须建立唯一配置真相源，推荐目录如下：

```text
config/
  schema/config.schema.json
  defaults/base.yaml
  manifests/local.yaml
  manifests/staging.yaml
  manifests/production.yaml
  flags/registry.yaml
  secrets/reference.schema.json
scripts/
  validate_config.py
  check_secret_refs.py
  render_release_manifest.py
```

配置合并顺序固定为 `typed defaults → environment manifest → deployment overrides → secret references`；不允许业务代码自行读取未声明环境变量。每个配置项必须声明类型、默认值、敏感级别、允许环境、变更 Owner、是否需要重启、是否需要迁移以及回滚方式。秘密只允许以 `secret_ref` 进入运行时，启动时校验存在性、格式、权限和 fingerprint；真实值不得进入 Git、日志、artifact、前端 bundle 或异常文本。[118] [119]

发布前必须生成 `release-manifest.json`，包含 build/protocol/event/data/provider/flag 版本、commit SHA、artifact hash、config hash、SBOM hash、签名和 secret presence（仅 fingerprint）。`start-xeyo.bat`、`wait_health.py`、Tauri 构建、HTTP bridge、JSONL bridge 和 CI 均只能消费同一 manifest 的派生结果；schema/hash/secret 校验失败时启动拒绝，未知 flag 默认关闭。

### 14.34 数据退出、支持视图与租户终止流程

数据退出必须复用统一 Job/Delivery 状态机，不能由管理员直接删除目录。最小流程为：冻结租户写入 → 建立 legal hold 快照 → 生成对象清单与 hash → 双人审批 → 异步 export → 用户确认或保留期结束 → 撤销凭据和设备 → 删除权威数据、事件、blob、备份索引和派生缓存 → 重建/校验索引 → 生成完成证明 → 进入 `closed`。任一步失败都进入 `recovery_required`，保留失败对象清单，不得报告成功。

| 证据文件 | 必填字段 | 验收动作 |
|---|---|---|
| `support-access.json` | actor、tenant/workspace scope、ticket、reason、field allowlist、created/expiry、query hash、operator | 越权字段不可见；到期后 token 和视图均失效 |
| `export-report.json` | job_id、对象类型/数量、hash、开始/结束时间、保留策略、下载/交付记录 | 随机抽样可还原；重复请求不重复生成或产生不同清单 |
| `deletion-report.json` | approval ids、对象清单、删除顺序、hash、失败对象、credential revoke、完成时间 | 双人审批；legal hold 对象不删；失败可重试且不扩大范围 |
| `tenant-close-proof.json` | tenant 状态、权威库/blob/事件/缓存/备份索引检查、operator、tool/schema version | 独立操作者复核；无证明不得进入 `closed` |

支持视图默认不提供 prompt 原文、完整文件内容、provider 原文、cookie、token、个人信息或未脱敏请求体。必要的诊断必须采用字段 allowlist、短期授权和最小 scope。`remote_deliver.py` 当前失败只记录 warning、没有 durable delivery ledger，因此外发必须在 Delivery 状态机和审计层完成后才进入企业支持矩阵。[100]

### 14.35 DAY-0 与首十个工作日开工卡

新成员不得直接修改核心链路。进入 C0 的第一天必须在项目根目录执行以下步骤，并把结果提交到按 commit 隔离的证据目录：

```text
1. git status --short；确认工作树干净并登记分支、Owner、REQ、预计周期和变更范围。
2. 创建 contracts/、artifacts/、scripts/、runbooks/、migrations/、owners/ 目录及 README 占位。
3. 固定 Python、Node、Java、Tauri、pnpm/npm 版本；记录系统、端口、依赖和 provider 配置存在性。
4. 运行现有 Python/Vitest/Java 基线测试、fake smoke、workspace 安全测试和秘密扫描。
5. 生成 artifacts/plan-baseline/<commit_sha>/baseline.json，登记测试摘要、源码清单、覆盖审计、配置 hash 和失败项。
6. 创建 owners/registry.yaml、contracts/requirements.yaml、config/schema/config.schema.json、config/flags/registry.yaml。
7. 对每个失败项决定修复、flag-off、受限支持或明确退出；不得把失败留作无 Owner 的备注。
```

首十个工作日的固定顺序如下：

| 工作日 | 产物 | 必须完成的验证 | 失败行为 |
|---:|---|---|---|
| 1 | baseline、Owner registry、工作树目录 | 基线命令可重复、秘密扫描通过或有阻断单 | 停止新功能提交 |
| 2 | requirements/contract 初稿、错误码和事件字段表 | 需求→PR→测试→证据链无断点 | 未闭合需求退回 |
| 3 | config schema、flag registry、release manifest 草案 | 未知配置/flag/secret ref 能被拒绝 | 默认全部 flag-off |
| 4 | Task/Turn/Permission/Job/Delivery schema 与状态迁移 fixture | 合法/非法迁移和未知状态测试 | 不进入旧入口切换 |
| 5 | repository/ports 与最小迁移 dry-run | 空库、旧 JSONL 导入、rollback/readiness | 保留旧 adapter |
| 6 | event envelope、event store、outbox、cursor contract | 重复、乱序、断线、重启重放 | 禁止前端消费新事件 |
| 7 | TaskCoordinator/lease/abort/permission application service | kill、lease expiry、ASK/resolve、recovery | 高风险工具继续关闭 |
| 8 | v2 API 和 auth/scope middleware 骨架 | OIDC/local 边界、越权、幂等、request_id | 只开放 health 和 fake smoke |
| 9 | 前端 reducer 与最小任务/权限/恢复页面 | 刷新、断线、事件重建和错误展示 | 维持 legacy UI |
| 10 | C0 review 包和 PR-S0/S1 merge decision | `check_plan_consistency`、`check_traceability`、全量 baseline、Owner 签字 | 周期不出关，拆分或 flag-off |

每日结束前更新 evidence manifest；依赖阻塞超过一个工作日必须登记，超过两个工作日必须降级为 flag-off、替代方案或拆分 PR。每日 smoke、每周 restore drill、周期末 release review 和事故演练必须沿用同一证据目录与 commit 关联。

### 14.36 FINAL-PLAN-GATE

只有下列条件全部满足，才停止计划书完善并转入真正的 PR 开发：

| Gate | 自动或人工检查 | 必须保留的证据 | 不通过动作 |
|---|---|---|---|
| G-50 | 支持矩阵与 OIDC/local/legacy 边界一致 | `contracts/auth.schema.json`、OIDC/local/legacy 测试报告 | 企业 GA 关闭，保留受限 local/pilot |
| G-51 | 五类角色、tenant scope、workspace scope 和 deny-by-default 一致 | allow/deny matrix、越权测试、RBAC fixture | managed multi-tenant 关闭 |
| G-52 | v2 管理 API、幂等、撤销、双人审批、审计一致 | OpenAPI/schema、E2E、`support-access.json`、audit 对账 | 管理面关闭，仅保留内部运维 |
| G-53 | typed config、secret reference、manifest、启动校验只有一个真相源 | config hash、secret scan、release-manifest、clean-start 日志 | 启动拒绝，不能发布 |
| G-54 | export/delete/legal hold/revoke 完成证明可独立复核 | export/deletion/tenant-close proof、恢复报告 | 租户关闭和 GA 均阻断 |
| DAY-0 | 新环境能按顺序生成 baseline 和 Owner/REQ/contract 目录 | `baseline.json`、命令日志、目录清单 | 不允许进入 C1 |
| TRACE | 所有 REQ、PR、代码、schema、测试、指标、runbook、Owner、release gate 闭合 | `traceability-report.json` | 周期签字失败 |
| FORMAT | 引用、路径、表格、编号、Markdown 换行和术语一致 | `plan-consistency-report.json` | 仅修文档，不扩大范围 |

`FINAL-PLAN-GATE` 通过的含义是：计划已经达到**可以无歧义开工、逐项编码、逐项测试、逐项发布和逐项运营验收**的标准；不代表 XEYO 已经实现或上线。达到该门禁后，后续任务应转移到 PR-S0–S13 的真实开发、测试、灰度和运营，不再通过继续扩写计划书代替工程交付。

## 十五、最终判断

XEYO 当前最值得投资的不是增加功能数量，而是把已有能力变成**单一事实源、统一事件协议、可恢复任务状态、可挂起权限、可验证 workspace、可审计副作用和可重复交付的产品系统**。这条路线能最大化复用现有 QueryEngine、SessionPool、iLink、File Helper、前端主链路、IndexedDB、设置/profile、Sidebar、RemoteQrPanel、usage 双源策略、memory 评估控制面和 rewind 后端骨架。新增事实进一步表明：IndexedDB 和 ContextPasture 都应被定位为可靠的下游投影，而不是后端任务权威；`OfflineReplayRoute` 应作为性能基准保留，但不能替代真实跨入口验收；remote/File Helper/iLink 的现有 JobStore 与投递层应被接入统一协议，而不是被误判为已经完成的 durable control plane。与此同时，Session JSONL 续聊、进程内 SessionPool 和 DeepSeek 基础 SSE 解析都应保留为增量改造基线；它们分别还不是完整任务账本、高可用调度器或可靠 Provider 层。除非秘密卫生、恢复完整性、错误可观测性、真实 readiness 和 G0–G5 证据同时达标，否则 XEYO 仍应按内部试点或受限灰度管理。

若只能先安排一个短周期，优先完成 C0 的基线冻结，然后完成 C1 的事件 envelope、C2 的 SessionTaskState/cwd/Tauri workspace 作用域，并同步完成 C3 中的工具 registry contract guard。随后才进入 Permission ASK、remote/iLink、前端 reducer 和回溯审计。若计划按完整生命周期执行，则依次经过 C4–C6 的可用性、安全和发布闭环，再以证据门禁推进 C7–C8 memory，最后进入 C9–C12 的 Java、MCP/LSP、多 Agent 与持续运营。

完成标准不是“所有未实现工具都已补齐”，也不是“离线 bench 回放通过”或“远程 job 进入 done”就算完成，而是 XEYO 能在不同入口下稳定运行同一会话，危险操作可询问和恢复，工作区不串线，事件可重放，远程文件副作用有独立可诊断状态，成本边界可解释，数据可迁移，制品可安装和回滚；所有后续扩展都必须在这套核心契约上演进。

## References

[1]: ../python/engine/query_engine.py "XEYO QueryEngine：会话提交、事件流、恢复与回溯接缝"
[2]: ../python/engine/query_loop.py "XEYO query loop：上下文投影、模型—工具回流、预算与停止"
[3]: ../python/server/session_pool.py "XEYO SessionPool：lease、busy、interrupt、stale 回收与 session 生命周期"
[4]: ../python/tests/test_resume_from_disk.py "XEYO 跨重启 session hydrate 与隔离契约测试"
[5]: ../python/channels/ilink/service.py "XEYO iLink：peer session、长轮询、队列、事件游标与镜像"
[6]: ../python/channels/filehelper/service.py "XEYO File Helper：intentionally thin final-only 通道"
[7]: ../gui/src/stores/chatStore.ts "XEYO 前端 chatStore：本地发送、流式处理、remote 镜像与 rollback"
[8]: ../gui/src/stores/settingsStore.ts "XEYO 前端 settingsStore：profile、budget、remoteChannel 与持久化"
[9]: ../python/usage/combine.py "XEYO usage 汇总：vendor/local/mixed 双源策略"
[10]: ../python/session/state.py "XEYO SessionState：会话工作目录、消息、预算、中止与工作快照边界"
[11]: ../python/session/persistence.py "XEYO session persistence：会话 JSONL 写盘开关与默认路径"
[12]: ../python/engine/abort.py "XEYO AbortController：中止信号与任务取消边界"
[13]: ../python/permissions/gate.py "XEYO permission gate：工具权限裁决与 ASK/DENY/ALLOW 边界"
[14]: ../python/msgtypes/events.py "XEYO EngineEvent 联合类型"
[15]: ../python/server/app.py "XEYO FastAPI 主入口与 SSE 协议"
[16]: ../python/bridge/http.py "XEYO HTTP bridge 入口"
[17]: ../python/bridge/__main__.py "XEYO JSONL stdin/stdout bridge 入口"
[18]: ../java/pom.xml "XEYO Java Maven 构建配置"
[19]: ../java/src/main/java/xeyo/rpc/JsonRpcServer.java "XEYO Java JsonRpcServer 当前实现"
[20]: ../java/src/main/java/xeyo/tools/ToolRuntimeServer.java "XEYO Java ToolRuntimeServer 当前实现"
[21]: ../java/src/main/java/xeyo/tools/ToolRegistry.java "XEYO Java ToolRegistry 当前实现"
[22]: ../python/tools/catalog.py "XEYO 工具目录：ENABLED_TOOLS、SCAFFOLD_TOOLS 与默认 registry"
[23]: ../python/tests/test_catalog.py "XEYO 默认 registry 不注册 scaffold 工具的回归测试"
[24]: ../python/tests/test_quality_plan.py "XEYO memory/L5 质量计划、默认 gate 与离线验证回归"
[25]: ../python/scripts/memory_stack_eval.py "XEYO memory stack 评估、AB、r/theta 探针与每日监控"
[26]: ../python/scripts/kv_cache_probe.py "XEYO 基于真实 QueryEngine 的 KV cache 在线探针"
[27]: ../gui/src/lib/groupTranscript.test.ts "XEYO 前端 transcript 分组与增量投影测试"
[28]: ../gui/src/lib/toolActivity.test.ts "XEYO 前端工具活动、文件变更与 Todo 投影测试"
[29]: ../gui/src/lib/streamMarkdown.test.ts "XEYO 前端流式 Markdown 增量解析测试"
[30]: ../gui/src/lib/types.ts "XEYO 前端 BridgeEvent 与 transcript 类型"
[31]: ../python/types/permissions.py "XEYO 权限 pending 占位模型"
[32]: ../python/tests/test_history_continuity.py "XEYO 历史续聊、model 变更与 cwd stash 回归"
[33]: ../python/tests/test_usage_combine.py "XEYO vendor/local/mixed usage 合并回归"
[34]: ../gui/src/stores/remoteStore.test.ts "XEYO remoteStore session gating、streaming 与去重测试"
[35]: ../gui/src/stores/settingsStore.profiles.test.ts "XEYO settings profile 迁移、切换与保留最后 profile 测试"
[36]: ../gui/src-tauri/src/lib.rs "XEYO Tauri 桌面壳自启后端与 XEYO_CWD 注入"
[37]: ../python/server/workspace_fs.py "XEYO workspace_fs 路径逃逸阻断与文件操作"
[38]: ../gui/src/components/Sidebar.tsx "XEYO Sidebar：workspace/session 导航、搜索和持久化"
[39]: ../gui/src/components/RemoteQrPanel.tsx "XEYO RemoteQrPanel：iLink/File Helper 二维码登录与轮询状态"
[40]: ../python/tools/todowritetool/store.py "XEYO TodoStore：进程内默认 key 的 Todo 存储"
[41]: ../python/tools/todowritetool/types.py "XEYO Todo 状态类型与三态边界"
[42]: ../python/pyproject.toml "XEYO Python 构建、测试和依赖配置"
[43]: ../gui/package.json "XEYO CLI 构建、类型检查、Vitest 与 Tauri 命令"
[44]: ../gui/src/App.tsx "XEYO CLI 路由与应用生命周期入口"
[45]: ../gui/src/lib/apiBase.ts "XEYO CLI 浏览器/Tauri API 基址选择"
[46]: ../gui/src/lib/api.ts "XEYO CLI 流式 API、旧协议兼容和错误处理"
[47]: ../docs/00-总计划书-可上线路线图.md "XEYO 总计划与上线路线图"
[48]: ../docs/08-从Demo到企业级.md "XEYO 从 Demo 到企业级的三层路线"
[49]: ../docs/09-企业级落地计划-时序与排期.md "XEYO 企业级时序、依赖与阶段出口"
[50]: ../docs/10-完整记忆体系.md "XEYO 完整记忆体系与长期门禁"
[51]: ../docs/11-记忆体系落地步骤书.md "XEYO memory Wave 1–6 实施步骤与 PR 切分"
[52]: ../docs/12-压缩质量验证计划书.md "XEYO 压缩质量、evidence gate 与回滚计划"
[53]: ../docs/13-历史消息编辑与回溯实施计划.md "XEYO 历史编辑、回溯事务与发布门禁"
[54]: ../docs/task6-Java工具运行时.md "XEYO Java ToolRuntime 里程碑与验收"
[55]: ../docs/task7-会话持久化与发布.md "XEYO 会话持久化、发布和交付门禁"
[56]: ../python/channels/filehelper/broadcast.py "XEYO File Helper 轻量 SSE 广播边界"
[57]: ../python/channels/ilink/store.py "XEYO iLink credentials 文件存储"
[58]: ../python/channels/ilink/media.py "XEYO iLink 媒体加密、落盘与失败处理"
[59]: ../gui/src/main.tsx "XEYO CLI 主题恢复与 Tauri 运行模式入口"
[60]: ../gui/src/lib/streamMarkdown.test.ts "XEYO 前端 Markdown 增量解析与 fence/math 回归"
[61]: ../gui/src/components/MessageList.test.tsx "XEYO 前端消息列表空态、历史和流式错误回归"
[62]: ../gui/src/hooks/useTypewriter.test.ts "XEYO 前端 typewriter 增量、emoji 与替换回归"
[63]: ../python/channels/api.py "XEYO remote API 与 FinalOnlyRunner/JobStore 接线"
[64]: ../python/channels/filehelper/api.py "XEYO File Helper API、状态流和静态 UI"
[65]: ../python/channels/api.py "XEYO remote API：token 保护的 health、submit 和 job poll 接口"
[66]: ../python/channels/auth.py "XEYO remote auth：单一进程级 XEYO_REMOTE_TOKEN 与 Bearer/X-Remote-Token 校验"
[67]: ../gui/src-tauri/capabilities/default.json "XEYO Tauri main window capability manifest：core/window/shell-open/dialog 权限与当前缺少的 filesystem 分区"
[68]: ../python/channels/base.py "XEYO 通道抽象：InboundMessage 与 inbound-to-final 的薄接口"
[69]: ../python/channels/remote_deliver.py "XEYO 远程文件/图片投递：优先 iLink、文件回退 File Helper 的投递策略"
[70]: ../gui/src/bench/OfflineReplayRoute.tsx "XEYO OfflineReplayRoute：直接注入 chatStore 的离线性能回放入口，不经过真实协议"
[71]: ../gui/src/lib/db.ts "XEYO 前端 IndexedDB：xeyo-web schema version 4、spaces/sessions/messages/kv 与迁移删除"
[72]: ../gui/src/stores/chatStore.test.ts "XEYO chatStore 主回归：会话恢复、远程流、workspace 合并、回溯与 usage 边界"
[73]: ../gui/src/stores/explorerStore.ts "XEYO explorerStore：workspace 文件浏览 API 的前端投影与目录缓存"
[74]: ../gui/src/stores/explorerStore.test.ts "XEYO explorerStore 测试：workspace 切换、目录缓存、预览与写回边界"
[75]: ../gui/src/components/FilesChanged.tsx "XEYO FilesChanged：工具文件变更的展示投影"
[76]: ../gui/src/components/TodoList.tsx "XEYO TodoList：TodoSnapshot 的展示组件"
[77]: ../gui/src/components/StreamingMarkdown.tsx "XEYO StreamingMarkdown：流式 Markdown 展示与 fallback"
[78]: ../gui/src/lib/toolFilePath.ts "XEYO toolFilePath：工具活动文件路径归一化辅助"
[79]: ../gui/src/lib/sanitizeToolInput.ts "XEYO sanitizeToolInput：前端工具参数脱敏展示辅助"
[80]: ../gui/src/lib/frameScheduler.ts "XEYO frameScheduler：前端帧级批处理与渲染调度"
[81]: ../gui/src/lib/layoutBusy.ts "XEYO layoutBusy：布局忙碌状态标记"
[82]: ../gui/src/lib/idle.ts "XEYO idle：浏览器空闲回调与调度辅助"
[83]: ../gui/src/components/DiffPreview.tsx "XEYO DiffPreview：差异内容展示，不承担 revision 提交"
[84]: ../gui/src/components/EditableMarkdown.tsx "XEYO EditableMarkdown：本地 Markdown 编辑与提交前序列化"
[85]: ../gui/src/components/ErrorBanner.tsx "XEYO ErrorBanner：前端错误提示展示"
[86]: ../gui/src/components/MessageBubble.tsx "XEYO MessageBubble：消息、远程来源和工具回退展示"
[87]: ../gui/src/components/ModelPicker.tsx "XEYO ModelPicker：本地 profile/model 选择与配置展示"
[88]: ../gui/src/components/PaneResizeHandle.tsx "XEYO PaneResizeHandle：本地面板尺寸拖拽"
[89]: ../gui/src/components/PaneSlot.tsx "XEYO PaneSlot：面板容器布局"
[90]: ../gui/src/components/TextFileEditor.tsx "XEYO TextFileEditor：工作区文本编辑器的前端保存调用"
[91]: ../gui/src/components/ThinkingLine.tsx "XEYO ThinkingLine：思考文本展示"
[92]: ../gui/src/components/TurnRail.tsx "XEYO TurnRail：回合轨道视觉分组"
[93]: ../gui/src/components/WorkspaceImg.tsx "XEYO WorkspaceImg：工作区图片展示与缓存边界"
[94]: ../gui/src/components/BrandMark.tsx "XEYO BrandMark：品牌静态视觉组件"
[95]: ../python/engine/budget.py "XEYO submit 级预算门禁：turn/token/USD/CNY 约束与 unknown 计费边界"
[96]: ../python/usage/ledger.py "XEYO usage ledger：本地用量记录与按日/厂商/模型聚合"
[97]: ../python/usage/pricing.py "XEYO pricing：实时价格网络缓存、24 小时 TTL 与离线回退"
[98]: ../python/channels/jobs.py "XEYO JobStore：进程内 queued/running/done/error 记录与有限 public projection"
[99]: ../python/channels/runner.py "XEYO FinalOnlyRunner：按 session 串行的远程执行与进程内广播回调"
[100]: ../python/channels/remote_deliver.py "XEYO remote_deliver：异步微信文件投递副作用层、warning 失败边界与无持久审计"
[101]: ../gui/src/pasture/Pasture.tsx "XEYO Pasture：上下文状态驱动的展示层挂载"
[102]: ../gui/src/pasture/PastureEvents.ts "XEYO PastureEvents：浏览器自定义事件适配层"
[103]: ../gui/src/pasture/PastureStorage.ts "XEYO PastureStorage：全局装饰状态 localStorage 持久化，不按 workspace/session 隔离"
[104]: ../gui/src/test/setup.ts "XEYO Vitest 全局设置：同步 RAF 与 settingsStore mock，非真实启动/协议运行时"
[105]: ../python/requirements.txt "XEYO Python 运行依赖清单：版本范围与供应链锁定边界"
[106]: ../gui/package-lock.json "XEYO CLI npm lockfile：Node 依赖完整性与可重复安装边界"
[107]: ../gui/src-tauri/cargo.toml "XEYO Tauri Rust/Cargo 构建配置：原生依赖、版本与 release profile"
[108]: ../start-xeyo.bat "XEYO 本地启动包装脚本：依赖检查、端口与启动行为"
[109]: ../start-remote-tunnel.bat "XEYO 远程隧道启动包装脚本：远程访问与进程托管边界"
[110]: ../xeyoq.bat "XEYO release 启动包装脚本：进程清理与关闭边界"
[111]: ../python/scripts/wait_health.py "XEYO 启动健康检查：当前 HTTP 轮询 readiness 边界"
[112]: ../python/scripts/smoke_engine.py "XEYO engine smoke：fake backend/echo 的离线烟测路径"
[113]: ../gui/src-tauri/tauri.conf.json "XEYO Tauri 打包配置：CSP、签名、资源和升级发布边界"
[114]: ../gui/src-tauri/gen/schemas/acl-manifests.json "XEYO Tauri 生成 ACL manifest schema：框架权限格式而非项目安全策略"
[115]: ../gui/src-tauri/gen/schemas/capabilities.json "XEYO Tauri 生成 capabilities schema：能力配置格式边界"
[116]: ../gui/src-tauri/gen/schemas/windows-schema.json "XEYO Tauri 生成 windows schema：窗口配置格式边界"
[117]: ../.gitignore "XEYO 根目录忽略规则：版本控制层的运行数据与秘密排除意图"
[118]: ../.env.example "XEYO 环境变量模板：本地、模型、远程和 File Helper 配置分区"
[119]: ../python/.xeyo_ilink/credentials.json "XEYO iLink 运行时凭据文件：工作树秘密暴露风险依据"
[120]: ../python/.xeyo_filehelper/seen_index.json "XEYO File Helper seen index：本地文本去重状态而非审计日志"
[121]: ../python/.xeyo_filehelper/component_crx_cache/metadata.json "XEYO File Helper component CRX cache metadata：当前为空的缓存元数据"
[122]: ../python/.xeyo_filehelper/extensions_crx_cache/metadata.json "XEYO File Helper extensions CRX cache metadata：组件供应链验证边界"
[123]: ../gui/src-tauri/gen_icons.py "XEYO Tauri 图标生成脚本：资源输出与制品清单边界"
[124]: ../capture-xy-main-verify.ps1 "XEYO Windows 主路径视觉验证脚本：固定坐标与截图采样边界"
[125]: ../gui/src/lib/tauri.ts "XEYO 前端 Tauri 检测：运行时全局标志判断，不是安全授权"
[126]: ../gui/src/lib/api.stream.test.ts "XEYO 前端 SSE API 单测：流解析与 side-channel 回调，不是跨入口 E2E"
[127]: ../gui/public/bench/chat-replay.json "XEYO bench chat replay fixture：固定本地回放数据，不含真实协议身份"
[128]: ../gui/scripts/fixtures/chat-replay.json "XEYO CLI 测试 chat replay fixture：测试夹具而非真实跨入口事件回放"
[129]: ../gui/src-tauri/icons/android/mipmap-anydpi-v26/ic_launcher.xml "XEYO Android adaptive-icon 资源：不代表 Android 制品已构建或签名"
[130]: ../list-source.ps1 "XEYO 源码清单脚本：有限扩展名盘点，不等于 SBOM 或企业覆盖证明"
[131]: ../python/channels/base.py "XEYO 通道抽象：仅承诺入站 job_id 与最终文本"
[132]: ../python/channels/filehelper/service.py "XEYO File Helper service：独立轻量事件/流/队列投影，不是任务状态机"
[133]: ../python/channels/filehelper/bridge.py "XEYO File Helper Playwright bridge：浏览器生命周期、登录、轮询与 SeenIndex"
[134]: ../python/bridge/http.py "XEYO HTTP bridge：独立 ThreadingHTTPServer、EnginePool 与 SSE 入口"
[135]: ../python/bridge/__main__.py "XEYO JSONL bridge：独立 stdin/stdout 单会话入口"
[136]: ../python/model/client.py "XEYO ModelClient：仅有 stream(messages, tools, abort) 的模型边界"
[137]: ../python/model/chunks.py "XEYO ModelChunk：仅有 text_delta/tool_use 的窄模型协议"
[138]: ../python/model/openai_compat.py "XEYO OpenAI-compatible 模型适配与 SSE/tool/usage 归一化"
[139]: ../python/model/deepseek.py "XEYO DeepSeek 模型适配：provider SSE 与 usage 边界"
[140]: ../python/model/fake.py "XEYO fake model：echo/tool 回流测试替身"
[141]: ../python/model/vendor_models.py "XEYO vendor model discovery：能力、上下文与价格归一化"
[142]: ../python/tools/orchestration.py "XEYO 工具编排：安全工具并发、危险工具串行与 abort 检查"
[143]: ../python/tools/fileio/file_write_tool.py "XEYO FileWriteTool：read-before-write 与 rewind snapshot/inverse 接缝"
[144]: ../python/tools/fileedittool/file_edit_tool.py "XEYO FileEditTool：精确编辑、hash/mtime 与 rewind 记录接缝"
[145]: ../python/tests/test_rewind_service.py "XEYO RollbackService 事务、冲突、幂等与 recovery 回归"
[146]: ../python/tests/test_rewind_api.py "XEYO rewind API：feature flag、preview/execute/status 契约"
[147]: ../python/tests/test_rewind_query_engine.py "XEYO QueryEngine 正常 turn 与 revision/journal 接线回归"
[148]: ../python/tests/test_runtime_c2.py "XEYO C1/C2 压缩、sidecar、KV 前缀和 message id 回归"
[149]: ../python/tests/test_permissions.py "XEYO 权限安全基线：路径、危险操作与 Registry 二次阻断"
[150]: ../python/tests/test_tool_orchestration.py "XEYO 工具编排并发与安全顺序回归"
[151]: ../python/tests/test_governance.py "XEYO memory governance：schema、source/confidence、supersedes 与墓碑回归"
[152]: ../gui/src/lib/remoteStream.test.ts "XEYO 远程流增量、reset、stale offset 与 accumulator 回归"
[153]: ../gui/src/lib/remoteSession.test.ts "XEYO 远程 session gating、镜像切换与 legacy 兼容回归"

[154]: ../python/tests/test_session_pool_busy.py "XEYO SessionPool busy 回归：同 session 串行、busy lease、stale reclaim 与并发拒绝"
[155]: ../python/tests/test_record_transcript.py "XEYO transcript 回归：message id 去重、JSONL append、禁用持久化与失败边界"
[156]: ../python/tests/test_vendor_models.py "XEYO vendor model 回归：供应商模型能力、SSE/usage 解析与降级边界"
[157]: ../python/session/state.py "XEYO SessionState：cwd、MessageStore、BudgetTracker、AbortController 与 WorkingSnapshot 的当前数据类"
[158]: ../python/session/persistence.py "XEYO session persistence：JSONL 写盘开关、默认 sessions 路径与 session 文件名映射"
[159]: ../python/session/message_store.py "XEYO MessageStore：进程内消息列表、API 映射与当前缺失的 message revision/并发契约"
[160]: ../python/session/hydrate.py "XEYO session hydrate：JSONL 消息还原、坏行容错与缺失的完整性告警/schema version"
[161]: ../python/session/record_transcript.py "XEYO transcript recorder：message id 去重、JSONL append 与当前缺失的文件锁/fsync/审计字段"
[162]: ../python/server/session_pool.py "XEYO SessionPool：进程内锁、busy lease、history stash 与 stale reclaim 的横向扩展边界"
[163]: ../python/model/deepseek.py "XEYO DeepSeek V4 Flash SSE 客户端：双 HTTP 路径、tool_call 缓冲、usage 与缺失的 retry/熔断"
[164]: ../python/common/errors.py "XEYO common errors：ProviderError/NetworkError 与友好错误映射、稳定错误契约的缺口"
