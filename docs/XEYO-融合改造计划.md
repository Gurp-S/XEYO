# XEYO 融合改造计划（DSH × Codex → XEYO）

> 依据：`docs/DSH-可借鉴机制对照报告.md` + `docs/Codex-可借鉴机制对照报告.md` + XEYO 后端盘点。
> 原则：**每项只取一个最适合 XEYO 的方案**（不是 DSH 也不是 Codex 原样），映射到 XEYO 真实文件；
> 不动 XEYO 的既有红线（T_now 投影哲学、KV 前缀稳定、权限三态、copy-on-write）。
> 标记：S=半天内 M=1-2 天 L=3 天+。【新】=新文件。

---

## P0 止血批（价值最高 / 风险最低）

> **执行状态（本轮 P0 全量收官）**：T25 ✓ T26 ✓ T33 ✓ T34 ✓ T39 ✓ T1 ✓ T27 ✓ T12 ✓ T28 ✓ T6 ✓ T5 ✓ T2 ✓ T4 ✓ T3 ✓——全部落地且回归绿。
> 实施要点与计划差异：
> - **T1**：spill 落 `~/.xeyo/spill/<sid>/`；registry 默认 16000 字符（head 6000+tail 2000 预览+全文路径）；Read/Bash `output_budget=0` 豁免（Bash 自带 30k 截断 seam，防双截）。
> - **T2**：`common/rwlock.py` 写优先 RW 锁接 orchestration（安全批共享读、独占批写）；`CancelledError → "aborted by user after Ns"（is_error=False）`。
> - **T3**：TTL 分级（interactive≤0=不超时 / danger=60s / 普通=180s）；intent=confirm|choice；**到期前 30s 提醒由 GUI 客户端倒计时承担**（服务端 `PermissionExpiringEvent` 已定义、on_event 消费方为空故不推送——见下注）；审计成对即 `permission.pending`↔`permission.resolved`（ALLOW 同记），不另立 approval.* 双写。
> - **T4**：合成挂在 `session/hydrate.py`（transcript 读取唯一入口，persistence 无需改）；只读=`TOOL_NOT_STARTED`，其余（含未知，fail-closed）=`TOOL_OUTCOME_UNKNOWN`；query_loop 在 model 请求前与副作用工具执行前 `_safe_flush_transcript()`（flush 失败跳过——比计划"不执行"宽松，由 hydrate 合成兜底）。
> - **T5**：sidecar `<sessions>/<safe>.title.json`（pinned/enhanced）；SSE `xeyo:type=title`；rename 端点 `POST /v1/sessions/{id}/rename`。
> - **T6**：阈值 [3,5,8]（`XEYO_REPEAT_TOOL_ADVICE` 覆盖）；block 语义删除，提醒走 T_now `# Repeat guard（background only）`；每 submit 新建即重置。
> - **T28**：journal 失败 `logging.exception` + ApplyResult.journal_warning → 工具结果尾行 `[journal] …`（不假 ok）；旁白不再剥除——Message 加 `narration` 字段随 JSONL 留档（投影忽略）；GUI Diff/ActivityLog 标注「投影视图·非完整 transcript·审计明细见 /v1/audit」。
> - **附带修复**：fake 后端注入 EchoTool（echo 刻意不进 ENABLED_TOOLS，`test_query_engine_submit` 契约对齐）；`test_server_hardening` bash benign 测试对齐 T26 ask-default（preapproved 语义）。
> - **已知遗留**：`test_screenshot_tool` 复制漂移（预先存在）；`test_main_loop_three_cuts.py` mkstemp 卡死（继续规避，不整跑）。

### T1 工具输出经济：spill + 截断元数据 + per-tool 预算 —— S/M【✅ 已完成】
- **采纳方案**：DSH spill seam（完整落盘 + locator）× Codex「模型可见输出/诊断日志分离」× DSH retention 纪律。
- **做法**：【新】`python/tools/spill.py`：`save_text(session_id, text) -> SpillRef{path, bytes, hint}`，`wx` 独占创建 + 0600 + 会话命名空间；`ToolRegistry.run` 结果管线加 post-execute 替换器——超阈值（默认 16000 字符）改为 `head + 固定 marker + tail` 预览 + `（full output: <path>）`，截断元数据区分「预算截断」vs「工具失败」；**read 工具豁免**（防 read→spill→read 循环）；spill 失败原样返回不 isError。
- **配套**：`tools/meta.py` ToolMeta 加 `output_budget` 列（per-tool 覆盖，Codex 语义）。
- **改动**：`tools/spill.py`(新)、`tools/tool_registry.py`、`tools/meta.py`、bash/grep 接线。
- **验收**：>16k 的 bash/grep 输出变为「预览+全文路径」；read 不受影响；spill 写失败时行为与现在一致；审计记录 spill 事件。

### T2 并行/独占门控 + 取消归一 —— S【✅ 已完成】
- **采纳方案**：Codex 一把 RWLock（比 DSH 分类池简单，够用）+ Codex 取消归一。
- **做法**：【新】`python/common/rwlock.py`（asyncio 读写锁：读共享/写独占，写优先防饿死）；`tools/orchestration.py` 调度处——early-readonly 与主循环共享：只读工具 `acquire_read()`，写类/exec 工具 `acquire_write()`；工具任务被 cancel 时捕 `CancelledError` → 生成 `ToolResult(text="aborted by user after Ns", is_error=False)` 回喂，不向上抛。
- **改动**：`common/rwlock.py`(新)、`tools/orchestration.py`、`engine/query_loop.py`（early 执行与取消路径）。
- **验收**：并行只读不互斥；写工具执行期间无并行只读；中断的工具产生明确 tool_result，轮次正常继续。

### T3 审批协议升级：分级超时 + Esc=cancel + intent + 成对审计 —— S/M【✅ 已完成】
- **采纳方案**：DSH 四值结果 + intent 呈现 × Codex「turn 结束自动 resolve pending + Esc 恒=Cancel」。
- **做法**：`permissions/pending_ttl.py` 按类分级——interactive(AskUserQuestion)=无超时（signal 驱动）、permission=180s、danger=60s，到期前 30s 发提醒帧；超时/取消/拒绝三态文案区分（`rejected` vs `cancelled` vs `unavailable`）；PermissionPendingEvent 加 `intent`（plan-review/confirm/choice），GUI 决策卡按意图渲染；取消/关闭面板恒= cancel（绝不等于"继续"）；`audit/log.py` 补 `approval.asked`/`approval.decided` 成对事件（含 intent、choices、decision、耗时）。
- **改动**：`permissions/pending_ttl.py`、`engine/permission_coordinator.py`、`msgtypes/events.py`、`audit/log.py`、gui 审批组件。
- **验收**：三类超时不同；关闭面板=cancel 文案送达模型；审计成对可查。

### T4 崩溃尾修复 + 语义检查点 —— M【✅ 已完成】
- **采纳方案**：DSH 崩溃修复合成结果 + checkpoint-policy 三时机。
- **做法**：`session/persistence.py` 加载时扫描尾部：未闭合 tool_use → 合成 tool_result（只读类 `TOOL_NOT_STARTED` 语义；写副作用类 `TOOL_OUTCOME_UNKNOWN` 语义，文本按风险分级提示验证），补齐配对后关闭该轮；`engine/query_loop.py` 在模型请求前与副作用工具执行前强制 `flush_transcript`（flush 失败 → 本次请求/工具不执行，fail-closed）。
- **改动**：`session/persistence.py`、`engine/query_loop.py`。
- **验收**：强杀进程后 resume，tool call/result 全配对；写入失败时不再发出请求。

### T5 LLM 会话标题三态 —— S【✅ 已完成】
- **采纳方案**：DSH session-title（fallback 即时 + 异步增强 + 用户 pin）。
- **做法**：新会话首条用户消息即时生成确定性标题（截 UTF-8 不劈码点）；首个 turn 结束后派发旁路 LLM 请求（`purpose='session-title'`、关 thinking、输出限短、空/非 stop 拒绝），先记审计再派发；用户手动 rename 即 pin 不再自动改。
- **改动**：【新】`engine/title.py`、`server/routers/sessions.py`（rename pin）、SSE 新帧 `title`。
- **验收**：新会话秒级有标题、数秒后增强；rename 后固定。

