# XEYO_Workspace 计划书

> 更新时间：2026-08-23
> 目标：把右侧栏（文件树 + 文件预览/编辑）整合为一个父级容器「XEYO_Workspace」，并新增「审查 / Git 树 / Git 提交推送 / 历史命令行 / 左键快捷菜单」等能力，统一工作区入口。
> 状态：**计划（草案，未落地）**。落地遵循「先预览再选择」流程，每项能力先行实现最小闭环。

---

## 一、项目背景与目标

### 1.1 现状问题

右侧存在两个**独立**的侧栏组件，各自维护 PaneSlot、resize、presence、hover-scroll：

- `ExplorerPanel`（文件树，`PaneSlot side="right"`）
- `FilePreview`（文件预览/编辑，`PaneSlot side="right"`）

二者在 `ChatPage.tsx` 里是**平级兄弟**（`<FilePreview />` 在 `<ExplorerPanel />` 之前），各自独立开合，宽度、状态互不共享。

缺少：统一的「工作区」语义、修改文件审查（默认）、历史 diff 审查（可选择）、Git 树、Git 提交/推送、历史命令行、可复用的左键快捷菜单。

### 1.2 目标

创造一个父级容器 **`XEYO_Workspace`**，作为右侧栏唯一出口，内部以**模块（tab / 分栏）**组织能力：

| 能力 | 说明 | 现状 |
|---|---|---|
| **功能选择（首次）** | 首次展开 XEYO_Workspace 时显示功能入口面板（如 审查 / 文件 / Git / 历史 命令行等），勾选启用哪些模块；**选择持久化**，下次展开侧栏保留上次的选择。 | **无**，新增 |
| **审查（Review）** | 默认展示「本会话改动文件」及「与上轮的 diff」；可切换到「历史文件 diff」。 | 已有部分 `reviewDiff` + `DiffPreview`，缺历史维度 & 会话维度聚合 |
| **文件预览编辑** | 点击文件 → 预览（markdown/代码/图片）+ 就地编辑 + 保存。 | **已有**（`FilePreview` + `TextFileEditor` + `EditableMarkdown`） |
| **Git 树** | 以 Git 视角展示工作区：未提交/未暂存/已暂存/已提交/分支。 | **无**，需新增 |
| **Git 提交推送** | 提交（stage + commit + message）、推送（push）。 | **无**，需后端 git 封装 + 前端操作栏 |
| **历史命令行** | 按「一轮会话」聚合显示该会话内所有命令行/工具调用历史。 | 已有 `ActivityLog`（按 turn 内 tool），需「会话聚合」视图 |
| **左键快捷菜单** | 左键文件 → 菜单：VS Code 打开 / 打开方式 / 另存为 / 复制路径 / 添加到聊天。 | **右键已落地**：`WorkspacePanel` 文件树经共享 `ContextMenu`（`gui/src/components/ui/ContextMenu.tsx`）+ `workspaceOpen` helpers；左键快捷菜单仍为后续可选，不改变「单击打开预览」 |

### 1.3 命名

- 父组件：**`XEYO_Workspace`**（前端 `gui/src/components/XEYO_Workspace/` 目录）。
- 后端：`server/workspace_git.py`（Git 相关）+ 复用 `workspace_fs.py`（文件 IO）。

---

## 二、总体架构

### 2.1 组件分层

```
ChatPage
 └─ AppShell
     └─ <XEYO_Workspace />                    ← 新的唯一右侧出口（替代 FilePreview + ExplorerPanel）
         ├─ <WorkspaceHeader />               ← 工作区标题 + 顶栏动作（模块切换/收起）
         ├─ <WorkspaceModuleTabs />           ← 模块切换（审查 / 文件 / Git / 历史 命令行…，来自启用集）
         ├─ <WorkspaceResizeHandle />         ← 复用 PaneResizeHandle
         ├─ <WorkspaceFeatureGate />          ← 首次功能选择 + 持久化读取（见 3.7）
         │     ├─ <WorkspaceFeaturePicker />  ← 首次：勾选启用模块，选择持久化
         │     └─ <WorkspaceModuleHost />     ← 有启用集时按当前模块渲染：
         │          ├─ <ReviewView />         │  审查（默认改动文件 + 对话关联 + 历史 diff）
         │          ├─ <FileExplorerView />   │  文件树（复用 ExplorerPanel 逻辑）
         │          ├─ <FilePreviewView />    │  文件预览/编辑（复用 FilePreview 逻辑）
         │          ├─ <GitTreeView />        │  Git 树（新增）
         │          ├─ <GitHistoryView />     │  提交历史 / 文件 diff（新增）
         │          └─ <SessionCommandHistory />│ 会话历史命令行（新增/聚合 ActivityLog）
         └─ (空态) 首次无启用集 → 仅渲染 <WorkspaceFeaturePicker />
```

