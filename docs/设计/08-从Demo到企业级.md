# XEYO：从 Demo 到可用 / 企业级 / 有亮点

> 日期：2026-08-14  
> 前置：`00-总计划书` 的 Task0–5 骨架已落地；Task8（重启续聊 + 按人隔离）已落地；Task6 Java 仍是空壳。  
> 本文是产品身份与「立刻停止什么」。**带时序图、理由、按周 PR 的执行版见** [09-企业级落地计划-时序与排期.md](../%E5%AE%9E%E6%96%BD%E8%AE%A1%E5%88%92/09-%E4%BC%81%E4%B8%9A%E7%BA%A7%E8%90%BD%E5%9C%B0%E8%AE%A1%E5%88%92-%E6%97%B6%E5%BA%8F%E4%B8%8E%E6%8E%92%E6%9C%9F.md)。

---

## 0. 一句话结论

XEYO **已经不是空仓库**，主循环、核心编码工具、桌面 UI、微信双通道都在。  
它看起来像玩具，是因为产品身份仍是「迷你 Claude Code」，宽而浅；企业级也不是再抄 18 个 stub。

**下一阶段只做一件产品：**  
本机编码 Agent，微信是第一交互面，策略与审计可给别人用。

---

## 1. 现状（以仓库为准，2026-08-14）

### 已经能讲、能跑

| 层 | 现状 |
|---|---|
| 主循环 | `query_loop`：流式、工具回流、abort、max_turns、安全/不安全分区执行 |
| 真工具 | Glob / Grep / Read / Write / Edit / Bash / TodoWrite / Screenshot / SendToWeChat |
| 权限 | cwd 沙箱 + 危险路径；Registry 前置 `can_use_tool` |
| API / UI | FastAPI SSE、Stop、设置、Tauri 桌面 |
| 会话 | JSONL transcript、`hydrate_if_empty` |
| 远程 | 文件传输助手 + iLink Bot；本条消息就是从微信进来的 |

### 仍是玩具的证据

| 缺口 | 代码事实 | 用户体感 |
|---|---|---|
| 18 个脚手架工具 | `catalog.py` 的 `SCAFFOLD_TOOLS` 全是 `not_implemented` | 目录像大厂，点进去是空壳 |
| Java VT | `ToolRuntimeServer.java` / `JsonRpcServer.java` 空类 | 计划书写的核心亮点不存在 |
| 长会话会炸 | 无 compact / 无摘要 | 聊十几轮就超上下文或变蠢 |
| Bash 无门禁 | `gate.py` 把 Bash 放进 `_ALWAYS_ALLOW` | 企业场景不可给别人用 |
| 权限只有 deny | 无 UI ask、无审计落盘 | 不能讲「可治理」 |
| 费用预算未接 | `max_budget_usd` 注释「暂未使用」 | 跑飞了不知道花了多少 |
| 本地 API 过宽 | CORS `allow_origins=["*"]` | 演示级，不是交付级 |
| 文档过期 | `00` 仍写 permissions stub、Java 下一步从 task0 开始 | 自己都对不齐现状 |

### 为什么「做成 Claude 子集」赢不了

Cursor / Claude Code / Copilot 已经占满 IDE。再做一个功能更少的本地 Agent，面试能讲、产品没人每天打开。  
你们**已经有别人没有的楔子：微信远程驾驶本机 Agent**（扫码、文件助手、截图回传、把文件打回微信）。这才是差异，不该当副作用。

---

## 2. 产品身份（必须写死，否则继续发散）

```text
XEYO = 跑在你电脑上的编码 Agent
         + 微信是第一等公民的交互面
         + 每次副作用可拒绝、可审计
```

**不是：** 开源 Claude Code、MCP 全家桶、多租户 SaaS、计费中台。

**企业级在这里的含义（本地产品）：**

1. 别人的机器上能连续用一周，不丢会话、不胡写盘  
2. 危险操作有策略，事后能查出「谁、何时、调了什么」  
3. 挂了能恢复，密钥不进 git，远程通道有 token  
4. 一个工作流每天都比不用它更快  

不是：微服务、K8s、25 个工具、Spring Cloud。

---

