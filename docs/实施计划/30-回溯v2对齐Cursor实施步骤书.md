# 回溯 v2 对齐 Cursor · 实施步骤书

> 合同真源：[`docs/设计/30-回溯v2对齐Cursor口径.md`](../设计/30-回溯v2对齐Cursor口径.md)

## Phase 0 — 口径

- [x] `30-回溯v2对齐Cursor口径.md`
- [x] `29` 文首标注产品面由 30 取代
- [x] `25` 调研附录：Cursor Agent 校正

## Phase 1 — Checkpoint

- turn 绑定 `checkpoint_id` + 预计算 `shadow_paths`
- FE `ChatMessage.checkpointId`
- 轻量 checkpoint / 缓存命中 preview

## Phase 2 — 异步 + 乐观 UI

- execute 快速 accepted；transcript 优先
- FE `restoreCheckpoint` / `continueAndRevert`
- 主路径去掉厚确认窗；接 status/recover

## Phase 3 — Restore 引擎

- scoped safety；禁热路径 `add -A`
- batch blob；WAL fsync 合并
- 信任 plan `shadow_paths`

## Phase 4 — 双入口 UI

- 悬停 Restore Checkpoint
- 编辑 = Continue-and-Revert（自动 send）

## Phase 5 — 测试

- `test_rewind_checkpoint_cursor.py`
- scoped restore 探针（无全仓 add -A）
- FE chatStore / rollbackMachine
