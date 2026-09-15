# XEYO 未开启功能全清单与原因（源码级取证 · 2026-09-10）

> **本文回答两个问题**：XEYO 里**已实现但没开**的功能有哪些？**为什么没开**？
>
> **口径**：全部结论来自直接读源码（`python/` 全仓 + `gui/src/`），每条带 `文件:行号`。**不依赖任何转述**。
> **边界**：只收「已实现但处于关闭态」的功能。**未实现**的能力单列 §7（那是"没写"，不是"没开"）。
> **状态基准**：本文同时标注两件事——① **代码默认值**（新装机器开箱状态）；② **本工作区实际值**（`<repo>/.xeyo/settings.json`）。

---

## §0 一页速览

| 类别 | 数量 | 性质 | 能否由用户打开 |
|---|---|---|---|
| A 已裁决下线 / 证据门未过（恒关） | 7 | **不能**（源码级固化） | ❌ 改源码 + 过证据门 |
| B 默认关，但有明确"开的价值" | 4 | 待验证 / 待补前置机制 | ⚠️ 可开，需前置 |
| C 安全默认（故意关） | 11 | **故意的**（防越权/防误删） | ⚠️ 可开，有风险 |
| D 产品决策默认关 | 9 | 定向场景才需要 | ✅ 可开 |
| E 前端默认关（用户可见） | 10 | 省成本 / 半成品隔离 | ✅ 可开 |
| F 侧挂模块 | 11 已升格开 / **1 真关** | 见 §6（含一处**全仓级更正**） | — |
| G 未实现（不是开关） | 4 | 功能不存在 | — |

---

## §1 A 类：已裁决下线 / 证据门未过 —— **恒关，配置打不开**

这类开关**即使写了 `=1` 也不生效**，因为读点被固化为常量或直接删除。

### A-1 Memory 索引常驻注入 —— 唯一"用户已裁决下线"项 ★

| 项 | 内容 |
|---|---|
| 开关 | `XEYO_MEMORY_INDEX_LIVE` |
| 读点 | `engine/query_loop.py:355-363` → `def _memory_index_live_enabled() -> bool:` **恒 `return False`** |
| 注册 | `memory/memory_switches.py:51`（**保留注册占位**，原文：「本条目仅保留注册占位（authority 面不因下线而少一个已裁决键）」） |
| 为什么没开 | **事故 `sess_mtiche8l`**：弱模型（glm-4.5-air）**把索引条目当任务对象**。2026-09-09 用户裁决维持下线，`AGENTS.md`「已下线」与此对齐。 |
| 打开条件 | **源码级改此函数 + A1（200+ 轮 live）+ A3 过门证据**（`:360-361` 原文） |
| 残留值处理 | 「settings/env 残留一律忽略（同其他固化恒关项）」 |

> 原文摘录（`engine/query_loop.py:356-363`）：
> ```
> """Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。
> 事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
> 与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
> 生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
> 须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。"""
> return False
> ```

### A-2 记忆 v6.1 三个实验参数 —— B1/B2/B3 证据门未过

| 开关 | 状态 | 原因 |
|---|---|---|
| `XEYO_V61_PARETO` | 恒关，**已从注册表删除** | `memory/memory_switches.py:34`：「B1/B2/B3 证据门未过，恒关」 |
| `XEYO_V61_SI` | 同上 | 同上 |
| `XEYO_V61_DYNAMIC_R` | 同上 | 同上 |

删除后只能改源码回退——`save()` 对未知键直接抛错（`memory/memory_switches.py:160-162`：「未知/已删键…一律拒绝，防 GUI/脚本误写回惰性残留」）。

### A-3 已「固化」的 10 个开关 —— 不是关，是**已删且恒开**

`memory/memory_switches.py:32-45` 记录了 2026-09-06 用户决策「v61 默认开启」后**删除**的开关。它们已**固化开启**，回退只能改源码：

