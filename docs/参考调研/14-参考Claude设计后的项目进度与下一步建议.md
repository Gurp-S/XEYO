# XEYO 当前项目进度与下一步建议

> 更新时间：2026-08-20  
> 依据：XEYO 当前生产源码、Python/前端测试、启动与构建配置、项目文档，以及 `D:\lea\claude\docs` 中关于 QueryEngine、工具运行时、上下文权限、任务状态和远程多 Agent 的设计文档。  
> 本版目标：只保留能够由真实代码支持的判断，明确哪些能力已经存在、哪些只有基础、哪些才是真正的下一步缺口，并把本轮完整源码研读发现统一写回。

## 一、结论先行

XEYO 当前最需要解决的不是继续增加工具、重写 compact，或者提前实现 Java ToolRuntime，而是让**同一轮 session turn 在 FastAPI、HTTP bridge、JSONL bridge、桌面前端、remote runner 和微信 iLink 中拥有同一份可关联、可恢复、可审计的状态**。

核心 Agent 已经可以运行：`QueryEngine` 持有会话查询入口，`query_loop` 驱动模型—工具回流，已有上下文投影、预算、停止、消息持久化和 rewind 接缝。`SessionPool` 的 busy/lease/interrupt/pending interrupt/stale 回收/drop 语义也已有实现和测试。因此，下一阶段不应把这些基础能力描述为“尚未建设”，而应把资源投入集中到跨层语义收口。[1] [2] [3] [4]

Claude 设计中最值得迁移的不是文件名，而是职责边界：入口只接收输入、渲染事件和回传控制命令；QueryEngine 持有会话生命周期；工具通过统一上下文执行；权限询问可以挂起并恢复；任务状态独立于 Todo 文本；远程和平台层复用同一会话核心。[10] [11] [12] [13]

因此建议的优先级为：**P0 统一事件协议和三套入口、建立 SessionTaskState 并修复 session/workspace 作用域、完成 Permission ASK 挂起—确认—恢复、将 remote/iLink 接到统一状态、让前端消费事件投影，并冻结工具能力矩阵与默认 registry 禁用策略；P1 补审计、回溯事务补偿和安全治理；P2/P3 在现有评估控制面基础上，以 evidence-gated 方式推进 memory/L5，并再做 Java 最小 RPC；P3 才扩展 MCP、LSP、多 Agent 和更多脚手架工具。**

> **关键修正：** memory/L5 不是 P0 空白。`memory/simulator`、`memory_stack_eval.py`、`p2_full_campaign.py`、`formula_live_ab.py`、质量计划测试、黄金轨迹、AB gate、theta/r 探针和每日 ledger/C2 监控已经构成较完整的离线/旁路评估控制面；当前缺口是生产 runtime 接线、真实 shadow/AB、回滚门禁与长期观测闭环，且默认生产模式仍是 `project`、C2 gate 默认关闭。[24] [25] [26]

## 二、参考 Claude 后保留的架构原则

| Claude 设计原则 | XEYO 对应代码 | 当前判断 | 路线含义 |
|---|---|---|---|
| 入口不重新实现 Agent 主循环 | `QueryEngine`、`query_loop`、FastAPI、HTTP bridge、JSONL bridge、iLink | 核心循环已有，但三个入口协议和生命周期封装不一致 | 保留一个引擎事实源，入口改成薄适配器 |
| QueryEngine/Session 持有会话级生命周期 | `engine/query_engine.py`、`server/session_pool.py` | 会话提交、busy、interrupt 和恢复基础已存在 | 在引擎层增加统一 task state 与事件发布，不重写主循环 |
| query loop 负责模型、工具、权限回流 | `engine/query_loop.py`、`tools/tool_registry.py`、`permissions/*` | 模型—工具循环可用，ASK 不能挂起恢复 | 优先补 pending/resolve/resume，不新增第四套循环 |
| Context 与 UI transcript 分离 | `prompt/*`、`memory/*`、`compact.py`、前端 transcript | C0/C1/C2 与投影基础已有 | 固化上下文输入输出，禁止把前端拼接 transcript 当成唯一事实源 |
| 工具执行上下文包含取消与权限回调 | `tools/*`、`permissions/gate.py`、`ToolUseContext` 相关代码 | 工具和三态决策已有，权限回流缺闭环 | 冻结工具结果、取消和审批协议，再扩展工具 |
| `canUseTool` 是可挂起的权限协议 | `permissions/filesystem.py`、`permissions/gate.py` | `ALLOW/DENY/ASK` 已有，但 ASK 最终被降为拒绝 | P0 实现 request id、pending、resolve、恢复和超时 |
| TaskState 不等于 Todo 文本 | `TodoWrite`、`TodoStore`、`JobStore`、`chatStore` | 三种局部状态并存，无统一会话任务状态 | 新建 `SessionTaskState`，TodoWrite 仅作为兼容写入器 |
| 工具目录的 schema 数量不等于可执行能力 | `tools/catalog.py`、`tools/stub.py`、各 scaffold tool、`test_catalog.py` | 默认 registry 已主动排除 scaffold，但能力矩阵和 contract guard 仍需固化 | 在实现更多工具前，明确真实可用、显式禁用和未实现三类，防止模型调用空壳工具 |
| Python 编排与 Java 工具后端分离 | `java/pom.xml`、Java RPC/ToolRuntime 类 | Java 连构建层都只是前基础设施，尚无 RPC 依赖 | P2 做单一 schema、最小 JSONL/RPC 和一个低风险工具 |
| Remote/MCP/Multi-agent 在核心状态成熟后平台化 | `channels/runner.py`、`channels/ilink/*`、MCP 空壳工具 | remote/iLink 已能复用 SessionPool，但不应各自发展为 Agent 核心 | 先统一状态，再扩展平台能力 |

## 三、当前实际状态：已完整、已有基础与真正缺口

下表是本轮完整源码复核后的收窄判断。“已完整”表示该能力已经有实现和相应测试或明确产品化边界；“已有基础”表示主路径存在，但还需要接入更高层的统一协议；“真正缺口”表示下一阶段必须新建的语义或安全闭环。

