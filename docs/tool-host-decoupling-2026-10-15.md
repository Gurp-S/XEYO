# 第二阶段：产品工具宿主依赖解耦

本阶段在第一阶段的 `RuntimeServices` 基础上接入工具宿主能力。Git、Bash 后台任务、job 三工具和 XeyoUI 不再直接导入 `server`。GUI、TUI、CLI 的产品入口负责装配服务；旧注册表和会话池继续持有状态。

## 结构性根因与约束

此前工具在执行时自行查找 `server.workspace_git`、全局 JobRegistry 和全局 SessionPool。目录上属于引擎的工具实际依赖产品启动环境，测试只能修改全局单例，独立安装也无法证明 Git 和后台能力的边界。

本轮规则是：每个工具注册表显式接收 `ToolHostServices`；每次任务操作只取得一次注册表实例；子代理和批处理重新创建工具注册表时继续传递宿主能力。静态测试禁止 `tools/`、`engine/` 导入 server、CLI、FastAPI 和 uvicorn，安装检查还会主动阻断这些模块的加载。

| 模块 | 职责 |
| --- | --- |
| `tools/host_services.py` | 定义 Git、后台任务、会话忙状态协议，以及不可变的 `ToolHostServices` 配置 |
| `tools/tool_registry.py` | 创建时保存宿主能力，注册工具时显式注入；后注册和替换工具也适用 |
| `common/workspace_git.py` | 迁移现有 Git 只读算法，保留超时、输出、路径限制和异常类型 |
| `common/workspace_paths.py` | Git 与 HTTP 文件接口共享同一条工作区路径边界 |
| `server/workspace_git.py`、`server/workspace_fs.py` | 兼容再导出，现有 HTTP 调用路径保留 |
| `server/tool_services.py` | 取得现有 JobRegistry；为指定 SessionPool 提供忙状态查询 |
| `server/engine_services.py` | 组装引擎运行服务和工具宿主能力 |
| `engine/subagent_runner.py`、`engine/scheduler.py` | 把服务传到委派执行和子工具注册表，沿用现有工具白名单与权限规则 |

后台任务的缓冲区、增量游标、等待通知、取消、容量管理和完成投递仍由原 JobRegistry 实现，没有复制第二份状态。Bash 未配置宿主或宿主不可用时，继续走现有日志文件后台路径；Docker 后台路径保持原样。

任务服务通过一个显式注入的取得函数提供。每次操作开始时调用一次：操作之间能跟随产品注册表重置，已在等待中的一次输出读取仍使用原注册表及其游标。没有新增全局 service locator 或用于宿主服务的 ContextVar。

## 独立引擎与产品入口

```python
from xeyo import RuntimeServices, ToolHostServices, build_default_engine

# job_registry 实现 BackgroundJobs 协议；session_pool 实现 is_busy(session_id)。
host = ToolHostServices(jobs=lambda: job_registry, sessions=session_pool)
engine = build_default_engine(
    cwd=workspace,
    runtime_services=RuntimeServices(jobs=job_registry, tools=host),
)
```

如需替换 Git，可传 `ToolHostServices(git=git_reader, ...)`。缺省 Git 使用独立的本地只读实现。没有宿主任务服务时，任务列表为空，后台 Bash 保留日志回退；仅构建 `JobOutputTool()`、`BashTool()` 或 `build_default_registry()` 不再隐式接入服务端单例。直接嵌入这些工具的调用方需显式传 `host_services`。

GUI/TUI 使用的 HTTP SessionPool 将自己的忙状态服务注入工具；CLI 创建引擎时沿用产品装配工厂。Agent、Workflow 共用的运行时提供器及 Scheduler 将宿主能力继续传给子执行。不会因本轮注入增加子代理原本无权使用的工具。

本轮没有增加模型指令，没有改工具 schema、Git 格式化文案或任务结果格式。安装依赖与第一阶段保持一致；`xeyo` 新增公开导出 `ToolHostServices`。

## 旁路、A/B 与验收记录

以任务开始时的未提交工作区作为基线，先在隔离副本实施。原始基线、候选、校正测试桩后的控制组、逐项结果与合回前备份保存在被忽略的 `python/.tmp-tool-host-20261015/`。

