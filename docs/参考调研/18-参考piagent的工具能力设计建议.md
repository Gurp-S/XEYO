# XEYO 工具能力设计与下一步演进建议

基于 XEYO 当前的代码状态以及对 piagent 架构设计（《14-参考Claude设计后的项目进度与下一步建议.md》及官方文档）的分析，XEYO 目前的工具系统已经具备了核心骨架，但在生命周期管理、任务隔离和权限交互上仍然处于基础阶段。

本文档梳理了当前工具矩阵的现状，对比了 piagent 的工具设计，并给出了按优先级可落地的后续设计建议。

## 1. piagent 的工具设计哲学

根据 piagent 官方文档，其工具设计的核心原则是**“极简内核 + 极致扩展”**：

* **默认只提供 4 个读写工具**：`read`、`write`、`edit`、`bash`。
* **可选 3 个只读辅助工具**：`grep`、`find`、`ls`。
* **总计 7 个内置工具**。

piagent 明确**不包含**内置的 MCP（Model Context Protocol）、子 Agent 调度、计划模式（Plan mode）、内置 Todo 列表或后台 Bash 运行。这些能力全部被推向了外部扩展（Extensions）、技能（Skills）和包管理体系。

## 2. 当前 XEYO 工具能力的真实状态

XEYO 现有的工具目录 (`tools/catalog.py`) 明确划分了两个矩阵：**真实可用工具 (ENABLED_TOOLS)** 和 **脚手架工具 (SCAFFOLD_TOOLS)**。

### 2.1 真实可用的核心工具
目前已实现并在默认 Registry 中启用的工具，数量和能力甚至**超过了 piagent 的默认配置**：
* **系统与文件 I/O**：`Bash`, `Read`, `Write`, `Edit`, `Glob`, `Grep` （对应 piagent 的 7 个内置工具）
* **记忆与持久化**：`MemoryWrite`, `MemoryUpdate`, `MemorySearch`, `MemoryForget`
* **外部交互与基础能力**：`Screenshot`, `SendToWeChat`, `Echo`, `GetTime`, `TodoWrite`

这些工具已经接入了主循环 (`query_loop`)，具备基础的执行、错误捕获、超时中止（通过 `AbortController`）以及静态的权限拦截（`can_use_tool`）。

### 2.2 仅有 Schema 的空壳工具 (Scaffold)
XEYO 源码中还包含大量看似高级的能力，但目前**并未实现**，它们只定义了 Schema 并在执行时返回 `not_implemented`，且被严格排除在默认执行环境之外：
* **多 Agent 与通信**：`Agent`, `SendMessage`
* **复杂任务管理**：`TaskCreate`, `TaskGet`, `TaskUpdate`, `TaskList`, `TaskStop`, `TaskOutput`, `EnterPlanMode`, `ExitPlanMode`
* **网络与扩展**：`WebFetch`, `WebSearch`, `ListMcpResources`, `ReadMcpResource`, `LSP`, `Skill`, `NotebookEdit`
* **用户交互**：`AskUserQuestion`

### 2.3 当前执行框架的局限性
XEYO 当前真正的瓶颈不在于“工具太少”，而在于**缺少支撑高级工具运行的基础设施**：
* **权限审批不可挂起**：`permissions/gate.py` 中的逻辑是同步的。如果遇到需要用户确认的危险操作，目前的实现是将 `ASK` 降级为 `DENY` 直接拒绝，而没有“挂起任务等待用户确认”的机制。
* **生命周期缺失**：`ToolRegistry.run` 仅仅是根据名字查找工具并直接 `await tool.execute(...)`。它没有请求 ID 追踪，没有运行时的任务上下文（Task State），也不会抛出供前端渲染的中间状态事件。
* **任务状态隔离不足**：目前的任务状态主要依赖于 `TodoWrite` 写入进程内的清单（`DEFAULT_TODO_KEY`），无法很好地按会话或 Agent 隔离状态。

## 3. 还需要设计哪些工具与基础设施？

为了达到企业级落地标准，XEYO 下一步的重点**绝不是盲目实现所有 Scaffold 工具**，而是优先建设支撑工具运行的“基础设施”，然后再有选择地扩展工具。