| 领域 | 状态等级 | 真实代码事实 | 不应再写成什么 | 对路线的影响 |
|---|---|---|---|---|
| Agent 主循环 | 已完整 | `QueryEngine` 负责会话提交、事件流、恢复和 rewind 接缝；`query_loop` 负责模型—工具循环、预算和停止 | “需要重写主循环” | 不重写；围绕引擎补统一状态和事件 |
| Context/compact | 已有基础且可用 | 已有 C0/C1/C2、上下文投影、压缩决策和 memory runtime | “compact 尚未实现” | 收口契约、边界测试和各入口一致性 |
| SessionPool busy/lease | 已完整 | 已有 lease、busy、interrupt、pending interrupt、stale 回收和 drop；跨重启 session hydrate 也有契约测试 | “SessionPool 缺少基本 busy/lease” | 只补 task state 映射和并发边界，不从零建设 lease |
| 会话恢复 | 已完整 | per-session JSONL、原 message id 恢复、目标 session 隔离、坏行容忍、禁用持久化开关均有测试；model 变更保留历史、set_cwd stash 后恢复也有回归。[32] | “重启续聊尚未支持” | 保持现有能力，优先处理恢复后的 task/permission/revision 状态 |
| 前端本地持久化 | 已完整 | IndexedDB 已有 `spaces`、`sessions`、`messages`、`kv` 以及 rollback state；localStorage/IndexedDB 迁移也已有 | “前端没有持久化” | 将后端事件投影持久化进去，而不是另建存储 |
| 设置与 profile | 已完整 | 多 profile、provider/model/apiKey/baseUrl、thinking、budget、remoteChannel、主题和布局设置均有 store/UI/持久化；profiles 测试覆盖 legacy 迁移、新增/切换 profile、禁止删除最后一个 profile | “设置面板仍待建设” | 只补设置与后端 schema、审批和安全配置的对齐 |
| 前端主链路与投影测试 | 已有稳定测试 | `chatStore` 覆盖发送、busy、工具行合并、流式批处理、remote 镜像和 rollback；`groupTranscript`、`toolActivity`、`streamMarkdown`、`remoteStore`、路径/脱敏/布局也有稳定回归 | “前端主链路未验证”或“需要重做聊天 UI” | 不重做 UI；改为事件 reducer、版本和断线语义，并保留这些测试为回归基线 |
| 工作区导航与二维码登录 UI | 已完整且产品化 | `Sidebar` 已有工作区/会话分组、搜索、Ctrl+K、新建会话、打开/删除 workspace 和宽度持久化；`RemoteQrPanel` 已区分 iLink/File Helper，覆盖 starting/qr/scanned/error、revision、重轮询和停止 | “Sidebar/二维码登录 UI 仍是缺口” | 不投入核心架构重做；只让它们消费统一状态和错误 |
| 用量与成本 | 已有较完整策略 | vendor/local/mixed 三态合并已有回归：vendor 权威、vendor 为空时 local fallback、vendor 有总计但无模型细分时保留 mixed；ledger/vendor 解析和前端展示已有。[33] | “usage 只有本地估算”或“三态合并尚未实现” | 保留双源策略；后续只补 session/turn 关联、时间范围和审计可见性 |
| iLink 微信通道 | 已有较完整契约 | 按 peer 隔离 session、context token、长轮询、入站排队、超时恢复、服务层事件游标和镜像测试均已有；`session_id_for` 对 userId 做 `ilink:<uid>` 映射 | “iLink 只是简单壳” | 保留现有契约；P0 后接统一事件、permission/task/stop |
| File Helper | 有意保持薄实现 | `File Helper` 是 intentionally thin 的 final-only 通道，职责是接收和发送最终结果，不是完整工具生命周期镜像 | “File Helper 需要镜像所有工具事件” | 不改造成 iLink；只维护 final-only、错误和投递可靠性 |
| EngineEvent | 已有基础但不完整 | 已有 delta/tool/usage/final/stopped/result 事件，但联合类型只有 7 类，缺少 permission/task/approval 等统一状态事件和 envelope 字段 | “没有事件系统” | 扩展统一 envelope 和 task/permission 事件 |
| 三套入口协议 | 真正缺口 | FastAPI/8000、HTTP bridge/8765、JSONL stdin/stdout 各自持有协议或引擎入口，SSE/JSONL 语义没有统一 envelope；HTTP bridge 还自持独立 EnginePool | “只需再补一个前端事件类型” | P0 统一核心发布器、适配器、session/turn/event 身份 |
| Permission ASK | 真正缺口 | 策略已有 `ALLOW/DENY/ASK`，但 `enforce_decision` 将 ASK 在执行边界降为拒绝，没有 pending store、resolve API 和 resume | “需要新增三态策略” | P0 做真实挂起—确认—恢复闭环 |
| SessionTaskState | 真正缺口 | TodoWrite 是进程内工具清单，默认 `DEFAULT_TODO_KEY = "default"`；JobStore 是远程投递状态；chatStore 是 UI 投影，三者都不是会话权威任务状态 | “把 TodoStore 改名即可” | P0 新建会话级状态，并让其发布事件 |
| remote job 对齐 | 已有基础但未统一 | `FinalOnlyRunner` 和 JobStore 已有 queued/running/done/error；缺 waiting permission、stopping、turn 绑定和统一错误原因 | “远程执行完全没有队列” | 映射到 SessionTaskState，不另建 Agent |
| workspace/cwd 作用域 | 真正缺口，且桌面入口有额外风险 | `session/cwd.py` 通过模块级全局变量保存 cwd，`set_cwd` 不做 `os.chdir`，多 session 并发仍可能串目录；Tauri `lib.rs` 自启后端时固定注入 `XEYO_CWD=<Python 根>`，不是用户当前 workspace，必须验证前端 workspace 覆盖是否可靠。[36] | “工作区权限已经完全按 session 隔离”或“Tauri 已自动绑定用户 workspace” | P0/P1 交界的并发与入口作用域修复，先于扩大远程能力 |
| 工具能力矩阵与 registry 策略 | 已有禁用基础，能力矩阵仍需固化 | 真实可用的核心工具包括 Echo、GetTime、Screenshot、SendToWeChat、Bash、Read/Write/Edit、Glob/Grep、TodoWrite、MemoryWrite/Forget/Search；Task*/AskUser/Plan/MCP/LSP/Web/Agent/Skill/Notebook/SendMessage 等主要为 schema + `not_implemented`，`task_creat_tool.py` 为空；`test_catalog.py` 证明 SCAFFOLD_TOOLS 不注册到默认 registry | “工具目录里有 schema 就等于已实现”或“需要一次性实现全部 Claude 工具” | P0 先冻结 `ENABLED_TOOLS`/`SCAFFOLD_TOOLS` 边界、contract tests 和用户可见能力声明；不盲目扩充工具 |
| 活动日志与审计 | 已有 UI、缺后端审计 | `ActivityLog` 能展示工具参数、输出和 diff，但数据来自 transcript/toolActivity 投影，不是后端不可篡改审计日志 | “需要新建活动日志面板” | 保留 UI，新增后端 audit/event/revision 对齐 |
| rewind/rollback | 后端骨架成熟，端到端未收口 | `RollbackService` 已有 preview、execute、幂等、冲突、recovery_required 等事务骨架；默认 feature flag 关闭，入口/API/UI/补偿和可观测性仍需补 | “回溯后端尚不存在” | P1 补开放、事件、恢复和前端事务补偿 |
| memory/L5 | 已有完整评估控制面，生产接线 evidence-gated | simulator 有不变量、1000 次确定性、黄金轨迹、theta/r 探针、AB gate；campaign/replay、`memory_stack_eval.py`、`formula_live_ab.py`、每日 ledger+C2 监控和 docs/12 表 D 写回均已存在；但 `XEYO_L5=project` 默认只走 C0+C1，C2 gate 默认关闭，`kv_cache_probe.py` 是脚本级在线探针而非持续监控，simulator 明确不接 `query_loop` | “L5/memory 是 P0 空白”或“v6.1 已默认线上” | 放到 P2/P3；先做 production parity、shadow/AB、真实任务质量、回滚和持续观测，不重写离线数学基础设施 |
| Java/RPC | 前基础设施阶段 | `pom.xml` 仅 Java 21 compiler plugin；Java RPC、ToolRuntime、ToolRegistry 多为空壳，无 RPC/JSON/test/package wiring | “已有 Java RPC 接缝” | P2 独立完成最小协议和一个真实工具 |

