# XEYO 普通多 Agent 协同落地实施计划书

> 仓库：`D:\lea\XenYon code`
> 版本：2026-08-18
> 定位：先落地**普通多 Agent 协同**（第四个模式），建成让 N 个独立决策 agent 共享同一 workspace 可运行的**运行时基座**。
> 对照：[28-多Agent协同设计.md](../设计/28-多Agent协同设计.md)（设计总纲） · [10-完整记忆体系.md](../设计/10-完整记忆体系.md) §5（多 Agent 记忆） / §7（落地门控）。
> 前提：XEYO 现为**单 Agent 主循环**——`AgentTool` 工厂在 [catalog.py](../python/tools/catalog.py) 存在但**未进 `ENABLED_TOOLS`**，故"多 Agent"目前实为空壳。本计划从"地基"起步。

---

## 当前落地进度（P0 普通多 Agent 协同——统一汇总）

> 更新时间：2026-08-18。**机制全部打通并验证**；唯一的"真跑"门槛是真实模型/运行环境。

### ① 新增文件
| 文件 | 关键接口 |
|---|---|
| `python/memory/journal.py` | `ChangeRecord`/`record_change`/`recent_changes`/`gc` |
| `python/engine/write_store.py` | `EditOp`/`ChangeIntent`/`ApplyResult`；`submit`(async 队列)/`submit_sync`(同步)；`_apply_core`(content-hash 校验+原子写+journal)；`_content_hash`/`_content_hash_text` |
| `python/engine/scheduler.py` | `Task`/`toposort`/`scope_conflicts`/`build_tool_whitelist`/`Scheduler`(DAG+并发+文件级冲突+超时+状态 best-effort+`registry_for`)；`SUBSET_TOOL_BASELINE`/`FORBIDDEN_SUB_TOOLS` |
| `python/engine/subagent_context.py` | `SubagentContext`/`build_subagent_context`(A3 前缀稳定+动态尾部；A4/A8 剔除禁止项) |
| `python/engine/subagent_runner.py` | `SubagentRuntime`/`SubagentRunResult`/`run_subagent`/`_sidechain_path`/`_flush_subagent_snapshot`/`gc_sidechains` |
| `python/tools/agent_tool/`（`__init__`+`agent_tool.py`） | `AgentTool`(name/schema/execute)/`AgentInput`/`SubagentOutput`/`MAX_DEPTH=1`/`set_runtime_provider` |
| `python/tests/test_agent_tool.py` | 20 项边界断言 |

### ② 修改文件
| 文件 | 改动 |
|---|---|
| `python/tools/catalog.py` | `_agent` 进 `ENABLED_TOOLS`；`SUBSET_TOOL_WHITELIST`/`_FORBIDDEN_SUB_TOOLS`；`inject_write_store`/`build_subagent_registry`(含禁止项过滤+注入)/`inject_subagent_runtime` |
| `python/engine/query_engine.py` | `build_default_engine` 注入 `SubagentRuntime`(append_system_prompt/date_iso) |
| `python/server/session_pool.py` | `_build` 注入 `SubagentRuntime`+`AgentTool.write_store`；`scheduler_for`/`gc_sidechains`/`_schedulers`/`drop` 清 scheduler |
| `python/tools/file_edit_tool.py` / `file_write_tool.py` | `set_write_store`/`set_agent_id`/`_persist`（`None`=旁路，`非None`=经 store） |
| `python/memory/working.py` | `WorkingSnapshot.tasks` |
| `python/tests/test_catalog.py` | `_FROZEN_ENABLED` 加 `Agent` |

### ③ 验证清单（全部 PASS）
- **编译**：所有新增/修改文件 `py_compile` 通过。
- **写路径**：`submit_sync` 新写 ✓；**stale 拒绝、不覆盖**(content preserved) ✓；原子写无 `.tmp` 残留 ✓；journal 记录 ✓。
- **注入**：`build_subagent_registry` 排除 `_agent`/`Bash`/`Agent` + 注入 `write_store`/`agent_id` ✓；`inject_subagent_runtime` 设置 `_runtime_provider` ✓。
- **A3/A4/A8**：`build_subagent_context` base_prefix 未改、动态在尾、禁止项剔除 ✓。
- **AgentTool**：无 runtime → `is_error` 安全失败 ✓；`max_depth=1` 拒绝 ✓。
- **调度器**：`toposort` 正确、`scope_conflicts` 同文件冲突/异文件不冲突 ✓。
- **侧链**：`_flush_subagent_snapshot` 落 `agent_id` ✓；`gc_sidechains` 清超 TTL ✓。
- **端到端**：`build_default_engine("fake")` 里 `Agent` 在注册表且 `_get_runtime()` 完整；`run_subagent` 用 fake 引擎产出 `FinalEvent` → `conclusion='ok: ...'` ✓。
- **HTTP 层**：`session_pool._build` 注入 helper 就位；`scheduler_for`/`gc_sidechains` ✓。
- **调度闭环**：`Scheduler._run_task` 经 `run_subagent` 真实跑子 agent；`run_task_batch` 批量调度（fake 引擎 2 任务、含依赖）→ `status=done` + 产出 `last_result` ✓。
- **Multi-Agent 前端接入**：`chat.py` `multi_agent`/`tasks` 字段 + `_multi_agent_stream`（`run_task_batch`）；前端 Composer "Multi-Agent" 菜单项 → chip 指示（与 Plan/Ask 对齐）→ `multi_agent` flag 全链路（chatStore/api.ts）✓（后端编译通过）。
- **一键分解**：`subagent_runner.decompose_tasks` + `parse_tasks_json`（容忍代码块/前后缀，解析失败回退单任务）已接；`parse_tasks_json` 实测（合法数组→task、非法/空→[]）✓。
- **联调（本沙箱最接近真）**：前端 `pnpm typecheck` **exit 0**（含 `Composer/chatStore/api.ts` 改动 + `AppShell.tsx` 未用变量修复）；后端复刻 `_multi_agent_stream` 流程 smoke（fake 引擎：decompose→[]→回退单任务→`run_task_batch`→`done`+结果→summary）= **SMOKE_OK** ✓。**真实模型 + 浏览器点按需用户环境（key + `pnpm dev` + fastapi + 点 chip）。**

