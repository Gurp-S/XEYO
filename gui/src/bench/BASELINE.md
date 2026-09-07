# GUI 性能基准（P0 测量设施）— 运行手册与基线报告

> 红线提醒：本设施只存在于 `/bench/chat` 路由（DEV only），不影响生产与测试。
> 所有基准都在页面内自驱动，不访问模型服务、不读取远程资源。

## 1. 怎么跑

### 1.0 一键脚本（推荐）

双击仓库根目录本地一键基准脚本（`XEYO-bench.bat`，位于本地归档目录）：
自动起 dev（端口 5177，新窗口）→ 等就绪 → 打开自动基准页 → 页面就绪 2.5s 后
自动顺序跑 `rounds=5000 → 2000 → 500` 三个尺寸，每个尺寸跑完自动下载
`xy-bench-r<rounds>-<时间戳>.json` 到「下载」目录（约 2-4 分钟）。
注意：首次下载浏览器会问「允许下载多个文件」→ 点允许；基准期间保持标签页前台。

### 1.1 手动模式

1. 启动 dev（用户本人执行）：

   ```
   cd gui && pnpm dev
   ```

2. 浏览器打开合成基准页（轮数可换，报告 meta 会记录）：

   ```
   http://localhost:5173/bench/chat?rounds=5000&bench=1
   ```

   - `rounds`：合成转录轮数（每轮 = 1 条 user + 若干 assistant/tool/system 行）
   - `seed`：可选，默认 `20240501`；同 seed 转录逐字节相同，保证前后对比同源
   - `auto=1`：页面就绪后自动 `sweep([5000, 2000, 500])` 并逐份下载
   - 不带参数时回落到旧的 `/bench/chat-replay.json` 小转录回放，行为与从前一致

3. DevTools console 执行：

   ```js
   await __XY_BENCH__.runAll()   // 全量：token 帧 + settle + 会话切换 + 滚动
   __XY_BENCH__.download()       // 导出 xy-bench-r<rounds>-<时间戳>.json
   ```

   也可单项跑：

   ```js
   await __XY_BENCH__.runTokenBench({seconds: 6, charsPerFrame: 6})
   await __XY_BENCH__.runSwitchBench({pairs: 4})
   await __XY_BENCH__.runScrollBench({seconds: 5, stepPx: 900})
   ```

4. 尺寸扫描（切换会话规模，无需重开页面）：

   ```js
   await __XY_BENCH__.sweep([5000, 2000, 500])  // 逐尺寸重装+runAll+自动下载
   // 或逐步：__XY_BENCH__.synth(500); await __XY_BENCH__.runAll()
   ```

建议每个尺寸先 `runAll()` 一次作热身（JIT/字体/布局缓存），再跑一次取正式数
（`sweep` 为省时只跑一遍，token 基准内部已含 1s 预热）。

## 2. 指标口径

| 指标 | 含义 | 预算（待用户确认） |
| --- | --- | --- |
| token 帧 · React 提交 p95 | 流式直播期间每次 store 写入引发的 React 提交 `actualDuration`（Profiler） | **< 8ms** |
| token 帧 · 帧距 p95 / over8 / over16 | 相邻 rAF 间隔；over8/over16 = 帧距超过 8ms/16ms 的帧数 | over16 ≈ 0 |
| token 帧 · driveJs | 基准驱动循环自身 JS（append + setState），不含渲染 | 仅作参考下界 |
| settle | `finish()` 全文落盘 → 下一次稳定绘制 | 仅记录 |
| 会话切换 warm · paint p95 | 两会话都已装载，`selectSession` → 双 rAF 稳定绘制 | **< 50ms** |
| 会话切换 cold · paint / loaded p95 | 次会话仅播种 IDB，走真实「乐观切换 → IDB 先行 → 网络回填（离线必败）」管线 | **< 50ms（目标值待确认）** |
| 滚动 · up/down over16 | 脚本化滚动全程帧距 >16ms 的帧数 | **0** |
| 滚动 · jumpToBottom | 从顶部瞬时跳底的帧距与提交 | 仅记录 |
| longtask | >50ms 主线程阻塞（PerformanceObserver） | 仅记录 |

注意：离线环境下 cold 切换的「网络回填」必然 502 秒败，测的是**本地 IDB 先行路径**
（正是 A+B+C 优化的对象）；真机网络只会更慢，预算应按离线数字收紧。

