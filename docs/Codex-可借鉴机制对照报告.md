# OpenAI Codex CLI 可借鉴机制对照报告

> 调研对象：`openai/codex` 仓库浅克隆（`D:\lea\XenYon code\.tmp\codex-src`，Rust，约 1.5M 行；调研后可整目录删除）。
> 对照目标：XEYO（`python/` engine + FastAPI，`gui/` React+Tauri，`cli-ts/` Ink TUI）。
> 方法：7 个并行子代理分簇精读 Rust 源码 + 人工综合。姊妹篇：`docs/DSH-可借鉴机制对照报告.md`。
> 格式：每节 **Codex 做法 → 对 XEYO 的建议（P0/P1/P2）**。注意标注【实验】：Codex 侧未稳定，只取概念勿照搬。

---

## 0. 总体判断

Codex 与 DSH 是两种工程气质：DSH 是「事件溯源 + 插件内核」的架构派，Codex 是「协议 + 沙箱 + 产品工程」的实战派。对 XEYO 最有价值的五块：

1. **协议成熟度**：tagged 事件信封 + 提交级 `id` + Begin/End/Delta 三件套 + 审批独立往返（server-initiated request）——直接升级 XEYO 的 xeyo SSE 信封。
2. **Windows 沙箱实答案**：不用 AppContainer，用 `CreateRestrictedToken`（WRITE_RESTRICTED）+ 每路径 capability SID + ACL + WFP 封网，两级后端（RestrictedToken 默认 / Elevated 提权）——与 DSH 的 windows-acl 蓝本互为印证且更完整。
3. **工具层三通道解耦**：模型可见输出 / 有损诊断日志 / token 预算覆盖分开建模；`ToolExposure` 与权限三态正交。
4. **上下文纪律的交叉印证**：Codex `AGENTS.md` 规定 model-visible context 必须增量构建、禁 history rewrite、总硬上限、单项 <10K、注入片段全部 struct 化——与 XEYO T_now 管线理念完全一致，可作为 T_now 的对外说辞与硬化依据。
5. **与 XEYO 惊人一致的自证**：Codex 同样**无 LLM 标题**（title=首条用户消息）、单 session 单任务、spawn 深度硬限报 "Solve the task yourself"——说明 XEYO 的几个「粗糙点」其实是主流取舍，不必焦虑。

与 DSH 报告合并后的优先级修正见 §15。

---

## 1. 核心循环与模型客户端（core/）

**Codex 做法**
- 主循环在 `session/turn.rs` + `tasks/`（顶层 codex.rs 已不存在）。**每 session 至多 1 个在跑任务**；新任务到来先 `abort_all_tasks(Replaced)`。`SessionTask` trait（kind/run/abort）把 Regular/Compact/Review/UserShell 显式建模为可取消后台任务（AbortOnDropHandle + CancellationToken + `done: Notify`）。
- `run_turn`：PreSampling 压缩 → `capture_step_context`（一次冻结工具表/环境/模型/settings）→ 注入 `ContextualUserFragment`（skill/plugin）→ **step 循环**（drain 排队输入=steer → 记录 world_state 变化 → 采样）→ `needs_follow_up = model_needs_follow_up || has_pending_input`，必要时 MidTurn 压缩后 continue。
- **并行/独占一把锁**：`ToolCallRuntime.parallel_execution: Arc<RwLock<()>>`；并行工具 `lock.read()`，非并行（exec/写类）`lock.write()`。比 DSH 的分类调度池更简单。
- **取消归一**：工具被取消 → 生成 `AbortedToolOutput`（"aborted by user after N s"）**作为普通工具输出回喂模型**，不中断整轮；中断后插入模型可见 `InterruptedTurnHistoryMarker`（归属明确的 Developer/User fragment）。100ms 优雅退出 + abort 兜底。
- **先落盘再执行**：模型每个 output item 完成即 `record_completed_response_item`，然后才派发工具——中断后已流出前缀必在历史。
- **三层重试**（responses_retry.rs）：①连接级无限指数（5s→60s，仅 ConnectionFailed）；②`is_retryable` 白名单 + 200ms·2ⁿ·jitter[0.9,1.1]（默认 5 次 cap 100）；③耗尽后**换传输通道**（WebSocket→HTTPS）并重置计数。
- 错误二分：`Fatal` → 整轮错误；其余 → `success:false` 工具输出回喂。compaction 触发预算化（`auto_compact_limit + fallback_buffer` / 窗口百分比，`BodyAfterPrefix` 只算前缀后增量）；token-budget 特性下**跳过摘要直接换新上下文窗口**仍走完整生命周期。
- 缓存纪律：Responses Lite 用 uuid_v5(thread_id, tools_json) 生成确定性前缀 id；`history.for_prompt` 纯增量。