### ④ 边界 / 待做（诚实）
- **pytest 未能在本 sandbox 跑**（basetemp 写系统 Temp 被拒）；已用直接脚本验证同样断言（20/20）。正常 CI（系统 Temp 可写）应 `pytest tests/test_agent_tool.py` 直接通过。
- **真实模型未跑**（E2E 用 fake）；真实 `OpenAICompatClient` 未在 `_build` 跑（需 API key）。机制已通，真跑需环境。
- **`base_prefix` 真稳定前缀**由 `prompt.build_system` 生成（已接）；但"L1/索引/工具 schema"的**精确稳定段**未单独单测，依赖引擎的 build_system。
- **B1**（子 agent `_depth>=1` 不得等跨 Agent DAG）仅在注释/白名单约束，未在 runner/调度器**强制**——需 scheduler 层保证。
- **`scheduler.run()` 调度闭环已接**：`run_task_batch` + chat.py `_multi_agent_stream`。**`multi_agent=true` 时一律走批量**：有 `tasks` 用现成；否则让主模型 `decompose_tasks(user_text)` 拆任务；再否则回退单任务。前端 `Composer` 的 Multi-Agent chip 点亮即生效。
- **侧链 GC 未定时调用**（`gc_sidechains` 方法已就位，需在服务层周期性触发）。
- 启用 `AgentTool` 后主模型可自由调用它（嵌套跑子 agent，深度限 1、预算小）——**行为变化**，建议用调度器或前端控制真正触发多 Agent 的场景。

### ⑤ 当前"能用"到什么程度
主模型调用 `Agent` 工具 → 注入 runtime/store → 子 agent **短上下文(真A3前缀)** + **受限工具(剔除_agent/Bash, memdir只读)** + **走每文件单写者 store(content-hash)** + **写侧链+agent_id snapshot** → 端到端产出结果。**机制层已全通**；"多 Agent 真正由调度器编排任务"与"真实模型联调"是下一阶段。

### ⑥ 本轮新增强化 + 下一步（2026-08-18）
**本轮做**：① `scheduler.run()` 调度闭环（`run_task_batch` 真实分发子 agent）；② `chat.py` 接 `multi_agent`/`tasks`（有 tasks 走 `_multi_agent_stream` 批量）；③ 前端 Composer "Multi-Agent" 菜单项（点击即选模式，出现 **Multi-Agent chip** 指示，与 Plan/Ask 的 ModeChip 对齐；去掉 ON/OFF 文本）+ flag 全链路（chatStore/api.ts）。

### ⑦ 多 Agent 聊天 UI 已落地（浏览器式界面导航）

> 更新时间：2026-08-18 第二轮。**UI 全链路落地并测试通过**；待真实环境点验。

**数据层（后端）**
| 改动 | 说明 |
|---|---|
| `subagent_runner` 增加 meta 持久化 | `upsert_subagent_meta`/`list_subagent_metas`/`load_sidechain_messages`；每子 agent 写 `~/.xeyo/sessions/{main}/agents/{id}.meta.json`（task_id/desc/status/result_preview/has_transcript/started_at）；`run_subagent` 结束时落盘 |
| `scheduler.run_task_batch(..., agent_ids=)` | 编排层可预生成 agent_id（批次尾缀去重），多次运行侧链不再互相覆盖 |
| `chat.py _multi_agent_stream` 重写 | 事件统一走 **`xy` 字段**（旧 `xeyo` 字段前端不解析，已废弃）：`multi_agent_task`(running, 含 uid/agent_id/desc) → `multi_agent_result`(全量汇总)；结果摘要以流式 Markdown 回主对话（跑完有留痕）；meta 兜底补齐 |
| `sessions.py` 新端点 | `GET /v1/sessions/{id}/agents`（卡片列表）、`GET /v1/sessions/{id}/agents/{agent_id}`（完整侧链对话：user 块+图片引用、assistant、tool 行映射为 ChatMessage 同构） |

**展示层（前端）**
| 组件 | 职责 |
|---|---|
| `chatStore` 多 Agent 状态 | `multiAgentTasksBySession`（SSE 实时卡片）/`agentsBySession`（服务端历史批合并）/`agentTranscriptsById`（transcript 缓存）；selectSession 时重置视图+预取列表 |
| `MultiAgentStrip` | 运行条：本会话「正在运行(spinner)/done(ok 点)/failed(danger 点)」卡片，点击进入子视图；仅有多 Agent 任务时渲染 |
| `SubAgentView` | 同一聊天区覆盖渲染子 agent 完整侧链对话（复用 `MessageBubble`——图片/Markdown/tool 行与主对话完全一致，Q7）；带返回/回主对话按钮；加载中/空态 |
| 标题（Q4） | 子视图中 ChatHeader = `原对话标题 / 子agent标题`（16ch 截断） |
| 侧栏右上角 ←→（Q5 扩展） | 升级为**整个 GUI 的浏览器式导航**：全局导航日志 `navJournalStore`（路径+用量面板开合即「界面」，就近匹配算法：相同忽略/邻居后退前进/新访问截断 forward），`NavJournalSync` 挂 App 自动采集；箭头常驻，覆盖所有会话/Side Chat/用量面板切换。多 Agent 子视图保持会话内存栈（切会话回主视图） |

**协议要点**
- SSE 事件：`xy: {type:"multi_agent_task", task_id, uid, agent_id, desc, status}` 与 `xy: {type:"multi_agent_result", tasks:[{uid,taskId,agentId,desc,status,reason,result}]}`。
- uid 规则 `{task_id}:{batch_tail}`；agent_id 规则 `agent-{task_id}-{batch_tail}`。
- 历史 meta 兜底：即使子 runner 崩溃/runtime 未配置，也有卡片可回放（status=failed）。

**验证**
- 后端 pytest（排除缺 fastapi/pytest-timeout 的模块）：**487 passed, 3 skipped, 0 failed**；新增 `tests/test_subagent_meta.py`（8）+ `tests/test_multiagent_hardening.py`（4，防静默失败回归）。
- 过程中修复真 bug：`AgentTool.set_write_store` 缺失导致 session_pool 注入 AttributeError（此前 sandbox 无法跑 pytest 故未暴露）。
- 前端：`pnpm typecheck` exit 0；**281 测试全过**（含 navJournalStore 8 用例 + Composer multiAgent 参数传递 3 用例）。
- 后端冒烟：meta 排序/截断/has_transcript 自动探测/侧链往返/损坏行跳过 PASS。
- **防静默失败加固（2026-08-18 第三轮）**：多 Agent SSE 分支曾被 try/except 遗漏——`decompose_tasks`/`run_task_batch` 任一内部异常都会让流半途而废，FE 无卡片无横幅（静默无输出）。三层收敛：① `decompose_tasks` 失败回退单任务；② `Scheduler._dispatch` 广泛捕获，单任务异常落成 `failed`+reason 不再炸整批；③ chat 层整段分支兜底 `_sse_error`+[DONE]，保证 FE 至少出现错误横幅。`batch_error` 时所有任务合成可见的 failed 行并写 meta 兜底。

