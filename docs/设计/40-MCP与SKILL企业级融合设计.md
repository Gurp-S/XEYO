# 40 - MCP × SKILL 企业级融合设计（冻结稿）

> 状态：**设计冻结，待实施**。本文档自包含：换会话/换工程师可直接按 §6 落地文件清单开工，P0 范围见 §9。
> 依据：`docs/DSH-可借鉴机制对照报告.md` §11、`docs/Codex-可借鉴机制对照报告.md` §3/§5/§6/§13，以及 Codex Rust 源码三路精读（`codex-rs/skills|ext/skills`、`codex-mcp|rmcp-client|connectors`、`core/src/tools|core-plugins|context-fragments`），一手结论已内嵌并在括号注明出处文件。

---

## 1. 背景与问题

XEYO 扩展层（`python/extension/`）现状：

- **MCP**：`extension/mcp_client.py`（T11）stdio 客户端完整（JSON-RPC、重连退避、generation 整体替换/回滚、schema 5KB 降级、权限三态约定），但**从未接线到真实会话**——`register_mcp_server` 仅测试调用；`tools/catalog.py`、`server/session_pool._build`、`engine/query_engine.build_default_engine` 均不挂 MCP 工具。
- **SKILL**：`extension/skill_loader.py` 三源发现（workspace>home>plugin）+ `tools/skill_tool/skill_tool.py` 按需加载可用，但：目录嵌 schema 无上限、>12KB 截断不可回读、frontmatter 静默容错、无 model/user 双面调用策略、skills-lock.json（`skill_store.py`）无任何调用方、无启停写盘。
- 插件 `prompts` 解析后从未投影（`prompt_paths` 无调用方）；settings 写入非原子；坏插件只进日志不可见。

目标：让 MCP 与 SKILL 端到端可用，并按 Codex/DSH 的企业级机制融入 XEYO 全部既有机制（见 §3 接缝表）。

## 2. 用户已冻结的产品决策（改设计先改本节）

1. **技能目录 = 图书目录「会话快照」+ 活页增量**：Skill 工具 schema 内嵌索引——每技能一行 `- 名字: 一句话描述[来源]`（**描述截 120 字符、总硬顶 2400 字符**，超出尾注「更多用 action:'list' 查询」）；目录在**会话建立时按当时启用状态渲染，会话内永不变化**（tools 数组冻结红线）。会话内技能启停 → 单轮 T_now 活页块（`# 技能目录变更（background only）：+名字（一句话）`）+ `Skill{action:"list", query}` 即时可查；下个会话重塑原生目录。SKILL.md 正文仍走 Skill 工具按需加载进历史（红线不变）。
2. **`Skill{action:"list", query?}` = 详情/检索**：每条 desc ≤500 字符、总响应 ≤4k 字符，query 按名称/标签/描述子串过滤（客户端过滤，廉价）。
3. **单旗子原则**：只留 `model_invocable`（false → 不进目录、list 不出现、拒绝模型加载）与 `user_invocable`（false → 用户菜单/`/skills` 不展示）。砍掉 `advertise` 等冗余旋钮。
4. **MCP 逐工具勾选**：GUI 面板 checkbox → `enabled_tools: null|[raw名]`（null=全部，勾选过即写显式表）；未勾选工具**不进 schemas 但保留注册**（模型幻觉调用仍走权限 ASK，fail-safe）；cap 32 兜底。
5. **MCP 默认全关**：总开关 `enabled_extensions:false`（现状）+ 每 server `mcp_servers.<id>.enabled:false`（现状默认）+ project scope 首次 `/mcp approve` 信任批准。未启用 server 对模型 0 token、不 spawn。
6. 用户手势三档全通：GUI 技能菜单插 `$name`、`/skills show`、Skill 工具按名加载。

## 3. XEYO 接缝盘点（每个机制都有落点）

| XEYO 现有机制 | MCP/SKILL 融合点 |
|---|---|
| T_now 注入管线（`prompt/pre_llm_inject.py`，6000 字符预算/净化清单） | 插件 prompts 块、`$skill` 提及提示块、required 服务失败警告；子代理净化清单自动豁免 |
| ToolMeta 单表（`tools/meta.py`，已有 `output_budget`） | 增 `exposure: "normal"\|"hidden"` 列 |
| ToolRegistry 三态 gate + readonly_gate（读 `tool_flag`） | MCP 分支 + `McpTool` 实例级 `is_read_only` → Plan/Ask/side/readonly 自动放行 |
| `_eligible_for_early` 投机执行（`engine/query_loop.py:105`） | manifest 声明只读的 MCP 工具进早期并行批 |
| grant store「always allow」（`permissions/store.py`） | MCP 工具弹窗持久放行，指纹按 tool name |
| repeat_guard（`engine/repeat_guard.py`） | 对 `mcp__*` 按 canonical input 自动生效，零改动 |
| agent_scope / 子代理静态工厂表 | MCP 工具天然不可达子代理（白名单只来自静态工厂）；`agents/*.toml` role `extra` 可声明 skills/mcp_servers 作 spawn 提示 |
| `ToolResult.images`（Read/Screenshot 已用，`query_loop.py:1585` 视觉链路） | MCP `image` 内容块 → data URL 直接进视觉链路 |
| spill + 输出预算（registry 级 16000 字符） | MCP 超长输出/resource 块自动 spill；per-tool `output_token_limits` 实例覆盖 |
| AskUserQuestion 挂起机制（ask_store） | MCP elicitation server 请求路由到同一面板应答 |
| audit `record()` + usage 计数（`multi_agent_metrics` 范式） | `mcp.server.*`/`mcp.tool.call`/`skill.loaded/mentioned` 事件 + 调用计数 |
| slash registry + manifest 导出 | `/mcp` `/skills` 子命令升级；`py -3.11 -m slash.export_manifest` 同步 GUI/TUI |
| settingsStore→api.ts→chat.py→contextvar 链 | 扩展开关走同链路新端点（`/v1/extensions/settings`） |
| config.toml `api_key_env` 范式（密钥不落盘） | MCP 密钥按名引用 `bearer_token_env_var`，同理不落明文 |
| session_pool 引擎重建 | 连接按配置身份复用，重建不重 spawn |
| skill_store lockfile（hash 固定） | install/update/remove/doctor 接线 |

