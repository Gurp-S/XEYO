# XEYO 项目说明

> 本文件按「指针式、保持简短」维护；细则/长流程不内联，需要时用 Read / Skill 现查。

## 核心判断（先读这一条）

前沿编程 Agent 的榜单分**混淆了「解决缺陷」与「检索已知修复」**。
评审强调：报告必须**先归因再谈分**；SWE 系与 XEYO 自我评测**禁止只报单一 accuracy**。

## 常用命令
- 联合离线门（仓库根）：`pwsh -File scripts/check.ps1 -Json -SkipInstall`；输出逐阶段结果与日志路径。
- Python 测试（`python/`）：`py -3.11 -m pytest -q --timeout=60 -m "not live"`；WSC 子集：`py -3.11 -m pytest tests/wsc -q`。
- GUI（`gui/`）：测试 `npm test`；类型检查 `npm run typecheck`；前端构建 `npm run build`；桌面打包 `npm run tauri:build`。
- TUI（`tui/`）：测试 `npm test`；类型检查 `npm run typecheck`；构建 `npm run build`。

## 禁区 / 硬约定
- 不动 `python/memory/` 会话内冻结的召回面来「讨好」评测——召回/检索必须在报告中先归因，再谈分。
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**。
- 索引类改动（⑦–⑪）必须 **fail-open**：索引不可用/异常/超限 → 无条件回退全量 `rg` / 整树语义；绝不假阴、绝不泄密。

## 指针（细则不内联；需要时用 Read / Skill）
- 入口与引擎约定：`AGENTS.md`；引擎入口 `python/engine/query_loop.py`，HTTP 服务 `python/server/app.py`，WSC 投影 `python/memory/wsc_projection.py` → `python/synaptic/project.py`。
- WSC 修复状态与证据：`docs/wsc-open-issues.md`、`docs/wsc-loop-notes-2026-10-07.md`、`docs/wsc-root-contracts-evidence-2026-10-08.md`。
- 长流程（发版等）→ `.xeyo/skills/<name>/SKILL.md`，用 Skill 工具按需加载
