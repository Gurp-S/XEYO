# XEYO 项目级说明

仓库结构：`gui/`（React+TS 前端，Tauri 壳）、`tui/`（Ink 终端 UI）、`python/`（engine + FastAPI server + Typer CLI）。

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

**注入声道（方案 A 环境声道，2026-09-04）：** 默认策略 `env_channel`（`python/prompt/t_now_strategy.py`）——全部易变块装进一对**仅存在于投影**的伪造 tool 对（`assistant(xeyo_env_notice) → tool_result`，`turn_context.append_env_notice_pair`）尾插，不进 MessageStore/JSONL、不进 tools 数组（schemas 冻结红线不受影响）、尾部追加 KV 前缀逐字节不动。tool_result 是模型训练出的"环境声道"，注入内容与用户意图在消息结构上隔离（根治说话人混淆型注意力漂移）。回退档 `legacy` = 原行为（bg_wrap 身份标记 + 尾插末条 user，A1 分仓仍生效）；运行时 env_channel 被厂商以结构类 4xx（400/404/413/415/422）拒绝且未吐 chunk 时，自动记进程级备忘并当场以 legacy 重建重试。策略优先级：会话/请求显式（`set_t_now_strategy`）> `XEYO_T_NOW_STRATEGY` 环境变量 > 默认 env_channel；`prefill` 为预留档（实测前回落 env_channel）。

**硬准入（2026-09-04）：** 块登记表 `T_NOW_BLOCK_REGISTRY`（`pre_llm_inject.py`）：每个块一行（类别 / 为什么必须在上下文 / 预算与门控），**登记数硬顶 20**，加一块必须删一块或证明预算不破；所有 `tagged.append` 装配点必须带 `# block: <名>` 标记且与登记表一一对应，由 `tests/test_t_now_block_registry.py` 机器执法——新块不登记，测试即红。第一问永远是"能不能不进上下文"（引擎能强制的，一律不给模型看）。

**现有 T_now 候选（新增前先查重）：** Continue（工具续写）、Ask/Plan 模式指令、Approved Plan（首写收敛 + 实施中指针）、Wrap-up、Runtime budget notice、续跑指令 Resume（投影-only，`engine/resume_directive.py`）、上一轮思考回顾（GUI 设置，默认**关**）、Multi-Agent hint、Repeat guard、Nested XEYO.md（限窗）、stale XEYO.md 提醒、输出精简、写代码精简、MCP required 故障、工具面/技能目录变更（reconcile）、其他会话活动、文件冲突、浏览器预览、审批模式快照、子代理结算、Goal、jobs 补投。最新权威清单以 `T_NOW_BLOCK_REGISTRY` 为准。

**已下线（不再推送 T_now）：** Proposals digest（拉取走 `/proposals` + Memory 候选计数行）、Memory index 块（脚本/评测用）。

## 扩展层（MCP × SKILL）契约

权威口径以 `python/extension/`（`mcp_gateway.py` / `mcp_client.py` / `reconcile.py` / `config.py`）实现与 `tests/extension/test_freeze_invariants.py` 等契约为冻结面（配置、产品决策、实施注记见代码注释）。

- **配置单一来源**：`<root>/.xeyo/settings.json`（后台纯 JSON，无 GUI）。home 级 `~/.xeyo/settings.json` 与工作区级 `<ws>/.xeyo/settings.json` 按范围合并，**workspace 更具体者优先**；总开关 `enabled_extensions`（默认 **关**）；`plugins/skills/mcp_servers` 各带 `{"<name>": {"enabled": true, ...}}`。坏 JSON 走 keep-last-good + `config.invalid` 审计，方向安全（不静默打回默认）。
- **原生工具面 = 会话起点快照**：attach 时按当时启用状态决定哪些 MCP 工具进 `schemas()`；此后 **tools 数组会话内冻结、零前缀重缓存**（绝对红线）。会话内启停**永不触碰 `_schemas_cache`**。
- **会话内新增工具的唯一通道 = `Mcp` 网关工具**（`python/extension/mcp_gateway.py`）：`action=list|describe|call|resources|read_resource`，扩展开启时**始终注册**。list 含 hidden-but-registered 标注；describe 按 (server,tool) 返回入参 schema；call 身份经**已知工具集解析**（`resolve_tool`），绝不从 args 之外的通道取身份。
- **会话内启停 = push 为主 reconcile**（`python/extension/reconcile.py`）：`set_mcp_enabled`/`set_skill_enabled` 后**直接发布**单轮 T_now 活页块（`# 工具面变更`/`# 技能目录变更`），digest 幂等（同值零块）；pull 兜底 = `enabled_probe`。活页块经 `prompt/pre_llm_inject.py` 按类别装配（directive/event/inventory），**事件类静默即失，绝不门控**。
- **停用即时 DENY，不可被 grant 穿越**：`permissions/policy.py` 先于 grant 两分支判定，`移除→DENY` 门。网关**不绕权限**——`registry.run` 的 ASK/DENY 在 `execute` 之前已按目标工具策略裁决；子代理注册表只来自静态工厂，网关天然不可达。
- **指纹 v2（授权身份）**：`permissions/store.py` `mcp_grant_fingerprint = "v2:" + sha256(["mcp-tool", 注册名])[:32]`（**参数不进指纹** → 注入免疫）；`mcp_target` 贯通 `PolicyDecision → 挂起项 → /v1/permission/resolve`。v1 已不匹配 v2。
- **控制路径**：`GET/POST /v1/extensions/settings`（`server/routers/extensions.py`，loopback 门禁，POST=push reconcile）+ `/mcp enable|disable|tool`（`python/slash/dispatch.py`）；manifest 已重导出到 `*/generated/slashManifest.ts`。
- **契约测试（改扩展层必须守）**：`tests/extension/test_freeze_invariants.py`、`tests/extension/test_reconcile.py`、`tests/extension/test_mcp_fingerprint_v2.py`、`tests/extension/test_mcp_gateway.py`、`tests/extension/test_mcp_exposure.py`、`tests/test_extensions_api.py`。
- **扩展层改动验收**：`py -3.11 -m pytest python/tests/extension -m "not live"`（本地手动执行）；无网关路径零回归（P0a 出口）。