## 4. Codex 源码机制 → 吸收对照（一手出处）

| Codex 机制 | 出处 | 吸收方式 |
|---|---|---|
| 连接身份复用、`required` 分级启动、30s/300s 每服务超时 | mcp_types.rs / rmcp_client.rs L97-98 | F1 |
| env 白名单 `env_vars:[名]` + `bearer_token_env_var` 按名密钥（**无 ${VAR} 展开**） | rmcp-client/utils.rs | F1 |
| 工具名 ≤128B + 冲突 SHA1-12；`enabled_tools/disabled_tools`；单工具 spec ≤8000B/服务总量 ≤64000B 超限→Hidden | codex-mcp/tools.rs、mcp_tool_exposure.rs | F2 |
| annotations：readOnlyHint→免审可并行，destructive 缺省按危险；per-tool `approval_mode`；session 键 {server,tool} | mcp_tool_call.rs | F3 |
| elicitation 全链路 + 挂起暂停超时（`ElicitationPauseState`） | rmcp_client.rs / session/mcp.rs | F7 |
| 工具结果 image 块、resources 经内建工具 `list/read_mcp_resource` 暴露模型 | handlers/mcp_resource*.rs | F6 |
| 目录渲染：description 截断+总预算分档；fail-closed+标量行向修复；双 flag | render.rs / parser.rs / provider/host.rs | F4 |
| `$Name` 提及 + name_counts 歧义防护（纯名仅全局唯一生效） | selection.rs / name_counts.rs | F5 |
| SKILL `dependencies.tools[type=mcp]` → 缺失检查+Install/Continue+policy 准入 | core/src/mcp_skill_dependencies.rs | F5 |
| broken-but-listed（`LoadedPlugin.error`，`is_active=enabled&&error.is_none()`） | core-plugins/loader.rs | F8 |
| git_policy：剥 17 个具名 GIT_* 变量 + `GIT_OPTIONAL_LOCKS=0` + `safe.bareRepository=explicit` | core-plugins/git_policy.rs | F8 |
| skill 调用遥测（explicit/implicit） | core/src/skills.rs | F8 |

## 5. 融合机制设计（F1–F8）

### F1 运行时接线 + 生命周期（P0）

新建 `python/extension/mcp_manager.py`：

- `McpManager` 按 resolved workspace 进程级单例（`get_mcp_manager(cwd)`）。
- `collect_specs()` 汇三来源：插件 manifest `mcp_servers`、`~/.xeyo/mcp.json`（user）、`<ws>/.xeyo/mcp.json`（project）；同 id 冲突 **project > user > plugin**；企业 deny 一票否决。
- server 身份 = canonical 配置 sha256；attach 时按身份复用 ready client（Codex `reusable_client` 语义），身份变更才重连。
- `required:true` 的 server 启动失败 → 不挡会话，T_now 挂 `# MCP 依赖异常（background only）` 警告 + 审计（比 Codex exec fail-fast 温和，GUI 场景更稳）。
- `attach_mcp_tools(registry, cwd)`：用现有 `McpServerRuntime(spec, registry=reg, client=client)` 注册工具；扩展层关 → 一次读盘 no-op。
- **接线点仅两处**：`server/session_pool._build`、`engine/query_engine.build_default_engine`；`server/app.py` `_lifespan` finally 调 `shutdown_all_managers()`（Windows JobObject 路径已有）。
- transport 加固：8MB 单行丢弃；stderr PIPE→logger + 100 行环形缓冲（`/mcp logs <id>`）；错误人话化（spawn ENOENT→「命令不存在」等，仿 `mcp_init_error_display`）。
- env 契约（对齐 Codex，**不做 ${VAR} 展开**）：`env` 字面 K/V + `env_vars:["名字"]` 白名单继承进程环境 + `bearer_token_env_var` 按名引用；`env_mode:"scrub"（默认，现 sanitize_env）| "minimal"`（env_clear+allowlist）。

### F2 工具目录·逐工具可见性（P0）

- `tools/meta.py` 增 `exposure: Literal["normal","hidden"]="normal"`；`ToolRegistry.schemas()` 过滤 hidden（**仍可 dispatch**）；attach 后失效 `_schemas_cache`。
- MCP 可见性三层：①GUI 勾选 `enabled_tools`；②工具 `_meta.ui.visibility` 不含 "model" → hidden（`tool_is_model_visible` 语义）；③cap 32（env `XEYO_MCP_TOOL_MAX_VISIBLE`）+ 单工具 spec 8KB/服务总量 64KB 超限 → hidden，`/mcp` 标注。
- 名长 >128B 截断加后缀（现 12hex 命名保留）。
- per-tool `output_token_limits`（config）→ MCP 工具实例属性，`_apply_output_budget` 优先读实例覆盖。
- **原生工具面 = 会话起点快照**：attach 时按当时勾选状态决定哪些 MCP 工具进 schemas；此后 tools 数组会话内冻结（动态性见 F2.5）；网关工具 `Mcp{action:list|describe|call}` 在扩展开启时始终注册。

### F2.5 可见性即时生效——「会话快照 + 活页增量」，tools 数组绝对冻结（P0）

**铁律：会话内 `tools` 数组永不变更**（前缀缓存是最长公共前缀语义，tools 变更=全前缀重算，禁止发生）。动态性只走两个零破坏通道：**工具结果**（历史追加，缓存安全）与 **T_now 尾部**（每轮本就重算）；「向历史追加目录块」被 AGENTS.md 红线否决（易变上下文不回写历史）。

