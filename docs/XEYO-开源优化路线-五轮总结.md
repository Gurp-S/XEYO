# 五轮对比总结：最适合用来优化 XEYO 的点

> **本文性质**：不是第六轮对比，而是**决策文档**。前五轮回答"两端各是什么样"，本文只回答一件事：**在五轮发现的所有差异里，哪些点最适合用来改进 XEYO，按什么顺序做。**
>
> **取证口径**：本文所有事实引用均来自前五轮报告的实测行号，另在落笔前**新增核实了三处**（§2 的三条更正）。凡与前面轮次冲突，以本文为准并已给出复现命令。
>
> **目标读者**：决定"下一步做什么"的人。看完 §3 的表 + §4 的详解就够开工；§5 是红线自检，§6 是顺序，§7 是明确不做的事。

---

# §0 五轮回顾（一页纸）

## 0.1 五轮各自产出了什么

| 轮次 | 文件 | 行数 | 视角 | 回答的问题 | 该轮的主要更正 |
|---|---|---|---|---|---|
| 一 | `XEYO-vs-DeepSeekHarness-全量对比.md` | 605 | 功能面 | 有什么 / 没什么 | —（初版，含 1 处归属错误） |
| 二 | `...设计级对比-第二轮.md` | 1307 | 设计面 | 32 个系统怎么设计、为什么 | 更正一：dsh **没有** `Mcp` 网关工具、工具面**不冻结**（第一轮把 XEYO 的契约抄到了 dsh 列）；更正二：`engine/scheduler.py` 不是死代码 |
| 三 | `...实现级对比-第三轮.md` | 2246 | 实现面 | 函数签名 / 算法步骤 / 常量 | 计数更正：XEYO 19 事件 + 23 SSE 帧；dsh 48 事件 |
| 四 | `...逐字段级对比-第四轮.md` | 1505 | 枚举面 | 每个类型每个字段每个键名 | 更正：dsh 事件 **51**（第三轮正则漏 3 个双斜杠键）；`packages/client` **45** 子包；62 条工具目录 = **57** 唯一工具 |
| 五 | `...机制设计说明-第五轮.md` | 2017 | 机制面 | 同一个问题两端怎么解 | 新发现：`hotpath.py:1-13` 注释写的是 v3.0 旧合同；`usage/ledger.py:66-76` 明确写着"对齐 DeepSeek Harness 记账纪律" |

**累计 7680 行**，覆盖 dsh 全部 9080 个受控文件与 XEYO `python/`(1141 文件) + `gui/src`(391) + `tui/` + `src-tauri/`。

## 0.2 五轮读下来的三句话

1. **dsh 强在"层"，XEYO 强在"纪律与运营"。**
   dsh 的五处是**可复用架构层**：事件溯源日志、沙箱、类型化协议、组合层（profile/bundle/preset）、质量门。XEYO 的四块是**把一件事做到底的产品能力**：注意力治理（T_now）、工作区可逆性（rewind 五件套）、权限细化（11 级链 + 指纹 v2）、成本治理（峰谷 + 账本 + 归因）。

2. **最根本的分岔是"可信边界放在哪"。**
   dsh 放内核（沙箱）与类型系统；XEYO 放文本分析与测试断言。**这决定了两端策略的粗细**——dsh 的权限策略可以粗，因为下面有内核兜底；XEYO 必须细，因为正则就是最后一道防线。

3. **两端是镜像，不是趋同。**
   XEYO 冻结工具面 → 必须发明网关工具绕过自己；dsh 不冻结 → 不需要网关，代价是靠类型化 RPC + 事件溯源保证一致。**同一段代码不会同时服务两个目标。**

## 0.3 一个必须先说的口径修正

第五轮发现：`usage/ledger.py:66-76` 的注释逐条引用了 dsh 的 S2/S4/D-3 记账纪律。**所以两端是"架构独立、局部借鉴"，不是"完全独立演化"。** 这对本文的意义是：**借鉴不是破例，XEYO 已经在这么做了，且有先例可循。**

---

# §1 筛选准则：什么叫"适合用来优化 XEYO"

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

# §2 落笔前新增核实的三处事实更正（重要）

