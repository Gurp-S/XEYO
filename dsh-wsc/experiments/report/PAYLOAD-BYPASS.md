# 检查点 payload 旁路：实现、离线 A/B、实跑 A/B

日期：2026-11-02 · 旁路形态（默认值 = 现状，主链路行为不变）

## 一、旁路形态

新模块 `lib/payload.js` 把检查点"装多少、收多长、各段占多少"从硬编码抽成配置项。
**所有默认值等于改造前的常量**，不配置的 profile 输出逐字节不变（有单测断言）。

| 配置项 | 默认（= 改造前） | 作用 |
| --- | --- | --- |
| `payloadFraction` | 0.35 | 检查点预算占被压缩区域的比例 |
| `payloadMaxChars` | 24000 | 预算绝对上限 |
| `payloadQuoteMaxChars` | 1200 | 模型引用被接受的最长字符数（超了整条丢弃） |
| `payloadSelectedItemCap` | 1200 | 引用段单项渲染上限 |
| `payloadFactMaxChars` | 320 | 判断被接受的最长字符数 |
| `payloadJudgmentItemCap` | 320 | 判断段单项渲染上限 |
| `payloadVerificationItemCap` | 220 | 验证段单项渲染上限 |
| `payloadPriorItemCap` | 1200 | 上一份检查点段单项上限 |
| `payloadPriorEchoDepth` | 0 | 上一份检查点嵌套回声保留层数；`1` = 只留最外层 |
| `payloadOutputsItemCap` | 240 | **工具结果**单项字符上限（仅 deterministic 构建器） |
| `payloadOutputsItems` | 6 | **工具结果**携带条数（仅 deterministic 构建器） |
| `payloadOutputsWeight` | 0.2 | **工具结果**段预算权重（仅 deterministic 构建器） |

`priorEchoDepth` 顺带修一个结构缺陷：渲染器把上一份检查点逐行变成 bullet，于是它的
`## Prior checkpoint` 变成 `- ## Prior checkpoint`，再下一层 `  - ## Prior checkpoint`。
**回声逐层增长、段落配额不变**，1200 字节配额被回声吃干净。

## 二、离线 A/B：方法与被证伪的一次测量

`experiments/tools/replay-payload-ab.mjs`：从会话记录重建每次压缩看到的区域
（`compaction/summary.shadowedSeqs`），同一区域分别用现状策略与旁路策略构建，比较
`bytes`、`recall`（区域内去重后 ≥30 字符的行有多少**逐字**留下）。

第一版脚本报出"现状 749 字节 / recall 0.008，基线 3022 字节 / 0.195，差 24 倍"。
**这个数字是记录器的产物，不是构建器的。** 根因：会话里的 `tool/result` 是 harness 事件，
`message` 没有 `role` 字段，工具正文在 `content[0].content[].text` 里；旧脚本把原始 payload
直接塞给构建器，于是**所有工具结果都被静默丢弃**。

已修：`experiments/tools/region.mjs` 做唯一一处归一化（角色、内容展平、`toolCallId`），
两个回放脚本共用。修正后同一批样本：现状 749 字节 / recall 0.005，旁路 749 / 0.005，
落盘基线 3022 / 0.075，**160 次压缩、两套策略输出逐字节相同**。

另外查到：`shadowedSeqs` 里**没有工具结果**（抽检区域角色统计 `{user:15, assistant:4}`、
`{user:7, assistant:2}`、`{user:1}`），所以离线回放**结构上无法**验证工具输出这条旁路。

## 三、实跑 A/B（2026-11-02 21:24–22:16）

- profile：`ab-pay-a` / `ab-pay-b`，同一份源码快照（复制进各自 `node_modules/@xeyo/dsh-wsc`，非 link），
  唯一差异是 `ab-pay-b` 的 `wsc-config` 多三行：`payloadOutputsItemCap 1200` /
  `payloadOutputsItems 24` / `payloadOutputsWeight 0.5`。
- 任务与评分：`fixture` + `PROMPT.md` + `score.mjs`，与既有矩阵逐字相同。
- 驱动：`tools/trial.ps1`（`dsh --profile … "prompt"`，headless，串行）。

| 指标 | A 默认 | B 放宽工具输出 |
| --- | --- | --- |
| 隐藏测试 | 8/9 | 8/9 |
| 失败项 | `--watch rebuilds after a source change` | 同左 |
| 步数 / 请求数 | 73 | 153 |
| 输入 / 输出 token | 221512 / 54309 | 627429 / 96994 |
| 压缩次数 | 19 | 55 |
| 检查点字符数（中位） | 3025 | 3608 |
| 触到预算上限的检查点 | 0 / 16 | 0 / 42 |
| 工具调用 / 其中重复 | 118 / 34 | 243 / 100 |
| 墙钟 | 739 s | 1933 s |

结论：

1. **旁路没有生效，但不是配置没接上。** 72 条账本记录的 `payload.sections` 只有
   `control / selected / judgments / prior / verification`，**没有 `outputs`**，`priorDepth` 全 0。
   压缩走的是 selective 构建器，而工具输出段只存在于 deterministic 构建器。
