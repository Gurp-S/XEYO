# P0/P1 冒烟测试交接（本会话产物 → 下会话）

> 交接时间点：已完成"Playwright 全栈 + 保留 jsdom"的决策，下会话要执行
> ①把 jsdom 组件集成补成 Playwright 全栈（真浏览器+真后端）
> ②保留 jsdom 用于快速测试
> ③对 P0/P1 做完整冒烟测试。
> 本文件是给下一个 agent 的**自包含交接提示词**，可直接粘贴；同仓立即可读。

---

## 0. 一句话总目标

把已搭好的服务器端到端冒烟套件（**已跑通 19 个场景 / 62 断言**）扩展成：
- 保留 `scripts/smoke_p0p1/`（服务器端、真引擎+mock LLM，已绿）；
- **新增 Playwright 全栈层**：真实 Chromium + 真实 Vite dev GUI + 复用同一个隔离后端，验收**前端 UI 消费**那半边；
- 保留 **jsdom/vitest** 做快速回归，不动它；
- 最后对 P0/P1 给出**完整**冒烟（服务器端 + GUI 全栈 + 手工清单）。

## 1. 已建成的服务器端冒烟（在 `scripts/smoke_p0p1/`，勿重写）

- `mock_llm.py` —— 脚本化 OpenAI 兼容上游，流式 SSE；**按"请求是否携带 tools"区分主轮次 vs 旁路**（标题增强等旁路不带 tools，不消费场景脚本）；每个请求落盘 `requests.jsonl`。
- `harness.py` —— 自启真引擎：`python -m server`（sv.executable），随机端口，`XEYO_ALLOW_LOCAL_MODEL=1`；等 `/health`；驱动 `POST /v1/chat/completions`（SSE）+ **自动放行 `permission_pending`**；提供 `api / create_session / read_messages / get_goal / patch_goal / chat / chat_async / kill_engine / read_spill_files`。
- `run.py` —— 发现 `scenarios/*.py` 执行，`--task <name>` / `--all`，写 `report.md`。
- `scenarios/`（19 项，62 断言全 PASS）：`t1_spill t2_cancel t3_permission t4_crash t5_title t6_repeat t7_bashrules t9_goal t12_protected t13_envelope t17_instruction t25_badconfig t26_monotonic t28_narration t30_portfile t31_ssot t34_friendly t35_tools t39_busy`。

**运行**：
```powershell
py -3.11 scripts/smoke_p0p1/run.py --task t9_goal
py -3.11 scripts/smoke_p0p1/run.py --all          # 写 report.md
```
（必须 `py -3.11`；环境里默认 `python` 是 3.14，用 3.11 的 httpx/uvicorn 才齐。）

## 2. 关键契约（写场景前必读，已从源码核实）

- 端点 `POST /v1/chat/completions`：头 `X-Session-Id / X-Provider: local / X-Base-Url:<mock>/v1 / X-Xeyo-Surface`；body `{model,messages,stream,provider,base_url,workspace,...}`。
- SSE `data:{json}`：xeyo 事件在 `json["xy"]`（`type` 区分 `title / tool_call / tool_result / permission_pending / permission_resolved / task_state_changed / usage / final`），助手文本在 `json["choices"][0].delta.content`；结束帧 `data: [DONE]`。
- 权限：`xy.type=="permission_pending"` 带 `request_id` → `POST /v1/permission/resolve {request_id,approved,actor,outcome:"allow",remember}`；`remember` 记 grant（T10）；T26 用 `remember=False` 观察"不反向放宽"。
- 工具 schema：Bash `{command,...}`；Write `{file_path,content}`（绝对路径）；Grep `{pattern,path,output_mode:"content",-n:false}`（**默认 output_mode 是 files_with_matches，出小输出**）；TodoWrite `{todos:[{id,content,status,activeForm}]}`。
- **Bash/Read 豁免 registry spill**（`output_budget=0`，Bash 自带 30k 中段截断 seam）：测 spill 用非豁免工具，如 **Grep `output_mode:"content"` 对预埋大文件**。
- 任务 `--task` 用**模块名精确匹配**（如 `--task t1_spill`），不是前缀子串（`t1` 会命中 `t12`）。
- 场景可注入工作区路径：`RESPONSES` 可以是 `callable(h)`，返回用到 `str(h.workspace)` 的列表；run.py 在 Harness 构造时求值。

## 3. 环境隔离（踩过坑，务必照做）

引擎输出目录**不都跟随 `XEYO_HOME`**，必须各设独立 env，否则污染真实 home：
```
XEYO_HOME=<tmp/home>
XEYO_SPILL_DIR=<tmp/spill>        # tools/spill.py 用 XEYO_SPILL_DIR，不是 XEYO_HOME
XEYO_SESSIONS_DIR=<tmp/sessions>  # session/persistence.py 用 XEYO_SESSIONS_DIR
XEYO_PORT_FILE=<tmp/backend_port.json>  # server/portfile.py 用 XEYO_PORT_FILE
XEYO_HTTP_PORT=<free>            # __main__.py 从该端口起找空闲
XEYO_ALLOW_LOCAL_MODEL=1
```
`harness.py` 已全部设置（`up()`）。**清理纪律**：`down()` 会杀 proc + 删 `_tmp`；但重启类场景（t4/t39 二次 `up()`）要确保先 kill 旧 proc（`up()` 内已有 guard）；跑完检查无遗孤 `python -m server` 进程、清 `%TEMP%\smoke_*`。