### 3.1 三个经常被混淆的边界

**第一，SessionPool 已解决资源占用，不等于已经解决任务语义。** 它能够阻止同一 session 的并发执行、接收 interrupt 并回收 stale lease；但它还不是 `SessionTaskState`，也不负责向所有入口发布 waiting permission、stopping、revision 和可恢复状态。后续应做“状态映射”，不是重写 busy/lease。[3] [4]

**第二，iLink 与 File Helper 必须分开。** iLink 已具备按 peer 隔离、长轮询、排队和事件游标等较完整通道契约，后续目标是让它消费统一事件并增加审批、任务状态和停止命令。File Helper 则是有意设计成 final-only；它不需要为了“协议统一”而复制工具调用、工具结果和中间流镜像，只需使用统一的最终结果、错误和投递标识。[5] [6]

**第三，ActivityLog、Todo dock、usage panel、Sidebar 和 RemoteQrPanel 是已有产品界面，不是空白页面。** 真正缺的是它们与后端权威状态的关系：ActivityLog 目前是 transcript 的活动投影，Todo dock 依赖 Todo 快照，usage 已有 vendor/local/mixed 解释，Sidebar/QR 面板已有产品化交互。下一步应替换数据来源和语义边界，而不是重复建 UI。[7] [8] [9] [27] [28] [29] [34] [35] [38] [39]

**第四，memory/L5 的“已有”与“上线”不是同一件事。** 评估脚本、模拟器和质量计划已经存在并且有 gate，但生产默认仍关闭 C2，在线 KV 探针也没有自动写入持续账本或运行时门禁。因此 memory 的后续工作是证据驱动的接入和验收，不是把实验代码直接改成默认生产策略。[24] [25] [26]

## 四、P0：先收口跨入口的身份、状态、安全与可执行能力边界

### P0-1：统一 EngineEvent envelope，并收口三套入口协议

这是第一优先级，因为任务状态、权限审批、远程镜像和前端恢复都必须共享同一个事件身份。目前 `msgtypes/events.py` 已有事件联合类型，但 FastAPI、HTTP bridge、JSONL bridge 和前端 SSE parser 没有统一的 `session_id + turn_id + event_id` 外壳；`gui/src/lib/types.ts` 的 `BridgeEvent` 也仍只有 assistant_delta/tool_call/tool_result/final/stopped/error，缺少身份、顺序、权限和任务字段。[14] [15] [16] [17] [30]

| 项目 | 具体建议 |
|---|---|
| 统一 envelope | 每条事件至少包含 `schema_version`、`session_id`、`turn_id`、递增 `event_id`、`type`、`created_at` 和结构化 `payload`；同一 turn 的事件可去重、排序、断线后 reset/replay |
| 事件类型 | 保留已有 delta/tool/usage/final/stopped/result；新增 `task_state_changed`、`permission_pending`、`permission_resolved`、`job_queued`/`job_started` 的统一表达。状态变化不应埋在 UI 文案中 |
| 权威发布点 | 由 QueryEngine/Session 层创建并发布事件；FastAPI、HTTP bridge、JSONL bridge、remote runner 和 iLink 只做传输适配，不各自推导状态 |
| 三套入口路径 | FastAPI 8000 作为主 HTTP/SSE 入口；HTTP bridge 8765 改为同一 service/session pool 的兼容适配器；JSONL bridge 改为同一事件 schema 的命令行适配器。若保留独立端口，必须共享同一 session/event 语义，不能共享之外再各自拥有权威状态 |
| 前端兼容 | `api.ts` parser 先接受新 envelope，同时兼容旧 OpenAI delta 和 `xy` side-channel；未知事件跳过并记录可诊断信息，不破坏旧客户端 |
| 完成标准 | 同一 turn 从本地桌面、remote API、HTTP bridge、JSONL bridge 和 iLink 观察到相同的 session/turn/event 身份，乱序和重复事件不会生成第二个工具行或第二次最终回复 |
| 预期收益 | 消除三套协议和多处状态猜测，为 P0-2 至 P0-5 提供唯一接缝；后续新增入口不再复制 Agent 生命周期 |

**涉及文件：** 后端重点为 `python/msgtypes/events.py`、`python/server/app.py`、`python/bridge/http.py`、`python/bridge/__main__.py`、`python/engine/query_engine.py`、`python/channels/runner.py`；前端重点为 `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts` 和 `remoteStore.ts`；iLink 仅修改适配和游标处理，不重写已有 peer/session 隔离。

### P0-2：建立 SessionTaskState，并修复 session/workspace 作用域

`TodoWrite`、`JobStore` 和 `chatStore` 解决的是三个局部问题，不能代替会话级任务状态。建议在 `QueryEngine` 或 Session 层增加权威 `SessionTaskState`，同时立即处理 cwd 的模块全局问题和 Tauri 启动注入问题。否则即使前端能显示统一状态，多 session 并发时仍可能把一个会话的工作目录带入另一个会话，桌面壳还可能把 Python 根误当作用户 workspace。