- **原生面 = 会话起点快照**：会话建立时按当时勾选/启用状态生成 MCP 工具 schema 与技能图书目录，本会话内不变（`_schemas_cache` 会话内永不失效）。
- **会话内勾选/启停变化即时生效但不碰数组**：
  - 新增 → manager allowlist 即时更新 + **单轮 T_now 活页块** `# 工具面变更（background only）：+fs.read_file（一句话描述）` / `# 技能目录变更（background only）：+react-doctor（一句话）`（仿 Codex `McpStartupUpdateEvent`；仿 repeat_guard 的模块级 advice 消费模式）；
  - MCP 新增工具经**网关工具 `Mcp{action: list|describe|call}`**（静态 schema ~150 token，扩展开启即常驻注册）立即可用：`describe` 取参数 schema（进历史一次性），`call` 走既有权限三态；
  - 移除 → 原生 schema 保留但**权限门 DENY**（提示「该工具已被用户停用」）；技能禁用 → 加载路径校验 `enabled` 拒绝；
  - `Skill{action:"list", query}` 对会话内新增/存量技能全量可查（工具结果通道）。
- reconcile **push 为主、pull 兜底**：server 进程内写 settings 的代码路径（`set_mcp_enabled`/`set_skill_enabled`/`/v1/extensions/settings` POST）在原子写后**直接调用 apply**（更新 allowlist/门控集 + 发布单轮 T_now 活页块，内存即时生效，绕过文件时序）；请求入口 digest 对比（settings mtime 缓存）仅作跨进程/CLI 兜底（部分文件系统 mtime 粒度 ~1s，同秒写可能漏检——故 pull 不可为唯一通道）。动作**永不触碰 `_schemas_cache`**。
- 下一会话按新勾选状态重塑原生面（`/mcp` 面板显示「本会话生效状态 vs 下会话原生面」）。
- 边界：hidden/DENY ≠ 注销（在途调用正常完成）；总开关中途关 → 下一请求 MCP 全部门控 DENY + 网关 list 返回空 + T_now 通知；CLI/TUI/GUI 均自然生效（同一请求入口）。

### F3 权限·审批·deny 闭环（P0）

- `permissions/policy.py`：`evaluate_policy(..., tool: Tool | None = None)` 加参；impl unknown 兜底**前**加 `mcp__` 分支：企业 deny → DENY；`tool_policies`（`always_allow`/`outbound_ask`/`ui_ask`）→ ALLOW/ASK。外层 grant store / 远程会话 / worker / `permission_mode=always` 守卫不动。传 tool 的调用点：`tool_registry.run`、`engine/query_loop.py:125`（`registry.get(name)`）；`permissions/gate.py` 保持 None（保守 ASK）。
- 企业策略 `~/.xeyo/policy.json`（env `XEYO_ENTERPRISE_POLICY` 覆盖路径）：`{"mcp_server_deny":[id]，"mcp_tool_deny":["server/raw"|"server/*"]，"skill_deny":[name]}`——**deny 最严胜出、下级不可覆盖**；坏 policy → keep-last-good + 审计 `config.invalid`。
- annotations 保守采用：仅 server/manifest 显式 `trust_annotations:true` 时，`readOnlyHint`（且非 destructiveHint）→ 免审可并行；缺省不信 server。
- `McpTool.is_read_only/is_concurrency_safe` 改实例级：manifest `read_only_tools` 显式声明（或 trust_annotations 判定）→ True → readonly_gate / Plan 模式 / `_eligible_for_early` 自动生效。

### F4 Skill 图书目录（P0）

`extension/skill_loader.py`：

- **fail-closed frontmatter**：`name/description/tags/model_hint/paths/model_invocable/user_invocable/mcp_dependencies` 类型校验，坏值丢整个 skill → broken-but-listed 条目 `{name, broken:true, reason}`（进名册不进目录/不进加载）。
- **行向修复**（移植 `repair_frontmatter_scalar_fields`）：YAML 解析失败后仅对「值含 `: ` 分隔符或 flow 符（`[{@\``）的裸标量行」加单引号重试，其余错误照抛。
- 双 flag 缺省 true/true；`paths` 解析为 tuple（纯元数据）；3s TTL + digest（names+descs+序）跳过重扫；`discover_skills_report()` 返回 `(entries, suppressed_conflicts)`。

`tools/skill_tool/skill_tool.py`：

- schema 内嵌**图书目录**（§2 决策 1：desc≤120、总≤2400、`model_invocable:true` 才列、来源标注）+ 一句用法说明（「任务匹配描述或用户点名 → 必须先读 SKILL.md 全文再动手」，Codex 触发规则同款）。
- `action:"list"`（可选 `query`）详情/检索：desc≤500、总≤4k、query 子串过滤。
- `args` 可选参数：body 含 `$ARGUMENTS` 则替换，否则追加「## 调用参数」节。
- 结果头带 `(path: <SKILL.md>)`；>12KB 截断尾注 `[truncated; full file: <path> — use Read to continue]`。
- `user_invocable:false` → `/skills` 菜单与 `/v1/skills` 不展示；`model_invocable:false` → 目录不列 + 模型调用返回 `not available for model invocation`。

### F5 提及 + SKILL 声明 MCP 依赖（P1）

- 新建 `extension/mentions.py`：解析用户文本 `$skill-name` / `skill://name`（纯名仅当**全局唯一**，name_counts 歧义防护）→ `InjectContext.skill_mentions` → T_now 块 `# 用户点名技能（background only）`（提示模型调 Skill 工具加载，正文仍走工具进历史）+ 审计 `skill.mentioned`。
- SKILL frontmatter `mcp_dependencies:[server-id]`：Skill 工具加载时经 manager 校验——缺失/未批准 → 结果尾附可操作指引（「/mcp approve X 或检查配置」）；ready → 附「已就绪」。**不自动安装**。
- `agents/*.toml` role `extra` 可声明 `skills`/`mcp_servers` 作子代理 spawn 提示（只展示不放权）。