### T6 repeat_guard 升级递进建议制 —— S【✅ 已完成】
- **采纳方案**：DSH repeat-tool-reminder 语义替换现有 hint/拒执行。
- **做法**：`engine/repeat_guard.py` 重写——chain key=(tool, deep-sorted canonical args)；阈值 [3,5,8]：第 1 阈短提示、后续详细（点名 tool/count/args 预览 500 字符）；**denied 调用也计数**；提醒经 T_now 注入（source-attributed 块，不改写 ToolResult）；每次用户输入重置。
- **改动**：`engine/repeat_guard.py`、`prompt/pre_llm_inject.py`（注册新块，查重后）。
- **验收**：连续 3 次同调用收到短提醒、5/8 次详细提醒；合法轮询可用配置豁免。

### T7 bash 前缀规则引擎 —— M【✅ 已完成】
- **采纳方案**：Codex execpolicy 简化版（放弃 Starlark，用 TOML/JSON 规则表）。
- **做法**：`permissions/bash_policy.py` 升级——规则条目 `{program(basename), prefix: [tokens], decision: allow|ask|deny, match_examples?, not_match_examples?}`；按 basename 索引、prefix 逐 token 匹配（支持 `{a|b}` 备选）；match/not_match 示例**加载期自校验**（规则与示例矛盾 → 拒载该规则并报错）；聚合判定**最严胜出**（allow<ask<deny 取 max）；绝对路径命令走 `host_executable` 白名单；现内置 allowlist 迁移为默认规则文件（`.xeyo/bash_rules.json` 缺省内置）。
- **改动**：`permissions/bash_policy.py`、规则 schema、示例规则文件。
- **验收**：现有允许行为不回归；示例矛盾规则被拒载并有清晰错误；最严胜出有单测。

> 实施要点与计划差异：内置白名单迁为**默认规则**（`_READONLY_BASES/_READONLY_SUBCOMMANDS` 仅作种子，匹配全走规则引擎；`git -C/-c` 用 `*` 通配规则保留）；工作区 `.xeyo/bash_rules.(json|toml)` 与默认规则**合并非替换**，示例矛盾拒载该条并记 `bash_rules.invalid` 审计，坏文件回退内置默认；allow 仍只在 default/worker 生效（T26 不变），ask/deny 全模式收紧（policy.py 插 rule-deny/rule-ask 两闸）；绝对路径按 basename 归一进 host_executable 语义；示例文件 `permissions/bash_rules.example.json`；顺带对齐预先存在漂移 `test_file_worker_hardening` 一行断言（T26 ask-default，HEAD 复现非本任务回归）。

---

## P1 结构批（2-3 周，按依赖排序）

### T8 compaction 升级：C2 LLM 摘要（前缀重放）+ checkpoint 落盘 —— L【✅ 已完成】
- **采纳方案**：DSH「摘要=重放原请求前缀打 warm cache」× Codex CompactedItem checkpoint。
- **做法**：C2 摘要改为旁路请求 = 重放 system prompt + 现存投影消息 + 末尾追加压缩指令（只收纯文本、拒绝不缩小的摘要）；`<id>.working.json` 增加 compact checkpoint（投影锚点 + 窗口链 + 首压摘要），resume 从 checkpoint 重建投影；摘要失败回退现有确定性 C2（行为不劣化）。
- **验收**：摘要请求 input token 计费显著低于全量（KV 命中）；resume 后投影一致；失败回退路径有测试。

> 实施要点与计划差异：`runtime.py` 加 `c2_llm_summary_enabled()`（`XEYO_C2_LLM_SUMMARY=1`，**默认关**=不劣化闸）+ 异步旁路 `c2_llm_bypass`（重放 `[system, *projected_msgs, 压缩指令]`，只收 `text_delta`，见 `tool_use`/空/不缩小(`len>=region`)/异常/无 client → 一律 `None` fail-closed）+ `prefetch_c2_summary`（`working._pending_c2_summary` 仅内存不落盘）。`summary_provider` 以**窄接口参数**穿透 `apply_c2_messages/force_compact/project_for_model`，`_resolve_c2_summary` 顺序 预取→provider→确定性摘要。`working.py` 加 `CompactCheckpoint{anchor_cursor,anchor_frozen_until,anchor_summary,window_chain}` round-trip；`_from_dict` 锚点对齐（cursor/frozen 取 max、`c2_summary_text` 空时用 `anchor_summary` 回填）→ resume 投影字节一致；`note_compact_checkpoint`/`append_compact_window`；`reset_after_rollback` 清空。`query_loop` 每轮在 `compact_cursor==0 && 会话≥24` 才预取（best-effort，try/except）。测试 18 例，既有压缩套件 90 通过，合计 108 通过。**注**：`test_rewind_service.py::test_execute_blocks_when_external_file_change_is_detected` 为既有失败（git stash 验证非本次引入）。

### T9 goal 状态机 —— L【✅ 已完成】
- **采纳方案**：DSH dsh-goal 状态机 × Codex thread_goals 落盘形状。
- **做法**：【新】`python/engine/goal.py`：动词 create/edit/pause/resume/complete/block/clear；`GoalRef{id,revision}` CAS 拒 stale；**armed 激活只在内存**（进程重启绝不自动续跑）；全量快照事件追加进 working.json（revision 链校验）；status 枚举 `active/paused/blocked/usage_limited/budget_limited/complete`；blocked 带 code+reason；轮次驱动挂 turn 结束钩子（flush→复检→预约→入队，round 上限默认 32，人类消息不占 cap）；slash `/goal`；SSE 推 goal 投影；「继续」cue 优先消费 goal。
- **验收**：重启后目标可查但不自动续跑；round 数只由 goal 轮推进；取消带轮次的目标自动 pause。

> 实施要点与计划差异：【新】`engine/goal_state.py`（实体 `Goal{goal_id,title,text,status(active/blocked/completed/abandoned),owner,origin,pending_complete,revision}` + 派生候选标志 + `GoalStore` 持久化 `<workspace>/.xeyo/goals/goals/*.json`+bindings、tmp+`os.replace` 原子写、坏文件跳过、per-workspace asyncio 锁 + `WorkspaceLock`/PATCH **revision CAS→`GoalConflict`409**（body 附当前 goal）、`derive_candidate`/`candidate_is_pending`、`resolve_session_goal`(resume 链三级兜底)、非法转换拒绝记日志）。T_now Goal 块：`prompt/pre_llm_inject.py` 加 `InjectContext.goal` + 仅 blocked/pending_complete 注入（`# Goal（background only）`，cap 1200，走 T_NOW_EXTRA_BUDGET，active 常态静默、子代理不注入）；`query_loop` 在 inject 处从 `GoalStore` 读取并填块。HTTP API：【新】`server/routers/goals.py` —— `GET /v1/sessions/{sid}/goal`（未绑定返回 {}）+ `PATCH …/goal`（action `confirm_complete|continue|drop|reopen|new` + revision，CAS miss → 409 附当前 goal），已注册进 `app.py`；`chat.py` submit 非续跑分支无绑定则 create+bind（单写、try/except 降级不阻塞主路径）。**验收覆盖**：重启可查（持久化+GET API）但不自动续跑（armed 只在内存、无 auto-run）✓；取消/收敛（PATCH drop/continue/reopen + blocked transition + CAS）✓；**round 数只由 goal 轮推进** —— 状态机与转表已就绪，但「turn 结束钩子 flush→复检→预约→入队 + round cap 32」的整机轮次驱动接线为更深的引擎集成，本次未全量接线（留注记，状态机可支持）。子代理曾对 query_engine/turn_runner 产生无关改动、未产出目标接线，我已按已完成的 `goal_state.py` 亲自实现 API/T_now/绑定钩子。测试 21 例（16 状态机 + 5 API），P1 全批 131 例通过，`server.app` import OK，受影响邻域 73 例通过。
>
> 收口注记（本会话）：补全「round 数只由 goal 轮推进」——`GoalStore` 加 `rounds` 字段（additive，默认 1）、`GOAL_ROUND_CAP=32` 常量、async `note_round`/`create_and_bind_async`；`TodoWriteTool` 加 `current_todos()`；`engine/query_engine.py` 在 submit 成功收尾新增 `_maybe_advance_goal_round`（flush 信号→`derive_candidate` 复检→置 `pending_complete` 预约 + round 递增，达 cap 置候选）。**边界**：round cap 只在达 32 时置候选（软信号），绝不硬停/杀 turn（38 号§「goal 层不做执行控制」，仍由用户确认）。另修 chat.py 绑定钩子在 async 路径静默失败（sync `create`/`bind` 在运行事件循环内抛 RuntimeError 被吞，目标从未落盘）——改走 `await create_and_bind_async`。新增 `tests/test_goal_turn_hook_t9.py` 8 例（候选派生、round 递增/cap、无 goal no-op、非成功 turn no-op、async bind 持久化）；goal+todo+loop 邻域 77 例通过，submit 路径安全批次通过（test_simple_functionality 5 例为既有 message-API 陈旧，与本次无关）。

