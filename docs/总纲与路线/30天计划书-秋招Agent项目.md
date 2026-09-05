# XEYO 30 天计划书（秋招Agent项目）

> **【已废弃】** 本文被 [00-总计划书-可上线路线图.md](./00-总计划书-可上线路线图.md) 替代（2026-08-08）。  
> 请勿再按本文排期；分阶段开发请打开 `task0`～`task7`。  
> 下文仅作历史存档。

---

# XEYO 30 天计划书（秋招个人项目）

> 仓库：`D:\lea\XenYon code`  
> 更新日期：2026-08-07  
> 定位：**可演示、可讲解、有架构亮点的编码 Agent**，参考 Claude Code 思想，**不是**源码移植。

---

## 0. 目标与非目标

### 0.1 最终要证明什么（面试叙事）

1. **Agentic 主循环**：消息历史 → 调模型 → 工具调用 → 结果回流 → 中断/预算 → 多轮续聊  
2. **分层架构**：前端只负责交互；Python 负责编排；副作用工具可替换（后期 Java 21 虚拟线程）  
3. **可演示产品**：桌面/网页 UI 能流式对话、能跑真实工具、能 Ctrl+C 中断  
4. **差异亮点（最后一周贴）**：Java VT 工具运行时 / 工作区权限沙箱 / 会话可恢复 三选一做深

### 0.2 明确不做（30 天内）

| 不做 | 原因 |
|---|---|
| 逐行移植 `QueryEngine.submitMessage` 全阶段 | TS 壳太重，与秋招 ROI 不符 |
| 25 个工具全部实现 | 空壳无说服力 |
| MCP / 多 Agent / Skill / PlanMode / LSP 全套 | 时间不够 |
| 企业级跨平台 permissions/filesystem | 先 Windows + cwd 沙箱即可 |
| 读懂 Claude 全部 SDK / compact / hooks | 只保留状态机认知 |

### 0.3 成功标准（第 30 天）

- [ ] 双击启动 → UI 打开 → DeepSeek 流式对话  
- [ ] 至少 **Glob + Read + Bash（或 Shell）+ Echo** 可用  
- [ ] 中断、max_turns、两轮续聊可演示  
- [ ] README + 架构图 + 30 秒演示脚本  
- [ ] **一个**差异亮点可讲清设计取舍  
- [ ] `pytest` 核心用例全绿  

---

## 1. 现状盘点（以仓库为准）

### 1.1 总览

| 切片 | 成熟度 | 说明 |
|---|---|---|
| `query_loop` / abort / budget | **可用** | 主循环骨架已在 |
| `QueryEngine` | **阻塞** | Config 缩进错乱、`submitMessage` 嵌套进 `__init__`、调用方要的是瘦身 `submit` |
| permissions | **阻塞** | `__init__.py` 导出了 `filesystem.py` 里不存在的符号 → **整包 import 失败** |
| DeepSeek / OpenAI 兼容客户端 | **可用** | 客户端与 UI 设置已接 |
| FastAPI `server` + CLI UI | **半可用** | UI/SSE 面完整，被引擎 import 卡住 |
| 工具 | **部分** | 已启用：echo / getTime / Glob；其余多为 stub |
| Java ToolRuntime | **空壳** | 仅有接口/空类 |
| `docs/` | **空** | 本计划书为第一份 |

### 1.2 当前启动链（目标形态）

```text
start-xeyo.bat
  → py -3.11 -m server   (FastAPI :8000)
  → npm run tauri:dev 或 npm run dev  (CLI UI :5173 → 代理 /v1 → 8000)
  → POST /v1/chat/completions 流式
  → SessionPool → QueryEngine.submit → query_loop
```

**现状：引擎 import 失败时，整条链不可用。** 第一周唯一任务是打通这条链。

### 1.3 资产清单（已经有、别推倒重来）

**保留并依赖：**

- `python/engine/query_loop.py` — 核心循环  
- `python/engine/abort.py` / `budget.py`  
- `python/session/message_store.py` / `state.py`  
- `python/model/deepseek.py` / `openai_compat.py` / `fake.py`  
- `python/tools/catalog.py` + echo / getTime / Glob  
- `python/server/app.py` + `session_pool.py`（修好引擎后即可用）  
- `gui/` React UI（Composer / MessageList / streamChat）  
- `python/tests/*`（引擎修好后恢复跑）