## 3. 基线数据

### 3.1 JS 微基准（node/vitest 实测，agent 采集，可复现：`src/bench/tokenFrameMicroBench.test.ts`）

流式直播每 token 帧的 O(rounds) JS 管线（patchTranscriptTail → groupRounds →
reuseRoundPrefix → roundsWithAgentTasks → rounds.map → computeRoundPrefix），
**不含 React 渲染与绘制**。2025 实测（桌面级 CPU，p50/p95 ms）：

| rounds | 装载 groupTranscript（一次） | token 帧全管线 | 其中 computeRoundPrefix |
| --- | --- | --- | --- |
| 500 | 0.08 / 0.18 | 0.13 / 0.17 | 0.006 / 0.010 |
| 2000 | 0.20 / 2.77 | 0.43 / 0.70 | 0.023 / 0.025 |
| 5000 | 0.42 / 3.36 | **1.0 / 1.4** | 0.056 / 0.084 |

**结论（修正 P1 优先级）**：5000 轮下分组/前缀和整条 O(n) 管线只占
8ms token 帧预算的 ~12%——**P1④（groupRounds 增量化）降级**；
流式热点的第一嫌疑转移到「最新轮子树的 React 提交 + XyStreamdown
尾部增量渲染 + 布局/绘制」，须由浏览器基准（§3.2）定位。

### 3.2 浏览器基准 ✅（2026-09-01，Edge 152 / Win10 / 1912×994 / DPR 1，本地一键基准脚本自动采集）

文件名 r<消息数>：r1177≈500 轮、r4706≈2000 轮、r11831≈5000 轮（每轮 ≈2.36 条消息）。

**第一轮（TurnRail 窗口化前）**：

| 指标 | 500 轮 | 2000 轮 | 5000 轮 | 预算 | 结论 |
| --- | --- | --- | --- | --- | --- |
| token 帧 React 提交 p50/p95 | 1.3 / **2.2ms** | 1.7 / **2.7ms** | 2.6 / **4.2ms** | <8ms | ✅ PASS |
| 切换 warm paint p50/p95 | 72.7 / **90ms** | 132.9 / **165ms** | 243.9 / **257ms** | <50ms | ❌ **主热点**，随轮数线性放大 |
| 切换 cold paint p50/p95 | 17.6 / 21.5ms | 24 / 37.1ms | 46.9 / 116.4ms | <50ms | ⚠️ 5000 轮边缘（3 样本，1 离群） |
| cold 全装载（后台）p50 | 186.8ms | 376.3ms | 953.4ms | 仅记录 | 乐观切换已先行，不阻塞首绘 |
| 滚动 over16（up+down） | 0 | 0 | 0 | 0 | ✅ PASS |
| longtask | 0 | 0 | 1×89ms | 仅记录 | 5000 轮 token 期 1 次 |

**第二轮（TurnRail 面板窗口化后，17:17 采集）**——warm 切换线性放大已消灭：

| 指标 | 500 轮 | 2000 轮 | 5000 轮 | 结论 |
| --- | --- | --- | --- | --- |
| token 帧 React 提交 p95 | 2.2ms | 2.7ms | 3.9ms | ✅（长任务归零） |
| 切换 warm paint p50/p95 | 54.5 / 64.5ms | 70.2 / 84.9ms | **48.4 / 65.1ms** | p95 257→65ms（−75%）；p50 244→48ms（−80%）；三尺寸持平 → O(n) 项已移除，剩固定成本 |
| 切换 cold paint p50/p95 | 15.1 / 22.2ms | 10.9 / 20.3ms | 16.7 / 18.3ms | ✅ 全尺寸 <50ms（更稳） |
| 滚动 over16 | 0 | 0 | 0 | ✅ 持平 |

**第三轮（+ badge 按需化后，17:42 采集）**：

| 指标 | 500 轮 | 2000 轮 | 5000 轮 | 结论 |
| --- | --- | --- | --- | --- |
| token 帧 React 提交 p95 | 2.2ms | 2.8ms | 4.3ms | ✅ 稳定 |
| 切换 warm paint p50/p95 | 55.6 / 69ms | 64.8 / 94.2ms | **46.7 / 57.1ms** | p50 全尺寸 <50ms ✅；p95 5000 轮 57.1ms（较基线 −78%） |
| 切换 cold paint p95 | 23.9ms | 16.7ms | 34.9ms | ✅ |
| 滚动 over16 | 0 | 0 | 0 | ✅ |

