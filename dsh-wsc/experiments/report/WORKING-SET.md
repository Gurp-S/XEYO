# Working set：把"文件状态"带过压缩点

## 问题

同一 fixture、同一 prompt、同一模型、同 24k 预算下，WSC 臂的 `read` 调用是 native 的 11–20 倍：

| | native-1 | echo-d-1 | echo-c-2 |
| --- | --- | --- | --- |
| 步数 | 70 | 352 | 511 |
| 工具调用 | 86 | 616 | 954 |
| `read` | 34 | 382 | 693 |
| 不同文件 | 16 | 22 | 19 |

每文件读取次数：native ≈ 2.1，d ≈ 17.4，c ≈ 36.5。

## 根因

压缩后的 checkpoint 只记录"哪些文件被碰过"（`## Files touched` 一行一个路径），**不记录文件内容**。
模型要继续改代码，只能重新 `read`；重新读入的内容又把上下文填满，触发下一次压缩，形成
"压缩 → 重读 → 再压缩"的自循环。压缩时机（`minReclaimRatio`）只决定这个循环多久跑一次，
不改变"每次压缩后都必须重读"这个事实——这解释了 c→d 只降 38% 而 read 次数几乎不变。

## 机制（`lib/workingset.js`）

从被 shadow 的区域里重建每个文件**最后一次被模型看到的内容**，作为 checkpoint 的一个 section：

```
## Working set (file state the model last saw; stale snapshots are labelled)
- <path> — read #7, unchanged since; 222 lines
  <verbatim body, 头尾截断到 1200 字符>
- <path> — read #6; body stale, edited at #8; last edit wrote: "…"
```

规则：

1. **read**：结果正文入快照（去掉工具自带的 `<path>/<type>/<content>` 外壳）。
2. **write**：新内容成为快照，并清空之前的 edit 记录。
3. **edit**：不猜结果，只把快照标记为 stale 并附上这次 edit 写入的片段——模型由此知道
   手里那份是旧的，而不是拿旧内容继续改。
4. **失败/空结果**：不产生快照。
5. 只保留最近 `maxFiles` 个文件（默认 8），最久未碰的排在最前。

预算：该 section 权重 0.45，并有一个**下限**（`workingsetFloor`）= `min(预算×0.5, 实际需求)`，
理由是整个 checkpoint 里只有这一段是模型不调用工具就能直接行动的状态；上限仍受总预算约束。

## 开关

`payloadWorkingset: true`（默认 false，保持既有行为），另有
`payloadWorkingsetFiles`（默认 8）、`payloadWorkingsetItemCap`（默认 1200 字符）。
`engine.js` 启动时把解析后的策略打进日志（`workingset=on(files=8,cap=1200)`），
用于确认开关真的到达了 builder。

## 验证

- 单元测试 `tests/workingset.test.mjs`：read/write/edit/失败/裁剪 5 条，全部通过；
  全量 102 条通过。
- 真实区域回放 `tools/replay-workingset.mjs`：用 echo-d-1 记录的 shadow 区域重建，
  compaction 1 得到 8 个文件、section 6432 B（checkpoint 8940 B / 预算 12715 B）。

## A/B

E 臂 = D 臂 + `payloadWorkingset: true`，其余完全相同（`minReclaimRatio: 0.35`、
`payloadPriorEchoDepth: 1`、`controlItemCap: 4000`、`selectionMaxTokens: 16384`）。

判据：`read` 次数与总步数应显著下降，且 hidden tests 分数不低于 D 臂。

## 快速 A/B 回路（`experiments/fixture-fast`）

真实 fixture 一次 350 步、~78 分钟，改一行要等一小时。快速回路把任务缩小到 3 个文件：

| 件 | 用途 |
| --- | --- |
| `experiments/fixture-fast/` | `mini-count`：3 个 bug、3 条可见测试、无依赖 |
| `experiments/PROMPT-fast.md` | 对应任务书 |
| `experiments/hidden/fast.test.mjs` | 评分用的 4 条隐藏断言（`MINI_BUILD_ROOT`） |
| `experiments/tools/trial.ps1` | 新增 `-Fixture` / `-HiddenTest` / `-PromptFile`，其余不变 |

跑一臂：

```powershell
pwsh -File experiments/tools/trial.ps1 -Profile ab-fast-e -Name fast-e-2 `
  -Fixture fixture-fast -HiddenTest 'hidden\fast.test.mjs' `
  -PromptFile "$PWD\experiments\PROMPT-fast.md"
```

**容量旋钮**：`ab-fast-d/e` 的 `capacityTokens` 决定压缩密度——8k 时 39 步压 35 次（退化，
预算小到只能装控制段），16k 是可用区间（约每 2–3 步一次，与真实 24k 臂同量级）。

**已知噪声**：`runs/` 在仓库内，fixture 会继承本仓库的 `AGENTS.md`（~2k token）。
下一版把 `runs/` 放到 `%TEMP%` 下即可消除。
## 结果（真实 fixture，24k 预算）

| | native-1 | echo-d-1 | echo-e-1 |
| --- | --- | --- | --- |
| 隐藏测试 | 7/7 | 7/7 | 7/7 |
| 墙钟 | 666 s | 4713 s | **3477 s**（−26%） |
| 步数 | 70 | 352 | 279（−21%） |
| 工具调用 | 86 | 616 | 421（−32%） |
| `read` | 34 | 382 | 288（−25%） |
| write+edit | — | 28 | 9 |
| 压缩次数 | — | 125 | 94 |

