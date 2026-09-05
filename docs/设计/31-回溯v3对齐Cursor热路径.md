# 会话回溯（Rewind）v3 · Cursor 级热路径

> 状态：**现行产品合同**（2026-08-30）  
> 取代 [`30-回溯v2对齐Cursor口径.md`](./30-回溯v2对齐Cursor口径.md) 的**产品面与数据模型**。30 号仅作实现考古；v2 的 preview/execute API 保留为测试/降级路径。实施细节与评审修订记录见 [`docs/实施计划/32-回溯v3热路径Rewind实施计划.md`](../实施计划/32-回溯v3热路径Rewind实施计划.md)。

## 目标

Cursor 级体感：点击同帧投影、transcript 快速提交、工作区后台追平；**AgentFileIndex + blob 替代全仓 shadow-git 热路径与必经 preview**。

## 双入口与切点 pill

| 动作 | 对话 | 文件 | 之后 |
| --- | --- | --- | --- |
| **Restore Checkpoint** | 不动（保留全部消息） | 恢复 agent 触及路径至 checkpoint | 不 send；弹窗提示文件已回滚 |
| **Continue（从此重试）** | 截断整个 target 轮（含 target 消息，进 orphan） | 恢复至 checkpoint（该轮发出前状态） | restore 完成后自动 send（复用发送链路，产生新 checkpoint） |

- 入口：Continue = 「编辑历史消息 → 弹窗」；Restore 主入口 = **切点 pill**（回溯发生后渲染的哑组件，按钮只打开锚定该切点的弹窗）；任意消息仍可走编辑入口。
- 无 checkpoint：Restore 禁用；Continue 仅截断对话并警示。
- 所有回溯 UX（确认、进度、脏跳过、recovery、Undo）都在弹窗内完成；除切点 pill 外不得新增列表内可见控件。

## 数据模型

- **Checkpoint = 该条 user 消息发出时、agent 作用域文件的 blob 图**（COW），`checkpoint_id` 绑定 user 消息并随 `/messages` hydrate。
- 记录：Edit/Write/Notebook 走 `record_file_mutation`（before/after blob）；Bash / 未走 file tool 走 **turn 起止双向 lstat 差量**（变化路径读盘，before/after 入 blobs）。热路径零 `git add -A`、零整树内容读取、零必经 preview。
- 恢复：只写 checkpoint 中的路径；agent 在 checkpoint 之后新建的路径删除；用户手改路径**跳过**（弹窗提示）；restore 完成后**回写 AgentFileIndex**。

## 落盘布局

`~/.xeyo/sessions/{sid}/`：

- `transcript.jsonl` — 仅当前主链前缀
- `orphans/{rewind_id}.jsonl` — 被删整轮后缀（不可变）
- `checkpoints.jsonl` — checkpoint 文件图（需 compaction，待决）
- `agent_file_index.jsonl` — AgentFileIndex upsert 账本
- `rewind_events.jsonl` — 审计 + Undo（`orphan_id`、`pre_rewind_index`、pill 展示摘要）

Blob：`~/.xeyo/snapshots/{sha256}`（复用 v2 SnapshotStore）。

**崩溃顺序：** orphan → fsync → 原子替换 transcript → 再改工作区。Hydrate 只读 transcript。

## API（跳过 preview）

`POST /v1/sessions/{session_id}/rewind`（`mode: restore|continue`，`confirmed` 必填，`continue` 必填 `edited_text`；幂等 `idempotency_key`）；`POST .../rewind/{rewind_id}/undo`；`GET .../rewind/{rewind_id}`。transcript 提交后立即返回；**忙时不 interrupt，直接 409**。

## 性能门槛

- 确认 → 列表截断 <100ms（主线程）；transcript commit 典型 <100ms；≤20 文件后台 restore <500ms；Continue 端到端 <600ms；发送冻结 COW 典型 <50ms。

## 明确不做

完整编辑器 VFS；侧聊对等 rewind UI；默认整树 restore；用户 `.git` 写入；主视图聊天 DAG；气泡悬停 Restore；列表外 toast/横幅。
