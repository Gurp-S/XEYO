# 下一阶段工作计划（2026-11-04 起）

目标（用户 11-04 交办）：先确认 WSC 成本与质量均超过 DSH 原生压缩，然后依次：

1. **WSM 真实质量** — 工作集（working set）管理的质量评估，需先确认 wsm 指代对象与现有实验臂的对应关系。
2. **Compact-Bench 只跑 1 个 instance** — 先确认单实例预算（token/时间），再决定是否扩展。
3. **CompressAgent 最小复现** — 基于论文做最小手动复现，不做完整实现。
4. **BenchPress 零成本收尾** — 作为对照基线，不投入额外预算。
5. **C：测试 WSC 分数** — 在以上基线下给 WSC 打分。

## 已完成

- WSC vs native 质量验证：native n=4 均分 0.786（最差 1/7），WSC n=18 均分 0.992（最差 6/7）；WSC 中位请求 22 vs 70，输入 60k vs 304k，墙钟 126s vs 907s。结论见 `experiments/QUALITY-VERDICT.md`。
- 数据已入库：commit `f138fa8c`（1376 个文件，含 raw 记录与运行产物）。

## 待办与依赖

- Compact-Bench / CompressAgent / BenchPress 均不在本地，需先取回代码与论文；wsm 的指代需确认（本地无同名目录）。
- 每次实验前先估预算，单次 native 基线约 70 请求 / 300k 输入 / 15 分钟。
- 版本控制：所有产物提交到 `codex/wsc-cooperative-compaction` 分支，实验目录为 `dsh-wsc/experiments`。
