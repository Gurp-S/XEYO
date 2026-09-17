# XEYO 项目级说明

仓库结构：`gui/`（React+TS 前端，Tauri 壳）、`tui/`（Ink 终端 UI）、`python/`（engine + FastAPI server + Typer CLI）。

## 设计理念（引擎铁律，2026-09-08 定稿；改引擎 / 写模型可见文本前必读）

XEYO 引擎对模型注意力的总原则：**注意力里只出现信息，不出现导演**。

1. **只给信息**：模型可见的一切文本（system prompt、T_now 注入块、工具结果、错误 detail、工具描述）只承载**状态 / 结果 / 事实**。禁止建议、劝导、评价、奖励、惩罚、以及"应该 / 优先 / 不要再"式编排文本。
2. **模型自决**：调度、规划、执行的全部决策由模型自己做；引擎不规划路线、不纠偏、不点评。引擎认为更优的路径至多以事实形式呈现，或干脆不呈现。
3. **限制只在执行层**：引擎的限制永远存在，但只在执行层表达——检测到模型反复走不该走的路，就让该路径的工具**持续静默报错**；报错措辞必须是中性结果型（如 `Permission denied: …`、`missing_read: no prior Read for this path in this session`），绝不写成警告 / 说教 / 指令去影响注意力。
4. **能静默就不说话**：引擎自己能完成的事（状态维护、清理、折叠、重建）一律静默完成，不给模型看（范本：`memory/instruction_maintain.py::reconcile_nested_state`）。第一问永远是"能不能不进上下文"——引擎能强制的，一律不给模型看。
5. **弱模型护栏不做在引擎文本里**：不靠往注意力塞提示来兜底弱模型；护栏 = 执行层机制（DENY、报错、折叠）。

写任何模型可见文本前自检：这是**信息**还是**指令 / 评价**？非信息 → 删掉，或改为引擎执行层动作。既有整改范本：2026-09-08 全仓理念审计（51 文件，净 −813 行）；权威面 = `python/prompt/system_prompt.py`、`python/prompt/pre_llm_inject.py`、`python/prompt/t_now_strategy.py`、`python/engine/` 各 guard。

## 入口与运行模型（读代码前先看）

| 你要…               | 入口                               | 与引擎的连接                                                                        |
| -------------------- | ---------------------------------- | ----------------------------------------------------------------------------------- |
| 桌面 GUI             | `XEYO.bat` → `gui/` Tauri dev | HTTP/SSE →`python/server`                                                        |
| 终端 TUI（Ink）      | `XEYO-TUI.bat` → `tui/`    | **必须先** `py -3.11 -m cli serve` 或已运行的 FastAPI                       |
| 脚本 / 管道 / attach | `python/cli/` Typer              | 进程内`QueryEngine` 或 HTTP attach                                                |
| 改斜杠命令           | `python/slash/registry.py`       | 改后跑`py -3.11 -m slash.export_manifest` 并提交 `*/generated/slashManifest.ts` |

## 工程硬规矩（机器执法，违反即失败）

1. **提交门**：`tsc + vitest + pytest P0` 全绿才允许 commit。既有失败必须显式 `xfail` 并注明归属，不允许静默挂账。
2. **开工检查**：第一行功能代码前先看 `git status`——工作树里只允许有本功能的在途改动；发现跨功能的在途改动，先停下向用户确认归属，禁止把别人的在途改动卷进本次提交。
3. **任务流程：**有疑问,用户表达不明确,有歧义必须提问用户,获得最符合用户的理想方向
4. **新功能准入**：新行为先以旁路形态（feature flag / 独立模块 / 钩子）上线验证收益，**有数据证明收益后才并入主链路**；并入时在对应登记表（如 T_now 块登记表）标注功能归属与收益证据。
5. **事故模板**：事故修复前必须先答三个问题——结构性根因是什么？哪条规则能让它结构上不再发生？回归测试怎么写？答不出第一条的修复只是把事故推迟。
6. **任务完成：** 反问自己:是否解决用户的问题?是否过程中产生或埋下隐患?用户任务是否已经完成且边界清晰?
7. **反巨石**：新逻辑一律进新模块，既有巨石（`chat.py` / `query_loop.py` / `Composer.tsx` 等）只留接线点；因功能触碰巨石时允许顺手抽离本次触碰的函数，禁止顺手做无关重构。