### 3.1 基础设施缺口（优先级 P0）

1. **可挂起与恢复的权限审批机制 (Permission ASK)**
   * **设计缺口**：必须在 `types/permissions.py` 中定义完整的审批请求模型（包含 `request_id`, `session_id`, `tool_name`, `expires_at` 等）。
   * **执行流改造**：`query_loop` 在遇到需要 `ASK` 的工具时，应发布 `permission_pending` 事件并**挂起当前 Turn**，而不是直接 DENY。系统需要提供 `resolve_permission` API 供前端或微信端确认/拒绝，确认后系统根据 `request_id` 恢复工具执行。
2. **统一的会话级任务状态 (SessionTaskState)**
   * **设计缺口**：当前依赖 `TodoStore` 和前端的 `chatStore` 拼凑状态。需要设计一个权威的 `SessionTaskState`。
   * **状态机**：明确区分 `queued`, `running`, `waiting_permission`, `stopping`, `stopped`, `succeeded`, `failed`。工具的启动、挂起、结束必须触发状态机流转，并向所有入口（FastAPI, iLink, HTTP bridge）广播状态事件。
3. **工作区与上下文的严格隔离**
   * **设计缺口**：工具执行时的 `cwd` 目前仍有依赖模块级全局变量的风险。必须确保工具执行的上下文（Context）与具体的 `session_id` 和工作区目录强绑定，防止多并发会话串线。

### 3.2 核心工具能力缺口（优先级 P1）

在基础设施稳固后，优先将以下 Scaffold 工具真正实现：

1. **联网能力 (`WebFetch` / `WebSearch`)**
   * **价值**：打破大模型知识截止时间的限制，是 Agent 解决实际问题的基础。
   * **设计**：需要接入无头浏览器或搜索 API，处理超时、反爬虫和内容提取，并将其纳入统一的工具生命周期中。
2. **用户提问交互 (`AskUserQuestion`)**
   * **价值**：允许 Agent 在信息不足时主动打断执行，向用户索要参数。
   * **设计**：类似于 Permission ASK，这也需要一个挂起和恢复的机制，而不是直接返回错误。
3. **MCP (Model Context Protocol) 资源接入**
   * **价值**：通过标准协议接入外部数据源和工具，而不是硬编码所有工具。
   * **设计**：实现 `ListMcpResources` 和 `ReadMcpResource`，让 Agent 能够动态发现和使用工作区或远程提供的 MCP 服务。

### 3.3 暂时不应照搬的复杂设计（优先级 P2/P3）

1. **多 Agent 调度 (`AgentTool`, `SendMessage`, 复杂 `Task*` 工具)**
   * 真正的多 Agent 涉及复杂的父子任务预算分配、上下文隔离和跨 Agent 通信。piagent 本身也明确排除了内置子 Agent，选择通过外部扩展实现。在单 Agent 的状态流转稳定前，不建议投入精力实现这些工具。
2. **Java ToolRuntime 与 RPC 拆分**
   * 当前的 Java 代码只是一个前期的基础设施壳。在 Python 端的任务状态、事件和权限机制未统一之前，过早拆分 Java RPC 会增加不必要的分布式调试成本。
3. **File Helper 的全量事件镜像**
   * File Helper 被设计为 intentionally thin 的 final-only 通道。不应为了追求架构上的“统一”，而让它镜像所有的工具调用和审批过程。

## 4. 总结与行动建议

XEYO 现有的可用工具数量（15个）已经远超 piagent 的默认配置（7个）。

如果您准备开始下一阶段的开发，建议**绝对不要先去实现 `WebFetch` 或 `AgentTool`**。

您的第一步应当是：
1. **定义统一的事件 Envelope**，确保 `query_loop` 能够发出包含身份标识的任务和权限事件。
2. **重构 `permissions/gate.py`**，实现真实的挂起（Pending）和恢复（Resume）闭环。
3. 将现有的前端和微信端接入这套新的状态机制中。

只有当现有的危险工具（如 `Bash` 或 `Write`）能够触发弹窗、等待您点击确认、然后再继续执行时，XEYO 才算具备了扩展更多复杂工具的安全底座。
