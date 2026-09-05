# LLM 调用前注入 · 选型冻结

> 状态：**已冻结 · 终稿**（2026-08-29）  
> 落地必须严格按本文件；与 [10-完整记忆体系](./10-完整记忆体系.md) §2.6 / §3.1、[11-记忆体系落地步骤书](./11-记忆体系落地步骤书.md)「送模型前那一行」对齐。

## 底座（不可改）

| 层 | 选型 | 说明 |
|----|------|------|
| 插入点 | **`run_pre_llm_inject`** | 每次 `model.stream` 前唯一调用前阶段；`query_loop._attach_turn_context` 只做薄封装 |
| 写入面 | **仅投影 T_now** | `append_text_blocks_to_last_user`；**禁止**改 MessageStore / JSONL / system 左段 |
| 左段纪律 | **本 submit 字节稳定** | Identity / CWD / 根 XEYO.md / Tool policy 只在 `build_system`；易变块一律右段 |
| 编排顺序 | Continue → Mode/Plan → Wrap-up/budget → Multi-Agent → Nested → Stale/Proposals → Memory | 预算裁剪时 Continue 优先，Nested 先于 Runtime notice |

### T_now 合同（严格）

```text
projected = project_for_model(...)          # C0/C1/C2，不改 JSONL
projected = run_pre_llm_inject(projected)   # 仅尾插 / 投影尾 user
api_messages = prompt.build(system, projected)
model.stream(api_messages, ...)
```

- **copy-on-write**：不得就地改入参消息对象。  
- **after_tools**（末条为 tool / tool_result）：必须先挂 `CONTINUE_AFTER_TOOLS`；**禁止**挂 Memory index / Stale / Proposals。  
- **after_tools 允许挂本轮新发现的 Nested**（Continue 已声明 background）；非 after_tools 挂全部 `loaded_nested_instruction_paths`。  
- 子 Agent / 短工人：`inject_instructions=False`（或 `include_memory_index=False` 且未显式开 instructions）→ 不挂 Nested / Stale / Proposals / Memory。

## 注入器表（全部采纳 · 终稿口径）

| # | 注入器 | 冻结口径 |
|---|--------|----------|
| 1 | Continue | 工具续写轮强制；声明后续块为 background，非新用户问题 |
| 2 | Mode / Plan | Ask / Plan 文案；Agent + approved plan 挂批准计划（上限 4k） |
| 3 | Wrap-up / budget | 硬停收尾；`runtime_notice` 单独块 |
| 4 | Multi-Agent hint | Composer chip 软提示；不裁工具、不拦收尾 |
| 5 | Nested XEYO.md | 扫投影**尾部**成功 Read → `note_read_path_for_nested`；`load_nested_instruction_text`（≤4k）；标题须含 **background only** |
| 6 | Stale instruction | `stale_instruction_notice(cwd, commit=False)`；**仅当最终进 T_now 后**再 `refresh_instruction_stamp` |
| 7 | Proposals digest | 非 after_tools；与 Stale 同闸 |
| 8 | Memory index | 非 after_tools；`memory_index_context_block`；不进 system 左段 |

### Nested 发现合同

- **不改 FileReadTool**：发现只在注入阶段扫投影。  
- 扫描窗口：投影尾部 `READ_SCAN_TAIL = 64`（禁止每轮全历史无界扫描）。  
- 成功判定：`tool_use.name == Read` 且配对 tool_result **非** `is_error`；`input` 缺失时可弱回退，不得把失败 Read 记入路径。  
- C2 / `try_extend_c2`：必须清空 `WorkingSnapshot.loaded_nested_instruction_paths`（与 `note_c2` 一致），下一枪按需再发现。

### 预算合同

| 常量 | 值 | 含义 |
|------|-----|------|
| `T_NOW_EXTRA_BUDGET` | 6000 | T_now 增量硬顶（字符） |
| `NESTED_MAX_CHARS` | 4000 | Nested 正文上限 |
| `NESTED_RESERVE_CHARS` | 2000 | 裁剪时 Nested 相对 notice 的优先意图（靠顺序落实） |

超出硬顶：截断并保留 Continue；禁止为塞 Nested 而改写 system 左段。

## 明确不做