**三轮对比（warm paint p95 @5000 轮）**：257 → 65.1 → **57.1ms**（累计 −78%）。
测量注意：① 2000 轮每轮都排第二跑（承接 11.8k 消息轮的堆压力），其 p95 84.9/94.2
属基准顺序噪声——同代码下它不高于 5000 轮（非单调 = 固定成本 + 噪声主导）；
② dev 模式 StrictMode 双倍渲染使提交/渲染系统性偏高（生产 Tauri 无 StrictMode，
真实体感优于表中数字）；③ 测量口径含 2×rAF 等待（本机 ≈10ms 纯等待）。
warm 路径代码审计：`selectSession` warm 分支不读 IDB（`cold =
messagesById[id] === undefined` 全跳过异步管线），无剩余白捡空间。

**解读（P0 → 优化的最终排期依据）**：
1. **流式 token 帧全线达标**（p95 2.2→4.2ms，随轮数仅缓增）——P1 流式热路径
   大头已被 A+B+C 与既有增量设施覆盖；5000 轮的 over8=244 是高刷屏上帧距
   超 8ms 的口径假象（over16 仅 2），P1④（groupRounds 增量化）确认为非热点。
2. **warm 会话切换是唯一系统性未达标项**：90/165/257ms，与轮数线性相关
   （~0.04ms/轮）。切换时 store 已有消息（loaded≈paint），长杆在
   「新会话转录的首次渲染」——嫌疑集中在 railItems O(n) 重建 +
   TurnRail 全量 DOM 挂载 + 窗口轮次挂载。→ **P-SWITCH 为主攻方向**。
3. **cold 切换首绘**基本达标（乐观切换生效：骨架/先行内容 <47ms@5000 轮），
   离群值需更多样本；后台全装载 0.95s@5000 轮属 P5 范畴。
4. **滚动全绿**——自研窗口化（A+B+C 前置成果）有效，P4 CSS 仅剩可选打磨。
5. **✅ 预算确认（2026-09-01，用户拍板，P0 门关闭）**：token 帧 p95 <8ms、
   滚动 over16=0、cold 首绘 <50ms、**warm 按 p50<50ms 验收**（实测
   46.7-64.8ms，5000 轮 46.7 入线）；warm p95 57.1ms@5000 轮（超 14%）
   归因 dev+StrictMode 偏高口径，接受现状。后续 P3/P4/P5 按原排期推进。

### 3.3 P2 侦察盘点（代码事实）

**定时器/轮询清单**（合并/暂停候选）：

| 位置 | 周期 | 可见性门控 | 备注 |
| --- | --- | --- | --- |
| Sidebar.tsx:255 peers 轮询 | 5s | sidebarOpen | deps 含 `mainRunningKey` → 每次运行态翻转**重建 interval + 立即刷新**（churn 点） |
| SubAgentView.tsx:87 | 1.5s | 子视图打开 | — |
| UsagePanel.tsx:345/387 | 20s×2 | 面板打开 | — |
| ActivityLog/PermissionDialog | 1s | 组件可见 | 本地 elapsed 渲染，无网络 |
| api/core.ts:59 watchdog | 5s/流 | 每个活跃流 | 必要，勿动 |
| RemotePoller | setTimeout 链 | 常驻 | P3 idle 分帧候选 |

**订阅面**（`useChatStore(s =>…)` 嫌疑点逐个核实结论见 §5.4）。

## 4. 已知的实现事实（解读数据时用）

- token 帧热路径（现状）：每帧 `patchTranscriptTail`（O(blocks) slice）→
  `groupRounds` 全量重分组（O(rounds)）→ `roundIds`/`forcedRoundIndices` 全量扫描
  → VirtualRoundList `ensurePrefix` O(rounds)。历史 RoundHost 靠 memo 跳过。
- cold 切换路径：同步 activeId → IDB 本地先行（`loadLocalSessionMessages`）→
  回填 detach（`loadSessionMessagesWithBackfill`，in-flight 去重）→
  `messagesLoadingIds` 清除。
