# WSC × DSH 协作式压缩：A/B 实验报告

日期：2026-11-02
实验对象：`@xeyo/dsh-wsc`（WSC 压缩后端） vs `@deepseek-ai/dsh-compaction-basic`（原生压缩）
宿主：DSH headless（`dsh --profile`），模型 `deepseek-v4.1-flash`，窗口 65536，maxTokens 32768

## 1. 结论

1. **WSC 在此 harness 构建上原本完全不可用**：`#consider` 每步抛 `session.eventAt is not a function`，被 `agent/pre-step` 的 try/catch 吞成一条 warn，从未真正压缩过。桌面 profile 的 `@xeyo/dsh-wsc` 是指向源码的链接，所以桌面端同样一直是「静默失效」。修复后 WSC 在 headless 下可正常压缩（`compaction/start → summary → end` 完整闭环，账本与证据落盘）。
2. 修复后按同触发线对比（容量 20000 tokens、保留 3200 tokens）：**WSC 的 checkpoint 体积约为原生的 40%**（平均 1428 vs 3523 字符），请求数 27 vs 44、输出 token 13.5K vs 19.3K，步数 13 vs 19；但**墙钟时间更慢**（172s vs 120s），因为每次 checkpoint 要额外发一次选择性抽取请求。
3. 单样本、无重复，不能据此断言「显著更优」；能确定的是**机制可用、体积显著更小、质量在本任务上无退化**（两臂计数与结论均正确）。

## 2. 修复的结构性根因

| 症状 | 根因 | 修复 |
| --- | --- | --- |
| `session.eventAt is not a function` | 插件按旧版 Session API 写，当前构建只有 `eventsSnapshot` / `events` | 新增 `lib/session.js::eventAt()`，两种形态都读；6 处调用点统一替换 |
| `agent.session.toolHistory is not a function` | 该字段不是 `llm.stream` 的合法选项，是从 XENYON Python 版误移植 | 从请求 options 移除 |
| `agent.session.snapshotEvents is not a function` | 同上，当前构建为 `session.events`（冻结快照） | 2 处替换为 `session.events` |

这三处不是配置问题，是**对宿主 API 的错误假设**；它们同时解释了「为什么 WSC 装了却从不压缩」。修复未改变任何策略逻辑，只对齐 API。

## 3. 方法

- 两 profile 除压缩后端外逐字相同：同 provider/model/reasoningEffort、同窗口与 maxTokens。
- 触发线与保留量对齐：B 组 `capacityTokens 20000`、`retainRatio 0.16`；A 组 `thresholdRatio 20000/65536 ≈ 0.305`、`retainRatio 3200/65536 ≈ 0.049`。
- 同一提示词（4 步：整读 65KB 文件 → grep 两次计数 → 写 summary.md → 回读核对），同一工作目录形态。
- 指标取自 session 日志（`session.jsonl.zstd` 解帧）与 B 组探针日志，账本取 `~/.dsh/wsc`。

## 4. 数据

### 4.1 现实容量（20000 / 3200）——主实验

| 指标 | A 原生 | B WSC |
| --- | --- | --- |
| 步数 | 19 | 13 |
| LLM 请求数 | 44 | 27 |
| 输入 token 累计 | 195,432 | 184,070 |
| 输出 token 累计 | 19,346 | 13,536 |
| compaction/start | 8 | 6 |
| summary 次数 | 6 | 6 |
| prune 次数 | 6 | 0 |
| checkpoint 平均字符 | 3,523（3404–3617） | 1,428（934–1665） |
| 墙钟 | 120s | 172s |
| 任务正确性 | 1500/1500，summary 写入并回读 | 1500/1500，summary 写入并回读 |

B 组每次压缩的影子规模 4.5K–18.3K tokens，checkpoint 0.9–1.6KB，压缩比约 10:1。

### 4.2 压力容量（2048 / 327）——边界实验

| 指标 | A 原生 | B WSC |
| --- | --- | --- |
| 步数 | 11 | 16 |
| compaction/start | 20 | 15 |
| summary | 16 | 15 |
| prune | 7 | 0 |
| 墙钟 | 166s | 345s |
| 任务正确性 | 正确 | 正确 |

2048 tokens 的预算低于单次工具结果体积，两臂都退化为「每步压缩」，只证明机制在极端压力下不崩，不作为质量结论。

## 5. 观察到的风险

1. **桌面端历史数据不可信**：修复前桌面会话里没有任何 WSC 压缩产物（只有 warn）。若要评估真实收益，需要修复后重新采样，旧会话不能当基线。
2. **`compact_context` 工具在 headless 花名册中的可见性未验证**：本实验中 B 组的 6 次压缩全部由容量触发，没有一次来自模型主动请求。工具注册代码在 `agent/created` 上执行，但 headless 的工具清单是否包含它尚未确认。
3. **延迟代价**：WSC 每次 checkpoint 多一次 LLM 调用，墙钟约 +43%；在交互式桌面场景需实测体感。
4. **单样本**：每臂 1 次运行，无重复、无置信区间；结论应表述为「机制可用 + 体积更小」，而非「质量更优」。
5. **A 组出现 `approval/asked`**：B 组运行中沙箱拒绝写 `.smoke-b` 后按规程重试，属环境产物，不是引擎行为差异。

## 6. 建议下一步

1. 重启桌面会话使源码修复生效，再跑同一提示词，确认桌面端出现 `compaction/*` 事件。
2. 用 5 次重复 × 2 臂替换单样本，统计 checkpoint 体积、请求数、墙钟的中位数与离散度。
3. 确认 `compact_context` 是否进入模型工具清单；若未进入，模型主动压缩这条路径等于未启用。
4. 把「宿主 API 兼容层」纳入 `tests/`：对 `eventAt`/`events` 两种形态各写一条断言，避免下次宿主升级再静默失效。