## Bash 专用工具路由（本工作区已开启）

`<workspace>/.xeyo-policy.json`（即仓库根 `.xeyo-policy.json`）已设 `"bash_routing": "auto"` +
`"bash": "default"`。权威口径以 `python/tools/bash_tool/` 路由实现与 `tests/test_bash_routing*` 契约为准。

- **透明路由**：Bash 中纯文件读命令且目标在**工作区内**时，引擎直接改用专用工具执行并返回结果——
  `cat/type/Get-Content`→`Read`、`rg/grep/findstr`→`Grep`（`output_mode="content"`）。
- **模型可见信号**：结果头会带一行 `[routed: Bash …→…]` 提示；GUI 工具区显示 `Bash → Read/Grep`。**不是错误**，数据已到手。
- **明确不路由**：`ls`/`dir`/`ll`/`la`（Glob 对宽匹配 `*` 只回目录摘要、列不出文件名，故交给 bash 真实列目录）、
  `find`（不在 bash 只读白名单，`bash=default` 下先 ASK）；以及目标路径在工作区外、或带管道/重定向/链式的复合命令 → 原样执行 Bash。
- **回退**：把 `bash_routing` 改为 `"off"` 即回"报错提示"行为；`"auto"` 启停属工作区策略，Agent 工具层不可写该文件。
- **渐进强制（Phase 2）**：`bash_escalate`（整数，0=关；同会话同命令形状重复命中达到该次数后放行 bash 执行）。**推荐值 3、上限 5**；仅在 `bash_routing=off`（报错路径）生效。可在「设置 → 权限 → Bash 工具策略」调整，或写 `<workspace>/.xeyo-policy.json`。

## 易变上下文必须走 T_now（新增前先查重 + 硬准入）

新增"每轮可能变化 / 随时可能开关"的模型可见内容（提示块、状态、提醒、开关类指令）时，**默认走 T_now 注入管线**（`python/prompt/pre_llm_inject.py`），不要写进 system prompt、不要拼进历史消息。权威口径以 `pre_llm_inject.py` / `t_now_strategy.py` 实现与 `tests/test_t_now_block_registry.py` 为冻结面。

**注入声道（声道 B 原生 system，2026-09-15 起默认）：** 默认策略 `system_channel`（`python/prompt/t_now_strategy.py`）——全部易变块作为一条**原生 system 消息**追加在投影尾部（`turn_context.append_system_notice`），不进 MessageStore/JSONL、不进 tools 数组（schemas 冻结红线不受影响）、尾部追加 KV 前缀逐字节不动。协议分工：OpenAI 系保留 `role=system`；Anthropic 由 `anthropic._split_system` 上提顶层 `system` 字段（`_build_body` 无 `cache_control`，无显式缓存可损）。

**为什么废掉伪对（原方案 A 环境声道）：** 伪对 `assistant(tool_use: xeyo_env_notice) → tool_result` 与「模型自己的工具调用」**完全同形** ⇒ 模型在投影里看到自己调过该工具，判定自己拥有它并真的去调。实测第六轮单会话 70+ 次、第七轮 80+ 次（含多次整条响应体只有该调用），且**被 host 侧应答者当成真实工具轮应答**（回灌 `# Continue（工具结果后）`）⇒ 自催化闭环；意图抑制不可靠（明知情、正在修它时仍复现）。system 是"引擎注入的状态"的原生声道：既非 user（说话人隔离仍成立）也非 assistant ⇒ **不可调用性来自形态本身**，不靠劝阻文本。