### F6 内容融合（P0）

- `_result_from_mcp_call` 升级：`image` 块 → `ToolResult.images`（data URL；受 `apply_read_vision` 能力开关约束，关时降级占位文本）；`resource` 块 → spill 落盘 + 路径引用；文本维持现状。
- **resources 走网关单入口**（修正：不设独立内建工具，避免与网关双入口冲突）：`Mcp` 网关 action 扩展 `resources`（分页列 `resources/list`）与 `read_resource`（按 uri 读）；`read_path` 级策略（只读）；subagent 不可达（网关本身 `subagent_ok=False`）。

### F7 elicitation → AskUserQuestion（P1，末位）

- `McpStdioClient._request` 循环补 server→client **request** 处理：`elicitation/create` → per-server `elicit` 开关（**默认 false = 自动拒绝**，fail-closed）→ 复用 `ask_store.create()` 挂起（同 AskUserQuestion 面板/resume 链路）→ 应答回 JSON-RPC result。
- **挂起期间暂停该调用超时计时**（Codex `ElicitationPauseState` 语义：deadline 改「剩余时间」模型）。
- 审计 `mcp.elicit`。

### F8 治理·供应链·GUI（P1）

- **信任链**：project scope server 首次 spawn 前 `/mcp approve`（信任存 `~/.xeyo/mcp-trust.json` 按声明 hash；声明变更 → 回 unapproved）；user/plugin scope 免批。**P0a 实施记录**：信任文件已先行落地为 workspace 级 `<ws>/.xeyo/mcp-trust.json`（user 级 `~/.xeyo/mcp-trust.json` 兜底），键 = `{declaration_hash: {"approved": true}}`；`/mcp approve` 手势与 GUI 面板仍属 P1。
- **状态机**：`declared|unapproved|denied|broken|starting|ready|failed|stopped`；`LoadedPlugin` 增 `error` 字段（`is_active = enabled && error is None`）→ **broken-but-listed** 进名册。
- **slash**：`/mcp`（状态+tools+enable/disable+勾选回显+reload/approve/logs）、`/skills`（enable/disable/doctor：lockfile drift+冲突+broken）；`registry.py` usage 更新后跑 `py -3.11 -m slash.export_manifest`。
- **API**：`GET /v1/mcp`（状态+工具+脱敏 env 键名）、`POST /v1/mcp/op`（approve/enable/disable/reload）、`GET/POST /v1/extensions/settings`（开关+enabled_tools 写入）、`GET /v1/skills` 加字段（enabled/model_invocable/user_invocable/paths + broken[]/conflicts[]，向后兼容）。
- **config.py**：`write_settings` 原子写（temp+`os.replace`+写前 re-read 合并）；增 `set_skill_enabled`/`set_mcp_enabled`；`extension.config.changed` 审计。
- **供应链**：`/skills install github:<owner>/<repo>[@ref]|path`（`git clone --depth 1` + **剥 17 个具名 GIT_* 变量** + `GIT_OPTIONAL_LOCKS=0` + `-c safe.bareRepository=explicit`；同名已存在一律拒绝；lockfile `skill_store.install` hash 固定）、`update`（hash 对比报漂移）、`remove`（`entry_owner` 归属校验）。
- **插件 prompts**：T_now 块 `# 插件提示（plugin prompts，background only）`——启用插件 prompt 文件按名拼接、`T_NOW_EXTRA_BUDGET` 截断、3s TTL。
- **GUI**：`api/mcp.ts`+`api/extensions.ts`；`McpPanel.tsx`（server 状态徽标 + **逐工具 checkbox** + approve/enable 按钮）；技能菜单加 broken/冲突/user-only 徽标。

## 6. 落地文件清单

**新建**：`python/extension/mcp_manager.py`、`python/extension/mcp_scopes.py`（scopes+trust+deny）、`python/extension/mentions.py`、`python/server/routers/mcp.py`、`python/server/routers/extensions.py`、`gui/src/lib/api/mcp.ts`、`gui/src/lib/api/extensions.ts`、`gui/src/components/McpPanel.tsx`。

**修改**：`python/extension/{config,skill_loader,skill_store,mcp_client,loader}.py`、`python/permissions/policy.py`、`python/tools/{tool_registry,meta}.py`、`python/tools/skill_tool/{skill_tool,prompt}.py`、`python/tools/catalog.py`（McpResource 注册位）、`python/engine/query_loop.py`、`python/engine/query_engine.py`、`python/server/{app,session_pool}.py`、`python/server/routers/skills.py`、`python/prompt/pre_llm_inject.py`、`python/slash/{dispatch,registry}.py`、`gui/src/lib/api/skills.ts`、`gui/src/components/ComposerQuickMenu.tsx`、`AGENTS.md`（扩展层节补契约）。

**收尾**：`py -3.11 -m slash.export_manifest` 提交 `*/generated/slashManifest.ts`。

## 7. 配置契约（冻结）