**待真实环境点验（唯一剩余）**：fastapi + uvicorn 环境 + DeepSeek key + `pnpm dev`：
发一条 Multi-Agent 消息 → 观察运行条 running → done → 点卡片进子对话 → ChatHeader 组合标题 → 侧栏右上角 ←→ 往返 → 主对话底部出现结果摘要 Markdown → 刷新后卡片仍可回放。


**下一步（三选一）**：
1. **用户环境真跑联调**（本沙箱"最接近真"已验证：前端 typecheck 通过 + 后端 fake 引擎 multi_agent 流程 SMOKE_OK）。需要：装 `fastapi`/uvicorn + 配真实 DeepSeek key + `pnpm dev` + 起后端 → 点 Multi-Agent chip 发消息，看 `decompose_tasks`→`run_task_batch`→流式回传。**是完整确认链路的唯一路径。**
2. **补前端测试**：`Composer.chat.test.tsx` 的 `sendMessage` 参数断言需同步加 `multiAgent`；可顺手补一个 `MultiAgentChip`/菜单项的 ui 测试。
3. **子 agent 结果回填主会话**：`_multi_agent_stream` 目前只回传任务结果摘要；可让子 agent 真正改文件（写 store）并把结论写进主会话（回传单条）。

---

## 0. 为什么先做"普通多 Agent 协同"

它是其余三个模式（主从/裁判-辩论/流水线）的**运行时基座**。没有"多个独立 agent 共享工作区、不踩脚、不瞎、不烧钱"这个底座，主从的 Router、裁判的 Jury、流水线的交接链都是**空中楼阁**。

`28-多Agent协同设计.md` 已经给了"主从 + 同文件交接 + 新闻"的**理想终态**，但那是 P2 之后的事。**本计划先把"最灵活、也最难"的普通多 Agent 做成能跑的基座**，再往上叠。

三个必须拔掉的硬伤（你点得很准）：

| 硬伤 | 说明 | 本计划对策 |
|---|---|---|
| **踩脚** | 无**LLM 协调者**；agent 互相挤同一文件 | 共享写锁 + 版本校验（§2.1） |
| **瞎** | 无共享状态，不知道彼此在干嘛 | 共享变更日志 + 索引（§2.2） |
| **成本爆炸** | N 个 agent 各带完整 context = 共享部分 ×N | 短上下文隔离 + 共享稳定前缀（§2.3） |

**"没有协调者"要精确理解（这是本计划的架构核心）：**
> 指**没有 LLM 中央大脑替大家做语义决策**；但**必须有确定性调度器 + 确定性共享原语**，否则 20 个任务根本分不下去。三层分工：
> 1. **分解/建 DAG**（可能 1 次 LLM，有界、一次性语义）→ 产出任务清单（id · 依赖 · 写范围）。
> 2. **分发/调度**（确定性，非 LLM，§2.4）→ 按依赖 + 冲突安全 + 并发上限 分配/并行/串行。
> 3. **独立决策**（每 agent 自己推理）→ 拿到任务后**怎么干**完全自己定（这才是"没有协调者"的本意）。

---

## 1. 目标与非目标

### 目标（本阶段）
让 **N 个独立决策的 agent 在同一个 workspace 干活**，做到：
1. **不踩脚**：并发写同一路径不再互相覆盖（至少报错/串行）。
2. **不瞎**：agent 能看到"其他人改了啥、哪些文件最近被动过"。
3. **不烧钱**：子 agent 不再 N 倍载入主会话 80k 全上下文。
4. **能分配**：N 个任务能被**确定性调度器**按依赖 + 冲突安全分配/并行/串行（§2.4），不需要 LLM 协调者。

### 非目标（本阶段不做，留给 P2 / 其它模式）
- 裁判-辩论、完整流水线、语义重叠 AST、News 语义检索。
- write-through store **完整版**（冲突仲裁/语义重叠/drift_check 全套）——P0 用轻量替身（§4）。
- 主从 Router 分级、`MemoryCandidate` 自动晋升、侧链多维索引。

---

## 2. 三个核心问题的落地对策（映射到代码）

### 2.1 问题 A：踩脚（并发写）→ 每文件独立序列化队列 + content-hash 版本校验（非全局串行）

**做法（P0 轻量，不引 AST；不引入分布式锁——见 28 §2.5.2）：**
1. **每文件独立序列化队列（per-file single writer，非全局串行）**：所有写操作（[`file_edit_tool.py`](../python/tools/file_edit_tool/file_edit_tool.py)、[`file_write_tool.py`](../python/tools/file_write_tool/file_write_tool.py)）不直接落盘，而是**提交一个"变更事务"给 write_store**。`write_store` 内部维护 **`path → queue` 映射**，按事务路径**路由到对应队列**；**每文件一个消费者、串行 apply**。**同一时刻每个文件只有一个写者；不同文件的写完全并行**（保留"普通多 Agent"不同文件并行的甜点）。**没有共享锁文件、没有锁 TTL、没有死锁可坏**；若文件数多则**按 path hash 分桶**（如 64–128 shard），consumer 放 **scheduler 专用 worker 池（B1/#1）**。
2. **content-hash 版本校验**：agent 提交事务时带 `base_hashes`（它读到的文件内容哈希）。store 落盘前比对 **base hash vs 当前磁盘内容 hash**：
   - 一致 → 放行。
   - **不一致（stale）** → 与上游**无重叠**则 **rebase**（能干净 apply 才做，否则判硬冲突，§2.5.1）；**重叠**则**显式冲突**，不覆盖，让 agent 重读再改。**用 content hash 而非 mtime**（mtime 同刻度会漏，28 §2.5.2 B8）。
3. **原子写（B2/#2，P0 限定单文件事务）**：写入用 temp + rename（或 append-only journal + 原子替换），避免并发读写撕裂（28 §2.5.2 C9）。**P0 把"一次事务"严格限定为单文件**；多文件强一致 → 强制拆成多个串行子任务。`submit_transaction(files)` 若传多文件：**先全部校验 `base_hashes`、再全部落盘（预检）**，任一冲突 → **整体拒绝，不做脏写**（避免"A 已写、B 冲突、A 回滚不了"，"全有或全无"才成立）。
4. 语义重叠检测（同符号）**留到 P2**（需跨语言 AST，`28` §7.2 风险 #5）。P0 只做"同路径 hash 校验"这一档。
5. **Stale 冲突后的重试（A1/#2）**：store 报 `StaleConflict` 后，调度器**不直接重放原任务**，而是生成一个**修补任务（Patch Task）**（见 §2.4）：`desc="merge/re-apply 你的改动到最新版本"` + **强制注入 `recent_changes`**；重试上限 **3 次**，超则宣告失败并告警。

