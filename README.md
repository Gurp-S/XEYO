# XEYO

本地编码 Agent：Python 编排主循环 + React/Tauri 前端。

## 一键启动（推荐）

### 安装步骤

确保系统已安装：
- Python 3.11+
- Node.js 20+（GUI 与 cli-ts；`XEYO-CLI.bat` 在缺 Node 时会回退 Python CLI）
- Rust（Tauri 桌面端，可选）

```bat
XEYO.bat
```

执行流程：
1. 探测环境并自动安装 Python（`pip install -r python/requirements.txt`）与 Node（`npm install`）依赖。
2. 启动 FastAPI 后端 `http://127.0.0.1:8000`。工作区由桌面里「打开文件夹」绑定，不要把 `python/` 包根当成项目目录。
3. 等待 `/health` 接口就绪。
4. 启动 Tauri 开发桌面窗：`npm run tauri:dev`（需 Rust/cargo）。纯浏览器联调请改用手动分步里的 `npm run dev`。

> 端口被占用时不阻塞启动：后端若 `8000` 被占会自动挪到下一个空闲端口（真实端口写入 `.xeyo/backend_port`），
> 前端 Vite 若 `5173` 被占会自动递增，前后端通过该文件/环境变量保持端口一致。启动器也会先清理旧进程占用的前后端端口。

API Key 在应用内 **设置** 面板填写（本机持久化），不必写进 `.env`。

## 手动分步

### 后端

```powershell
cd python
# 可选：仅手动调试时指定项目根。桌面请用「打开文件夹」，不要指向 python/ 包目录。
$env:XEYO_CWD = "D:\path\to\your\project"
$env:XEYO_REWIND_ENABLED = "1"         # 开启企业级 rewind（回溯 + 工作区恢复）
py -3.11 -u -m server
```

健康检查：`curl http://127.0.0.1:8000/health`

### 前端（Web）

```powershell
cd gui
npm install
npm run dev
```

Vite 已把 `/v1`、`/api`、`/health` 代理到后端端口（默认 `:8000`，被占时跟随后端自动挪动的实际端口；见 `gui/vite.config.ts`）。

### 前端（Tauri 桌面）

```powershell
cd gui
npm run tauri:dev
```

首次编译较慢；Release 包请手动 `cd gui && npm run tauri:build` 后从产物启动（`XEYO.bat` 当前仅走 dev 桌面窗）。

## 本地门禁（CI 同款）

```powershell
pwsh -File scripts/check.ps1
```

或在 Linux/macOS：`bash scripts/check.sh`

跑 Python pytest（`-m "not live"`）、GUI typecheck + vitest、cli-ts typecheck。GitHub Actions 见 `.github/workflows/ci.yml`。

## `npm run dev` vs `tauri:dev`

| | `npm run dev` | `npm run tauri:dev` |
|---|---|---|
| 形态 | 浏览器标签页 | 桌面窗口 |
| 依赖 | Node + 后端 | Node + Rust + 后端 |
| 适用 | 日常联调 UI | 演示 / 桌面产品感 |

二者共用同一套 React 代码与同一后端 API。

## 核心能力

- Agentic 主循环：模型 ↔ 工具多轮（中断 / 预算 / 工具分区执行）
- 编码工具：Glob / Grep / Read / Write / Edit / Bash / TodoWrite
- 符号级代码理解（33号计划）：Read 支持 `symbol` 参数只读单个类/函数体；Grep 支持 `output_mode: "symbols"` 列出仓库符号目录（tree-sitter 可选，未装自动降级）
- 权限沙箱：工作区外路径 deny（Bash 门禁仍在加强，见 `docs/设计/08`）
- 流式桌面 UI + Stop（`POST /v1/interrupt`）
- 微信远程：文件传输助手 / iLink Bot；按微信号隔离会话，重启后端可从磁盘续聊；截图与文件可回传到微信
- 会话 JSONL 持久化（`SessionPool` 键 = 引擎 session_id = 磁盘文件名）