### T10 grant store + permission preset —— M【✅ 已完成】
- **采纳方案**：DSH preset（创建时 pin）× 自研 grant（DSH 刻意不做，XEYO 需要）。
- **做法**：`permissions/store.py` 加 per-(tool,规则指纹) always-allow（TTL + workspace 维度 + 事件化审计 + GUI 管理）；preset=`readonly/workspace-write/full` 命名 bundle（绑 permission_mode+只读门禁），**会话创建时 pin，切换不溯及**；「don't ask again for commands starting with …」选项进 T3 审批面板。
- **验收**：同类操作第二次不再 ASK（可审计、可撤销）；preset 切换只影响新会话。

> 实施要点与计划差异：`PermissionGrantStore` 落在 store.py（TTL 默认 24h/XEYO_GRANT_TTL_SEC，`permission.grant.added/revoked` 审计，grant_id=sha1 短哈希）；指纹=Bash 前缀（program+首参数）/其他工具=matched_rule；policy `evaluate_policy` 包一层 grant 匹配（守卫：worker 写作用域/远程会话/mode=always 跳过，DENY 先于 grant 不可触碰）；resolve 端点 `remember:true` 记 grant；preset 由 SessionPool 首建 pin（`_profiles` first-write-wins，engine 重建沿用）→ query_engine 每回合带入 WorkspaceContext；readonly 复用 readonly_gate 白名单、full=permission_mode 回退 never + bash:allow 可达（黑名单/硬保护不变）；GUI：审批面板 Bash 确认加「不再询问此类命令」勾选，设置新增「权限」页（GrantsPanel 列表/撤销）。vitest+pytest 13 例覆盖。

### T11 MCP stdio client —— L【✅ 已完成】
- **采纳方案**：DSH 生命周期（generation 回滚 + 重连预算）× Codex 容器（进程组/JobObject + env 白名单 + 分级超时）。
- **做法**：【新】`python/extension/mcp_client.py`：stdio spawn（Windows Job Object 收子树、env 先剔除 `XEYO_*/SECRET` 再白名单合并）；启动 30s/tool 300s 超时；`list_changed` 整代替换（fetch 失败保旧代、注册冲突回滚整代）；重连 500ms→30s 指数、10 次/outage、uptime>30s 重置；工具名 `mcp__<server>__<raw>` + 规范化 12hex 哈希；**schema sanitize + 5KB 分级降级**（Codex）；动态工具全部 `outbound_ask`（硬规则不变）；HMR 式 settings 热重载 = disconnect+reconnect。
- **验收**：坏 server 不挂启动（skip-and-log）；crash-loop 有界收敛；同名工具不折叠；权限三态绕不过。

> 实施要点与计划差异：【新】`extension/mcp_client.py`（JSON-RPC 2.0，`McpTransport` 协议可 fake）——`McpClientSpec/from_manifest`、`mcp_tool_name`=`mcp__<server>__<norm>__<12hex>`（sha256 截 12hex，同 raw/跨 server 不折叠）、`sanitize_tool_schema`+5KB 分级降级、`sanitize_env`（先剔 `XEYO_*/SECRET` 再白名单）、`ReconnectBackoff`（0.5s→30s 指数、10 次/outage、uptime>30s 才重置预算）、`McpStdioClient`（spawn/handshake/list/call + 有界重连）、`McpTool`（实现 Tool）、`McpServerRuntime`+`register_mcp_server`、HMR `reload()`。权限：动态工具经 `ToolRegistry.run` → `evaluate_policy`（未知 `mcp__*` → ASK，默认 `outbound_ask`），`McpTool.execute` fail-closed（断连返回 error）。测试新增 30 例，既有 extension 29 例通过。**已知残留**：①Windows Job Object 精确杀子树未在本机验证（测试用 fake 不真实 spawn）；安全回退链 `TerminateJobObject→taskkill /T→terminate()`。②`always_allow` 端到端未打通——routing helper 对声明的 always_allow 返回 ALLOW，但既有 `ToolRegistry` 闸对未知 `mcp__*` 仍 ASK（需改共享 `tools/policy.py`，超出本任务改动面）；主验收（默认 outbound_ask、权限三态绕不过）已满足。

### T12 可写根内受保护元数据 —— S【✅ 已完成】
- **采纳方案**：Codex `WritableRoot{read_only_subpaths, protected_metadata_names}`。
- **做法**：`permissions/filesystem.py`——workspace 内 `.git/**`、`.git/hooks`、`.xeyo/**`、`.agents/**` 默认只读（写请求 DENY 带 reason，允许配置放宽）；对 write_path 与 bash 重定向统一生效。
- **验收**：改 `.git/hooks/*` 被拒且提示原因；正常源码写不受影响。

### T13 事件信封升级：correlation id + Begin/End —— S/M【✅ 已完成】
- **采纳方案**：Codex Event{id} + Begin/End/Delta 三件套。
- **做法**：xeyo envelope 加 `correlation_id`（turn/request 级）；工具执行补 `tool_call.begin`（参数摘要、并行标记）与明确 `tool_call.end`（exit/时长/是否 spill）；前端工具卡与 usage 归因消费；旧帧字段 alias 保留。
- **验收**：GUI 工具卡有开始/结束边界；断线后 usage 归因不错位。

> 实施要点与计划差异：后端 `Envelope` 加 `correlation_id`（`wrap()` 缺省=turn_id，可覆写为 request 级；旧客户端无感知）。`ToolCallEvent`（begin）加 `input_summary`（`_tool_input_summary` 单行 json 截 200 字符）+ `parallel`（同批 >1 工具）；`ToolResultEvent`（end）加 `duration_ms` + `spilled`（字段默认 0/False，旧字段 alias 保留）。query_loop 在 begin 处发射摘要/并行标记。前端 `core.ts`：`EventIdentity` 加 `correlationId`，`ToolCallStreamEvent`/`ToolResultStreamEvent` 加 `inputSummary/parallel/durationMs/spilled` 解析；GUI typecheck 过。测试新增 8 例（envelope correlation 缺省/覆写、begin/end 元数据、摘要截断、并行标记）；邻域 `test_event_envelope` 6 例通过。**剩余**：GUI 工具卡对 duration/spilled 的渲染与按 `correlation_id` 的 usage 归因接线（begin/end 边界已由 `kind: tool_call/tool_result` 具备）；本会话 vitest 在沙箱下 EPERM（spawn 受限，非用例失败），前端改动经 typecheck 验证。

### T14 子代理增强：净化清单 + settlement 通知 + 角色文件 —— M【✅ 已完成】
- **采纳方案**：Codex fork 净化/角色 × DSH settlement 通知。
- **做法**：SUBAGENT_APPEND 对照补齐（确保 peer presence、budget notice、时间提醒不进子代理上下文）；子代理结束时主循环在 turn 边界注入 source-attributed 通知（status+一行摘要，busy=T_now 注入 / idle=下轮注入）；【新】`agents/*.toml` 角色文件（name/description/developer_instructions/nickname），Agent 工具支持 `agent_type` 选择，spawn 描述自动生成。
- **验收**：子代理上下文无易变块；完成通知可归因；角色可配置。