### 2.2 断言 / 不变式

1. `XEYO_Workspace` 是右侧栏**唯一**入口；`FilePreview` / `ExplorerPanel` 不再被 `ChatPage` 直接引用（改由容器内部 `FilePreviewView` / `FileExplorerView` 调用）。
2. 文件 IO 语义不变：仍走 `/v1/workspace/*`，仅允许 cwd 内。
3. 权限语义不变：`OpenFolder` 仍走 `pickFolder` + `openFolder`。
4. Git 操作**只读默认**；`commit/push` 需显式确认（复用权限弹窗或内联确认）。
5. **功能选择集是「准入」而非「单例」**：`XEYO_Workspace` 只在「已启用模块集」非空时才渲染各模块内容；首次无选择 → 显示 `WorkspaceFeaturePicker`。
6. **选择持久化**：已启用的功能集 + 最近激活模块写入 `settingsStore.persistLite`（localStorage），下次展开侧栏恢复上次的模块与启用集。

---

## 三、功能规格

### 3.1 审查（Review）

**默认模式 — 本会话改动文件（且关联到触发它的对话）**

- 数据源：基于**会话内 tool 事件**聚合出「被写/改过的文件」。
  - 现有 `toolActivity.ts` 已能从 `ActivityStep` 提取 `DiffStat`（add/del）。
  - 新增派生物：`collectWorkspaceChangedFiles(sessionId, transcripts)` → `ChangedFile[]`，
    `ChangedFile = {path, name, status: created|modified|deleted, diff?, turnId, userText, userTitle, steps: ActivityStep[]}`。
- **修改 → 对话关联**（用户新增需求）：利用 `groupTranscript` 的 `TranscriptBlock` 结构，`groupRounds` 能把
  「用户消息（round.user）」与其后的工具轮（turn）绑定。于是可把每个改动文件追溯回：
  - `turnId`：产生该改动的轮次 id
  - `userText`：触发该轮的用户消息原文（`round.user.text`）
  - `userTitle`：用户消息的「标题」（取首行 / 截断前 N 字，作为一键跳转可读标题）
  - `steps`：该轮中涉及此文件的所有 ActivityStep（含 verb、diff、args）
- **展示（Git 树 / 审查列表共用）**：文件清单每一项显示
  - 左侧状态图标 + 文件名 + `+/-` diff 统计
  - 下方一行：`标题 → 用户消息`（如 `修复登录 → 请修复登录页面报错`）
  - 点击 / 展开 → 显示该文件详细的 `steps`（verb、args、diff 片段）与关联轮次
  - 展开项内含**「回溯」按钮**：可**选择是否回溯**该文件/该轮（见 3.1.1）
- 默认交互：点击 → `openReview(file)` 打开 diff（复用 `openReview` + `DiffPreview`）。

**可切换 — 历史文件 diff 审查**

- 数据源：基于 **rewind**（已具备 `/v1/sessions/{sid}/rollback/preview`）或 **shadow-git** 版本。
- 新增后端 `/v1/workspace/history/{path}` → 该文件历史 revision 列表 + 任意两版本 diff。
- 前端：`GitHistoryView` 选择文件 + 两个 revision → 渲染 `DiffPreview`。

### 3.1.1 回溯（Rollback）选择

- 每个改动文件/轮次展开项内提供「回溯」操作，**由用户选择是否执行**：
  - **单文件回溯**：把该文件恢复到「本轮开始前」的状态（基于 shadow-git / rewind 版本）。
    - 后端：`POST /v1/workspace/git/restore-file` `{path, targetTurnId?}` → 恢复指定版本。
  - **轮次回溯**：把该轮改动整体回滚（复用现有 `/v1/sessions/{sid}/rollback/preview` + `/execute`）。
    - 前端沿用 `WorkspaceRevertDialog` 交互：预览受影响文件清单 → 确认 → 执行 → 刷新 Git 树。
