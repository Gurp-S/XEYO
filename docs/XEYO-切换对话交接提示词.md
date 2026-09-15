# XEYO 上下文交接提示词（新会话用）

> 用途：把这个文件整段贴到新对话开头。**不是给本机用的**——新会话里的 Agent 不认识你、不认识这个仓库、不认识这段历史。
> 篇幅：能精简就精简，能引文件就引文件，不复述结论。

---

## 项目身份

仓库：`D:\lea\XenYon code`（中文名"XEYO code"），本地编码 Agent。
规模：python 引擎 1141 文件 / 160,772 行；gui/src 391 / 81,484 行；tui 3,544；rust 1,162。**`scripts/check.ps1` 是提交门**（pytest not-live + tsc + vitest）。

读代码前必读：仓库根 `AGENTS.md`（**v1 引擎铁律 + 提交门 + T_now 登记表 + Bash 透明路由**），以及本机长期记忆 `D:\lea\XenYon code\.workbuddy\memory\MEMORY.md`（红线密集，含 Bash/Shell/python 解释器/git 铁律/发布链路成本口径等已踩坑记录）。

## 工作环境

- **clash 代理**端口 `127.0.0.1:7897`。`git cat-file` 走 promisor fetch、npm 拉 dsh 镜像、curl 出口都必须配上，否则失败。
- **python**：
  - **测试必须 `python\.venv\Scripts\python.exe`**（fastapi 0.141.1 等齐全）。`py -3.11` 也可。
  - **managed python 3.13.12 缺 fastapi**——跑 `test_server_gate_*`/`test_usage_ssrf_guard` 都会 collection error。
  - 跑 pytest 加 `--basetemp=<全新路径>`，避免 basetemp 竞争假失败。
- **git 铁律**：① `git stash` 实测 4 次击穿 `.git`（refs + 对象库清空），禁；临时挪文件改 `git diff -- <path> > patch.diff` + `git checkout -- <path>`；② 多会话并行 commit 用 **路径限定** `git commit -m "..." -- <path>`，禁 `git add -A`；③ 提交前 `git status` 看有无别人的在途改动；④ 当前分支 `main`，无 remote；bare mirror 在 `D:\lea\XenYon-git-mirror-20260905-1340.git`（remote 名 `mirror`），并发写会互踩。
- **解释器以外的工具坑**：gui 用 `npx tsc --noEmit` + `npx vitest run`；rust `cd gui/src-tauri && cargo check`（≈6.5 分钟）；CLI 子命令含在 `python/cli/` Typer。

## dsh 对照仓库

`D:\lea\dsh-src` —— GitHub `deepseek-ai/deepseek-harness` (commit `d347e70`, master)。255 包 / 1611 src ts / 51 会话事件 / 863 测试。仅做考古对照，**不导入其代码**。

## 今日产出（按读序）

如果用户问"我们这些天干了什么"，按这个顺序读：

| 序 | 文件 | 行数 | 内容 |
|---|---|---|---|
| 1 | `docs/XEYO-vs-DeepSeekHarness-全量对比.md` | 605 | R1 功能面清单 |
| 2 | `docs/XEYO-vs-DeepSeekHarness-设计级对比-第二轮.md` | 1307 | R2 设计级 32 系统 |
| 3 | `docs/XEYO-vs-DeepSeekHarness-实现级对比-第三轮.md` | 2246 | R3 实现级 + 三处更正 |
| 4 | `docs/XEYO-vs-DeepSeekHarness-逐字段级对比-第四轮.md` | 1505 | R4 逐字段枚举 |
| 5 | `docs/XEYO-vs-DeepSeekHarness-机制设计说明-第五轮.md` | 2017 | R5 机制面（设计意图+不变量+算法） |
| 6 | `docs/XEYO-vs-DeepSeekHarness-五轮合集.md` | 9811 | R1–R5 + 决策 合并全集（**首选读这份**） |
| 7 | `docs/XEYO-开源优化路线-五轮总结.md` | 532 | R6 收官决策——按什么顺序做 |
| 8 | `docs/XEYO-高杠杆优化点-收益评估.md` | 745 | R7 收益评估（五维打分+一页结论） |
| 9 | `docs/XEYO-未开启功能全清单-与原因.md` | 279 | R9 开关盘点 238 个 |
| 10 | `docs/XEYO-开关处置与优化优先级-决策汇总.md` | 576 | R10 三件事落改+三轨优先级 |

合并工具脚本仍在 `scripts/tmp_merge_docs.py`、`scripts/tmp_verify_claims.py`、`scripts/tmp_finalize_merge.py`——下次跑合并前先看。

## 本轮刚改了什么（路径限定提交）

R10 改了 7 个文件：