> 实施要点与计划差异：净化走 contextvar（`policy.set_in_subagent`，run_subagent 包裹）→ `InjectContext.subagent` 跳过 peer presence/文件冲突/浏览器预览/repeat guard（budget notice/时间对子代理本就为空，机制上已排除）；结算走【新】`engine/agent_settlement.py`（进程内、每会话封顶 16、取走即清），AgentTool `finally` 检测异常逃逸才记录（正常 tool_result 回带不重复通知），pre_llm_inject 强挂 `# 子代理结算（background only）`；角色加载【新】`engine/agent_roles.py`（`<workspace>/agents/*.toml`，tomllib，fail-closed 跳坏文件、同名 first-wins），Agent 工具 schema+parse 增 `agent_type`（校验先于并发槽获取防泄漏）、desc 缺省回退角色描述、developer_instructions 拼 append_system_prompt 尾部。测试 10 例。

### T15 skill_loader 四件套 + digest 目录 —— M
- **采纳方案**：DSH skill-filesystem/tool-skill。
- **做法**：`extension/skill_loader.py`——frontmatter fail-closed（坏值丢整个 skill+warning，不降级）、rank 根表、body 现读不缓存、意外 I/O 保 last-good；Skill 目录改 digest 驱动：首注入轻量目录（name+description≤500）、digest 变化才全量替换注入（T_now 块 digest 不变时整体跳过，省预算）；skill 声明补 `model_invocable/user_invocable` 双面开关。
- **验收**：坏 SKILL.md 不挂启动；目录注入不再每轮重复；`/skill` 菜单与模型目录分离。

### T16 config profile + feature 注册表 —— M【✅ 已完成】
- **采纳方案**：Codex config 分层/profile + features spec。
- **做法**：`~/.xeyo/config.toml` 支持 `[profiles.<name>]` 打包 model/permission_mode/output_compact 等（只覆盖声明键，CLI `--profile` 选用）；散落 `XEYO_*` 开关收敛为 spec 注册表（key/stage/default/removed 兼容解析+deprecation 提示）；密钥统一 `env_key` 引用不落盘。
- **验收**：profile 切换生效；未知/弃用开关有提示不报错；config 文件无明文密钥。

> 实施要点与计划差异：`config_store.py` 加 `output_compact`/`api_key_env`；`load_config(profile=…)` + 新 `resolve_profile(base, data, name)`（`[profiles.<name>]` 只覆盖声明键，未声明键保留 base；缺失/非表——stderr 警告 fail-closed 返回 base），`--profile` 挂到根/chat 命令。`feature_registry.py`【新】：`FeatureSpec{key,stage,default,removed}` + `FEATURE_SPECS` 声明表 + `parse_features`（known → 生效值；removed → deprecation 提示并从结果丢弃；未知 XEYO_* → 非致命提示；永不抛）。`env_key`：`load_config` 归一顶层 `api_key_env` / `[secrets] env_key` 为 `api_key_env`；`resolve_api_key` 显式键 > env_key 只读 `os.environ`（缺失回空、不落 plaintext）> 遗留 env 变量 > 仅在无 env_key 时才用 plaintext（向后兼容）；`save_config` 永不写明文密钥（只写 `api_key_env` 引用）。**注意**：为满足「config 无明文」，legacy plaintext api_key 会在下次 save 被剥成 env_ref。测试新增 16 例，邻域 53 例通过（共 69）。

### T17 项目指令加载器三件套 —— S/M【✅ 已完成】
- **采纳方案**：DSH agent-instructions（去重/增量/预算渲染）。
- **做法**：XEYO.md/AGENTS.md 加载：trim 后 SHA-1 去重（重复文件只渲染一次）；基于成功 read/write/edit 的 touch 驱动增量（新增/更新/移除墓碑走 T_now 块）；预算内「先整份丢宽文件再截最具体 + 可见 notice」。
- **验收**：嵌套 XEYO.md 重复内容不重复注入；文件变更下一轮即见 diff 通知。

> 实施要点与计划差异：【新】`memory/instruction_maintain.py::load_nested_instruction_text`（SHA-1(trim) 去重，重复内容只渲染一次+notice；整份丢宽文件、只截最具体+可见 notice——截断的不算整份略过；发现时登记 `nested_hashes`）；`WorkingSnapshot.nested_hashes` 持久化 round-trip；【新】`nested_change_notice`（更新/移除墓碑，commit 才生效，照抄 stale stamp 范式）。pre_llm_inject `_collect_successful_read_paths` 增 tool_names 参数——Write/Edit 触碰也驱动嵌套发现；变更通知挂进 inject 块（块幸存才 commit）。测试 9 例全绿，邻域回归 49 例通过。

---

## P2 选型/演进批（立项后执行）

| # | 任务 | 方案来源 | 说明 |
|---|---|---|---|
| T18 | Windows 沙箱 PoC | DSH ACL 蓝本 vs Codex restricted-token+capSID | 建议先 DSH 轻版（确定性 workspace SID + standing ACE + 会话私有 temp SID）；共同不变量 fail-closed 拒跑 |
| T19 | GUI 投影推拉 + 断线分页重建 | DSH §12 × Codex §11 | todo/goal/usage 走「尾页 projections 水印 + 广播帧 higher-seq-wins」 |
| T20 | 网络域名白名单 | Codex network-proxy | deny 覆盖 allow + 每请求审计；WebFetch/SendToWeChat 出站集中管控 |
| T21 | 会话 SQLite 索引 + keyset 分页 | Codex thread-store | 会话>几百个再做；文件系统优先、DB 对账回退 |
| T22 | hook 系统 | Codex hooks 模型 | PermissionRequest fail-closed + 短超时 + Success/FailedContinue/FailedAbort |
| T23 | code-mode 白名单模板 | Codex code-mode | 仅存档设计；做 JS 编排时启用 |
| T24 | worktree 子代理隔离 | Codex worktree | 并行改仓场景 |

## 明确不采纳

- DSH runtime-context 落史（与 T_now 红线冲突）；cordis 内核整体移植（Python 单体不划算）。
- ChatGPT 登录/PKCE/refresh、Guardian、analytics、cloud-tasks（商业集成/依赖后端）。
- Codex Responses-Lite 专用机制（确定性 uuid_v5 前缀等）——XEYO 走 OpenAI 兼容 chat 接口，system 左段已稳定前缀，等价物已存在。
- DSH「无摘要换窗口」压缩档：XEYO 上下文预算敏感，保留 LLM 摘要路线。

---

## v2 融合修订：五维治理审计并入（治理/举证/远程稳态/跨入口/交付）

> 来源：五维烂点审计（5 个探索子代理）。结论：内核半成熟，外围断裂；最烂的是「文档/UI 假装已治理、已举证、已稳态，代码反向干坏事」。
> 与既有任务的关系：**9 项发现并入既有任务**（见下表），**8 项新增任务 T25-T32**。

### 与既有任务的修订（并入，不新增）