- **安全**：回溯前必须展示受影响文件与将丢弃的后续轮次；未追踪新文件移入 `.xy-trash`；execution 用 idempotency key；失败回滚安全快照。
- **落地顺序**：**先做「单文件回溯」**（直接对 shadow-git，成本低、风险小）；**再做「轮次回溯」**（复用 rewind rollback 服务）。

> 落地顺序：**先做「默认改动文件审查 + 对话关联」**（复用现有 `reviewDiff` 最小改动）；**再做「历史 diff」与「回溯」**（依赖 rewind/shadow-git，属二次迭代）。

### 3.2 文件预览编辑

完全复用 `FilePreview` 现有实现，抽到 `FilePreviewView`，不改交互。保留：

- markdown 预览/源码切换
- 代码高亮、图片、binary
- 就地编辑 + 防抖保存（`saveFile`）+ `loadingFile` / `truncated`
- 选中区工具条（`SelectionToolbar`）：Ask Agent / Ask Side / Markdown 格式化

### 3.3 Git 树

- 后端新增 `server/workspace_git.py`：
  - `git_status(cwd)` → `{branch, ahead, behind, entries: {path, status: untracked|modified|staged|deleted|renamed}[]}`
  - 复用 `.xy-shadow-git`（已存在）或直接调用户仓库 `git`（用 `GIT_DIR` 指向用户 `.git`）。
- 前端 `GitTreeView`：
  - 分区：`未提交`（未暂存 / 未暂存已改）、`已暂存`、`已提交`、`分支`
  - 头部下拉（复刻图一）：`上一轮 / 未提交 / 未暂存 / 已暂存 / 已提交 / 分支`
  - **每一项 = 修改 + 对应对话**（用户新增需求）：
    - 行首：文件名 + 状态徽标 + `+/-` diff 统计
    - 行下：`标题 → 用户消息`（如 `修复登录 → 请修复登录页面报错`），标识该改动由哪轮对话触发
    - 点击展开：显示该文件**详细信息**（关联轮次 turnId、触发用户消息原文、该轮所有涉及此文件的 `ActivityStep`：verb/args/diff 片段）
    - 展开项内「**回溯**」按钮 → 见 3.1.1（是否回溯由用户选择）
    - 其它点击入口：`openReview(file)` 打开该轮 diff，或 `openFile(path)` 打开当前文件

### 3.4 Git 提交推送

- 后端：
  - `POST /v1/workspace/git/commit` `{message, paths?}` → `git add` + `git commit`
  - `POST /v1/workspace/git/push` `{remote?, branch?}` → `git push`
  - `GET /v1/workspace/git/log` → 最近提交列表（`git log --oneline -N`）
  - `GET /v1/workspace/git/diff` `{path, a, b}` → 两版本 diff
- 前端 `GitToolbar`：提交输入框 + 「提交」「推送」按钮；提交前调 `confirm`（复用 `PermissionDialog` 或内联二次确认）。

### 3.5 历史命令行（按会话聚合）

- 数据源：`ActivityLog` 现按「turn 内 tool step」聚合（`AssistantTurn` 内嵌）。
- 新增「会话维度」聚合视图：`SessionCommandHistory` 遍历该会话所有消息/turn 的 `ActivityStep`，扁平化成「一轮会话」归组的时间线。
- 复用 `formatArgs` / `oneLinePreview` / `DiffBadge` 展示逻辑；点击展开 tool payload。

### 3.6 左键快捷菜单

- **右键（已落地）**：`WorkspacePanel` `FileRow` 使用共享 `ContextMenu`（`openContextMenu` / `ContextMenuHost`），handlers 在 `gui/src/lib/workspaceOpen.ts`（VS Code / 系统默认 / 另存为 / 复制路径 / 添加到聊天）。旧 `ExplorerContextMenu` 已删除。
- **左键（后续可选）**：若要做「单击文件弹同款菜单」，需保留默认打开预览，或改为修饰键/长按触发，避免破坏当前左键打开行为。
- 审查 diff 行、侧栏会话、聊天消息亦已接入同一 ContextMenu 原语。

### 3.7 功能选择 + 持久化（首次展开 XEYO_Workspace）

- **触发时机**：`XEYO_Workspace` 首次展开（`open=true` 且「已启用模块集」为空）时，显示**功能入口选择面板** `WorkspaceFeaturePicker`。
- **功能清单（模块）**（仅参考图片功能，不照搬样式）：列出可启用的模块，作为功能入口项，每项带可选快捷键：
  - 审查（Review）
  - 文件（文件树 + 预览/编辑）
  - Git（Git 树 + 提交/推送 + 历史 diff）
  - 历史命令行（会话聚合的 tool/命令时间线）
  - 侧边聊天（详见现状 `SideChat`，如需并入可扩展）