| 项目 | 具体建议 |
|---|---|
| 任务状态 | 建议区分 task 生命周期 `queued/running/waiting_permission/stopping/stopped/succeeded/failed` 与 Todo item 状态 `pending/in_progress/completed`；两者不能共用一个枚举 |
| 身份与版本 | 包含 `session_id`、`turn_id`、可选 `job_id`、`revision`、`updated_at`、`current_tool`、`interruptible`、`error`；每次状态变化产生可去重事件 |
| 状态归属 | QueryEngine/Session 为权威；SessionPool 负责 lease/interrupt 资源协调；JobStore 只保存 remote 投递和结果；chatStore、iLink、Todo dock 只保存投影 |
| Todo 迁移 | `TodoWrite` 继续支持现有调用和 UI。它目前是进程内、按默认 `DEFAULT_TODO_KEY = "default"` 的三态清单；先增加结构化 snapshot 到 TaskState 的兼容写入，再逐步停止让 UI 从 `<todo_list>` 人话文本反解析唯一状态。[40] [41] |
| cwd/workspace | 将 cwd 从模块级变量改为 session/workspace context，`QueryEngine → query_loop → tool permission/filesystem → workspace_fs` 显式传递；每个 session 建立可验证的 workspace identity |
| Tauri 注入 | 检查并修复 `gui/src-tauri/src/lib.rs` 固定注入 `XEYO_CWD=<Python 根>` 的覆盖关系；桌面启动链应把用户选择的 `activeSpace.rootPath` 映射到后端 session/workspace，而不是把 Python 根默认为工作目录；dev/release 两种 resource_dir 路径都要有回归 |
| 恢复 | JSONL hydrate 后恢复任务快照、事件游标和必要的 revision/permission 状态；不能只恢复 messages |
| 完成标准 | 两个并行 session 各自使用自己的 cwd；Tauri 打开两个 workspace 时后端 root 与前端 activeSpace 一致；刷新、切换 session、排队、停止、异常和重启恢复后，均能按 `session_id + turn_id + revision` 查询同一状态 |
| 预期收益 | 将“资源忙不忙”“任务做到哪一步”“工作目录是什么”从 UI 猜测变成可验证的会话事实，降低串 session、桌面误用 Python 根和错误执行风险 |

**涉及文件：** 新增 `python/engine/task_state.py` 或等价模块；修改 `python/engine/query_engine.py`、`python/engine/query_loop.py`、`python/server/session_pool.py`、`python/session/state.py`、`python/session/cwd.py`、`python/permissions/filesystem.py`、`python/server/workspace_fs.py`、`python/channels/jobs.py`、`python/tools/todowritetool/store.py`、`todo_write_tool.py`、`gui/src-tauri/src/lib.rs`；前端修改 `gui/src/lib/types.ts`、`chatStore.ts`、`SessionTodoDock.tsx`、`db.ts`、`explorerStore.ts` 以存储任务投影、游标和 workspace 关联。

### P0-3：实现 Permission ASK 的 pending/resolve/resume 闭环

当前已经有 `ALLOW/DENY/ASK` 三态，缺口不是策略枚举，而是 ASK 没有成为可挂起的运行时状态：请求没有可靠的 request id，入口没有统一的 pending 事件，Query loop 不能等待 resolve 后恢复，超时和重复 resolve 也没有统一收口。`types/permissions.py` 目前只有 `PendingClassifierCheck` 占位模型，没有 pending record、resolver 或 resume API。[31]

| 项目 | 具体建议 |
|---|---|
| 请求对象 | `permission_request_id`、`session_id`、`turn_id`、工具名、脱敏参数摘要、风险等级、过期时间和可选的修改后输入；不得把原始 secret 或完整 API key 放进事件 |
| 后端流程 | ToolRegistry 调用 gate；ASK 时写入 pending store、发布 `permission_pending`、暂停当前 turn；resolve API 按 request id 原子写入 decision；query loop 恢复、拒绝或超时结束 |
| 入口行为 | 桌面端提供确认/拒绝；remote API 提供查询和 resolve；iLink 支持带 request id 的明确命令；File Helper 不承担审批交互，只收最终结果 |
| 安全规则 | 单个 request 只能 resolve 一次；默认超时拒绝；session 停止或重启后 pending 状态可查询且不会重复执行；resolve 必须经过认证和 session 校验 |
| 审计 | permission pending、resolved、tool started、tool result 和拒绝原因写入后端审计事件，前端 ActivityLog 只展示其投影 |
| 完成标准 | Write/Bash、Screenshot、SendToWeChat 等有副作用的工具能在桌面与 iLink 被确认、拒绝或超时；拒绝后会话继续可用；并发 session 的 pending request 不串线 |
| 预期收益 | 这是从“本机可运行 Agent”走向“可远程安全使用 Agent”的底座，也是 Claude `canUseTool` 设计的关键落地 |

**涉及文件：** `python/permissions/gate.py`、`python/permissions/filesystem.py`、`python/types/permissions.py`、`python/tools/tool_registry.py`、`python/engine/query_loop.py`、`python/engine/query_engine.py`、`python/msgtypes/events.py`、`python/server/app.py`、`python/channels/ilink/service.py`；前端为 `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts` 和新增确认组件。

### P0-4：冻结工具能力矩阵、默认禁用策略与 contract tests

工具目录目前明确区分可执行工具和 scaffold 工具，但这条边界需要作为长期契约冻结。默认 registry 不注册 `SCAFFOLD_TOOLS`，`test_catalog.py` 已对该策略做回归；如果未来为了展示 Claude 风格工具而把 schema 直接注册到默认目录，模型就可能得到一个表面可用、实际只返回 `not_implemented` 的能力。P0 的目标不是一次性实现所有工具，而是让“可见能力 = 可执行能力”成为可验证规则。[22] [23]

| 项目 | 具体建议 |
|---|---|
| 真实可用矩阵 | 明确记录并持续测试 Echo、GetTime、Screenshot、SendToWeChat、Bash、Read/Write/Edit、Glob/Grep、TodoWrite、MemoryWrite/Forget/Search 的输入 schema、权限、取消、并发安全和副作用边界 |
| scaffold 矩阵 | 将 TaskCreate/Get/List/Output/Stop/Update、AskUserQuestion、Enter/ExitPlanMode、MCP resource、LSP、WebFetch/WebSearch、Agent、Skill、Notebook、SendMessage 等标记为未实现；`task_creat_tool.py` 空文件和其他 `not_implemented` 返回不得进入默认 registry |
| registry 契约 | `ENABLED_TOOLS`、`SCAFFOLD_TOOLS`、`DEFAULT_TOOLS` 只允许通过显式变更进入默认目录；每个启用工具必须有 execute contract、错误/取消/权限测试和能力说明 |
| 副作用审计 | Screenshot 会异步向远程发送图片，SendToWeChat 会发送文件，Bash/Write/Edit 有本地副作用；它们不能因为 schema 标为 read-only 就跳过 permission、event、audit 和失败可见性 |
| 模型可见性 | system prompt、catalog API、前端工具状态和实际 registry 必须来自同一能力矩阵；未实现工具应明确隐藏或返回机器可识别的 unsupported，而不是伪装成成功 |
| 完成标准 | contract test 能证明默认 registry 不含 scaffold；每个真实工具都有最小执行/错误/取消/权限边界测试；新增工具若没有完整契约则不能进入默认目录 |
| 预期收益 | 防止模型调用空壳工具、降低错误路径和安全副作用的不确定性，并为后续 MCP/LSP/Task 扩展建立可回归的工具边界 |

**涉及文件：** `python/tools/catalog.py`、`python/tools/stub.py`、`python/tools/tool_registry.py`、`python/tools/*`、`python/tests/test_catalog.py`、各真实工具测试；前端补能力展示/unsupported 状态测试，协议侧同步 `gui/src/lib/types.ts` 和 `api.ts`。

