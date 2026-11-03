# 当前状态（2026-11-04 03:1x）

## 已完成

| 项 | 结果 | 证据 |
|---|---|---|
| WSC vs 原生（成本+质量） | WSC 0.992（n=18）vs 原生 0.786（n=4）；中位请求 22 vs 70，输入 60k vs 304k，墙钟 126s vs 907s | `QUALITY-VERDICT.md` |
| 并入主链路 | desktop profile 已换 WSC 后端，k2 参数，真机启动 200 | `MERGE-WSC.md`，commit `ab7d6417`/`e2461ae0` |
| WSM 真实质量 | 789 次读里 489 次重读（62%），工作集只覆盖 16 次（3%）；k 臂重读率 73%、j 臂 65%，工作集没有抑制重读 | `experiments/tools/wsm-quality.mjs` |
| c 臂 WSC 分数 | echo-c-1 0.778（7/9）、echo-c-2 0.889（8/9），9 项任务书 v1 | `report/raw/echo-c-*.score.json` |

## 被阻塞（需要外部输入）

| 项 | 阻塞原因 | 需要什么 |
|---|---|---|
| Compact-Bench 1 instance | 代码不在本地；`web_search` 402 余额不足，`web_fetch` 全部被拦（非公网 IP），本地全盘搜索零命中 | 仓库路径 / 离线包 / 可用的网络出口 |
| CompressAgent 最小复现 | 同上，且没有论文原文，按记忆复现等于编造方法 | 论文 PDF 或代码 |
| BenchPress 对照基线 | 同上 | 同上 |

三项都不是"再试一次"能解决的：网络层是硬失败，本地也没有缓存副本。
