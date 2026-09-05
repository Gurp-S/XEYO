# GUI 前端代码地图

> React 19 + Vite + Tauri。系统 prompt 在 Python 组装，前端只发用户消息与设置。

## 发一条消息（读码路径）

```
Composer.tsx
  → slashCommands.ts / lib/slash.ts
  → useChatUiStore（SideChat 可注入独立 store）
  → chatStore.ts（facade）
  → stores/chat/streamSendSlice.ts
  → lib/api/chatStream.ts → lib/api/core.ts（SSE）
  → lib/toApiMessages.ts
  → FastAPI chat.py
```

## Chat Store 切片（`stores/chat/`）

| 文件 | 职责 |
|------|------|
| `preStoreHelpers.ts` | `ChatState` 类型与共享 helper |
| `spaceSessionSlice.ts` | 空间 / 会话列表 |
| `uiChromeSlice.ts` | 侧栏、composer 插入、pending 权限 UI |
| `streamSendSlice.ts` | SSE 发送、流排水、持久化钩子 |
| `streamRecoverySlice.ts` | 断点续跑 / recovery |
| `streamHelpers.ts` / `streamDrain.ts` / `streamPersistence.ts` | 流辅助 |
| `rollbackSlice.ts` | 回溯 **v2** 任务 |
| `multiAgentSlice.ts` | 子 agent 卡片 |
| `remoteMirrorSlice.ts` | 远程微信镜像 |

独立 store：`stores/rewindV3Store.ts` — 回溯 **v3** 热路径（现行默认）。

## 回溯：v2 vs v3

| | v2 | v3 |
|---|----|----|
| Store | `rollbackSlice` | `rewindV3Store` |
| UI | `RollbackDialogs`, `WorkspaceRevertDialog` | 同文件内 v3 对话框 |
| 后端 | sessions rollback API | `/v1/rewind/*` hotpath |

新功能默认走 **v3**；改 v2 前先确认是否仍被调用。

## 消息列表

```
components/MessageList.tsx（shim）
  → messageList/MessageList.tsx
  → useMessageListStore.ts
  → groupTranscript.ts → groupRounds.ts
  → RoundHost.tsx → AssistantTurn.tsx
  → useMessageListEditing.ts（编辑/回溯，文件较大）
```

## API 层

| 路径 | 说明 |
|------|------|
| `lib/api.ts` | 仍含大量 endpoint（迁移中） |
| `lib/api/core.ts` | SSE 解析、fetch 工具 |
| `lib/api/chatStream.ts` | 聊天流 |
| `lib/workspaceMapApi.ts` | 工作区地图（待并入 `api/workspace.ts`） |

## Markdown 渲染

- **流式**：`StreamingMarkdown` → `XyStreamdown` → streamdown
- **静态**：`MarkdownView` → 同上内核
- 启发式：`lib/streamMarkdown.ts`、`incrementalRemend.ts`

## 工作区

- `workspaceStore` + `explorerStore` — 预览与工具面板互斥
- `stores/workspaceExplorerSync.ts` — 在 `main.tsx` 启动时绑定

## Store 约定

- 共享组件用 **`useChatUiStore`**（可注入 SideChat 独立 store）
- 页面级可直接 **`useChatStore`**

## 测试

```powershell
cd gui
npm run typecheck
npm test
```