- **交互**：
  - 首屏为模块清单（每项一行：图标 + 名称 + 快捷键提示），勾选 / 点选启用；
  - 勾选后写入「已启用模块集」；默认勾选最常用（文件 + 审查）。
  - 点击进入 → 存为「最近激活模块」。
- **持久化**：复用 `settingsStore.persistLite`（localStorage `xeyo-settings`），新增字段：
  - `workspaceModules: WorkspaceModuleId[]`（已启用集）
  - `workspaceActiveModule: WorkspaceModuleId | null`（最近激活）
  - `workspaceFeatureSeen: boolean`（是否已完成首次选择）
- **恢复**：下次展开侧栏 => 读 `workspaceFeatureSeen` + `workspaceModules`；非空则直接进入 `workspaceActiveModule`，否则重新显示选择面板。
- **可重新打开**：`WorkspaceHeader` 提供「修改功能」入口，可再次打开 `WorkspaceFeaturePicker` 增删模块。
- **严格只参考功能**：不参考图中的具体样式/布局，仅采用「首屏选择功能、选中后持久化、下次保留」的交互语义。

---

## 四、实施步骤（分阶段）

### 阶段 A — 容器整合（重构，不改行为）

1. 建 `gui/src/components/XEYO_Workspace/`，创建 `XEYO_Workspace.tsx` 用 `PaneSlot side="right"` 包裹。
2. 把 `FilePreview`/`ExplorerPanel` 的 PaneSlot/resize/presence 收敛到容器；`FilePreviewView` / `FileExplorerView` 只保留内容区。
3. `ChatPage.tsx`：删除 `<FilePreview />` 与 `<ExplorerPanel />`，改渲染 `<XEYO_Workspace />`。
4. **验收**：打开文件夹、点击文件预览/编辑/保存，行为与现在完全一致。

### 阶段 A2 — 功能选择 + 持久化（首次展开）

4a. `settingsStore` 新增 `workspaceModules / workspaceActiveModule / workspaceFeatureSeen` 字段并入 `persistLite`。
4b. 新增 `WorkspaceFeaturePicker`：模块清单（审查/文件/Git/历史命令行/侧边聊天）+ 勾选 + 进入，写入启用集 + 最近激活。
4c. `XEYO_Workspace` 接入 `WorkspaceFeatureGate`：首次（`workspaceFeatureSeen=false`）→ 显示选择面板；否则 → 直接进入上次 `workspaceActiveModule`。
4d. `WorkspaceHeader` 提供「修改功能」入口，可重开选择面板。
4e. **验收**：首次展开出现功能选择面板；勾选进入某模块；关闭再展开侧栏 → 恢复上次模块；修改功能后启用集更新并持久化。

### 阶段 B — 默认改动文件审查 + 对话关联

5. `changedFiles.ts` 新增 `collectWorkspaceChangedFiles(sessionId, transcripts)`，返回含 `turnId/userText/userTitle/steps` 的 `ChangedFile[]`（复用 `groupTranscript` 的 `round.user`）。
6. `explorerStore` 新增 `workspaceChanges` 状态 + `loadWorkspaceChanges(sessionId)`。
7. `XEYO_Workspace` 增加「审查」模块默认视图 + `ChangedFileCard`（标题→用户消息 + 展开详情）。
8. **验收**：一轮对话后，右侧「审查」列出改动文件，每项显示「标题→用户消息」，点击展开显示详情与 diff。

### 阶段 B2 — 回溯（选择是否回溯）

8a. 后端 `workspace_git.restore_file(cwd, path, targetTurnId?)` + `POST /v1/workspace/git/restore-file`（基于 shadow-git）。
8b. `explorerStore` 新增 `rollbackChangedFile` / `rollbackTurn`（单文件 restore，或复用 rewind rollback preview/execute）。
8c. `ChangedFileCard` 内「回溯」按钮 → 确认 → 执行 → 刷新 Git 树 + 改动文件列表。
8d. **验收**：对某项改动点回溯，该文件恢复到本轮前状态，Git 树随之刷新；未追踪文件进 `.xy-trash`。

### 阶段 C — Git 树 + 提交推送