## 3. 立刻停止

- 把 `SCAFFOLD_TOOLS` 里的 Agent / MCP / LSP / Plan / Task* 再实现一层皮  
- 并行开「Java VT + 企业权限 + 微信打磨 + 新工具」四条线  
- 继续以「对齐 Claude 文件结构」当进度  
- 在 README 写「核心亮点 Java 虚拟线程」却不跑通一条 Read  

脚手架工具保持冻结，直到 L1 可用清单打勾。

---

## 4. 三层升级（按顺序，未完成不进入下一层）

### L1 — 真正可用（约 2～3 周）

目标：自己愿意每天用；杀进程、换网络、超长对话都不丢人。

| # | 做什么 | 落点 | 完成定义 |
|---|---|---|---|
| 1.1 | 上下文 compact | `engine/` 新模块，query_loop 超阈值摘要旧 tool_result | 80+ 轮或超 N 字符后仍能续聊，有单测 |
| 1.2 | 重启 resume 闭环 | `session_pool` 按 session_id 读 JSONL → `hydrate_if_empty` | 杀 `py -m server` 再启，同一会话历史还在 |
| 1.3 | Bash 最小黑名单 | `permissions/gate.py` 移出 `_ALWAYS_ALLOW`；拒绝 `rm -rf`、格式化、改系统目录 | 越权命令返回 Permission denied，有单测 |
| 1.4 | 预算真接上 | `BudgetTracker` 记 token/USD；超限 `StoppedEvent` | 设置里能看到本轮消耗；超限可演示 |
| 1.5 | 远程通道稳态 | iLink / 文件助手：重连、去重、失败重投、心跳 | 微信断 1 分钟再发，不丢、不双回 |
| 1.6 | 错误可读 | 模型 401/429、rg 缺失、微信掉线 → UI + 微信同一句话 | 不出现栈轨迹砸到用户脸上 |

**L1 演示剧本（每天用）：**

1. 微信说「看一下当前屏幕」→ Screenshot → 图回到微信  
2. 「把 `query_loop.py` 里 abort 那段改稳健一点」→ Glob/Read/Edit → 回微信摘要  
3. 关掉后端再开 → 同一会话能续  
4. 故意让它 `rm` 工作区外路径 → 被拒，会话还活着  

### L2 — 企业级感（约 3～4 周，L1 之后）

目标：可以装到同事电脑 / 给面试官讲「可治理」，不是「我本地能跑」。

| # | 做什么 | 落点 | 完成定义 |
|---|---|---|---|
| 2.1 | 权限三态 allow / deny / **ask** | gate + UI 弹一次 + 微信回 `允许/拒绝` | 写文件、Bash 危险命令会停下来问 |
| 2.2 | 审计日志 | 每次 tool_call JSONL：时间、session、工具、路径、裁决、耗时 | `~/.xeyo/audit/` 可 grep；敏感字段脱敏 |
| 2.3 | 工作区策略文件 | 仓库根 `.xeyo-policy.json`（允许路径、Bash 模式、远程白名单） | 换仓库策略跟着走，不改代码 |
| 2.4 | 密钥与远程鉴权 | API Key 只存本机；远程 token 强制；CORS 收口 localhost | 无 token 的 `/api/remote` 全 401 |
| 2.5 | 工具调用可观测 | 每轮：模型时延、工具时延、token、失败率 | 设置页或 `/health` 扩展能看到 |
| 2.6 | 安装与崩溃 | 一键启动失败原因人话；Tauri 崩溃不丢 transcript | 别人按 README 10 分钟能聊上 |

**L2 对企业客户的一句话：**  
Agent 能动你的文件和终端，但默认最小权限，每次副作用留审计，策略跟仓库走。

### L3 — 唯一亮点（只选一个做深）

三个里 **只选 A（推荐）**。B 适合秋招口述补强，C 适合卖安全。不要三个都做。

#### 选项 A（推荐）：微信原生 Agent OS

已经有 iLink + 文件助手 + Screenshot + SendToWeChat，这是市场上 Cursor 不做的事。

做深到：