| 原开关 | 现状 | 固化点 |
|---|---|---|
| `XEYO_C2_GATE` | 已删，恒 `True` | `memory/l5_flag.py:52-58` `def c2_gate(): return True` |
| `XEYO_C2_PRESSURE_FORMULA` / `_GAIN_` / `_EXTEND_` | 已删 → `_c2_formula_enabled` 恒 True | `memory_switches.py:35-36` |
| `XEYO_MEMORY_SQLITE_INDEX`（A4） | 已删，恒开 | `memory/memindex.py:86` |
| `XEYO_CACHE_COOLDOWN_OMEGA`（A1 ω） | 已删，恒开 | `memory/memindex.py:16` |
| `XEYO_MEMORY_RERANK_PREFERENCE`（⑮） | 已删，`enabled()` **恒 True** | `memory/rerank_preference_shadow.py:47-53` |
| `XEYO_MEMORY_QUERY_REWEIGHT`（F4） | 已删，恒开 | `memory/search.py:98`：「原 XEYO_MEMORY_QUERY_REWEIGHT 键已删」 |
| `XEYO_C2_CITATION`（C2 引用锚点） | 已删，恒开 | `runtime._c2_citation_enabled` |
| `XEYO_C2_ESCAPE_HATCH`（C2 逃生舱） | 已删，恒开 | `runtime._c2_escape_hatch_enabled` |
| `XEYO_MEMORY_RESTORE`（A2 碎片还原） | 已删，恒开 | `memory/runtime.py:810` |
| `XEYO_SESSION_MD_DELTA`（A5 差分重写） | 已删，恒开 | `session_md.deltas_enabled` |

---

## §2 B 类：默认关，但**开了就有明确价值**（本轮重点）

这四个是"已实现 + 默认关 + 收益可述"的候选。**详见配套文档 §8 表格**。

### B-1 `XEYO_C2_LLM_SUMMARY` —— C2 摘要 LLM 旁路（默认 `"0"`）

| 项 | 内容 |
|---|---|
| 位置 | `memory/runtime.py:62-85`；注册 `memory/memory_switches.py:30` |
| 默认 | `"0"`（确定性摘要） |
| **为什么没开（源码原话）** | 「实测**吸收潜力高但输出不稳定**，默认关=确定性摘要」（`memory_switches.py:30`） |
| 开了的收益 | 超长会话压缩摘要由**模型生成强保真要点列表**，替代确定性截断 → 压缩后不丢关键细节 |
| 代价 | **多一次模型调用** |

### B-2 `XEYO_TOOL_OFFLOAD` —— L3 超长工具结果外部化（旁路默认关）

| 项 | 内容 |
|---|---|
| 位置 | `memory/offload.py:8-23`（`_ENV="XEYO_TOOL_OFFLOAD"`，阈值 `XEYO_TOOL_OFFLOAD_CHARS` 默认 128，预览 `XEYO_TOOL_OFFLOAD_PREVIEW` 默认 128） |
| 默认 | 关（旁路） |
| 为什么没开 | 「Link②① 统一 C0/L3 截断：>OFFLOAD_THRESHOLD 的工具结果**直接 offload**（写文件 + 固定预览引用），**不再走 C0 截断**（8192）——避免"先截断又 offload"的双重处理」——切换尚在旁路阶段 |
| 开了的收益 | 超长工具结果不再全量进上下文；**引用文本与文件内容都确定性 → 同消息同 uid 每次生成相同引用 → KV 前缀稳定**（源码明写的红线保证） |

### B-3 `XEYO_TOOL_AGING` —— 工具输出老化（默认 `"0"`）

| 项 | 内容 |
|---|---|
| 位置 | `engine/aging.py:4`、`:43`；注册 `memory/memory_switches.py:31` |
| **为什么没开（源码原话）** | 「**toolout 占位的恢复机制未落地前保持关闭，避免原文不可找回**」（`aging.py:43`） |
| 开了的收益 | 压缩后冻结区仍可按窗口紧追推进；近档留富信息、远档折叠短存根 → 长会话上下文预算显著改善 |
| 前置 | 先落"恢复机制"（`logs/toolout` 文件级恢复为设计文档前置依赖①） |

### B-4 `XEYO_MCP_NAME_MANIFEST` —— MCP 工具 name-manifest 暴露档（默认 `0`）