**这三处直接改变了推荐的形态。** 前五轮有三条建议是基于不准确的事实提的，如果不先纠正，会给出"要做很多其实已经做了的事"的假建议。

## 2.1 更正一：XEYO **已经有投影层**，差距是"算子种类"而不是"有没有层"

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

## 2.2 更正二：XEYO 的 JSONL **已有写后缓冲 + fsync + 轮转**，只缺"撕裂尾修复 + 跨进程租约"

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

## 2.3 更正三（**本文最重要**）：dsh 的沙箱**有 Windows 后端**，XEYO 可以直接对照移植

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

# §3 候选池与排序（核心结论）

## 3.1 总表

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

## 3.2 一句话排序理由

**先做 P0（两个小改动，两周内可见收益，零架构风险）→ 再做 P1（投影泛化 + 压缩事务 + 命名事件，三者互相成全）→ 最后啃 P2（沙箱是"换地基"，必须等前三项让代码变干净之后再动）。**

**注意顺序不是按差距大小排的。** 沙箱差距最大，但它排最后，原因有三：
1. 它是**唯一会改变现有行为边界**的改动（confine 之后原本能跑的命令会失败），必须先有**审批分级 + 命名事件**（P1-#7、P1-#6）把"失败时如何优雅降级"这条路铺好；
2. 它做完会**连带简化权限链**——如果先做沙箱，那 11 级链可能就白改了；
3. 它是**唯一无法旁路验证**的一项，需要最干净的代码基线。

---

# §4 逐项详解

## P0-1 工具结果头尾预算 + spill 可取回

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

## P0-2 JSONL 撕裂尾修复 + 跨进程租约

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

## P1-3 投影层加通用 `replace` 算子 + 来源追踪

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

## P1-4 压缩事务化：括号事务 + 工具配对平衡

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

## P1-5 命名事件瀑布（先只做"命名"）

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

## P1-6 审批审计配对 + 审批策略不入 transcript

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

## P2-1 沙箱 `confine(argv, policy)` seam + Windows restricted-token 后端 ★最大项

**问题**：XEYO 的 Bash 一落地就**没有第二道防线**。现有的一切（11 级权限链、18 条 bash 正则、密钥拦截、WriteStore 三门）**都是文本分析**——它们让误用变难，但不构成隔离。

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

## P2-2 会话自查询工具

**问题**：XEYO 有 `_workspace_index.jsonl` 与完整 transcript，但**模型自己不能查**。dsh 有 5 个会话历史自查询工具（`session_event_read` / `session_event_search` / `session_event_trace` 等，第三轮 §2）。

**落点**：`python/tools/` 新增只读工具，注册进 `TOOL_META`（注意 `tools/catalog.py:359` 的 `XEYO_BENCH_MINIMAL` 裁剪集要同步决策）。

**验收判据**：能回答"上一轮我改了哪些文件"并给出行号级证据；工具是只读的（不触发权限 ASK）。

**风险提示**：这是**唯一一条可能触碰应试性红线**的建议——见 §5.2。

---

## P2-3 质量门分级

**问题**：XEYO 的提交门是 `scripts/check.ps1`（pytest not live + typecheck + vitest + slash manifest check），**没有覆盖率门**。dsh 是 **per-file 100%**。

**落点**：`scripts/check.ps1`、`.github/workflows/ci.yml`。

**改动**：**不做 per-file 100%**（对 160k 行 Python 不现实，见 §7），改做：
- 新增/修改的文件覆盖率 ≥ 80%；
- `python/rewind/`、`session/`、`permissions/` 三个高风险模块整体 ≥ 70%；
- 覆盖率**只降不升即红**（ratchet，防止倒退）。

**验收判据**：故意删一个测试 → CI 红。

---

# §5 红线自检：逐条过应试性审查

XEYO 有一条用户红线：**任何修改不能是应试修改**。四条尺子（`docs/应试性审查-副作用修复与53号.md`）逐条对本文 10 项建议过一遍。

## 5.1 R1 产品受益（不是只评测受益）

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

## 5.2 R2 无评测分支（**唯一需要注意的一项**）

**P2-2 会话自查询工具**存在一个风险面：dsh 的 `session-query` 包在 TerminalBench 场景下**可能恰好受益**。若实现时出现下面任何一种形状，**即为应试**：