- 用户脚本 `hooks.json` / UserPromptSubmit / PreToolUse 式外挂 hooks  
- 每轮自动注入 `git status` / 打开文件列表 / 墙钟日期进 **system 左段**  
- 用注入替换 `GetTime` 工具  
- 把 MEMORY.md 索引或 Nested 塞进 `assemble_system_prompt` 左段  
- after_tools 挂 Memory index（弱模型会当成新问题）  
- 失败 Read / 子 Agent 短上下文灌入主会话目录规则  

## 收益边界（冻结口径，勿对外夸大）

- **解决**：子目录 `XEYO.md` 进模型；Stale 可送达且不误刷 stamp；调用前逻辑单一插入点；C2 后不挂已滚出窗口的旧嵌套规则；KV 前缀不被易变块打爆。  
- **不解决**：不直接提高模型代码质量；弱模型仍可能忽略 Nested；空仓无探测文件时 Stale 无感。

## 落地入口

- `python/prompt/pre_llm_inject.py` — **真源**：`InjectContext` / `run_pre_llm_inject`  
- `python/prompt/turn_context.py` — Continue / `append_text_blocks_to_last_user` / mode blocks  
- `python/engine/query_loop.py` — `_attach_turn_context` 薄封装；`tools.cwd` 传入  
- `python/memory/instruction_maintain.py` — Nested 发现 / `stale_instruction_notice(commit=)` / stamp  
- `python/memory/working.py` — `note_c2` 清嵌套路径  
- `python/memory/runtime.py` — `try_extend_c2` 同步清嵌套路径；C2 后 `clear_instruction_cache`  
- `python/tests/test_pre_llm_inject.py` — 合同回归（时机 / 尾扫 / stamp commit / C2 清空）

### 已冻结补充口径（2026-08-29）

- `inject_instructions: bool | None`：`None` → 跟随 `include_memory_index`；显式拆开工人「短上下文」与 Memory 开关。  
- 注入路径异常：`logging.debug(..., exc_info=True)`，禁止静默裸 `except: pass` 无日志。  
- Stale：**先 peek 再 commit**；trim 后未进 blocks 则不得 `refresh_instruction_stamp`。

## 验收（合入门）

```text
cd python
python -m pytest tests/test_pre_llm_inject.py tests/test_instruction_maintain.py tests/test_main_loop_three_cuts.py -q
```

手工：workspace 下 `pkg/XEYO.md` + `Read pkg/foo.py` → **同一枪 after_tools 续写**的投影 T_now 含 Nested；system 左段字符串相对本 submit 开头不变；JSONL 行数/内容不被注入改写。

## 修订 P1（2026-09-01 · 分仓 / 门控 / 硬顶 / 标签）

> 起因：弱模型（glm-4.5-air）把尾插 Memory index 当成模糊请求「帮我修改」的任务对象（事故会话 sess_mtiche8l）。P0 已把索引块一行化 + 围栏 + 去条件化（`memory/runtime.py::memory_index_context_block`）；本修订为结构层根治。

- **F3 性质标签（治理位）**：块以 `(KLASS_DIRECTIVE | KLASS_EVENT | KLASS_INVENTORY, text)` 装配（`pre_llm_inject.py`）。**新增块必须声明类别**，遗漏按 INVENTORY 处理（最保守）。directive=行为指令（贴生成点，绝不裁剪）；event=事件通知，部分含 drain 语义——**绝不门控、绝不裁剪**（notices/settlements/reconcile 取走即清，静默即永久丢失）；inventory=参考数据。
- **A1 分仓**：fresh-user 轮 inventory **前插**到末条 user 文本之前（`prompt/turn_context.py::prepend_text_blocks_to_last_user`，copy-on-write）——生成点紧邻用户请求，recency 为用户服务；块靠 P0 围栏与「background only — NOT the user request」头防归属误读。directive/event 仍尾插。**after_tools 轮维持原尾插合同**（Continue 在前，单插合成 user）。
- **D1 轮型门控**：模糊指代型短追问（**有上文** + ≤24 字 + 无路径/代码标记 + 含指代/确认词，见 `_is_vague_referent_turn`）静默本轮全部 INVENTORY。首轮不门控（无从指代）。fail-open：误判只丢一轮参考数据。
- **F1 真硬顶**：原 bypass 组（compact / mcp / reconcile / peer / conflict / preview / snapshot / settlements / goal）全部纳入预算。directive/event 全保（构造处各自有界）；inventory 受双闸 `min(T_NOW_INVENTORY_MAX=2500, T_NOW_TOTAL_BUDGET=6000 - 指令已用)`，超限截断（带 …）。`_trim_blocks_to_budget` 保留兼容（仅测试/脚本直调）。
- **KV / JSONL 不变量不变**：所有改动仍只发生在投影尾部消息内，copy-on-write，左段与历史字节不动。
- 现状备注：peer 块暂标 EVENT（notices 有 drain 语义）；「跨对话话题工具化」**已落地**（commit 266e067）：peer 块缩为 notices + beacon + 禁答行，话题明细走 Memory(action=peers / search)（见 `docs/交接/peer-topics-toolization-handoff.md`）。
- 回归：`tests/test_p1_block_placement.py`。