9. 后端 `server/workspace_git.py` + 4 个端点（status/log/commit/push/diff）。
10. `api.ts` 加 `gitStatus/gitLog/gitCommit/gitPush/getGitDiff`。
11. `GitTreeView` + `GitToolbar`（复刻图一分组 + 下拉；每项含「标题→用户消息」关联 + 展开详情 + 回溯）。
12. **验收**：改一个文件 → Git 树出现「未提交」（含对应对话）；提交 → 进入「已提交」；推送成功。

### 阶段 D — 历史命令行（会话聚合）

13. `gui/src/lib/sessionActivity.ts` 聚合 `ActivityStep`。
14. `SessionCommandHistory` 视图。
15. **验收**：切到「历史」模块，看到该会话全部命令行/tool 按轮分组。

### 阶段 E — 左键快捷菜单 + 打磨

16. 文件树左键 → 菜单（复用 context 菜单）。
17. 顶栏 / 模块切换 / 空态 / 深色适配。
18. 回归全量后端测试 + 前端 typecheck + vitest。

---

## 五、时序图

### 5.0 功能选择与持久化（首次展开 XEYO_Workspace）

```
User              XEYO_Workspace/FeatureGate     settingsStore(persistLite)
 |                     │                              │
 | 展开侧栏 ─────────► │ read workspaceFeatureSeen    │
 |                     │◄── false（首次）              │
 |                     │ 渲染 WorkspaceFeaturePicker  │
 | 勾选模块 + 进入 ──► │ selectModules([…])           │
 |                     │ setActiveModule(m) ────────► │ persistLite({workspaceModules, workspaceActiveModule, workspaceFeatureSeen:true})
 |                     │◄── 进入 m 模块视图            │
 | 收起再展开 ───────► │ read workspaceFeatureSeen    │
 |                     │◄── true                      │
 |                     │ 直接进入 workspaceActiveModule│
```

### 5.1 打开工作区 → 文件树 → 预览编辑（现状保留）

```
User              XEYO_Workspace              explorerStore            Backend(/v1/workspace)
 |                     │                          │                        |
 | 打开文件夹  ──────►  │  pickFolder()             │                        |
 |                     │  openFolder(path) ──────► │  POST /v1/workspace    │
 |                     │                          │  GET /v1/workspace/entries
 |                     │                          │◄────────────── entries  │
 | 点击文件(左键) ───► │  openFile(path)  ──────► │  GET /v1/workspace/file │
 |                     │                          │◄────────────── doc      │
 |                     │  set({childrenByPath, doc})
 | 编辑文本  ────────► │  onDraftChange ─► dirty  │                        │
 |                     │  防抖700ms ─► saveFile() │  PUT /v1/workspace/file │
```

### 5.2 审查（默认改动文件 + 对话关联）

```
轮次结束(工具执行完成)
  explorerStore.loadWorkspaceChanges(sessionId)
     │ 读会话 ActivityStep + groupTranscript → collectWorkspaceChangedFiles
     │◄── ChangedFile[]{path,name,status,diff,turnId,userText,userTitle,steps}
  XEYO_Workspace: ReviewView / GitTreeView 渲染文件清单
     ├─ 每项显示：状态图标 + 文件名 + +/- diff
     ├─ 每项显示：标题 → 用户消息（turnId 对应轮次的 round.user）
     │   点击展开 → ChangedFileCard 显示关联详情(steps/turnId/userText) + 回溯按钮
     │   【回溯】→ confirm → 单文件 restore / 轮次 rollback → 刷新 Git 树
     └─ 点击文件 → openReview(file) → FilePreviewView 显示 DiffPreview(diff)
```

### 5.3 回溯（选择是否回溯）

```
User            ChangedFileCard/ReviewView       api.ts            Backend
 |                    │                           │                  |
 | 点「回溯」 ──────► │  confirm(影响文件/丢弃轮次)│                  |
 |                    │  restoreFile(path) ──────►│ POST /git/restore-file
 |                    │◄── ok                     │ (shadow-git 恢复版本)
 |                    │  或 rollbackPreview() ───►│ POST /rollback/preview
 |                    │◄── plan                   │
 |                    │  rollbackExecute() ──────►│ POST /rollback/execute
 |                    │◄── ok                     │
 |  刷新 Git 树 ─────►│  gitStatus() ────────────►│ GET /git/status
```

### 5.4 Git 提交推送