### P0-5：把 remote job 与 SessionTaskState 对齐，分别处理 iLink 与 File Helper

`FinalOnlyRunner`、`JobStore` 和 iLink 入站队列已经有可用基础：它们能按 session 串行执行，记录 `queued/running/done/error`，在 busy 时排队，并镜像部分 delta、tool 和 final。下一步不是重建远程执行，而是把它们接到引擎权威状态。

| 通道/层 | 保留现状 | 只补什么 | 明确不做什么 |
|---|---|---|---|
| `FinalOnlyRunner` | 继续负责远程一次执行和最终回复回调 | 创建 job 时绑定 `session_id + turn_id`；把 queued/running/done/error 映射到 SessionTaskState；传递 stopped、timeout、permission 等原因 | 不在 runner 内再做一套模型—工具主循环 |
| iLink | 保留 peer session 隔离、context token、长轮询、InboundQueue、事件游标和超时恢复 | 消费统一 envelope；增加 task status、permission confirm、stop/retry；按 cursor/idempotency 镜像 | 不推倒重写已有通道契约 |
| File Helper | 保留 final-only 和 intentionally thin 边界 | 统一 final/error/job 标识，确保投递失败可重试或可观测 | 不镜像所有 delta、tool call、tool result 和审批过程 |
| JobStore | 保留远程投递记录 | 增加 `turn_id`、状态版本、取消/失败原因和恢复查询 | 不把 JobStore 改成 SessionTaskState 权威 |

**完成标准：** `/v1/remote/jobs/{job_id}`、iLink `status_payload`、桌面端和统一事件流对同一 turn 给出一致的状态与原因；File Helper 仍只输出最终结果；同一 remote event 重放不会重复发送最终回复。

**涉及文件：** `python/channels/runner.py`、`python/channels/jobs.py`、`python/channels/ilink/service.py`、`python/channels/filehelper/service.py`、`python/channels/filehelper/bridge.py`、`python/server/session_pool.py` 以及统一事件和 API 类型文件。

### P0-6：让前端从“拼 transcript”升级为“消费事件投影”

前端主链路和核心投影已有稳定测试，不应把它描述成需要重写。当前真正的问题是 `chatStore` 同时承载 transcript、流式锁、工具活动、remote 镜像和 rollback 局部状态；`api.ts` 又混合解析 OpenAI delta 与 `xy` side-channel。应在不破坏现有 UI 和测试的前提下，让事件 reducer 成为唯一投影入口。[27] [28] [29] [34] [35]

| 项目 | 具体建议 |
|---|---|
| reducer 输入 | 只接受统一 envelope；按 `session_id`、`turn_id`、`event_id`/版本去重和排序；未知事件安全跳过 |
| 状态分层 | 明确分离 transcript、stream projection、SessionTaskState、permission pending、remote mirror 和 rollback state；不要求一次性拆成多个 store，但必须有清晰 reducer 边界 |
| 持久化 | 复用 `db.ts` 现有 IndexedDB 的 sessions/messages/kv/rollback 能力，增加 task snapshot、last event cursor 和 schema version；不新增第二套本地数据库 |
| 远程镜像 | `remoteStore` 保留 session gating、seenEventIds、seenToolIds 和 stream accumulation 的成熟逻辑，但改为消费统一 event id；切换 session 时禁止旧 stream 投影到当前对话 |
| 活动面板 | `ActivityLog` 继续展示工具活动和 diff，但把后端审计事件作为可选权威字段；不重新做一个“审计面板”来替代已有 UI |
| 回溯联动 | rollback、resend、stop 都更新同一 task state；preview/execute 的现有流程保留，补 commit 后 send 失败的明确状态 |
| 测试策略 | 保留 `groupTranscript` 的回合/工具配对测试、`toolActivity` 的文件/Todo/回合分段测试、`streamMarkdown` 的增量 fence/math 测试、`remoteStore` 的 session gating/stream 去重测试，并新增统一 envelope 的跨入口 contract tests。[34] [35] |
| 完成标准 | 重复、乱序、断线、刷新、切换 session、本地与 remote 同时运行时，UI 能按 event id/version 丢弃旧事件或请求 reset/replay；既有 store、投影和 settings/profile 测试继续通过 |
| 预期收益 | 消除幽灵 loading、孤儿 tool 行、重复 outbound 和远程镜像串 session，同时最大化复用当前前端实现 |

**涉及文件：** `gui/src/lib/api.ts`、`gui/src/lib/types.ts`、`gui/src/stores/chatStore.ts`、`gui/src/stores/remoteStore.ts`、`gui/src/lib/db.ts`、`gui/src/lib/groupTranscript.ts`、`gui/src/lib/toolActivity.ts`、`gui/src/lib/streamMarkdown.ts`、`gui/src/components/ActivityLog.tsx`、`gui/src/components/SessionTodoDock.tsx` 及现有 store/API/投影测试。

## 五、P1：状态统一后的治理、回溯与可观测性

P0 解决“谁是事实源、如何传输、能否暂停和恢复、哪些工具真的可用”。P1 解决“发生过什么、能否安全回溯、能否限制风险、发布产物是否可靠”。以下事项不能取代 P0，但应在 P0 接口冻结后并行推进。