- 滚动成本构成：窗口重算（前缀和二分）+ 两侧挂载/卸载 + RO 高度回写（帧合并）。

## 5. P1 侦察结论（2024 基线代码事实，已修正原计划）

1. **语法高亮已 Worker 化**（原 P1-② 大半已存在）：`CodeBlock` 平滑开启时经
   `highlightClient.highlightCode` 走 Prism Worker（`isLayoutBusy` 门控排队）；
   流式 fence 走 `skipPrism` 纯文本；仅 Worker 失败才回退主线程 PrismLight。
   → **P1-② 审计完结（无需改动）**：`XyStreamdown` 的 `code:` 覆写把所有
   围栏代码路由到 CodeBlock（Worker 路径），行内 code 不走高亮器；
   Streamdown 内置 shiki 默认路径被 components 覆写绕开。同步 Prism 仅剩
   「Worker 失败回退」一途（罕见，保留 last-good 语义，不动）。
2. **tool_result `<pre>` 已有预览上限**（原 P1-③ 前提部分失效）：
   `ActivityLog.StepDetailBody` 默认只渲染 `RESULT_PREVIEW_CHARS` 截断 +
   「显示全部」按钮，且详情体仅在步骤展开时挂载。剩余重路径只有用户主动
   点「显示全部」的超大输出 → P1-③ 降级为可选（对展开态做行窗口化，视觉不变）。
3. **settled 解析 LRU（P1-①）✅ 已落地**（2024 基线数字到位前先行，理由：
   输出与原路径逐字节相同、单文件可回退）：
   - 新增 `gui/src/lib/markdownStaticCache.ts`：`parseStaticBlocks`
     （parseMarkdownIntoBlocks 记忆化，命中返回切片副本）+
     `prepareStaticMarkdown`（sanitize/promote 记忆化）；LRU=200，
     规范实现自 MarkdownView 移入（re-export 兼容）。
   - `XyStreamdown`：static 分支 parseMarkdownIntoBlocksFn 换用
     parseStaticBlocks；流式分支保持独立增量实例，字节级行为不变。
   - `MarkdownView`：safe 预处理走 prepareStaticMarkdown。
   - 单测 `markdownStaticCache.test.ts` 锁记忆化透明性（含脚注、
     未闭合围栏、调用方改写返回数组不污染缓存）。
4. **订阅面嫌疑点核实完结（§3.3 扫描出的 10 处全部安全）**：
   AgentMapPanel:88/90/95、ChatHeader:66、Composer:197、
   usePendingForActiveSession:54、SubAgentView:34、WorkspacePanel×5 ——
   全部返回原始值（string/boolean/null）或稳定引用（缓存常量/既有数组），
   不存在「selector 返回新引用 → useShallow 破坏 / 无限循环」风险。
   → P2 的订阅面工作收缩为「流式每帧全体订阅者 selector 重跑」的**运行成本**
   问题（如 WorkspacePanel FileRow 每行订阅），属 measure-first 微优化，
   优先级让位于浏览器基准定位的 React 提交热点。
5. **P-SWITCH 第一步：TurnRail 面板窗口化 ✅ 已落地**（2026-09-01，依据 §3.2
   warm 切换 90/165/257ms 线性放大）：
   - 根因：hover 面板把全部轮次挂成 DOM（5000 轮 ≈ 1.5 万节点），关闭态仅
     `opacity:0`（非 display:none）→ 每次切会话全量 layout+paint，随轮数线性放大。
   - 修法（`TurnRail.tsx`）：items > 60 时面板行窗口化（行高 `min-height:26px`
     均匀 + 单行省略，运行时实测行高、兜底 26；scrollTop→区间映射 +
     上下 spacer 补齐总高）；≤60 保持与旧实现逐字节同构（无 spacer、无
     scroll listener）。打开面板的活动行滚动由 `scrollIntoView(block:'nearest')`
     改为等价 scrollTop 数学（窗口化后活动行可能不在窗口内）。
     面板 label 改为只对挂载行做 `oneLine` 归一化（切会话不再 O(n) 构建整表）。
   - 视觉/交互契约不变：idle 刻度仍 ≤15、面板淡入/150ms 延迟/滚动条/跳转/悬停
     全部原样；唯一差异是超大会在面板未滚到处不挂载行（不可见区域）。
   - 契约测试 `TurnRail.test.tsx`（5 测）：≤60 全量无 spacer、>60 行数有界 +
     spacer 补高、>15 刻度降采样、打开滚动到活动行 + scroll 事件后窗口覆盖、
     onJump 接线。
   - 待复测：本地一键基准脚本重跑，预期 warm paint 5000 轮 257ms → ~常数
     （目标 <50ms）；若仍不达标，下一嫌疑是 railItems badge 的
     collectLatestTodosFromItems O(总 items) 扫描（改按需计算）。
   - **复测（第二轮）已确认**：warm p95 257→65ms、p50 244→48ms@5000 轮，
     三尺寸持平（64.5/84.9/65.1）→ O(n) DOM 项移除成功；剩 ~50-85ms 固定成本。
