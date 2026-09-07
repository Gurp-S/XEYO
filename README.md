# XEYO

> 本地编码 Agent · Python 引擎 + Tauri 桌面 / Ink 终端 / Typer CLI 三界面

<p align="center">
  <img src="assets/xeyo-final-source.jpg" alt="XEYO" width="120">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11+-3776AB.svg">
  <img alt="Node" src="https://img.shields.io/badge/node-20+-339933.svg">
  <img alt="Tauri" src="https://img.shields.io/badge/desktop-Tauri%202-FFC131.svg">
  <img alt="Engine" src="https://img.shields.io/badge/agent-mode-Model%20%E2%86%94%20Tools-blueviolet.svg">
</p>

## 是什么

XEYO 是一个**本地运行**的编码 Agent —— Python 编排的模型 ↔ 工具多轮主循环，配合代码理解（符号级 Read / Grep）、流式响应、Stop 中断、回溯 rewind、企业级权限沙箱与多表面会话。

一份引擎，三种界面：

| | 形态 | 入口 |
|---|---|---|
| 桌面 GUI | Tauri 2 透明无边框窗，1080p 矢量 UI | `XEYO.bat` |
| 终端 TUI | Ink + React，`Ӿ I am XEYO` 工具卡片 | `XEYO-TUI.bat` |
| 管道 / 脚本 | Typer，进程内 chat / JSON 输出 | `py -3.11 -m cli chat` |

会话 JSONL 持久化、引擎 session_id 与磁盘文件名同源；微信 / iLink Bot 通道（文件传输助手）按微信号隔离，可从磁盘续聊。API Key 在 UI **设置** 面板填写（本机持久化），不写进 `.env`。

## 下载（Windows）

桌面 GUI 安装包（**已就绪**——Tauri 2 NSIS + MSI，构建脚本 `scripts/build_installer.ps1` / `.sh`，精简 Python 引擎内嵌）：

| 包 | 大小 | 说明 |
|---|---|---|
| [`XEYO_0.1.0_x64-setup.exe`](../../releases) | 52M | **NSIS 安装器**，双击装完即用（推荐） |
| [`XEYO_0.1.0_x64_en-US.msi`](../../releases) | 77M | **MSI 安装包**，企业分发友好 |

源码分发（开发者）：下载源码后双击 `XEYO.bat`（自动装 Python/Node 依赖并启动）。

## 打包

桌面安装包已可用。**已就绪脚本**：

```powershell
pwsh -File scripts/build_installer.ps1
# 或 bash scripts/build_installer.sh
```

脚本会：①精简 Python 代码 → `gui/src-tauri/resources/python/` ②复制并精简 .venv（裁掉 ray/sqlalchemy/pytest/playwright，开发包，从 363M → 33M）③补装 typer ④`npm run tauri:build`。

**精简策略**：
- python/ 裁 evals/bridge/scripts/tests/_shadow/memory.simulator/out（runtime 无用）
- .venv 裁 ray(118M) + sqlalchemy(19M) + playwright(104M, 注: playwright 运行时 channels/filehelper 用, 已恢复) + pytest 系列
- 补拷 .pyd（Rust 编译扩展，不被 ignore 误伤）

NSIS 压缩后 52M（含 ~40M 精简引擎、~4M 代码、~12M 前端 + GUI 壳）。

## 快速开始（源码）

> 系统要求：Python 3.11+ · Node.js 20+ · Rust（Tauri 桌面端，可选）

### 一键启动（推荐）

```bat
XEYO.bat
```

启动器会：

1. 探测并安装依赖（`pip install -r python/requirements.txt` + `npm install`）
2. 启动 FastAPI 后端 `http://127.0.0.1:8000`（端口被占自动挪到下一个空闲端口，写入 `.xeyo/backend_port`）
3. 拉起 Tauri 桌面窗

### 手动分步

**后端：**

```powershell
cd python
$env:XEYO_CWD = "D:\path\to\your\project"     # 可选：手动指定项目根
$env:XEYO_REWIND_ENABLED = "1"               # 开启 rewind（回溯 + 工作区恢复）
py -3.11 -u -m server
```

**前端（Web 联调，浏览器即可）：**

```powershell
cd gui
npm install
npm run dev
```

Vite 已把 `/v1` `/api` `/health` 代理到后端（默认 `:8000`，跟随后端实际端口）。

**前端（Tauri 桌面）：**

```powershell
cd gui
npm run tauri:dev
```

首次编译较慢；Release 产物：

```powershell
cd gui
npm run tauri:build
# 产物：gui/src-tauri/target/release/bundle/{nsis,msi}/
```

### 入口怎么选

| 场景 | 命令 |
|---|---|
| 桌面 GUI（推荐） | 双击 `XEYO.bat` |
| 终端 Ink TUI | 双击 `XEYO-TUI.bat`（自动检查并拉起引擎） |
| 浏览器联调 UI | `py -3.11 -m cli serve` + `cd gui && npm run dev` |
| 脚本 / 管道 / CI | `py -3.11 -m cli chat --json "..."` |
| 本地门禁 | `pwsh -File scripts/check.ps1` |

## 核心能力