- 手机下达任务 → 本机改代码 → 摘要+截图+补丁回微信  
- 入站队列、会话隔离、图片入模型、文件回传可靠  
- 「允许这次 Write」可以在微信里回复  

**可讲的差异：** 不是又一个 IDE 插件，是 **人在微信、Agent 在你的电脑**。

#### 选项 B：Java 21 虚拟线程 ToolRuntime

`java/` 仍是空壳。只有在 L1 稳了、且你要打 Java 岗时再开。

最小可讲集：

- Python 编排，Read/Bash 走 JSON-RPC  
- 虚拟线程执行，日志打印 `Thread.currentThread().isVirtual()`  
- 权限仍在 Python gate，Java 只跑已放行的调用  

详见 `docs/task6-Java工具运行时.md`。未选中则 README **不要再写这是核心亮点**。

#### 选项 C：策略即代码 + 审计

适合对安全/平台岗。把 2.1–2.3 做成可演示的产品：策略文件、ask、审计查询 UI。编码能力保持现有工具即可。

---

## 5. 建议排期（90 天）

```text
W1–W2   L1.1 compact + L1.2 resume 真闭环 + L1.3 Bash 黑名单
W3      L1.5 微信稳态 + L1.4 预算 + L1.6 错误文案
W4      冻结功能，自己连续用 5 个工作日，只修 P0
W5–W7   L2 ask + 审计 + policy 文件 + CORS/token
W8–W10  只打磨选项 A（微信工作流），录屏、README、演示剧本
W11–12  若秋招需要：选项 B 的最小 VT 演示（可选，不阻塞发布）
```

---

## 6. 本周就可以改的代码（按优先级）

1. `permissions/gate.py`：Bash / Screenshot 移出 `_ALWAYS_ALLOW`；Bash 先做命令黑名单。  
2. `engine/query_loop.py`：在 `store` 超阈值时压缩旧 `tool_result`（保留最近 2～3 轮全文）。  
3. `server/session_pool.py`：创建引擎时若磁盘有 transcript 则 hydrate。  
4. `server/app.py`：CORS 改为 localhost；远程路由继续走 `channels/auth.py`。  
5. 新建 `python/audit/log.py`：Registry.run 前后写一行 JSONL。  
6. 删除或隐藏 README「演示向」口吻；亮点改写成微信远程 + 沙箱，Java 标成可选。

未做完 1–3 之前，不要启用 WebSearch / MCP / LSP。

---

## 7. 完成时对外怎么讲（30 秒）

> XEYO 是本机编码 Agent：模型在云上，文件和终端在你电脑上。  
> 主循环是标准的模型↔工具，但交互面是桌面和微信同一套会话。  
> 工作区外写盘拒绝；危险命令要确认；每次工具调用有审计。  
> 不是要替代 Cursor，而是让你离开工位时还能安全地让 Agent 干活。

局限也主动讲：单机、非多租户、Java VT 若未做就说「编排与运行时可拆，下一步才是 JVM」。

---

## 8. 检查单

**可用**

- [ ] 连续 5 天自己用微信或桌面改本仓库代码  
- [ ] 重启后端会话还在  
- [ ] 长对话不因为历史爆炸而 400  
- [ ] 越界路径 / 危险 Bash 可演示拒绝  

**企业级**

- [ ] Write/Bash 能 ask  
- [ ] 审计日志可打开给人看  
- [ ] `.xeyo-policy.json` 换仓库即生效  
- [ ] 无远程 token 不能驱动 Agent  

**亮点**

- [ ] 一条微信消息走完：理解 → 改文件 → 截图或 diff 回到微信  
- [ ] 上述路径有测试，不是「演示时灵」  
- [ ] README 只宣传已存在的能力  

---

**下一步：** Task8 已落地。按 [09-企业级落地计划-时序与排期.md](../%E5%AE%9E%E6%96%BD%E8%AE%A1%E5%88%92/09-%E4%BC%81%E4%B8%9A%E7%BA%A7%E8%90%BD%E5%9C%B0%E8%AE%A1%E5%88%92-%E6%97%B6%E5%BA%8F%E4%B8%8E%E6%8E%92%E6%9C%9F.md) 开 **PR-C1 compact**。不要先开 Java，也不要先实现 MCP。

