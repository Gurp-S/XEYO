# XEYO 合并计划（去重）

来源对话：

- [主要设计](8942651d-34d7-4b28-8fb1-7820e10e2628) — Agent 落地分层 / 能力优先级（画布 `xeyo-agent-readiness`）
- [XEYO Agent evaluation and insights](99768447-61b5-417d-83ee-4149b58cb141) — 落地判断 + 补全/分叉 + 前端巨石拆除脚本（画布 `xeyo-product-verdict`）

合并原则：以 **evaluation 较新口径为准**；「主要设计」里已过时或被纠正的条目降级/删除；重复项只保留一条并写清来源。

**进度三态**（与落地判断画布一致）：`未开始` / `进行中` / `已完成`。
进度来源：`xeyo-product-verdict.canvas.data.json` 的 `optStatus`（三态优先）；无记录时回退 `xeyo-agent-readiness.canvas.data.json` 的 `todo-done`（勾选→已完成，未勾选→未开始）。快照日期约 2026-08-30。

---

## 进度总览

| 进度   | 事项数（§3 统一清单，不含纯冻住维护项） |
| ------ | ---------------------------------------- |
| 已完成 | 11                                       |
| 进行中 | 1                                        |
| 未开始 | 22                                       |

| 进度   | ID                                                                                                                                                                                                                   |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 进行中 | `megastore`                                                                                                                                                                                                        |
| 已完成 | `avoid-ide` · `avoid-loop` · `cwd` · `avoid-depth` · `lsp` · `rewind-ux` · `subagent-stable` · `notebook-ux` · `git-write` · `web-landed`（工具已上，见 websearch-keys）· 冻住层 12 项 |
| 未开始 | 其余 P0–P3 行动项                                                                                                                                                                                                   |

画布原始快照：

- **落地判断 `optStatus`：** `megastore=doing`，`clone-ide=done`；其余默认未开始
- **落地分层 `todo-done` 已勾：** loop, tools-core, session, ui-stream, perm-skeleton, prompt, model-client, skill, orchestration, ask-plan, usage, tests-core, cwd, bash-policy, subagent, rewind, session-cwd, web, lsp, notebook, git-tool
- **落地分层未勾：** c2, wechat, gui-polish, slash, tool-comments, fallback-cfg, nightshift, mcp, cli, os-sandbox, model-fallback

---

## 0. 总判（两边一致，evaluation 更细）

| 判断                  | 结论                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| 是不是 demo           | **不是。** 真 SessionPool、真 HTTP 流、真工具、真权限挂起。                                 |
| 有没有一套 Agent 体系 | **有骨架。** 单 Agent + 一层工人：循环 / 工具 / 权限 / 会话 / 中断续上 / 回溯闭环。         |
| 能不能落地用          | **作者本机写代码：可以。** 给不可信任务 / 微信随便跑命令 / 当 1.0 安装包：**不行。**  |
| 接下来是不是都是优化  | **只对一半。** 亮点可做；结构债（前端巨石、双多 Agent）和安全债（Bash 非沙箱）不是 polish。 |
| 版本水位              | `0.1.0` alpha：自用成立，熟人接近，1.0 不成立。                                                 |

**冻结（不要重建）：** `query_loop`、编码最小文件工具、JSONL 会话协议、流式 UI/Stop、权限三态骨架、Skill 加载器、工具分区执行、Ask/Plan 协议、用量账本、主路径契约测试。

---

## 1. 口径校正（evaluation 对「主要设计」的覆盖）

| 「主要设计」原条目                       | 合并后口径                                             | 进度备注                                               |
| ---------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------ |
| WebSearch / WebFetch = 刚需缺口          | **工具已启用**；余下是「无钥时很脆」→ P2 产品化 | 工具侧**已完成**；无钥禁用仍 **未开始**    |
| Notebook 结构化编辑 = 刚需缺口           | **`NotebookEdit` 已独立工具**                  | **已完成**                                       |
| Agent 侧 Git 工具 = 刚需缺口             | **只读 Git 已在启用工具里**                      | 只读**已完成**；写细权限仍可后排                 |
| 微信 / NightShift / 回溯 / 桌宠 = 差异化 | **降格为补全**                                   | 回溯**已完成**；微信/NightShift **未开始** |
| CWD / 多 session 隔离 = P0               | 与会话 CWD 隔离合并跟踪                                | **已完成**（cwd + session-cwd 均已勾）           |
| 联网 / MCP / LSP / CLI 当差异            | **明确不是差异**                                 | LSP**已完成**；MCP/CLI **未开始**          |