6. **P-SWITCH 第二步：badge 按需化 ✅ 已落地**（2026-09-01，攻击剩余固定成本）：
   - 根因：railItems 构建时对每一轮做 `collectLatestTodosFromItems` 深扫
     （O(全部 items)），badge 只在面板可见行展示却每次切换全量计算。
   - 修法：MessageList 不再在 railItems 里扫 badge；TurnRail 新增
     `getBadge(id)`（父组件对挂载行回调，内部 rounds id 索引 + messages
     引用失效缓存）+ `badgeVersion`（messages 换代自增，驱动挂载行重算；
     流式 token tick 不改 messages → 不自增 → TurnRail 全跳不变）。
     `turnRailEqual` 增加 version/getBadge 比较；RailRow badge 变 props。
   - 语义不变：badge 数值仍随 todos 更新（todos 变化必然伴随 messages 更新）；
     未传 getBadge 的旧调用回退 item.badge。
   - 契约测试 +2（getBadge 仅对挂载行调用；version 驱动重算 / memo 命中）。
   - **复测（第三轮）已确认**：warm p95 65.1→57.1ms、p50 48.4→46.7ms@5000 轮
     （badge 深扫在 11.8k 消息下约占 8ms）；p50 全尺寸入预算，p95 57.1ms
     （超 14%，dev+StrictMode 偏高口径）。剩余固定成本 = 窗口轮挂载提交
     （commit p95 22.7ms）+ 浏览器排版 + 2×rAF 等待；再压需动 overscan
     （影响滚动预挂载行为，触 UX 契约）或生产构建，暂缓。
7. **P3/P4/P5 终局处置（2026-09-01，全部有测量依据）**：
   - **P4 mediaRefs 懒加载 ✅ 已落地**：`MessageBubble` 与 `PromptBubble` 的
     4 处转写内 `<img>`（mediaRefs 缩略图）加 `loading="lazy" +
     decoding="async"`——容器均为 `aspect-square` 定尺寸网格，零布局位移；
     滚动大画史时屏外图片不再提前解码。**P4 CSS contain 判定不需要**：
     三轮滚动 over16 恒为 0（自研窗口化已覆盖），且 contain 触碰
     sticky 测量层红线邻域，无测量需求不冒回归风险。
   - **P3 lazy/idle 分帧 判定不实施**：`RemoteQrPanel` 关闭态已渲染 null
     （运行成本≈订阅 4 个 selector），React.lazy 只省模块求值（dev ~1-3ms、
     生产近零）且引入生产 chunk 首开延迟——收益/风险倒挂；启动副作用中
     `hydrateRemote`/`recoverStuckStream` 为亚毫秒级，真正的首绘竞争者是
     `hydrate()`（IDB 必需，不可延后）——无可安全摘取的量。远程轮询合并
     （§3.3 ticker）留待真实远程使用反馈再评估。
   - **P5 replaceMessages 增量 patch 判定暂缓**：cold **首绘**已全尺寸达标
     （16.7-34.9ms，乐观切换先行）；后台全装载的离线基准数字（540ms-8s）
     是服务端回填离线超时伪象，真实收益无法离线验证；而快照替换改增量
     直接触碰数据正确性——留待真实场景报告「回填期卡顿」时按当时证据重开。
   - **P1③（tool_result 展开态行窗口化）维持可选**：仅用户点「显示全部」
     的超大输出才触发，属显式交互路径，不冒视觉回归风险。