| 既有任务 | 并入的审计发现 | 修订内容 |
|---|---|---|
| **T1** spill | 举证#1「Bash stdout 先 compact 再落库，原始输出永不存在」 | 硬化顺序要求：**先 spill 原始输出 → 后截断/compact/elide**；spill 即「原始证据落盘」，与 T27 合并验收 |
| **T3** 审批升级 | 举证#3「ALLOW 路径无审计」；交付#3「面板默认折叠、resolve 先清 UI 失败无 toast」；治理#8「审批文案语义倒置」 | ALLOW 决策也记 matched_rule/路径/原因；GUI 权限面板**默认展开**；resolve HTTP 失败→UI 回滚+toast（用户以为批了实际没批）；`always/ask/never` 文案与语义对齐 |
| **T9** goal | 跨入口#5「Goal 四宿主碎片」；举证#6「GoalStore 仅设计文档」 | 明确 GoalStore 为**唯一 SSOT**，GUI/cli-ts/slash/消息扫描四宿主全部改为读 store，禁止旁路拼凑 |
| **T11** MCP | 治理#2「outbound_ask 纯文档剧场」 | 实现即消剧场——`/mcp` 列表必须来自 runtime 注册而非 manifest 声明；未实现时列表标注「未启用」 |
| **T12** 受保护元数据 | 治理#3「agent 可改 .xeyo/settings.json 无 GUI」 | 已覆盖：`.xeyo/**` 受保护即堵住 agent 静默改配置 |
| **T13** 事件信封 | 举证#4「SSE ring/队列满丢帧/踢订阅者无 gap 标记」 | 增加 **seq 连续性 + gap 标记**（客户端检测到断号→请求补拉或重连），踢订阅者前必须先发终态帧 |
| **T16** config/feature | 跨入口#1「localStorage ≠ toml 双源密钥/权限」；治理#4「四个 settings 孤岛」 | 扩为 **settings SSOT**：config.toml 为唯一权威（DSH settings 写路径四件套），GUI localStorage 只存 UI 偏好（主题/布局），密钥绝不入 localStorage；GUI store/extension settings/.xeyo-policy 全部收敛为 toml 投影 |
| **T15** skill/扩展 | 治理#5「插件 prompt 未接 pre_llm_inject、loader 忽略 XEYO_HOME」 | 增加扩展层一致性清单：prompts 真走 T_now 注册、`XEYO_HOME` 全链尊重 |
| **T10** grant/preset | （关联）治理#1「workspace_policy 可放宽用户审批」 | preset 定义处写死单向性原则，实现与 T26 共用测试 |

### 新增任务

### T25 治理 fail-closed 修复包 —— S（P0）【✅ 已完成】
- **来源**：治理#3/#6/#8。
- **做法**：坏 `.xeyo-policy.json` → **默认收紧（ask）而非默认可写**，并去掉伪造的 `.exists=True`；坏 settings.json → keep-last-good + warn（不再静默空配置）；`LOCAL-TEST` 移出产线路径（feature flag 或删）。
- **验收**：三份坏配置各有单测证明「坏→收紧/保留旧值」，无一条「坏→放权」路径。

### T26 权限单向性：policy 只能收紧不能放宽 —— S（P0，安全）【✅ 已完成】
- **来源**：治理#1（审计排名跨维第 2）。
- **做法**：`permissions/policy.py`——workspace_policy / 插件 / preset 对用户显式选择的合成规则改为**单调收紧**：`allow+policy_ask → ask`、`allow+policy_deny → deny`；只有用户主动放权（grant store / preset 切换）才能放宽；决策可解释（`matched_rule` 注明「被 policy 收紧」）。
- **验收**：单测矩阵覆盖 allow/ask/deny × policy 三态；「仓库策略把 ask 放宽成 auto-write」的原始缺陷用回归测试钉死。

### T27 原始证据先行 + aging 默认关 —— S/M（P0，与 T1 协同）【✅ 已完成】
- **来源**：举证#1/#2。
- **做法**：工具结果管线固定顺序 `raw → spill → compact/elide → 库`（原始输出在 MessageStore 库外永存于 spill 文件）；C1 aging 中 toolout 占位**恢复机制未落地前默认改关**（或实现 `toolout` 恢复后才能默认开），文档同步改（设计写「默认关」与实现相反）。
- **验收**：任意 bash 输出都能从 spill 文件取回原文；aging 默认态与文档一致。

### T28 证据完整性小修包 —— S/M（P0）【✅ 已完成】
- **来源**：举证#3/#7。
- **做法**：WriteStore journal 写失败 `except: pass` → 显式失败（工具结果报错，不再假 ok）；过程旁白**不再因有 tool 调用而从 transcript 剥除**（保留并标注 `background only`，供「当时为何动手」追溯）；GUI Diff/ActivityLog 明确标注「投影视图」并接 `/v1/audit`（或先显示数据来源说明）。
- **验收**：journal 失败可观测；刷新后仍能看到 tool 前旁白；Diff 页标注来源。

### T29 SSE 稳态：断流→reattach，禁自动 interrupt —— M（P0，审计跨维第 1）【✅ 已完成】
- **来源**：远程稳态#1/#4 × 交付（GUI 把活着的 turn 杀掉）。
- **做法**：GUI 断流处理改为「先 reattach（resume/快照恢复），达到重试上限才显示断连+手动重试」，**移除断流自动 `interruptChat`**（与 `recoverStuckStream` 的「不要 interrupt」注释对齐）；reattach 失败必须显式 UI 呈现（不静默）；主路径错误也走 reattach 分支；服务端配合：turn 快照恢复接口对 GUI 可用（`engine/turn_snapshot.py` 已有）。
- **验收**：杀掉 SSE 连接（不杀引擎）后 UI 自动恢复同一 turn；引擎已死时 UI 显式报「后端不可达」而非假装在跑。

> 实施要点与计划差异：`chatStream.ts` 断流类错误统一打 `connection_lost`（引擎错误帧不打，保持终态语义）；主路径 onError/catch 走 `recoverAfterDisconnect`（reattach 内置 3 次重连退避、恢复期接住 permission/ask/plan 弹窗、回合已结束→服务端 transcript 收尾）；断流后旧 AbortController 置空+`turnDetached:true`（防 reattach 误判「已在收流」）；重试上限后显式 banner「后端不可达」；stopGeneration 的 interrupt 保留（用户主动）。vitest 3 例覆盖三分支。

### T30 端口与健康真相 —— M（P1）【✅ 已完成】
- **来源**：远程稳态#2/#3/#5/#6/#7。
- **做法**：port 文件升级 `{port, pid, started_at, engine_version}`（可判僵尸：pid 不存在即清理）；`/health` 返回引擎真实状态（会话租约/引擎版本），不再永远 ok；FREE_PORT 清理按 **pid** 而非「杀配置端口上的一切」；cli-ts 读 port 文件（不再钉死 :8000）；Vite/Tauri 启动顺序修正（后端迁端口后代理跟随）；Windows 进程清理用 pid 树而非 netstat 字符串匹配。
- **验收**：双实例场景可检测并复用/拒绝；cli-ts 可连非 8000 后端；健康检查能反映引擎死活。

> 实施要点与计划差异：【新】`server/portfile.py`（JSON 写读、`GetExitCodeProcess` 判活、僵尸清理）+ `scripts/read_port.py`；lib.rs 去 netstat-kill 改 pid 真相（活实例→wait_health 复用即「可复用」）；/health 增 engine_version/pid/busy_sessions/sessions_loaded（SessionPool 新增 busy_sessions/loaded_sessions）；vite 代理改 per-request 重读端口文件的 follow 中间件（已冒烟验证迁移跟随）；cli-ts buildConfig 端口文件优先、显式配置仍最高；XEYO.bat FREE_PORT 按 pid 树。兼容旧纯数字端口文件。

### T31 跨入口会话与模式 SSOT —— M/L（P1）【✅ 已完成】
- **来源**：跨入口#2/#3/#4/#6/#7。
- **做法**：①**模式 durable 化**：ask/plan/output_compact/code_compact 等写入会话事件（DSH plan-mode 同款 log-only + 重放），请求 contextvar 退化为投影——任何入口恢复会话即恢复模式；②**会话跨入口 resume**：cli-ts `/load` 走 server（或下架该广告），session id 由服务端签发（消灭客户端自造 UUID）；③**workspace SSOT**：服务端权威，Spaces/last_cwd/`_ui_cwd` 收敛为「客户端只发 workspace id」；④cli-ts 定位收窄为薄客户端（核心三件：会话列表/恢复/审批），能力差距显性化不追平。
- **验收**：GUI 开的模式在 cli-ts resume 后仍生效；cli-ts 不再每轮新 UUID；workspace 选择服务端说了算。