---

## 2. 产品分叉选择（仅 evaluation；主要设计无此项）

检验一句：Cursor（或 Claude Code）用一年做成这件事之后，它还是不是 Cursor？还是 → **不是差异，只是完整度**。

| 路                    | 含义                       | 默认动词     | 进度                                 |
| --------------------- | -------------------------- | ------------ | ------------------------------------ |
| **A · 做完整** | 和 Cursor 同一赛道，补器官 | 去把这事做完 | 默认施工路（未显式改选）             |
| **B · 分叉**   | 故意变窄变慢，换身份       | 见下         | **未开始**（产品选择，非现状） |

若选 **B**，两条必须锁在一起：

### 2.1 设计分叉 · 对弈结对 — 未开始

- 默认动词：对**这一步**表态（接受 / 驳回 / 改招），不是干完整单。
- 必须变差：禁止 YOLO、「去把整单做完」当默认；无通宵雇员主路径。
- 成功态：一步被裁决，不是 `ResultEvent(task done)`。

### 2.2 功能分叉 · 一仓一人 — 未开始

- 打开的是「这座仓库的那个人」，不是通用码农 + 仓库参数。
- 必须变差：禁止跨仓一套人格；冷启动故意慢。

| 组合                | 算不算差异           |
| ------------------- | -------------------- |
| 对弈 + 一仓一人     | **是**         |
| 对弈 + 通用助手     | 否（变差的 Cursor）  |
| 干完整单 + 一仓一人 | 否（带记忆的 Devin） |
| 干完整单 + 通用助手 | 否（今日赛道）       |

**未选 B 就按 A 施工**；不要把微信/晨报/检查点写成身份。

---

## 3. 统一事项清单（去重后 · 含进度）

优先级：P0 → P1 → P2 → P3 → 冻。
进度列：`未开始` / `进行中` / `已完成`。

### 3.1 P0 — 现在就该动

| 进度   | ID            | 事项                                      | 动作                                           | 做完后 | 进度依据                                                                  |
| ------ | ------------- | ----------------------------------------- | ---------------------------------------------- | ------ | ------------------------------------------------------------------------- |
| 完成   | megastore     | 拆`chatStore` / `MessageList` 巨石    | 按流/回溯/多 Agent/UI 切开；不改 SSE；详见 §4 | P2     | verdict`optStatus.megastore=doing`；Phase A 已跑过                      |
| 否定   | bash-sandbox  | Bash → 工作区 jail / Job（或可选容器）   | 远程 bash 默认 deny；禁止堆正则装沙箱          | 冻     | readiness：`bash-policy` 已勾，但 `os-sandbox` 未勾；完整 jail 未完成 |
| 已完成 | avoid-ide     | **不要**补齐内置浏览器 / Open IDE   | 菜单删掉或改成系统浏览器                       | 冻     | verdict`clone-ide=done`                                                 |
| 已完成 | avoid-loop    | **不要**重写 `query_loop`         | 只修真实故障                                   | 冻     | readiness`loop` 已勾（冻住）                                            |
| 进行中 | avoid-xeyo-md | **不要**让 Agent 静默改 `XEYO.md` | NightShift 只提案                              | 冻     | 无显式进度记录（约束项，保持执行）                                        |
| 已完成 | cwd           | 桌面工作区 = 用户选的根                   | 禁默认`python/`；每 session 钉 cwd           | 冻     | readiness`cwd` + `session-cwd` 均已勾                                 |

### 3.2 P1 — 下一波必须动