2. **A/B 的差异是运行间方差，不是旋钮效果。** 两臂配置在有效代码路径上完全相同，
   差异却达到 2.1× 请求数、2.8× 输入 token、2.6× 墙钟 —— 同任务同模型 n=1 的方差就有这么大。
   所以本轮**不能**用来判定旁路收益（它测的是噪声），但也足以否掉"这些旋钮当前有任何作用"。
3. **预算从来不是约束。** 检查点中位 3.0–3.6 KB，预算 8.6–24 KB，**72 次压缩 0 次触到上限**。
   真正的上限是选择模型愿意引用多少内容，不是渲染器能装多少。
4. 两臂都 8/9、失败项相同，与 pilot 和 b-fix 系列一致 → 该失败是 fixture/模型问题，不是本次回归。

## 四、这次 A/B 暴露的设计问题

`payloadOutputs*` 接在 deterministic 构建器上，而生产路径（`selection: selective`）不用它 —— **旋钮是死的**。
这是我上一轮方案的结构性错误：把"工具输出引用"做在了渲染器层，而工具结果能否进入检查点由**选材层**决定。

两条出路（需要决策，不能两件都做）：

1. **让工具结果成为可选材条目**：selective 路径把工具结果按编号放进选择请求，模型能引用它们。
   改动在 `lib/selection.js` 的提示词与解析，不动渲染器；顺带让 `quoteMaxChars` 对工具引用生效。
2. **在 selective 路径保留一个 outputs 兜底段**：构建器侧改动，但会和模型的选材抢预算，
   等于把"模型自决"换回"引擎决定装什么"，与设计理念冲突。

无论走哪条，验证都需要 **n ≥ 3 的两臂矩阵**：本轮 2.6× 的运行间方差说明单跑一次得不出任何结论。

## 五、复现

```powershell
cd 'D:\lea\XenYon code\dsh-wsc\experiments'
pwsh -File tools\trial.ps1 -Profile ab-pay-a -Name pay-a-1
pwsh -File tools\trial.ps1 -Profile ab-pay-b -Name pay-b-1
node tools/pay-ab.mjs pay-a-1 pay-b-1
```

profile 由 `ab-b` 复制而来，`node_modules/@xeyo/dsh-wsc` 内是本仓当前源码快照
（`index.js` `engine.js` `client.js` `lib/*.js` `cordis.patch.yml`），实验期间不回链源码。

```powershell
cd 'D:\lea\XenYon code\dsh-wsc'; npm test   # 87 项，含 tests/payload.test.mjs
```

## 六、方案 A 的前置核查：工具输出其实已经在选材面上（2026-11-02 22:53）

按方案 A 动手前先查代码与实跑记录，结论推翻了我上一轮的判断：

1. **工具结果早就是可选材条目。** `lib/selection.js::numberedTranscript` 把 `role: 'tool'`
   投影成 `[m<n> tool-result]` 编号条目（无长度上限），`checkpoint.js` 也早已按 `role: 'tool'`
   渲染。所以"让工具结果成为可选材条目"这件事**已经是现状**，再加一层是重复实现。
2. **离线回放是无效测量，不只是测不到旁路。** `shadowedSeqs` 不含工具事件：抽检区域只有
   `{user, assistant}`；而实跑预算反推的 `sourceBytes ≈ 34 KB` 远大于这 6 条消息的体量，
   说明**真实区域里有大量工具输出，只是 `shadowedSeqs` 没记**。回放脚本据此重建的区域
   缺了主要部分 → 第二节的所有 recall 数字（含"逐字节相同"）都不能用来判断收益。
3. **实跑暴露的真问题在别处：上一份检查点的回声逐层嵌套。** 同一次 `pay-a-1` 的 18 份检查点里，
   含 `## Prior checkpoint` 的行数从 10 增到 17（每次压缩 +1），占用字符 690 → 1263：

   | 检查点 | 总字符 | 回声行 | 回声字符 | 占比 |
   | --- | --- | --- | --- | --- |
   | #11 | 2173 | 10 | 690 | 32% |
   | #15 | 1974 | 14 | 1022 | 52% |
   | #18 | 2397 | 17 | 1263 | **53%** |

   到后段，**一半以上的检查点预算花在"历史检查点回声"的缩进噪音上**，真正的用户请求、
   判断、验证项被挤到剩下的 47%。这不是工具输出的问题，是渲染器把回声逐行变成 bullet 的结构缺陷
   ——`payloadPriorEchoDepth`（默认 0 = 现状）正是修它。

## 七、下一步：先测回声折叠，而不是工具输出

建议的下一组两臂（各 n=3）：

- **A 臂**：默认配置。
- **C 臂**：`payloadPriorEchoDepth: 1`（只保留上一份检查点最外层，去掉嵌套回声）。

判据：检查点回声占比（应降到 <5%）、`selected` 段字符数（应上升）、请求数、墙钟、隐藏测试。
工具输出那条线等这一轮结论出来再定，因为选择模型现在只有一半预算可用，此时测"它愿不愿意引用
工具输出"是被污染的实验。

已加观测项（无行为变化）：`selection.transcriptChars / transcriptMessages / transcriptEmpty /
transcriptTools / transcriptToolChars` —— 下一轮就能直接看到区域里有多少工具输出、有多少
消息因为空文本被静默丢弃（`transcriptEmpty` 若不为 0，就是第 2 条问题的量化证据）。