### 批次 1 追加（2026-09-01 · 块审计减法）

- **Proposals digest 下线推送**：模型对候选晋升无可执行动作（NightShift / 人工确认），判据「模型能否据此行动」否决。拉取通道：`/proposals` slash 命令；`Memory(action=search)` 结果附带候选计数行（`tools/memory_tool/memory_tool.py::_proposals_notice_line`，P1 批次1 同步落地——工具化 commit 未含此项）。
- **上一轮思考回顾限 after_tools**：fresh-user 轮里它是上一个任务的推理残留，注入造成旧任务锚定污染（与指代劫持同族）；工具循环续写场景才是设计目的。
- **Runtime budget notice 保留（审计更正）**：`budget.consume_runtime_notice()` 是 consume-once 队列（budget.py:167），本就是事件型一次性通道而非每轮常驻——维持原状，不并入 Wrap-up。
- 42 号 `pending_jobs_block` 并行接入确认：DIRECTIVE（一次性待领信息，drain 语义），在 D1 门前装配，不受门控影响。

### 批次 3 追加（2026-09-01 · Memory index 退役）

- **索引块不再推送 T_now**（事故源头块退役）：能力宣告住 Memory 工具 description（新增静态召回指引 "call it first before answering questions that depend on prior context, user preferences, or earlier decisions"）；检索走 `Memory(action=search)`（跨会话 session notes + 提案计数行）。
- `memory_index_context_block` / `_append_memory_index` 保留（脚本与评测用）；`query_loop._content_parts` 的 `# Memory index` 统计前缀保留（生产路径恒 0，无害）。
- `include_memory_index` 字段保留兼容（决定 `inject_instructions` 默认值），不再挂载任何块。

### 批次 2 追加（2026-09-01 · Nested 限窗）

- **fresh-user 轮只注入「目录包含尾窗触碰文件」的已加载嵌套规则**（`_nested_paths_for_touched`）：触碰文件在其规则目录子树内即命中（pkg/sub/x.py 恢复 pkg/XEYO.md）；滚出尾窗（READ_SCAN_TAIL=64，成功 Read/Write/Edit）静默，再次触碰自动恢复。挂载集合不淘汰，仅注入过滤。
- after_tools 分支维持原合同（本轮新发现 Nested 全挂）。
- 语义耦合：D1 模糊轮静默 inventory 在限窗前仍生效——「继续改」类短追问拿不到 nested 属预期。

### 批次 4 追加（2026-09-01 · Approved plan 首写收敛）

- `approved_plan` 本就是 query 循环局部变量（跨 submit 重建 None）；批次4 在同 query 内加首写收敛——工具结果落库后 `approved_plan_decays_on(tu.name, is_error)` 判定，首次成功 Write/Edit/NotebookEdit 即清空，后续调用不再重发计划块（正文已在批准轮历史）。
- 写失败不收敛；纯读型计划在 query 生存期内保持注入（预算硬顶兜底）。

### 批次 5 追加（Approved plan 两档化 + 上一轮思考回顾默认关）