| 进度   | ID              | 事项                           | 动作                                               | 做完后 | 进度依据                                           |
| ------ | --------------- | ------------------------------ | -------------------------------------------------- | ------ | -------------------------------------------------- |
| 未开始 | dual-multiagent | Scheduler 归档或真接聊天       | 默认 library/tests-only                            | 冻     | verdict 无记录                                     |
| 未开始 | stale-docs      | 删假能力与过时口径             | fallback 实现或删除；改文件头；LOCAL-TEST 正式开关 | 冻     | readiness`fallback-cfg` / `tool-comments` 未勾 |
| 未开始 | e2e             | 5 条 GUI 主路径 e2e            | 发/停/reattach/权限/回溯                           | P2     | verdict 无记录（曾 focus`no-e2e`）               |
| 未开始 | tmp-clutter     | 清`gui/tmp-*`、`_repair-*` | 删快照 + gitignore；单独 PR                        | 冻     | readiness`gui-polish` 未勾                       |
| 未开始 | wechat-harden   | 微信主通道打磨（补全）         | 微信内确认、远程默认只读、截图闭环                 | P2     | readiness`wechat` 未勾                           |
| 未开始 | nightshift-ui   | NightShift 晨报产品面          | 可开关可审计：晋升/冲突 → 接受或遗忘              | P2     | readiness`nightshift` 未勾                       |
| 未开始 | cursor-copy     | 去掉 Cursor 口吻               | 检查点/工作区还原/侧线                             | 冻     | verdict 无记录                                     |
| 已完成 | avoid-depth     | **不要**子 Agent 深度 2+ | 先稳一层工人                                       | 冻     | readiness`subagent` 已勾（边界保持）             |

### 3.3 P2 — 重要但不挡自用

| 进度   | ID               | 事项                       | 动作                                  | 做完后 | 进度依据                                     |
| ------ | ---------------- | -------------------------- | ------------------------------------- | ------ | -------------------------------------------- |
| 未开始 | pending-persist  | 权限/提问挂起落盘          | 重启可恢复；超时 deny + 审计          | 冻     | verdict 无记录                               |
| 未开始 | secret-scan      | 写入路径密钥扫描           | Write/Edit/SendToWeChat 命中 ASK/DENY | 冻     | verdict 无记录                               |
| 未开始 | c2-default       | C2 默认口径统一            | 桌面与测试同一默认                    | 冻     | readiness`c2` 未勾                         |
| 未开始 | websearch-keys   | WebSearch 无钥禁用         | 设置写明钥匙；没钥匙禁用              | P3     | 工具已上（`web` 已勾）；本项产品化未记完成 |
| 未开始 | journal          | Journal 锁与索引或拿掉叙事 | 产品化或别说「多 Agent 可见」         | P3     | verdict 无记录                               |
| 未开始 | mcp              | MCP stdio 宿主（补课）     | 先读再写 + 出站 ASK                   | P3     | readiness`mcp` 未勾                        |
| 已完成 | lsp              | 最小诊断闭环               | 诊断回 loop；不做完整 IDE             | P3     | readiness`lsp` 已勾                        |
| 未开始 | gui-polish       | 桌面收口                   | 冻交互、修真回归                      | —     | readiness`gui-polish` 未勾                 |
| 已完成 | rewind-ux        | 回溯失败态与中文叙事基础   | 不做第二套撤销                        | —     | readiness`rewind` 已勾                     |
| 已完成 | subagent-stable  | 一层工人做稳（当前边界）   | 进度/取消/写冲突；Bash 跟沙箱         | —     | readiness`subagent` 已勾                   |
| 未开始 | pasture          | Pasture：绑状态或删        | 忙/等权限/出错                        | 冻     | verdict 无记录                               |
| 未开始 | avoid-embeddings | **不要**先上向量记忆 | 先晨报可观测                          | 冻     | verdict 无记录                               |

### 3.4 P3 — 可后排

