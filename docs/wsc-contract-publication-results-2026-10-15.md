# WSC：契约、候选发布与同产物对照（325–327）

本轮按用户确认的五步方向推进。无子代理；未切换生产 provider、未重启 XEYO、未提交混合工作树。自然语言入口仍维持原来的默认关闭状态，不能把机械测试通过当作整体语义准入。

## 三轮复审与正确性边界

1. **契约与职责**：原始字段、大小、ID 合法性仍严格检查；原生解析后，所有后续 Guard 使用同一规范化对象。来源存在、形式合法与语义正确分开。不以补齐强制字段或捕获 KeyError 代替结构修复。
2. **时序与恢复**：候选绑定生成前的 cwd、session、source layout、游标、旧头指纹、Goal ID/revision/status/text；生成后与发布时复核。完整来源先持久化。已知生成失败、控制变化、取消、发布失败分别处理，拒绝候选不推进退休。冻结头与 working 仍是分别持久化，本轮验证两个中断位置，不宣称所有断电场景原子提交。
3. **呈现、证据与实验**：Goal 基线必须对应实际呈现的事实；原始 Message 封套与压缩输入视图分开，使用既有不可变对象、分块编码和 Read。只把入口放热层。固定同一份交接，比较原生与薄头，保留相同尾部、查询和工具能力；A1 用户保留策略另列，不能混称纯投影消融。

## 已接入的实现

- `python/memory/wsc_handoff_contract.py`：规范化合同。`wsc_handoff_validation.py` 在保留原始形状与 ID 检查后统一使用原生解析对象。
- `python/memory/wsc_semantic_binding.py`：候选绑定与机械复核。Goal 事实进入生成输入和新发布头；已完成/放弃目标不重新展开正文。沿用 `wsc_goal_events` 追加后续变化，不重写已发布头。
- `python/memory/wsc_semantic_compaction.py`：生成及发布复核，生成异常也复核控制状态；取消检查贯穿真实调用入口。调用者依旧负责会话互斥。
- `python/memory/wsc_semantic_originals.py` 与 `wsc_semantic_evidence.py`：使用既有 `message_fields` 保留消息 ID、角色、原始内容块及消息元信息，与压缩行按 message_id→id 关联。它是原始 Message 对象的封套，不是带落盘 ts 的转录文件逐字节备份。分块可读视图和未分块恢复对象都绑定进 publication manifest。
- `python/engine/query_loop.py`、`python/engine/manual_compaction.py`：提供实际 cwd、原始消息来源和取消检查；没有增加实验开关。
- 评测适配：`python/evals/wsc_semantic_production_trial.py`、`wsc_glm_real_sources.py` 使用相同候选边界及原始来源；`wsc_same_artifact_native.py` 准备固定产物的对照请求。
- 测试：新增 `test_handoff_normalization.py`、`test_semantic_boundaries.py`；更新 `test_semantic_production.py` 分别核对两类冷对象。

**准入范围**：D 的规范化修复在既有主路生效。自然语言分支的边界、证据修复已接入真实入口，但整个自然语言方法默认仍关闭；没有宣称超过 A1 或满足完整质量底线。

## 前后证据与定向测试

- 可选空字段：修改前 2 failed / 2 passed（decisions 与 constraints 崩溃），修改后 4/4。
- Goal 专项：旧实现 3/3 反例失败——生成期间/发布前只有 Goal 改变未拒绝候选，已记录 Goal 基线却未呈现。新实现全部通过。
- 上轮真实候选 `D_production-g2-generation-provider-4` 与原 33 条来源：旧验证器 `KeyError: constraints`；新验证器通过。没有新生成、没有更改候选、没有放宽引用或退休合同。证据：`_wsc_out/wsc-contract-publication-325/original-candidate-replay.json`。
- 最终定向测试 **156 passed / 0 failed**。覆盖解析/引用/阶段/退休、生产自动与手动入口、容量、生成失败续接、Goal 更新、同长度改史、迟到结果、取消、原始封套实际 Read、重启一致性。
- 持久化中断：头已保存而 working 未保存时，重启保留原游标并完整回放来源；working 已保存但内存尚未采用时，重启恢复新头。两者都保留完整来源。没有据此声称跨文件事务或任意断电恢复已证明。
- Goal 更新后，原发射序列仍是新发射序列前缀，头文件字节不变，重启重建一致。
- 机器报告：`_wsc_out/wsc-contract-publication-325/targeted-tests.xml`。这不是全仓库测试。