- ❌ `if os.environ.get("XEYO_BENCH_MINIMAL")` 或 `if 任务名 in ...` 才注册该工具；
- ❌ 工具的查询能力**只能读评测判分器需要的东西**；
- ❌ 该工具只为"让模型看到更多历史"而存在，而正常用户场景下无意义。

✅ **正确的形状**：工具无条件注册、无条件可用，收益在**用户日常使用**中可观察到（"上一轮我改了哪些文件"）。

**P2-1 沙箱的对称风险**：若写成"容器路由就跳过 confine"，即为应试——这条 `AGENTS.md` 已经明确禁止（*"'容器路由就跳过'一律应试，禁止"*）。正确写法是 **confine 与执行通道无关**，容器内也要过同一层判定。

**其余 8 项不存在评测分支可能。**

## 5.3 R3 信息纪律（不注入引擎无法核实的事实、不做导演）

**P0-1 有一处需要注意**：spill 后的替代文本**只能给事实**。

- ✅ `完整输出已落盘：<path>`（事实）
- ❌ `建议你读取完整输出`（导演）、`输出被截断了，请注意`（评价）

其余各项：
- P2-1 沙箱的拒绝措辞必须是**中性结果型**（`Permission denied: …`），符合引擎铁律第 3 条；
- P1-3 投影层的 `source_event_seqs` 是给**审计侧**用的，不注入模型上下文；
- P1-5 命名事件**不产生任何模型可见文本**（只进审计/telemetry）。

## 5.4 R4 收益可证伪

**全部 10 项均给出了构造性判据**（§4 每项的"验收判据"），且**不依赖判分器或 `/tests` 目录**。这是本文筛选时最花力气的一条——凡是只能说"更好"的都已被剔除。

**逐条复核**：P0-1 用 `FINAL_MARKER`；P0-2 用半行 JSON 注入；P1-3 用"20 行→3 行但人类侧 20 行"；P1-4 用"cut 点落在配对中间"；P1-5 用"关掉后逐字节一致"；P1-6 用审计配对可查；P2-1 用"read-only 下写失败、读成功"；P2-2 用"能回答且给证据"；P2-3 用"删测试即红"；P3 用"定时真的触发"。**无一条依赖外部判分。**

## 5.5 自检结论

**10 项建议全部通过 R1/R3/R4；R2 有两项需要实现时守住形状（P2-2 无条件注册、P2-1 不按执行通道分叉）。**

---

# §6 建议的实施顺序与依赖

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

# §7 明确不建议照搬的清单

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

# §8 结论（一句话级）

1. **五轮 7680 行，最终要做的不是十件事，是一个顺序**：先用两个小改动（P0-1/P0-2）建立"构造性测试"的节奏，再用三个互相成全的中项（投影泛化 → 压缩事务 → 命名事件）把代码变干净，最后才动唯一一件"换地基"的事（沙箱）。

2. **沙箱是唯一一项"做了会连带简化其他一切"的改动**——它做完，11 级权限链、18 条 bash 正则、WriteStore 三门这些"因为有风险所以必须细"的设计都可以变粗。这才是它排在最值得做的第一位的真正理由，而它排在实施顺序的最后一位，是因为它最需要干净的地基。

3. **而它现在有了一条 Windows 路径**（restricted token + ACL 写授权，只交写不交读，不需要动宿主 DACL）——这消除了"XEYO 是 Windows 产品所以用不了沙箱"这个最大的落地顾虑。**这是本文最有价值的单条发现。**

4. **XEYO 不需要"补成一个 dsh"**。它的四块独有资产（T_now 治理 / rewind 五件套 / 权限细化 / 成本治理）里，有三块是 dsh **完全没有**的。要做的是**在它现有的纪律下面铺一层地基**，而不是用地基替换纪律。

5. **两条硬红线在实施时守住**：P2-2 必须无条件注册（不得有 `BENCH_MINIMAL` 分支），P2-1 不得按执行通道分叉（"容器路由就跳过"一律应试）。其余八项无风险。

---

*本文基于五轮共 7680 行对比报告；§2 的三处更正为本文落笔前新增核实，均可一行命令复现。若与前面轮次冲突，以本文为准。*