| 优先级 | 工作项 | 为什么现在做 | 主要文件 | 范围 | 预期收益 |
|---|---|---|---|---|---|
| P1-1 | 后端审计与 ActivityLog 对齐 | `ActivityLog` 已有工具参数、输出和 diff 展示，但只是 transcript 投影；permission、tool、task transition、rollback 需要后端可查询记录；Screenshot/SendToWeChat 等真实外部副作用也需可追踪 | 新增 `python/audit/log.py`；修改 `tool_registry.py`、`gate.py`、`query_engine.py`、`runner.py`；前端补事件字段 | 后端为主，前端投影 | 可追责、可复盘、可诊断；能解释危险操作为何发生 |
| P1-2 | 回溯提交—本地截断—重发事务补偿 | `RollbackService` 后端事务骨架已成熟，但前端在后端 commit 后还要截断 transcript、重新发送；中间失败需要明确部分成功状态 | `python/rewind/service.py`、revision/snapshot/journal/context；`gui/src/stores/chatStore.ts`、`lib/api.ts` | 前后端 | 避免历史消息、工作区 revision 和 resend 状态不一致；支持重试或人工恢复 |
| P1-3 | rollback 统一事件与 task state | preview/execute/幂等/冲突已有后端能力，但还未完全进入通用事件序列和任务投影 | `rewind/*`、`python/server/app.py`、`gui/src/lib/api.ts`、`chatStore.ts` | 前后端 | 回溯可观察、可取消、可恢复，和普通 turn 使用同一状态语义 |
| P1-4 | 项目级 policy 与 workspace 安全边界 | 当前 gate、Bash policy、filesystem 权限已有基础，但危险 Bash、写文件、截图及外部副作用需要仓库级可审查策略；底层 `workspace_fs` 已阻断 `..` 逃逸，重点是统一 root authority。[37] | `python/permissions/gate.py`、`bash_policy.py`、`filesystem.py`、`server/workspace_fs.py`；新增 `.xeyo-policy.json` 和测试 | 后端为主 | 同一 Agent 在不同仓库使用不同安全策略，降低默认放行风险 |
| P1-5 | 收紧 CORS、remote 鉴权和 resolve API | 远程能力具备本机写盘和命令执行潜力，P0 增加审批 API 后攻击面更敏感；当前 remote token 主要是全局环境变量，缺 session/peer/role scope | `python/server/app.py`、`python/channels/auth.py`、remote API、前端请求头和配置 | 前后端 | 降低本地网页、局域网和远程控制面的误用风险 |
| P1-6 | 跨入口端到端测试与真实验收 | 单测已经覆盖不少基础能力，但协议统一后仍需验证长轮询、跨 session、刷新恢复、权限等待和断线重放；`wait_health.py` 只验证 HTTP 2xx，不能替代端到端验收 | Python engine/channel/server tests；CLI API/store tests；iLink 手测记录 | 前后端与通道 | 证明“连续可用”，而不是只证明单个函数可以运行 |
| P1-7 | 启动入口、构建产物和文档收口 | `start-xeyo.bat`、旧入口和 `xeyoq.bat` 已能启动本地环境，但存在 release/dev 两套路径和多个脚本；Tauri CSP 为 null、Windows 签名和后端资源打包仍未完成发布验收 | 根目录 bat、`README.md`、`gui/src-tauri/src/lib.rs`、Tauri/Vite 配置、CI 或发布说明 | 前后端/交付 | 降低新用户启动失败和开发环境误判，补齐桌面发布安全和可重复交付 |

**关于 usage、Settings、Sidebar、RemoteQrPanel 和现有前端测试的处理。** usage 的 vendor/local/mixed 双源策略应继续保留，不应再列为“从本机估算升级为厂商接口”的大项；后续只需确保 usage report 与 `session_id/turn_id` 或审计记录的关系明确。Settings/profile 已有迁移和多 profile 回归，Sidebar 与 RemoteQrPanel 已产品化，`chatStore`、`groupTranscript`、`toolActivity`、`streamMarkdown`、`remoteStore` 测试应作为重构的回归基线；新增的是统一事件契约测试，而不是推倒现有实现。[27] [28] [29] [34] [35] [38] [39]

## 六、P2/P3：memory/L5 以证据门禁推进，不作为 P0 空白

memory 方向已有相对完整的离线控制面：simulator 覆盖不变量、确定性、黄金轨迹、theta/r 探针、成本/质量分拆和 AB gate；`p2_full_campaign.py`、`memory_stack_eval.py`、`formula_live_ab.py` 能运行合成场景、真实 session JSONL replay、可选真实 provider A/B、命中率扫描、每日 ledger/C2 监控并回写 docs/12 表 D；`test_quality_plan.py` 还验证默认 `XEYO_L5=project`、C2 gate 默认关闭、题库和质量验收规则。[24] [25] [26]

这条路线仍未成为生产默认优化：`memory/simulator/__init__.py` 明确说明 simulator 不接 `query_loop`；`kv_cache_probe.py` 已通过真实 `QueryEngine` 主链路采集 prompt-cache hit/miss、usage 和成本，但只是脚本级在线探针，不是持续账本、运行时门禁或自动 shadow/AB；报告也明确 `verdict_ready=False`。因此，下一步是把评估证据与生产 runtime、事件、任务结果和回滚接起来，而不是直接打开 v6.1。

| 优先级 | 工作项 | 为什么现在做 | 主要文件 | 范围 | 预期收益 |
|---|---|---|---|---|---|
| P2-M1 | simulator/production projection parity 与运行时观测接线 | simulator 的 segment/token/cost 投影和 `engine/compact.py` 生产投影尚未由统一 parity contract 约束；在线探针也未进入持续账本 | `python/memory/simulator/projection.py`、`state_model.py`、`decision.py`、`python/engine/compact.py`、`working.py`、`scripts/kv_cache_probe.py`、usage ledger | 后端/评估 | 防止“仿真节省”与“线上送模内容”漂移，形成可审计的 hit/miss、token、cost 和 action 观测 |
| P2-M2 | 真实 session replay + provider-neutral shadow/AB gate | 现有 campaign 和 live A/B 已有成本、命中、质量代理和 gate，但 task_success、用户 correction、permission/abort/rewind、任务状态仍未完整关联，provider probe 也偏 DeepSeek | `scripts/memory_stack_eval.py`、`p2_full_campaign.py`、`formula_live_ab.py`、`memory/simulator/replay.py`、`report.py`、`tests/simulator/*`、`docs/12-压缩质量验证计划书.md` | 后端/评估，前端仅消费结果 | 在不改变默认生产策略的前提下获得可解释的 shadow 证据，并支持失败自动回滚 |
| P2-M3 | C2/L5 feature flag、回滚与长期监控闭环 | 当前 `XEYO_L5=project` 且 C2 gate 默认关闭，已有每日 ledger+C2 监控但还没有与统一 SessionTaskState、EngineEvent、真实发布门禁绑定 | `python/memory/l5_flag.py`、`memory_stack_eval.py`、`memory/working.py`、`msgtypes/events.py`、`engine/task_state.py`（新增）、usage ledger、docs/12 | 后端为主，前端展示指标 | 让 L5 从实验配置变成可灰度、可观测、可回滚的生产策略，而不是一次性全量开启 |
| P3-M1 | provider-specific cache contract、overlay 版本与质量校准 | `cache_model.py` 的 DeepSeek profile 较真实，OpenAI profile 仍是未来 stub；参数 overlay、theta/r 校准和质量模型已存在但不是线上自适应闭环 | `memory/simulator/cache_model.py`、`params.py`、`calibration.py`、`quality_model.py`、`metrics.py`、`report.py` | 后端/评估 | 为多厂商缓存与参数演进建立可复现、可审计、不会污染生产公式的校准边界 |

**memory 的阶段出口：** 只有当真实 replay 的任务结果、用户修正、权限/中断/回溯事件、usage/cost 和 compression action 能按 `session_id + turn_id` 对齐，且 shadow/AB 通过既定 gate 并具备回滚路径时，才考虑扩大 feature flag；在此之前，保持 `project` 默认模式和 C2 gate 关闭。

## 七、P2：Java ToolRuntime 的正确实施方式

Java 当前不是“已有接缝等待接入”，而是**前基础设施阶段**。`pom.xml` 只有 Java 21 编译插件；`JsonRpcServer.java`、`RpcRequest.java`、`RpcResponse.java`、`ToolRequest.java`、`ToolResult.java`、`ToolRuntimeServer.java` 和 `ToolRegistry.java` 尚未形成可执行 RPC、schema、测试和打包链路。[18] [19] [20] [21]