- 26 个工具行为场景及完整工具 schema 配对一致：Git 各只读动作与路径拒绝；真实 Bash 后台启动、活进程收编和取消；增量输出、未知任务及跨会话拒绝；XeyoUI 的会话列表、忙状态和 GUI/TUI/CLI 入口结果。
- 另有 4 个引擎场景、每侧 5 次假模型请求配对一致，比较请求消息、工具表、事件、宿主任务快照和恢复事实。真实供应商调用为零。
- 临时路径、随机标识与观测时间做明确归一化；Git 提交日期及会话文件时间固定。没有删除业务结果字段来消除差异。
- 新增 12 项边界契约通过，覆盖实例隔离、一次操作中的游标归属、延迟注册、产品入口、子代理和 Scheduler 传递、空宿主回退及导入约束。

首轮原有套件两侧均为 194 通过、21 失败、3 个预期失败，失败项相同。其中 17 项来自旧假注册表缺少当前已使用的 `snapshot_list` 方法，2 项来自测试子进程调用到错误的 Python。补齐测试桩（不改断言），并在两侧固定子进程 Python 路径后，扩大后的控制组为 238 通过、2 失败、3 个预期失败；候选加上新增契约为 250 通过、同样 2 失败、3 个预期失败。

两项保留的原有失败：

1. `test_job_tools_with_fake_registry` 要求输出必须以状态行结尾，但现有 activity 事实位于其后。
2. `test_schema_budget_shortens_descriptions` 要求所有短描述小于 200 字符，当前 Compact 描述为 317 字符。

本轮未修改这两项断言或其产品行为。最终合回结果、GUI/TUI 类型检查、安装验证及文件哈希见 [机器可读记录](tool-host-decoupling-2026-10-15.json)。验证范围不包含全量界面交互、全部工具、真实供应商、真实 Docker 或安装器回归。

| 最终实际工作区验证 | 结果 |
| --- | --- |
| Python 定向套件（含新增契约） | 250 通过、2 个上述既有失败、3 个预期失败；无新增失败 |
| 最新完整快照补验 | CLI、宿主边界与 Agent 工具链路 31 项通过 |
| GUI 流协议定向测试 | 47 通过；类型检查最终通过 |
| TUI 回合与队列定向测试 | 14 通过；类型检查通过 |
| 最终 wheel 干净安装 | 核心隔离、Git、注入任务服务、CLI 命令入口和 HTTP/SSE 均通过 |

GUI 第一次类型检查发现共享工作区 `multiAgentBoundary.test.ts` 的不完整状态桩类型错误；期间该文件被并行工作更新，随后复查通过。本轮没有修改 GUI/TUI 源码。

独立安装验证在仓库外的新虚拟环境执行：主动阻止 server/CLI 加载，运行引擎、真实本地 Git 和显式任务服务；随后安装产品 extras，验证 `xeyo`、`python -m cli`、CLI 假模型聊天及 HTTP/SSE。第一阶段的打包 CI 会自动运行这些增强检查；本轮未执行远程 CI。

## 并行修改交接

合回前发现 `tools/tool_registry.py` 新增按 Agent 动作分类副作用，`tools/agent_tool/agent_tool.py` 新增 `reuse_attempt_id` 参数。以它们的最新内容为前像完成三方合并，并在写入前再次核对。没有重置、暂存或提交混合工作区。

合回后并行工作继续更新 CLI 的退出清理及部分 Agent/coord 生命周期模块。最终另取完整冻结快照构建 wheel，补验相关 31 项测试并重新执行干净安装检查。源码清单与 wheel 哈希写入验证记录；快照之后的其它对话改动不属于该产物的验证范围。

记录生成时，`server/routers/sessions.py` 又出现快照后的并行变动。该修改完整保留，未计入本轮 wheel 的安装验收；本轮 26 个实施文件在合回后没有检测到内容漂移。

继续处理 WSC/Agent 的对话需保留本轮接线：`ToolRegistry.host_services`、`SubagentRuntime.host_services`、`run_subagent(host_services=...)` 和 Scheduler 的传递参数。任务算法、权限白名单及已有并行修改仍归原模块；宿主适配器在新模块中维护。

后续可以继续处理工具生命周期与资源释放，以及内部包迁移到正式 `xeyo` 命名空间。本轮只建立宿主边界，尚未宣称整个产品所有间接依赖已经完全拆分。