**冻结（先别加功能）：**

- 巨型 Claude 风格 `QueryEngineConfig` 字段表  
- 大量 `tools/*_tool.py` stub  
- `java/**` 空壳（Week 3 前不动）  
- `permissions` 企业级跨平台抄写  

---

## 2. 架构原则（写代码时的北极星）

```text
┌─────────────────────────────────────────┐
│  cli (React / Tauri)                      │  输入、流式渲染、设置、中断按钮
└──────────────────┬──────────────────────┘
                   │ HTTP + SSE (/v1/...)
                   ▼
┌─────────────────────────────────────────┐
│  python server + QueryEngine              │  会话、system、submit
│         └─ query_loop                     │  模型 ↔ 工具 while
│         └─ ToolRegistry (ENABLED only)    │
└──────────────────┬──────────────────────┘
                   │ 后期：JSON-RPC（可选）
                   ▼
┌─────────────────────────────────────────┐
│  Java 21 VT ToolRuntime（差异亮点）        │  Read/Bash 等副作用
└─────────────────────────────────────────┘
```

**主循环只认瘦身协议（对齐 Claude 阶段 ⑥，不是 ①～⑦ 全抄）：**

```text
submit(text):
  abort.reset()
  budget.reset_for_submit()
  messages.append(user)
  system = build_system(...)   # 可用固定字符串起步
  async for ev in query_loop(...):
    yield ev                   # delta / tool_call / tool_result / final / stopped
```

---

## 3. 30 天排期

> 每天建议投入：3～5 小时有效编码。周末可加演示与文档。  
> **每日完成定义：有可运行证据**（命令输出 / 截图），不是「读了源码」。

---

### Week 1 — 解阻塞，恢复可演示主循环（Day 1～7）

**主题：先能聊，再谈完美。**

| Day | 任务 | 验收 |
|---|---|---|
| 1 | 修 `permissions`：删掉不存在的导出，或补最小 `PermissionDecision`/`check_*`，保证 `import tools.catalog` 成功 | `py -3.11 -c "from tools.catalog import build_default_registry; print('ok')"` |
| 2 | **砍回** `QueryEngine`：删除半成品 Config 抄写；实现瘦身 `submit` / `interrupt` / `get_messages` / `build_default_engine` | `build_default_engine(model_backend='fake')` 可构造 |
| 3 | 对齐调用方：`session_pool`、`bridge`、`tests`、`smoke_engine` 统一走 `.submit()` | smoke 脚本跑通 echo |
| 4 | 装测试依赖并修红：`pip install pytest pytest-asyncio`；核心测试全绿 | `pytest -q` 绿 |
| 5 | FastAPI 通：`/health` + Fake/DeepSeek 一轮 SSE | curl 或 UI 收到流式字 |
| 6 | CLI 联调：设置里填 key → 普通问答 + `echo:hi` | 界面可见 tool 行与最终回复 |
| 7 | 演示脚本 + README 骨架：启动方式、架构图、当前能力列表 | 别人按 README 能跑起来 |

**Week 1 交付物：**

- [ ] 启动链端到端绿  
- [ ] 测试绿  
- [ ] 30 秒演示路径写进 README  

**Week 1 禁止：** 新工具、Java、抄 `submitMessage` 斜杠命令/transcript。

---

### Week 2 — 工具做深，不做全（Day 8～14）

**主题：4 个真工具 > 25 个空壳。**

| Day | 任务 | 验收 |
|---|---|---|
| 8 | `FileReadTool` 真实实现；启用进 `ENABLED_TOOLS` | 模型能读仓库内文件 |
| 9 | `GrepTool` 真实实现（可用 rg） | 按内容搜索 |
| 10 | `BashTool` 或最小 Shell（先 Python subprocess，限制 cwd） | 能跑只读命令如 `dir`/`rg` |
| 11 | 工作区权限 v0：cwd 内 allow，cwd 外 deny（读） | 越界路径报错可演示 |
| 12 | Glob 与权限/abort 小修；工具结果截断防爆上下文 | 大结果不卡死 |
| 13 | E2E：「找出某函数定义并读出上下文」演示剧本 | 剧本 3 步可复现 |
| 14 | 补测：工具注册、越界拒绝、query_loop+Read | pytest 增补 |

**Week 2 交付物：**