**建议**
- P0：**RWLock 并行门控**——XEYO early-readonly 已有投机执行，加一把全局 RWLock（只读共享/写独占）即可获得安全并行，成本极低。
- P0：**取消归一为工具输出** + 中断标记（可走 T_now 一轮）：让模型知道"被用户中断了"，避免盲目重试。
- P1：三层重试骨架（白名单 + jitter 退避 + 连接级无限档 + 换通道）；XEYO 现在是单层。
- P1：工具调用先落盘再执行（XEYO 已 append tool_use 到 MessageStore，确认执行路径严格在后）。
- P2：`SessionTask` 化（任务/turn 分离）。

## 2. 持久化与压缩（rollout/ thread-store/ state/）

**Codex 做法**
- `~/.codex/sessions/rollout-<ts>-<thread_id>.jsonl`（冷文件 zstd 压缩）。每行 `RolloutLine{timestamp, ordinal, item}`，item 带类型标签（session_meta/response_item/compacted/turn_context/world_state/event_msg…）；首行必须 `session_meta`（含 git 信息）。
- **持久化白名单**（policy.rs）：瞬态事件（Delta/审批请求/Error/Warning）一律不落盘——历史干净。
- 追加：后台 writer + 有界通道(256) + 延迟建文件 + 保留未写尾部重试 + `ensure_rollout_is_newline_terminated` 半行修复 + 坏行 `parse_errors++` 继续。
- 索引：**SQLite 双写**（文件系统枚举优先、DB 对账/回退）、keyset 分页 `Anchor{ts,id}`、`threads` 表 + **`thread_goals` 表**（objective + status CHECK active/paused/blocked/usage_limited/budget_limited/complete + token/time 预算字段）。
- **CompactedItem checkpoint**：`{replacement_history, window_number, first/previous/window_id(UUIDv7 链)}`；resume 从最新存活 checkpoint 前向重放 suffix——与 XEYO C0/C1/C2 投影是同一思想的落盘版。
- **无 LLM 标题**（title=first_user_message）——与 XEYO 相同；意味着 DSH 的标题三态仍是 XEYO 可选增强而非必修。

**建议**
- P1：rollout 式事件白名单写进 `session/persistence.py`（现在全量写，Delta/信令事件会污染 transcript）；半行修复 + 坏行计数。
- P1：**thread_goals 表结构直接抄**——XEYO 要做 goal 机制（DSH 报告 §4）时，落盘形状可用此表（status 枚举更全：usage_limited/budget_limited 单列）。
- P2：SQLite 会话索引 + 文件系统回退 + keyset 分页（会话多时的列表/搜索）；冷会话 zstd 压缩。

## 3. 工具体系（tools/ core/src/tools/）

**Codex 做法**
- 三层：`ToolDefinition`（元数据+JsonSchema）→ `ResponsesApiTool/FreeformTool`（模型可见）→ `ToolExecutor`（运行时）。
- **`ToolOutput` trait 三通道**：`to_response_item`（模型可见）、`log_output`（刻意有损诊断，截断归 logger）、`fallback_token_limit_override`（每工具覆盖历史 token 上限）——输出精简不是一刀切。
- **错误二分**：`FunctionCallError::{RespondToModel, Fatal}`——可恢复错误走输出通道。
- **`ToolExposure`（Direct/Deferred/DirectModelOnly/DeferredModelOnly/CodeModeOnly/Hidden）**与权限正交：管理"模型可见面"而非"能否执行"；MCP 工具过多时自动降级 Deferred/Hidden。
- 第三方 schema 容错：sanitize + prune_unreachable + **5KB 字节预算分级降级**（删 description→删 defs→折叠深对象→删 composition），best-effort 不硬失败。
- 并行标记 `supports_parallel_tool_calls()` 默认 false（fail-closed）。