**回退阶梯（均为进程级备忘，重启即重试）：** `system_channel` --结构类 4xx（400/404/413/415/422，未吐 chunk）--> `env_channel`（保功能；已知会重新引入上述 affordance）--结构类 4xx--> `skip`（L2：宁缺毋滥，绝不落回 legacy 用户尾插）。`env_channel` / `legacy` 保留为对照与显式评测档。策略优先级：会话/请求显式（`set_t_now_strategy`）> `XEYO_T_NOW_STRATEGY` 环境变量 > 默认 `system_channel`；`prefill` 为预留档（实测前回落 `env_channel`）。

**硬准入（2026-09-04）：** 块登记表 `T_NOW_BLOCK_REGISTRY`（`pre_llm_inject.py`）：每个块一行（**pipe 管道 / quota 是否受配额裁剪 / dedup 是否纳入"值不变不重注"台账 / why 为什么必须在上下文**），**登记数硬顶 16**，加一块必须删一块或证明预算不破；所有装配点必须走 `_tag_block(tagged, "登记名", 正文)`（裸 `tagged.append(` 被测试禁止），名与登记表一一对应，由 `tests/test_t_now_block_registry.py` 机器执法——新块不登记、事件块声明去重或配额，测试即红。第一问永远是"能不能不进上下文"（引擎能强制的，一律不给模型看）。

**T_now v2 = 一个边界，三条管道（2026-09-16 重分类 + 落地）：** 边界 = 工具批次完成后 / 下一次采样前（`engine/query_loop` 边界处三件事同刻：留痕落库 → 引导投递 → 装配注入）。**管道 1 用户消息**：运行中输入 → 队列（`engine/t_now_steer`）→ 到边界取出 → **真 user 消息进历史**（`role=user`，可被引用/压缩；不打断工具批次、不伪装角色）。服务端开关 `steer_if_busy`（需同时 `queue_if_busy`）。**管道 2 引擎当前态 → `PIPE_STATE`**（每轮可能变；`dedup=True` 者值不变不重注——台账 `python/prompt/inject_store.py`，档位 `XEYO_T_NOW_DEDUP=on|shadow|off`，**默认 on**；未落库成功的版本一律重发，`off` 为逃生门）。**管道 3 引擎事件 → `PIPE_EVENT`**（drain 语义：永不裁剪、永不门控、**永不去重**，去重＝静默丢事件）。装配点不自带类目，类目只在登记表。

**留痕面（hidden note，管道 2 的"进历史"半边）：** 值变过一次的块，在下一个边界以 `role=system` 条目落进 MessageStore + transcript（`msgtypes.message.system_note`，身份字段 `note_kind/note_key/note_fp`，`row_from_message` 持久化、`message_from_row` 恢复），此后历史里就有这一版 ⇒ 台账判「值没变」成立 ⇒ 尾部不再重发。**模型可见 / 用户不可见**：`/v1/sessions/{id}/messages` 过滤 `note_key` 行。历史被改写（压缩 / 回溯 / 会话删除）⇒ 台账清账（`engine/t_now_notes.invalidate_after_compaction`、`session_pool.resync_after_rewind` / `.drop`），下一轮按当前值重注——先改写、后重注。失败一律 fail-open。

**现有 T_now 候选（新增前先查重）：** 管道 2｜Continue（工具续写）、Ask/Plan 模式指令 + Approved Plan（首写收敛 + 实施中指针）、Multi-Agent hint、Repeat guard、Nested XEYO.md（限窗，quota）、输出精简 / 写代码精简（compact）、浏览器预览（quota）、Goal、技能直呼（skill_preinvoke）；管道 3｜续跑指令 Resume（投影-only，`engine/resume_directive.py`）、MCP required 故障、工具面/技能目录变更（reconcile）、跨会话通知（peer_notices）、文件冲突、子代理结算、jobs 补投。最新权威清单以 `T_NOW_BLOCK_REGISTRY` 为准。