| 进度   | ID             | 事项                | 动作                                 | 进度依据                         |
| ------ | -------------- | ------------------- | ------------------------------------ | -------------------------------- |
| 未开始 | slash          | 4～6 个高频斜杠     | `/clear` `/compact` `/init`…  | readiness`slash` 未勾          |
| 进行中 | cli            | 无头`xeyo chat`   | 复用同一 QueryEngine                 | readiness`cli` 未勾            |
| 已完成 | notebook-ux    | Notebook 工具落地   | 独立`NotebookEdit`；余下体验可选做 | readiness`notebook` 已勾       |
| 已完成 | git-write      | Agent 只读 Git 落地 | 写操作仍 Bash+ASK，细权限可后排      | readiness`git-tool` 已勾       |
| 未开始 | model-fallback | 主模型失败自动切换  | 实现配置或从 UI 拿掉                 | readiness`model-fallback` 未勾 |

### 3.5 已冻住（维护项 · 进度均为已完成）

| 进度   | ID            | 事项                    |
| ------ | ------------- | ----------------------- |
| 已完成 | loop          | Agentic 主循环          |
| 已完成 | tools-core    | 编码最小工具集          |
| 已完成 | session       | 会话 JSONL 持久化与续聊 |
| 已完成 | ui-stream     | 流式 UI + Stop          |
| 已完成 | perm-skeleton | 权限三态骨架            |
| 已完成 | prompt        | 系统提示组装            |
| 已完成 | model-client  | OpenAI 兼容模型客户端   |
| 已完成 | skill         | Skill 按需加载          |
| 已完成 | orchestration | 工具分区执行            |
| 已完成 | ask-plan      | Ask / Plan 挂起恢复     |
| 已完成 | usage         | 用量账本                |
| 已完成 | tests-core    | 主路径契约测试          |

---

## 4. 前端巨石拆除脚本（进度：进行中）

整体事项 `megastore` = **进行中**。
已知：Phase A（纯函数抽出）已由调度脚本跑过并落盘；后续 Phase B–G / M1–M4 仍 **未开始**。

约束：不改对外 API（`useChatStore` / `MessageList` 导出名）；一波只切一块；每波回归门。

每波门禁：

```bat
cd gui && npm test -- src/stores/chatStore.test.ts src/components/MessageList.chat.test.tsx src/hooks/useMessageListStore.ts
```

手测：发消息 → 停 → 刷新续上 → 权限 → 回溯编辑 → 多 Agent 进侧链。

### 4.1 目标树

```
gui/src/stores/
  chatStore.ts                 # facade
  chat/
    types.ts
    streamHelpers.ts
    historyHelpers.ts
    rollbackHelpers.ts
    spaceSessionSlice.ts
    streamSendSlice.ts
    remoteMirrorSlice.ts
    rollbackSlice.ts
    multiAgentSlice.ts
    uiChromeSlice.ts

gui/src/components/messageList/
  types.ts
  groupRounds.ts
  PromptBubble.tsx
  RoundHost.tsx
  MessageList.tsx
gui/src/components/MessageList.tsx   # re-export 保旧路径
```

### 4.2 chatStore 阶段

| 进度   | Phase       | 内容                                                                                 | 完成定义                                     |
| ------ | ----------- | ------------------------------------------------------------------------------------ | -------------------------------------------- |
| 已完成 | **A** | 纯函数搬出：`streamHelpers` / `historyHelpers` / `rollbackHelpers` / `types` | 行为零改；脚本调度已跑过                     |
| 未开始 | **B** | `multiAgentSlice`                                                                  | 多 Agent 卡/侧链/cancel/retry 绿             |
| 未开始 | **C** | `remoteMirrorSlice`                                                                | 微信镜像路径冒烟                             |
| 未开始 | **D** | `rollbackSlice` + helpers                                                          | 预览/执行/Continue-and-Revert；只用`get()` |
| 未开始 | **E** | `spaceSessionSlice`                                                                | hydrate / 开文件夹 / CRUD                    |
| 未开始 | **F** | `streamSendSlice`（最肥，最后）                                                    | 先同文件收 handler，测绿再搬；同周禁改 SSE   |
| 未开始 | **G** | `uiChromeSlice` + 收 facade                                                        | facade ≤ ~400；单 slice ≤ ~1200            |

### 4.3 MessageList 阶段（可与 A/B 并行，勿与 F 同周）