**建议**
- P0：`ToolMeta` 单表补两列：`exposure`（normal/hidden/deferred）与 `output_token_budget`（per-tool 覆盖）——为 MCP 接入和输出经济做准备。
- P1：错误二分进 `ToolRegistry.run`（`RespondToModel` 类错误回模型不拆会话；系统级错误才 turn error）。
- P1：schema 分级降级函数（MCP server schema 不可信时的地基，DSH 报告没有覆盖这层）。

## 4. 文件编辑：apply-patch 的容错（对 XEYO Edit/Write 直接有用）

**Codex 做法**
- 自有 patch 格式（`*** Begin/End Patch`），`ParseMode::Lenient` 剥 heredoc 包装；错误分整块/hunk 级。
- **seek_sequence 递减严格度匹配**：精确 → 忽略尾部空白 → 两侧 trim → **Unicode 标点归一化**（typographic dash/quote/空格→ASCII）；`context_line_indices` 成对记录上下文行防止误改；`is_end_of_file` 强制文件尾。
- **`AppliedPatchDelta.exact`**：失败时上报"已提交的副作用 + 是否精确"——写失败不再谎报。

**建议**：P1——把「递减严格度匹配 + exact 标志」移植进 XEYO Edit 工具（纯 Python 可实现）；对模型给错空白/标点时的成功率提升立竿见影。

## 5. MCP（rmcp-client/ mcp-server/）

**Codex 做法**：stdio 双 launcher（本地 spawn 用进程组(0)/Windows JobObject + `env_clear` + 受控 env + kill_on_drop + 2s 宽限）；单行上限 8MB；超时体系 startup 30s / tool 300s / 分页整体 30s，单次调用取 min 合并；命名 `mcp__server__tool` + sanitize + ≤128 字节冲突哈希（与 DSH 一致）；完整 OAuth（issuer 发现/refresh lock/store pinning）。

**建议**：与 DSH 报告 §11 合并执行——进程容器/受控 env/分级超时取 Codex 版（更工程化），generation 回滚/重连预算取 DSH 版（更完整）。

## 6. skills（codex-rs/skills/）

有序 roots + 快照缓存 + per-root `SkillError`（坏根跳过不挂）；frontmatter 行向修复（description 含冒号等不规范 YAML 先修复再报错）；**按显式提及（`# Skill` 标题/工具 mention）按需注入正文**，catalog 只存轻量元数据；`SkillPolicy{allow_implicit_invocation, products}`。与 DSH skill 体系（§11）互为补充：DSH 多了 digest 驱动 catalog replacement 与 invocation 四象限，Codex 多了提及选择与隐式触发开关。

## 7. code-mode（4 crate）【Codex 特有，XEYO 暂无对应】

V8(deno_core) 单 isolate；**删除 console/Atomics/SharedArrayBuffer/WebAssembly**，白名单注入 `tools/ALL_TOOLS/text/store/notify/yield_control/exit`；可选 `--jitless`；嵌套工具标 `ToolCallSource::CodeMode{cell_id}`、`wait` 续跑 cell；首行 pragma `// @exec:{yield_time_ms, max_output_tokens}` 控制预算。**建议**：P2 留档——XEYO 未来若做脚本编排，白名单 + pragma 预算 + cell 续跑是安全模板；明确"vm 非安全边界，视同 bash 权限"。

## 8. Windows 沙箱（windows-sandbox-rs/，2 万行——本次调研最重的一份）