| 项 | 内容 |
|---|---|
| 位置 | `extension/mcp_name_manifest_shadow.py:13,31,37-42` |
| 为什么没开（源码原话） | 「**需改会话起点冻结快照**，标记「**实测 token 收益后接入**」」（`sidecar/upgrade.py:23-24` 红线） |
| 开了的收益 | 把一个工具的 schema 收缩为 `name + 一句短描述`（丢弃 `inputSchema` 全文）→ **省 token** |
| 前置 | **不可先开**：动它会触碰 `tools 数组会话内绝对冻结 / _schemas_cache 永不失效 / 零前缀重缓存` 三条红线 |

---

## §3 C 类：安全默认（**故意关**，开=放宽权限）

这类"没开"是**设计意图**，不是遗漏。

| # | 开关 | 读点 | 为什么默认关 |
|---|---|---|---|
| C-1 | `XEYO_WORKSPACE_FS_WRITABLE` | `server/workspace_fs.py:37-40`，报错文案 `:210`、`:232` | 旁路直写通道**默认只读**（源码注释：「属安全默认值」）；GUI Explorer 编辑器即时保存依赖它 |
| C-2 | `XEYO_BASH_UNSAFE_ALLOW` | `permissions/policy.py:878` | `bash_mode=="allow"` 时若无它且非 full profile → **自动降回 `default`**（"没有 OS jail 就不给全权"的代码化） |
| C-3 | `XEYO_ALLOW_LAN` | `cli/serve_cmd.py:35` | 默认空 = 不监听局域网 |
| C-4 | `XEYO_ALLOW_REMOTE_CONTROL` | `server/local_gate.py:22`、`:48` | 默认空 = 不许远程控制（loopback 门禁） |
| C-5 | `XEYO_ALLOW_FAKE_MODEL` | `server/deps.py:194` | 默认空 = 生产不许假模型 |
| C-6 | `XEYO_ALLOW_LOCAL_MODEL` | `server/deps.py:180` | 默认空 = 不许本地模型 |
| C-7 | `XEYO_ENTERPRISE_POLICY` | `extension/mcp_scopes.py:206-210` | 默认无企业 deny 策略文件（`~/.xeyo/policy.json`） |
| C-8 | `enabled_extensions` | `extension/config.py:31` | **扩展层总开关，企业级默认关闭**（`:142`「缺省视为关」） |
| C-9 | `plugin_market` | `extension/config.py:32,180` | 插件市场：需总开关 + 市场开关**双开** |
| C-10 | hooks 总开关 | `extension/config.py:184`、`extension/hooks.py:6` | 生命周期钩子：需总开关 + hooks 开关双开，**默认关** |
| C-11 | `XEYO_BLOB_GC_ENABLED` + `XEYO_BLOB_GC_DRY_RUN` | `rewind/blob_gc.py:16`、`:430`；`server/app.py:170` | **三重默认安全**：`enabled=False` + `dry_run=True`（默认 1）+ 未超预算不动手。注释记录**曾漏判 dry_run 导致真删**（已被测试钉死） |

---

## §4 D 类：产品决策默认关（定向场景才需要）