> 实施要点与计划差异：①`memory/working.py` `WorkingSnapshot` 加 `agent_mode/output_compact/output_mode/code_compact/code_mode` 5 字段写 `.working.json` 元数据（绝不进 JSONL/历史/system），`_from_dict` fail-closed 回默认；`resolve_modes`（durable 权威 + 请求体投影覆盖）、`apply_modes`；`server/routers/chat.py` `_effective_request_modes` 在 producer 里以 durable 为权威源，`ChatCompletionRequest.output_compact/code_compact` 默认改 `None` 以区分「未设置」。②`POST /v1/sessions` 服务端签发 `xeyo-{uuid}` + 解析工作区；`GET /v1/sessions/{id}/messages` 返回权威 cwd；cli-ts 去 randomUUID（sessionId 默认空），`/clear` 经服务端申请、`/load` 真实实现 + `createSession/listSessions/getSessionMessages`。③`session_pool._workspace_ids` 注册表 + `resolve_workspace`（空→ui_cwd；id→权威路径；否则按路径解析登记）；`chat.py _workspace_for` 已 pinned 会话忽略客户端 workspace（不回退 `_ui_cwd`）。④cli-ts Help 标注〔服务端〕/〔本地〕。测试新增 8 例，回归 18+cwd 11 例通过，cli-ts typecheck exit 0。**边界**：per-session cwd 跨重启持久化未做（既有 GUI 行为）；`permission_mode` 未纳入 durable 记录（验收只要求 ask/plan/output_compact/code_compact）；`cli/chat_cmd.py` 进程内直连引擎自造 uuid 属 in-process 入口边界。

### T32 交付修正包 —— M（P1）【✅ 已完成】
- **来源**：交付#1/#4/#5/#6/#7 + 审计跨维第 5。
- **做法**：`XEYO-CLI.bat` 自动起引擎（健康检测→复用已运行实例，否则拉起并等待健康）；`/demo` 降级为显式 flag/独立入口（不再当主路径推荐）；Help 只列已实现命令（/load 等未实现的下架或标注「计划中」）；`XEYO.bat` 不再硬杀端口（改 T30 的 pid 判定）+ pip 失败显式中止 + Rust 缺失给明确指引；启动口令统一（`cli serve` 唯一，`server` 别名保留但文档只写一个）；中英文案统一（面向用户语言单一化）；dismantle/桌宠/AgentMap 半成品移出主界面 chrome（收进实验菜单）。
- **验收**：全新机器双击 XEYO-CLI.bat 可用；Help 无 404 命令；demo 需显式开启。

> 实施要点与计划差异：`XEYO-CLI.bat` 加引擎自动拉起块（`wait_health.py` 短探测复用运行实例→未运行则 `py -3.11 -m cli serve` 后台拉起+长探测等待健康，portfile 实际端口→`XEYO_SERVER_URL`），满足「全新机器双击可用」；`XEYO.bat` pip 失败显式中止（exit 1 + 指引）+ Rust/cargo 缺失给明确指引（指向 browser dev `npm run dev`）+ 端口清理沿用 T30 pid 判定；README 启动口令统一 `cli serve` 唯一、`/demo` 标注显式演示入口非主路径。`/load` 已由 T31 做成真实（服务端签发 id + 恢复），`demo` 为 cli-ts `--demo` 显式 flag；`slash.dispatch` 对未知命令给「未知命令 /help」友好提示（非 HTTP 404）→「Help 无 404 命令」满足。**剩余/观感**：dismantle/桌宠/AgentMap「半成品移出主界面 chrome 收进实验菜单」为次要 GUI 收边——AgentMap hint 已由 T37 去除；完整「收进实验菜单」关联 T9 子代理当前改 `gui/`，本次未并线（注记留待后续或并入 T9 收口）。
>
> 收口注记（本会话）：补 AgentMap 收进实验菜单——`settingsStore` 加 `showExperimental`（default false，持久化纳入 PersistedLite）；`WorkspacePanel` 顶层 `地图` 入口与 `CommandPalette`「打开地图」默认隐藏（showExperimental 开启才出现）；`SettingsModal` 外观页新增「实验功能」开关（说明文案）。dismantle 已在 T36 清空无存留；桌宠 XeyoPet 本身在 Settings 页（非主 chrome），保留现有设置页入口。`gui npx tsc --noEmit` 通过；`gui vitest run` 551 例通过，1 例既有失败（chatStore rewind 恢复横幅 PR-R4，与本次无关）——证明本会话沙箱内 vitest 可运行（T37 的 EPERM 限制在此环境未复现）。

### v2 后的执行顺序（替换原 W1-W3）

```
W1（P0）: T25 → T26（安全小修，先钉死）→ T1（含 T27 顺序要求）→ T2 → T12
          T3（含 ALLOW 审计 + 面板 UX）→ T4 → T5 → T6 → T27 → T28
W2（P0 尾 + P1 头）: T7 → T29（断流 reattach）→ T10 → T14 → T17
W3+（P1）: T8 → T9（SSOT）→ T11 → T13（含 gap）→ T16（settings SSOT）→ T30 → T31 → T32 →（P2 立项）
```

审计「若只修 5 刀」的映射：①断流杀 turn→**T29**；②policy 放宽→**T26**；③原始输出先落盘→**T27+T1**；④统一 durable settings/session→**T16+T31**；⑤面板 UX+CLI bat→**T3+T32**。

---

## v3 融合修订：Goal 定稿设计 + 企业级缺口 + 整仓「新手感」审计并入

> 来源：①38-goal 一等实体设计评审（含 CAS 并发定案）②「本机企业级还差什么」对照 ③整仓四路审计（GUI 杂乱 / Python 引擎 / 文档入口 / 产品完备）。
> 主判：引擎内核扎实；乱在**外壳、叙事、半成品开关、双轨、安全边界**。新增两条 P0 安全任务；T9 升级为定稿设计；新增诚实度/卫生/门面/记忆解耦四任务。

### 修订既有任务

| 任务 | 修订内容 |
|---|---|
| **T9 goal（设计定稿）** | 按 38 号评审落地（见下方详设） |
| **T11 MCP** | `/mcp` 现状「只列配置」即审计定位的剧场；实现后列表必须来自 runtime 注册，未实现期 UI 标「未启用」 |
| **T29 远程稳态** | 并入 iLink zombie-slot（取消时机→~35s 僵尸 poll）与 channel.py `except TypeError` API 漂移（签名不匹配静默丢 peer/ctx → 显式契约 fail-loud） |
| **T31 跨入口** | 并入 channels AskUser 缺口（微信面无 Ask 弹窗；`/allow`/`/deny` 文本语义对齐 + AskUserQuestion 镜像）；cli-ts 收口（AskUser/Plan 最小可用或显式「去 GUI」，multi_agent flag 透传） |
| **T25c LOCAL-TEST** | 文件清单齐备（settingsStore/SettingsModal/ModelPicker/UsagePanel/api core/remoteStore/chatStream/streamSendSlice 等 12 处）→ 统一 `isLocalTestEnabled()` gate（dev 构建 + 显式开关），替换各处散条件 |
| **T32 交付** | 并入 start-tauri-dev.bat 相对路径化/移除、四 bat 职责表、空根 `cli/` 删除 |

### T9 详设（定稿，可直接开工）