**Codex 做法（不用 AppContainer）**
- `SandboxPolicy`：read-only / workspace-write / danger-full-access / external-sandbox；**`WritableRoot{root, read_only_subpaths, protected_metadata_names}`**——可写根下保留只读子路径与受保护元数据名（`.git`、`.git/hooks`、`.codex`、`.agents`…），防"改 .git/hooks 提权"。
- 两级后端：**RestrictedToken（默认非提权）**：`CreateRestrictedToken`，flags `DISABLE_MAX_PRIVILEGE|LUA_TOKEN|WRITE_RESTRICTED`；restricting SID 顺序固定 capabilities→logon→world；**WRITE_RESTRICTED 只约束写，全盘可读**——真正只读需 Elevated 后端（请求读受限时拒跑："refusing to run unsandboxed"，fail-closed）。
- **capability SID**：每 workspace CWD / 每 writable root 各一个随机 SID 持久化 `$CODEX_HOME/cap_sid`（canonical 路径归一）；token 只带当前允许根的 capability；**default DACL 主动排除路由/身份 SID**（"拿到代理身份≠拿到对象访问权"）。
- **Elevated 后端**：一次性提权 provisioning（版本化 setup marker + singleflight）建专用账户 `CodexSandboxOffline/Online`、隐藏用户敏感目录（.ssh/.aws/.gnupg…）、私有桌面、**WFP 封网**（按沙箱账户 SID 的 ALE_USER_ID 条件 BLOCK，仅放行 loopback 代理端口）；deny-read ACE 才可能。
- 临时目录显式建模：`TEMP/TMP` env roots 并入 writable roots，可排除。
- Linux：bwrap（`--ro-bind / /` 全盘只读 + 逐层放开 writable root + ro-bind 重放只读子路径，**挂载顺序是关键**）+ seccomp（deny connect/bind/listen，放行 AF_UNIX socketpair，deny ptrace/io_uring）；权限 profile 整体序列化成 JSON 传给 helper。macOS Seatbelt，拒绝含 symlink 的 writable root。

**建议**
- P1：**路径分类升级**：`permissions/filesystem.py` 增加「可写根内的只读子路径 + 受保护元数据名」（.git/.xeyo/.agents）——纯 Python，立即防提权，无需任何 OS 沙箱。
- P1：与 DSH windows-acl 蓝本合并立项：DSH 版（确定性 workspace SID + standing ACE + 每会话 temp SID）与 Codex 版（restricted token + capability SID + WFP）是同一问题的两个成熟答案；Codex 版多了网络封网与两级后端，DSH 版更轻。按 XEYO 需求选型，共同不变量是 fail-closed（拒跑优于裸跑）。
- P2：WFP 网络封网 + loopback 代理端口放行（配合 §10 network-proxy）。

## 9. execpolicy 与 escalation

**Codex 做法**
- 规则用 **Starlark DSL**：`prefix_rule(pattern, decision, match/not_match, justification)`、`network_rule(host, protocol, decision)`、`host_executable(name, paths)`；`match` 示例**解析期验证**（fail-fast）；匹配按 program basename 索引 + prefix token（支持 Alts）；绝对路径走 `host_executable` 白名单；**聚合判定取最严**（Allow<Prompt<Forbidden 的 max）。
- **escalation**（Unix）：打补丁的 shell 拦截 exec()，子进程经继承 socket 发 `EscalateRequest`；`EscalationDecision = Run / Escalate(Unsandboxed|TurnDefault|Permissions) / Deny{reason}`；每次决策可审计。本质是"per-command 提权 = 换 permissions profile 重跑"。

**建议**
- P0：**XEYO bash allowlist 升级为前缀规则引擎**：basename 索引 + prefix pattern（支持 Alternatives）+ `match/not_match` 加载期自校验 + 最严胜出——比现在的函数式 allowlist 更可配置、可审计。
- P1：escalation 状态机（Prompt→批准→按更宽权限重跑同一命令 + Deny 带 reason + 审计）正是 XEYO `outbound_ask`→`always_allow` 与"一次 escalation 重试"（DSH 语义）的落地形状。

## 10. network-proxy（1.7 万行）

**Codex 做法**：沙箱进程出站走本地代理；域名权限 `None<Allow<Deny`（**deny 覆盖 allow**）；每请求 `NetworkDecision{Allow|Deny{reason, source, decision: Deny|Ask}}` 且**全部审计**；MITM CA trust bundle 追加为 readable root；Windows 用 WFP 把封网限定到沙箱账户、仅放行代理端口。