```jsonc
// <ws>/.xeyo/mcp.json（project，需 approve）或 ~/.xeyo/mcp.json（user）
{"servers": {"fs": {
  "command": "npx", "args": [], "env": {}, "env_vars": ["NODE_EXTRA_CA_CERTS"],
  "bearer_token_env_var": "FS_TOKEN",          // 密钥按名引用，不落盘；无 ${VAR} 展开
  "env_mode": "scrub|minimal",                  // 默认 scrub
  "auto_start": true, "required": false,
  "elicit": false, "trust_annotations": false,
  "startup_timeout_sec": 30, "tool_timeout_sec": 300,
  "tools_policy": "outbound_ask",               // always_allow|outbound_ask|ui_ask
  "tool_policies": {"raw_name": "always_allow"},
  "read_only_tools": ["raw_name"],              // 实例级 is_read_only（或 trust_annotations 判定）
  "enabled_tools": null,                        // null=全部；GUI 勾选后写显式表
  "output_token_limits": {"raw_name": 4000}
}}}

// ~/.xeyo/policy.json（企业 deny，最严胜出，下级不可覆盖）
{"mcp_server_deny": [], "mcp_tool_deny": ["server/raw", "server/*"], "skill_deny": []}

// .xeyo/settings.json 增量（现有结构内）
// skills.{name}: {"enabled": true}
// mcp_servers.{id}: {"enabled": true, "auto_start": true, "enabled_tools": null}

// SKILL.md frontmatter 增量
// model_invocable / user_invocable (bool, 默认 true)
// paths (csv/列表, 元数据) / mcp_dependencies (server-id 列表)
```

## 8. 影响评估（已确认）

- **KV/上下文**：目录快照常驻 ~200–350 token（10 技能），硬顶 2400 字符封死劣质 description；MCP 原生面 = 会话起点快照 + 网关工具 ~150 token；**会话内 tools 数组冻结，零前缀重缓存**；会话内勾选/启停走 T_now 活页块（单轮尾部）+ 网关/门控，无任何数组变更；正文仍按需进历史。
- **性能**：扩展关 = 每会话 +1 次读盘（~0.5ms）；开 = 首会话每启用 server spawn 1–3s（npx 冷启动最坏 30s；`auto_start:false` 缓解；P1 可加工具目录缓存）；技能发现 3s TTL 净赚（现状每次调用全量扫盘）。
- **实用性**：目录常驻恢复模型主动匹配；用户手势（菜单/`$name`//skills）全档可用；单旗子无漂移。
- **效果指标**：e2e（启用→勾选→调用→ASK→审计）；`/v1/mcp` 延迟/计数；目录 ≤2400 断言；deny/broken/drift 可测；总开关关 = 零残留。

## 9. 实施阶段

1. **P0a（地基与闭环，独立可交付）**：F1 全部 + F3 全部 + F4 全部 + F6a（image/resource spill，原生路径）。交付语义 = 方案二主路径（会话前勾选原生面完整可用；会话中改勾选→下会话生效）。出口：e2e 主链绿 + 无网关路径零回归。**实施注记**：P0a 无 exposure 列/网关，「未勾选工具不进 schemas 但保留注册」（§2 决策 4）暂以**不注册**表达（原生面由勾选决定，幻觉调用落 unknown tool，同样 fail-safe）；hidden-but-dispatchable 语义由 P0b exposure 列补齐（**已补齐**，见下方 P0b 实施注记）。
2. **P0b（动态层，全部新风险集中此批）**：F2（exposure+网关 `Mcp{action:list|describe|call|resources|read_resource}`）+ F2.5（push 为主 reconcile+活页块+冻结不变量测试）+ 指纹体系（v2）+ F6b（resources 网关化）+ 最小控制路径（`/v1/extensions/settings` + `/mcp enable|disable|tool` 最小版，GUI 完整面板留 P1）。出口：指纹测试组全绿 + 冻结不变量 + 活页块幂等。

   **P0b 实施注记（已交付，落地映射）：**

   - **指纹 v2**：`permissions/store.py`（`mcp_grant_fingerprint` = `v2:` + sha256(`["mcp-tool", 注册名]`)[:32]；参数不进指纹 → 注入免疫；`mcp_target` 贯通 `PolicyDecision → 挂起项 → /v1/permission/resolve` 落库，网关与原生路径**同一身份**；v1 纯 `matched_rule` 授权结构上无法匹配 v2）。测试：`tests/test_mcp_fingerprint_v2.py`。
   - **exposure 列**：`tools/meta.py`（`ToolMeta.exposure` + `exposure_of`）、`tools/tool_registry.py`（`schemas()` 过滤 hidden，**保留注册**；`_apply_output_budget` 实例级 `output_budget` 优先）、`extension/mcp_client.py`（`McpTool.exposure`/`enabled_probe`/`output_budget`；名长 ≤128B 截断；`tool_is_model_visible`）、`extension/mcp_manager.py`（三层可见性：①勾选→hidden ②`_meta.ui.visibility` ③cap 32（env `XEYO_MCP_TOOL_MAX_VISIBLE`）+ 单工具 8KB + 每 server 64KB）。P0a 的「不注册」语义废止：未勾选 = hidden-but-registered（幻觉调用走权限 ASK）。测试：`tests/extension/test_mcp_exposure.py`。
   - **网关 `Mcp`**：`extension/mcp_gateway.py`（静态 schema ~150 token，扩展开启即常驻；`list`=全量含 hidden 标注、`describe`=入参 schema、`call`=已知工具集解析→目标三态（未知 fail-closed DENY）、`resources`/`read_resource`=F6b 只读网关化；`output_budget=0` 自带 4k 截断；子代理注册表静态工厂 → 天然不可达）。策略分支：`permissions/policy.py::_evaluate_mcp_gateway`（list/describe/resources→meta 放行；read_resource→`mcp_gateway_read`；call→目标身份三态+企业 deny+停用门）。测试：`tests/extension/test_mcp_gateway.py`。
   - **F2.5 reconcile**：`extension/reconcile.py`（push 活页块队列 + digest 幂等；`# 工具面变更`/`# 技能目录变更` 两类，`prompt/pre_llm_inject.py` 预算截断后强挂、子代理不继承）；`extension/config.py`（`write_settings` 原子写 temp+`os.replace`；`set_mcp_enabled`/`set_skill_enabled`/`set_extensions_enabled` 变化才发布）；pull 兜底 = `enabled_probe`（settings+mcp.json 双级 (mtime,size) 签名缓存重读）→ **移除→DENY 门**（`permissions/policy.py` 两分支，先于 grant，用户停用不可穿越）；skill 拒载区分文案（`tools/skill_tool/skill_tool.py::_disabled_now` 双发现对比，broken 不误报）。测试：`tests/extension/test_reconcile.py`。
   - **F6b**：`McpStdioClient.list_resources/read_resource`（JSON-RPC `resources/list|read`，server 不支持 → 网关转 error 结果）。
   - **最小控制路径**：`server/routers/extensions.py`（`GET/POST /v1/extensions/settings`，loopback 门禁，POST=push reconcile）+ `/mcp enable|disable|tool`（`slash/dispatch.py`；`tool` 回写声明 mcp.json，`enabled_tools` 缺省全量从运行中 client 枚举）。manifest 已重导出。
   - **验收件**：冻结不变量（会话内启停/重复 attach → `schemas()` 逐字节不变，执行侧探针即时 DENY）+ 活页块幂等（同值零块；A→B→A 各一块）→ `tests/extension/test_freeze_invariants.py`；全量回归脚本 `run-pytest-p0b.bat`（用户手动执行）。

   - **P0b 验收存证（本会话，§9.2 落地核定）：**
     - **测试全绿**：`test_mcp_exposure` 10 / `test_mcp_gateway` 12 / `test_mcp_fingerprint_v2` 18（≥设计 14）/ `test_reconcile` 10 / `test_freeze_invariants` 4 / `test_extensions_api` 6 / `test_blob_gc` 12 / `test_skills_api` 4 / `test_pre_llm_inject` 18 / `test_slash` 14 —— 全部 `-q -p no:cacheprovider --no-header` 通过。
     - **全量回归**：`run_p0b_tail_batches.py --all`（205 文件 → 21 批独立、无缓冲、无窗口）跑完，**1764 tests / 8 fail / 4 skip**；无“进程中途消失”死亡点。
     - **8 红归属（均非 P0b，对照 P0a 基线 `62b720c` 核实）**：① `test_simple_functionality` ×5（`get_tool`/`is_aborted`/Message 下标等在基线即不存在）——既有陈旧冒烟测试；② `test_web_tools::test_web_concurrency_safe`——既有；③ `test_rewind_service::test_execute_blocks_when_external_file_change_is_detected`——既有 WIP 红；④ `test_nightshift::test_promote_rate_limit_caps_per_run`（NameError）——**未提交 WIP**（`test_nightshift.py` 工作树增测的导入遗漏）。
     - **红线**：对账块仅注入 `pre_llm_inject`（`system_prompt.py` 0 处）；密钥按名引用；P0b 变更文件无新增三方依赖（仅既有 `fastapi/httpx/pydantic`）。
     - **落地判定**：P0b 零回归，可合。提交链 `4413023`→`e5beaee`→`1762f13`→`91b770e`→`c565253`→`5488633`→`762abbb`→`ff90ad6`（主提交 `4413023`=30 文件，其余为 AGENTS.md/fingerprint 测试/回归工具跟进，作用域均验证；之外 WIP 未提交）。
     - **工具**：`run_p0b_tail_batches.py`（默认=98 文件尾部清单；`--all`=全量 205 文件分批；`--tail` 显式）＋ `run-pytest-p0b-tail.vbs`（零窗口全静默启动）。
     - **遗留（非 P0b，单列）**：既有 `test_simple_functionality`/`test_web_tools` 测试债；`test_nightshift` 增测属未提交 WIP，交由该 owner 收尾。
