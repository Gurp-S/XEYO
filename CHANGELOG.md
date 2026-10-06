# Changelog

本项目采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 当前正式版：**1.1.0**（2026-10-07）。

## [1.1.0] - 2026-10-07

### Added

- Windows x64 一键安装包，内置可迁移的 Python 运行时和 ripgrep。
- 用量事件读取与本地用量报告。

### Changed

- 整理桌面端、终端端和引擎的会话、流式输出与恢复流程。
- 微信远程通道收敛为 iLink Bot。

### Fixed

- 修复 Windows 绝对路径在 POSIX 环境中被当作工作区相对路径的问题。
- 修复 CI 缺少运行工具、Tauri 资源未生成和 GUI 锁文件下载地址错误。

### Security

- 正式桌面配置关闭 Chromium 远程调试端口。

## [0.1.0] - 2026-09-07

### 初始化（Initial）

- 首次公开：XEYO —— 本地编码 Agent（Python 编排主循环 + React/Tauri 前端 + Ink 终端 UI）。
- 仓库结构：`python/`（engine + FastAPI server + Typer CLI）、`gui/`（React+TS，Tauri 壳）、`tui/`（Ink TUI）。

### Added

- Agentic 主循环：模型 ↔ 工具多轮（中断 / 预算 / 工具分区执行）。
- 编码工具面：Glob / Grep / Read / Write / Edit / Bash / TodoWrite 等 21 项（`python/tools/catalog.py`）。
- 符号级代码理解：`Read symbol` / `Grep output_mode:"symbols"`（tree-sitter，未装自动降级）。
- 会话 JSONL 持久化 + 重启续聊；微信远程通道（iLink Bot，按微信号隔离）。
- 权限沙箱：工作区外 deny；Bash 读命令透明路由（`bash_routing=auto`，可关）。
- 记忆体系：内存索引 / 语义检索 / C2 压缩与回溯（rewind v3 热路径，`XEYO_REWIND_ENABLED`）。
- 斜杠命令统一 manifest：`python/slash/registry.py` → 四表面共用。
- 评测诚实度基建：环境污染门 / 盲审反作弊 / 冷记忆评测等（侧挂模块，默认关）。
- 起步阶段评测记录：BFCL / HumanEval（见 `docs/起步阶段评测结果.md`）。

### Changed

- （首个公开快照，无此前公开历史；内部迭代见归档目录。）

### Fixed

- （同上；快照内不追溯内部修复。）

### Security

- `.env` / `api_key.txt` / 内部过程文档（`[过程]/`）不入公开仓库。
- `/v1` API 默认仅本机回环可达。

## [未发布路线]

- 插件 / MCP 扩展层默认关闭，需显式启用（实验）。
- Multi-Agent（子代理批量调度）实验性。
- Memory C2 / L5 投影与 NightShift 离线重塑默认 `XEYO_L5=project`（灰度形态）。