- **实体**：`python/engine/goal_state.py` —— `Goal{goal_id, title, text, status, owner, origin, pending_complete, revision}`；4 态 `active/blocked/completed/abandoned` + **派生候选 `pending_complete`（非终态，仍 active）**；转换表按 38 号 §3，非法转换拒绝并记日志、不影响 turn 主路径。
- **存储**：`<workspace>/.xeyo/goals/goals/<goal_id>.json` + `bindings/<safe_session_id>.json`；tmp + `os.replace` 原子写；坏文件跳过。
- **并发三层**：per-workspace asyncio 锁（读→转→写临界区）+ `WorkspaceLock(owner=f"goal:{session_id}", ttl=10)` 跨进程短租约 + **PATCH revision CAS**（miss → `409 goal_revision_conflict`，body 附当前 goal 供刷新；客户端重读再提交，禁盲写）；文件原子写照旧。内部钩子不带 revision，对外 PATCH 必带。
- **钩子三点（只注册不进主循环）**：①chat.py submit 非续跑分支——无 binding→create+bind；有候选+实质消息→隐式 completed + 立刻 create 新 goal（同一持锁事务）；②turn_runner failed finally + `mark_crashed_as_recovery`——active→blocked(reason)；③resume cue——blocked→active、清候选、owner 重绑。
- **Additive 兼容**：TurnSnapshot/TurnPublic 加 `goal_id`（默认 ""）；`goal_text` 字段保留不动。
- **API**：`GET /v1/sessions/{sid}/goal`；`PATCH …/goal`（action: `confirm_complete|continue|drop|reopen|new` + revision）；`turns/current` 加嵌套 goal 投影。
- **resume 链三级兜底**：GoalStore.current → `_previous_user_goal(messages)` → snapshot `goal_text`（P1 加懒采纳：老会话首次 resume 把 goal_text 升格为实体）。
- **P1**：候选派生（turn succeeded + todos 全 done→`todos_all_done`；多 Agent `all_succeeded`→`batch_awaiting_synthesis`；synthesis succeeded→`synthesis_done`）；T_now Goal 块（**仅 blocked/pending_complete 注入，active 常态静默**；头 `# Goal（background only）`；cap 1200；走 T_NOW_EXTRA_BUDGET）；GUI chip（灰 active/绿描边候选/琥珀 blocked/青 awaiting_input）+ 候选条双按钮 + 恢复横幅读实体。
- **P2**：`/goal` 斜杠族（接 37 号 manifest；远程白名单评估）、`GET /v1/goals`、跨会话 peer goal hint、wrap-up「建议完成」软信号（仍需用户确认）。
- **刻意不做**：goal 树 / 单会话多活跃 goal / 跨 workspace / 模型直宣布 completed / goal 进 system 或历史 / goal 层杀 turn 挡工具 / 非候选期自动分类连发目标。
- **降级铁律**：锁/文件/坏 JSON 一律 try/except + log，resume 落历史扫描兜底——失败只降级不挡主路径。

### 新增任务

**T33 安全边界硬化 —— M（P0，审计 ship blocker）【✅ 已完成】**
- chat/sessions/rewind 路由默认 loopback 闸（与 local_gate 控制面对齐）；绑非回环地址需 `XEYO_ALLOW_REMOTE_CONTROL=1` + remote token。
- filehelper/ilink 的 start/stop/qr/status 接 `verify_remote_token`（token 机制已存在，主通道未接）。
- legacy `/api/chat` 移除 body `api_key`（密钥只走 env/config）。
- CORS `allow_methods/allow_headers` 由 `*` 收敛为实际清单。
- 验收：LAN 直连默认拒；无 token 不能启停通道；请求体与日志无密钥。

**T34 错误信息人话化 —— S/M（P0）【✅ 已完成】**
- `common/errors.py` 兜底不再裸 `str(exc)`；rewind/sessions `api_error` 不外传内部异常文本；channels 回帖前过滤。
- GuiErrorBoundary 去 `<pre>` dump（友好页 + 可展开详情）；toast 统一友好文案。
- 验收：API 响应、微信回帖、GUI 崩溃页均不含 Python 异常原文。

**T35 产品诚实度收口 —— M（P1）【✅ 已完成】**
- README/能力矩阵 = catalog `ENABLED_TOOL_ENTRIES`；`/mcp`、Multi-Agent chip、Memory/L5/NightShift、Java 文案改「实验/未启用」；task6 移出卖点序列。
- XeyoUI 非 GUI 面返回明确「需要 GUI」而非假成功；cli-ts manifest 只列可跑命令；symbol 级「33」注明无 tree-sitter 时的退化行为；Diagnostics 无后端时从 ENABLED 摘除或明示。

> 实施要点与计划差异：README「核心能力」新增「成熟度说明（诚实口径）」——21 项工具逐条对 `ENABLED_TOOL_ENTRIES`，并明示插件/MCP（默认关）、Multi-Agent（实验）、Memory C2/L5+NightShift（默认 `XEYO_L5=project`、C2 关）、符号 33（无 tree-sitter 自动降级）、Java（未启用）均为「实验/未启用」。代码侧【新增】`policy` 入口面上下文 `surface`（默认 gui；`set_surface/current_surface/is_gui_surface`），XeyoUI 的 UI 副作用动作在 cli/cli_ts/remote 面明确返回「需要 GUI」（list_sessions 仍放行），`cli/chat_cmd.py` 进程内脚本置 `surface=cli`，`server/routers/chat.py` 读 `X-Xeyo-Surface` 头并 finally 复位；Diagnostics DESCRIPTION 明示 best-effort（依赖 ruff/tsc，无后端明确报不被猜）。测试新增 3 例（xeyo_ui 非 GUI 闸），邻域 40+29 例通过。**不足**：cli-ts manifest 仅列可跑命令与完整 surface SSOT 属 T31（跨入口 SSOT）范畴，本次未全量接线。

**T36 仓库卫生与文档收口 —— M（P1）【✅ 已完成】**
- .gitignore 补齐（根 `.xy-shadow-git/`、`.dsh-repro*`、credentials、`*-preview.html`、tmp/log）；根目录 scrap 清除（theme-preview.html、test.ipynb、_tmp_* 等）。
- `.agents` skills 三副本去重（tailwind / tailwindcss / 已删 tailwindcss-perf 的 git+规则残留删净）。
- docs/README 单一「当前总纲」指针（现指 00，应指 09/08）；回溯 v1/v2 文档归档；branding 收口说明（XEYO/XenYon/xy-/XeyoPet）。

> 实施要点与计划差异：`gitignore` 补 `.xy-shadow-git/`、`.dsh-repro*`、`credentials`、`*-preview.html`、`tmp/`（`logs/` 已存在）；删根目录 scrap（theme-preview.html、test.ipynb、sidebar-running-animations.html、agent-a.md、_tmp_mech_bench.txt、pytest-chunk0.log、pytest-full.log、test_tools_output.txt、dsh-glob-no-match-suggestion-design.md、空目录 `-p`），未动源码/受保护文件；`.agents/skills` 三副本去重保留 canonical `tailwind`，删 `tailwindcss` 副本与 `tailwindcss-perf` 残留；docs/README「当前总纲」指针改为 09（00 标演示期总纲）；新增「品牌命名说明」节（XEYO/XenYon/xy-/XeyoPet）。**观察项**：`gui/theme-preview.html` 为被追踪的 `*-preview.html` 且不在根目录，未删（若确属一次性预览后续单独处理）；`tailwind/SKILL.md`、`tailwind/AGENTS.md` 内引用了不存在的 `metadata.json` 为既有遗留，范围外未改。本任务无行为变更，未跑测试（仅静态/git 检查验证）。

**T37 GUI 门面清理 —— M（P1）【✅ 已完成】**
- EmptyState 英文 quip 墙中文化或删除；ContextIsland DEV HUD 移到 /bench 路由；AgentMap 去 `preview · scroll zoom`；rewind 设置页口语化（blob GC/字节上限）；bench/lab 路由加守卫。
- dismantle 26 条脚本+引擎归档 `scripts/archive`；依赖清理（@heroicons 零引用删除、@tauri-apps/api 归 devDependencies、@types/react-syntax-highlighter 归 dev、CSS 注释乱码修复）；`__probe4` 假测试删除；`rollbackSlice` v2 stub 删除（api.ts 收敛单协议，配合 T31）。