**为什么够用**：绝大多数"踩脚"是同文件被两个 agent 同时改。每文件单写者串行 + content-hash 校验已能挡住「静默覆盖」。同符号不同区域的"语义冲突"是更高阶问题，留 P2。

**关键（与"普通多 Agent"一致）：** store 是**确定性"每文件单写者"（管 mutation 安全）**，**不是 LLM 协调者（管决策）**。agent 仍**独立决策**，只是"改文件"走**每文件的串行通道**（不同文件并行）。agent 的慢端是 LLM 推理（仍并行），写操作少且 store apply 快（确定性文件操作）——**串行的只是"写"，不是"想"。**

**journal/版本序：** 正确性按文件（每文件自己的版本链 + content-hash + rebase/conflict，自然）；**全局单调 seq**（journal 追加时打）用于审计/追溯，跨文件乱序也能重建全局先后。

**悲观 vs 乐观由 `§7` 碰撞频率定**：碰撞低 → 乐观为主（version-check + rebase）；碰撞高 → 加重锁 / 串行化碰撞范围（牺牲并发换不白做）。

### 2.2 问题 B：瞎（无共享状态）→ 共享变更日志 + 索引

**做法（P0 轻量）：**
1. **共享变更日志（journal）**：每次写成功记录一条到 `.xeyo/journal/{ws}/changes.jsonl`：
   ```json
   { "ts":"...", "agent_id":"agent_b", "path":"src/foo.ts", "action":"edit",
     "file_hash_after":"sha256:...", "brief":"Foo.render hook 化" }
   ```
   - 挂点：写工具成功后调用一个新模块 `journal.record_change(...)`；或复用 [`audit/log.py`](../python/audit/log.py) 的 `record(kind,**fields)`（已 append-only、线程安全）加 `path`/`agent_id`/`is_write`。
   - 这给 agent **"其他人改了啥"** 的可见性。
2. **轻量索引（"最近变更"）**：读端提供一个 `journal.recent_changes(path_prefix?, since_ts?)`，返回最近 N 条。**在子 agent 要写之前**，把"目标路径最近被谁改过"注入它的上下文，让它知道"这块刚被碰过"。
   - **索引只做"按路径过滤 + 最近排序"，不做语义检索**（News 语义检索留 P2）。

**为什么够用**：P0 的"瞎"主要指"我不知道我正要改的文件刚被别人改了"。路径级"最近变更"就够；跨文件/跨模块的"全局知情"是 News(§4.7) 的事，P2 再上。

### 2.3 问题 C：成本爆炸（N×全上下文）→ 短上下文隔离 + 共享稳定前缀

**做法（P0 关键，直接决定钱）：**
1. **子 Agent 上下文隔离（§5.3"隔离（默认）"）**：子 agent 的 system = `L1 XEYO.md + MEMORY.md 导航索引 + 裁剪后的工具 schema + 任务 prompt`——**绝不载入主会话 80k 全上下文**。这是 `28` 里记忆设计 1"方向修正"的核心：**不是缓存重复读，而是"一开始就别喂 N 份全文"**。
   - 实现：`AgentTool` 构建子 agent 时生成一套**裁剪工具 + 短 system**（对齐 [`permissions/policy.py`](../python/permissions/policy.py) 的工具过滤）。
2. **共享稳定前缀（让缓存命中）**：所有子 agent 共用**同一份基础前缀**（base system + 工具 schema 顺序/键序锁定），只在**右段**加各自的"任务 prompt + 近期变更注入"。这样它们能蹭同一段前缀缓存（`28` §3.2；`10` §2.6 前缀稳定）。
   - **禁止**为省 token 本轮只暴露 3 个工具（schema 一变整段 miss，通常更贵——`10` §2.6 已写明）。
3. **缓存拼接顺序（A3/#4，强制）**：`[固定 System] + [固定 ToolSchema]` 必须**严格连续、置于最前**；一切动态（任务 prompt / 近期变更）**只能 append 在最后**。动态插进中间 → 前缀哈希全变 → 全部 miss。**P0 单测 + CI 加"前缀哈希不变性"测试**，一有人把动态塞中间就报错。
4. **子 Agent 工具集（A4/#5 + C2/#3）**：基线 `ReadFile + WriteFile + EditFile + JournalQuery(只读最近变更)`；**高级工具（搜索/AST/终端）由任务 `required_tools` 声明后动态开放**（§2.4 item 3，调度器按任务建 whitelist）。写进 `catalog.py` 的 `SUBSET_TOOL_WHITELIST`；**永不给子 Agent `_agent`**（防递归，A8）。

### 2.4 调度 / 分发：把 N 个任务分下去（回答"20 个任务怎么分配"）

"没有 LLLM 协调者"不代表"没调度"。**20 个任务必须有一个分配机制，否则谁都抢同一个任务或没人干。** 这一层做成**确定性**的，绝不做成 LLM（否则退回贵/慢/盲的协调者——`§7.2` 风险 #1/#8）。

**任务清单**（建议复用 `WorkingSnapshot.todos` 加依赖、写范围、所需工具字段）：

```jsonc
{ "id": 1, "desc": "改 Foo.render", "depends_on": [], "scope": ["src/foo.ts"],
  "required_tools": ["Edit","JournalQuery"], "timeout_s": 300 }   // C2/#3, C4/#5
{ "id": 2, "desc": "改 login",       "depends_on": [1], "scope": ["src/login.ts"],
  "required_tools": ["Read","Edit"], "timeout_s": 300 }
```