Claude 的 Java 方向应被保留为工具后端替换层：Python 继续负责 QueryEngine、上下文、权限和任务生命周期，Java 只负责工具执行和资源隔离。建议严格按下表推进。

| 阶段 | 只实现什么 | 不实现什么 | 通过标准 |
|---|---|---|---|
| P2-J1 协议 | 定义单一 request/result/error/cancel/ready schema，明确 stdout JSONL、stderr 日志和退出码 | 不维护 Python/Java 两份不兼容 schema；不让 Java 做模型循环 | Python 能启动 Java 子进程并完成 health check |
| P2-J2 工具 | 先实现一个低风险 Read 或 Glob 工具 | 不一开始迁移 Bash、Write、Screenshot 或全部工具 | 相同输入产生结构化结果和错误 |
| P2-J3 接入 | 在 Python ToolRegistry 增加可配置 Java adapter | 不修改 QueryEngine turn 循环和上下文模型 | QueryEngine 不知道工具由哪种后端执行 |
| P2-J4 取消与权限 | 透传 request id、cancel、timeout 和权限上下文；权限仍由 Python gate 决定 | 不让 Java 自己决定是否允许工具 | 停止、拒绝和超时可正确收口 |
| P2-J5 可靠性 | 测试进程重启、坏 JSON、超时、半关闭 stdout 和版本不兼容 | 不急于做多租户、Kubernetes 或插件市场 | Java 崩溃不会让 QueryEngine 永久 busy |

## 八、P3：微信深化、MCP、LSP、多 Agent 与更多工具

iLink 应继续作为“入口适配器 + 事件镜像 + peer 队列”维护。它已有较完整的基础契约，正确的增量是消费 P0 统一事件、支持 permission confirm/task status/stop/retry，并保持按 peer/session 隔离。File Helper 不应被拉入同一复杂度，它仍然只输出最终结果。

| 能力 | 当前真实状态 | 建议顺序 |
|---|---|---|
| iLink | 已有 peer session、context token、长轮询、队列、事件游标、超时恢复和测试 | P0 事件统一后补审批、任务状态、停止、重试和断线恢复 |
| File Helper | intentionally thin final-only | 只补最终结果/错误/投递可靠性，不做完整工具生命周期镜像 |
| MCP | 工具目录有接缝或空壳，但不是当前稳定性阻塞项 | P0/P1 稳定、能力矩阵和权限契约冻结后，先接入一个真实 MCP，并复用 Tool 契约和权限门禁 |
| LSP | 当前为 schema/空壳接缝，不是当前运行稳定性阻塞项 | 等工具协议、任务状态和 workspace 作用域稳定后再做 |
| 多 Agent | `AgentTool`、`SendMessage`、Task 工具目前未实现，缺完整父子任务、取消传播和资源预算语义 | 先完成 SessionTaskState、parent/child、预算和隔离，再考虑 |
| 更多脚手架工具 | 目前主要是 schema + `not_implemented`，扩大目录会扩大权限、执行和测试面 | 暂停新增，除非真实用户任务和完整 contract test 证明收益 |

## 九、建议的实施顺序与阶段出口

| 阶段 | 实施顺序 | 阶段出口 |
|---|---|---|
| 阶段 A：协议基线 | 统一 envelope 与事件类型 → QueryEngine 权威发布 → FastAPI/HTTP bridge/JSONL bridge 适配 → `api.ts` parser → iLink/remote adapter | 本地、remote、HTTP bridge、JSONL bridge、微信使用同一 `session_id + turn_id + event_id` 语义 |
| 阶段 B：会话状态与作用域 | SessionTaskState → SessionPool/QueryEngine 持有 → cwd/workspace 从全局变量改为 session context → Tauri workspace 注入验证 → Runner/JobStore 映射 → 前端和微信投影 | 两个并行 session 不串 cwd；Tauri dev/release 都能把用户 workspace 绑定到正确 session；刷新、排队、停止、异常和重启恢复都有可查询状态 |
| 阶段 C：权限回流与工具边界 | pending store → `permission_pending` → 桌面/iLink/remote resolve → resume/deny/timeout；冻结 ENABLED/SCAFFOLD registry 和工具 contract tests | Write/Bash 等 ASK 工具能确认、拒绝、超时；默认 registry 不会暴露空壳工具；拒绝后 session 不死 |
| 阶段 D：前端与通道验收 | reducer 化、IndexedDB task/cursor 持久化、断线 replay/reset、iLink 状态命令、File Helper final-only 回归 | 现有主链路、投影和 profile 测试继续通过；乱序、重复、刷新、跨 session 和远程镜像有契约测试 |
| 阶段 E：治理与回溯 | audit、policy、CORS/token、rollback 事件和事务补偿、Tauri CSP/签名/资源发布验收 | 试用过程中每个危险操作可解释、可限制、可恢复；桌面包可重复交付 |
| 阶段 F：memory evidence gate | projection parity → provider-neutral telemetry →真实 replay/shadow/AB → SessionTaskState/EngineEvent 对齐 → rollback gate；默认保持 project/C2 off | memory 结果能按 session/turn 与真实任务结果、usage、权限/回溯事件关联；只有 gate 通过才扩大 L5 |
| 阶段 G：平台扩展 | Java 最小 RPC → 一个真实 Java 工具 → MCP/LSP → 多 Agent | 扩展后不改变 QueryEngine、权限和统一状态协议 |

## 十、现在明确不应做什么

现在不应重新实现 compact，因为 C0/C1/C2、投影和压缩决策已经存在；应把工作改为契约收口和测试。也不应把 TodoStore 简单改名为 TaskState，因为任务生命周期、权限等待、远程 job、停止和恢复都超出了 Todo 文本范围；TodoStore 当前的精确边界是进程内、默认 key 为 `default` 的三态清单，未来才需要更细的 agent 隔离。[40] [41]

现在不应把 SessionPool busy/lease 当作大缺口，也不应重写已经有稳定测试的 chatStore 主链路、IndexedDB、Settings/profile、Sidebar、RemoteQrPanel、usage 双源策略、`groupTranscript`、`toolActivity`、`streamMarkdown`、`remoteStore` 或 iLink 基本通道。应在这些能力之上补统一事件和权威状态。

现在不应把 File Helper 改造成 iLink 的完整镜像；这会扩大通道复杂度而不增加其 final-only 产品价值。也不应在三套入口协议尚未统一、cwd 仍是模块级全局变量、Tauri workspace 注入关系未验证、ASK 尚不能恢复、默认工具能力矩阵未冻结之前，继续增加 MCP、LSP、多 Agent、更多工具或完整 Java runtime。