- **Approved plan 两档化**：批4 的"清空"改为"切换"——首写收敛后 `approved_plan = None` 且 `plan_pointer = True`，T_now 改挂 ~110 字符「实施中」指针块（`prompt.turn_context.PLAN_POINTER_BLOCK`，InjectContext.plan_pointer 贯通），正文仍以历史批准消息为准；两档文案均含**证据优先豁免条款**：`计划是执行蓝图：与最新工具结果或新证据冲突时，以证据为准，并就偏差做简短说明。`（弱模型/强模型共用的旧计划锚定风险治理）。
- **上一轮思考回顾默认关**：捕获侧门控（query_loop `reasoning_tail_enabled()`）默认**不捕获不注入**；开关为会话级模式（`ChatCompletionRequest.reasoning_tail` → T31 durable 模式链路 → `set_reasoning_tail_enabled`），优先级 会话/请求显式 > `XEYO_REASONING_TAIL` 进程默认；**子代理不继承**（`not in_subagent()`，T14 净化清单精神）。after_tools 限性与 fresh-user 不注入语义不变。

### 修订 2（2026-09-04 · 方案 A 环境声道：伪造 tool 对根治说话人混淆）

实测漂移事故（会话 sess_mtlpmznl）确认三类漂移：说话人混淆（模型把 T_now 块当作用户贴文）、
元叙事税（模型多轮自述"这段是注入内容"）、跨任务锚定。格式路线（[system-background] 标记 +
--- 分隔符，方案一/三）只能降概率，不能归零——**任何进入 user 消息层的注入文本都无法在结构上
与用户意图隔离**。本修订把注入内容整体换出 user 消息层：

- **新默认策略 `env_channel`**（`python/prompt/t_now_strategy.py`）：装配产物（kept 全部块）
  经 `format_env_notice` 加环境头（`[system-environment]`，纯状态陈述、不含行为引导词）后，
  装进一对**仅存在于投影**的消息尾插：`assistant(tool_use xeyo_env_notice) → user(tool_result)`。
  - 零额外往返（引擎写历史，模型无需先调工具——区别于"强制工具调用"方案）；
  - tool_result 为模型 RL 训练出的环境数据声道，说话人混淆在消息结构上不可能发生；
  - 尾部追加，KV 前缀逐字节不动（与 legacy 等价，"禁插 system 左段"铁律维持）；
  - **绝对红线延伸**：伪对不进 MessageStore / JSONL / proj_cache（三者均在注入点之前）；
    伪对工具名不注册进 tools 数组（schemas 会话内冻结不受影响）。
- **回退档 `legacy`**：原行为（bg_wrap + 末条 user 尾插，P1/A1 分仓合同保留）。三档策略
  （`set_t_now_strategy` > `XEYO_T_NOW_STRATEGY` > env_channel）+ 运行时回退：结构类 4xx
  （400/404/405/413/415/422，排除 402/429/5xx）且零 chunk 时，记进程级备忘（provider:model 粒度）
  并当场以 legacy 重建重试。`prefill` 预留档（尾部 assistant 预填充，厂商容忍度实测通过前回落 env_channel）。
- **不再需要的方案**：强制工具调用（其环境声道收益已被伪对零成本获得）；"末条 user 内部分仓"
  （A1 分仓退役——用户消息不再被任何注入块夹持，仅 legacy 档保留该合同）。
- **装配层不变**：D1 门控 / F1 硬顶 / F3 标签 / Nested 限窗 / 事件不门控 / plan 收敛等全部
  在 `kept` 之前完成，与声道无关；换的只是送达通道。
- **厂商兼容面**：凡支持 function calling 的 OpenAI 兼容 chat 模型均接受伪对（历史 tool 消息
  不校验工具名归属，只校验 id 配对——伪对天然良构）；不支持 tools 的模型 XEYO 本就无法运行，
  无需考虑。回退路径即 legacy，可靠性下界=改动前行为。
- **验收**：`tests/test_t_now_env_channel.py`（伪对构造 / 双声道分派 / 不落库防线 / L404 环境头
  回归锚 / normalize 转良构 tool 对 / unsupported 回退解析）、`test_cache_prefix_invariant.py`
  （B/C/D 断言双声道参数化）、`test_p1_block_placement.py`（钉 legacy 合同）。
  关联 228 测试全绿（2026-09-04）。