| 进度   | Phase        | 内容                               |
| ------ | ------------ | ---------------------------------- |
| 未开始 | **M1** | `types` + `groupRounds` 纯逻辑 |
| 未开始 | **M2** | `PromptBubble`                   |
| 未开始 | **M3** | `RoundHost`                      |
| 未开始 | **M4** | 壳瘦身 ≤ ~800；根目录 re-export   |

### 4.4 建议节奏

| 周 | 做                    | 不做                 |
| -- | --------------------- | -------------------- |
| W1 | A（已完成）+ M1       | 不动 sendMessage     |
| W2 | B + C                 | 不动 rollback 方法体 |
| W3 | D + M2                | 不重构 sticky        |
| W4 | E + M3                | —                   |
| W5 | F（先同文件再搬）+ M4 | 同周禁改 SSE         |
| W6 | G + 清 tmp（可另 PR） | —                   |

### 4.5 明确不要做的（拆分专用）

1. 不要先拆成多个 Zustand store 再同步。
2. 不要 `rollbackSlice` ↔ `streamSendSlice` 顶层循环 import。
3. 不要在拆分 PR 里改 sticky / virtual 算法。
4. 不要改调用方 `useChatStore(s => …)`，除非类型逼迫。
5. 不要一次提交「拆 store + 拆 MessageList + 清 tmp」。

---

## 5. 建议并行的三件（evaluation 收口句）

| 进度   | 事项                                 |
| ------ | ------------------------------------ |
| 进行中 | 拆前端巨石（§4）                    |
| 未开始 | 归档 Scheduler（或真接上，禁止双轨） |
| 未开始 | 微信远程收成默认只读 + 微信内确认    |

若选分叉 B，另开「对弈结对 + 一仓一人」产品规格（当前均为 **未开始**）。

---

## 6. 来源对照（去重账本）

| 主题                     | 主要设计      | evaluation | 合并结果      | 进度                        |
| ------------------------ | ------------- | ---------- | ------------- | --------------------------- |
| 总判 alpha               | ✓            | ✓ 更细    | 用 evaluation | —                          |
| 冻住主循环/工具/会话     | ✓            | ✓         | 保留          | 已完成                      |
| CWD / session 隔离       | P0            | 部分已进展 | 保留          | 已完成                      |
| Bash / OS 沙箱           | 分两条        | 合成 jail  | 合成 P0       | 未开始（门禁已勾≠沙箱）    |
| Web / Notebook / Git     | missing       | 已启用     | 删 missing    | 工具已完成                  |
| MCP / CLI / LSP / slash  | P1–P2        | 补课非亮点 | 保留          | LSP 已完成；其余未开始      |
| C2 / fallback / 注释口径 | ✓            | ✓         | 合并          | 未开始                      |
| 微信 / NightShift / 回溯 | 差异 P2       | 补全       | 补全          | 回溯已完成；微信/晨报未开始 |
| 前端巨石拆除             | 仅 gui-polish | 完整 Phase | 用 §4        | 进行中（A 已完成）          |
| 分叉（对弈/一仓一人）    | —            | ✓         | 整段保留      | 未开始                      |
| 不要内置 IDE             | —            | ✓         | P0 不应做     | 已完成                      |

---

## 7. 进度原始数据（便于回写画布）

```json
{
  "verdict_optStatus": {
    "megastore": "doing",
    "clone-ide": "done"
  },
  "readiness_todo_done_true": [
    "loop", "tools-core", "session", "ui-stream", "perm-skeleton", "prompt",
    "model-client", "skill", "orchestration", "ask-plan", "usage", "tests-core",
    "cwd", "bash-policy", "subagent", "rewind", "session-cwd", "web", "lsp",
    "notebook", "git-tool"
  ],
  "readiness_todo_done_false": [
    "c2", "wechat", "gui-polish", "slash", "tool-comments", "fallback-cfg",
    "nightshift", "mcp", "cli", "os-sandbox", "model-fallback"
  ]
}
```

*进度为画布 sidecar 快照合并结果。之后若在画布改勾选/三态，以画布为准，再同步本 md。*