```
User            GitTreeView/GitToolbar         api.ts            Backend(workspace_git)
 |                    │                          │                    |
 | 打开 Git 模块 ───► │  gitStatus()  ──────────► │  GET /git/status   │
 |                    │◄──── status{branch,entries}
 | 输入 message ────► │  gitCommit(msg,paths) ──► │  POST /git/commit  │
 |                    │◄──── commit ok           │ (git add && commit)│
 | 推送 ───────────► │  gitPush()     ─────────► │  POST /git/push    │
```

---

## 六、事件图（关键事件流）

### 6.0 功能选择持久化

```
WorkspaceFeaturePicker 勾选 ──► settingsStore.update({workspaceModules, workspaceActiveModule, workspaceFeatureSeen})
                              ──► persistLite → localStorage('xeyo-settings')
XEYO_Workspace mount/open   ──► read workspaceFeatureSeen
                              ──► true → 进入 workspaceActiveModule；false → 显示 WorkspaceFeaturePicker
```

### 6.1 会话 → 审查数据

```
[tool_result SSE] ──► chatStore 更新 messages
                    ──► toolActivity 派生 ActivityStep
                    ──► collectWorkspaceChangedFiles 聚合改动文件
                    ──► XEYO_Workspace 订阅 → ReviewView 刷新
```

### 6.2 文件选中

```
文件树点击 ──► explorerStore.setSelectedPath(path)
            ──► FilePreviewView 显示对应 doc / diff
```

### 6.3 Git 状态刷新

```
GitTreeView mount / 文件保存后 ──► api.gitStatus()
                                  ──► GitTreeView 更新 entries
```

---

## 七、最终文件树（前端新增/变更）

```
gui/src/components/XEYO_Workspace/
├── XEYO_Workspace.tsx            # 父容器：PaneSlot + header + gate + host
├── WorkspaceHeader.tsx           # 顶栏：标题 + 打开文件夹 + 「修改功能」入口 + 收起
├── WorkspaceFeatureGate.tsx      # 首次功能选择 + 持久化读取（新增）
├── WorkspaceFeaturePicker.tsx    # 模块清单勾选 + 进入（新增）
├── WorkspaceModuleTabs.tsx       # 模块切换（审查/文件/Git/历史）
├── WorkspaceModuleHost.tsx       # 依模块渲染子视图
├── ReviewView.tsx                # 审查：改动文件清单 + 对话关联 + 回溯入口
├── ChangedFileCard.tsx           # 单改动：标题→用户消息 + 展开详情 + 回溯（新增）
├── FileExplorerView.tsx          # 文件树（从 ExplorerPanel 收敛）
├── FilePreviewView.tsx           # 预览/编辑（从 FilePreview 收敛）
├── GitTreeView.tsx               # Git 树（新增，含对话关联项）
├── GitToolbar.tsx                # 提交/推送操作栏（新增）
├── GitHistoryView.tsx            # 提交历史 / 文件 diff（新增）
└── SessionCommandHistory.tsx     # 会话历史命令行（新增）

gui/src/lib/
├── sessionActivity.ts            # 新增：ActivityStep 会话聚合
├── changedFiles.ts               # 新增：collectWorkspaceChangedFiles → 对话关联（turnId/userText/userTitle）
└── toolActivity.ts               # 变更：导出 changed-file 相关复用件

gui/src/stores/
├── explorerStore.ts              # 变更：新增 workspaceChanges + loadWorkspaceChanges
├── settingsStore.ts              # 变更：persistLite 新增 workspaceModules / workspaceActiveModule / workspaceFeatureSeen
└── workspaceStore.ts             # 新增：当前模块、Git 状态、回溯作业（可选拆分）

python/server/
├── workspace_git.py              # 新增：git status/log/commit/push/diff/restore-file
└── app.py                        # 变更：新增 /v1/workspace/git/* 端点
```

---

## 八、落地策略与风险

- **先重构后加功能**：阶段 A 纯收敛，保证零行为变化，风险最低。
- **Git 只读优先**：status/log/diff 安全；commit/push 需确认，且先做「shadow-git」可回滚。
- **跨平台 git 路径**：`GIT_DIR` 指向用户 `.git`，需处理 HTTP 下无法调用 git（Tauri 才有）的降级。
- **性能**：文件树与 Git 状态均懒加载，避免打开即全量扫描。
- **回归**：每阶段跑 `npm run typecheck` + `vitest`，后端 `pytest` 全量。