> **成熟度说明（诚实口径）**：以上「核心能力」逐条对应当前真实的工具矩阵
> `python/tools/catalog.py::ENABLED_TOOL_ENTRIES`（21 项，含 GetTime/Git/Diagnostics/
> JournalQuery/NotebookEdit/WebFetch/WebSearch/Skill/Agent/XeyoUI 等）。以下特性**未上线或属实验**：
> - **插件 / MCP 扩展层**（`/mcp`、`/plugins`）：默认关闭，需 `.xeyo/settings.json` 显式启用。
> - **Multi-Agent（子代理批量调度）**：实验性，Composer 里勾选才走批量调度；主模型仍可主动 spawn 单个子代理。
> - **Memory C2 / L5 投影与 NightShift 离线重塑**：默认 `XEYO_L5=project`（只走 C0+C1 截断），C2 门禁默认关闭；属评估/灰度形态，不当作已上线。
> - **符号级理解（33 号）**：`Read symbol` / `Grep output_mode:"symbols"` 依赖 tree-sitter；未安装时**自动降级**为仅列出符号名（无行内结构）。
> - **Java 工具运行时（task6）**：未启用，不作为卖点。
> 这些在 README/文档里只作「实验/未启用」说明，不宣称已产品化。

## 入口怎么选

| 场景 | 命令 |
|------|------|
| 桌面 GUI（推荐） | 双击 `XEYO.bat` |
| 终端 Ink TUI | 双击 `XEYO-CLI.bat`（自动检查并拉起引擎） |
| 浏览器联调 UI | 手动：`py -3.11 -m cli serve` + `cd gui && npm run dev` |
| 脚本 / CI / 管道 | `py -3.11 -m cli chat --json "..."` |
| 本地门禁 | `pwsh -File scripts/check.ps1` |

## CLI

两种入口（同一引擎 / 同一 `~/.xeyo/config.toml`）：

| | |
|---|---|
| **TypeScript UI（推荐看外观）** | [`cli-ts/`](./cli-ts/) — Ink · `Ӿ I am XEYO` · 工具卡片 |
| **Python CLI（脚本 / serve）** | [`python/cli/`](./python/cli/) — Typer · 进程内 chat · `serve` |

**最快上手（Windows）：** 双击 [`XEYO-CLI.bat`](./XEYO-CLI.bat)（优先 TS Ink；引擎未启动会自动拉起；`/demo` 为**显式**演示入口，非主路径）。

```powershell
cd cli-ts
npm install
npm run demo

# 真聊：先起引擎
cd ..\python
py -3.11 -m cli serve --cwd D:\path\to\project
# 另开窗口
cd ..\cli-ts
npm start -- --cwd D:\path\to\project

# 脚本 / 管道（无 TUI）
npm start -- --json "hello"
```

Python 侧仍可用：

```powershell
cd python
py -3.11 -m cli                # 无参数 = chat
py -3.11 -m cli setup
py -3.11 -m cli chat --provider fake --print --json "hello"
py -3.11 -m cli sessions list
```

REPL / Ink 斜杠（统一 manifest：`python/slash/registry.py` → 四表面共用；**完整命令表见文档**）：

详见 [docs/设计/37-斜杠命令统一设计.md](./docs/设计/37-斜杠命令统一设计.md)。无 TTY 时权限 ASK **fail-closed**。

下一阶段（可用 → 企业级 → 微信亮点）：`docs/实施计划/09-企业级落地计划-时序与排期.md`

## 文档

> 代码地图（新人必读）：[`python/ARCHITECTURE.md`](./python/ARCHITECTURE.md) · [`gui/ARCHITECTURE.md`](./gui/ARCHITECTURE.md)

> docs 目录已按类别分目录整理，完整索引见 [docs/README.md](./docs/README.md)。

- 执行总纲（时序 / 理由 / 周排期）：`docs/实施计划/09-企业级落地计划-时序与排期.md`
- 产品身份：`docs/设计/08-从Demo到企业级.md`
- 远程微信（重启续聊 + 按人隔离，已落地）：`docs/任务书/task8-远程微信-重启续聊与按人隔离.md`
- 演示期总纲：`docs/总纲与路线/00-总计划书-可上线路线图.md`
- Task4 API：`docs/任务书/task4-服务端API稳定.md`
- Task5 前端：`docs/任务书/task5-前端产品化.md`

## 开发自测（可选）

```powershell
# 后端契约
cd python
py -3.11 tests/test_server_api.py

# 前端单测
cd gui
npm test
```