3. **P1**：F5 提及/依赖 + F8 治理面（信任链/状态机/GUI/供应链/prompts/settings 原子写）。
4. **P1（末位）**：F7 elicitation（默认关）。
5. **收尾**：文档（AGENTS.md 扩展层节）+ slash manifest 导出。

## 10. 测试与验收（P0 即须全绿）

- manager/scopes：扩展关零 spawn；三来源优先级；身份复用/变更重连；trust 流（未批准不 spawn→approve→spawn→hash 变更回退）；deny 三层；required 失败→会话照常+警告块；env 白名单（无 ${VAR}）；8MB 行丢弃；stderr 环形。
- 权限：mcp 三态（always_allow→ALLOW/outbound_ask→ASK/grant 命中→ALLOW/deny→DENY）；实例 read_only 进 readonly_gate 与 `_eligible_for_early`；无 coordinator ASK→DENY。
- 目录：≤2400+desc≤120+model_invocable 过滤断言（schema 永不含超限目录）；list/query 4k 硬顶；fail-closed+行向修复样例；双 flag 拒绝路径。
- 勾选：enabled_tools 写读回环；hidden 不进 schemas 但 dispatch 走 ASK。
- 内容：image→images（vision 关降级）；resource→spill；McpResourceList/Read。
- **P0b 追加**：指纹 v2 组（`tests/test_mcp_fingerprint_v2.py`，冻结 6 项：同工具异参同纹/异工具异纹/参数欺骗不迁移/授权回环/拒绝优先/版本隔离）；exposure 三层+cap/尺寸/名长截断（`tests/extension/test_mcp_exposure.py`）；网关五动作+fail-closed+grant 统一身份+企业 deny 按目标（`tests/extension/test_mcp_gateway.py`）；reconcile push/pull+DENY 门+skill 拒载文案（`tests/extension/test_reconcile.py`）；冻结不变量+活页块幂等（`tests/extension/test_freeze_invariants.py`）；控制路径 API+slash（`tests/test_extensions_api.py`）。
- 路由/GUI api 合同；全量 `run-pytest-baseline.bat`；**不新增第三方依赖**。

## 11. 非目标（P2 留档）

HTTP/SSE transport 与 OAuth（`McpTransport` Protocol 已是接缝、manifest `transport` 字段预留；OAuth 要点已记录：issuer origin 绑定校验、刷新排他锁防 token 重放、提前 30s 刷新、三级存储回退）；MCP prompts 协议（Codex 客户端也未实现）；resources subscribe；ToolExposure 六态与 bm25 tool_search（仅取 normal/hidden）；skill `allowed-tools` 硬门控（需会话级激活状态机）；hooks 系统；市场白名单执行器；skill 文件系统 watch（TTL 轮询够用）。