| # | 开关 | 读点 | 为什么默认关（源码原话） |
|---|---|---|---|
| D-1 | `XEYO_WALL_HARD_STOP` | `engine/budget.py:38-43` | 「**默认关（产品会话无墙钟武装 → 行为零变化）**」；`:163`「产品会话即使设了死线（仅时间感播报）也不会被引擎自动武装」 |
| D-2 | `XEYO_BUDGET_DEFAULT_USD` | `engine/budget.py:69` | 旁路默认预算档，「2026-09-09 Phase 1，**默认关**」 |
| D-3 | `XEYO_GOAL_AUTO_CREATE` | `server/routers/chat.py:926-930` | 「**生产默认不自动建 goal**——目标只在用户…」（默认 `"0"`） |
| D-4 | `XEYO_REWIND_FSYNC` | `rewind/journal.py:64-66` | 「**默认关闭**（flush 已保证进程内顺序完整，读端本就容忍 partial line）。审计要求落盘即持久时设 `=1`」 |
| D-5 | `XEYO_REWIND_FULL_TREE` | `rewind/__init__.py:6,27` | 默认 `"0"`；全树恢复较慢，可 `full_tree_restore=true` 按次开 |
| D-6 | `XEYO_PROC_LEDGER` | `engine/process_ledger.py:298,313` | 「旁路便捷入口（`XEYO_PROC_LEDGER` 门控；**默认关，关时零行为差异**）」 |
| D-7 | `XEYO_WEBSEARCH_INCLUDE_DDG` | `tools/web_search_tool/web_search_tool.py:41` | 默认不附带 DuckDuckGo 源 |
| D-8 | `XEYO_AUDIT_LOG` | `audit/log.py:121` | 审计日志**路径覆盖**（默认走 `~/.xeyo` 默认位置，非关闭） |
| D-9 | `XEYO_NO_PREWARM` / `XEYO_PEER_PRESENCE_OFF` / `XEYO_T_NOW_SKIP` / `XEYO_BENCH_MINIMAL` | `server/app.py:52`、`prompt/pre_llm_inject.py:1201-1205`、`:914`、`tools/catalog.py:359` | **反向逃生门**：默认空 = 正常行为；置值才"关掉正常功能"。仅测试/评测/消融用 |

---

## §5 E 类：前端默认关（用户可见）

`gui/src/stores/settingsStore.ts` 的 `DEFAULTS`（`:261-305`）：

| # | 设置 | 默认 | 行号 | 说明 |
|---|---|---|---|---|
| E-1 | `thinking` | `'disabled'` | `:266` | **思考态默认关**（成本考虑：输出占成本 83%） |
| E-2 | `outputCompact` | `false` | `:270` | 输出精简块**默认不注入**（`outputMode:'lite'` 仅在它开启时生效，`:158`） |
| E-3 | `codeCompact` | `false` | `:272` | 写码精简同上 |
| E-4 | `stickyBubbles` | `false` | `:294` | 气泡吸顶；`:803`「**默认关**：气泡留在原位」；`StickyPromptController.ts:80`「默认关，关闭时零吸附」 |
| E-5 | `showExperimental` | `false` | `:304` | 「T32：显示「实验功能」入口（**AgentMap 代码/架构地图等半成品**收进实验菜单）。**默认关闭**——半成品移出主界面 chrome」 |
| E-6 | `rewindFullTreeRestore` | `false` | `:301` | 「**默认关闭**：只恢复本轮 Agent 改过的文件」 |
| E-7 | `xeyoPetEnabled` | `false` | `:298` | 桌宠 ⚠️ **与注释矛盾**：`:218` 注释写「缺失时默认开启」，但 `DEFAULTS` 是 `false` |
| E-8 | `paneEaseSilky` | `false` | `:293` | 侧栏动画用 quintic-out 而非默认 expo-out |
| E-9 | `searxngUrl` | `''` | `:274` | 未配搜索地址 → 搜索能力不可用 |
| E-10 | `profiles` / `activeProfileId` / `maxBudgetUsd` | `[]` / `''` / `''` | `:268,275-276` | 模型档案、预算上限未配 |

---

## §6 F 类：侧挂模块 —— 含一处**全仓级更正** ★

### 6.1 更正：12 个 `*_shadow.py` 里 **10 个实际已升格默认开**

各模块 docstring 写着「**【侧挂模块·默认关】**」，但**那是升格前的旧描述**。实际链路：

- `engine/query_engine.py:1374-1381` 在 `build_default_engine` 里调 `sidecar.upgrade.apply()`
- `sidecar/upgrade.py:47-60` `apply()` 受 `sidemod_promote()` 门控
- `sidecar/policy.py:28-33` **`sidemod_promote()` 默认 `True`**（「用户决策：全部升格（除 ⑫）」）
- 各模块 `enabled()` → `side_enabled(_ENV)` → 未设专用 env → 回落 `sidemod_promote()` = **True**
- 各模块 docstring 已更新为：「**升格后默认开**；专用 env / 全局 promote 可关」