- **Agentic 主循环**：模型 ↔ 工具多轮，中断 / 预算 / 工具分区执行；R1'墙钟事件源 + R2'重复输出折叠 + R3'收尾配额窗
- **编码工具集**：21 项，对应 `python/tools/catalog.py::ENABLED_TOOL_ENTRIES`（Glob / Grep / Read / Write / Edit / Bash / TodoWrite / Agent / Skill / XeyoUI / WebFetch / WebSearch 等）
- **符号级代码理解（33 号计划）**：Read 支持 `symbol` 参数只读单个类/函数体；Grep 支持 `output_mode: "symbols"` 列出仓库符号目录（tree-sitter 可选，未装自动降级为名称列表）
- **权限沙箱**：工作区外路径 deny；T13 工具卡可见审批面板
- **流式 + Stop**：`POST /v1/interrupt` 实时中止
- **回溯 rewind**：企业级 v3，文件级检查点 + Restore + Undo
- **微信远程**：文件传输助手 / iLink Bot，按微信号隔离会话，重启后端可从磁盘续聊
- **会话 JSONL 持久化**：`SessionPool` 键 = 引擎 session_id = 磁盘文件名
- **多表面**：GUI / tui / Python CLI / 微信四表面共用 `python/slash/registry.py` 统一 manifest

## 入口表

| 入口 | 路径 | 引擎连接 |
|---|---|---|
| 桌面 GUI | `XEYO.bat` → Tauri dev | HTTP/SSE → `python/server` |
| 终端 TUI | `XEYO-TUI.bat` → Ink | HTTP/SSE → 已运行的 FastAPI |
| 脚本 / 管道 | `py -3.11 -m cli` (Typer) | 进程内 `QueryEngine` 或 HTTP attach |
| 改斜杠命令 | `python/slash/registry.py` | 改后跑 `py -3.11 -m slash.export_manifest` 并提交 `*/generated/slashManifest.ts` |

## CLI / TUI

```powershell
# 终端 TUI（推荐先看外观）
cd tui
npm install
npm run demo               # 一轮展示
# 真聊：另窗口启动引擎
cd ..\python
py -3.11 -m cli serve --cwd D:\path\to\project
cd ..\tui
npm start -- --cwd D:\path\to\project

# 脚本 / 管道
cd python
py -3.11 -m cli chat --provider fake --print --json "hello"
py -3.11 -m cli sessions list
```

REPL / Ink 斜杠：统一 manifest 在 `python/slash/registry.py`。**无 TTY 时权限 ASK fail-closed**。

## 成熟度说明（诚实口径）

以上「核心能力」逐条对应当前真实工具矩阵。以下特性**未上线或属实验**——README 只作说明，不宣称已产品化：

- **插件 / MCP 扩展层**（`/mcp`、`/plugins`）：默认关闭，需 `.xeyo/settings.json` 显式启用
- **Multi-Agent（子代理批量调度）**：实验性，Composer 里勾选才走批量调度；主模型仍可主动 spawn 单个子代理
- **Memory C2 / L5 投影与 NightShift 离线重塑**：默认 `XEYO_L5=project`（只走 C0+C1 截断），C2 门禁默认关闭；属评估/灰度形态
- **符号级理解（33 号）**：依赖 tree-sitter，未安装时**自动降级**为仅列出符号名（无行内结构）
- **Java 工具运行时（task6）**：未启用，不作为卖点

## 基准

第三轮评测（2026-08-26）口径：

| 基准 | 思考模式 | 通过率 |
|---|---|---|
| BFCL v4 simple_python (200 例) | 关闭 | **93.50%** |
| BFCL v4 parallel (400 例) | 关闭 | **90.50%** |

底座模型 `deepseek-v4-flash-vision-exp`，harness `python/evals/`（自研轻量）+ Linux 容器内官方 `bfcl-eval` 2026.3.23。详见 [`docs/起步阶段评测结果.md`](./docs/起步阶段评测结果.md)。

## 本地门禁（CI 同款）

```powershell
pwsh -File scripts/check.ps1
# 或 Linux/macOS：bash scripts/check.sh
```

跑 Python pytest（`-m "not live"`）、GUI typecheck + vitest、tui typecheck。GitHub Actions 见 `.github/workflows/ci.yml`。

## 文档

- 代码地图（新人必读）：[`python/ARCHITECTURE.md`](./python/ARCHITECTURE.md) · [`gui/ARCHITECTURE.md`](./gui/ARCHITECTURE.md)
- 架构可视化（系统 / 记忆架构 HTML 图）：[`docs/架构/`](./docs/架构/)
- 起步阶段评测结果（BFCL / HumanEval 等）：[`docs/起步阶段评测结果.md`](./docs/起步阶段评测结果.md)
- 安全策略：[`SECURITY.md`](./SECURITY.md) · 变更日志：[`CHANGELOG.md`](./CHANGELOG.md) · 许可：[`LICENSE`](./LICENSE)

## 打包（开箱即用 exe）

> Tauri 桌面 GUI 安装包（NSIS + MSI）正在打。当前构建能力：Rust 1.97 + Tauri 2 + NSIS；Tauri 壳已内置引擎启动 / 健康守护 / 单实例 / 端口迁移逻辑（`gui/src-tauri/src/lib.rs`），差最后一步把精简 Python 引擎打进 Tauri `resources/`。

`gui/src-tauri/src/lib.rs::python_root()` 优先用打包资源 `resources/python`（含精简 venv + 引擎子集），回退到源码路径。这意味着安装后**用户无需任何预装**（不需 Python 3.11 / Node 20 / 任何依赖）即可双击启动。

## 工程硬规矩

1. **提交门**：`tsc + vitest + pytest P0` 全绿才允许 commit
2. **开工检查**：第一行代码前先看 `git status`——只允许本功能在途；他人改动先停下确认归属
3. **新功能准入**：先以旁路形态（feature flag / 独立模块 / 钩子）上线验证收益，**有数据证明后**才并入主链路
4. **事故模板**：修复前先答——结构性根因？哪条规则让结构上不再发生？回归测试怎么写？

详见 [`AGENTS.md`](./AGENTS.md)。

## 许可

[MIT](./LICENSE)。