**已下线（不再推送 T_now）：** Proposals digest（拉取走 `/proposals` + Memory 候选计数行）、Memory index 块（脚本/评测用）、`wrap_up` / `runtime_budget` 两块（2026-09-15 用户裁定撤销：只讲"预算已尽"却不标作用域，模型必然误标成上下文窗口——第五/第六轮各一次；按引擎铁律「限制只在执行层」，收尾窗与配额由 `engine/query_loop` 强制，不需要讲给模型听。**预算机制保留**，撤的只是模型可见文本）、`budget_mirror`（触发条件产品链路从无设置＝死块）、`runtime_mode_snapshot`（真门禁在 permissions 层）、**D1「模糊指代轮静默参考块」（2026-09-16：弱模型特化，按铁律 1/5 删除——注意力里只出现信息，模型强弱不改变口径）**。

## 扩展层（MCP × SKILL）契约

权威口径以 `python/extension/`（`mcp_gateway.py` / `mcp_client.py` / `reconcile.py` / `config.py`）实现与 `tests/extension/test_freeze_invariants.py` 等契约为冻结面（配置、产品决策、实施注记见代码注释）。

- **配置单一来源**：`<root>/.xeyo/settings.json`（后台纯 JSON，无 GUI）。home 级 `~/.xeyo/settings.json` 与工作区级 `<ws>/.xeyo/settings.json` 按范围合并，**workspace 更具体者优先**；总开关 `enabled_extensions`（默认 **关**）；`plugins/skills/mcp_servers` 各带 `{"<name>": {"enabled": true, ...}}`。坏 JSON 走 keep-last-good + `config.invalid` 审计，方向安全（不静默打回默认）。
- **原生工具面 = 会话起点快照**：attach 时按当时启用状态决定哪些 MCP 工具进 `schemas()`；此后 **tools 数组会话内冻结、零前缀重缓存**（绝对红线）。会话内启停**永不触碰 `_schemas_cache`**。
- **会话内新增工具的唯一通道 = `Mcp` 网关工具**（`python/extension/mcp_gateway.py`）：`action=list|describe|call|resources|read_resource`，扩展开启时**始终注册**。list 含 hidden-but-registered 标注；describe 按 (server,tool) 返回入参 schema；call 身份经**已知工具集解析**（`resolve_tool`），绝不从 args 之外的通道取身份。
- **会话内启停 = push 为主 reconcile**（`python/extension/reconcile.py`）：`set_mcp_enabled`/`set_skill_enabled` 后**直接发布**单轮 T_now 活页块（`# 工具面变更`/`# 技能目录变更`），digest 幂等（同值零块）；pull 兜底 = `enabled_probe`。活页块经 `prompt/pre_llm_inject.py` 按**管道**装配（`PIPE_STATE` / `PIPE_EVENT`），**事件类静默即失，绝不门控、绝不去重**。
- **停用即时 DENY，不可被 grant 穿越**：`permissions/policy.py` 先于 grant 两分支判定，`移除→DENY` 门。网关**不绕权限**——`registry.run` 的 ASK/DENY 在 `execute` 之前已按目标工具策略裁决；子代理注册表只来自静态工厂，网关天然不可达。
- **指纹 v2（授权身份）**：`permissions/store.py` `mcp_grant_fingerprint = "v2:" + sha256(["mcp-tool", 注册名])[:32]`（**参数不进指纹** → 注入免疫）；`mcp_target` 贯通 `PolicyDecision → 挂起项 → /v1/permission/resolve`。v1 已不匹配 v2。
- **控制路径**：`GET/POST /v1/extensions/settings`（`server/routers/extensions.py`，loopback 门禁，POST=push reconcile）+ `/mcp enable|disable|tool`（`python/slash/dispatch.py`）；manifest 已重导出到 `*/generated/slashManifest.ts`。
- **契约测试（改扩展层必须守）**：`tests/extension/test_freeze_invariants.py`、`tests/extension/test_reconcile.py`、`tests/extension/test_mcp_fingerprint_v2.py`、`tests/extension/test_mcp_gateway.py`、`tests/extension/test_mcp_exposure.py`、`tests/test_extensions_api.py`。
- **扩展层改动验收**：`py -3.11 -m pytest python/tests/extension -m "not live"`（本地手动执行）；无网关路径零回归（P0a 出口）。