| 模块 | 挂钩点 | 实际状态 | `enabled()` 证据 |
|---|---|---|---|
| `memory/memindex_sig_shadow.py`（⑧.5 内容哈希签名） | memindex notes 表 | **开** | `:52-56` |
| `tools/fileio/content_index_cache_shadow.py`（⑧ trigram 缓存） | `content_index._build_index` | **开** | `:51-55` |
| `memory/eval_cold_memory_shadow.py`（① 冷记忆评测） | `memory.search.search` | **开** | `:41-45` |
| `tools/spill_shadow.py`（⑭ spill tail 建议） | `tools.spill.save_text` | **开** | `:32-36` |
| `prompt/transcript_pointer_shadow.py`（⑬ C2 原始历史指针） | `pre_llm_inject.run_pre_llm_inject` | **开** | `:36-40` |
| `memory/rerank_preference_shadow.py`（⑮ 检索重排偏好） | `memory.search.search` | **开（恒 True）** | `:47-53` |
| `evals/pollution_gate_shadow.py`（环境污染门） | 纯函数 | **开** | `:44-48` |
| `evals/reporting_shadow.py`（报告口径四字段） | 纯函数 | **开** | `:31-35` |
| `evals/strict_env_shadow.py`（严格环境档） | 纯函数 | **开** | `:54-58` |
| `evals/blind_audit_shadow.py`（盲审反作弊） | 纯函数 | **开** | `:76-80` |
| `extension/mcp_name_manifest_shadow.py`（⑫ name-manifest） | — | **关**（真默认关） | `:37-42`：`return False` |

**唯一真默认关的是 ⑫**，且是**明文红线不升格**（`sidecar/upgrade.py:23-24`）。

### 6.2 一键回退

`XEYO_SIDEMOD_PROMOTE=0` → `apply()` 返回 `False`，上述 10 个**全部回退**（全局应急开关，不是单项功能开关）。

---

## §7 G 类：**未实现**（不是"开关没开"）

| # | 缺的能力 | 证据 | 说明 |
|---|---|---|---|
| G-1 | **时间触发型定时任务** | `engine/scheduler.py` 有 `toposort` / `scope_conflicts` / `_break_cycles` / `checkpoint`，**全仓 `crontab|schedule_at|webhook|cron` 零命中** | `scheduler.py` 是**任务 DAG 调度器**（不是死代码，有 14 个消费方文件），但**没有时间轴** |
| G-2 | hooks 三个预留事件 | `extension/hooks.py:3`、`extension/manifest.py:41` | `Subagent*` / `UserPromptSubmit` / `PrePostCompact` **预留但未实现**（现只有 5 个：`PreToolUse` / `PostToolUse` / `PermissionRequest` / `SessionStart` / `SessionEnd`） |
| G-3 | MCP HTTP/SSE 传输 | `extension/manifest.py:73` | 「本期仅 stdio；**HTTP/SSE 预留**」 |
| G-4 | 插件 npm 安装 | `extension/plugin_fetcher.py:284` | 「npm 安装（默认关闭；**本期内置为未启用，抛错以保持 fail-closed**）」 |

---

## §8 本轮发现的**两处缺陷**

### 8.1 ★ `XEYO_MEMORY_INDEX_LIVE` 的 GUI 开关是**死的**（显示开、实际恒关）

| 环节 | 行为 | 证据 |
|---|---|---|
| 注册 | **在** `MEMORY_SWITCHES` 里（保留占位） | `memory/memory_switches.py:51` |
| 本工作区 settings | `.xeyo/settings.json` 的 `memory` 段写着 `"XEYO_MEMORY_INDEX_LIVE": "1"` | 实测读取 |
| GUI 读取 | `get_value()` → store 里有 → 返回 `"1"`，`source="settings"` | `memory_switches.py:94-111` → `current()` `:114-131` |
| GUI 渲染 | `on = sw.value === '1'` → **开关显示为"开"** | `gui/src/components/MemorySwitchesSetting.tsx:64` |
| GUI 写回 | 可点、可切、`save()` 接受（键在 `_DEFAULTS` 里） | `memory_switches.py:159-167` |
| **运行时** | `_memory_index_live_enabled()` **恒 `return False`**，**不看这个键** | `engine/query_loop.py:355-363` |

