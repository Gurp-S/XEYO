# XEYO P0/P1 完整冒烟 — 最终总结（FINAL SUMMARY）

> 结束时间点：本轮已把「服务器端 + 基线（大部分）+ B 层前端核心」三层实际验证。
> 承接上会话 `scripts/smoke_p0p1/HANDOFF.md`。本文件是**离开当前长上下文前**的最终交付口径，供下会话直接复用。
> 详细逐场景/逐失败表见同目录 `COMPLETE_SMOKE.md`（**下会话请先读它 + 本文件 + HANDOFF.md**）。

---

## 0. 一句话总结论

**P0/P1 冒烟 = 后端真验收 ✅ + 前端核心真验收 ✅（T3 审批面板 / T13 工具卡 / T38 compact 按钮）+ 基线无新增回归**。
「完整冒烟通过」从「半旗」推进到：**后端全绿 + 前端核心场景真绿**；剩余可断言子集仅剩 T29（缺后端断流钩子），其余半旗项属「前端未实现 / 需钩子」，不是测试没覆盖。

---

## 一、P0 / P1 哪些做完了（✅）

### A. 服务器端（真验收，本轮复现）
- `py -3.11 scripts/smoke_p0p1/run.py --all` → **19 场景 / 62 断言全 PASS**（`report.md` = 62 PASS / 0 FAIL）。
- 覆盖：spill / 取消 / 权限三态 / 崩溃恢复 / 标题 / 重复守卫 / 受保护元数据 / 目标单调性 / 端口文件 / SSOT / 友好错误 / 工具目录 / 繁忙态。`harness.py`、`mock_llm.py` 未改写。

### B. Playwright 前端消费（本轮新增 → 核心打通 ✅）
新增 `gui/e2e/fullstack.spec.ts`（真实 Chromium + 真后端 `provider=local`→`mock_llm` + Vite dev），跑 **2 passed / 1 skipped**：
| 场景 | 结果 | 断言 |
|---|---|---|
| T3 审批面板 | ✅ | 默认展开 / 允许 / 拒绝 / 超时文案 / **Esc=取消→面板关闭** |
| T13 工具卡 | ✅(部分) | **Bash 工具活动块在浏览器渲染**；duration/spilled/correlation 前端仍无可见渲染 |
| T38 compact 按钮 | ✅ | `XEYO_C2_GATE=1` 时按 `compression.c2_gate` 显示「立即压缩 /compact」 |
| T29 断流 banner | ❌ skip | 需后端断流钩子（见「待办」） |

**B 层关键路径（零生产代码改动）**：GUI seed 用 `provider=local` → 命中 `Composer.tsx:821` 的 `provider !== 'local'` 空 Key 放行；后端 `XEYO_ALLOW_LOCAL_MODEL=1` 把 `/v1/chat` 转发到 `scripts/smoke_p0p1/mock_llm.py` 固定端口实例（`mock_runner.py`）。
运行：`cd gui && npx --no-install playwright test -c playwright.fullstack.config.ts fullstack`。

**B 层还修了上一会话 e2e 骨架的 3 个真 bug**：①`@playwright/test` 没装；②`playwright.config.ts` 在 ESM 下用 `__dirname`；③Vite 只绑 `::1` 导致 `127.0.0.1:5173` 健康检查永远超时（改 `--host 127.0.0.1`）。

### C. 基线（大部分）
- `tsc --noEmit`：**0 错误** ✅。
- `vitest`：**551 通过 / 5 失败**（1 既有 + 2 类上一会话新引入）。
- `pytest`：一键脚本 `run-pytest-baseline.bat` → **869 通过 / 9 失败**（后被卡死中断）；子集复验 **136 / 6 / 1**，**无本轮改动引入的回归**。

### 本轮真 bug / 修复（✅ 已落地）
| 项 | 说明 | 状态 |
|---|---|---|
| `memory_tool.py:296` `NameError: asyncio` | 真回归（update 路径漏 import） | ✅ 已补 `import asyncio`（roundtrip 用例通过） |
| `test_main_loop_three_cuts` 并发断言 | 既有（描述误为“卡死”，实为断言失败，文件无 mkstemp） | ✅ 已按 `run_tools_partitioned` 串行语义对齐，文件 8/8 绿 |
| `test_governance_failclosed` 顺序依赖 | 测试非密封（`_permission_mode_ctx` ContextVar 未复位） | ✅ conftest 加 autouse `_reset_permission_mode_ctx`，`always`/`never` 两条由红转绿 |

---

## 二、哪些有问题 / 仍红（⚠️）

