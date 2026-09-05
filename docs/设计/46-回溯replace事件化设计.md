# 46-回溯 replace 事件化设计（v3.2 · append-only surface）

> 状态：已实施（本文件为实施后的冻结口径）。修订 31 号《回溯v3对齐Cursor热路径》与
> 36 号《回溯企业级设计》中与本文冲突的条款；v2 物理重写路径降级为遗留兼容路径。
> DSH 对照依据：`docs/XEYO-三方设计对比-DSH×Codex×XEYO.md` 及 DSH 源码精读
> （`dsh-session/lib/types/surface.d.ts`、`dsh-client-runtime/.../conversation-context.d.ts`）。

## 0. 为什么改

v3.1（31 号）的 continue 回溯 = 「orphan 先落盘 → transcript 原子重写 → 事件落盘」。
审计（2026-09，三路并行）确认该三步协议有一整类结构性缺陷，全部源于**改写唯一真相文件**：

| 缺陷 | 位置 |
| --- | --- |
| undo 半途失败 → transcript 重复 + 永久 409 | `_undo_conversation`→`_undo_files` 无事务 |
| transcript 替换后、事件落盘前崩溃 → 全盲截断 | `mark_crashed_rewinds` 只扫事件文件 |
| 异步 writer 与原子替换竞态 → 被删行复活 | `record_transcript` 后台队列 |
| 幂等重放返回陈旧终态；轮转归档内目标 404 | 事件重放 / 只读当前文件 |
| v2/v3 互相不知道对方的截断 | 双入口语义漂移 |

DSH 的答案：**append-only 日志是唯一真相，回溯只是追加一条 surface replace 事件**，
模型可见历史 = fold（投影），原始行永不改写；"模型看 surface、人看 append-origin"。
本设计将该语义移植到 XEYO，并保留 XEYO 自己的强项（文件检查点回滚、undo、企业级事件状态机）。

## 1. 行格式与 fold 语义

新增 `session/surface.py`。transcript JSONL（含轮转归档 `.old2→.old1→当前`，合并读取）
新增两类 marker 行（无 `id`、无 `role`，`messages_from_rows` 天然跳过）：

```json
{"type": "surface_op", "op": "rewind", "rewind_id": "rw_...", "shadow_from": "<可见行 id>", "ts": ...}
{"type": "surface_op", "op": "rewind_undo", "rewind_id": "rw_...", "ts": ...}
```

`fold_surface_rows(rows)` 规则：

- `rewind`：在**当时可见面**里从末尾反向定位 `shadow_from`，其自身（对齐 v3「target 一并移除」）
  与之后全部可见行被该 marker 影子化；重复同 id marker 幂等。
- `rewind_undo`：恢复该 marker 影子化的行（按原日志顺序 extend；服务端追加前已保证
  marker 之后无新可见行）；重复 undo 只恢复一次。
- `shadow_from` 不在可见面（v2 物理重写掉的极端场景）→ 保守不隐藏任何行。
- 无 id 的普通行原样保留；输出按日志顺序过滤。

**崩溃语义**：marker 是单行 fsync 追加。最坏情况写坏半行 → 读取时跳过 → 回溯视为未发生
（GUI 本地截断由既有 rehydrate/idempotency 重试链路对齐）。三步崩溃窗口不复存在。

## 2. 消费者覆盖矩阵（fold 必须同源）

| 消费者 | 接入点 | 说明 |
| --- | --- | --- |
| 引擎冷启动 hydrate | `session/hydrate.messages_from_transcript` | 合并读取 → fold → Message |
| GUI 消息列表 | `GET /v1/sessions/{sid}/messages`（sessions.py） | raw_rows → fold → `_side_row_to_ui` |
| 引擎热历史 | `SessionPool.resync_after_rewind`（37 号批注） | 从 fold 后磁盘 `replace_history`，契约不变 |
| Todo 冷启动回填 | `tools/todo_write_tool/restore.py` | 改用 `surface_rows_for_session`（合并 fold），被回溯轮的 todo 不复活 |
| 回溯目标定位 | `RewindHotpath.rewind` | 在 fold 可见面中定位 target（顺带修掉「归档内目标 404」P2-7） |
| v2 物理重写 | `rewind/service.py` | `_load_transcript_rows` 改 fold 视图；重写后**回填 active markers**（方向安全：fold 对缺失影子首行保守不隐藏） |
| subagent 侧链 | `subagent_runner.messages_from_transcript` | 侧链永无 marker，fold 恒等 |
| C2 历史指针侧挂 | `prompt/transcript_pointer_shadow.py`（默认关） | 读**原始**文件——人看 append-origin 语义，模型按需 grep 全史（含被影子行），属预期行为，文档化 |
| session 标题提取 | `sessions.py` `_session_meta` | 读原始行（cosmetic，被回溯首行仍可作标题，不改） |