---

## 9. 对着代码讲（比 §4 更具体）

下面每条都是：**现在实际跑什么 → 缺哪一行 → 改完用户能看到什么 → 怎么验收**。

### 9.0 你发一条微信时，代码怎么走

```text
微信 iLink
  → channels/ilink/service.py  _from_user_id(msg)     # 其实读到了你的 userId
  → _begin_inbound(..., session_id="ilink:default")    # 丢掉了 userId
  → ILinkChannel.handle_inbound
  → channels/runner.py  run_final_only
  → SessionPool.get_or_create("ilink:default")
  → QueryEngine.submit_message
  → engine/query_loop.py  while:
        model.stream( 全部历史 )
        run_tools_partitioned
          → ToolRegistry.run
            → permissions/gate.py can_use_tool
            → Read/Edit/Bash.execute
  → 最终文本
  → ILinkChannel.send_final → 微信
```

桌面路径只是把入口换成 `POST /v1/chat/completions`（`server/app.py`），后面同一套 engine。
**微信路径不带历史 body**，全靠进程内存里的 `SessionPool._engines`。所以「杀后端丢记忆」在微信上比桌面更惨：桌面至少还会把 IndexedDB 里的 prior 塞回请求。

---

### 缺口 1 — 会话 ID 对不上，resume 是假的（L1 第一刀）

> **执行计划：** [task8-远程微信-重启续聊与按人隔离.md](../%E4%BB%BB%E5%8A%A1%E4%B9%A6/task8-%E8%BF%9C%E7%A8%8B%E5%BE%AE%E4%BF%A1-%E9%87%8D%E5%90%AF%E7%BB%AD%E8%81%8A%E4%B8%8E%E6%8C%89%E4%BA%BA%E9%9A%94%E7%A6%BB.md) 工作流 A

**现在：**

| 层 | ID 从哪来 | 文件 |
|---|---|---|
| HTTP / 微信 | `ilink:default` / `filehelper:default` / 前端 `X-Session-Id` | `app.py`；`ilink/service.py` `_begin_inbound` |
| 引擎内部 | `uuid4().hex` 随机 | `session/state.py` |
| 写盘路径 | `~/.xeyo/sessions/<随机uuid>.jsonl` | `record_transcript` 用的是引擎内部 ID |

`QueryEngine.__init__` 构造 `SessionState` 时**没有**把 pool 的 `session_id` 传进去（只传了 cwd 和 budget）。
`get_or_create` 重启后也**从不**调用 `load_transcript()`。磁盘上即使有 JSONL，也找不到对应文件。

**要改的 4 个点：**

1. `QueryEngineConfig` 增加 `session_id: str`
2. `SessionState(..., session_id=pool传入的id)`
3. `SessionPool.get_or_create`：内存没有消息时 `load_transcript(transcript_path(session_id))` → 转成 `Message` → `initial_messages`
4. `load_transcript` 的 dict → `Message` 写一个 `session/hydrate.py`（role/content/id/tool_call_id）

**改完体感：** 微信聊 3 句 → 关 `py -m server` → 再开 → 再说「我上一句说了什么」能答上来。

**验收：**

```powershell
cd python
py -3.11 -m pytest tests/test_record_transcript.py tests/test_history_continuity.py -q
# 再加：tests/test_resume_from_disk.py
# 写 2 条消息到 tmp jsonl → 新 SessionPool.get_or_create(同一id) → len(messages)==2
```

手测：桌面同一会话刷新；微信同一 Bot 重启后端。

---

### 缺口 2 — 历史原样塞进模型，长对话必炸（L1 compact）

**现在：** `query_loop` 每一轮把 `store.as_api_messages()` **全文**交给模型。Grep/Read 的整段输出都留着。
`BudgetTracker.max_chars` 只在工具结果累加后发出 `StoppedEvent(reason="budget")`——是**掐死**，不是压缩。
`max_budget_usd` 在 `submit_message` 里被丢掉，从未计费。

另外 `as_api_messages` 把 `role=tool` 改成 `role=user`，模型看不到标准 tool_result。这是协议级玩具。