## 12. 红线（实施全程有效，摘自 AGENTS.md）

- 提示走 T_now 投影，绝不写 system 左段或 XEYO.md；T_now 块带归属声明头。
- skill 内容（正文）只走 Skill 工具按需加载；目录索引属元数据可进 schema。
- MCP 动态工具必经 `ToolRegistry.run` 权限三态，默认 `outbound_ask`；`always_allow` 仅显式声明；deny 最严胜出。
- 同名 skill 默认禁止插件覆盖（workspace>home>plugin）；坏 manifest/settings 跳过并记录（broken-but-listed），不搞挂启动。
- 密钥永不落盘明文（按名引用环境变量）。

## 13. 方案二已知缺点清单（用户选定方案，代价存档）

1. **语义分叉**：同一勾选三种效果（会话前=原生 schema；会话中新增=仅网关；会话中移除=可见但 DENY）。
2. **移除工具的可见但拒绝窗口**：数组冻结 → 被移除 schema 会话内持续可见；模型可能反复尝试，每次=浪费往返+DENY 结果永久进历史；仅能靠 DENY 文案+repeat guard 压低，无法归零。
3. **会话内新增是二等公民**：list→describe→call 多跳；失去 provider 级参数校验（畸形调用率升）；describe 结果可被 compaction 压缩需重取；通用网关 action 的预训练可靠性低于原生 function-calling。
4. **T_now 活页块新鲜度衰减**：单轮通知未被接住即遗忘，动态工具注意力二等；周期重注入与「历史干净/预算」冲突，结构性弱点。
5. **「会话起点」非单一点**：engine 重建（模型/配置变化）=隐式重快照=数组变化炸前缀；须显式规则「快照绑定 registry 实例，重建即重快照（等价今天模型切换的既有代价）」。
6. **grant store 指纹重定义**：网关模式下指纹必须 hash(action=call, server, raw_tool, args)，防「always allow」跨工具误匹配（过放=安全事故）；新优先级规则：用户取消勾选的 DENY 压过 grant store。
7. **网关常驻税**：`Mcp` ~150 token 永久常驻 + 工具选择噪音；不可按需注册（出现/消失即数组变更）。
8. **一致性面 1→3 份**：快照/allowlist/DENY 门三源合一；`/mcp` 面板三种状态；测试矩阵组合扩大（快照×网关×门控×重建×总开关×跨会话）。
9. **GUI 工具卡适配**：网关调用 name=`Mcp`，前端需网关卡（从 input 抽 server/tool），否则会话内新增工具 UI 退化通用卡。

缓解已在 F2.5/F3 落地：DENY 文案、repeat guard、活页块带一句话描述、重建重快照显式规则、指纹新方案单测覆盖。结构项（1–4）接受为冻结前缀的固有价格；工程项（5/6/8/9）P0/P1 一次性做对收敛；7 可忽略。

## 14. 结构缺点 1–4 的风险控制（可落地手段）

| 缺点 | 控制手段 |
|---|---|
| 1 语义分叉 | system 左段 `TOOL_POLICY`（静态前缀，零增量）加一句永久契约：「工具/技能可用性由用户实时管理；被停用的会明确拒绝并指引替代；会话中新增能力经 `Mcp` 网关出现」；DENY 文案、活页块、`/mcp` 面板共用同一套状态词汇（原生/网关/停用），拒绝文案永远带替代指引 |
| 2 可见但拒绝窗口 | DENY 结果计入 repeat_guard（既有设施）：同一被停用工具 3/5/8 次递进 T_now 提醒，末档升格「请勿再调用，改用 Mcp{action:'list'}」；DENY 文案一行化（最小历史成本）；面板明示「已停用（本会话仍占位，下会话移除）」+「重建会话」按钮作为硬移除出口 |
| 3 新增工具二等公民 | 活页块**内联 schema**（序列化 ≤1KB 的工具直接跳过 describe）；`call` 服务端先按缓存 schema 校验 args，失败时错误**附带完整 schema**（一轮自愈，compaction 后同理）；list 结果含一句话描述，简单工具可跳过 describe；validate 前移补齐 provider 校验缺位 |
| 4 活页块新鲜度衰减 | 网关 description（静态、永不衰减）写明「用户可能随时启停工具；需要的能力不在工具集中时调 Mcp{action:'list'}」——**静态前缀里的永久指针指向动态通道**；事件驱动重注入：调用被停用/未知工具且 allowlist 有网关等价物时自动发一条 T_now 提示；活页块走 AGENTS.md「开关类块」通道（`_trim_blocks_to_budget` 之后追加），不被其他块挤掉 |

## 15. 计划自身缺点（复查结论）

1. **网关指纹规范化是全计划安全最集中单点**：args canonicalization（键序/嵌套/类型）做错即过放；须独立规范+独立测试组（§13.6）。
2. **三层技能信息（快照目录/活页块/list）一致性**：单一真相源 = `skill_loader` 实时发现态，快照与活页块均为其投影；digest 错位 = 新 bug 类别，需对账测试。
3. **required 失败与缺点 2 同构**：required 服务挂掉后其快照工具变 DENY 循环候选，走 repeat_guard 缓解。
4. **审计聚合退化**：网关调用 name=`Mcp`，per-MCP-tool 统计靠 input 解析——审计 metadata 必须显式带 `server/raw_tool`（硬要求，非可选项）。
5. **测试量 ≈ 代码量 1.5 倍**（§10 + §13.8 矩阵），排期须按此预期。
6. **P0 偏大 → 切分**：**P0a** = F1+F3+F4（端到端打通；勾选跨会话生效，无网关无活页）；**P0b** = F2+F2.5+F6（网关+活页+即时性+内容融合）。每块独立验收，review 面减半。