**确定性调度器**（非 LLM）：
0. **专用 worker 池（B1/#1，防死锁）**：`scheduler.py` 用**独立 worker 池**，与主循环/`orchestration.py` 的池**物理隔离**。**约法**：子 Agent `_depth>=1` 时其内部**绝不等待跨 Agent 的 DAG 任务**，只做纯工具操作，杜绝嵌套等待（否则 Worker 全被阻塞、再无空闲线程处理依赖任务）。
1. **DAG 拓扑排序**：有依赖的任务等前置完成才放行（`depends_on`）。
2. **写范围冲突检查（C1/#2，只留文件级）**：P0 无 AST → **只区分文件级**：**不同文件→并行；同文件→调度层不并行（防白做）+ 写队列串行兜底（§2.1）**。**移除 `lines` 行区间字段与启发式**（有每文件队列后冗余且误导：物理间隔≠语义安全；真实语义冲突由 P2 AST 接管）。
3. **所需工具白名单（C2/#3）**：根据每个任务的 `required_tools`，动态构建子 agent 工具白名单（`Read/Write/Edit/JournalQuery` 基线上再加所需），**不暴露 `_agent`**、高级工具（搜索/AST/终端）仅当任务声明才开。
4. **并发上限**：worker 池，上限复用 `orchestration.py` 的 `_max_concurrency()`（默认 10）。
5. **任务超时（C4/#5）**：记每任务 `started_at` + 每任务 `timeout_s`（默认 300）；后台巡检，超时任务**标失败（reason=timeout）并释放 worker**，失败原因进离线分析。
6. **状态持久化（A2/#3，P0 best-effort）**：每次状态变更**轻量写** `{ws}/.xeyo/scheduler_state.json`（含 `cleanup_ttl`/`parent_session_id`）；P0 允许"重启即弃、只留日志"（C7/#8），**重启恢复与断点续跑 → P1**。
7. **Stale 冲突处理（A1/#2，P0 记日志为失败 → P1 接 Patch 重试）**：P0 收到 `StaleConflict` **记日志 + 标失败**（不自动重放）；P1 起升级为**修补任务（Patch Task）** `desc="merge/re-apply 到最新版本"` + 强制注入 `recent_changes`，重试上限 3 次。
8. **任务池取用**：完成一个、调度器再从待办队列派下一个（work-stealing / 队列）。

**三个情形：**
- **独立、写不同文件** → 并行跑，普通多 Agent 的甜点。
- **有依赖** → 拓扑排序，前置完成后才放行后置。
- **都写同一文件** → 并行无好处，**调度层不并行**（防白做）+ 写队列串行（§2.1）；这种**不该用"普通多 Agent"，该往流水线/交接靠**（`28` §4）。

**关键：分发是确定性的、便宜的、可单测的。** 唯一的 LLM 参与是"分解/建 DAG"这一步（用户一句话 → 拆成带依赖的任务图），它是一次、有界、语义性的；一旦拿到任务图，**分发就是确定性的**。

---

## 3. 前置地基（先搭：基本 agent 框架）

`§5.6` 明确：未做「侧链 JSONL + agent_id snapshot + 回传单条 + memdir 只读」之前，**不要**把 `AgentTool` 移出脚手架。所以地基先行：

### 3.1 AgentRun 身份 + 侧链 JSONL
- [`working.py`](../python/memory/working.py) 已有 `agent_id: str = "main"`——子 agent 跑时**设为非 main 的 id**。
- **侧链**：子 agent 的完整历史写 `{session}/agents/{agent_id}.jsonl`，**禁止 append 进主 JSONL**。参照 [`session/record_transcript.py`](../python/session/record_transcript.py) 加一个 sidechain recorder。

### 3.2 注册 AgentTool + 回传单条 + 递归控制
- [`catalog.py`](../python/tools/catalog.py):122 的 `ENABLED_TOOLS` 加 `_agent` 工厂；`AgentTool.execute()` 真正 spawn 子 agent（独立的 `query_loop`/`QueryEngine` 实例，`agent_id` 非 main）。
- **回传只加一条** `tool_result`（结论 / 改过的文件 / 关键路径 / 可选 `MemoryCandidate[]`），不把子 agent 全文打进主 store（`§5.4`）。
- **递归控制（A8/#8，安全）**：`AgentTool.execute()` 加 `_depth` 参数，spawn 时 depth+1；**构建子 agent system prompt 时动态移除 `_agent` 工具（depth≥1 时）**。P0 **硬限制 `max_depth = 1`**，避免孙 agent 无限递归 / 成本爆炸。

### 3.3 memdir 只读 + MemoryCandidate 回传
- 子 agent **默认只读** memdir；要记的走 `MemoryCandidate` 回传主会话，过验证闸再晋升（`§5.2`/`§5.5`）。

---

## 4. 分期（带 `§7` 门控）

| 阶段 | 做 | 验收 | 门控 |
|---|---|---|---|
| **P0（基座）** | ① 侧链 JSONL + `agent_id` ② 注册 `AgentTool` ③ 子 agent 短上下文隔离(§2.3) ④ **每文件独立序列化队列 + content-hash 版本校验(§2.1，不引入分布式锁)** ⑤ journal 变更日志(§2.2) ⑥ **任务队列 + 确定性调度器(§2.4)** | 能 spawn 2 个子 agent 并行改不同文件不发生覆盖；子 agent 上下文不含主会话全文；写路径能报 stale 冲突；**20 个任务能按依赖+冲突被分配/并行/串行** | **无条件**（地基，必须先做） |
| **P1** | ⑦ 子 agent 上下文共享稳定前缀 + 近期变更注入 ⑧ "最近变更"索引注入写前上下文 ⑨ 测量打点(task_batch_id/agent_id/碰撞) | 子 agent 能看到"这块刚被谁改过"；缓存命中率数据可统计 | 需 P0 验收通过 |
| **P2** | ⑩ write-through store 完整版(冲突仲裁/语义重叠 AST) ⑪ News 语义检索 ⑫ 主从 Router 分级 | 同符号语义冲突显式抛出；跨模块知情 | **数据支持**（§7.4：碰撞频率高 且 handoff/News 实测省 token） |

**原则：P0 是地基、无条件；P1/P2 都要数据说话（`§7.4`）。**

---

## 5. 代码改动点（具体文件，P0 优先）

| 改动 | 文件 | 说明 |
|---|---|---|
| `agent_id` 非 main | `python/memory/working.py` | WorkingSnapshot 已含字段，子 agent 赋非 main id |
| 侧链 JSONL | `python/session/record_transcript.py`（新增 sidechain + GC） | `{session}/agents/{agent_id}.jsonl`；**`cleanup_ttl`(默认 7 天)清理 + 未消费标孤儿删除（B6）** |
| 注册子 agent 工具 | `python/tools/catalog.py`（ENABLED_TOOLS 加 `_agent`） | 前置条件齐后启用 |
| spawn 子 agent | `python/tools/agent_tool/`（execute 实现） | 独立 QueryEngine/query_loop，短上下文；**`_depth`+1，depth≥1 移除 `_agent` 工具，`max_depth=1`（A8/#8）；depth≥1 不得等跨 Agent 任务（B1/#1）** |
| 子 agent 短上下文 | `python/engine/query_engine.py`（构建 system/tools 处） | 裁剪工具 + 短 system；**动态只 append 尾部 + 前缀哈希不变性 CI 单测（A3/#4）** |
| 子 agent 最小工具集 | `python/tools/catalog.py`（`SUBSET_TOOL_WHITELIST`） | `ReadFile+WriteFile+EditFile+JournalQuery` 基线（A4/#5） |
| 每文件独立写队列 | `python/tools/file_edit_tool/`、`file_write_tool/`；新建 `python/engine/write_store.py` | `path→queue` 路由 + **每文件单消费者**（按 path hash 分桶）；content-hash 版本校验；原子写（temp+rename）；**P0 单文件事务 + 多文件预检整体拒绝（B2/#2）**；**写后局部 AST 语法校验记 `syntax_valid`（A5/#7+B4/#4）** |
| **任务队列 + 调度器** | 新建 `python/engine/scheduler.py`（+ `WorkingSnapshot` 加 `depends_on`/`scope`/**`required_tools`**/`timeout_s`） | DAG 拓扑 + **scope 文件级（已移除行区间，C1/#2）** + **按 required_tools 建工具白名单（C2/#3）** + 并发上限 + **独立 worker 池（B1/#1）** + **任务超时（C4/#5）**；**轻量写 scheduler_state.json（A2/#3，P0 best-effort，含 cleanup_ttl/parent_session_id）** + **Stale→Patch 重试（A1/#2，P0 记日志为失败、P1 接重试）** |
| 变更日志 | 新建 `python/memory/journal.py` 或复用 `audit/log.py` | `.xeyo/journal/{ws}/changes.jsonl`（含 `syntax_valid`） |
| 最近变更查询 | 同上 | `recent_changes(path, since)` 注入写前上下文 |
| 测量打点 | `python/usage/ledger.py`、`audit/log.py`、写工具 | `task_batch_id`/`agent_id`/`path`/`is_write` |

