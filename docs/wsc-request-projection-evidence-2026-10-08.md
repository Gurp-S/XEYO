# WSC 请求投影修复与离线证据（批次 21，2026-10-08）

> **批次 22 更新：本文末尾的绑定状态反例已修复。** 先持久化再追加状态事实；完成后折叠吸收、重启、去重通过 11/11。长任务原话保留与失败身份的新证据见 `docs/wsc-continuation-evidence-2026-10-08.md`；真实模型行为仍未验证。

## 修复结论与范围

用户授权修复后通过离线结果继续调整方案。批次 20 对“未修清单全部完成”的表述过宽：绑定 GoalStore 与显式关闭规则，仍没有解决未绑定会话中最早请求永久充当目标的问题。本批删除该旁路下的回退，不要求用户声明“已经修好”。

新增 `XEYO_WSC_REQUEST_PROJECTION`，默认关闭。开启时包含 `XEYO_WSC_STATE_CONTRACTS` 的不可变冷层与发布契约；不自动启用执行权限旁路，不改 GoalStore，不改生产环境开关。此前两批的默认行为和开关兼容保留。

## 事故三问

1. 根因：从最早未关闭用户原话派生常驻目标，把历史请求与当前工作状态混在一起。仅添加关闭关键词无法处理用户未声明已修好。
2. 结构规则：最近人类请求是请求事实；只有已绑定的 GoalStore 提供长期目标状态。旧请求移入历史索引与完整冷层，不被推断为 completed、abandoned 或 paused。历史硬约束沿用既有确定性提取/覆盖规则，独立保留已提取项。新请求在尾部时利用尾部原文；进入折叠区域后才进入新头。不逐轮改写已发出的冻结头。
3. 回归：无关闭声明、短追问、绑定目标五态、尾部去重、折叠后持续发射、旧对象不变、机器注入/工具结果排除、重复身份与冲突、三种预算渲染器不能重新带入旧请求摘录、默认关闭兼容。

## 方案调整及取舍

- 不采用“最新消息自动关闭上一目标”。总结、追问和继续都能是当前请求，但不构成目标已完成的证据。
- 原会话中旧过滤规则只识别 20 条实质人类消息；新投影识别 29 条，补回短追问。它们也有精确回读入口。
- 复验中增加身份保护：相同消息 ID 的相同正文只计一次；不同正文复用同 ID 则投影失败，交由既有中性失败/旧头复用机制处理。无 ID 时不靠内容去重不同的合法请求。
- 绑定目标显示状态事实（active/paused/blocked），避免暂停目标冒充当前执行目标。completed/abandoned 不再发目标正文。
- 冻结重放发现“最近人类请求”的标签会在新请求进入尾部后变成陈旧断言。因此改为“折叠区末人类请求”，明确快照范围，维持事实真实与冻结字节。当前尾部原文照常存在。
- 旧用户正文在 REQUESTS 中只呈现召回入口，三种预算退化路径遵守同一规则。当前请求与有效约束保留直接显示；完整历史保持可回读。
- **完整可恢复不等于全部直接可见。** 短追问在无绑定长期目标时可能需要回读上一请求。这是可复现的取舍，没有宣称通用意图识别或任意历史事实的可见性已解决；本批也没有实现任意自然语言事实槽及其真值判定。
- 引擎没有添加“只执行 active_goal”“不要再执行旧任务”之类导演文本，没有调用 LLM 做压缩。

## 测试数字（按代码阶段记录）

新增请求投影回归 **18 passed**。结构修复相关套件 **825 passed，28.85 秒**；最终快照标签修正后相关复验 **48 passed，2.39 秒**：825 覆盖 WSC、环境登记、执行事实契约、changedetect only 与 lifecycle；48 覆盖请求投影、状态契约与环境登记。825/48 均包含新增回归，不能累加。变更检测 **5/5**，L0/L1 快照无变化。未重跑全仓 Python/GUI/TUI；本批无界面改动，不引用批次 20 全仓结果作为本批验证。

## 真实会话与无关闭声明对照

原始会话：`C:/Users/48522/.xeyo/sessions/sess_mux0q86a_ea2kv9.jsonl`，1879 条，SHA-256 `a63576fe9c8171d350f6efd10598b12045e26c4175ace6dfb2c03615fd2bb910`。

无关闭声明反事实：仅删除零基 #1844 消息（用户自行修好 ChatGPT 的声明），其余消息内容、元数据及顺序不变，共 1878 条。变体 SHA-256 `6e79ca298989e1da2e4aa797b6ebe667044c46e85894630ed9dcf4f84517d0a6`。只写隔离副本，不修改原会话。

两臂都开启已有状态/执行事实契约，都关闭 G1 关键词退休；唯一行为差异是新请求投影开关。原会话切点 67/200/1844/1845/1879；无关闭声明切点 67/200/1844/1845/1878。这里比较的是批次 20 与批次 21，不能与批次 20 的 12295→8414 混成同一基线。Token 数包含离线冷层路径，跨目录数值不可直接比较。