## 3. 热路径与 undo 的变化

**rewind(continue)**：flush 写队列 → 合并读取 → fold → 可见面定位 target → 追加
rewind marker（单行 fsync）→ 事件落盘（新增 `surface_marker: true`，`orphan_count`
保留为「被影子行数」供 pill/GUI 兼容）→ 文件恢复线程（不变）。不再写 orphan、不再重写。

**undo**：事件带 `surface_marker` →
1. flush 写队列，合并读取，若已存在 undo marker（前次文件部分失败）→ 续跑只做文件；
2. 守卫：fold 可见面末行 id 必须等于事件 `after_message_id`（等价旧行数守卫，对轮转健壮）；
3. 追加 undo marker（对话即刻恢复）→ `_undo_files`。
**遗留 orphan 事件**（46 号之前）走原 `_undo_conversation_legacy`，完全兼容。

**幂等重放**（37 号批注沿用）：`failed/undone/recovery_abandoned` 释放键；marker 事件
`transcript_committed` 判定不依赖 `orphan_count`。

**启动对账**：`mark_crashed_rewinds` 除原有 in-flight 提升外，新增
`_reconcile_orphan_surface_markers`——transcript 有 rewind marker 而事件缺失（事件落盘前
崩溃）→ 合成终态 `partial + no_checkpoint` 事件（含按「marker 落地前一刻可见面」计算的
`after_message_id`），使该回溯有 pill/undo 入口且扫描幂等。

## 4. 内存态对齐（37 号契约，不变）

回溯提交后 `SessionPool.resync_after_rewind` 仍从磁盘 hydrate（现在读到的自然是 fold 后
视图）整表替换引擎历史 + 复位压缩侧车 + 清非活跃 turn snapshot；busy 时置 pending 由
`try_begin` 消费。fold 不改变该契约——引擎内存仍是独立副本，只是权威源变成了投影。

## 5. 兼容与迁移

- 旧 transcript 无 marker → fold 恒等，零迁移。
- 旧 rewind 事件（orphan 型）undo 走 legacy 分支；新事件 `surface_marker: true`。
- 旧 orphan 文件与 `blob_gc` 不动（历史审计留存）。
- v2 `/rollback/*`：fold 视图 + marker 回填；其 head revision 与 fold 后 id 不一致时按
  既有冲突语义拦截（`transcript changed before conditional rewrite`）。
- GUI 零改动：`/messages` 已 fold，pill/undo/状态机契约字段未变。

## 6. 测试

- `tests/test_surface_fold.py`：fold 恒等/影子/组合/undo 幂等/保守缺失/非消息行/hydrate
  集成/启动对账幂等/legacy orphan undo。
- `tests/test_rewind_hotpath.py`：continue/undo 契约迁移为「原始行保留 + marker + fold
  可见面」断言；续跑测试改为「undo marker 已落、文件部分失败」重试。
- 回归：rewind 全家 + resync + batch2 守卫 + history/resume/compact/inbox/concurrency/c2
  共 129 项（2026-09-04 全绿）。

## 7. 已知取舍

- 被影子行永久留在磁盘（含其 content blob）：磁盘占用换审计完整性；`blob_gc` 未来可按
  「影子行可达性」扩展清理（需另行设计，不在本期）。
- transcript 体积不再因回溯缩小（反而多 marker 行）；轮转上限（32MB×3）不变。
- 模型可见面与人类可见面自此分离：若产品要求「回溯即从磁盘消失」，那是 v3.1 语义，
  本设计明确放弃（正是多数 bug 的根源）。
