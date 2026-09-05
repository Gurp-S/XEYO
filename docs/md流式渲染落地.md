# md 流式渲染落地

> 状态：已落地（2026-08-30，二轮补充同日）。涉及长文流式渲染的修复、性能增量化与二轮实测反馈修复，全部已实测验证。
>
> 关联代码：`gui/src/lib/rehypeTailFade.ts`、`gui/src/lib/fadeRamp.ts`、`gui/src/lib/incrementalRemend.ts`、`gui/src/lib/incrementalBlockParse.ts`、`gui/src/lib/rehypeSafeHtml.ts`、`gui/src/hooks/useStreamTypewriter.ts`、`gui/src/components/XyStreamdown.tsx`、`gui/src/components/streamingMarkdown.css`、`gui/src/stores/chat/streamSendSlice.ts`、`gui/src/bench/FadeLabRoute.tsx`（实验路由，可删）。

## 〇、二轮实测反馈修复（同日补充）

实机测试发现三类问题，逐项定位后处理：

### 1. 「没有实时渲染 / 满屏源码」——模型把整篇 md 包进了 ```markdown 围栏

复现实测：增量管线在同构文档上与旧管线逐字节一致（remend 269 帧、分块 102 帧），渲染行为未变。模型用 ```markdown 包裹输出时，围栏未闭合期间内容按代码源码显示是**正确行为**；围栏内的内层 ``` 围栏会按 CommonMark 语义把外层围栏提前闭合（同长度 ``` 即闭合），属 markdown 本身语义。

### 2. HTML 元素安全渲染（新增能力）

- 新增 `rehypeSafeHtml.ts`：逐个处理 `{type:'raw'}` 节点（hast-util-raw 解析 → 白名单过滤 → 拼回），markdown 自身生成的元素**不经过白名单**。
- 白名单：纯展示标签（div/span/u/b/i/em/strong/br/hr/details/summary/sub/sup/mark/kbd/p）；属性仅允许 div/span 的 style 与 details 的 open；script/style/iframe 等连子树丢弃；未知标签解包保留内容。
- 两个关键坑（已绕过）：
  - streamdown 通过「用户 rehypePlugins 数组中是否含有 rehype-raw **本体**（恒等判断）」决定是否跳过其自带的 html→转义文本插件，因此过滤插件必须与 rehype-raw 以**数组**形式一起注入；
  - 过滤插件必须按 unified 约定写成 attacher（返回 transformer），直接写 transformer 会在 use 期收到 undefined。
- 已知边界：行内被拆开的 `<script>...</script>`，标签被删净（不会执行），但内部文本可能作为纯文本可见——安全无虞，观感小瑕疵。

### 3. 流式代码块尾行渐隐

代码内容不走逐字渐变（跳过 pre/code 的既有设计），改为对流式代码块的 `code` 元素加纵向 `mask-image` 渐变（最后一行渐隐），落盘后自动消失。计算样式已验证生效。

### 4. 「6.嘿嘿嘿7」中间态与列表翻转跳动（抖动复现的根因之一）

流式揭示切在「数字标号未写完」时，标号被当作正文延续渲染（如 “6.嘿嘿嘿7”），等 “7. 内容” 成形后又翻转为列表项——产生中间态和布局跳动。修复：

- `useStreamTypewriter.ts` 新增 `holdBackPartialListMarker`：揭示前沿停在疑似未写完的标号行时回退到行首，等「标号 + 分隔符 + 内容首字」成形后一次性揭示（利用全文前瞻消歧：独立数字行后随换行会正常放行；行首前缀数字如 “2024年” 不受影响）。
- 直播循环的续跑条件新增 `isOnlyHoldBackLag` 豁免——剩余滞后仅为被扣住的标号尾巴时不再空转续帧（新 delta 会重新调度）。
- drain 排水路径显式 `allowHoldBack=false`：收尾必须追平，否则 shown 永远差标号一口气、drain 停不下来。
- 效果：有序/无序列表项出现时直接以成形列表项落地，无中间态、无翻转跳动。


## 一、解决了什么问题

围绕长 Markdown 流式输出，解决三个问题：

### 1. 末尾渐变动画看不见

设计是"最后 N 字渐变"，实际只能看到最后一个字。根因：旧实现把末尾 16 字包进**单个 span**，用 `background-clip: text` + 90° 横向 `linear-gradient` 上色。流式时该 span 几乎必然跨行（末行通常很短），浏览器把横向渐变按 span 的**包围盒**绘制——渐变的淡端对齐到最后一行行尾，前面几行采样到渐变中段（55% 墨色，肉眼接近实心）。

### 2. 流式时最后几行文字抖动

`background-clip: text` 使 span 成为独立裁剪绘制层。打字机每帧推进 1–6 字时渐变边界在末几行"扫过"，字符每帧在「普通文本 ↔ 裁剪层」两种绘制路径间切换，亚像素反锯齿结果不同 → 末行文字可见抖动。旧代码注释里"单 span 避免逐字抖动"的方案没有解决这个问题，反而牺牲了动画。

### 3. 长回答流式掉帧卡顿（"偶尔出现"）

每个打字机帧的 O(全文) 开销：

| 环节 | 位置 | 成本 |
| --- | --- | --- |
| remend 配对扫描 | Streamdown 内部，每帧 1 次 | ~0.4ms/千字 |
| 全文分块 lex | Streamdown 内部，每帧 1 次 | ~0.4ms/千字 |
| 全文分块 lex | XyStreamdown fadePlans 重复调用 | ~0.4ms/千字 |

20k 字回答每帧解析开销约 28ms，远超 16.7ms 帧预算 → 持续掉帧；另有每帧 O(全文) 字符串分配带来的间歇性 GC 停顿。这解释了"偶尔出现"——只有长文才触发。React 渲染部分本来就增量（Block memo 只重渲染尾块），解析才是瓶颈。

## 二、如何做的

### 修复 1：逐字 opacity 渐变（解决 1 + 2）

- `rehypeTailFade.ts`：末尾 N 码点逐字包 `.xy-char` span 设 opacity，不再用单 span + 渐变背景。opacity 不改字形宽度、不产生裁剪层，跨行时沿阅读方向逐字变淡。
- `fadeRamp.ts`（新）：ramp 从 `LiveFadeText` 抽成共享模块，加 t^1.5 缓入——窗口中段即明显变淡，前半段不再近似实心。
- `streamingMarkdown.css`：删渐变裁剪规则，**保留** `.xy-streamdown-live` 的 `font-kerning: none; font-variant-ligatures: none`——这是逐字 span 边界宽度与整段文本完全一致的前提（span 边界本身不是换行点）。

### 修复 2：增量 remend（B 计划，`incrementalRemend.ts`）

读 remend 源码得出的两个事实是方案基础：

1. 所有 handler 的**修改只落在文本尾部**（收尾未闭合构造）；全文性修改仅有两条转义规则（`字~字`、列表内 `- >25`），且有 `includes` 快速路径。
2. 各 handler 的**判定**依赖全文配对计数（`**`/反引号/`$$` 奇偶），这是 O(n) 的来源。

方案：增量状态机维护一个**安全切分点**——「``` 围栏（行首 `^``` ` 与任意位置 kn 两种语义）、`$$`、未闭合单反引号均闭合的空行」。此时前文所有配对奇偶为偶，**对尾部单独 remend 与全文 remend 数学等价**（尾部自身扫描即得与全文一致的全局奇偶）。两条全局转义规则单独在全文预应用（与内部实现逐字一致）。

接入：`XyStreamdown` 传 `parseIncompleteMarkdown={false}` 关闭 Streamdown 内部全量 remend（已验证该 prop 只控制这一处），改为传入 `createIncrementalRemend({handlers: xyRemendHandlers})` 的输出；fadePlans 同步改用该输出，与 Streamdown 实际解析文本严格对齐。

防护：内容回溯/替换（非前缀追加）自动全量重扫；任何异常 try/catch 回退全量 remend。

### 修复 3：增量分块（路线 A，`incrementalBlockParse.ts`）

流式文本追加式推进，已"封口"的块不再变化（streamdown 的合并规则保证未闭合围栏块持续吸收后续 token，因此已封块永不以未闭合围栏结尾）。缓存除最后一块外的全部块，每帧只对「最后一块起点之后」重新分块再拼回。

两个对齐细节：

- 通过 Streamdown 官方 `parseMarkdownIntoBlocksFn` 注入点传入，**无需 patch 上游**。
- 逐字复刻了源码里的**脚注特判**：文本含 `[^ref]` 时 streamdown 全量解析会把整篇当单块，增量实现同样退回全量并清缓存，避免此类文档分块漂移。
- fadePlans 与 Streamdown 内部解析**共用同一实例**：第一次调用做增量工作，第二次命中缓存，每帧只做一次 O(增量) lex。

## 三、带来了什么收益（实测）

### 渐变与抖动

- 跨行渐变沿阅读方向连续可见（修复前只有最后一字，有截图对比）。
- 同一字符在渐变 span 内 vs 实心状态：宽度完全一致（15.08px）、坐标差 0.03px（测量噪声）——边界扫过零重排。

### 解析开销（浏览器实测，同机同帧序列）

| 场景 | 全量 | 增量 | 一致性 |
| --- | --- | --- | --- |
| remend @10.3k 字（311 帧） | 1.9ms/帧 | 0.1ms（19×） | 逐字节一致 |
| remend @20.9k 字（333 帧） | 3.9ms/帧 | 0.1ms（39×） | 逐字节一致 |
| 分块 lex @20.9k 字（498 帧） | 1.1ms/帧（P95 1.8） | <0.05ms（P95 0.1） | 分块零差异 |
| 分块 lex 原型 @11k 字（642 帧） | 3.7ms/帧（P95 5.6） | 0.1ms（35×） | 零差异 |

每帧三项 O(全文) 开销（remend、双次 lex）全部变为 O(增量) 且 lex 双调用共享缓存。20k 字回答从每帧约 28ms 解析开销降到接近零：**长文流式从"必掉帧"回到 60fps**，GC 尖刺同步消失。

## 四、验证与测试

- `incrementalRemend.test.ts`（11 用例）：流式逐帧与全量 remend 逐字节对比（段落/粗体/行内码/围栏开合/未闭合围栏尾部/半截链接/表格/全局转义/空行结尾），回溯回退、缓存复用。
- `incrementalBlockParse.test.ts`（7 用例）：流式逐帧与全量分块对比（标题/列表/围栏开合/单块持续增长/空行结尾/脚注特判/回溯回退/缓存复用）。
- 浏览器组件级冒烟（`/bench/fade` 实验路由）：标题/粗体/行内码/删除线/链接/列表/代码块渲染正确、无残留源码标记、末尾 16 字渐变正常（代码块内按设计跳过）。
- 全量 vitest 501/501 通过；本次改动文件 typecheck 零错误。

## 五、行为变化与权衡（须知）

1. **有意的行为变化**：`**` 跨过空行仍未闭合时（病态输入），旧全量 remend 会把收尾追加到全文最末——中间整段被渲染成粗体、闭合瞬间又弹回；增量版保持前文原样直到真正闭合。流式观感更稳定，已有测试固定此行为。
2. 脚注文档、内容回溯时自动退回全量路径，成本与旧版相同（不会更差）。
3. 每帧仍保留两次 O(全文) 正则快速路径（`includes('~')`/`includes('>')`，memchr 级速度，21k 字 ≈ 微秒级），仅当正文确实含这些字符时才做全文正则替换。

## 六、可复现与调参

- dev server 下打开 `http://localhost:5173/bench/fade`（`FadeLabRoute`，仅 DEV 构建注册）：
  - `__FADE_LAB__.reveal(n)` / `auto(ms, step)` / `setDoc(text)`：精确驱动流式揭示；
  - `__SD_REMEND_BENCH__` / `__SD_BLOCK_BENCH__` / `__SD_PARSE__`：remend 与分块的增量/全量基准与等价性脚本。
- 不需要时删除 `gui/src/bench/FadeLabRoute.tsx` 及 `App.tsx` 中的 `/bench/fade` 路由即可。