结论：working set 把 WSC 相对 D 臂的开销砍掉约四分之一，且没有掉分。
但它没有解决真正的大头——WSC 仍比 native 慢 5 倍。

> **更正（2026-11-03，实测）**：上面把差距归给"选材模型调用"是错的。按 session 事件
> 逐次计时，`echo-c-1`（确定性 payload，没有选材调用）每次压缩 23.4 s，比
> `echo-d-1`（21.3 s）、`echo-e-1`（20.7 s）**更慢**——一次压缩的成本就是一次全上下文
> 模型调用，选材还是总结几乎不影响它。真正的变量是**压缩次数**，见下节。


## 快速回路上暴露的两个结构性缺陷（已修）

1. **各 section 各自按整份预算分额度**，拼起来必然超预算，末尾的 `truncateBytes`
   把 working set 和 verification 整段切掉——恰恰是预算紧、最需要它们的时候。
   改为按价值顺序（control → prior → workingset → selected → judgments → verification）
   在同一份递减预算上依次取用，`truncated` 不再为真。回归测试：
   `selective: a tight budget keeps the working set instead of truncating it away`。
2. **下限取了预算的 50%**：文件正文是唯一随"打开的文件数"增长的 section，占一半预算后
   checkpoint 变大，下一次压缩来得更早——carried state 反而把区域推回阈值之上。
   降到 25%。
## 差距的真正来源：压缩次数 × 单次压缩成本

按 session 的 `compaction/start` → `compaction/summary` 时间戳逐次计时：

| run | 墙钟 | 步数 | read | 压缩次数 | 单次压缩 | 压缩总耗时 | 占墙钟 | 输入 tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| native-1 | 666 s | 70 | 34 | 14 | 15.2 s | 213 s | 32% | 224 K |
| echo-d-1 | 4713 s | 352 | 382 | 125 | 21.3 s | 2669 s | 57% | 1393 K |
| echo-e-1 | 3477 s | 284 | 288 | 95 | 20.7 s | 1969 s | 57% | 1056 K |
| fast-native-1 | 53 s | 14 | 9 | 0 | — | — | — | 18.2 K |
| fast-d-2 | 185 s | 16 | 13 | 8 | 16.8 s | 134 s | 72% | 74.0 K |
| fast-f-2 | 218 s | 15 | 13 | 8 | 20.5 s | 164 s | 75% | 76.6 K |
| fast-g-1 | **47 s** | 14 | 7 | **0** | — | — | — | **16.7 K** |

两件事同时成立：

1. 压缩占总墙钟的 57%（快速回路上 72–75%），而单次压缩在三种 payload 下都是 16–23 s，
   没有哪种 payload 设计能把它压下来。
2. WSC 在 24 K 预算下压缩 95–125 次，native 在 65 K 窗口下压缩 14 次。差的是**触发频率**：
   echo-e-1 平均每 3 步压缩一次，每次压缩后又得重读文件把上下文填回来。

## G 臂：把预算调到 native 实际能用的量级

同一份 payload（working set + 回填），只把 `capacityTokens` 从 16 K 提到 48 K：

| run | 墙钟 | 隐藏测试 | 步数 | read | 压缩 | 输入 tokens |
| --- | --- | --- | --- | --- | --- | --- |
| fast-native-1 | 53 s | 4/4 | 14 | 9 | 0 | 18.2 K |
| fast-g-1（WSC @48 K） | 47 s | 4/4 | 14 | 7 | 0 | 16.7 K |

预算对齐后 WSC 与 native 打平（略快、读得更少），说明**引擎本身没有 5 倍开销**，
5 倍是 16–24 K 预算强制出来的压缩频率。真实 fixture 的 `echo-g-1`（48 K + working set +
回填）正在跑，用来确认这条在长任务上也成立。

## F 臂：checkpoint 预算回填（旁路，默认关闭）

选材是保守的：实测 checkpoint 只用了预算的 1/20（212 B / 14 KB），于是模型反复重跑命令
把输出捞回来。新增 `payloadBackfill`（`lib/checkpoint.js::outputsSectionOf`）：

- 引擎侧确定性填充，取区域内最近 10 条工具输出（每条 ≤ 900 B），标注 `[oN] [tool:名字]`；
- 最后分配，只用更高价值 section 剩下的预算，不会挤掉 control / working set；
- 选材已逐字引用的输出不重复引；< 12 B 的空应答丢弃。

快速回路 A/B（同一 fixture，各 1 次）：

| | fast-d-2 | fast-f-2 |
| --- | --- | --- |
| 墙钟 | 185 s | 218 s |
| 步数 / 调用 / read | 16 / 23 / 13 | 15 / 25 / 13 |
| 压缩 | 8 | 8 |
| checkpoint 里出现回填段 | — | 是（3.5 KB / 325 B） |

**结论：没有可测收益**（差异在噪声内），按准入规矩留在旁路、默认关闭，不进主链路。
它确实让 checkpoint 用满了预算，但在 3 文件 fixture 上省下的重读不足以体现。