- [ ] ENABLED：`echo` / `getTime` / `Glob` / `Read` / `Grep` / `Bash`（或五选五）  
- [ ] SCAFFOLD 其余继续冻结  
- [ ] 权限一句话能讲清  

---

### Week 3 — 产品稳定 + 差异点开工（Day 15～21）

**主题：像产品，并开始「和别人不一样」。**

| Day | 任务 | 验收 |
|---|---|---|
| 15 | 中断路径：UI Stop → `/interrupt` → abort → `stopped` | 生成中可停 |
| 16 | 多会话 / session 隔离检查（SessionPool） | 两会话互不串历史 |
| 17 | 错误体验：无 key、模型 401、rg 缺失 → UI 可读错误 | 不白屏 |
| 18 | **差异点二选一开工（推荐 A）** | 见下 |
| 19 | 差异点继续 | |
| 20 | 差异点最小可演示 | |
| 21 | 文档：架构决策记录（ADR）1～2 页 | docs 可看 |

**差异点选项（只选一个做深）：**

| 选项 | 内容 | 适合你若… |
|---|---|---|
| **A. Java 21 VT ToolRuntime** | Python 编排，Java 执行 Read/Bash；JSON-RPC | 想打 Java 强项（**推荐**） |
| B. 会话可恢复 | transcript JSONL + `/resume` | 想讲工程完整性 |
| C. 权限模式 | default / ask（UI 弹一次确认） | 想讲安全产品感 |

**Week 3 禁止：** 同时开 A+B+C；回头抄 Claude permissions 全文件。

---

### Week 4 — 打磨、叙事、冻结功能（Day 22～30）

| Day | 任务 |
|---|---|
| 22～23 | 差异点收口 + 对比数据或截图（如 VT 并发、恢复前后） |
| 24 | UI 小修：工具状态、滚动、空态（不重构） |
| 25 | README 完整：动机、架构、演示、技术取舍、与 Claude Code 关系（参考非抄袭） |
| 26 | 面试口述稿：3 分钟 / 8 分钟两版 |
| 27 | 录屏 1～2 分钟；整理常见追问（主循环、工具协议、为何 Java） |
| 28 | 回归：启动、对话、工具、中断、测试 |
| 29 | 冻结功能；只修 P0 bug |
| 30 | 打包提交材料（仓库整理、`.env.example`、许可证、截图） |

---

## 4. 每周「最小演示剧本」

### 剧本 A（Week 1）

1. 启动项目  
2. 问：你是谁？  
3. 输入：`echo:hello`  
4. 看到 tool 与 `echoed: hello`

### 剧本 B（Week 2）

1. 「用 Glob 找出所有 `query_loop.py`」  
2. 「读取该文件前 40 行」  
3. 「在工程里 Grep `submit`」  

### 剧本 C（Week 3～4，含亮点）

- 若 Java：同一 Read 请求走 Java VT，日志打印线程名  
- 或：杀掉进程后 resume 仍看到历史  
- 或：读 `.env` 被 deny / ask  

---

## 5. 源码阅读策略（配合计划，避免再卡壳）

### 5.1 允许阅读的材料（按序）

```text
docs/task1/04-query-engine-flow.md   （若仍在 claude 仓库 docs）
  → 本仓库 query_loop.py（当作实现圣经）
  → query.ts 仅看 queryLoop 控制流（可选，1～2 小时）
```

### 5.2 禁止陷入的文件（30 天内）

```text
QueryEngine.ts 的 submitMessage 全量
permissions/filesystem.ts 全量
MCP / AgentTool / compact / hooks 全家桶
SDK entrypoints 细节
```

### 5.3 对照原则

| Claude | XEYO |
|---|---|
| `queryLoop` | `query_loop.py` |
| tools + canUseTool | `ToolRegistry` +（后期）简单 gate |
| REPL/Ink | `cli` React UI |
| ToolRuntime（概念） | 先 Python，后 Java VT |

**参考的是状态机与分层，不是 TS 语法与 SDK 形状。**

---

## 6. 目录与职责约定

