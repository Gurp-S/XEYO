# XEYO 项目说明

> 本文件按「指针式、保持简短」维护；细则/长流程不内联，需要时用 Read / Skill 现查。

## 核心判断（先读这一条）

前沿编程 Agent 的榜单分**混淆了「解决缺陷」与「检索已知修复」**。
评审强调：报告必须**先归因再谈分**；SWE 系与 XEYO 自我评测**禁止只报单一 accuracy**。

## 常用命令
- 联合离线门（仓库根）：`pwsh -File scripts/check.ps1 -Json -SkipInstall`；输出逐阶段结果与日志路径。
- Python 测试（`python/`）：`py -3.11 -m pytest -q --timeout=60 -m "not live"`；WSC 子集：`py -3.11 -m pytest tests/wsc -q`。
- 看当前**磁盘代码**会注入什么（新进程、零 API 成本，改完不用等重启）：`py -3.11 -m cli probe t-now --session <sid> --used <n> --window 1000000`；工具面 `py -3.11 -m cli probe tool --tool Read --args '{"file_path":"…"}'`。
- 判归因（不动工作树）：`pwsh -File scripts/baseline_run.ps1 -PytestArgs "tests/test_x.py -q"`；`-Ref` / `REF=` 指基线，台账 `.xeyo/baseline_stamp.json`。
- GUI（`gui/`）：测试 `npm test`；类型检查 `npm run typecheck`；前端构建 `npm run build`；桌面打包 `npm run tauri:build`。
- TUI（`tui/`）：测试 `npm test`；类型检查 `npm run typecheck`；构建 `npm run build`。

## 仓库状态（事实）
- 本仓有**外部自动提交**：编辑会被逐批 commit（reflog 实测，偶发 merge 别的分支）⇒「改动都没提交」不是恒真前提。判归因一律带 `ref`，别把 HEAD 当"我动手之前"；基线与台账走 `scripts/baseline_run.*`。

## 禁区 / 硬约定
- 不动 `python/memory/` 会话内冻结的召回面来「讨好」评测——召回/检索必须在报告中先归因，再谈分。
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**。
- 索引类改动（⑦–⑪）必须 **fail-open**：索引不可用/异常/超限 → 无条件回退全量 `rg` / 整树语义；绝不假阴、绝不泄密。
- **没有分母不谈余量**：上下文窗口的分母只认**用户登记的**窗口；未登记就只报分子。不准拿「跑得久 / 被压过」当余量判据（历史事故：据此判"到窗口边缘"，实际约 30%）；阈值类配置（水位 / 压缩比）不进模型可见文本。
- **改工作树的 git 动作必须先说明**：`stash` / `checkout` / `clean` / `worktree add` 动手前先讲清"要动什么、留什么、怎么回退"；**禁止**用它们判「某条红是不是本次改动造成的」——那条判断走开关对照 / 独立进程 / `scripts/baseline_run.*`（临时 worktree，只读 HEAD）。

## 指针（细则不内联；需要时用 Read / Skill）
- 入口与引擎约定：`AGENTS.md`；引擎入口 `python/engine/query_loop.py`，HTTP 服务 `python/server/app.py`，WSC 投影 `python/memory/wsc_projection.py` → `python/synaptic/project.py`。
- WSC 修复状态与证据：`docs/wsc-open-issues.md`、`docs/wsc-loop-notes-2026-10-07.md`、`docs/wsc-root-contracts-evidence-2026-10-08.md`。
- 长流程（发版等）→ `.xeyo/skills/<name>/SKILL.md`，用 Skill 工具按需加载