```
M python/memory/memory_switches.py                # 注册表 4→6 列（加 exposed/ignored）；新增 prune_stale
M python/server/routers/control.py                # GET 报告残留，POST 自动清理
M python/server/__main__.py                       # 启动期调 apply_to_environ+prune_stale
M gui/src/lib/api.ts                              # 类型加 exposed/ignored/effective/stale/pruned
M gui/src/components/MemorySwitchesSetting.tsx    # 完全重写为 exposed 驱动
M gui/src/components/SettingsModal.tsx            # 入口文案/警告改写
M python/tests/test_memory_switches.py            # 新增 4 类断言
M python/tests/test_memory_switch_authority.py    # 扩写 index_live 默认 0 注解
```

**核心修法（不是打补丁）**：原缺陷是"保留占位键 → GUI 显示开 → 运行时恒关"。正确修法是**让注册表自己说话**：exposed 驱动 UI、ignored 自陈下线语义、effective 与 value 解耦、prune_stale 把陈旧键自动清掉。

## 等你（或下一会话）裁决的三件事

1. `python/cli/feature_registry.py` —— 与权威注册表口径冲突、零生产消费方。**建议删**；收编成本显著更高。
2. `python/memory/*_enabled()` 等恒真**函数** —— **保留**（它们是刻意保留的回退句柄）；但函数内的恒真**死分支**可删（属清理范畴，不影响行为）。
3. `MemorySwitchesSetting` 的"A3 监控快照行"——按"面板只留 C2"的口径**保留**（它不是开关，是状态行）。

## 红线 / 踩过的坑

- **T_now 块**：`prompt/pre_llm_inject.py::T_NOW_BLOCK_REGISTRY` 硬顶 21 块、加 1 必删 1；所有装配走 `_tag_block()`；裸 `tagged.append(` 即红；测试 `tests/test_t_now_block_registry.py` 机器执法。
- **JSONL 撕裂**：读侧 `except JSONDecodeError: continue` 静默吞——下次找"丢了一半的事"记得查这。
- **fsync 默认关**（`XEYO_REWIND_FSYNC=1` 才开），见 `rewind/journal.py`。
- **覆盖率门**：不做 per-file 100%——只做覆盖率 **ratchet**（不下降）。
- **第五轮确认的事实**：`usage/pricing.py` 价格表 **仍是 2026-08-17 旧价**（flash 空闲 0.05/1.5/4.5 高峰×2），新价未同步——预算口径与用户决策有 1 个月缺口。
- **`XEYO_BENCH_MINIMAL`（TerminalBench 评测）**：只允许影响**工具集**，不得影响信息正确性（AGENTS.md 明文）。
- **更贵的隐性陷阱**：全仓有 **12 个 `*_shadow.py` 侧挂模块**，其中 **10 个已经由 `sidecar/policy.py:sidemod_promote()` 默认 True 升格开**——它们 docstring 写的"默认关"是**升格前的旧描述**。读 docstring 不读 `enabled()` 函数体会报 10 个假"没开"。唯一真默认关的是 `extension/mcp_name_manifest_shadow.py`。
- **核实脚本本身必须被核实**：第五次实战教训。提取器错有特征形状——整数整十整百变小（千位下划线 `6_000` 被 `\d+` 吃成 `6`）、否定断言返回 0 命中、两个不同的量算成一个。先怀疑自己、再怀疑文档。

## 工地状态

git status 里有大量改动但都不在本轮署名内（`Composer.tsx` / `ChatHeader.tsx` / `pre_llm_inject.py` 等累计在途），**与本会话无关**，交给你**审**。新会话开始的第一步建议：

```
git status                            # 看有没有别人（在途）进来
git log --oneline -10                 # 看是否有人 commit
git -C D:/lea/dsh-src status          # 平行会话可能在那改东西
```

## 一句话总结

XEYO 这次的当务之急是**先把"开了就是巨大收益"的 6 项"卡在前置"的项目解锁掉**——而解锁它们的前置是**命名事件瀑布 + 投影层算子 + compression 事务化**。沙箱按收益最大但行为边界最大排在最后。任何"看起来很赞但没前置机制落地"的功能（offload / aging / wall / MCP）**统统先停**。

全仓对比权威结论以 `docs/XEYO-vs-DeepSeekHarness-五轮合集.md`（9811 行）为准；优化决策以 `docs/XEYO-开关处置与优化优先级-决策汇总.md`（576 行）为准。冲突以轮次更高者为准。

— XEYO 项目助手（2026-09-10 23:14 交接）

---

## 附：新会话第一句话建议模板

```
[粘贴本文件以上所有内容]

下一步你只做一件事：根据 docs/XEYO-开关处置与优化优先级-决策汇总.md §9 等我
裁决的三件事，给我列出每件事的代码改动 + 一份 PRD + 一份验收方案（构造性测试
或可观测指标）。不要直接动代码，先给我看方案。
```