### 各缺点的控制手段（已冻结）

| 缺点 | 控制手段 |
|---|---|
| 1 网关指纹 | ①身份与参数分离：指纹=调用点身份 `("mcp", server_id, raw_tool)` 结构化哈希，**绝不从 args 读 server/tool**（注入免疫）；②`canonical_args` 纯函数规范先行（`json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=True)`）；③指纹带版本号 `(v2, hash)`，变更不静默复用旧授权；④独立测试组：同工具异 args 同指纹/异工具异指纹/args 伪装字段不迁移/grant 回环/deny 压过 grant/版本隔离 |
| 2 三层技能一致性 | 快照/活页/list 均为同一 `render_catalog(entries)` 的投影（禁独立渲染路径）；活页块唯一发布器（reconcile）按 digest 迁移幂等；对账不变量测试：`快照+累积 diff == list 全量` |
| 3 required 失败 | **根治**：required 启动失败 → 其工具不进快照（模型不见即无循环）；退避重连恢复后 allowlist 翻转 + T_now 通知；「可见但 DENY」仅保留给用户会话内主动移除一种情况 |
| 4 审计聚合 | dispatcher resolve 时写审计 metadata 硬字段（server/raw_tool/gateway_action/duration_ms/is_error），**写入端保证，不靠读端解析**；usage 同点递增 per (server,tool)；GUI 网关卡与审计共用同一身份解析 helper；测试覆盖 ALLOW/ASK/DENY 三结果字段齐全 |
| 5 测试量 | 金字塔：纯函数单测打底；三源状态机表驱动转移测试（非笛卡尔积）；**fake MCP server**（进程内 JSON-RPC stub，扩展现有 T11 基建）；e2e 仅三条主链（启用→调用→审计 / 勾选→活页→网关 / 总开关关零残留）；**冻结不变量测试（全计划最重要）**：会话中随意改 settings，断言 `schemas()` 输出逐字节不变 |
| 6 P0 切分 | P0a 出口：e2e 主链绿+无网关零回归；P0b 出口：指纹测试组全绿+冻结不变量+活页块幂等 |

## 16. 插件安装 / 分发 / 市场 + 生命周期钩子（P0 旁路，默认关）

依据本会话「给 XEYO 加入插件系统（安装/分发/市场 + 钩子）+ 后端优先 + 旁路验证」，在既有 `extension/` 插件层（manifest/发现/启停/MCP+skills 接线）之上补齐两块，全部**默认关**（`enabled_extensions` 主开关 + `plugin_market`/`hooks.__master__` 子开关）。

### 16.1 安装 / 分发 / 市场

- **lockfile**：`extension/plugin_store.py` —— `<ws>/.xeyo/plugins-lock.json`（同 `skill_store` 范式，4 字段+目录级 `computedHash`+`installedAt`；`install` 同名拒绝/`update` 重拉/`remove` 归属校验/`detect_drift` 漂移）。
- **fetcher**：`extension/plugin_fetcher.py` —— 本地路径 / `github:owner/repo[@ref]` 安装；**供应链防线**（git 在 `<ws>/.xeyo/.plugin-stage/` 暂存目录执行、剥仓库级 `GIT_*` + `GIT_OPTIONAL_LOCKS=0` + `-c safe.bareRepository=explicit`、校验 manifest+`min_xeyo` 通过才复制进插件根、失败清暂存）。npm（默认关，P2）。
- **信任（fail-closed）**：远程源默认未受信（`plugin-trust.json` 需 `approved` 才激活）；`discover_plugins` 加信任门（未受信远程插件视为禁用，不进 MCP/skills/hooks）；本地源免批。
- **市场 / 白名单**：`GET /v1/plugins/market`（`<home>/plugin-market.json` registry + 企业 `plugin_market_allow` 白名单过滤 + `plugin_deny` 一票否决）；`plugin_market` 子开关默认关。
- **控制路径**：`server/routers/plugins.py`（`GET /v1/plugins` / `POST install|update|remove` / `GET market`，loopback 门禁）+ `/plugins install|update|remove`（`slash/dispatch.py`）；manifest 已重导出。
- **旁路**：全部操作要求 `enabled_extensions` 开（否则 fail-closed）；`plugin_market` 关时市场返回空。

### 16.2 生命周期钩子

- **manifest**：`PluginManifest.hooks: list[HookSpec]`（`{event, command, args, timeout_s, fail_policy}`，command 相对插件根禁越界）；`_at_least_one` 允许仅 hooks 成插件。
- **执行器**：`extension/hooks.py` —— 事件 `PreToolUse/PostToolUse/PermissionRequest/SessionStart/SessionEnd`；子进程、短超时、**三分结果**（Success/FailedContinue/FailedAbort，超时归 FailedAbort）；`PermissionRequest` 任一非 Success → fail-closed DENY；`hooks_enabled()`（主开关 && `__master__`）关时零执行零注入。
- **接线（巨石仅留调点）**：`tools/tool_registry.py` —— PreToolUse 门（abort → 短路工具，不进入权限/执行）、PermissionRequest 门（fail-closed）、PostToolUse 观测（只注入不改结果）。上下文块经 `reconcile.publish_reconcile_block` 发布，由 `pre_llm_inject.py` F2.5 的 `consume_reconcile_blocks` 注入（**复用既有 `# block: reconcile_events` 登记，不新增 T_now 块**，遵守登记数硬顶）。
- **契约测试**：`tests/plugin/test_plugin_store.py` / `test_plugin_fetcher.py` / `test_config_market.py` / `test_hooks.py` / `test_tool_gate_hooks.py` + `tests/test_plugins_api.py`。
- **验收**：`run-pytest-p0b.bat`（P0）+ `tsc` + `vitest` 全绿；全开关默认关零行为。
