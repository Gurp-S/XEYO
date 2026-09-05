# 会话回溯（Rewind）v2 · 对齐 Cursor Agent

> 状态：**考古（已被 v3 取代）**（2026-08-30）——产品面与数据模型以 [`31-回溯v3对齐Cursor热路径.md`](./31-回溯v3对齐Cursor热路径.md) 为准；本文仅作 v2 preview/execute 降级路径的实现参考。  
> 取代 [`29-回溯v1冻结口径.md`](./29-回溯v1冻结口径.md) 的**产品面**。v1 文档仅作实现考古；落地与回归以本文件为准。

## 目标

对齐 Cursor Agent 公开可复现行为：Checkpoint + Restore + Continue-and-Revert，点击同帧投影、磁盘后台追平。

| Cursor 行为 | XenYon v2 合同 |
|-------------|----------------|
| 每轮 Agent 前有 checkpoint | 每条可回溯 user 绑定 `checkpoint_id` + 作用域快照（`.xy-shadow-git` / snapshot store） |
| 悬停 Restore Checkpoint | 一键：截断后续对话 + 恢复该拍 agent 触及文件；无厚确认窗 |
| 编辑历史并提交 | Continue-and-Revert：同帧截断 + 文件 rehydrate + **自动 send** |
| 聊天 DAG | 后继进 orphan/归档分支；主视图只显示 active 前缀 |
| 瞬时体感 | 乐观 UI；`execute` 快速 `accepted`；先 transcript 再 workspace |
| 不碰用户 `.git` | 仅 shadow-git / 内容寻址 blob |

## 相对 v1 的废止项

- 厚确认弹窗作为主路径（改悬停 Restore + 编辑即提交）
- 确认后不自动重发
- 日常「是否回滚文件」勾选（默认同拍恢复；仅脏冲突阻断）

## 保留（自 v1）

- 幂等 `idempotency_key`
- worktree 脏路径阻断（禁止 force 盖手改）
- 客户端 message id 真源
- `.old*` 作废；权威在服务端 revision
- 默认 `path_scope` 差集；`full_tree_restore` 仅 opt-in

## 双入口

### A. Restore Checkpoint

- 触发：用户气泡悬停控件
- 行为：乐观截断 + orphan → 异步 execute（`restore_workspace=true` 默认）→ **不** send
- 冲突：轻量阻断条 / `blocked`，非模态厚窗

### B. Continue-and-Revert

- 触发：编辑历史 user 并提交
- 行为：乐观截断 + orphan → 异步 execute → **自动 `sendMessage(editedText)`**
- 无 checkpoint 的旧消息：降级 preview 或仅截断对话

## 后端合同

### Checkpoint

- turn 开始 / user 落盘时写入 `before_commit` + 稳定 `checkpoint_id`
- 可预计算并缓存 `shadow_paths` / fingerprint，悬停 Restore 免重算 diff
- 恢复热路径：**禁止**全仓 `git add -A`；scoped safety + batch blob 写盘

### Execute（异步）

| 阶段 | 含义 |
|------|------|
| `accepted` / `preparing` | 已受理，FE 可乐观投影 |
| `transcript_committed` | jsonl 前缀已重写；可继续 Agent |
| `executing` | 工作区 restore 进行中 |
| `committed` | transcript + workspace（若需）完成 |
| `recovery_required` | 中间态；仅 recover / abandon |

- `confirmed=true` 仍必填（Restore / Continue 均视为显式确认）
- 成功响应优先 `retained_message_ids`；全量 `retained_messages` 兜底
- `GET .../rollback/status/{job_id}` 为主路径进度源

### Preview

- Continue 路径可仍用 preview 做冲突探测；命中 checkpoint 缓存则快速返回
- Restore 路径可跳过厚 preview UI，直接带缓存 plan / checkpoint execute

## 前端合同

| 项 | 口径 |
|----|------|
| 乐观投影 | 点击同帧 `messagesById` slice + orphan；不等 HTTP |
| Continue | execute 受理后自动 `sendMessage` |
| Restore | 不自动 send |
| 对话框 | `WorkspaceRevertDialog` 仅 `blocked` / `recovery` |
| 阶段机 | `rollbackMachine` 含 optimistic / workspace_pending |

## 性能门槛

- 空闲 session、≤20 scoped 文件：点击→消息列表截断 **&lt; 100ms**（主线程）
- workspace 后台典型 **&lt; 1s**
- scoped restore 热路径不得出现全仓 `git add -A`

## 明确不做

- 完整编辑器 VFS
- 侧聊对等 rewind UI
- 二进制大文件可靠快照
- 默认整树 restore