| 路径 | 职责 | 本阶段 |
|---|---|---|
| `gui/` | UI、SSE 客户端、设置、会话本地缓存 | 维护，不大拆 |
| `python/engine/` | QueryEngine + query_loop + abort/budget | Week 1 修复核心 |
| `python/server/` | FastAPI 对外协议 | Week 1 打通 |
| `python/tools/` | ENABLED 真工具；SCAFFOLD 冻结 | Week 2 |
| `python/permissions/` | cwd 沙箱即可 | Week 2 |
| `python/model/` | DeepSeek / Fake | 维护 |
| `java/` | VT ToolRuntime | Week 3 可选亮点 |
| `docs/` | 计划、ADR、演示说明 | 持续更新 |

---

## 7. 质量门槛（每阶段出门检查）

**任何一天结束前至少满足一条：**

1. 新的自动化测试绿，或  
2. 手测剧本多一步可演示，或  
3. 文档多一节「如何运行 / 如何讲解」

**红线：**

- 不提交会破坏 `import tools.catalog` 的代码  
- 不新增 ENABLED 工具除非 `execute` 真实现  
- 不平行开启三个大功能  

---

## 8. 风险与应对

| 风险 | 应对 |
|---|---|
| 又想对齐 Claude 100% | 重读本文 §0.2；功能进「不做清单」 |
| Python 不熟拖进度 | 主循环/工具逻辑保持短函数；复杂 IO 丢给 Java 或 subprocess |
| DeepSeek 工具调用不稳 | Fake 保测试；演示备「echo + Glob」双剧本 |
| UI 花时间过多 | UI 只修阻塞演示的 bug |
| 30 天不够 Java | Week 3 改选 B/C，Java 留作「下一步规划」口述 |

---

## 9. 面试讲解提纲（提前写好）

1. **动机**：本地编码 Agent，弄清 agentic loop  
2. **架构图**：UI → Python 编排 → 工具（→ Java）  
3. **主循环**：画 while；说明停续条件  
4. **工具协议**：schema / execute / registry / ENABLED  
5. **取舍**：为何不移植 Claude 全量；为何 Python+Java  
6. **亮点**：你做深的那一个  
7. **局限与下一步**：权限企业级、MCP、compact  

---

## 10. 立即执行（今天 / 明天）

### Day 1 清单（按顺序打勾）

1. [ ] 修 `python/permissions`，恢复 import  
2. [ ] 确认：`py -3.11 -c "from tools.catalog import build_default_registry; print(build_default_registry().schemas())"`  
3. [ ] 备份并砍瘦 `query_engine.py`（可参考 `engine/_recovered_qe.py` 的形状，但修正包导入为 `engine.*` / `tools.*`）  
4. [ ] `build_default_engine(model_backend="fake")` + `async for _ in eng.submit("echo:hi")`  
5. [ ] 把本计划书进度表第一行标成「进行中」  

### 本周唯一口号

> **先绿起来，再变强；先主循环，再工具；先演示，再亮点。**

---

## 11. 进度跟踪表（自行勾选）

| 里程碑 | 计划完成日 | 状态 |
|---|---|---|
| M1 引擎可 import + submit | Day 3 | ☐ |
| M2 pytest 绿 + smoke | Day 4 | ☐ |
| M3 UI 流式对话 | Day 6 | ☐ |
| M4 四个真工具 + 沙箱 | Day 14 | ☐ |
| M5 中断/多会话稳定 | Day 17 | ☐ |
| M6 差异点可演示 | Day 21 | ☐ |
| M7 文档+录屏+口述 | Day 30 | ☐ |

---

## 附录 A — 与旧思路的切割

| 旧思路 | 新思路 |
|---|---|
| 读懂 `submitMessage` 再写 | 瘦身 `submit` = Claude 阶段 ⑥ |
| 工具目录先搭满 | ENABLED 少而真 |
| 权限抄 filesystem.ts | cwd allow/deny |
| 前后端并行大重构 | 固定 UI，只修引擎堵点 |
| 企业级 = 功能多 | 企业级感 = 边界清晰 + 可测试 + 可讲解 |

---

## 附录 B — 常用命令

```powershell
# 引擎
cd "D:\lea\XenYon code\python"
py -3.11 -m pip install -r requirements.txt pytest pytest-asyncio httpx
py -3.11 -m pytest -q
py -3.11 -m server

# 前端（另开终端）
cd "D:\lea\XenYon code\\gui"
npm run dev
# 或根目录
# start-xeyo.bat
```

---

**文档结束。** 执行时以 Week 1 Day 1 为唯一入口；完不成不进入 Day 2 的新功能。