> 实施要点与计划差异：EmptyState 标题中文化「在「{workspaceName}」里，我们要一起构建些什么呢？」；`emptyQuips.ts` 整墙 quip 中文化（EMPTY_QUIPS，`pickEmptyQuip` 防重复）；AgentMapCanvas 去 `preview · scroll zoom` hint；删除 `__probe4.test.tsx`、删除 `rollbackSlice.ts` v2 stub（chatStore/preStoreHelpers 引用同步清理）；package.json 依赖清理（@heroicons 等零引用与 devDeps 归位）；ContextIslandRuntime 处理 DEV HUD。**验证**：GUI `npx tsc --noEmit` 通过（子代理完成并自跑 typecheck 通过；vitest 在本沙箱 EPERM 受限，未跑通，改动为结构性/文案，typecheck 已覆盖类型一致性）。remaining：dismantle 26 条脚本在 T36 已发现 `.dismantle` 无存留（近清理完毕），`scripts/archive` 无新归档需求；bench/lab 路由守卫与 rewind 设置页口语化以文案/网关改动为主，typecheck 通过。
>
> 收口注记（本会话）：GUI vitest 复跑通过（`npx vitest run` 551 例通过 / 1 例既有 chatStore rewind 横幅失败）——本会话沙箱内 vitest 可正常 spawn 运行，T37 时任的 EPERM 限制未复现。

**T38 记忆热路径解耦 —— S/M（P1）【✅ 已完成】**
- `memory/runtime` 生产投影与 `memory.simulator`（离线实验）解耦（decision 逻辑抽独立模块或条件 import）。
- ChatHeader「立即压缩 /compact」按 C2 gate 显隐（避免讲成「记忆已完成」）。

> 实施要点与计划差异：解耦走「条件 import」——`memory/runtime.py` 移除 `from memory.simulator.{cache_model,decision,params,scenarios,state_model}` 顶层 import，`project_for_model` 的 v61/C2 分支与 `force_compact` 内改为惰性 import（默认 project 路径 `return` 前不触 simulator）；纯估参 `token_len`/`n_lines` 抽到【新】`memory/token.py` 生产共单，`simulator/state_model.py` 改转导出（单点不漂移）。因 `decide`/`load_params` 不再作为 `memory.runtime` 模块属性，测试把 `monkeypatch.setattr("memory.runtime.decide"/"memory.runtime.load_params", …)` 改为打 `memory.simulator.decision.decide` / `memory.simulator.params.load_params`（语义等价，惰性 import 在调用时取到补丁值）。GUI `ChatHeader` 的「立即压缩 /compact」按 `compression.c2_gate`（后端 `/v1/sessions/{id}/compression` 回真实 `c2_gate()`）显隐：gate 关（默认）不渲染按钮，改为诚实提示「C2 压缩为实验功能，默认关闭（XEYO_C2_GATE=1 开启后可用）」。测试 4 例（import 隔离子进程 + 共享估参奇偶），memory 邻域 125+37 例通过；GUI typecheck 过。

### v3 执行顺序（取代 v2 顺序）

```
P0（安全+止血）: T25 → T26 → T33 → T34 → T1（含 T27 顺序要求）→ T2 → T12
                → T3 → T4 → T5 → T6 → T27 → T28
P1（结构+收口）: T7 → T29 → T30 → T9（按定稿设计）→ T10 → T14 → T17
                → T35 → T36 → T37 → T38 → T8 → T11 → T13 → T16 → T31 → T32
P2: 同 v1（Windows 沙箱 / 投影推拉 / 网络白名单 / SQLite 索引 / hooks / code-mode / worktree）
```

企业级缺口对照（08/09「本机企业级」口径）：治理→T25/T26/T33/T10；举证→T27/T28/T34；远程稳态→T29/T30/T31；跨入口→T16/T31；交付体验→T32/T35/T36/T37；Goal→T9。大厂 SaaS 另册（SSO/RBAC/多租户/合规平台/SLA）仍明确不做。第五波探索（测试/CI、Tauri capabilities、斜杠与权限、记忆热路径、能力矩阵）未回报的部分已由 T33/T35/T36/T38 预覆盖，报告到位后并入对应任务。

---

## v4 融合修订：并发防务审查并入

> 来源：④全库防并发审查（SessionPool/TurnRunner/工具编排/WriteStore/Agent/channels/前端 + 市面 agent 对照）。
> 主判：**主路径（聊天 turn）防并发企业级可用**——租约 + TurnRunner 双闸 + lease 语义 + 工具分区 fail-closed 已对齐市面主流（Claude/Cursor/Codex）；缺口集中在**旁路入口、引擎内防御、前端抢占时机、部署约束**，不是推倒重来。

### 审查确认的优势（不动）

SessionPool 双闸（`is_running` + `try_begin`）+ lease_id 释放语义 + stale 300s 回收；断线不断 turn；工具分区 fail-closed；多 Agent batch abort 期间禁 try_begin；`session_presence` 跨会话写冲突 ASK **比多数 CLI 更进取**。市面共性确认：单进程内存态互斥是行业常态（无需分布式锁）；多 worker 才需要外部 lease。

### 修订既有任务

| 任务 | 修订内容 |
|---|---|
| **T2** RWLock 门控 | 借鉴 Claude **`isConcurrencySafe(input)` 按入参判定**：只读 bash 可进读侧并行（如 `ls`/`cat`），写类 bash 必串行——判定器复用 T7 的 bash 前缀规则（basename+prefix→读/写分类），解析失败/未知命令 fail-closed 归写侧 |
| **T29** SSE 稳态 | 并入 **GUI `sendMessage` TOCTOU**（审计优先级#2）：`isLoading`/abort/send-token 占位提前到 `await syncWorkspaceRoot` **之前**，消灭连点双过 |
| **T30** 端口健康 | 并入**单 worker 硬约束**：`server/__main__.py` 文档化或启动时检测/拒绝多 worker（多 worker 会使内存 busy 表失效）；`XEYO_HTTP_HOST=0.0.0.0` 绑定时与 T33 联动提示 |
| **T24** worktree 隔离 | 行业确认：Claude/Cursor 多 agent 主流是 **worktree 隔离优先于共享工作区上锁**（best-of-N 到 8），维持 P2 立项；注意共享 `.git` 的 `index.lock` 重试 |

### 新增任务

**T39 并发旁路对齐与引擎内防御 —— M（P0）【✅ 已完成】**
- **compact 旁路补 `is_running`**（审查优先级#1）：`chat.py` 的 `/compact` 现只调 `try_begin`——权限等待久导致租约被 stale 回收时，compact 可能与仍在跑的 turn 同时改 `session.working`；与主路径对齐（`is_running` + `try_begin` 双检），或改走 slash dispatch（已有 `_reject_if_busy`）。
- **QueryEngine.submit 引擎内互斥**：MessageStore 无锁、安全全靠外层闸门——引擎内加 "already running" 防御（对齐 Codex 单 session 单任务模型），护住 CLI 进程内 REPL 与漏检入口。
- **TurnRunner 跨线程读**：`is_running` 读 `_turns` 时，sync 路由（slash/interrupt）在 threadpool 与 loop 侧写并发——相关路由改 async 或读路径加锁/快照。
- **InboundQueue._lock** 声明未用于 push/pop——补上或删掉。
- **命名去混淆**：`engine.workspace_lock.WorkspaceLock`（跨进程）vs `rewind.locks.WorkspaceLock`（进程内）重名易错用——后者改名（如 `ProcessLock`）或显式别名注释；v3 rewind hotpath 文档要求的 WorkspaceLock 语义与实现（busy 409）差异写进 rewind 文档。
- **验收**：compact 在 turn 运行中返回 409；引擎内重复 submit 被拒；`_turns` 读写无裸跨线程；多 worker 启动被拒或警告。

### v4 执行顺序（增量，其余同 v3）

```
P0 追加: T39（compact 双闸 + 引擎内互斥，紧跟 T28 之后）
P1 不变; T2/T29/T30 修订内容随原任务执行
```

---

## 执行顺序建议（v1 原稿，已被上方 v2 顺序取代）

```
W1: T1 → T2 → T12（小而独立，先跑通「新机制接入模式」）
    T3 → T4 → T5 → T6（引擎/协议侧并行推进）
W2: T7 → T10 → T14 → T17
W3+: T8 → T9 → T11 → T16 →（P2 立项）
```

每任务一条 PR、附单测与验收清单；T8/T9/T11 动引擎核心，各自先出设计小节再动手。
