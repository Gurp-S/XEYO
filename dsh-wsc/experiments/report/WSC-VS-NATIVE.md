# WSC 与 DSH 原生压缩的同任务对比（2026-11-03）

同一 fixture、同一 `PROMPT.md`、同一模型（deepseek-v4.1-flash, reasoningEffort medium）、
同一触发预算（约 24000 tokens），唯一变量是压缩后端。

- native：`ab-native`，DSH 自带 `compaction-basic`，`thresholdRatio 0.366`（65536 × 0.366 ≈ 24k），`retainTokens 3840`
- WSC c：`ab-echo-c`，`capacityTokens 24000`、`retainRatio 0.16`、`payloadPriorEchoDepth 1`
- WSC d：`ab-echo-d`，在 c 之上加 `minReclaimRatio 0.35`（回收不足预算 35% 的压缩不做）

| 指标 | native-1 | echo-d-1 | echo-c-2 |
| --- | --- | --- | --- |
| wall clock | **666 s** | 4713 s | 7547 s |
| LLM requests | **70** | 352 | 511 |
| input tokens | **223,945** | 1,393,047 | 3,126,479 |
| output tokens | **64,381** | 193,243 | 190,980 |
| tool calls | **86** | 616 | 954 |
| compactions | **15** | 130 | 259 |
| 稳定集 score | 7/7 | 7/7 | 7/7 |
| raw score | 9/9 | 9/9 | 8/9（评分策略前写入） |

相对 native 的倍数（d / c）：wall 7.1× / 11.3×，requests 5.0× / 7.3×，
input tokens 6.2× / 14.0×，tool calls 7.2× / 11.1×。

## 结论

1. **质量无差异**：三方在剔除 watch 噪声后的 7 条断言上都是满分，native 的 raw 也是 9/9。
2. **成本差异巨大且方向一致**：WSC 用 5–11 倍的请求、6–14 倍的输入 token、7–11 倍的工具调用
   完成同一任务。压缩次数只是结果，不是原因——native 15 次压缩、WSC 130–259 次。
3. **主因是步数膨胀，不是压缩本身**：WSC 每步约 1.75–1.87 次工具调用，native 1.23 次；
   但总工具调用差 7–11 倍，说明模型在 WSC 下反复做同类工作（重新读取、重新编辑）。
   首要怀疑：检查点把工具结果投影成摘要后，模型失去文件内容，只能重读。
   这是假设，未验证。
4. `minReclaimRatio 0.35` 按设计生效（平均回收 6.5k → 19.3k，跳过 5 次），
   但成本仍高于 c 的期望方向相反：d 比 c 便宜 38%，却仍比 native 贵 7 倍。
   准入闸门治的是"低压空转"，治不了"上下文长得快 + 模型重复劳动"。

## 方法学问题（先于任何结论）

同一 arm 重复运行步数：106（echo-a-2）、274（echo-a-1）、274→511（echo-c-2）、352（echo-d-1）。
组内方差 3.3 倍。n=1 的 arm 对比不足以支持配置级结论；本表只支持"WSC 与 native 差一个数量级"
这一量级的判断。要得到配置级结论，需要每 arm n≥3 取中位数，或换步数方差可控的任务集。

## 复现

```
pwsh -File experiments/tools/trial.ps1 -Profile ab-native -Name native-1
pwsh -File experiments/tools/trial.ps1 -Profile ab-echo-d -Name echo-d-1
node experiments/tools/arm-progress.mjs <ISO start time>
```

## 根因：重复读取同一批文件

`node experiments/tools/tool-mix.mjs native-1 echo-d-1 echo-c-2`（读会话日志统计工具调用）：

| | native-1 | echo-d-1 | echo-c-2 |
| --- | --- | --- | --- |
| 步数 | 70 | 352 | 511 |
| 工具调用总数 | 86 | 616 | 954 |
| `read` 调用 | **34** | 382 | 693 |
| 不同文件数 | 16 | 22 | 19 |
| **每文件平均重读次数** | **2.1** | **17.4** | **36.5** |
| `read_history`（回读被压缩的历史） | 0 | 7 | 20 |

同一批 16–22 个文件，native 读 34 次，WSC 读 382–693 次。步数膨胀的主体就是这批重复读取：
d 比 native 多 348 次 `read`，按 1.75 次调用/步计约等于多出的 282 步中的 200 步。

`read_history` 只在 WSC 出现（7 / 20 次），说明模型知道自己丢了内容，主动回查被压缩掉的历史。

### 结构性原因

native 的 `retainTokens 3840` 保留的是**原样的消息尾部**，最近读过的文件内容仍在上下文里；
WSC 把整个窗口投影成叙述式检查点（`payloadPriorEchoDepth 1`），**没有原样保留的工具结果**。
模型要改文件就必须重读，重读又推高上下文、又触发下一次压缩，形成正反馈。

这与 WSC 的设计取向直接冲突：检查点保留的是"发生过什么"（叙述），而模型继续工作需要的是
"现在是什么"（状态）。修法方向：检查点里给**工作集**留位置——本次会话读/写过的文件路径 +
当前内容（或内容摘要 + 行号锚），而不是把它们压成一句话。

## 结论修订

- 上一节"首要怀疑：检查点把工具结果投影成摘要后模型丢了文件内容"——**已由数据证实**。
- 成本差距（7–11 倍）的主因是重复读取，压缩次数多只是它的结果。
- 待验证的修法（arm e）：检查点增加工作集快照，保留原样尾部；预期 `read` 调用回到 native 量级。
