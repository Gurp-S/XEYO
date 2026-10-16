# WSC 334：发布边界、失败分类与证据引用收敛

实施前复审：[三轮复审计划](wsc-publication-convergence-plan-2026-10-15.md)。本轮直接接入现有生产调用点，没有新增实验开关；自然语言生成器整体的默认开关保持原状。没有改变交接提示词、80%/85% 时机或生成算法。

## 结果

| 项目 | 改前 | 改后 |
|---|---|---|
| 初始 15 项反例与拒绝检查 | 11 failed / 4 passed | 对应缺口修复，扩展定向验收见下 |
| 最终相关回归 | — | 233 passed，23 个测试文件 |
| 真实来源两条路径、各两代重建 | 3/4 链完成；长任务 D 第二折媒体目录范围被拒 | 4/4 链完成，8/8 重启一致 |
| 原生冷 Read | 已发布 7 代中 27 次成功 | 8 代中 31 次成功 |
| 旧对象、折叠间头字节 | 保留 | 保留 |
| API | 0 | 0，费用 0 |

初次沙箱执行受 Windows 硬链接权限限制，不能作为产品反例。`baseline.xml` 是允许真实本地文件操作后的改前结果；`before.xml`、`before-workspace.xml` 保留环境失败，不计入产品通过/失败结论。

## 生产改动

1. `memory/wsc_generation_commit.py` 成为 D 和自然语言生产折叠共用的提交边界：先保留旧代不可变引用，暂存新 WorkingSnapshot，验证来源与 Goal 控制版本、实际头与完整证据，最后提交游标和不可变引用。失败候选的进程缓存被移除。
2. WorkingSnapshot 写入返回原子替换结果。提交后再中断时采用已完成的新代，避免调用者 finally 把旧状态写回。已有不可变头引用优先于可替换头缓存；旧检查点不再回填另一代的摘要。作用域是现有会话互斥下的进程异常/重启，不是物理断电或任意外部写入的证明。
3. 模型生成阶段标记暂时性厂商/传输错误，复用 `common.errors` 分类。仅此阶段可获续接资格；来源、Goal、取消、预算与完整请求容量检查继续生效。无新增 HTTP 重试。401/402/403 等永久拒绝及存储错误没有放宽。
4. 新发布清单 v2 显式接收对象引用。普通投影、fallback、自然语言和媒体目录传递引用；新清单不扫描模型文字。旧格式只在恢复时兼容验证，既有冻结头不迁移、不改写。
5. 媒体覆盖使用已绑定目录的来源集合。旧目录只要来源封印正确、集合覆盖退休媒体，就仍然有效；不能因目录早于当前游标而拒绝。

## 同源重建证据

来源为 307 封存的两份真实会话：`long_noise_task` 1647 条、`completed_waiting_authority` 133 条。每臂使用相同路径、来源与配置；自然语言使用同一固定交接产物，专门隔离发布行为，不增加模型质量样本。每代运行真实生产折叠/发布、实际 FileReadTool、原生重启恢复；第一代追加 20 条确定性观察，再做第二代。

可比较的 7 代中：

- D 的 3 份已发布输出逐字一致，冷对象集合和哈希相同。
- 自然语言的 4 份输出，差异仅为移除 `原始封套文件` / `证据目录原文件` 机器登记行；正文、完整尾部与冷对象集合及哈希相同。原始对象仍在清单中，不依赖展示文字存在。
- 长任务自然语言头每代 1912→1605 字节，另一来源 1672→1341 字节。这是固定产物的字节差异，不是整体压缩率、真实语义收益或账单节省。
- 改前长任务 D 第二折拒绝，改后成功；没有将缺失的改前成绩填成通过，也没有移除失败样本。

证据目录：`_wsc_out/wsc-publication-convergence-334/`。主要文件：`baseline.xml`、`verified.xml`（最终 233 项）、`before-replay.json`、`after-replay.json`、`comparison.json`、`admission.json`、`replay.py`、`before/`。重放调试中发现的未启用媒体和临时转录污染已在同臂同配置的干净目录中纠正，不混入最终对照。

## 文件范围

- 共享提交与状态：`python/memory/wsc_generation_commit.py`（唯一新增生产模块）、`runtime.py`、`working.py`、`wsc_semantic_compaction.py`、`wsc_head_store.py`、`wsc_projection.py`。
- 显式证据：`python/memory/wsc_publication.py`、`wsc_semantic_evidence.py`、`wsc_fallback_handoff.py`、`wsc_fallback_publication.py`、`wsc_media_directory.py`、`wsc_media_fold_commit.py`；`python/synaptic/project.py`、`types.py`。
- 生成失败与控制：`python/memory/wsc_compaction_failure.py`、`wsc_handoff_prepare.py`；`python/engine/query_loop.py`、`manual_compaction.py`。
- 回归：新增 `python/tests/wsc/test_publication_convergence.py`，扩展真实查询边界故障场景；已有丢头测试现在同时破坏不可变引用，避免仅删除兼容缓存就冒充丢失整代；更新共享错误名称和提交后中断期望。

工作区同期出现的 `engine.shared_budget` / 查询循环共享预算修改保持原样，不计入本轮实现与收益；没有提交混合工作区，没有重启线上 XEYO。

## 保持开放

- 本轮证明发布和恢复的机械契约、同产物投影兼容，不证明新生成交接达到 A1，也不证明模型会自主正确触发和使用冷证据。
- 自然语言默认切换、真实模型多代任务质量、按需冷发现、交接回查仍按原 Goal 验收，未提前结案。
- 发布尝试期间既有诊断/费用统计与已提交代的计数区分，留在后续观测/经济性收敛；本轮不拿尝试日志证明提交成功或实际收益。
- 原始历史的分段归档、GC、去噪及缓存经济性不在本轮改动范围内。