---

## 6. 测量与门控（`§7.3`/`§7.4` 落地）

**P1 起采集，P0 先补打点：**
- `usage/ledger.py`：`record_from_openai_usage` 加 `task_batch_id` / `agent_id` / **`input_cache_hit`/`input_cache_miss`（C6/#7）**（现有可能只有 `session_id` / 总体 hit/miss）。
- 写工具 / `audit`：写事件带 `path` / `agent_id` / `is_write`；**碰撞事件带 `conflict_task` 标记（C5/#6）**。
- 复用 [`usage/pricing.py`](../python/usage/pricing.py):146 已有 hit/miss；[`memory/observe.py`](../python/memory/observe.py) 采缓存命中。
- **语法校验质量门控（A5/#7 + B4/#4 + C3/#4）**：**不整项目 `tsc`**；改用**按语言单文件 lint/快速诊断**（TS/JS→`eslint`/`prettier`，Python→`ruff`，Java→轻量 parse），且只统计**增量误差**（改动前 vs 改动后该文件错误数差，避免存量错误误判）；失败在 journal 记 `syntax_valid: false`。校验失败 → **把错误作为负反馈拼进 `JournalQuery`**，让 Agent 自己修正再提交，**不机械重放 Patch Task**。**别为了省上下文，子 agent 乱改导致编译不过还不测。**

**离线分析器**（读 ledger + audit 写事件）产出 `§7.3` 六项 + **语法错误率**。据此判定 `§7.4` 门控：**要不要上 store、handoff、News**；并**按语法错误率校正**：若语法错误率 > 20% → **不扩大并发，反而增加子 agent 上下文**。

**关键口径（避免误判）：**
- **碰撞率定义（C5/#6）**：碰撞率 = **发生 StaleConflict 的任务数 / 总写提交数**；**同任务多次 Patch 重试只算一个冲突任务**，重试后的提交不算新碰撞。
- **缓存命中率只算 input（C6/#7）**：命中率 = `input_cache_hit / (input_cache_hit + input_cache_miss)`；**output token 单独统计、不入命中率**（输出不可缓存）。
- `task_batch_id` 用 submit 边界划分，否则 token-per-task 无意义。
- 忽略会话首轮 KV（必 miss）+ 取多轮中位数。

---

## 7. 风险与应对（`§7.2` + 本阶段新增）

| 风险 | 应对 |
|---|---|
| **鸡生蛋**：没有真子 agent 就测不了碰撞 | P0 先建地基（最小 harness），P1 再测；或用"存量单 agent 的写入集中度"当碰撞**代理指标** |
| 子 agent 一旦启用就失控（乱改文件） | P0 就上**每文件单写者队列 + content-hash 校验**；memdir 只读；`§5.6` 前置不全不启用 `AgentTool` |
| **Stale 冲突后无限重跑**（A1/#2 → C7/#8） | **P0 记日志为失败**；P1 起生成**修补任务（Patch Task）** + 注入 `recent_changes`，重试 ≤3 |
| **悬死 agent 阻塞依赖**（C4/#5） | 每任务 `started_at` + `timeout_s`；后台巡检超时 → 标失败(reason=timeout) 并释放 worker |
| **坏依赖导致调度死锁**（C8/#9） | 分解后校验：无环 + 依赖存在 + 所需工具合法（P0 人工 / P1 规则校验） |
| **调度状态丢失**（A2/#3 → C7/#8） | P0 **best-effort 轻量写**；P1 重启恢复/断点续跑 |
| **缓存前缀被动态内容破坏**（A3/#4） | 动态**只能 append 在尾部**；CI 加"前缀哈希不变性"单测 |
| 短上下文隔离过头 → 子 agent 信息不足、干砸 | 给"裁剪工具 + 任务 prompt + 近期变更注入"的平衡；**按 `required_tools` 建白名单（C2/#3）**，别让子 agent 缺 `JournalQuery` |
| **递归 Agent 失控**（A8/#8） | `_depth` 参数 + depth≥1 时从 system prompt 移除 `_agent` 工具；P0 `max_depth=1` |
| 侧链数据不回传 → 主会话拿不到结论 | 回传**一条** `tool_result`(结论/改过的文件/关键词)；不写主 JSONL |
| 打点开销污染测量 | 用已有 append-only audit、不进热路径最贵处；打点成本可忽略 |
| 多 agent 成本爆炸（共享前缀仍 N× 独特上下文） | 短上下文 + 共享前缀；子 agent 寿命短、一般碰不到 C2 |
| **调度器与编排器资源死锁**（B1/#1） | `scheduler.py` **独立 worker 池**、与主循环池物理隔离；子 agent `_depth>=1` 不得等跨 Agent 任务（只做纯工具），杜绝嵌套等待 |
| **侧链磁盘堆积**（B6 + C9/#10） | `scheduler_state.json` 记 `parent_session_id` + 会话心跳判活跃；会话结束删其全部侧链；**任务完成即清理自己的侧链**（可配 keep-for-debug） |
| 与 `orchestration.py` 混淆 | 它只管**单 agent 一轮内**的并发分区；跨 agent 走**每文件单写者队列 / journal**，别塞进 orchestration；且**两者用独立 worker 池** |

---

## 8. 验收 / 里程碑