| 指标 | 原会话 | 移除关闭声明 |
| --- | --- | --- |
| 未绑定历史请求被发为目标 | 5/5 → 0/5 | 5/5 → 0/5 |
| 末切点热层 token | 8534 → 7923（-7.2%） | 8115 → 7701（-5.1%） |
| 首切点热层 token | 4454 → 4466（+12） | 4485 → 4498（+13） |
| 累计冷文本完整一致/可展开 | 11653/11653 | 11651/11651 |
| 实际 FileReadTool 成功回执 | 81/81 | 81/81 |
| 非目标常驻 PIN 事实缺失 | 0 | 0 |
| 验收 | 8/8 | 8/8 |

累计冷文本为各臂各切点之和，含重复节点；实际 Read 每次最多 10 行，全文一致另由完整冷文本与文件区间核对。原会话的 5 个既有文件哈希前后一致；变体文件也一致。最终未解决历史错误事实仍保留，不伪造成功证据。

生产发射适配器使用真实消息、隔离 XEYO_HOME 和操作员指定折叠边界：区域 66 → 用户 #66 在尾部 → 折叠区域 67 → 下一轮 → 清空进程态重启。两组均验证：尾部阶段头相同；折叠换头一次；之后头相同；重启后的整个发射列表一致。完整阶段 JSON 在各报告的 `freeze-replay/`。此证据检验字节稳定与请求撤出，不是厂商缓存命中率、实际自动折叠时机或模型行为测试。

离线重建证明“旧人类请求永久当目标”这个结构性根因已消除。不能据此声称模型以后绝不回读旧请求、绝不白跑，或无需证据就知道某任务已在外部修好。绑定目标的完成仍由目标状态库记录，普通工具成功也不自动证明整个任务完成。历史缺少闭合证据的 53 条错误继续按原规则保留。

## 本批改动文件

- 新逻辑：`python/synaptic/request_plane.py`。
- 小量接线：`python/synaptic/contracts.py`、`lifecycle.py`、`seeds.py`、`assemble.py`、`budget.py`、`project.py`、`metrics.py`。
- 开关登记：`python/engine/env_switches.py`。
- 离线工具：`python/evals/wsc_request_projection.py`。
- 回归：`python/tests/wsc/test_request_projection.py`。
- 记账：本文、`docs/wsc-loop-notes-2026-10-07.md`、`docs/wsc-open-issues.md`、`docs/XEYO-切换对话交接提示词-2026-10-08.md`、`docs/stale-goal-retire-plan-2026-10-08.md`、`docs/wsc-root-contracts-evidence-2026-10-08.md`。

其余工作区既有在途改动不归入本批；未提交、未迁移旧线上头。

## 产物与复现

- `_wsc_out/request-projection-2026-10-08/original-final/report.json`、`head.diff`、各切点 `head.txt`、`freeze-replay/`。
- `_wsc_out/request-projection-2026-10-08/no-closure-final/report.json` 及同名阶段产物；变体原文在 `no-closure/source.jsonl`。
- `_wsc_out/request-projection-2026-10-08/changedetect.json`。

在 python 目录执行：

```powershell
py -3.11 -m pytest tests/wsc tests/test_env_switches.py tests/test_execution_fact_contracts.py tests/test_changedetect_only.py tests/test_lifecycle.py -q
py -3.11 -m evals.changedetect check --json
py -3.11 -m evals.wsc_request_projection C:\Users\48522\.xeyo\sessions\sess_mux0q86a_ea2kv9.jsonl --output ..\_wsc_out\request-projection-2026-10-08\original-final
py -3.11 -m evals.wsc_request_projection ..\_wsc_out\request-projection-2026-10-08\no-closure\source.jsonl --output ..\_wsc_out\request-projection-2026-10-08\no-closure-final --cuts 67,200,1844,1845,1878
```


## 批次 21 复查：绑定目标状态在冻结期间滞后（未修，2026-10-08）

用户要求再次思考是否真的修好。新增真实生产适配器反例：隔离 GoalStore 将绑定目标 active→paused，消息从原会话前 67 条追加至 68 条，但不移动折叠边界。目标库已为 paused，WSC 仍逐字复用旧头并显示“绑定目标（active）”；移动边界实际折叠后才显示 paused。报告 `_wsc_out/request-projection-2026-10-08/review-bound-state/report.json` 和三阶段 JSON。无模型调用，不改原会话/原线上产物。

结构原因：`memory/wsc_projection.py` 的冻结复用分支先返回，`wsc_goal_source.snapshot` 只在后面的重建分支读取。既有五种静态状态回归与原会话离线验收没有覆盖“同一冻结头期间绑定状态动态变化”。因此不能把新旁路描述成全部生命周期问题治本。

修复方向：冻结头中的绑定状态应明确是带 revision 的快照；绑定目标状态变化通过追加的、版本化的中性状态事实进入尾部。完整重建时吸收这些事实。不能为状态更新逐轮改写冻结头，也不能把“不再显示旧请求”当作旧任务已经完成的证据。需要回归 active→paused/completed、同状态去重、状态变化后的重启恢复与前缀字节一致。当前只是复查与记账，尚未实施这条新修复。

另有未完成验证：无绑定长期目标时，“继续/照刚才方案做”依赖历史召回；完整冷层可读没有证明模型会正确召回和继续。真实模型的白跑率仍未测；生产旁路仍关闭。未绑定旧请求永久当目标这一特定根因已移除，不能扩大为整个 WSC 已治本。