memory/L5 也不应被当作“已有算法就直接上线”：离线控制面和在线 probe 是证据资产，不是生产默认策略。没有真实任务质量、持续 ledger、统一事件关联、shadow/AB gate 和回滚路径时，保持 `XEYO_L5=project` 与 C2 gate 默认关闭。

## 十一、具体 PR 拆分

下表沿用现有 `PR-S1` 至 `PR-S7` 编号，并新增 memory 的独立证据 PR。建议每个 PR 都先写契约测试，再改实现，避免把既有稳定能力与新状态协议一起推倒。

| PR | 内容 | 主要文件 | 前端/后端范围 | 验收与收益 |
|---|---|---|---|---|
| PR-S1 | 统一事件 envelope 与三套入口适配 | `python/msgtypes/events.py`、`server/app.py`、`bridge/http.py`、`bridge/__main__.py`、`engine/query_engine.py`、`gui/src/lib/api.ts`、类型与事件测试 | 前后端 | 本地、HTTP bridge、JSONL bridge、remote 和 iLink 能关联同一 turn/event；旧 SSE 兼容，未知事件不破坏客户端 |
| PR-S2 | SessionTaskState 与 session/workspace/Tauri 作用域 | 新增 `python/engine/task_state.py`；修改 `query_engine.py`、`query_loop.py`、`session_pool.py`、`session/cwd.py`、`workspace_fs.py`、`permissions/filesystem.py`、`jobs.py`、`gui/src-tauri/src/lib.rs` | 前后端 | 两个 session 并行执行不串 cwd；Tauri 用户 workspace 不被 Python 根覆盖；queued/running/stopping/stopped/failed/succeeded 可查询、可恢复，Todo 不再是唯一事实源 |
| PR-S3 | Permission ASK pending/resolve/resume | `permissions/gate.py`、`filesystem.py`、`types/permissions.py`、`tools/tool_registry.py`、`engine/query_loop.py`、`engine/query_engine.py`、`server/app.py`、`gui/src/lib/api.ts`、`chatStore.ts`、iLink service | 前后端与微信 | 同一 request 只能处理一次；桌面和 iLink 可确认/拒绝；超时默认拒绝；拒绝后 session 继续可用 |
| PR-S4 | 工具能力矩阵、默认 registry 禁用策略和 contract tests | `python/tools/catalog.py`、`stub.py`、`tool_registry.py`、真实工具与 scaffold 工具、`python/tests/test_catalog.py`、前端 capability/unsupported 类型 | 后端为主，前端同步 | 默认 registry 永不暴露 scaffold；真实工具的 execute/错误/取消/权限边界可回归；模型不会把 schema 误当成可执行能力 |
| PR-S5 | 前端事件 reducer、远程投影和本地游标持久化 | `gui/src/lib/api.ts`、`lib/types.ts`、`stores/chatStore.ts`、`stores/remoteStore.ts`、`lib/db.ts`、`ActivityLog.tsx`、`SessionTodoDock.tsx` | 前端为主，依赖后端 S1/S2 | 保留现有发送、busy、工具行、rollback、投影和 remote 测试；新增去重、乱序、断线、刷新、切 session 测试；UI 不再猜测 task 状态 |
| PR-S6 | remote/iLink 对齐与 Todo 兼容写入 | `channels/runner.py`、`channels/jobs.py`、`channels/ilink/service.py`、`channels/filehelper/service.py`、`todo_write_tool.py`、前端 task/todo 投影 | 前后端与通道 | iLink 使用统一状态并支持 status/stop/permission；File Helper 仍 final-only；JobStore 映射 turn/job；Todo UI 不被破坏 |
| PR-S7 | rewind 事务补偿、审计、policy 与安全边界 | `rewind/service.py`、revision/snapshot/journal/context、`server/app.py`、`chatStore.ts`、新增 `audit/log.py` 与 policy 配置、CORS/auth 测试 | 前后端 | rollback commit、前端截断、resend 失败有可恢复状态；ActivityLog 可追溯后端事件；危险操作受项目策略和鉴权保护 |
| PR-S8 | memory projection parity、shadow/AB 和 evidence gate | `memory/simulator/*`、`engine/compact.py`、`memory/working.py`、`memory/l5_flag.py`、`scripts/memory_stack_eval.py`、`kv_cache_probe.py`、`formula_live_ab.py`、docs/12 与测试 | 后端/评估，前端只消费结果 | 默认 project/C2 off 不变；真实 replay、usage、任务结果、权限/回溯事件可按 session/turn 对齐；shadow/AB 通过后才允许扩大 L5 |
| PR-S9 | Java 最小 JSONL/RPC 真实链路 | `java/pom.xml`、`java/src/main/java/xeyo/rpc/*`、`java/src/main/java/xeyo/tools/*`、Python ToolRegistry adapter、Java/Python 集成测试 | 后端为主 | 一个 Read/Glob 工具经 Java 执行，支持 ready/result/error/cancel/timeout；QueryEngine 不变，Java 崩溃不会造成永久 busy |

## 十二、最终判断

XEYO 已经从 Demo 阶段进入“核心运行能力存在、跨层契约需要收口”的阶段。最值得继续投资的是**统一事件、统一会话任务状态、真正可恢复的权限审批、session/workspace 作用域、工具能力矩阵和基于事件的前端投影**。这些工作会同时提高本地桌面、remote API 和微信入口的可靠性，而不要求推倒已经存在的主循环、SessionPool、iLink、前端主链路测试、IndexedDB、设置/profile、Sidebar、RemoteQrPanel、usage 双源策略或 rewind 后端骨架。

memory/L5 应作为已有评估资产上的 P2/P3 evidence-gated 路线：先完成生产投影一致性、可审计观测、真实 replay、shadow/AB、任务质量关联和回滚门禁，再考虑扩大默认策略。Java、MCP、LSP、多 Agent 和更多脚手架工具都应服从同一顺序，不能绕过统一事件、SessionTaskState、权限回流和 workspace authority。

如果只能安排一个短周期，建议先完成 PR-S1 的事件 envelope 和三套入口适配，再完成 PR-S2 的 SessionTaskState/cwd/Tauri workspace 作用域，并同步完成 PR-S4 的默认工具 registry contract guard。只有这三个接缝稳定，Permission ASK、remote/iLink、前端 reducer、工具扩展和 rollback 审计才不会各自形成第四、第五套局部状态。

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
[10]: file:///D:/lea/claude/docs/tasks/00-overview.md "Claude 总体设计与阶段划分"
[11]: file:///D:/lea/claude/docs/tasks/01-single-session-main-loop.md "Claude 单会话主循环与 QueryEngine 设计"
[12]: file:///D:/lea/claude/docs/tasks/02-file-shell-tools.md "Claude 文件与 Shell 工具契约"
[13]: file:///D:/lea/claude/docs/tasks/03-context-and-permissions.md "Claude Context 与 PermissionGate 设计"
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
