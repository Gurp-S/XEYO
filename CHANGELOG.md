# Changelog

本项目采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

> 状态：**发布准备中**——首个公开版本（v0.1.0）尚未打 tag。以下条目为发布快照的内容草案，按「语义化提交（Conventional Commits）」从开发历史整理而来。

## [Unreleased]（发布快照草案，待定 tag v0.1.0）

### 初始化（Initial）

- 首次公开：XEYO —— 本地编码 Agent（Python 编排主循环 + React/Tauri 前端 + Ink 终端 UI）。
- 仓库结构：`python/`（engine + FastAPI server + Typer CLI）、`gui/`（React+TS，Tauri 壳）、`cli-ts/`（Ink TUI）。

### Added

- Agentic 主循环：模型 ↔ 工具多轮（中断 / 预算 / 工具分区执行）。
- 编码工具面：Glob / Grep / Read / Write / Edit / Bash / TodoWrite 等 21 项（`python/tools/catalog.py`）。
- 符号级代码理解：`Read symbol` / `Grep output_mode:"symbols"`（tree-sitter，未装自动降级）。
- 会话 JSONL 持久化 + 重启续聊；微信远程通道（文件传输助手 / iLink Bot，按微信号隔离）。
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