**结论**：用户面板显示"开"、可来回切换，但**功能永久关**。这正是 `memory_switches.py:98` 想避免的那类问题（「显示关、实际开」）的**镜像形态**（「显示开、实际关」），且当前**没有任何测试覆盖**这一对矛盾。

> 同类风险：`memory_switches.py:360` 的设计前提是「注册键与 GUI 显示逐位一致」，但**恒关项被保留注册**恰恰破坏了这个前提。建议：恒关项在 `current()` 里加 `"effective": False` 或 `"ignored": true` 字段，GUI 置灰并注明"已下线"。

### 8.2 本工作区 settings 有 **4 个已删除的残留键**

`.xeyo/settings.json` 的 `memory` 段含：

```json
"XEYO_MEMORY_RERANK_PREFERENCE": "1",
"XEYO_MEMORY_SQLITE_INDEX": "1",
"XEYO_CACHE_COOLDOWN_OMEGA": "1",
"XEYO_C2_GATE": "1"
```

这四个**都已删除**（`memory_switches.py:32-45`）。它们**不生效**但也**不会报错**：`current()` 遍历的是 `MEMORY_SWITCHES`（不含它们），`save()` 只在被写入时才抛错（`:160-162`）。**没有任何清理入口**——文档说「旧 settings 残留值被忽略」是对的，但**残留会一直留在盘上**，未来若同名键复活会**静默继承旧值**。建议加一个一次性清理（或 `save` 时顺带剔除未知键）。

> 注：`"XEYO_L5": "v61"` 是**有效**键，且本工作区已开 v61（每轮 decide）。

---

## §9 为什么"没开"——四类根因

把上面所有条目归因，只有四种原因：

| 根因 | 释义 | 典型条目 |
|---|---|---|
| **① 出过事故** | 功能曾开启并造成真实损害，用户裁决下线 | `XEYO_MEMORY_INDEX_LIVE`（sess_mtiche8l）；`XEYO_BLOB_GC_ENABLED`（曾漏判 dry_run 致真删） |
| **② 证据门未过** | 收益没被测量到，或测量了但**输出不稳定**，按 AGENTS 第 4 条"有数据证明收益后才并入主链"停在旁路 | `XEYO_C2_LLM_SUMMARY`（"吸收潜力高但输出不稳定"）、`XEYO_V61_*`（B1/B2/B3 门未过）、`XEYO_MCP_NAME_MANIFEST`（"实测 token 收益后接入"） |
| **③ 前置机制未落地** | 功能本身安全，但它依赖的**恢复/回滚机制**还没有 | `XEYO_TOOL_AGING`（"toolout 占位的恢复机制未落地前保持关闭，避免原文不可找回"） |
| **④ 安全默认** | 故意关，开=放宽权限边界；属于产品安全姿态而非功能欠缺 | §3 全部 11 项；`XEYO_WALL_HARD_STOP`（无墙钟武装=行为零变化） |

**一个观察**：这三条「不是缺功能」的根因里，**②和③都是"等一个机制"**——而 §8 表格里那几个"开了就是巨大收益"的点，前置条件高度重合（都需要**可回滚 + 可观测**）。这与五轮报告的核心结论一致：**先补"命名事件瀑布 + 投影层算子"，才能安全地打开这些关闭态功能**。

---

## 附：取证边界

| 项 | 说明 |
|---|---|
| 复核方式 | 直接读源码（`Read` + Python 脚本切片），**不依赖子代理转述** |
| 覆盖 | `python/` 全仓 `XEYO_[A-Z0-9_]+` 穷举（去重 **238** 个）；198 个 `environ.get` 读取点逐条抽默认值；`gui/src/stores/settingsStore.ts` `DEFAULTS` 全表 |
| 排除 | `.venv` / `__pycache__` / `node_modules` / `tests/` / `scripts/`（评测脚本内的开关不属产品面） |
| 未逐行读 | `memory/runtime.py` 的 C2 公式族（约 600 行，只读了开关闸门）；`evals/*_shadow.py` 的函数体（只读 `enabled()` 与 docstring） |