**P0 验收（能跑起来的基座，按 C7/#8 收敛）：**
- [ ] 能 spawn ≥2 个子 agent，各带 `agent_id`
- [ ] 子 agent 历史进侧链，**不**append 主 JSONL
- [ ] 子 agent 上下文**不含**主会话全文（短上下文隔离生效）
- [ ] 两个子 agent 并发改**同一路径** → 其中一个拿到 **stale 冲突**，不静默覆盖；P0 记日志为失败（不自动重试）
- [ ] 每次写成功记录进 journal，`recent_changes` 能查到"刚被谁改过"
- [ ] 调度器：`DAG 拓扑` + `并发上限` + `文件级冲突` + **`required_tools` 建工具白名单**（C2/#3）+ **任务超时标失败（C4/#5）**；`scheduler_state.json` **best-effort** 写（崩溃即弃、只留日志）
- [ ] 子 agent 无 `_agent` 工具（depth≥1），`max_depth=1` 生效（A8/#8）
- [ ] **写后按语言单文件 lint + 增量误差**，失败记 `syntax_valid:false` 且不静默（A5/B4/C3）
- [ ] **动态只 append 尾部**——前缀哈希不变性 CI 单测过（A3/#4）

**P1 验收（数据可测 + 补 P0 缺失的稳健性）：**
- [ ] 测量打点齐（`task_batch_id`/`agent_id`/`path`/`input_cache_hit`/`input_cache_miss`/碰撞标记）
- [ ] 离线分析器出 `§7.3` 六项 + `§7.4` 门控结论（含 C5 碰撞率 / C6 input 命中率定义）
- [ ] Stale → **Patch 重试（≤3）+ 重启恢复/断点续跑**（由 P0 移到 P1）
- [ ] 分解 LLM 校验（C8：schema 约束 + 无环/依赖存在校验）

**P2 验收（在数据支持下）：**
- [ ] 语义重叠显式抛出（不静默）
- [ ] News/交接 实测省 token（否则不够格上）

---

## 9. 一句话

> 普通多 Agent 协同不是"把 N 个 agent 丢进一个 workspace 就完事"——**没有 LLM 协调者，就用确定性调度器（任务队列 + DAG + 写范围冲突 + 并发上限）+ 确定性共享原语（每文件单写者队列 + content-hash 版本校验 + journal + 短上下文隔离）替代它**。先拼成 P0 基座，在 `§7` 数据门控下跑通、测准，再决定要不要往上叠 store/handoff/News。

---

## 附录 A：P0 技术债与必做清单（8 项，按优先级）

> 来源：P0 设计审查（8 条）。这 8 条决定 P0 是"能跑"还是"玩具"，按优先级排。

### 必须补（否则崩溃即废）

**A1 / 审查 #2：Stale 冲突后的重试 / 修补任务**
调度器收到 `StaleConflict` **不直接重放原任务**（否则 agent 仍带旧上下文无限重跑）。改为生成**修补任务（Patch Task）**：`desc = "merge 或 re-apply 你的改动到最新版本"`，并**强制注入 `recent_changes`** 给该子 agent。重试上限 **3 次**，超过则宣告失败并告警。落到 `scheduler.py`（§2.4）。

**A2 / 审查 #3：调度器状态持久化**
新增 `{workspace}/.xeyo/scheduler_state.json`，**每次**状态变更（待办/运行中/完成/失败）**原子写入**。重启时检测该文件，让用户选"继续 / 放弃"。**这也是 P2 测"完成率"的必要基础**（否则崩溃的任务算未完成还是失败说不清）。落到 `scheduler.py`（§2.4）。

### 强烈建议（否则 P1 数据全是噪音）

**A3 / 审查 #4：缓存拼接顺序**
**强制**：`[固定 System] + [固定 ToolSchema]` 必须**严格连续、置于最前**；所有动态内容（任务 prompt / 近期变更）**只能 append 在最后**。动态插进中间 → 前缀哈希全变 → 全部 miss（比不共享更贵）。**P0 单测 + CI：加"前缀哈希不变性"测试**，一有人把动态塞中间就报错。落到 `query_engine.py`（§2.3）。

**A4 / 审查 #5：子 Agent 最小工具集**
P0 明确基线：`ReadFile + WriteFile + EditFile + JournalQuery(只读最近变更)`。其余高级工具（搜索 / AST / 终端）**默认禁用**，仅当任务 scope 显式申请才开。写进 `catalog.py` 的 `SUBSET_TOOL_WHITELIST`。落到 `catalog.py`（§2.3）。

### 测量基石（防优化方向跑偏）

**A5 / 审查 #7：语法校验质量门控**
写成功后**强制触发一次轻量语法校验**（tree-sitter 或对改动文件 `tsc --noEmit`），失败则在 journal 记 `syntax_valid: false`。P1 离线分析器统计**语法错误率**；若 > 20% → **不扩大并发，反而增加子 agent 上下文**。落到 `write_store.py` + `journal`（§6）。

### 其余必做（也重要）

**A6 / 审查 #1：scope 粒度（P0 无 AST）**
P0 scope **降级为"文件级"**：明确 P0 仅保证"**不同文件并行，同文件串行**"。调度器冲突检查内加**可选 `line_start/line_end` 字段**（简陋但优于纯字符串）：若两任务行区间**间隔 > 50 行**，允许并行（即使同文件）。写入 P0 风险附录（§2.4）。

**A7 / 审查 #6：§7 数据门控阈值**
给 `28 §7.4` 补硬性参考门槛（可后调整，但必须有）：
- 碰撞率 > **15%** → 必须上 write-through store（否则浪费太严重）。
- 同文件串行等待平均耗时 > 单任务推理耗时 × **1.5** → 必须上 handoff 交接（否则并发收益为负）。
- 缓存命中率 < **30%** → 查前缀稳定性，否则禁止宣称"共享前缀省钱"。

**A8 / 审查 #8：递归 Agent 失控（安全）**
`AgentTool.execute()` 加 `_depth` 参数，spawn 时 depth+1，**构建子 agent system prompt 时动态移除 `_agent` 工具（depth≥1 时）**。P0 **硬限制 `max_depth = 1`**。落到 `agent_tool/`（§3.2）。

---

## 附录 B：P0 技术债补丁（6 项，第二轮审查）

> 来源：第二轮 P0 设计审查。在第一轮 8 项（附录 A）基础上补，多数是对 A 项的修正/收紧，落地时**以 B 为准**。

### 边界 / 资源（防死锁与脏写）