## 4. 本会话修过的真 Bug

`python/server/routers/chat.py` 的 `chat_completions` 里 `/compact` 双闸（第 ~578 行）引用 `get_turn_runner`，但其函数级 import 在下方（~665 行）→ **`/compact` 必然 500（UnboundLocalError）**。已在函数顶部加了 `from engine.turn_runner import get_turn_runner`。这是冒烟独有的价值（单测没抓到）。下会话**别回退**。

## 5. "只是能用"清单（冒烟仍没验收的，特别是前端）

| 项 | 状态 | 该由谁验证 |
|---|---|---|
| T13 前端：工具卡 duration/spilled 渲染、correlation 归因 | 本次只测了后端成对 | **Playwright** |
| T3 服务端 30s 提醒帧（on_event 无消费方） | 未测（自动放行从不触发到期） | Playwright / GUI 手工 |
| T3 面板：默认展开、resolve 失败→回滚+toast、Esc=Cancel | 未测 | **Playwright** / GUI |
| T29 断流→banner、不自动 interrupt | 未测 | **Playwright** / GUI |
| T9 chip 四态、候选条、恢复横幅 | 未测 | **Playwright** / GUI |
| T11 `always_allow` 端到端未打通 | 未测（需 MCP fixture，后端） | scenarios/ 新增 |
| T31 三边界（cwd 跨重启、permission_mode durable、cli-ts 自造 uuid） | 未测 | cli-ts 驱动 / 手工 |
| T38 `/compact` 按钮按 gate 显隐 | 未测 | **Playwright** / GUI |

## 6. Playwright 全栈落法（下会话主任务）

1. 保留 `scripts/smoke_p0p1/`（服务器端冒烟）。
2. 新增 `gui/e2e/`：`@playwright/test` + `npx playwright install chromium`。
3. **关键衔接**：GUI 是 Tauri，但 dev 模式是浏览器 Vite 网页。配置 `playwright.config.ts`：
   - `webServer` 起两个：①先起后端（复用 `harness.py` 的扇逻辑，或直接跑 `py -3.11 -m server` + 隔离 env + 读其端口）；②再起 `gui/` 的 Vite dev（命令待确认：`pnpm dev` / `npm run dev`），并让 **GUI 连到那个临时后端端口**（GUI 默认连 `127.0.0.1:8000` / 读 portfile，需指到隔离端口）。
   - `baseURL = http://localhost:<vite端口>`。
4. 首批全栈流（各一条，证明走通即可）：**T13 工具卡渲染 duration/spilled**、**T3 审批面板**（默认展开/30s 倒计时/Esc=Cancel/失败回滚 toast）。走通后再扩 **T29 banner、T9 chip、T38 按钮**。
5. **jsdom/vitest 保留**（`npx vitest run`，~551 例），不要替换成 Playwright；两条基线分开跑。
6. `npx tsc --noEmit` 作为静态门禁。

## 7. 完整冒烟的三层（最终交付口径）

- 服务器端：`scripts/smoke_p0p1/run.py --all`（已 19 项/62 断言）。
- GUI 全栈：Playwright（真浏览器+后端）+ 手工清单。
- 基线回归：全量 `pytest`（285+）+ `vitest`（551）+ `tsc` —— 且**处理 4 条既有失败测试**：`test_screenshot_tool` 复制漂移、`test_main_loop_three_cuts.py` mkstemp 卡死、`test_rewind_service` git stash、chatStore rewind 横幅 PR-R4。

## 8. 明确不做 end-to-end 冒烟的（按性质归档）

T8（C2 压缩需 ≥24 轮，归压缩套件）、T16（config profile 属 CLI 层，归 `cli` 冒烟）、T27（aging 默认关，难短时观测）、T29 纯网络段（归 `test_server_hardening`）、T32（双击 bat，手工）、T33（loopback/远程，归 hardening）、T36（仓库卫生，静态/CI）。T11/T14 可 e2e 但需真 MCP/子代理 fixture，成本高，建议单独加场景。

## 9. 复用提示

- 场景模板：`scenarios/t9_goal.py`（callable `responses(h)`）、`scenarios/t3_permission.py`（权限+grant）、`scenarios/t4_crash.py`（chat_async+kill+重启）。
- 查/改产物前先跑 `--all` 复现；改 `harness.py` 后重跑现有场景防回归。
- 看到 `UnicodeDecodeError`/乱码是 GBK 控制台打印 UTF-8 所致，不影响 `report.md`（UTF-8）；运行时可加 `PYTHONIOENCODING=utf-8`。