**要改：** 新建 `engine/compact.py`。最近 6 条全文；更早的 tool_result 换成 `[compacted] Grep: 12 matches`。总字符仍超 80_000 再摘要更早的 user/assistant。

钩子：`query_loop` 在 `prompt.build` **之前**调用。**只压缩送模型的副本，JSONL 仍留全文。**

**改完体感：** 连续 15 次「读这个文件」不会 400；模型仍记得「刚才在改 gate.py」。

**验收：** 构造 40 条带 20KB tool_result 的 store，compact 后送模型总长 < 80_000，且最后 3 轮 Read 原文还在。

---

### 缺口 3 — 微信所有人共用一个大脑

> **执行计划：** [task8-远程微信-重启续聊与按人隔离.md](../%E4%BB%BB%E5%8A%A1%E4%B9%A6/task8-%E8%BF%9C%E7%A8%8B%E5%BE%AE%E4%BF%A1-%E9%87%8D%E5%90%AF%E7%BB%AD%E8%81%8A%E4%B8%8E%E6%8C%89%E4%BA%BA%E9%9A%94%E7%A6%BB.md) 工作流 B

**现在：** `ilink/service.py` `_begin_inbound` 写死 `session_id="ilink:default"`、`sender_id="ilink"`。
`_from_user_id(msg)` 已经能读到 `o9cq805…`，但没用它当 session。
结果：A 说「改 README」，B 接着说「继续」，Agent 会接着改 A 的任务。

**要改：** `session_id = f"ilink:{from_user_id or 'default'}"`。busy / inbound_queue 按 session 分片，不要全局一个队列混排。

**改完体感：** 两个微信号各聊各的。你这条消息会变成会话 `ilink:o9cq805…`。

**验收：** mock 两个 `from_user_id`，断言 `enqueue` 的 session_id 不同。

---

### 缺口 4 — 权限三态是假的（L2，L1 之后）

枚举里有 ASK，但 `enforce_decision` 把 ASK 降成 DENY（注释写明：无 UI 确认）。
读 `.git/config` 用户看到的是 Permission denied，不是「要不要允许」。
Bash 黑名单只拦伤机命令；普通删文件、`git push` 仍直接跑。

**L2 协议：** `can_use_tool` 对 Write / 非黑名单 Bash 返回 ASK → Registry 先不执行，发 `PermissionAskEvent` → 桌面两个按钮或微信回「允许/拒绝」→ 通过后才 `execute` → 审计一行。

---

### 缺口 5 — 审计 / 策略文件还不存在

`python/audit/log.py`：每次工具调用写 `~/.xeyo/audit/YYYY-MM-DD.jsonl`（session、工具、路径、裁决、耗时；密钥打码）。
仓库根 `.xeyo-policy.json`：允许路径、Bash 模式、远程是否强制 token。`gate.py` 读这份，而不是写死 `_ALWAYS_ALLOW`。

---

### 9.1 建议的 3 个连续 PR（不要合成一个大 PR）

| PR | 标题 | 文件 | 不要动 |
|---|---|---|---|
| 1 | resume：pool session_id = 磁盘文件名 | `state.py` `query_engine.py` `session_pool.py` 新 `hydrate.py` + 测试 | UI、Java、新工具 |
| 2 | compact 送模型副本 | 新 `engine/compact.py`，钩 `query_loop.py` + 测试 | 真删 JSONL |
| 3 | iLink 按 userId 分会话 | `ilink/service.py` `_begin_inbound`、queue 按 sid 分片 | 文件助手协议 |

做完这 3 个，再用 5 天自己微信改本仓库。仍天天炸再开 L2。

---

### 9.2 不要做的（再具体一点）

| 想法 | 为什么现在做是错的 |
|---|---|
| 实现 WebSearch / MCP / LSP | `tools/stub.py` 仍是 not_implemented；主路径还不稳 |
| 填 `JsonRpcServer.java` | 空类；面试能吹，用户无感；排在 PR1–3 之后 |
| 把 Bash 做成完整 AST 沙箱 | 黑名单够 L1；AST 是另一个月 |
| 给 18 个脚手架补 schema | 模型会去调，然后报 not implemented，体验更差 |