**建议**：P2——XEYO 的 `outbound_ask` 目前管工具层，不管网；若要管网络（WebFetch 域名白名单），"deny 覆盖 allow + 每决策审计 + 代理集中出站"是现成蓝图。

## 11. 事件协议与 GUI（protocol/ app-server*/ tui/）

**Codex 做法**
- `Event{id, msg}`：`id` 是提交关联键，把同轮流式片段/工具/审批/usage 绑到同一提交；`EventMsg` tagged union ~90 变体；**Begin/End/Delta 三件套**（ExecCommandBegin/OutputDelta/End、PatchApplyBegin/Updated/End…）让前端有 item 边界与精确结束态；`RawResponseItem` 透传层保留上游原始 chunk；wire 别名（task_started/turn_started）做前后兼容。
- **app-server JSON-RPC 2.0**：方法 `<resource>/<method>`（thread/start、turn/steer、item/completed）；Thread/Turn/Item 三级抽象；**审批 = server-initiated request**（item/started → requestApproval → 客户端 `{decision}` → `serverRequest/resolved` → item/completed；turn 结束自动清理 pending）；连接无状态，断线重连 = re-initialize + `thread/resume` + **游标分页重建（非事件重放）**；30 分钟无订阅卸载；单写者（-32600）；过载 -32001。
- TUI 精华：审批弹窗=选项+快捷键+结构化 header（Thread/Environment/Reason/Permission rule + `$ cmd` 高亮）+ **MCP 式「Esc 恒=Cancel」契约**；状态行 `Working (0s • esc to interrupt)` + 可暂停计时器 + 宽度折叠；diff 主题感知背景色 + hunk 整块高亮保留语法状态；keybinding context→global→defaults + 强制唯一。

**建议**
- P0：**审批往返独立成协议**：XEYO 的 permission/ask 挂起已走独立路由（好），补「turn 结束自动 resolve pending + 决策审计事件 + Esc/取消恒=cancel 不=continue」契约。
- P1：信封帧加**提交级 correlation id + Begin/End/Delta 三件套**：工具调用目前只有 progress/result，补 Begin（带参数摘要）与明确 End（含 exit/时长），GUI 工具卡与 usage 归因都受益。
- P1：断线重连改为「resume + 游标分页重建」（配合 DSH 报告 §12 的投影推拉）。
- P2：审批面板 UI 抄 Codex 的结构化 header + 快捷键 + 决策历史 cell（`✔ approved … this time`）；diff 主题感知渲染。

## 12. config / features / hooks

**Codex 做法**
- config 分层 precedence 显式（Packaged -10 < Mdm 0 < System 10 < Enterprise 15 < User 20 < **profile 21** < Project .codex 25 < SessionFlags 30 < Legacy 40/50）；profile 打包 model/provider/approval/sandbox/tools/features，只覆盖声明键；**密钥默认 `env_key` 引用环境变量名不落盘**，必须内联的用 `RedactedString`（序列化打码）。
- features：`FeatureSpec{id, key, stage, default_enabled}` 集中注册表；Stage=UnderDevelopment/Experimental/Stable/Deprecated/Removed；Removed 保留解析为 no-op + 发 DeprecationNotice；默认值来自 spec 而非硬编码。
- hooks：事件点 PreToolUse/PermissionRequest/PostToolUse/Pre-PostCompact/SessionStart/End/UserPromptSubmit/SubagentStart/Stop/Interrupt；子进程执行、默认 600s（SessionEnd/Interrupt 默认 1s cap 3s）；结果三分 Success/FailedContinue/FailedAbort；**PermissionRequest fail-closed**；非托管 hook 需 trust。

**建议**
- P1：XEYO `config.toml` 引入 profile 概念（`[profiles.work]` 打包 model+permission_mode+output_compact 等）——切工作场景一键切换；密钥统一 `env_key` 引用。
- P1：把散落的 `XEYO_*` 环境开关收敛成 feature 注册表（key/stage/default/removed 兼容），消灭"文档和代码不一致"。
- P2：hook 系统按此模型设计（若企业场景需要）：PermissionRequest fail-closed + 短超时 + 三分结果。

