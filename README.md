# XEYO

<p align="center">
  <img src="assets/xeyo-final-source.jpg" alt="XEYO" width="128">
</p>

<p align="center">
  <strong>本地优先的代码工作台</strong><br>
  在桌面、终端和命令行里，用同一套引擎阅读、修改和运行代码。
</p>

<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB.svg">
  <img alt="Node.js" src="https://img.shields.io/badge/node-20%2B-339933.svg">
  <img alt="Tauri" src="https://img.shields.io/badge/desktop-Tauri%202-FFC131.svg">
</p>

<p align="center">
  <img src="screenshots/20260828-193656.preview.png" alt="XEYO desktop interface" width="960">
</p>

XEYO 把代码阅读、文件操作、命令执行和会话管理放在一个本地工作区里。Python 引擎负责运行，Tauri 桌面端、Ink 终端界面和 Typer CLI 共用同一套能力。

## 功能

- 工作区感知的文件工具：`Read`、`Grep`、`Glob`、`Write`、`Edit`
- 符号级代码浏览：查看类、函数和模块结构
- 流式输出、即时停止和多轮会话
- 文件检查点、恢复与撤销
- 工作区边界和权限确认
- JSONL 会话持久化，支持从历史会话继续
- HTTP/SSE 接口，可连接桌面端、TUI 或脚本
- 可选的本地模型、MCP、Skill 和插件扩展

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.11
- Node.js 20+
- Rust + Cargo（仅桌面端需要，可从 [rustup.rs](https://rustup.rs/) 安装）

### 一键启动桌面端

```powershell
git clone https://github.com/GiseFt/XEYO.git
cd XEYO
XEYO.bat
```

首次启动时，脚本会检查并安装 Python 依赖和 GUI 依赖，然后启动本地后端和 Tauri 桌面窗口。API Key 和模型配置在应用内的“设置”面板填写；密钥不会写入仓库。

## 选择运行方式

### 桌面端

```powershell
XEYO.bat
```

这是最完整的使用方式：脚本启动 FastAPI 后端，再打开 Tauri 开发窗口。

### 浏览器开发

先启动后端：

```powershell
cd python
py -3.11 -m server
```

另开一个终端启动 Vite：

```powershell
cd gui
npm install
npm run dev
```

### 终端 TUI

TUI 通过 HTTP/SSE 连接已经运行的后端：

```powershell
# 终端一：启动后端
cd python
py -3.11 -m cli serve --cwd D:\path\to\your\project

# 终端二：启动 TUI
cd tui
npm install
npm start -- --cwd D:\path\to\your\project
```

先看演示：

```powershell
cd tui
npm run demo
```

### CLI 和脚本

```powershell
cd python

# 首次配置 provider、API Key 和默认工作区
py -3.11 -m cli setup

# 单次执行
py -3.11 -m cli chat --print "检查这个项目的入口"

# 输出 JSON，便于脚本或 CI 使用
py -3.11 -m cli chat --print --json "列出项目中的 Python 包"

# 管理通过 HTTP 服务保存的会话
py -3.11 -m cli sessions list
```

## 配置

`.env.example` 是本地开发配置模板：

```powershell
Copy-Item .env.example .env
```

它主要用于配置后端地址、端口和默认工作区。模型、账号和 API Key 可在 GUI 的设置面板中管理；本地模型的运行参数也在设置中配置。

扩展功能默认关闭。如需使用 MCP、Skill 或插件，在工作区的 `.xeyo/settings.json` 中显式启用。

## 项目结构

```text
python/     Python 引擎、FastAPI 服务和 Typer CLI
gui/        React + TypeScript + Tauri 桌面端
tui/        Ink + React 终端端
scripts/    启动、构建和检查脚本
docs/       架构与使用文档
```

## 开发与检查

安装依赖后，可以运行与 CI 接近的本地检查：

```powershell
pwsh -File scripts/check.ps1
```

也可以按模块执行：

```powershell
# Python
cd python
py -3.11 -m pytest -q --timeout=60 -m "not live"
py -3.11 -m slash.export_manifest --check

# GUI
cd ..\gui
npm run typecheck
npm test

# TUI
cd ..\tui
npm run typecheck
```

修改斜杠命令后，运行 `py -3.11 -m slash.export_manifest` 更新生成的 manifest 文件。

## 构建桌面安装包

```powershell
pwsh -File scripts/build_installer.ps1
```

安装包产物位于 `gui/src-tauri/target/release/bundle/`。构建流程会准备自包含的 Python 运行时，目标机器不需要预装 Python。

## 文档

- [Python 引擎架构](python/ARCHITECTURE.md)
- [GUI 架构](gui/ARCHITECTURE.md)
- [安全策略](SECURITY.md)
- [变更日志](CHANGELOG.md)

## 参与贡献

欢迎提交 Issue 和 Pull Request。提交安全问题前，请先阅读 [SECURITY.md](SECURITY.md)，不要在公开 Issue 中披露未修复的漏洞。

## 许可

[MIT License](LICENSE)
