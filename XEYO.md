# XEYO 项目说明

> 本文件按「指针式、保持简短」维护；细则/长流程不内联，需要时用 Read / Skill 现查。

## 来源（本次融合基准，细则见 `docs/设计/cursor博客的技术融合到XEYO.md`）

- [Cursor 博客：奖励作弊正在淹没模型智能的进步](https://prod.cursor.com/cn/blog/reward-hacking-coding-benchmarks)
- [Cursor 博客：Securely indexing large codebases（安全索引大代码库）](https://prod.cursor.com/cn/blog/secure-codebase-indexing)
- [Cursor 博客：Dynamic context discovery（动态上下文发现）](https://prod.cursor.com/cn/blog/dynamic-context-discovery)
- [Cursor 博客：Improving agent with semantic search（通过语义搜索改进智能体）](https://prod.cursor.com/cn/blog/semsearch)

> 备注：这些博客的 ①–⑱ 条「可取之处」已合并为融合方案稿 `docs/设计/cursor博客的技术融合到XEYO.md`，
> 评审/落地以那份文件为准，不在本文件内联。

## 核心判断（先读这一条）

前沿编程 Agent 的榜单分**混淆了「解决缺陷」与「检索已知修复」**。
评审强调：报告必须**先归因再谈分**；SWE 系与 XEYO 自我评测**禁止只报单一 accuracy**。
详见 `docs/设计/cursor博客的技术融合到XEYO.md` §一、§二。

## 常用命令
- 测试：
- 构建：

## 禁区 / 硬约定
- 不动 `python/memory/` 会话内冻结的召回面来「讨好」评测——召回/检索必须在报告中先归因，再谈分。
- SWE 系与 XEYO 自我评测结果**禁止只报单一 accuracy**。
- 索引类改动（⑦–⑪）必须 **fail-open**：索引不可用/异常/超限 → 无条件回退全量 `rg` / 整树语义；绝不假阴、绝不泄密。

## 指针（细则不内联；需要时用 Read / Skill）
- 本次 Cursor 博客融合方案：→ `docs/设计/cursor博客的技术融合到XEYO.md`
- 架构：
- 长流程（发版等）→ `.xeyo/skills/<name>/SKILL.md`，用 Skill 工具按需加载