## 13. 多代理 / 记忆 / 插件

**Codex 做法**
- 协作工具族 `collaboration.spawn_agent/send_input/wait/resume_agent/close_agent`；**根 thread 一个 AgentControl，全树共享 session_id**；`AgentGraphStore` 持久化父→子有向边（open/closed）**只恢复元数据不重开运行时**；深度硬限报 "Agent depth limit reached. Solve the task yourself."；**角色=配置层**（agents/*.toml：name/description/nickname_candidates/config_file 含 developer_instructions）；**fork 净化**：FullHistory/LastNTurns 模式，剔除多代理指令/usage-hint/时间提醒等易变块（与 XEYO「旁路不继承开关类块」红线同源）。
- memories 两阶段：Stage-1 按 thread 写 raw + rollout 摘要；Stage-2 后端汇总 memory_summary.md；注入按 token 上限截断、引用可溯源（citation→thread）、rate-limit 低于阈值跳过、7 天保留期剪枝、`disable_on_external_context`。
- 插件：`PluginManifest{name, version, paths{skills, mcp_servers, apps, hooks}, interface{...}}`；市场白名单；`plugins.<id>.enabled` 开关；坏插件保 prompt-safe description；**git_policy：插件 git 操作剥离仓库级 GIT_* env 并 stage 到可信临时仓库**（防供应链）。
- worktree：每 thread 独立 git worktree + `codex-thread.json` 原子记录属主 + KEEP_COUNT 回收。cloud-tasks【实验】：远端隔离执行 + apply 前冲突预检。

**建议**
- P1：**fork 净化清单**写进 XEYO 子代理路径（SUBAGENT_APPEND 已做，对照补齐：peer presence 块、budget notice、时间提醒不应进子代理上下文）。
- P1：角色文件（`agents/*.toml` 形状）给 XEYO 子代理工具加 persona/指令层——比硬编码 SUBAGENT_APPEND 更可配置。
- P1：记忆机制对照：XEYO memory 有 C0/C1/C2 + Memory index（T_now），Codex 的两阶段 + 引用溯源 + 保留期剪枝值得吸收进 `memory/`（尤其 citation 溯源与 rate-limit 门控）。
- P1：扩展层对照 DSH 报告 §11 一起做：manifest 形状两家几乎一致（skills/mcp/hooks/prompts），**git_policy 的「剥离 GIT_* env + 可信临时仓库」是 XEYO 插件防供应链的现成加强项**。
- P2：worktree 隔离（子代理并行改仓时）；AgentGraphStore 持久拓扑（多会话 presence 恢复）。

## 14. 认证 / 分发（大多无关，速览）

- login/ 的 ChatGPT 设备码、PKCE、refresh-token、Bedrock、Guardian review 全是 OpenAI 商业集成，**勿搬**。仅三点通用：AuthManager 单例 + auth 状态单一真相源（auth.json）+ env 解析 trim/非空。
- `codex-cli/bin/codex.js`：平台分发包 → 单入口 spawn 二进制 + 信号转发 + 退出码镜像（128+signum）——XEYO 桌面分发可参考。
- sdk/python 与 sdk/typescript：编程式 `thread_start → thread.run → TurnResult(final_response, items, token_usage)`——`python/cli` 对外 API 化的范式。

## 15. 三方对照速查（DSH × Codex × XEYO）

| 主题 | DSH | Codex | XEYO 现状 | 建议 |
|---|---|---|---|---|
| Goal | goal 域 + round driver（激活权不落盘） | `thread_goals` 表（status 含 usage/budget_limited）+ goal 扩展【实验】 | 无 | 按 DSH 状态机 + Codex 落盘表 |
| 压缩 | durable bracket + pruner + 前缀重放摘要 | CompactedItem checkpoint + window 链 + 无摘要 token-budget 档 | C0/C1/C2 投影（无 LLM 摘要） | C2 加 LLM 摘要（前缀重放式）+ checkpoint 落盘 |
| 工具输出 | retention 库 + spill+locator | ToolOutput 三通道 + per-tool token budget | 16k 硬截 | spill+locator（P0）+ per-tool budget 列 |
| 并行工具 | 分类调度池（默认 10） | 一把 RWLock 读/写 | early-readonly 投机 | RWLock（P0，最省） |
| 取消 | wake latch + interrupted anchor | AbortedToolOutput 回喂 + InterruptedTurnHistoryMarker | 异常/截断 | 取消归一为工具输出（P0） |
| 重试 | llm/retry 事件流 + 策略键 | 三层重试 + 换通道 | 单层 | 白名单+jitter+换通道（P1） |
| 沙箱(Windows) | ACL restricted token（确定性 workspace SID + standing ACE） | restricted token + capability SID + WFP + 两级后端 | 无 OS 级 | 立项二选一；共同先做受保护元数据名（P1 纯 Python） |
| exec 策略 | deny-only + escalation 单点 | Starlark 前缀规则 + 最严胜出 + EscalationDecision | 函数式 allowlist | 前缀规则引擎（P0） |
| 审批 | user-approval 四值 + intent | server-initiated request + decision + resolved 清理 | 挂起面板 + 180s TTL | 分级超时 + grant store + Esc=cancel 契约（P0） |
| 标题 | LLM 三态（fallback+增强+pin） | 无（title=首条消息） | 无 | P0 可选增强 |
| T_now | runtime-context 落史（相反哲学） | ContextualUserFragment 增量注入 + 硬上限 + struct 化 | T_now 管线 | 理念互证；补「注入片段 struct 化 + 硬上限」文档化 |
| MCP | generation 回滚 + 重连预算 | 进程容器 + env 白名单 + 分级超时 + schema 降级 | 壳 | 两家合并实现（P0/P1） |
| 标题/会话索引 | 投影缓存 + 水印 | SQLite 对账 + keyset 分页 | 文件枚举 | 会话多了再说（P2） |
| 插件 | cordis 生命周期 + broken-but-listed | manifest 市场化 + git_policy 供应链防护 | extension 层规则已定 | git_policy 剥离 GIT_*（P1 加强项） |

## 16. 合并后的建议路线（DSH + Codex 报告汇总）

- **P0（本周可做）**：spill+locator 与截断元数据（DSH §3）；RWLock 并行门控 + 取消归一（Codex §1）；审批分级超时 + Esc=cancel + intent 字段（DSH §5 + Codex §11）；崩溃尾修复 + 语义检查点（DSH §1）；LLM 标题三态（DSH §14）；bash 前缀规则引擎改造启动（Codex §9）。
- **P1（两周）**：compaction LLM 摘要（前缀重放）+ CompactedItem 式 checkpoint（DSH §2 + Codex §2）；goal 状态机（DSH 状态机 + Codex thread_goals 表）；grant store + permission preset；MCP client（DSH 生命周期 + Codex 容器/超时/schema 降级）；可写根内受保护元数据名（Codex §8）；event 信封 Begin/End/Delta + correlation id；fork 净化清单 + 子代理角色文件；config profile + feature 注册表；skill_loader 四件套 + digest 目录。
- **P2（选型后立项）**：Windows 沙箱（DSH ACL 蓝本 vs Codex restricted-token+capSID+WFP）；投影推拉 + 断线重连分页重建；network-proxy 域名白名单；worktree 隔离；code-mode 白名单模板；hook 系统。

### 附：调研范围与局限
- 克隆为 `--depth 1`（main 分支快照），无历史演进信息；tui/app-server 超大 crate 只做抽样精读；`docs/*.md` 为 stub，架构叙事取自 AGENTS.md、app-server/README.md 与源码注释。
- 明确不搬：ChatGPT 登录/PKCE/refresh、Guardian auto-review、analytics 埋点、cloud-tasks 远端执行、goal/approval-review 等【实验】扩展的完整实现。
- 调研副本位于 `.tmp/codex-src`（只读使用），确认不再需要后可整目录删除。