**B1 / #1：调度器 vs 单 Agent 编排器「资源池隔离」**
[`orchestration.py`](../python/tools/orchestration.py)（单 Agent 一轮内的并行工具调用）与 `scheduler.py`（跨 Agent 任务）**不得共享同一 worker 池**。`scheduler.py` 有自己的**专用 worker 池**（与主循环池**物理隔离**）。**约法**：子 Agent `_depth>=1` 时，其内部**绝不等待跨 Agent 的 DAG 任务**，只允许纯工具操作——从源头杜绝嵌套等待死锁（写进 `scheduler.py` + `agent_tool/` 的注释与约束）。

**B2 / #2：多文件"原子事务"（P0 限定单文件，防脏写）**
P0 把"一次事务"**严格限定为单文件**；多文件强一致 → **强制拆成多个串行子任务**。`write_store.submit_transaction(files)`：若传多文件，**先全部校验 `base_hashes`、再全部落盘（预检）**，任一冲突 → **整体拒绝，不做脏写**。**禁止**落盘第一个文件后才在第二个上发现冲突（否则 A 已写、B 冲突、A 回滚不了，"全有或全无"沦为空谈）。

### 语义 / 正确性（防虚假安全感、防误杀）

**B3 / #3：A6「行区间并行」降级为性能提示，不做并行安全依据**
P0 行区间启发式**不可作为并行安全依据**（物理间隔 ≠ 语义无关；删 49–51 行会漂移，改函数签名 100 行外也会逻辑错）。改为：调度器**日志标"已启用推测并行"**，**最终写序仍严格走单写者串行队列**；两任务行区间**相近（<100 行）→ 自动退化严格串行**。**P0 风险附录红字**："行区间并行仅为极端理想情况，真实语义冲突由 P2 AST 接管，**P0 宁可串行也不静默漏错**。"

**B4 / #4：语法校验（A5）防误杀、防机械重放**
校验**只针对改动文件的局部 AST 节点**（tree-sitter 解析变更的函数/类体），或 **git stash 暂存原文后校验增量**，**不整项目 `tsc`**（避免存量语法错误让错误率虚高、误触发"增加上下文"）。校验失败 → **不机械重放 Patch Task**，而是把**语法报错作为负反馈拼进 `JournalQuery`**，让 Agent 自己修正后再提交（落到 `write_store.py` + `journal`）。

### 门控 / 运维（防教条、防堆积）

**B5 / #5：§7 门控阈值改为「环比恶化率」+ 建议性诊断（A7 修正）**
硬阈值（碰撞>15% 等）易"过拟合"（重构期碰撞率天然高但业务价值大，强行上 store 拖慢迭代）。改为**环比恶化率**（如本周碰撞率较上周**飙升 50%** → 告警）；并把**门控降级为"建议性诊断报告"而非自动熔断**，最终由开发者结合业务上下文决策。落到 `28 §7.4` + `§6` 的离线分析器输出。

**B6 / 补丁：侧链数据垃圾回收**
- `scheduler_state.json` 加 `cleanup_ttl`（默认 **7 天**）；P1 离线分析器运行前自动清理超 TTL 的侧链文件。
- 回传给主会话的 `tool_result` **必须带 `agent_id`**；若主会话结束未消费该侧链 → 标**孤儿并删除**。防止 P0 大量 spawn 时 `.xeyo/sessions/.../agents/*.jsonl` 堆积。（落到 `scheduler_state.json` + `record_transcript` 侧链回收。）

---

## 附录 C：第三轮优化决策记录（以本附录为准，覆盖上文冲突项）

> 来源：第三轮审查。带 ✅ 采纳 / ⚠️ 精化采纳；**若与 A/B 冲突，以 C 为准**。

**C1 / #2（✅，覆盖 B3）：移除行区间并行**
有每文件队列后，行区间启发式**冗余且误导**。调度器冲突检查**只留文件级**：不同文件→并行；同文件→调度层不并行（防白做）+ 写队列串行兜底。**删除 `lines` 字段**；真实语义冲突由 P2 AST 接管。**B3 作废。**

**C2 / #3（✅）：`required_tools` 声明工具**
任务清单（`WorkingSnapshot.todos`）加 `required_tools`，由分解 LLM 生成时声明。调度器按任务动态构建子 Agent 工具白名单（基线 `Read/Write/Edit/JournalQuery` + 所需高级工具），**不暴露 `_agent`**。比"显式申请"更自动化、权限刚好。（落 §2.3/§2.4/§5）

**C3 / #4（⚠️，精化 B4）：语法校验按语言单文件 lint + 增量误差**
tree-sitter 抓不到类型错误；tsc 被存量错误污染。改**按语言单文件 lint/快速诊断**（TS/JS→`eslint`/`prettier`，Python→`ruff`，Java→轻量 parse），且只统计**增量误差**（改动前 vs 后，避免存量误判）；失败正文作为负反馈拼进 `JournalQuery`，Agent 自行修正再提交。**别整项目 tsc。**（落 §6/§5）

**C4 / #5（✅）：任务超时**
记每任务 `started_at` + `timeout_s`（默认 300）；后台巡检，超时任务标失败（reason=timeout）并释放 worker。防悬死 agent 阻塞依赖任务、耗尽 worker。（落 §2.4/§5/§7）

**C5 / #6（✅）：碰撞率明确定义**
碰撞率 = **发生 `StaleConflict` 的任务数 / 总写提交数**；同任务多次 Patch 重试**只算一个冲突任务**，重试后提交不算新碰撞。（落 §6/28 §7.4）

**C6 / #7（✅）：缓存命中只算 input**
打点独立记 `input_cache_hit`/`input_cache_miss`；命中率 = `input_hit/(input_hit+input_miss)`；output 单独统计、不入命中率（不可缓存）。（落 §6/28 §7.4）

**C7 / #8（⚠️，平衡 A2/A1 优先级）：P0 收敛**
P0 调度器只做 **DAG + 并发上限 + 文件级冲突**；**stale→P0 记日志为失败、P1 接 Patch 重试**；持久化做**轻量每次状态写 best-effort**，**重启恢复/断点续跑 → P1**（P0 实验环境重启少，允许状态丢失、只留日志）。P0 更快验证"多 Agent 共享 workspace"基础。

**C8 / #9（✅）：分解 LLM 约束 + 校验**
附**任务清单 JSON Schema** + **分解 prompt 样例**，严格约束输出；**分解后审核**（P0 人工 / P1 规则校验：无环、依赖存在、所需工具合法）——避免坏依赖 → 调度死锁。

**C9 / #10（✅）：侧链孤儿触发时机**
`parent_session_id` + **会话活跃心跳**（最后心跳时间）判"会话是否结束"；会话结束 → 删其全部侧链。且**任务完成即清理自己的侧链**（可配 keep-for-debug），防长期会话无限堆积。（细化 B6）