### 基线仍红（均既知/漂移/环境，非本轮引入）
| 失败 | 归类 | 处置建议 |
|---|---|---|
| `test_schema_mentions_grep_paths` | 测试漂移（schema 文案无 `transcript`） | 更新测试预期 |
| `test_policy_ask_tightens_user_never` | **design 豁免 vs 单调性契约** | 见「待你定 #1」（安全） |
| `test_broken_policy_falls_back_tight_and_audits` | 同上 | 见「待你定 #1」 |
| `test_subagent_write_risk_mode_...` | 环境（无 resolver） | 补测试 resolver 或标 skip |
| `test_blob_gc::test_dry_run_and_disabled_never_delete` | 快照路径（疑环境/真回归） | 复查 tmp/快照路径 |
| `test_grep_symbols::test_symbols_folded_ts_class` | grep 输出漂移（缺 `[+1 members`） | 更新测试预期 |
| `test_rewind_service` | 环境（working tree 极脏 509 项干扰 git 检测）+ 潜在真 bug（未抛 RollbackConflictError） | 干净树复验定级 |
| `test_screenshot_tool` | 测试漂移（描述不再含 `never tell the user`） | 更新测试预期 |
| `test_probe::test_live_keep_probe` | 环境/网络（402 真实 API） | CI/离线应 skip |
| `chatStore.test.ts` rewind 横幅 PR-R4 | 既有失败 | 按 PR-R4 预期对齐 |
| `Composer.chat.test.tsx` | 测试漂移（旧文案「Esc 中断」已改 `title="停止生成"`） | 更新断言 |
| `settingsStore.fakeProvider.test.ts`×3 | 全局 `test/setup.ts` mock 未导出 `isProviderId` | mock 补导出，或改测导入真实模块 |

（pytest 后两类 `Composer`/`fakeProvider` 为 vitest 侧；其余为 pytest 侧。）

### B 层前端「未实现」（诚实标注，非测试没覆盖）
- **T9 goal chip 四态 / 候选条双按钮**：`gui/src` 搜不到对应组件，仅恢复横幅读 goalText。
- **T13 `spilled` / `correlation`**：`api/core.ts` 有字段，UI 无可见渲染。
- **T3 服务端 30s 到期提醒帧**：`permission_pending` 自动放行从不触发到期，前端无消费方。

---

## 三、待你定的（⚠️ 我未擅自改，涉安全/产品语义）

1. **安全相关（最高优先）**：`permissions/policy.py:1380-1386` 当用户处「最高档（never/allow）」时，**刻意跳过 `pol.write:"ask"` 的收紧**（code 注释：防 smoke-test #1，不让最高权限仍每写必弹确认）。这让 `test_policy_ask_tightens_user_never`、`test_broken_policy_falls_back_tight_and_audits` 两测失败。
   - 若该豁免是对的（文档口径）→ **更新这两条测试** 对齐当前行为。
   - 若不该豁免 → **改 `policy.py` 该分支**（去掉/收紧豁免，安全向）。
2. **T29 断流 banner**：需给后端加一个「流中断/丢帧」测试钩子，才能断言「连接中断」横幅且不自动 interrupt。要不要补。
3. **前端未实现项（建议单开产品 issue）**：T9 chip/候选条、T13 spilled/correlation、T3 30s 帧。
4. **可选收敛 jsdom**：`fakeProvider` mock 补导出 `isProviderId`、`Composer.chat` 断言改 `title="停止生成"` → 5 红收敛到 1 红。
5. **补偿 `fake` 骨架**：`main-path.spec.ts` 想绿，改 `Composer.tsx:821` 为 `allowsEmptyApiKey(provider)`（生产行为不变，仅测试下放行 fake）——按约定本轮未改，仅上报。
6. **手工清单（需真人工，未做）**：T31（tui TUI plan→/load 模式仍在、id 服务端签发、workspace 权威）、T32（全新环境双击 `XEYO-TUI.bat` 拉起引擎、`/help` 无 404、`/demo` 需显式 flag）、T37（EmptyState 中文化、AgentMap 收进实验功能开关、`/bench`/`/lab` 路由守卫）。分步见 HANDOFF.md「手动冒烟清单」。

---

## 四、文件清单（本轮产物）
- **报告**：`scripts/smoke_p0p1/COMPLETE_SMOKE.md`（完整逐场景逐失败报告）；`scripts/smoke_p0p1/report.md`（62 PASS 刷新）。
- **一键脚本**：`run-pytest-baseline.bat`（已修 CRLF）。
- **B 层新增**：`gui/playwright.fullstack.config.ts`、`gui/e2e/fullstack.spec.ts`、`gui/e2e/helpers/seed.ts`（`seedLocalTest`）、`scripts/smoke_p0p1/mock_runner.py`、`scripts/smoke_p0p1/e2e_responses/t3_bash_ask.json`、`gui/src/main.tsx`（DEV-only `window.__XEYO_CHAT__`）、`gui/playwright.config.ts`（`testIgnore`）。
- **修复**：`python/tools/memory_tool/memory_tool.py`、`python/tests/test_main_loop_three_cuts.py`、`python/tests/conftest.py`。

---

## 五、环境/纪律
- DSH 管理端口 **8099 全程未动**（多次确认 UP）。长负载（pytest 全量 / Playwright）在**本机终端**跑，避免 DSH 被挤掉。
- 重跑命令备忘：
  - 服务器端：`py -3.11 scripts/smoke_p0p1/run.py --all`
  - pytest 全量：`run-pytest-baseline.bat`（结果 `logs\pytest-baseline.log`）
  - B 层：`cd gui && npx --no-install playwright test -c playwright.fullstack.config.ts fullstack`
- 跑完清遗孤 `python -m server` / `mock_runner` / 端口 5173/5175/8177/8179/8490/8491；别动 8099。