## 同产物对照：离线已完成，行为待 API

使用 324 中两份 A1 成功生成的 GLM 交接，分别固定其全部字节；没有重新生成摘要。真实来源各 1647 / 133 行。原生发布、实际 Read、重启一致性各 2/2；六份请求已准备。

以下为 ceil(UTF-8 bytes / 4) 参考估参，不是厂商 tokenizer 或计费量：

| 来源 | 投影 | 头估参 | 全请求估参 |
|---|---|---:|---:|
| 长 | 同交接薄头 | 847 | 9524 |
| 长 | 同交接原生入口 | 1169 | 9847 |
| 长 | A1 用户保留策略 | 847（仅交接本体） | 8292 |
| 短 | 同交接薄头 | 680 | 6028 |
| 短 | 同交接原生入口 | 945 | 6294 |
| 短 | A1 用户保留策略 | 680（仅交接本体） | 1710 |

原生与薄头对照保留相同尾部；A1 的尾部保留策略不同，不能据其更小宣布质量更好。所有 task_success/effective_recovery 均明确为未知，未借旧答案填分。来源、摘要、请求哈希及可读对象清单：`_wsc_out/wsc-same-artifact-native-327/preflight-manifest.json`。

## API 与费用

DeepSeek Flash 单路健康请求 1 次，30 秒读取超时，无 HTTP 重试。未返回 usage，预留 0.016814 元，不当作实际扣费；当前不能据此判断余额。首次本地 tokenizer 缺失在发出请求前失败，改用明确标注的保守字节估参后才发送这 1 次请求。证据：`_wsc_out/wsc-deepseek-health-326/run-report.json`。

没有再次使用上轮临时 GLM 凭据，没有继续发送质量请求。累计预算账本保留未知费用。

## 去噪与缓存结论

当前 `wsc_semantic_generation.generate` 复制已组装消息并追加交接请求，没有额外全历史清洗。`wsc_unfolded_results.preserve` 在当前主策略下保留未折叠工具结果；工具结果尺寸裁剪与 projection 去噪不等于每次交接前重写整段历史。

交接与主调用的 tools 可能不同；工具定义、模型设置、消息序列变化均可能影响缓存。模型可见的前缀字节稳定不等于厂商必定命中。不能把低命中率直接归因于去噪，也不能把删减百分比当成节费百分比。

下一步默认只考虑首次进入上下文的新材料；已发送稳定前缀不反复清洗。若必须在折叠时重构输入，应比较本次生成、后续主调用及冷恢复的总成本，同时保证任务质量。新增原始封套会增加冷存储和发布 IO；热层只增加读取入口，该开销也需要纳入后续性能验收。

## 继续执行的 TODO

- [x] 修复 D 解析与校验对象不一致，原失败候选前后对照。
- [x] Goal 候选绑定、已呈现状态基线、迟到/取消拒绝及两个持久化中断位置验证。
- [x] 原始封套与压缩视图分离并关联，实际 Read 和重启验证。
- [x] 两真实来源固定同交接的投影对照准备及离线入口检查。
- [ ] API 可用后完成同产物行为对照；不覆盖旧失败，不把跨模型结果混排。
- [ ] 多代自身产物链与独立留出，原 18/18 约束、21/21 具体值、36/36 来源及旧事实不复活质量门槛。
- [ ] 同质量前提下评估原始封套 IO、薄投影收益、去噪 useful-loss、缓存与任务总费用。
- [ ] 通过完整质量门槛后再默认启用自然语言交接。Goal 未完成。
