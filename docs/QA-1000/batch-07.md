# XEYO 面试题库 · 第 7 批（B07）

> 卷名：**权限与沙箱**（Agent 后端开发岗 · 三级能力域）
> 题号范围：**XEYO-QA-0301 – XEYO-QA-0350**
> 考查范围：三态裁决（allow/ask/deny）· 路径狱与 symlink 解析 · 密钥/危险路径/受保护元数据三道硬拦 · 审批模式活状态与单向性（收紧即时、放宽延后）· 权限 preset · 挂起与 TTL · write_scope（子 agent 写范围）· 仓库策略文件与 fail-closed · Bash 写判定与规则引擎 · 授权存储与指纹
> 难度配比：简单 12 / 中等 16 / 困难 15 / 超压 7
> 事实基线（本批实际打开读过的文件与实测行数）：
> `filesystem.py`(435, **全文精读**) · `policy.py`(1700, 定义面全量 + 52–130 / 386–445 精读) · `runtime_mode.py`(154, **全文精读**) · `runtime_preset.py`(62, **全文精读**) · `presets.py`(18, **全文精读**) · `write_scope.py`(157, **全文精读**) · `pending_ttl.py`(53, **全文精读**) · `gate.py`(71, **全文精读**) · `workspace_policy.py`(257, 1–90 精读 + 定义面) · `store.py`(508, 定义面) · `bash_policy.py`(654, 定义面) · `ask_store.py`(139, 定义面) · `__init__.py`(26)
> **边界声明**：`permissions` 在 **B04/B05/B06** 已从「工具如何调用它」的角度涉及（工具内 `check_permissions` 调用点、Bash 只读白名单的消费），本卷只出**裁决本体**（三态语义、优先级、边界判定、模式与 preset 活状态、挂起生命周期、授权存储）；`extension` 层的 MCP 指纹与停用语义归 **B16**（本卷只从 `PolicyDecision.mcp_target` 这一处接口涉及）；`server` 侧 `/v1/permission/resolve`、`/v1/sessions/{id}/runtime-mode|runtime-preset` 路由归 **B14**（本卷只讲 store 的语义与优先级）；rewind/写路径三层防护（分片锁 / 租约 / base hash）归 **B03/B11**。
> **行号口径**：`policy.py`(1700) 与 `bash_policy.py`(654) 采用「先 Grep 抽定义行号 → 再按 offset/limit 精读」；写题前复核的锚点见自检表。

---

## 本卷题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0301 | 简单 | 概念确认 | 三态裁决的定义与消费者 | `filesystem.py:32-35` |
| 0302 | 简单 | 概念确认 | 审批模式四档与严格度 | `policy.py:75` + `runtime_mode.py:26` |
| 0303 | 简单 | 概念确认 | 三个 Agent 模式与工具白名单 | `policy.py:120-125,386-412` |
| 0304 | 简单 | 概念确认 | 三个权限 preset | `presets.py:11-18` |
| 0305 | 简单 | 机制解释 | 挂起 TTL 三档与提醒点 | `pending_ttl.py:24-26` |
| 0306 | 简单 | 概念确认 | 密钥文件清单 | `filesystem.py:68-110` |
| 0307 | 简单 | 概念确认 | 受保护元数据三目录 | `filesystem.py:309-310` |
| 0308 | 简单 | 机制解释 | 三份统一的权限文案 | `pending_ttl.py:31-45` |
| 0309 | 简单 | 概念确认 | Bash 模式四值 | `workspace_policy.py:23` |
| 0310 | 简单 | 机制解释 | `enforce_decision` 的 ASK→DENY | `filesystem.py:356-367` |
| 0311 | 简单 | 概念确认 | `preapproved` 的用途 | `filesystem.py:12-29` |
| 0312 | 简单 | 机制解释 | gate 兼容层的存在理由 | `gate.py:1-71` |
| 0313 | 中等 | 机制解释 | `policy.path_in_allowed_working_path` 的双 realpath | `filesystem.py:127-154` |
| 0314 | 中等 | 机制解释 | 读裁决的四层顺序 | `filesystem.py:261-284` |
| 0315 | 中等 | 机制解释 | 写裁决 vs 读裁决的差异 | `filesystem.py:287-303` |
| 0316 | 中等 | 对比辨析 | `.env` 变体与模板后缀 | `filesystem.py:157-175` |
| 0317 | 中等 | 对比辨析 | `_SECRET_DIRECTORIES` 为何不含 `.git` | `filesystem.py:98-108,178-188` |
| 0318 | 中等 | 机制解释 | `protected_metadata_reason` 的组件级扫描 | `filesystem.py:323-353` |
| 0319 | 中等 | 机制解释 | `readable_extra_roots` 放宽了什么 | `filesystem.py:191-244` |
| 0320 | 中等 | 机制解释 | 单向性：收紧即时、放宽延后 | `runtime_mode.py:9-13,69-105` |
| 0321 | 中等 | 系统设计 | preset 优先级链与 pin | `runtime_preset.py:1-13,29-44` |
| 0322 | 中等 | 机制解释 | `normalize_worker_scope` 的三类收束 | `write_scope.py:46-103` |
| 0323 | 中等 | 机制解释 | `write_scope` 三态语义 | `write_scope.py:1-6,106-157` |
| 0324 | 中等 | 机制解释 | 挂起审计配对与 outcome 文案 | `pending_ttl.py:14-45` |
| 0325 | 中等 | 系统设计 | 仓库策略的四种开关面 | `workspace_policy.py:23-29,32-56` |
| 0326 | 中等 | 机制解释 | 策略文件坏文件的 fail-closed | `workspace_policy.py:1-11,49-55` |
| 0327 | 中等 | 机制解释 | `readonly_gate` 的两个来源 | `policy.py:417-434` |
| 0328 | 中等 | 对比辨析 | Bash 写判定 vs 危险路径判定 | `policy.py:765-806` + `bash_policy.py` |
| 0329 | 困难 | 安全拷问 | realpath 与时序：symlink 逃逸面 | `filesystem.py:127-154,261-303` |
| 0330 | 困难 | 安全拷问 | 归一化不一致导致的判定碰撞 | `filesystem.py:113-124,323-353` |
| 0331 | 困难 | 系统设计 | 单向性的两条实现路径 | `runtime_mode.py:41-47,69-105` + `workspace_policy.py:6-10` |
| 0332 | 困难 | 权衡取舍 | TTL 三档的取舍与「不超时」风险 | `pending_ttl.py:1-13,47-53` |
| 0333 | 困难 | 场景设计 | markdown 快照广播为什么不能当权限 | `runtime_mode.py:14-18,107-154` |
| 0334 | 困难 | 安全拷问 | 盘符根/仓根 scope 为什么必须拒 | `write_scope.py:63-103` |
| 0335 | 困难 | 对比辨析 | 读放宽（extra_roots）与写不能放宽 | `filesystem.py:191-199,287-303` |
| 0336 | 困难 | 代码阅读 | `_max_outside_allowed` 的延迟导入 | `filesystem.py:247-258` |
| 0337 | 困难 | 系统设计 | 授权存储的指纹与作用域 | `store.py:1-60`（定义面） |
| 0338 | 困难 | 安全拷问 | 「已批准」状态如何不被穿越 | `filesystem.py:396-435` + `policy.py` |
| 0339 | 困难 | 权衡取舍 | 工具内 ASK→DENY 与 registry 挂起的分工 | `filesystem.py:396-416` + `gate.py:13-18` |
| 0340 | 困难 | 场景设计 | 子 agent 与主会话的权限继承 | `write_scope.py:15-29,148-157` |
| 0341 | 困难 | 安全拷问 | `XEYO_ALLOW_PROTECTED_METADATA` 的放宽面 | `filesystem.py:318-321` |
| 0342 | 困难 | 故障排查 | 权限与工作区路径解析不一致 | `filesystem.py:47-64,370-376` |
| 0343 | 困难 | 权衡取舍 | 三态里 ASK 的语义债 | `filesystem.py:356-367` + `policy.py:63` |
| 0344 | 超压 | 故障排查 | 挂起与并发的竞态面 | `store.py` + `pending_ttl.py` + `runtime_mode.py` |
| 0345 | 超压 | 安全拷问 | 权限模型越权面总账 | 全卷 |
| 0346 | 超压 | 故障排查 | 加密路径为什么仍然「拒绝」未必安全 | `filesystem.py:157-188` |
| 0347 | 超压 | 场景设计 | 多 agent 并发的文件竞争与权限 | `write_scope.py` + `store.py` + B03 写路径 |
| 0348 | 超压 | 故障排查 | 「显示已批准但实际拒绝」的不一致 | `filesystem.py:17-29` + `store.py` |
| 0349 | 超压 | 安全拷问 | Bash 规则引擎的绕过面 | `bash_policy.py`(654) + `policy.py:742-806` |
| 0350 | 超压 | 系统设计 | 一套面向 Agent 的权限模型该怎么设计 | 全卷 |

---

### XEYO-QA-0301 权限裁决为什么是三种结果而不是两种

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 裁决枚举 | 三态定义与去向 | 简单 | 概念确认 | `python/permissions/filesystem.py:32-35` |

**面试官提问**
给 Agent 设计权限门禁时，你会在允许和拒绝之外再引入第三种结果吗？为什么？

**参考答案要点**
`PermissionDecision` 是**三态**（`:32-35`）：

```python
class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
```

三态存在的理由是**「需要用户决定」与「规则允许/规则禁止」是不同结果**：

| 结果 | 含义 | 去向 |
|---|---|---|
| ALLOW | 规则明确放行 | 直接执行 |
| **ASK** | 规则说不确定，**要问人** | 挂起 → 推给用户 → 等回执（超时按拒绝） |
| DENY | 规则明确禁止 | 直接拒绝，**不给用户「批准一下」的机会** |

若只有两态，两种折叠都有害：折叠进 ALLOW = 静默放行危险操作；折叠进 DENY = 危险操作**永远无法被用户批准**（而「写工作区外的文件」在用户明确同意时应当允许）。

配套证据：`pending_ttl.py` 为 ASK 定义了**挂起文案**（rejected / cancelled / unavailable 三条），说明 ASK 是一条**有独立生命周期的状态**，不是「延迟的 DENY」。

**评分要点**
- **及格**：说出三态名字，并知道 ASK 要有人来批。
- **良好**：能说明 ASK 的**独立生命周期**（挂起 → 回执/超时）。
- **优秀**：论证「为什么不能只有两态」——分别说出折叠到 ALLOW（静默放行）与折叠到 DENY（永不可批）两种具体损害。

**典型弱答**（听到这些就得分不高）
- 「三态就是多一个提示」（忽略它是独立状态机）；
- 把 ASK 当「软拒绝」（那等于两态）；
- 说不出 ASK 超时后怎么处理。

**追问**
ASK 超时之后应该按允许还是按拒绝？为什么？（→ 0305/0332：默认拒绝，且文案要说明「因超时按拒绝」而非「用户拒绝」）

---

### XEYO-QA-0302 审批模式的四档与严格度排序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | policy 审批模式 | 四档与严格度 | 简单 | 概念确认 | `policy.py:75,79` + `runtime_mode.py:26,41-47` |

**面试官提问**
审批模式（用户对「要不要每次问」的选择）有哪几档？如果要比较两个模式谁更严，你怎么编码这件事？

**参考答案要点**
`_PERMISSION_MODES = ("always", "risk", "never", "allow")`（`policy.py:75`）——**四档**：

| 模式 | 语义 | 严格度（`runtime_mode._STRICTNESS`，`:26`） |
|---|---|---|
| `always` | 每次写都问 | **3** |
| `risk` | 仅风险操作问（默认档） | **2** |
| `never` | 工作区内常规写免确认 | **1** |
| `allow` | 与 `never` 同义 | 归一到 `never`（`normalize_mode`，`:29-34`） |

`_AUTO_WRITE_MODES = frozenset({"never", "allow"})`（`policy.py:79`）——**「免确认」由这两个值共同表示**。

**「谁更严」被编码成整数**（`runtime_mode.py:26`）+ 比较函数（`:41-47`）：

```python
_STRICTNESS = {"always": 3, "risk": 2, "never": 1}

def stricter(a, b):
    if a is None: return b
    if b is None: return a
    return a if strictness(a) >= strictness(b) else b
```

`stricter()` 是全项目「权限单向性」的实现基础：**任意两处给出的模式都能求出更严者**。★ 注意 `strictness()` 对未知/空返回 **0**（`_STRICTNESS.get(mode or "", 0)`）——非法值比 `never` 还「松」，所以它**永远不会赢过**任何合法值（方向安全）。

**评分要点**
- **及格**：说出四档与默认档（`risk`）。
- **良好**：说出 `allow` 被归一到 `never`（不是第五档）。
- **优秀**：指出严格度被编码成**可比较整数**，并说明它解决「两处配置冲突取谁」的问题（取更严）；能指出 `strictness` 对未知值返回 0 的方向安全设计。

**典型弱答**
- 把 `allow` 当成「比 never 更松的第五档」；
- 无法回答「两处配置冲突取谁」；
- 用字符串比较来做严格度（字典序没有权限语义）。

**追问**
如果将来新增一档「只问删除类操作」，你会插在哪个严格度之间？插错会有什么后果？

---

### XEYO-QA-0303 Agent 模式与工具可见性

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | policy Agent 模式 | 三模式与白名单 | 简单 | 概念确认 | `policy.py:76,120-125,386-412` |

**面试官提问**
除了「问不问」，还有一个维度是「Agent 处于什么工作模式」。请说明这个维度有哪些取值，以及它怎么影响**模型能看到哪些工具**。

**参考答案要点**
`_AGENT_MODES = ("agent", "plan", "ask")`（`policy.py:76`），工具白名单表（`:120-125`）：

```python
PLAN_ONLY_ALLOW = frozenset({"ExitPlanMode"})
_MODE_TOOL_ALLOW = {
	"agent": None,                                   # None = 不限制
	"ask":   READONLY_ALLOW | READONLY_ASK_ALLOW,    # 只读类
	"plan":  READONLY_ALLOW | READONLY_ASK_ALLOW | PLAN_ONLY_ALLOW,
}
```

| 模式 | 工具面 |
|---|---|
| `agent` | `None` = **不按模式限制**（正常干活） |
| `ask` | 只读白名单并集（**不能改东西**） |
| `plan` | 只读白名单 + `ExitPlanMode`（**只能读 + 提交计划**） |

判定函数 `tool_allowed_in_mode(name, tool=...)`（`:386-412`）三处细节：

1. **优先读工具实例的 `is_read_only()`**（`tool_flag(tool, "is_read_only")`），无实例时回退名字表——判定与工具实现**同源**，避免两张表漂移；
2. `READONLY_ASK_ALLOW` 里的工具**在任何模式都放行**（`:404-405`）；
3. `PLAN_ONLY_ALLOW` 只在 `plan` 模式放行（`:406-407`）。

★ 另有一个**独立于 Agent 模式的请求级开关**：`side_mode()`（侧聊）——判定在函数最前面（`:394-399`），且**比 Agent 模式更严**：只允许真只读工具。

**评分要点**
- **及格**：说出三模式，知道 `plan`/`ask` 受限。
- **良好**：说出白名单是**并集表**，且 `plan` 比 `ask` 多一个 `ExitPlanMode`。
- **优秀**：指出「优先读工具实例的 `is_read_only()`」这一设计——**把权限判定绑到实现而不是维护第二张名字表**；并指出侧聊是请求级开关、优先于 Agent 模式。

**典型弱答**
- 把 `ask` 模式当成「每次都问」（它是 **Agent 工作模式**，与审批模式无关）；
- 答不出 `ExitPlanMode` 是模式特例；
- 忽略侧聊这一层。

**追问**
「按名字表」与「按工具实例声明」两种判定方式，哪一种更容易出现「表与实现不一致」的漏洞？为什么？

---

### XEYO-QA-0304 权限 preset 的三档与默认

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | presets 会话档位 | 三档与默认 | 简单 | 概念确认 | `python/permissions/presets.py:1-18` |

**面试官提问**
你会不会把「一堆权限开关」打包成几个预设档位给用户选？请说明档位设计与默认值，以及最高档到底放宽了什么。

**参考答案要点**
`presets.py` 仅 18 行（`:11-12`）：

```python
PERMISSION_PRESETS = frozenset({"readonly", "workspace-write", "full"})
DEFAULT_PRESET = "workspace-write"
```

| 档位 | 语义 |
|---|---|
| `readonly` | 只放只读白名单（等价侧聊只读语义） |
| **`workspace-write`** | **默认**：工作区内可写，按审批模式决定问不问 |
| `full` | 只放宽「确认频率」，**不触碰** deny 黑名单 / 密钥 / 受保护元数据 / worker 沙箱 |

**★ `full` 的边界**（模块 docstring `:1-7`）：

```
- preset = permission_mode + 只读门禁的组合语义（见 policy.session_permission_profile）。
- **会话创建时 pin**（SessionPool 首建写入，之后请求不得改写）→ 切换 preset 只影响新会话。
- 单向收紧红线不变：readonly 收紧到只读白名单；full 只放宽「确认频率」，
  不触碰 deny 黑名单 / 密钥 / `.git/.xeyo/.agents` 硬保护 / worker 沙箱。
```

即：**`full` 不等于「关闭权限」**——它放宽的是**询问频率**，硬拦截在任何 preset 下都生效。

**归一化**（`:15-18`）：未知/缺省值回退 `workspace-write`。

**评分要点**
- **及格**：说出三档与默认 `workspace-write`。
- **良好**：说出 `readonly` 是只读白名单、`full` 只放宽询问频率。
- **优秀**：主动指出**「full 不等于关闭权限」**这条红线并列举仍受限的维度（密钥 / 受保护元数据 / worker 沙箱 / deny 黑名单）；进一步指出「会话创建时 pin」后来被 `RuntimePresetStore` 以「用户显式切换」补齐（0321）。

**典型弱答**
- 把 `full` 理解成「关闭所有权限检查」；
- 认为 preset 可随意在请求里改（历史上被 pin 住）；
- 不知道未知值会回退默认。

**追问**
`normalize_preset` 把**非法值静默回退**成 `workspace-write`（一个**可写**档位）。这个方向安全吗？如果用户本意是打 `readonly` 打错了会怎样？（→ 0321 的「必须用原始名校验」正是为此）

---

### XEYO-QA-0305 权限挂起的超时与提醒

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | pending_ttl 挂起生命周期 | TTL 三档 | 简单 | 机制解释 | `python/permissions/pending_ttl.py:24-26,47-53` |

**面试官提问**
一次操作需要用户批准，而用户没在看屏幕。这个挂起请求应该永远等着吗？请给出你的超时设计。

**参考答案要点**
`pending_ttl.py:24-26`（原文）：

```python
PENDING_PANEL_TTL_SECONDS = 180.0
PENDING_DANGER_TTL_SECONDS = 60.0
PENDING_REMINDER_BEFORE_S = 30.0
```

| 档 | TTL | 适用 |
|---|---|---|
| 普通权限确认 | **180 s** | 一般写操作等 |
| **危险操作** | **60 s** | `reason`/`matched_rule` 命中 `danger` / `secret` / `protected` |
| **交互式提问**（AskUserQuestion） | **不超时**（`None`） | 由用户显式关闭结束 |
| 到期前 | **提前 30 s 提醒**（GUI 倒计时高亮） | — |

分档判定（`ttl_for_request`，`:47-53`）：

```python
def ttl_for_request(*, reason="", matched_rule="", tool_name="") -> float | None:
    blob = f"{reason} {matched_rule}".lower()
    if any(k in blob for k in _DANGER_MARKERS):
        return PENDING_DANGER_TTL_SECONDS
    return PENDING_PANEL_TTL_SECONDS
```

★ **危险操作 TTL 更短**（60 < 180）的取向要说明：危险操作更不该长期悬着——一个悬着的「删除工作区外文件」批准窗口本身就是风险（用户回来可能习惯性点同意）；更短也更容易落到默认拒绝，即**方向安全**。

★ **唯一不超时的是 `AskUserQuestion`**：它是「问信息」而非「求授权」，用户可能需要时间查证；而权限批准有明确的默认答案（拒绝）。

**评分要点**
- **及格**：说出有超时与默认秒数。
- **良好**：说出**分档**（危险更短）与**提前提醒**。
- **优秀**：解释「危险操作 TTL 更短」的双重理由（悬着的危险授权窗口本身是风险 + 更快落到默认拒绝）；并指出 `AskUserQuestion` 不超时的原因（问信息 vs 求授权，默认答案不同）。

**典型弱答**
- 单一 TTL 覆盖所有请求；
- 让权限挂起永不超时（用户离开后回合永久卡死）；
- 以为超时 = 用户拒绝（文案上是 `unavailable`，见 0308）。

**追问**
`ttl_for_request` 判危险靠 `reason`/`matched_rule` 里的**关键字**。这种「用文案判风险」的做法有什么脆弱之处？

---

### XEYO-QA-0306 密钥与凭据路径的清单

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 密钥判定 | 文件名/后缀/目录 | 简单 | 概念确认 | `filesystem.py:68-110,157-175` |

**面试官提问**
Agent 会读文件。请列出你认为**必须硬拦**的凭据类路径（文件名、后缀、目录三类），并说明匹配方式。

**参考答案要点**
三类清单（`filesystem.py:68-110`）：

**① 高危文件名**（`DANGEROUS_FILES`，14 条）：

```python
	".env", ".env.local", ".env.production",
	".gitconfig", ".git-credentials", ".netrc", ".npmrc", ".pypirc",
	"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
	"credentials.json", "credentials",
```

**② 高危后缀**：`DANGEROUS_SUFFIXES = (".pem", ".key", ".p12", ".pfx")`（`:110`）

**③ 凭据目录**（路径任一组件命中即拦）：`_SECRET_DIRECTORIES = frozenset({".ssh", ".kube", ".gnupg", ".aws"})`（`:101-108`）

另有 `DANGEROUS_DIRECTORIES = {".git", ".ssh", ".kube", ".gnupg", ".aws"}`（`:88-96`）——**比 `_SECRET_DIRECTORIES` 多一个 `.git`**（差异见 0317）。

★ 目录判定用**组件扫描**（`:171-174`）：

```python
	for part in norm.split(os.sep):
		if part.lower() in _SECRET_DIRECTORIES:
			return True
```

即 `a/b/.ssh/c` 与 `.ssh/c` 一样命中——**任意深度都拦**，且大小写不敏感。

**评分要点**
- **及格**：说出 `.env`、`id_rsa`、`.ssh` 这类。
- **良好**：说出三类清单的形态（文件名/后缀/目录组件）与大小写不敏感。
- **优秀**：指出目录匹配是**组件级**（任意深度）而非前缀；并主动补清单外的高风险项（`.aws/credentials`、`.docker/config.json`、`*.jks`、`*.keystore`、`.pgpass`）——说明有真实威胁模型而非背清单。

**典型弱答**
- 只列 `.env` 与 `.ssh`；
- 用前缀匹配实现（`sub/.ssh` 漏拦）；
- 忘了大小写不敏感（Windows 上 `.SSH` 绕过）。

**追问**
合法项目里可能有个叫 `credentials.json` 的**测试夹具**，硬拦会误伤。你会怎么在「不误伤」与「不放行真凭据」之间平衡？（→ 0330/0341）

---

### XEYO-QA-0307 受保护元数据的三个目录

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 元数据保护 | 三目录与放宽开关 | 简单 | 概念确认 | `filesystem.py:306-353` |

**面试官提问**
工作区里有些目录**不该被 Agent 写**（哪怕用户批准过）。你会保护哪些？怎么实现这个判定？

**参考答案要点**
`filesystem.py:309-310`（原文）：

```python
PROTECTED_METADATA_NAMES = frozenset({".git", ".xeyo", ".agents"})
ENV_ALLOW_PROTECTED_METADATA = "XEYO_ALLOW_PROTECTED_METADATA"
```

| 目录 | 为什么保护 |
|---|---|
| `.git` | 仓库元数据：写坏 = 丢历史 / 状态不一致 |
| `.xeyo` | 本项目自己的配置与状态目录 |
| `.agents` | Agent 相关元数据目录 |

**实现要点**（`protected_metadata_reason`，`:323-353`）：

1. 先转成**相对 cwd 的相对路径**（`:340-343`），`norm.startswith("..")` 即**直接放行**（工作区外交由既有边界检查处理，不在本函数职责内，`:344-345`）；
2. 再**逐组件扫描**（`:346-352`）——注释记录了这条修正（`:326-328`）：

```
- 约束 workspace 根内的 **任一路径组件** 命中 .git/.xeyo/.agents 即 DENY
  （G78: 原只查首组件,`sub/.git` 被降级为 ASK——嵌套仓库/子模块的
  git 元数据与顶层同等受保护）
```

3. **大小写不敏感**（`os.path.normcase`）；
4. 可用 `XEYO_ALLOW_PROTECTED_METADATA=1` **显式放宽**（`:318-321`）。

**评分要点**
- **及格**：说出 `.git` 要被保护。
- **良好**：说出三个目录 + 大小写不敏感 + 有 env 放宽开关。
- **优秀**：主动指出**「组件级扫描」是修过的**（原实现只查首组件，`sub/.git` 被降级为 ASK）——能指出嵌套仓库 / 子模块这一具体漏洞形态。

**典型弱答**
- 只保护仓库根 `.git`（漏 `vendor/x/.git`）；
- 保护 `.git` 但放行 `.xeyo`（那里面存着我方状态）；
- 不知道有放宽开关（也无法评估放宽后的风险面）。

**追问**
`XEYO_ALLOW_PROTECTED_METADATA=1` 一旦被设上，`.git` 就变可写。这个开关该由谁设、要不要留审计？（→ 0341）

---

### XEYO-QA-0308 三条权限结果文案为什么要分开

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | pending_ttl 结果文案 | 三种否定的区分 | 简单 | 机制解释 | `pending_ttl.py:14-45` |

**面试官提问**
一次操作没被批准，有几种「没被批准」？给模型看到的措辞要不要区分这几种？

**参考答案要点**
三条文案**刻意分开**（`pending_ttl.py:31-45`）：

| 情况 | 常量 | 文案要点 |
|---|---|---|
| 用户**显式拒绝** | `REJECTED_COPY` | "the user **explicitly rejected** this action. **Do not retry** the same call; adjust the approach or ask the user." |
| 面板被关闭 / Esc / 停止按钮 | `CANCELLED_COPY` | "cancelled: the user **dismissed the approval panel** before deciding. Do not retry the same call without asking." |
| **审批不可用**（超时或协调器缺失） | `UNAVAILABLE_COPY` | "unavailable: the request **timed out without a decision** and was treated as rejected." |

**为什么要分开**：三种情况的**正确后续动作不同**：

| 情况 | 模型该怎么做 |
|---|---|
| 显式拒绝 | **不要再试**同一调用；换方案或问用户 |
| 面板关闭（未决定） | 也**不要直接重试**，要先问 |
| 超时（无人值守） | 这是**环境问题**，不是用户态度；本次仍按拒绝处理 |

★ 第三条的「was **treated as rejected**」是关键措辞：同时给出**结果**（本次按拒绝）与**性质**（超时，不是用户拒绝）。若三种都写成 "Permission denied"，模型会**误判用户态度**（以为用户反对而过度退让），而正确信息是「没人来处理」。

★ 三条都**不含劝导与评价**（不说「请遵守权限规则」），只给「发生了什么 + 不要做什么」。

**评分要点**
- **及格**：知道拒绝会告诉模型。
- **良好**：能区分「用户拒绝」与「超时」至少两种。
- **优秀**：指出三分的必要性在于**后续动作不同**，并注意到「treated as rejected」同时表达结果与性质；进一步指出文案里没有说教（符合引擎文本纪律）。

**典型弱答**
- 三条合成一句 "Permission denied"（模型无法区分用户态度与超时）；
- 在文案里写「请遵守权限规则」这类劝导；
- 让模型自行重试（拒绝后重试同一调用是明确禁止的）。

**追问**
如果模型收到 `UNAVAILABLE_COPY` 后仍重试同一调用，系统层面该怎么处理？（→ 0348：执行层持续拒绝 + 审计，而非再写一段劝导）

---

### XEYO-QA-0309 仓库策略文件的四个开关面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | workspace_policy 仓库策略 | 四组取值与默认 | 简单 | 概念确认 | `workspace_policy.py:1-11,22-29,32-56` |

**面试官提问**
你会在仓库里放一个策略文件让团队共享权限设置吗？它应该能控制哪些维度？默认值是什么？

**参考答案要点**
策略文件是 `.xeyo-policy.json`（`POLICY_FILENAME`，`:22`），四个开关面（`:23-26`）：

```python
_BASH_MODES        = frozenset({"default", "ask", "allow", "deny"})
_REMOTE_BASH_MODES = frozenset({"ask", "deny"})
_WRITE_MODES       = frozenset({"ask", "always", "allow", "never", "risk"})
_BASH_ROUTING_MODES = frozenset({"auto", "off"})
```

| 维度 | 取值 | dataclass 默认 |
|---|---|---|
| `bash` | default / ask / allow / deny | `"default"` |
| `remote_bash` | **ask / deny（只有两档）** | `"ask"` |
| `write` | ask / always / allow / never / risk | `"risk"` |
| `bash_routing` | auto / off | `"off"` |

另有 `bash_escalate`（渐进强制阈值，`0` = 关闭，**推荐 3 / 上限 5**，`:27-29`）与 `bash_job_memory_mb`（Job Object 内存上限，**下限 64**）。

★ **`remote_bash` 只有 ask/deny 两档**是刻意的：远程通道**不允许配置成自动放行**——远程入口的持有者身份更难确认。这是「按入口差异化收紧」。

★ 模块 docstring（`:1-11`）写「缺省文件 = 对外安装默认：`bash=ask` / `write=ask` / `remote_bash=ask`」，而 dataclass 字段默认是 `bash="default"` / `write="risk"`——**两处口径不同**（「文件缺失」vs「文件存在但未写该键」），面试时可追问这一点。

**评分要点**
- **及格**：说出能控制 bash 与写权限。
- **良好**：说出四组取值与「remote_bash 只有更严的两档」。
- **优秀**：指出 `remote_bash` 只有 ask/deny 的理由（远程入口身份更难确认 → 不给自动放行档）；并能指出 docstring 与 dataclass 默认值口径不一致这一细节。

**典型弱答**
- 认为策略文件能放宽一切（受单向性约束，见 0331）；
- 忘了远程通道要更严；
- 把 `bash_routing` 当成命令过滤（它是**工具路由**开关）。

**追问**
策略文件在**仓库里**，Agent 自己能不能改它？为什么这件事必须硬拦？

---

### XEYO-QA-0310 ASK 降级为 DENY 的兼容层

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 二元兼容 | `enforce_decision` | 简单 | 机制解释 | `filesystem.py:356-367` + `gate.py:1-45` |

**面试官提问**
你有一套三态权限模型，但有些老调用方只会用「允许/拒绝」两个值。这个适配层该怎么写？

**参考答案要点**
`filesystem.py:356-367`（原文）：

```python
def enforce_decision(decision: PermissionDecision) -> tuple[PermissionDecision, str]:
    """
    P0：ASK 降级为 DENY（无 UI 确认）。
    返回 (allow|deny, reason_key)。
    """
    if decision == PermissionDecision.ALLOW:
        return PermissionDecision.ALLOW, "allowed"
    if decision == PermissionDecision.ASK:
        return PermissionDecision.DENY, "needs_confirmation"
    return PermissionDecision.DENY, "denied"
```

**两处要点**：

1. **降级方向是拒绝**——元注释直接写「P0：ASK 降级为 DENY（无 UI 确认）」；
2. **保留 reason 区分**：ASK→DENY 的 reason 是 **`"needs_confirmation"`**，与真 DENY 的 `"denied"` **不同**——调用方/日志仍能看出「这是缺 UI 而不是规则禁止」。

同类适配在 `gate.py`（`can_use_tool`，`:47-71`），其 docstring 说明它「供旧测试与不走 `ToolRegistry` 挂起流程的调用方使用」。★ `gate._deny_reason`（`:31-45`）还会把 policy 的 `needs_confirmation` **映射回可读路径原因**（`path_outside_working_directory` / `dangerous_path`）——降级但不丢诊断信息。

**评分要点**
- **及格**：说出 ASK 在二元 API 里被当拒绝。
- **良好**：说出降级方向是拒绝，且 reason 与真 DENY 不同。
- **优秀**：指出现代路径（`ToolRegistry` + `evaluate_policy`）**保留 ASK 挂起**，兼容层只为「不走挂起流程的调用方」存在——即**不是权限语义变简单了，而是调用方能力变简单了**。

**典型弱答**
- 把 ASK 降级成 ALLOW（无 UI 场景静默放行最危险）；
- 丢掉 reason 区分（无法诊断「为什么不放行」）；
- 以为兼容层是主路径。

**追问**
如果某个**生产**调用方偷懒走兼容层会有什么后果？你会怎么防止这种误用？（→ 0339）

---

### XEYO-QA-0311 preapproved 标记的用途与风险

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 执行期标记 | `permission_preapproved` | 简单 | 概念确认 | `filesystem.py:12-29,396-435` |

**面试官提问**
工具执行时会**再次**检查权限。如果上层（registry）刚刚已裁决通过，这次再检查会不会又把 ASK 判成拒绝？你怎么解决这个「双重裁决」问题？

**参考答案要点**
用**请求级标记**（`filesystem.py:12-19`）：

```python
_preapproved_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_permission_preapproved", default=False
)

def permission_preapproved() -> bool:
	"""Registry 已 ALLOW / skip_ask 后执行工具时为 True，避免工具内 ASK→DENY。"""
	return bool(_preapproved_ctx.get())
```

配套上下文管理器（`:22-29`）：`mark_permission_preapproved` 用 `token = ctx.set(...)` + `finally: ctx.reset(token)`。

**消费点**：工具内的读/写入口遇到 ASK 时**只信这个标记**（`:414-415`、`:433-434`）：

```python
	if decision == PermissionDecision.ASK:
		return permission_preapproved()
```

**它解决的具体问题**：工具执行路径上有**两次裁决**（registry 一次、工具内一次）。若不标记，工具内的第二次裁决会把 ASK 判成拒绝——**用户已批准的操作会被自己的工具拒绝**。

| 设计要点 | 说明 |
|---|---|
| 用 **ContextVar** 而非全局布尔 | 并发会话/协程之间不串（与容器路由用 ContextVar 防串线是同一理由） |
| `contextmanager` + `finally: reset` | 异常路径也复位（不会「泄漏」成后续请求永久预批准） |
| `default=False` | 默认不预批准（方向安全） |

**评分要点**
- **及格**：说出需要「记住已经批准过」。
- **良好**：说出用 ContextVar（并发隔离）且默认 False。
- **优秀**：主动指出这是**双重裁决**的产物，并说明不用 `try/finally` 复位会导致「一次批准把后续都变成免批准」的**标记泄漏**——这是权限系统最常见的实现漏洞。

**典型弱答**
- 用模块级全局布尔（并发会话互相影响）；
- 忘了复位（批准状态泄漏）；
- 让工具内检查一律跳过（等于取消第二道裁决）。

**追问**
那工具内那次检查还有必要吗？registry 已裁决过，它是不是多余？（→ 0338/0339：工具可能被非 registry 路径调用）

---

### XEYO-QA-0312 兼容层为什么值得单独存在

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | gate 兼容层 | 薄适配 vs 逻辑复制 | 简单 | 机制解释 | `gate.py:1-71` |

**面试官提问**
如果某模块注释写着「真实裁决已收敛到别处，本模块只保留兼容 API」，你怎么判断它该留还是该删？

**参考答案要点**
`gate.py` 就是这样一个模块（71 行，docstring `:1-7`）：

```
真实裁决已收敛到 ``permissions.policy.evaluate_policy``。
本模块保留 ``can_use_tool`` 二元 API（allow|deny）：ASK 降级为 DENY，
供旧测试与不走 ToolRegistry 挂起流程的调用方使用。
```

**判断「留还是删」的四个问题**：

| 问题 | 本例答案 |
|---|---|
| 还有调用方吗？ | 有：旧测试 + 不走 registry 挂起流程的调用方 |
| 是**薄**适配层吗？ | 是：`can_use_tool`（`:47-71`）只做「调 policy + 二元化 + 恢复 reason」 |
| 会不会成为绕过点？ | **会**——它把 ASK 降级为 DENY，若生产路径误用，用户就**无法批准**任何需要确认的操作 |
| 删掉会怎样？ | 旧测试红 + 调用方要改；但**没有重复实现**（不复制 policy 逻辑） |

结论：**保留但标注**。它不含第二套规则（只做形态转换），且注释明确指向真源。★ **危险的是「复制一份逻辑」的兼容层**，不是形态转换层。

**评分要点**
- **及格**：说出「有旧调用方所以保留」。
- **良好**：说出判断标准是「是否复制了第二套规则」——薄适配层可留，重复实现必删。
- **优秀**：指出真正风险是**误用**（生产路径走它 → 用户无法批准），并给出防误用手段（注释标注真源、限制可见性、测试只走它）。

**典型弱答**
- 「既然收敛了就该立刻删」（忽略调用方成本）；
- 认为兼容层与真源各有一份规则（那才是必须删的情形）；
- 不区分「形态转换」与「逻辑复制」。

**追问**
如果要在**代码层**防止生产路径误用这个兼容层，你会怎么做？

---


### XEYO-QA-0313 判断路径是否在工作区内，为什么要做两次 realpath

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 路径狱 | symlink 解析 | 中等 | 机制解释 | `python/permissions/filesystem.py:127-154` |

**面试官提问**
你要判断「这个路径是否落在允许的工作目录内」。如果只做字符串前缀比较会有什么漏洞？请写出你的判定函数。

**参考答案要点**
`path_in_allowed_working_path`（`:127-154`）——**两侧都做 realpath**：

```python
	abs_path = normalize_case_for_comparison(
		os.path.realpath(expand_to_abs(path, cwd=base))          # 路径侧 realpath
	)
	for root in roots:
		abs_root = normalize_case_for_comparison(
			os.path.realpath(os.path.abspath(os.path.expanduser(root)))   # 根侧 realpath
		)
		if abs_path == abs_root or abs_path.startswith(abs_root + os.sep):
			return True
		if abs_path.startswith(abs_root.rstrip("\\/") + "/"):    # 混合分隔符容错
			return True
	return False
```

**docstring 直接给出漏洞**（`:133-137`）：「两侧都按 realpath 解析：工作区内的符号链接若指向外部目标，比较时落在真实目标上，**防止借 symlink 逃出工作区写文件**」。即只比字符串时，`/ws/link/secret` 前缀看着在 `/ws/` 内，而 `link` 指向 `/etc` → 实际写到区外。

| 细节 | 作用 |
|---|---|
| `expand_to_abs` 先 `abspath`（`:118-124`） | 折叠 `..`，防穿越 |
| `normalize_case_for_comparison` = `.lower()`（`:113-115`） | Windows 大小写不敏感 |
| 拼 `+ os.sep`（`:149`） | 防前缀误判：`/ws-evil` 不该命中 `/ws` |
| 额外认 `/` 风格前缀（`:152`） | 混合分隔符容错 |

**评分要点**
- **及格**：说出「要做 realpath」。
- **良好**：说出**两侧**都 realpath，并解释 symlink 逃逸形态。
- **优秀**：主动指出 `+ os.sep` 的必要性（否则 `/ws-evil` 被判在 `/ws` 内）与 `abspath` 折叠 `..` 的作用。

**典型弱答**
- 只 `startswith(root)`（symlink 与 `/ws-evil` 都漏）；
- 只对路径 realpath、根不解析；
- 用 `os.path.commonpath` 但不处理跨盘符（Windows 抛 `ValueError`）。

**追问**
realpath 需要文件**存在**才能解析链接。若目标还不存在（要新建文件），你的判定会退化吗？（→ 0329 的时序问题）

---

### XEYO-QA-0314 读裁决的四层顺序

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 读裁决 | 判定顺序 | 中等 | 机制解释 | `python/permissions/filesystem.py:261-284` |

**面试官提问**
一次「读文件」的权限裁决，你会按什么顺序判断？顺序为什么重要？

**参考答案要点**
`check_read_permission_for_path`（`:261-284`）的顺序：

| 序 | 判定 | 结果 |
|---|---|---|
| ① | 组装 allowed 根 = 工作区 + `readable_extra_roots()` | — |
| ② | 工作区边界 | 区外 → **DENY**（除非最高档 `_max_outside_allowed()`） |
| ③ | `is_secret_path` | **硬 DENY**（不走 ASK） |
| ④ | `is_dangerous_path` | **ASK** |
| 默认 | 其余 | ALLOW |

**顺序重要的两个原因**：①**密钥判定必须在边界之后且无条件执行**——`readable_extra_roots` 会把工作区**之外**的记忆库目录加进 allowed，所以必须保证「**即使区外被放宽，密钥仍然硬拦**」（注释 `:276,279`）；②**危险判定给 ASK 而不是 DENY**——读 `.git/config` 有时是合理需求，但需用户知情。

**评分要点**
- **及格**：说出「先判区外、再判密钥」。
- **良好**：说出四层顺序与各自结果（DENY / 硬 DENY / ASK / ALLOW）。
- **优秀**：指出密钥判定**无条件执行**的意义（最高档放宽区外时密钥仍被硬拦）——即「放宽不能穿透硬拦」；并说明密钥与危险的结果差异（DENY vs ASK）的理由。

**典型弱答**
- 把密钥与危险都判 DENY（丢掉可批准路径）；
- 顺序颠倒导致最高档下可读密钥；
- 不知道 `readable_extra_roots` 会扩张 allowed 根。

**追问**
`readable_extra_roots` 把记忆库加进**可读**根。为什么写裁决不能同样放宽？（→ 0319/0335）

---

### XEYO-QA-0315 写裁决与读裁决差在哪

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 写裁决 | 复用与增量 | 中等 | 机制解释 | `python/permissions/filesystem.py:287-303` |

**面试官提问**
你已写好一个「读」的路径裁决函数。写裁决要重写一遍还是复用？请说明写法与理由。

**参考答案要点**
写裁决**先做两件写专有判定，再复用读裁决**（`:287-303`）：

```python
	if is_secret_path(path, cwd=cwd):                        # ① 密钥：写也硬 DENY
		return PermissionDecision.DENY
	if protected_metadata_reason(path, cwd=cwd) is not None:  # ② 受保护元数据：写硬 DENY
		return PermissionDecision.DENY
	return check_read_permission_for_path(path, context=ctx)  # ③ 复用读裁决
```

docstring（`:292-296`）：「密钥路径硬 DENY；受保护元数据（`.git/.xeyo/.agents`，T12）硬 DENY；**其余与读同级**（危险 → ASK，区外 → DENY）。」

**为什么能复用**：读与写在**边界、密钥、危险**三维上规则一致；写**专有的额外一层只有「受保护元数据」**。

★ 但有一处**方向差异**：读裁决内部会追加 `readable_extra_roots`，而那份函数注释写「**仅用于读裁决；写裁决不得包含**」（`:191-194`）。写裁决在最后一步复用了读裁决，因此**也会享受到这份放宽**——这是本卷标注的一处**待确认点**（注释声明与调用链之间存在张力）。

**评分要点**
- **及格**：说出写也要拦密钥。
- **良好**：说出写专有的受保护元数据这一层，其余复用读裁决。
- **优秀**：**主动发现** `readable_extra_roots` 的注释与写裁决复用读裁决之间的矛盾（即「写裁决不得包含」却因复用而生效）——这是本卷真实存在的一处不一致。

**典型弱答**
- 为写裁决重写全部规则（重复实现、易漂移）；
- 忘了受保护元数据只对写生效（读 `.git/config` 是允许的）；
- 没注意 `readable_extra_roots` 的作用域声明。

**追问**
如果要把「写裁决不得包含可读额外根」变成**代码强制**而不是靠注释，你会怎么改？

---

### XEYO-QA-0316 `.env` 变体与模板后缀

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 密钥判定 | 泛化与豁免 | 中等 | 对比辨析 | `python/permissions/filesystem.py:157-175` |

**面试官提问**
`.env` 这种文件，你会只拦 `.env` 三个字，还是拦所有变体？如果拦所有变体，`.env.example` 怎么办？

**参考答案要点**
**泛化 + 模板豁免**（`:161-168`）：

```python
	base_l = os.path.basename(abs_path).lower()
	if base_l in DANGEROUS_FILES:
		return True
	if base_l.startswith(".env") and not any(
		# 常见模板/示例后缀不含真凭据,不误伤
		base_l.endswith(s)
		for s in (".example", ".sample", ".template", ".dist")
	):
		return True  # .env 任意变体（G77: 原仅 3 个显式条目）
```

| 规则 | 覆盖 |
|---|---|
| 显式清单 | `DANGEROUS_FILES` 14 条 |
| **泛化** | 任何 `.env*` → 拦（`.env.staging`、`.env.backup`…） |
| **豁免** | `.example` / `.sample` / `.template` / `.dist` 结尾 → 放行 |

注释里的 **G77** 记录了历史：**原实现只有 3 个显式条目**，所以 `.env.staging` 曾被放行。

★ 泛化的**过宽面**：`.envrc`（direnv 配置）与 `.environment` 也会被拦——它们通常不含密钥。这是「宁可误拦」的取舍。

**评分要点**
- **及格**：说出 `.env` 要拦。
- **良好**：说出「前缀泛化 + 模板后缀豁免」两半。
- **优秀**：指出泛化的**误伤面**（`.envrc`）并说明这个方向仍对（凭据泄漏代价 >> 误拦成本）；能指出 G77 的历史（原来只有 3 条）。

**典型弱答**
- 只拦显式三条（`.env.staging` 漏）；
- 连 `.env.example` 也拦（合法模板被挡）；
- 用 `endswith(".env")`（`foo.env` 不命中，需说明取舍）。

**追问**
`.env.example` 里可能**恰好**被开发者写了真 key（很常见）。你的豁免会放过它吗？怎么降低这个风险？

---

### XEYO-QA-0317 为什么凭据目录清单不含 `.git`

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 两份清单差异 | 语义分层 | 中等 | 对比辨析 | `filesystem.py:88-108,178-188,323-353` |

**面试官提问**
代码里有两份长得很像的目录清单，只差一个 `.git`。为什么不能合并成一份？

**参考答案要点**
```python
DANGEROUS_DIRECTORIES = frozenset({".git", ".ssh", ".kube", ".gnupg", ".aws"})
_SECRET_DIRECTORIES  = frozenset({".ssh", ".kube", ".gnupg", ".aws"})   # 无 .git
```

**原因写在注释里**（`:98-100`）：

```
# 凭据目录（is_secret_path 硬 DENY 扫描）。刻意不含 .git——.git 的读写保护
# 走 protected-metadata(workspace 内)/is_dangerous_path(工具),避免把"读 .git 需
# 确认"的整体语义变成无条件 DENY(G77/G78 修正后口径)。
```

| 清单 | 消费函数 | 结果 |
|---|---|---|
| `_SECRET_DIRECTORIES` | `is_secret_path` | **硬 DENY**（不可被批准） |
| `DANGEROUS_DIRECTORIES` | `is_dangerous_path` | **ASK**（可被用户批准） |

`.git` 应按**场景**走不同路径：

| 场景 | 期望 | 靠谁 |
|---|---|---|
| 工作区内**写** `.git/...` | 硬 DENY | `protected_metadata_reason` |
| 工作区内**读** `.git/config` | **ASK** | `is_dangerous_path` |
| 工作区**外**的 `.git` | 边界判定处理 | `path_in_allowed_working_path` |

若把 `.git` 放进 `_SECRET_DIRECTORIES`，就会让「读 `.git`」变成**无条件 DENY**——把「查看仓库配置/日志」这一合理用例钉死。

**评分要点**
- **及格**：说出 `.git` 需要被保护。
- **良好**：说出两份清单对应两种结果（硬 DENY vs ASK）。
- **优秀**：把 `.git` 的**三场景分工**讲清；并指出合并会让「读 `.git`」永不可批准。

**典型弱答**
- 认为两份清单冗余应合并；
- 说不出 `is_secret_path` 与 `is_dangerous_path` 的结果差异；
- 把 `.git` 与 `.ssh` 同等对待。

**追问**
`protected_metadata_reason` 只对工作区内生效（相对路径以 `..` 开头就放行）。工作区**外**的 `.git` 写保护由谁负责？够吗？

---

### XEYO-QA-0318 受保护元数据为什么改成组件级扫描

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 元数据保护 | 嵌套仓库漏洞 | 中等 | 机制解释 | `filesystem.py:323-353` |

**面试官提问**
`sub/.git/config` 与根目录的 `.git/config` 该受同样保护吗？原实现只查第一个路径组件，会漏掉什么？

**参考答案要点**
注释记录了修正（`:326-331`）：

```
- 约束 workspace 根内的 **任一路径组件** 命中 .git/.xeyo/.agents 即 DENY
  （G78: 原只查首组件,`sub/.git` 被降级为 ASK——嵌套仓库/子模块的
  git 元数据与顶层同等受保护）
```

**原实现的漏洞链**：相对路径 `sub/.git/config` → 只查首组件 `sub`（不是 `.git`）→ 不命中 protected-metadata → 落到 `is_dangerous_path`（`.git` 在 `DANGEROUS_DIRECTORIES`）→ **判 ASK** → 用户批准即写入。后果是**嵌套仓库 / submodule 的元数据保护等级被降一级**。

修正后逐组件比对（`:346-352`）：`for part in norm.split(os.sep)` + `pn == os.path.normcase(name)`，任意深度命中即硬 DENY。

★ 边界：`if norm.startswith(".."): return None`（`:344-345`）——**工作区外的路径不由本函数管**（交给边界检查），这是有意的职责划分。

**评分要点**
- **及格**：说出 `sub/.git` 也要保护。
- **良好**：说出原实现「只查首组件」导致的降级（硬 DENY → ASK）。
- **优秀**：指出**具体利用路径**（submodule / 嵌套仓库），并说明「同一资产两种保护等级」是这类漏洞的典型信号。

**典型弱答**
- 认为「反正都会 ASK，差别不大」（两者保障等级完全不同）；
- 只想到 submodule，没想到任何嵌套的 git 仓库；
- 把 `..` 放行理解成漏洞。

**追问**
若工作区里有一个**合法**的嵌套仓库（你正在开发 submodule），硬 DENY 会妨碍正常工作。这个冲突怎么处理？

---

### XEYO-QA-0319 读放宽了哪些额外根

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 额外可读根 | 受控放宽 | 中等 | 机制解释 | `filesystem.py:191-244` |

**面试官提问**
有些文件在**工作区之外**但 Agent 必须能读（否则功能不可用）。你会放宽哪些？怎么保证放宽受控？

**参考答案要点**
`readable_extra_roots`（`:191-244`）返回三类：

| 类 | 内容 |
|---|---|
| ① | 当前工作区**记忆库目录** `memdir_root(workspace_id(c))` |
| ② | **user 域**记忆库 `memdir_root(USER_MEMDIR_ID)` |
| ③ | **仅当前会话**的转录（`transcript_path(sid)` + `.old1`/`.old2` 归档） |

**四条受控点**（docstring `:192-199`）：

```
	仅用于**读**裁决；写裁决不得包含。
	- **仅当前会话**的转录文件……不放宽整个 sessions 目录，其他会话的转录保持不可达。
	失败静默返回空——权限门永不因辅助目录计算而崩。
```

| 受控点 | 说明 |
|---|---|
| 只读 | 明确「写裁决不得包含」 |
| **只当前会话** | 不放宽整个 `sessions/` → 其他会话转录仍不可达 |
| 只列**实际存在**的文件（`:237-241`） | 不存在就不加进 allowed 根 |
| 失败静默 | 整段 `try/except`，异常返回已收集部分 |

★ 「只当前会话」是**关键安全边界**：转录含完整对话（可能含密钥与隐私）。放宽整个 `sessions/` 就等于**跨会话横向读取**。

**评分要点**
- **及格**：说出记忆库要能读。
- **良好**：说出「只读 / 只当前会话 / 失败静默」三条受控点。
- **优秀**：主动指出放宽整个 `sessions/` 会造成跨会话横向越权；并指出「只列实际存在的文件」这一细节（避免不存在的路径进入 allowed 根）。

**典型弱答**
- 放宽 `~/.xeyo/` 整目录（含 spill / offload / 其他会话 sidecar）；
- 让写裁决也享受这份放宽；
- 辅助计算失败时抛异常（权限门崩 = 整个 Agent 不可用）。

**追问**
这个函数在**每次裁决**时都会被调用（含 memdir 计算与多次 `is_file`）。热路径成本如何？怎么优化？

---

### XEYO-QA-0320 权限单向性：收紧即时、放宽延后

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | runtime_mode 活状态 | 单向性 | 中等 | 机制解释 | `python/permissions/runtime_mode.py:9-18,69-105` |

**面试官提问**
用户在回合**进行中**切换审批模式。如果他在批准一个危险操作后立刻把模式放宽，同一回合里剩下的调用会怎样？这个安全问题怎么解？

**参考答案要点**
docstring 给出问题与解法（`:9-18`）：

```
T26 单向性：收紧即时、放宽延后。
- turn 边界（``begin_turn``）拍定本轮基线；轮内 ``effective`` 返回
  ``baseline`` 与 ``requested`` 中**更严**者 —— 收紧立即生效，放宽等到
  下一 turn 才放行（防止「批准完当前危险操作后，同轮剩余调用被静默放行」）。
```

实现三件套（`:69-105`）：

| 动作 | 实现 | 效果 |
|---|---|---|
| 写活值 | `set()`：若比基线更严则**同步抬升基线** | **收紧即时** |
| turn 边界 | `begin_turn()`：`baseline = requested or normalize_mode(default) or "risk"` | 拍定基线、复位广播 |
| 轮内取严 | `effective()`：`stricter(baseline, requested)` | **放宽延到下一 turn** |

★ 它防的是一个**具体场景**：用户「批准删除 → 系统开始执行 → 顺手把模式调到 `never`」，若放宽即时生效，**同轮剩余调用会被静默放行**。

★ 并发细节（`:51-55`）：读路径（single-key get）**依赖 GIL 原子、不加锁**；写路径与 turn 边界（跨两个 dict 的复合更新）**用一把锁**。

**评分要点**
- **及格**：说出「放宽不该立刻生效」。
- **良好**：说出「基线 vs 活值取更严」与 turn 边界复位。
- **优秀**：指出要防的**具体场景**，并指出 `set()` 里「收紧时同步抬升基线」这一处设计——它让收紧不必等 turn 边界，才真正做到「收紧即时」。

**典型弱答**
- 认为模式切换应立即完全生效（放任宽即时 = 漏洞）；
- 只在 turn 边界读模式（收紧也无法即时）；
- 没注意 `stricter()` 是单向性的公共基础。

**追问**
`baseline = requested or normalize_mode(default) or "risk"` 有两层兜底。若既无活值、`default` 也非法，会落到哪一档？方向安全吗？

---

### XEYO-QA-0321 会话内切换 preset 与「pin」的关系

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | runtime_preset 活状态 | 优先级链与校验 | 中等 | 系统设计 | `python/permissions/runtime_preset.py:1-44` |

**面试官提问**
权限档位原先在**会话创建时固定**，导致「改设置只影响新会话」。现在要支持会话内切换。请说明优先级设计，以及校验时要注意什么。

**参考答案要点**
docstring 给出方案（`:1-13`）：

```
smoke-test #6：会话权限 preset（readonly / workspace-write / full）原先在会话
创建时被 SessionPool pin（T10），之后请求不得改写 —— 导致"权限变更只影响新
会话"。本 store 提供**会话内显式切换**……
（优先级：store 活值 > WorkspaceContext.permission_profile > ""）
```

**校验上的关键坑**（`set`，`:29-40`）：

```python
	def set(self, session_id: str, preset: object) -> str | None:
		"""注意：presets.normalize_preset 会把未知值回退为默认（workspace-write），
		这里必须用原始名校验 —— 用户打字错误不能静默变成"工作区写"。"""
		raw = str(preset or "").strip().lower().replace("_", "-")
		if raw not in PERMISSION_PRESETS:
			return None
```

即**不能复用 `normalize_preset`**（它把非法值回退成 `workspace-write` = **可写**）——否则 `readonly` 打成 `readonli` 会**静默升级为可写**。正确做法：**原始名校验 + 非法不写入**。

`replace("_", "-")` 让 `workspace_write` 也被接受（宽容输入），但校验仍走白名单。

**评分要点**
- **及格**：说出会话内切换优先于创建时固定。
- **良好**：说出优先级链三级与「显式切换才覆盖 pin」。
- **优秀**：**主动指出校验坑**——用 `normalize_preset` 会让打字错误**静默升级权限**；正确做法是原始名校验 + 拒绝。说明候选人对「默认值方向」有清醒认识。

**典型弱答**
- 复用 `normalize_preset`（静默升级权限）；
- 让请求体可改写 pin（违反 T10）；
- 只做小写归一不做白名单校验。

**追问**
`RuntimeModeStore` 与 `RuntimePresetStore` 都是 per-session 活状态。它们的**语义差异**是什么？

---

### XEYO-QA-0322 工人写范围的三类收束

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | write_scope 规范化 | 过宽与仓外 | 中等 | 机制解释 | `python/permissions/write_scope.py:46-103` |

**面试官提问**
子 agent 会声明「我可以写哪些路径」。作为引擎，你会**原样相信**这个声明吗？请说明怎么规范化。

**参考答案要点**
`normalize_worker_scope(raw, *, cwd)` → `(paths, read_only, reason)`，**三类收束**：

| 类 | 判定 | 处置 |
|---|---|---|
| ① 过宽 | `.` / `./` / 仓根 / 盘符根（`C:`、`C:/`、`/`、`\`） | 丢弃该条，`broad = True` |
| ② 仓外 | `rel` 以 `..` 开头或为绝对路径 | **当作无效，不扩大权限**（`:92-95`） |
| ③ 可收束 | 仓内绝对路径 | 收成**相对 cwd 的前缀** |

最终（`:99-103`）：

```python
	if broad and not out:
		return [], True, "scope_too_broad"   # 全过宽 → 只读
	if not out:
		return [], True, ""
	return out, False, ("scope_too_broad" if broad else "")
```

三条原则：①**不信任声明**——过宽不是「批准」而是**降级为只读**（方向安全）；②**仓外一律无效**——不是拒绝整个 scope，而是丢这一条；③**绝对路径收束成相对**，便于前缀匹配。

**评分要点**
- **及格**：说出要校验 scope。
- **良好**：说出「过宽 → 只读」这一方向，并知道盘符根/仓根必须进名单。
- **优秀**：指出三类的**不同处置**（丢弃 / 无效 / 收束）与 `broad and not out` 才整体降只读的精细度；指出「仓外只丢这一条」体现「不因一条坏声明废掉全部」的取舍。

**典型弱答**
- 原样使用模型给的 scope（`["/"]` 等于全盘写）；
- 过宽就整体报错拒绝；
- 只判 `.` 不判盘符根（`C:` 漏）。

**追问**
若模型传 `scope=["src", "../outside"]`，按规则结果是什么？（→ 保留 `src`、丢仓外项、`read_only=False`，reason 含 `scope_too_broad`）

---

### XEYO-QA-0323 write_scope 的三态语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | write_scope 上下文语义 | `None` / `()` / 非空 | 中等 | 机制解释 | `write_scope.py:1-6,106-157` |

**面试官提问**
一个「写范围」的上下文变量，「未设置」与「空集合」的语义应该一样吗？

**参考答案要点**
**必须区分三态**（docstring `:1-6`）：

```
- ``None``：主会话，不按 scope 限制（仍走工作区 / 策略门禁）。
- ``()``：子 Agent 未声明 scope → 禁止 Write/Edit。
- 非空：写路径必须落在任一 scope 前缀下。
```

| 取值 | 语义 | `path_in_write_scope` |
|---|---|---|
| `None` | **主会话**，不按 scope 限制 | `True`（`:118-119`） |
| `()` | 子 agent 未声明 → **只读** | `False`（`:120-121`） |
| 非空 | 必须落在某个前缀下 | 逐前缀比对 |

判定入口给出**两个不同原因码**（`:148-157`）：`write_scope_empty`（本来就不能写）与 `write_scope_denied`（能写但这条路不在范围内）——诊断与文案都不同。

上下文管理用 `token` + `finally: reset`（`:32-43`），与 0311 的 `preapproved` 同一模式。

**评分要点**
- **及格**：说出空 scope 表示不能写。
- **良好**：说出三态语义，尤其 `None`（主会话）与 `()`（只读工人）的区别。
- **优秀**：指出**为什么必须区分**——合并会让主会话被误判成只读（或只读工人被误判成可写任意处）；并指出两个原因码的区分价值。

**典型弱答**
- 用 `if not scope` 统一处理（`None` 与 `()` 混同）；
- 用模块级全局变量而非 ContextVar（并发子 agent 串味）；
- 忘了 `finally: reset`（scope 泄漏到后续调用）。

**追问**
并发跑两个子 agent（`scope=["a"]` 与 `scope=["b"]`）时，怎么保证 scope 不串？

---

### XEYO-QA-0324 挂起的审计配对与结果词表

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | pending_ttl 审计面 | 配对与 intent | 中等 | 机制解释 | `pending_ttl.py:14-21,47-53` |

**面试官提问**
权限挂起是一条异步流程（发起 → 用户决定 → 回执）。你会怎么设计它的**审计记录**与**结果词表**？

**参考答案要点**
**审计配对**（docstring `:18-21`）：

```
审计配对：``permission.pending`` ↔ ``permission.resolved``（allow/deny 都记），
即计划中的 approval.asked/decided 对——命名以 permission.* 为准，不再双写。
```

★ 「不再双写」说明曾经存在**两套命名**（`approval.asked/decided` 与 `permission.*`），后来收敛为一套——这是「同一语义两套事件名」的治理动作。

**两处词表**：

| 处 | 取值 |
|---|---|
| `ttl_for_request` 输入 | `reason` / `matched_rule` / `tool_name` |
| `intent_for` 输出 | `"choice"`（带 `choices` 的三选）或 `"confirm"`（`:52-53`） |

结果三值：`rejected` / `cancelled`（outcome=aborted）/ `unavailable`。

**评分要点**
- **及格**：说出要记「发起」和「结果」。
- **良好**：说出 **allow/deny 都记**，与 `intent_for` 的两值。
- **优秀**：主动指出**事件命名收敛**（两套 → 一套，避免双写）；并指出 `intent_for` 的 `choice` 对应 `PolicyDecision.choices` 的三选 ASK。

**典型弱答**
- 只记拒绝不记批准（无法审计「谁批准了什么」）；
- 保留两套事件名（查询时要不一致地拼）；
- 把 cancelled 与 rejected 混为一谈。

**追问**
三选 ASK（`choices`）与普通确认（`confirm`）在**审计**上要不要区分？为什么？

---

### XEYO-QA-0325 挂起请求为什么能幂等 resolve

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | store 挂起存储 | 幂等与三选 | 中等 | 系统设计 | `python/permissions/store.py:1-33` |

**面试官提问**
权限挂起可能被**两个入口**同时回应（桌面 GUI 与微信）。你怎么设计存储，保证「同一次请求只被处理一次」？

**参考答案要点**
`store.py` 的骨架（docstring `:1-10`）：

```
key = request_id，保存 pending 请求与唤醒信号；支持超时与幂等 resolve。
同一 request_id 只能被处理一次。
桌面 / 微信 resolve 均走本 store，成功时写 ``permission.resolved`` 审计。

三选 peer ASK：``user_choice`` 为 allow / deny / remind；旧客户端只传 approved。
```

| 设计点 | 实现 |
|---|---|
| **以 `request_id` 为键** | 同一次挂起只有一个键 → 两个入口打同一个键 |
| **幂等 resolve** | 「同一 request_id 只能被处理一次」——第二次 resolve 是 no-op（不会翻转已定结果） |
| **唤醒信号** | 存 pending 时带唤醒原语（异步等待方靠它被唤醒） |
| **超时** | 用 `pending_ttl.ttl_for_request` 决定的 TTL（0305） |
| **三选** | `USER_CHOICE_ALLOW` / `DENY` / `REMIND`（`:24-27`），且 `_VALID_USER_CHOICES` 做白名单校验 |
| **审计** | 成功 resolve 时写 `permission.resolved` |

★ **三选里的 `remind` 值得单独说**：它不是「允许」也不是「拒绝」，而是「**稍后再提醒我**」——即请求**仍处于未决状态**（对应 `PolicyDecision.choices` 的三选 ASK，`policy.py:63`）。所以「幂等」的实现必须能表达**三种终态之外的第四种：仍在等**。

**评分要点**
- **及格**：说出用 request_id 做键、只处理一次。
- **良好**：说出两个入口共用同一 store、且带审计。
- **优秀**：能指出 `remind` 让状态机不是「二元终态」，幂等实现必须把它当**未决**而不是终态；并能指出「旧客户端只传 approved」的兼容面（向后兼容的输入形态归一）。

**典型弱答**
- 用「工具名 + 参数」做键（同一参数的不同次请求会互相覆盖）；
- 不做幂等（两次 resolve 翻转结果 → 用户先点了拒绝又被微信的批准覆盖）；
- 把 `remind` 当拒绝处理。

**追问**
两个入口**同时** resolve 同一次请求（竞态）会发生什么？你会用锁还是 CAS？

---

### XEYO-QA-0326 策略文件坏掉时该收紧还是放宽

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | workspace_policy fail-closed | 坏文件处置 | 中等 | 权衡取舍 | `python/permissions/workspace_policy.py:1-11,49-55` |

**面试官提问**
仓库里的策略文件被写坏了（JSON 解析失败）。此时应该按「没配置」处理，还是按「最严」处理？

**参考答案要点**
按**最严**处理——`parse_error` 字段 + `exists` 属性（`:49-55`）：

```python
	#: 非 None 表示文件存在但解析失败（T25 fail-closed：策略不生效，默认收紧）。
	parse_error: str | None = None

	@property
	def exists(self) -> bool:
		"""策略文件存在**且解析成功**；坏文件不算生效策略（T25）。"""
		return bool(self.source_path) and self.parse_error is None
```

docstring 也写明（`:10-11`）：

```
坏文件（解析失败）一律回退收紧默认并记审计（T25 fail-closed）。
```

**为什么必须 fail-closed**：

| 若按「没配置」处理 | 后果 |
|---|---|
| 策略文件本来写着 `write: "always"`（每次写都确认） | 坏掉后回退到 dataclass 默认 `write="risk"` → **静默放松** |
| 攻击者若能写坏策略文件 | 就等于**用「制造解析错误」来降级权限** |

第二条是关键：策略文件是**仓库里可提交的文件**，它的内容由团队维护；若坏文件被当作「无策略」，那么「让文件解析失败」就成了一种绕过手段。所以 fail-closed 同时防误配置与防绕过。

★ `exists` 属性的语义（**存在且解析成功**）是这套设计的关键接口：调用方问 `policy.exists` 时得到的是「**有没有生效的策略**」，而不是「文件在不在」。

**评分要点**
- **及格**：说出坏文件要按严的来。
- **良好**：说出 `exists` 的语义是「存在且解析成功」，并指出要记审计。
- **优秀**：主动指出**「制造解析错误即可降级权限」**这条绕过路径（这是 fail-closed 的真正理由），并指出「文件在不在」与「策略是否生效」必须用不同接口表达。

**典型弱答**
- 坏文件当「无策略」（静默放松 + 可被利用）；
- 坏文件直接抛错拒绝整个会话（过度反应，用户失去所有能力）；
- 不记审计（事后无法知道「策略当时生效了吗」）。

**追问**
坏文件被回退成「收紧默认」之后，用户会看到什么？如果不给任何提示，用户会不会以为策略生效了？

---

### XEYO-QA-0327 readonly_gate 的两个来源

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | policy 只读门禁 | preset 与模式 | 中等 | 机制解释 | `policy.py:417-434` |

**面试官提问**
「只读」这个限制，除了「审批模式」之外还可能来自哪里？请说明你的判定顺序。

**参考答案要点**
`readonly_gate(name, *, tool=None)`（`:417-434`）有**两个来源**：

```python
	profile = session_permission_profile()
	if profile == "readonly":                       # 来源①：会话 preset
		if name in READONLY_ALLOW or name in READONLY_ASK_ALLOW:
			return None
		if tool is not None and tool_flag(tool, "is_read_only", default=False):
			return None
		return "readonly_mode_deny"
	if not side_mode() and agent_mode() == "agent":  # 来源②：侧聊 / Agent 模式
		return None
	if tool_allowed_in_mode(name, tool=tool):
		return None
	return "readonly_mode_deny"
```

| 来源 | 触发条件 | 范围 |
|---|---|---|
| ① **会话 preset**（`session_permission_profile() == "readonly"`） | 整个会话只读 | 会话级 |
| ② **侧聊 / Agent 模式**（`side_mode()` 或 `agent_mode() != "agent"`） | 按模式白名单 | 请求级 |

**顺序是先 preset、后模式**，且 **Agent 模式为 `agent` 且非侧聊时直接放行**（`:430-431`）。

★ 两处都返回**同一个原因码** `"readonly_mode_deny"`——即拒绝原因**不区分来源**。这是有意的（对模型而言「只读模式禁止」是一件事），但也意味着**排障时无法从原因码看出是 preset 还是模式导致的**（可观测性上的一个取舍，面试可追问）。

**评分要点**
- **及格**：说出只读来自 preset。
- **良好**：说出两个来源（会话 preset + 请求级侧聊/Agent 模式）与判定顺序。
- **优秀**：指出两来源**共用同一原因码**这一取舍（对模型简化 vs 排障信息损失），并指出「Agent 模式 = agent 且非侧聊」时**短路放行**这一早退。

**典型弱答**
- 只想到 preset（漏侧聊/plan/ask 模式）；
- 把 `readonly` preset 与「审批模式」混为一谈（后者管问不问，前者管能否改）；
- 试图从原因码区分来源（当前不能）。

**追问**
如果要让排障能区分来源，你会怎么改**而不破坏**模型可见面的简洁性？（→ 原因码保持不变，把来源放进审计字段）

---

### XEYO-QA-0328 「可能写盘」与「危险路径」是两回事吗

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | policy Bash 写判定 vs 危险路径 | 两个维度的分离 | 中等 | 对比辨析 | `policy.py:742-806` + `filesystem.py:178-188` |

**面试官提问**
代码里有「判断 Bash 命令是否会写盘」和「判断路径是否危险」两套判定。它们是一个东西吗？各自的结果会影响什么？

**参考答案要点**
**是两个独立维度**：

| 判定 | 位置 | 输入 | 输出 | 影响 |
|---|---|---|---|---|
| **Bash 写判定** | `policy._bash_writes_file`（`:785`）、`bash_write_target`（`:765,798-806`） | **命令字符串** | bool / 写目标路径 | 决定要不要走写路径的**边界与确认**；也决定搜索缓存是否失效（B05-0215） |
| **危险路径判定** | `filesystem.is_dangerous_path` | **路径** | bool | 决定 **ASK**（可被批准） |

它们**常常一起用**（Bash 命令要先解析出写目标，再判那个目标是否危险/在区外），但**职责不同**：

```
命令字符串 ──(写判定)──→ 写目标路径 ──(路径狱/危险判定)──→ ALLOW / ASK / DENY
```

`policy.py:742-765` 的四组正则正是「写判定」的实现面：`_BASH_REDIRECT_RX`（重定向）、`_BASH_WRITE_CMD_RX`（写命令）、`_BASH_INTERP_RX`（解释器）、`_BASH_WRITE_MARK_RX`（写标记）、`_BASH_PY_OPEN_RX`（Python 打开文件）。

★ 还有一个**独立于权限的消费方**：`bash_writes_file` 被 B05 的 `_command_may_mutate_workspace` 复用（决定是否清搜索缓存）——所以**同一个判定服务两个目的**（权限边界 + 缓存一致性），修改它的行为会同时影响两处。这是跨模块耦合点。

**评分要点**
- **及格**：说出一个判命令、一个判路径。
- **良好**：说出它们串联的关系（命令 → 写目标 → 路径判定），并指出写判定的多组正则形态。
- **优秀**：主动指出 `bash_writes_file` **有两个消费方**（权限 + 搜索缓存），即「改一处影响两处」的耦合风险（例如把判定放宽会让缓存漏清，反之会让缓存过度清理）。

**典型弱答**
- 认为它们是一回事（都叫「危险」）；
- 只想到权限消费方，忽略缓存那一侧；
- 以为写判定能直接给出「允许/拒绝」（它只回答「是否可能写」）。

**追问**
同一个 `bash_writes_file` 服务两个方向相反的失败取向吗？（→ 权限侧误判要安全，缓存侧 fail-closed 详见 B05-0215）

---

### XEYO-QA-0329 realpath 与时序：symlink 逃逸面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 路径判定的时序 | TOCTOU | 困难 | 安全拷问 | `python/permissions/filesystem.py:127-154,287-303` |

**面试官提问**
你的路径狱用 `realpath` 解析 symlink 后比较。请找出这套判定的**时序缺口**，并给出至少两种修法。

**参考答案要点**
**缺口**：`realpath` 解析发生在**判定时**，而实际打开文件发生在**判定之后**——两者之间有一个窗口：

```
t0：realpath(path) → 得到工作区内的真实路径 → 判定通过 ✅
t1：（窗口期）攻击者把路径上的某个组件替换成指向 /etc 的 symlink
t2：open(path) → 实际打开 /etc/xxx ❌
```

这与 WebFetch 的 DNS rebinding（B06-0287）是**同一类 TOCTOU**，只是载体从 DNS 换成文件系统。

**为什么这里比 DNS 更容易被利用**：攻击者不需要控制 DNS，只需要能**在工作区里写**（而 Agent 本身就在写工作区）。`sub` 是普通目录 → 换成 symlink 即可。

**此外还有两处退化**：
1. **路径不存在时 `realpath` 不解析 symlink**（对不存在的路径，`realpath` 只做 `abspath` 式处理）→ 判一个「将要创建」的路径时，判定是**弱化版**；
2. **`readable_extra_roots` 只列存在的文件**（`:237-241`），但 allowed 根一旦进入判定，其**内部**的 symlink 仍会在打开时被解析。

**修法**：

| 修法 | 做法 | 代价 |
|---|---|---|
| ① **以解析后的真实路径做 I/O** | 判定时把 realpath 结果**一路传下去**，写/读都用它（而不是原路径） | 需要改调用链（工具拿到判定时同时拿到 canonical path） |
| ② **打开后校验**（`O_NOFOLLOW` / 打开后比对 realpath） | POSIX 用 `O_NOFOLLOW` 拒绝最后一段是 symlink；或 `fstat` 后比对 inode | Windows 需用 `FILE_FLAG_OPEN_REPARSE_POINT` 一类等价物 |
| ③ **目录句柄相对打开**（`openat` 语义） | 逐级用目录 fd 打开，天然免疫中间段替换 | 平台差异大、实现成本高 |
| ④ **回滚侧兜底** | 写路径已有 rewind 快照（B11），即使被写到区外也能恢复内容 | 只能补救，不能阻止 |

**评分要点**
- **及格**：知道 symlink 要用 realpath。
- **良好**：能指出「判定与使用之间有窗口」这一 TOCTOU 结构。
- **优秀**：给出**可落地修法**（①把 canonical path 传下去，或 ②`O_NOFOLLOW`/打开后比对），并指出「路径不存在时 realpath 不解析链接」这一退化情形。

**典型弱答**
- 认为 realpath 之后就没有 symlink 问题了；
- 只提「加黑名单/更严格正则」（解决不了时序）；
- 不知道 Windows 侧的等价机制。

**追问**
如果修法①要让调用链一路携带 canonical path，你会怎么改造接口而不破坏既有工具签名？

---

### XEYO-QA-0330 归一化不一致导致的判定碰撞

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 归一化面 | 大小写/分隔符/相对 | 困难 | 安全拷问 | `filesystem.py:113-124,323-353` |

**面试官提问**
路径判定里有**多种归一化**（大小写、分隔符、`abspath`、`realpath`、`normcase`、`relpath`）。请说明「归一化不统一」会怎么变成漏洞。

**参考答案要点**
代码里出现的归一化**不止一种**：

| 归一化 | 位置 | 作用 |
|---|---|---|
| `normalize_case_for_comparison` = `.lower()`（`:113-115`） | 路径狱比较 | Windows 大小写 |
| `expand_to_abs` = `expanduser` + `join` + `abspath`（`:118-124`） | 统一成绝对路径 | 折叠 `..` |
| `os.path.realpath`（`:139-147`） | 路径狱比较 | 解析 symlink |
| `os.path.normcase(rel)`（`:343`） | 受保护元数据 | 大小写 + 分隔符（**Windows 上还把 `/` 转成 `\`**） |
| `abs_path.replace("/", os.sep).replace("\\", os.sep)`（`:171,184`） | 组件拆分 | 手写分隔符统一 |
| `os.path.relpath`（`:340`） | 受保护元数据 | 转相对 |

**三类漏洞形态**：

| 形态 | 机制 |
|---|---|
| ① **大小写旁路** | 若某处忘了 `.lower()`/`normcase`，`SECRET.KEY` 或 `.SSH/x` 绕过小写清单（清单全部存小写） |
| ② **分隔符旁路** | 手写 `replace` 与 `os.path.normcase` 在**非 Windows** 上行为不同（`normcase` 在 POSIX 是 no-op），跨平台判定可能不一致 |
| ③ **相对/绝对不一致** | 受保护元数据用 `relpath` 相对**传入的 cwd**，而路径狱相对 **allowed 根**——若两者不同（`allowed_paths` 多根），同一路径在两处结论可能相反 |

★ **最值得指出的是 ③**：`protected_metadata_reason(path, cwd=cwd)` 只看**单个 root**（`cwd`），而 `path_in_allowed_working_path` 支持**多个 allowed 根**。当会话有多个允许根时，一个位于「第二根」下的 `.git` 会在**元数据判定里被当成区外而放行**（因为 `relpath` 以 `..` 开头即 return None，`:344-345`），但它在**路径狱**里是「区内」——**两条判定对同一路径给出不同结论**。

**评分要点**
- **及格**：知道要统一大小写处理。
- **良好**：能列出至少三种归一化并指出「谁和谁可能不一致」。
- **优秀**：**定位到 ③ 这个具体不一致**（受保护元数据只认单个 `cwd`，路径狱认多根 → 多根会话下 `.git` 保护失效）——这是本卷真实存在的一处边界问题，能自己推出来说明候选人具备权限模型的结构化理解。

**典型弱答**
- 认为「都 lower 一遍就够了」；
- 不知道 `normcase` 在 POSIX 是 no-op；
- 没意识到 `cwd` 与 `allowed_working_paths` 可能是**不同集合**。

**追问**
如果允许根是 `["/ws", "/other"]`，而 cwd 是 `/ws`，那么 `/other/.git/config` 的写裁决结果是什么？应该是什么？

---

### XEYO-QA-0331 权限单向性的两条实现路径

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 单向性（取消/降级不可越过） | 多入口一致性 | 困难 | 系统设计 | `runtime_mode.py:41-47,69-105` + `workspace_policy.py:6-10` |

**面试官提问**
「权限只能被收紧、不能被放宽」这条原则，在你负责的代码里会有**几个入口**可能违反它？请说明你如何系统地实现它。

**参考答案要点**
本卷可见**至少三处入口**都在实现/消费这条原则：

| # | 入口 | 实现方式 |
|---|---|---|
| ① **轮内模式切换** | `RuntimeModeStore.effective()`（`:99-105`） | `stricter(baseline, requested)` —— 放宽延到下一 turn |
| ② **仓库策略** | `workspace_policy` docstring（`:6-10`） | 策略文件的 `write` 只能**收紧**（`ask`/`always`）；`risk`/`never`/`allow` **不得**把用户更严的模式放宽 |
| ③ **preset** | `presets.py` docstring（`:4-6`） | `full` 只放宽「确认频率」，**不触碰** deny 黑名单 / 密钥 / 受保护元数据 / worker 沙箱 |

**三处共同依赖的基石**是 `_STRICTNESS` + `stricter()`（`:26,41-47`）——**把「严」变成可比较的量**，任何两处冲突都取更严者。

★ 系统的做法（可答作设计原则）：**不要在每个入口各写一次「取严」**，而是：

1. 定义**唯一**的序（`_STRICTNESS`）；
2. 所有入口**只产出「请求值」**，由一个公共函数求实效值（本卷的 `effective()` / `stricter()`）；
3. 硬拦（密钥 / 元数据 / 沙箱）**不参与比较**——它们是「无论多松都不放行」的绝对值。

★ 仓库策略那处还写明了**方向**（`:8-10`）：放宽只能走**用户侧**（env / grant store / preset），「仓库策略不再**反客为主**」——即**仓库文件（可提交、可被他人修改）不允许单方面放宽用户权限**。

**评分要点**
- **及格**：说出「只能收紧」这句话。
- **良好**：能举出至少两处入口，并指出 `stricter()` 是公共基础。
- **优秀**：把三处入口的**不同层次**讲清（请求级 / 仓库级 / 会话级），并指出**硬拦不参与比较**（它是绝对值）；进一步指出「仓库策略不得反客为主」这一威胁模型（仓库文件可能被他人改动）。

**典型弱答**
- 只在模式切换里实现取严，其他地方各写一套；
- 让仓库策略能放宽审批模式（等于让仓库作者替你降权限）；
- 把密钥/元数据也做成「可比较的档位」（它们必须是无条件硬拦）。

**追问**
如果新增第 4 个入口（例如远程通道携带的权限声明），你怎么保证它也不会违反单向性？（→ 只产出「请求值」，交给统一求值函数）

---

### XEYO-QA-0332 TTL 三档与「不超时」的风险

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | pending_ttl 取舍 | 分档与例外 | 困难 | 权衡取舍 | `pending_ttl.py:1-13,47-53` |

**面试官提问**
挂起 TTL 你分了几档？其中有一档**永不超时**——请为这个例外辩护，并说明它可能带来什么风险、你怎么兜住。

**参考答案要点**
三档（`:24-26,47-53`）：

| 档 | TTL | 理由 |
|---|---|---|
| 普通确认 | 180 s | 常规等待 |
| **危险操作** | **60 s** | 悬着的危险授权窗口本身是风险；更短 → 更快落到默认拒绝 |
| **AskUserQuestion** | **`None`（永不超时）** | 它是「问信息」而非「求授权」，用户可能真要时间去查证 |
| 提醒 | 到期前 30 s | GUI 倒计时高亮 |

**`AskUserQuestion` 永不超时的风险**：

| 风险 | 说明 |
|---|---|
| 回合无限期挂起 | 若用户离开，整个会话的回合**永久卡住**（不只是这一次调用） |
| 资源占用 | 挂起项驻留内存；`PendingPermissionStore` 的键一直存在 |
| 无人值守场景 | CI / 远程通道下没有「用户」可答 → 永久等待 |

**兜住的手段（可答）**：①**外部取消**（用户点停止 / 面板关闭 → `cancelled`，`:33-38`）；②**回合级超时**（引擎的 budget / abort 体系独立于此 TTL）；③`AskUserQuestion` **不做权限用途**（不承载授权语义，所以「永久挂起」最坏只是丢一个提问）；④调用方必须能**主动放弃**（否则不该用这个工具）。

★ 这一档的存在恰好说明「TTL 不是一个数，而是**按语义分档**」——授权类有默认答案（拒绝），信息类没有默认答案（无法替用户回答）。

**评分要点**
- **及格**：说出有分档与「提问不超时」。
- **良好**：说出危险档更短的理由，并指出永不超时的风险（回合挂死）。
- **优秀**：把「授权有默认答案、信息没有默认答案」这条判据讲清，并给出兜底手段（外部取消 / 回合级超时 / 工具语义限定）——即**不靠 TTL 兜住，而靠语义与取消通道兜住**。

**典型弱答**
- 所有档统一 180 s（危险窗口过长）；
- 让权限确认也永不超时（无人值守时永久挂起）；
- 只答「有超时就行」，没有分档理由。

**追问**
`ttl_for_request` 判「危险」靠 `reason`/`matched_rule` 里的**关键字**匹配。这种「用文案判风险」的脆弱之处在哪？你会怎么改？

---

### XEYO-QA-0333 广播快照为什么不能透支权限

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | runtime_mode 广播 | 状态广播 ≠ 权限 | 困难 | 场景设计 | `runtime_mode.py:14-18,107-154` |

**面试官提问**
你打算把「当前审批模式」注入模型上下文，让模型知道现在是什么模式。这件事有什么风险？你怎么设计才安全？

**参考答案要点**
docstring 把原则写明了（`:14-18`）：

```
模型同步（增量快照 + supersedes）：同一 store 携带 ``_last_broadcast``，
turn 边界复位为 None 强制首次全量快照；轮内仅变更时重发……
快照只是广播，**不透支任何权限**——真开关始终在 ToolRegistry 准入 gate。
```

**四条设计**：

| 设计 | 实现 | 理由 |
|---|---|---|
| **广播 ≠ 授权** | 真开关在准入 gate（`evaluate_policy`） | 模型「知道」模式不改变「能不能做」 |
| **只在 turn 首广播** | `mark_turn_broadcast`（`:107-119`）：仅轮首有活值且未广播才 True | 避免弱模型在**回合中途**被新增背景块带偏 |
| **增量 + supersedes** | `runtime_mode_snapshot_text`（`:145-154`）：「This snapshot supersedes earlier runtime-mode snapshots.」 | 防「多份快照并存」导致模型读到旧结论 |
| **纯状态陈述** | docstring（`:146-149`）「刻意去掉一切引导/要求性措辞（避免弱模型误当用户新指令而重做任务）」 | 符合「只给信息不给指令」 |

**★ 最大的风险是「让模型以为广播就是许可」**：例如播报「当前审批模式: never（自动放行）」，弱模型可能把它读成「用户已经同意你做任何事」，从而**跳过本应有的谨慎**。所以设计上必须做到两点：①文案是**状态陈述**（不是「你可以…」）；②**真实门禁不依赖广播**（广播漂移/丢失不会放宽权限）。

**评分要点**
- **及格**：说出广播要让模型知道模式。
- **良好**：说出「广播不透支权限」这条原则，并指出真开关在准入 gate。
- **优秀**：指出**「轮中途广播会带偏弱模型」**这一具体风险（因此只在 turn 首广播），以及「supersedes」措辞的必要性（防旧快照并存）；并强调文案是纯状态陈述而非指令。

**典型弱答**
- 把广播当作权限来源（「已广播 = 已授权」）；
- 轮内任意时刻都广播（弱模型被中途的背景块带偏）；
- 在广播里写「你现在被允许执行 X」（指令式措辞）。

**追问**
如果广播**丢失**（注入失败）而模式其实是 `always`，会有什么后果？为什么这个方向可接受？

---

### XEYO-QA-0334 为什么盘符根与仓根必须拒绝

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | write_scope 过宽判定 | 根的识别 | 困难 | 安全拷问 | `python/permissions/write_scope.py:63-103` |

**面试官提问**
子 agent 声明 `scope=["src", ".", "C:"]`。请逐项说明你的处置，并说明为什么「盘符根」这类写法比「仓根」更危险。

**参考答案要点**
逐项处置（`normalize_worker_scope`，`:63-103`）：

| 项 | 判定 | 处置 |
|---|---|---|
| `src` | 仓内相对路径 → `rel = "src"` | **保留** |
| `.` | 命中 `norm in (".", "./", "")`（`:68`） | 丢弃 + `broad = True` |
| `C:` | 命中盘符根判定（`:72-77`） | 丢弃 + `broad = True` |

最终返回 `(["src"], False, "scope_too_broad")`——**保留合法项、丢掉过宽项、reason 标注**。

**盘符根判定**（`:72-77`）：

```python
		if len(norm) <= 3 and (
			norm in ("/", "\\")
			or (len(norm) >= 2 and norm[1] == ":" and (len(norm) == 2 or norm[2:] in ("", "/")))
		):
			broad = True
			continue
```

**为什么盘符根比仓根更危险**：

| 写法 | 实际范围 |
|---|---|
| `.` / 仓根 | 整个**工作区**（至少还受路径狱约束） |
| `C:` / `C:/` / `/` | **整个盘 / 整个文件系统** —— 包含系统目录、用户目录、**其他项目**、以及 `~/.ssh` 这类凭据目录 |

而且 `C:` 这种写法**容易被误认为相对路径**（不带斜杠），若不做专门识别就会漏过——这正是它必须**单独判**的原因（不能只靠「是不是 `.`」来判断过宽）。

★ 还有一条**方向**：仓外（`..` 开头或绝对路径）在 `:92-95` 被**当作无效**（不扩大权限），而不是「拒绝整个 scope」——这是「不因一条坏声明废掉全部」的取舍；只有 **`broad and not out`**（全部过宽）才整体降级为只读。

**评分要点**
- **及格**：说出 `.` 不能作为 scope。
- **良好**：说出 `.`、盘符根、仓根三类都要拒，并说出「保留合法项」而非整体拒绝。
- **优秀**：指出盘符根的**双重危险**（范围到整个文件系统 + 形似相对路径易漏判）；并指出 `broad and not out` 才整体降只读的精细度。

**典型弱答**
- 只判 `.`（`C:` 漏，等于给全盘写权限）；
- 有一条过宽就整体拒绝（合法项被牵连）；
- 把 `..` 与过宽混为一谈（前者是仓外，后者是过宽）。

**追问**
如果模型传 `scope=["C:\\"]`（带反斜杠）与 `scope=["C:/"]`，你的判定都能覆盖吗？`norm.replace("\\","/")` 之后是什么形态？

---

### XEYO-QA-0335 读可以放宽、写为什么不能

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 读写放宽的不对称 | 作用域声明 | 困难 | 对比辨析 | `filesystem.py:191-199,287-303` |

**面试官提问**
同一个「额外根」列表，为什么注释强调它只用于**读**裁决、写裁决不得包含？

**参考答案要点**
注释（`:192-194`）：

```
	仅用于**读**裁决；写裁决不得包含。当前含：
	- 当前工作区的记忆库目录 ~/.xeyo/memory/{workspace_id}
	- **仅当前会话**的转录文件（jsonl 及其 .old1/.old2 归档）
```

**为什么读可以放宽、写不能**：

| 维度 | 读 | 写 |
|---|---|---|
| 失败后果 | 读到不该读的内容（信息泄漏，**可审计、可追责**） | 写坏不该写的文件（**不可逆的数据破坏**：记忆库是长期资产、转录是权威记录） |
| 是否需要 | 高：不读记忆库/转录，记忆检索与续跑都做不到 | 低：这些目录的写入由**引擎自己的模块**完成（`memdir.write_note` / `record_transcript`），不需要给工具放开 |
| 攻击面 | 越读 → 信息泄漏 | 越写 → 伪造记忆 / 篡改转录 → **污染后续所有上下文**（比泄漏更危险，因为它会改变未来行为） |

★ 第二行是关键：**这些目录的写入路径本来就不经过工具权限门**（它们由引擎模块直接落盘）。所以给工具放开写毫无收益，只有风险。

★ 但本卷标注了一处**真实张力**：写裁决在最后一步复用了读裁决（`return check_read_permission_for_path(...)`，`:303`），而读裁决**内部**会追加 `readable_extra_roots`——所以写裁决**实际上**也会享受这份放宽，与注释「写裁决不得包含」不一致（见 0315）。

**评分要点**
- **及格**：说出读放宽是为了功能可用。
- **良好**：能对比两类后果（信息泄漏 vs 不可逆破坏）并指出「这些目录的写不需要给工具」。
- **优秀**：**发现注释与调用链的不一致**（写裁决复用读裁决 → 额外根也生效），并指出这是需要修的实现问题（或需要显式排除）。能指出「越写会污染未来上下文」比「越读泄漏」更危险。

**典型弱答**
- 认为「读能放宽写也应该能」（忽略不可逆性）；
- 不知道这些目录的写由引擎模块自己完成；
- 没发现复用带来的实际放宽。

**追问**
如果要让写裁决**显式排除**额外根，最小改法是什么？（→ 写裁决不调用读裁决，或读裁决接受一个「是否含额外根」的参数）

---

### XEYO-QA-0336 延迟导入解决了什么问题又带来什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 循环依赖 | 模块分层 | 困难 | 代码阅读 | `filesystem.py:247-258` |

**面试官提问**
这段代码在函数**内部**才 import 另一个模块。请说明它为什么这么做，以及这种写法有什么代价。

```python
def _max_outside_allowed() -> bool:
	"""最高档（never/allow=免确认）是否允许越出工作区读/写。

	延迟读 policy（避免 filesystem % policy 模块级循环 import；调用时两者已加载）。
	仅放宽「工作区外」这一**权限级**边界；密钥/危险路径仍按下文硬拦/ASK。
	"""
	try:
		from permissions.policy import is_max_permission_mode
		return is_max_permission_mode()
	except Exception:  # noqa: BLE001 — 权限模式读取失败不放松（默认区外 DENY）
		return False
```

**参考答案要点**
`filesystem.py:247-258` —— 三件事同时做了：

| 做法 | 解决什么 |
|---|---|
| **函数内 import** | `filesystem` 与 `policy` **互相依赖**（policy 用 filesystem 的判定，filesystem 用 policy 的模式）→ 模块级 import 会循环 |
| **`try/except` 包住** | 权限模式读取失败时**不放松**（返回 `False` = 区外 DENY）——**fail-closed** |
| **只在需要时导入** | 热路径上大部分裁决并不需要问「是不是最高档」（先判边界，区外才问），导入成本落在少数分支 |

**代价三条**：

| 代价 | 说明 |
|---|---|
| 每次调用都要走 import 机制 | Python 有 `sys.modules` 缓存，成本很低但非零；**热路径上会被反复执行** |
| **隐藏依赖** | 模块级 import 一眼能看出的依赖关系，被藏进函数体 → 架构依赖图不再完整（本卷的「边界声明」正需要人工梳理） |
| 循环依赖本身没被消除 | 只是绕开而非解耦；后续再加交叉调用会更难维护（正确解法是抽出**第三个模块**放共用判定，或让判定单向依赖） |

★ 但这里有一个**正确取向**值得表扬：`except` 里返回 `False`（**不放松**）而不是 `True`——即「读不到权限模式时按更严处理」。这与 B05-0215（缓存失效 fail-closed）、B06-0267（DNS 失败即拒绝）是同一条纪律。

**评分要点**
- **及格**：说出「为了避开循环 import」。
- **良好**：说出 `try/except` 的 fail-closed 取向（读不到模式就不放宽）。
- **优秀**：指出**代价**（依赖被藏起来、循环本身没解耦），并给出结构性替代（抽出共用模块 / 单向依赖）；能把「fail-closed 在这里的具体表现」说清（区外 DENY 是默认，放宽是例外）。

**典型弱答**
- 认为函数内 import 只是「代码风格」；
- 把 `except` 写成返回 `True`（读不到就放宽 = 最危险的默认）；
- 不知道这是循环依赖的绕行而非解决。

**追问**
`permissions/policy.py` 与 `filesystem.py` 之间存在双向依赖。你会怎么重构掉这个环？（→ 抽出「模式枚举 + 严格度比较」到独立小模块，两者都单向依赖它）

---

### XEYO-QA-0337 授权指纹该绑定什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | store 授权存储 | 指纹绑定的身份面 | 困难 | 系统设计 | `python/permissions/store.py:271-288,419-503` |

**面试官提问**
用户批准了一次工具调用，你把它存成「授权」，下次同类调用不再问。这个授权的**身份**该由什么计算？参数要不要进指纹？

**参考答案要点**
`store.py` 的三段结构：

| 组件 | 位置 | 作用 |
|---|---|---|
| `PermissionGrant` + `PermissionGrantStore` | `:275-418` | 授权持久化（含 `DEFAULT_GRANT_TTL_SEC = 24 * 3600.0`，`:271`） |
| `canonical_args(tool_input)` | `:419-440` | 把工具入参**规范化**（供比对/指纹） |
| `mcp_grant_fingerprint(registered_tool_name)` | `:444-457` | MCP 工具的指纹：`sha256(注册名)[:32]`，前缀 `"v2:"` |
| `grant_fingerprint(...)` | `:459-502` | 通用入口（`:482` 处对 MCP 身份转调上面那个） |

**核心问题的答案：MCP 工具的指纹绑定的是「注册名」，显式**不含参数****——`:449` 的说明是：

```
- 返回 ``v2:<32hex>``；身份不可用 → 空串（不可落 grant，fail-safe）。
```

再结合 `_MCP_FP_VERSION = "v2"`（`:441`）。

**为什么参数不能进指纹**：因为工具入参里可能含**模型可控文本**（文件内容、命令字符串）。若参数进指纹，攻击者可以用「参数不同 → 指纹不同」来**制造新授权**绕过既有拒绝；反之，「模型可控内容能影响授权身份」本身就是**注入面**。所以指纹只绑**稳定的身份**（工具名/注册名），参数留给 `canonical_args` 做**单次**比对面的用途。

**两处方向安全**：
- **身份不可用 → 空串**（`:449`）→ 不可落 grant（`fail-safe`）——即「算不出身份就不给持久授权」；
- **带版本前缀 `v2:`** → 旧版指纹（v1）与新指纹**不匹配**，等价于自动失效历史授权（升级时的安全默认）。

★ `DEFAULT_GRANT_TTL_SEC = 24 * 3600`（24 小时）说明「授权不是永久」——即使指纹固定，也有时间上界。

**评分要点**
- **及格**：说出授权要绑定工具身份。
- **良好**：说出**参数不进指纹**，并给出理由（模型可控内容 + 制造新授权绕过）。
- **优秀**：指出两处方向安全（身份不可用给空串 → 不落 grant；版本前缀 `v2:` 让旧授权自动失效），并指出 24h TTL 的存在意义（授权有时间界）。

**典型弱答**
- 用「工具名 + 完整参数」做指纹（模型可控参数 → 授权身份被污染）；
- 身份算不出时给一个默认指纹（应给空串、不落 grant）；
- 让授权永久有效。

**追问**
如果同一工具的两个**不同** MCP server 注册了同名工具，指纹会冲突吗？你会把什么加进身份？（→ 需要 server 维度）

---

### XEYO-QA-0338 工具级检查与 registry 谁说了算

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 双重裁决的职责 | 工具内检查的作用 | 困难 | 权衡取舍 | `filesystem.py:396-435` + `gate.py:13-18` |

**面试官提问**
如果 registry 已经做了完整裁决，工具**内部**为什么还要再查一遍权限？两边会不会互相矛盾？

**参考答案要点**
两边**职责不同**，且工具内的检查是**纵深防御**：

| 层 | 位置 | 判什么 | 遇到 ASK 时 |
|---|---|---|---|
| **registry 准入 gate** | `ToolRegistry.run` → `evaluate_policy` | 完整策略（含挂起流程） | **挂起**等用户决定 |
| **工具内检查** | 各工具的 `check_permissions` → `check_*_permission_for_tool` | 只做**路径裁决**（区外/密钥/危险） | **只信 `preapproved`**（`:414-415,433-434`） |

工具内入口的 docstring 把分工写得很清楚（`:401-406`）：

```
	只做路径裁决：ALLOW 放行；DENY 拒绝。
	ASK 仅在 registry 已批准（preapproved）时放行，不再二次把 ASK 降成 DENY 语义混淆——
	未批准的 ASK 直接 False，由 registry 挂起流程负责。
```

**为什么需要工具内这道**：

| 理由 | 说明 |
|---|---|
| **工具可能被非 registry 路径调用** | 例如单元测试直接 `tool.execute(...)`、CLI 直连、子 agent 的独立执行路径（`gate.py` 正是为这类调用方保留的兼容层，见 0312） |
| **参数解析差异** | registry 看的是**原始 dict**，工具内看的是**解析后的 dataclass**（`_extract_path_from_input` 同时支持 dict 与 dataclass，`:379-393`）——后者能拿到 registry 看不到的规范化路径 |
| **fail-safe 方向** | 少一道检查 = 一次「未经路径狱的写」；多一道检查 = 最多多一次拒绝（可诊断） |

**不会矛盾的原因**正是 `preapproved` 标记：工具内遇到 ASK 时**复用上层结论**（而不是重新判决）。

**评分要点**
- **及格**：说出「多一层更安全」。
- **良好**：说出工具内**只做路径裁决**、ASK 只信 `preapproved`（即不重复判决、只做纵深）。
- **优秀**：给出**需要这道检查的具体理由**（非 registry 调用路径、参数解析层不同），并指出 `_extract_path_from_input` 同时支持 dict 与 dataclass 这一设计正是为「两条调用路径」准备的。

**典型弱答**
- 认为工具内检查是冗余、可以删（非 registry 路径会失去全部路径狱）；
- 让工具内也跑完整 `evaluate_policy`（会重复挂起、语义混乱）；
- 不理解 `preapproved` 为什么必要（→ 0311）。

**追问**
如果工具内检查与 registry 结论**真的**相反（例如路径在两次解析之间变了），应该以谁为准？这暴露了什么共性问题？（→ 0329 的 TOCTOU）

---

### XEYO-QA-0339 兼容层的 ASK→DENY 会不会伤到用户

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | gate 兼容层代价 | 用户体验与安全 | 困难 | 权衡取舍 | `gate.py:1-71` + `filesystem.py:356-367` |

**面试官提问**
兼容层把 ASK 降级成 DENY。对**走兼容层的生产调用方**，用户会有什么体验？你会怎么限制这个风险？

**参考答案要点**
**体验后果**：用户**无法批准**任何需要确认的操作。

| 场景 | 走 registry（正常） | 走兼容层 |
|---|---|---|
| 写工作区外文件 | 弹窗 → 用户同意 → 执行 | **直接拒绝**（用户看不到弹窗） |
| 读危险路径（如 `.git/config`） | ASK → 可批准 | **直接拒绝** |
| 密钥路径 | 拒绝（一致） | 拒绝（一致） |

结果是**功能性地失去一类能力**，而且用户看到的只是「被拒绝」，**不知道本来可以批准**——这是最伤体验的一点（无解释的拒绝）。

**限制风险的三种做法**：

| 做法 | 说明 |
|---|---|
| **注释标注真源** | `gate.py` docstring 已写「生产路径请走 ToolRegistry + evaluate_policy（保留 ASK 挂起）」 |
| **保留可诊断原因** | `_deny_reason`（`:31-45`）把 ASK 映射成 `path_outside_working_directory` / `dangerous_path`——**至少能看出「这是需要确认的操作」而不是「被禁止的操作」** |
| **收窄可见面** | 不在包公开 `__init__` 里导出兼容 API（只给旧测试按路径导入）；或加 deprecation 标记 |

★ 还有一个更根本的做法：**让「需要确认」在二元 API 里有独立的原因码**（`enforce_decision` 已给出 `needs_confirmation`，`:365-366`）——调用方/日志能区分「缺 UI」与「规则禁止」。

**评分要点**
- **及格**：说出会直接拒绝。
- **良好**：指出「用户不知道本可以批准」这一体验损失，并说出 `_deny_reason` 的补救作用。
- **优秀**：给出**三类**限制手段（注释/原因码/可见面收窄），并指出根因是「二元 API 无法表达第三种结果」——所以**问题不在于兼容层实现，而在于调用方接口能力**。

**典型弱答**
- 认为兼容层只是「少个功能，无所谓」；
- 让兼容层静默批准（最危险方向）；
- 把原因码也一并丢掉（连诊断都不可能）。

**追问**
如果一定要给这些调用方保留「可批准」能力，最小的接口改动是什么？（→ 让它们拿到 `needs_confirmation` 并接入挂起 store，而不是返回 bool）

---

### XEYO-QA-0340 子 agent 的权限该继承还是该收窄

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 子 agent 权限模型 | 继承与收窄 | 困难 | 场景设计 | `write_scope.py:15-29,148-157` + B06-0253 |

**面试官提问**
主会话派一个子 agent 去改代码。子 agent 的写权限应该「继承主会话」还是「由下发方声明」？请给出你的模型。

**参考答案要点**
实现取的是**「由下发方声明 + 空即只读」**：

| 层 | 机制 |
|---|---|
| 工具面 | `Agent` 的 `scope` 空 → **移除 `Write`/`Edit`**（B06-0253） |
| **上下文层** | `write_scope` ContextVar（`:15-43`）：`None` = 主会话不限制、`()` = 子 agent 只读、非空 = 白名单前缀（0323） |
| **执行层** | 文件工具在 `write_store is None` 且 `get_write_scope() is not None` 时**抛错拒绝直写**（B04-0168） |
| 存储层 | 子 agent 的写必须经 `WriteStore`（base hash + 分片锁 + 租约，B03） |

**为什么是「收窄」而不是「继承」**：

| 维度 | 继承主会话 | 声明 + 收窄（现状） |
|---|---|---|
| 默认 | 子 agent 一开就有主会话全部权限 | 默认**只读**（方向安全） |
| 爆炸半径 | 一个跑偏的子 agent 能改整个工作区 | 只能改声明过的路径 |
| 可追责 | 事后难判断「这次改动是哪个 agent 做的」 | scope + agent_id 一起进 journal/快照 |

★ 三层的一致性值得指出：**工具面移除**（模型看不到）→ **上下文层白名单**（能写但受限）→ **执行层拒绝直写**（必须经 store）。这三层不是冗余，而是**同一约束在不同层次的表达**——任何一层被绕过，下一层仍然拦。

**评分要点**
- **及格**：说出要给子 agent 限范围。
- **良好**：说出「空 scope = 只读」这一默认，并指出三层（工具面/上下文/执行层）至少两层。
- **优秀**：把三层讲成「同一约束的分层表达」而不是冗余，并指出「执行层拒绝直写」的意义——它防的是**绕过工具面的路径**（例如子 agent 幻觉调用了被移除的工具、或经别的写入路径落盘）。

**典型弱答**
- 让子 agent 继承主会话全部权限（爆炸半径大）；
- 只有工具面移除（执行层没有兜底）；
- 认为 `write_scope` 与 `Agent.scope` 是两套无关机制（它们是同一约束的两层）。

**追问**
子 agent 写工作区**外**的文件时，是 `write_scope` 拦还是路径狱拦？两者的拒绝原因码一样吗？

---

### XEYO-QA-0341 放宽受保护元数据的开关该不该存在

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | filesystem 硬保护的可放宽性 | 开关设计 | 困难 | 安全拷问 | `filesystem.py:318-321,323-353` |

**面试官提问**
我们给 `.git` / `.xeyo` / `.agents` 做了硬保护，但留了一个环境变量可以放宽。这个开关该存在吗？如果留，怎么控制风险？

**参考答案要点**
开关本体（`:318-321`）：

```python
def _protected_metadata_allowed() -> bool:
	raw = os.environ.get(ENV_ALLOW_PROTECTED_METADATA, "").strip().lower()
	return raw in ("1", "true", "on", "yes")
```

命中即 `protected_metadata_reason` 直接返回 `None`（**整个硬保护关闭**，`:332-333`）。

**该不该存在——两面都要答**：

| 支持保留 | 反对 |
|---|---|
| 有些正当工作确实要改 `.git`（例如脚本化维护 hook、仓库迁移工具） | 它是**全局环境变量**，粒度是「所有会话 + 所有路径」，太粗 |
| 没有开关，用户会绕过（去改代码 / 用 Bash 也能碰 —— 不过 Bash 同样受本判定约束） | 一旦被设上，任何会话都能写 `.git` —— **权限倒挂**（本应最受保护的东西可写） |
| 硬保护本身有误伤面（合法嵌套仓库，见 0318） | 缺少「谁设的、什么时候设的」记录（环境变量看不见归属） |

**如果保留，风险控制手段**：

| 手段 | 说明 |
|---|---|
| **收窄粒度** | 改成会话级/路径级开关（而不是进程级 env），例如只在显式会话参数里允许 |
| **留审计** | 每次放宽生效时记一条审计事件（当前实现**无痕迹**——它甚至不查会话，纯粹读 env） |
| **失败方向** | 当前默认关（`""` 不在列表里 → 不放宽），方向安全 ✅ |
| **可见性** | 在 GUI/日志里显示「受保护元数据保护已关闭」，避免用户不知情 |

★ 值得注意的一点：本判定**不看会话、不看路径** —— 它只读环境变量。所以它的**作用域是进程级**，这与「per-session 活状态」的其余设计（`RuntimeModeStore` / `RuntimePresetStore`）不在同一粒度上。

**评分要点**
- **及格**：说出有这个开关、默认关。
- **良好**：指出它粒度太粗（进程级 env、不区分会话/路径）与缺少审计。
- **优秀**：给出「收窄粒度 + 留审计 + 保持默认关 + 界面可见」的完整处置，并指出它与项目其余「per-session 活状态」的粒度不一致。

**典型弱答**
- 认为「有开关很危险，必须删」（没回答「正当需求怎么办」）；
- 认为「默认关就安全」（忽略粒度与审计）；
- 把环境变量当成可信配置（它其实是攻击面，与 B06-0271 的「用户可填 URL」同类）。

**追问**
如果改为「仅当前会话 + 仅显式路径」的放宽，你会把它放在哪个 store 里？（→ 参照 `RuntimePresetStore` 的 per-session 活值）

---

### XEYO-QA-0342 权限用的 cwd 与工具跑在的目录不一致

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | cwd 来源与解析链 | 判定基准不一致 | 困难 | 故障排查 | `filesystem.py:47-64,370-376,437-445` |

**面试官提问**
权限判定要一个 `cwd` 作基准。请说明这个 cwd 可能来自哪几个地方，以及「判定用的 cwd」与「工具实际运行的目录」不一致会造成什么。

**参考答案要点**
`filesystem.py` 里有**三处** cwd 来源：

| 来源 | 位置 | 优先级 |
|---|---|---|
| 显式传入的 `context.cwd` | `_tool_cwd`（`:370-372`） | 最高 |
| 工具实例的 `tool._cwd` | `_tool_cwd`（`:373-375`） | 次之 |
| **进程当前目录** `os.getcwd()` | `_tool_cwd`（`:376`） | 兜底 |

而 `default_permission_context`（`:47-64`）在**没有显式 cwd 时**会去读**会话级 WorkspaceContext**，docstring 说明了理由：

```
	显式传入 cwd 时以其为准；为空时优先读会话级 WorkspaceContext，
	避免多并发会话读取模块级全局 cwd 而串目录。
```

即：**兜底路径也被刻意绕开了模块级全局 cwd**（防并发串目录，与 B05-0230 的容器路由串线同一类问题）。

**不一致会造成什么**：

| 不一致形态 | 后果 |
|---|---|
| 判定用 `cwd=A`、工具实际跑在 `cwd=B` | 相对路径 `x.txt` 在判定时被解析成 `A/x.txt`，实际写到 `B/x.txt` —— **判定与实际操作的对象不是同一个文件** |
| 多会话并发 | 若用模块级全局 cwd，会话 A 的调用可能按会话 B 的目录判定 → **串目录**（已在注释里点明并规避） |
| 工具自带的 `_cwd` 与调用方传入的 context 不同 | `_tool_cwd` 让 context 覆盖 `_cwd`——即**调用方决定基准**，但工具内部其它地方可能仍用 `self._cwd`（潜在不一致） |

**根因分类**：这类问题的本质是**「判定基准」与「执行基准」是两个来源**。防御原则是**让它们同源**：判定完成后把解析出的**绝对路径**一路传下去（与 0329 的修法①同构）。

**评分要点**
- **及格**：说出 cwd 影响相对路径解析。
- **良好**：说出三层优先级，并指出「判定基准 ≠ 执行基准」会导致判定的对象与实际操作的对象不同。
- **优秀**：指出 `default_permission_context` **刻意绕开模块级全局 cwd** 是为了防并发串目录（并发意识）；并给出结构性方向（判定与执行共用同一次解析结果）。

**典型弱答**
- 认为 cwd 只是个参数、无关紧要；
- 用 `os.getcwd()` 作为唯一来源（多会话/子 agent 场景必串）；
- 没意识到工具内还有 `self._cwd` 这个第二来源。

**追问**
如果 `Bash` 工具的 `working_directory` 参数让命令跑在子目录里，权限判定用的是哪个 cwd？应该用哪个？（→ 应当用**实际运行目录**，`BashTool.check_permissions` 的 `cwd=` 参数正是为此）

---

### XEYO-QA-0343 ASK 的语义债：三态里最难实现的一态

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | ASK 的实现成本 | 语义债 | 困难 | 权衡取舍 | `filesystem.py:356-367` + `policy.py:54-72` + `pending_ttl.py` |

**面试官提问**
三态里最贵的是 ASK：它要求挂起、跨进程回执、超时、多入口。请估算它的实现成本，并说明「把它砍掉」的代价，以及折中方案。

**参考答案要点**
ASK 的**完整实现面**（本卷可见的部件）：

| 部件 | 位置 | 职责 |
|---|---|---|
| 决策对象 | `PolicyDecision`（`policy.py:54-72`） | 带 `prompt` / `matched_rule` / `choices` / `peer_summary`，**供弹窗展示** |
| 挂起存储 | `PendingPermissionStore`（`store.py:61-244`） | 以 `request_id` 为键、幂等 resolve、唤醒信号、审计 |
| 超时 | `pending_ttl` | 分档 TTL + 提醒 + 三条结果文案 |
| 文案 | `_prompt_for_read/_write/_bash/_outbound/_agent/_ui`（`policy.py:447-506`） | 六类**人类可读提示** |
| 双入口 | 桌面 + 微信（`store.py:4-5`） | 「桌面 / 微信 resolve 均走本 store」 |
| 预批准 | `preapproved`（0311） | 防双重裁决误拒 |
| 二元兼容 | `enforce_decision` / `gate`（0310/0312） | 给不会挂起的调用方 |

**砍掉的代价**：

| 砍法 | 后果 |
|---|---|
| 折叠为 ALLOW | 静默放行（危险） |
| 折叠为 DENY | 一类操作**永远无法执行**（用户无法授权）——功能缺失且**用户不知道为什么** |
| 保留但只在 GUI 生效 | 非 GUI 面（cli/tui/remote）行为不一致——本项目 `_NON_GUI_SURFACES` 正是处理这类面差异（`policy.py:139`） |

**折中方案**：

1. **保留三态，但对**无 UI 面**先降级**（`enforce_decision` 的 ASK→DENY）——本项目已这么做；
2. **按操作风险选择性挂起**：低风险自动放行（`_AUTO_WRITE_MODES` 覆盖常规写），高风险才挂起——即**用审批模式档位控制 ASK 的出现频率**，把成本花在真正需要的少数调用上；
3. **授权持久化**（`PermissionGrantStore` + 指纹 + 24h TTL）——同一授权不必反复问，**把 O(每次) 降到 O(首次)**。

★ 第 3 条是这道题的关键洞察：**ASK 的成本主要不在「问一次」，而在「反复问」**。所以 `PermissionGrantStore` 是让三态在经济上可行的部件。

**评分要点**
- **及格**：说出 ASK 需要 UI 与等待。
- **良好**：能列出至少四个部件（挂起存储 / 超时 / 文案 / 多入口），并说出砍掉的两难。
- **优秀**：指出**授权持久化把成本从每次降到首次**，以及**审批模式档位控制 ASK 频率**——即「不是把 ASK 做廉价，而是让它少发生」。这两条是本项目让三态可落地的关键取舍。

**典型弱答**
- 认为 ASK 只是「弹个窗」；
- 主张砍掉 ASK 只留两态（忽略「永不可批」的代价）；
- 忽略非 GUI 面的行为一致性。

**追问**
在**评测/无人值守**场景，ASK 必然落到 `unavailable`。此时你会怎么配置让评测可复现（既不静默放行，也不因超时大量失败）？

---

### XEYO-QA-0344 【超压】挂起与并发的竞态面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 挂起/模式/授权三方并发 | 竞态 | 超压 | 故障排查 | `store.py:1-60,295-418` + `runtime_mode.py:50-127` + `pending_ttl.py` |

**面试官提问**
**故障背景**：并发场景下出现过「用户明明点了拒绝，操作却执行了」。已知系统有 `PendingPermissionStore`（挂起）、`RuntimeModeStore`（模式）、`PermissionGrantStore`（授权）三个有状态组件。请找出**所有**可能导致「拒绝被绕过」的竞态路径，并给出复现思路。

**参考答案要点**
**三条独立竞态路径**（每条都能单独造成该故障）：

**① 同一 `request_id` 的双入口竞态**（`store.py:1-6`）：「桌面 / 微信 resolve 均走本 store」「同一 `request_id` 只能被处理一次」。若幂等检查**不是原子的**（先查后写、无锁/CAS）：

```
t0 桌面线程：读到「未决」
t1 微信线程：写入 allow
t2 桌面线程：写入 deny   ← 覆盖（或反之）
```

结果取决于调度——**用户看到的与生效的可能不一致**。复现：对同一 `request_id` 并发发两个反向 resolve（例如脚本同时调两个入口），循环几百次应能观察到翻转。

**② 轮内模式放宽竞态**（`runtime_mode.py:69-105`）：这正是单向性要防的场景（0320）。若 `set()` 没有「收紧时同步抬升基线」那一行，则：

```
t0 用户批准危险操作（ASK 通过）
t1 用户把模式调到 never
t2 同轮剩余调用 → effective() = requested = never → 自动放行
```

★ 注意**单向性只覆盖「轮内」**：`begin_turn` 之后基线会重拍成活值，所以**下一轮**放宽是允许的。若有人误以为「模式切换永不即时放宽」，就会漏掉「跨轮」这一合法路径。

**③ 授权存储与拒绝的竞争**（`store.py:295-418`）：`PermissionGrantStore` 让同类调用**不再问**。若一次拒绝**没有**同步清理/不落入「负面记录」，而此前存在一条同指纹的 grant（24h TTL 内）：

```
t0 用户曾 allow 过同类调用（落 grant）
t1 用户本次 deny（用户预期：这次不做）
t2 下次同类调用 → 命中 grant → 不问 → 执行
```

用户会认为「我拒绝过它怎么又做了」——**其实是「以前的授权仍然有效」**。这是**语义问题伪装成竞态**：需要明确「一次 deny 是否撤销已有 grant」。

**复现思路（可答）**：①写一个脚本对同一 `request_id` 并发 resolve（反向）；②在单轮里提交多个工具调用 + 中途切模式；③先 allow 一次建立 grant，再 deny 一次，然后重发同类调用观察是否仍命中 grant。

**评分要点**
- **及格**：说出一处竞态（通常是双入口）。
- **良好**：说出两处，并能指出「幂等需要原子性（锁/CAS），先查后写不够」。
- **优秀**：三条都给全，尤其**第三条「deny 是否撤销已有 grant」**——这不是时序竞态而是**语义缺口**，能识别两者的区别说明候选人有状态模型思维；并指出单向性只覆盖轮内（跨轮放宽是合法的）。

**典型弱答**
- 只答「加锁就行」而不说哪把锁保护什么；
- 把三条混成一条（无法定位修复点）；
- 认为「同一 request_id 只能处理一次」这句注释就等于实现了原子性。

**追问**
第 ③ 条你会怎么定语义？（→ 显式选择：deny 撤销同指纹 grant / deny 只影响本次；无论哪种都必须写进文档与审计）

---

### XEYO-QA-0345 【超压】权限模型越权面总账

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 全卷总账 | 完整威胁模型 | 超压 | 安全拷问 | 全卷（`filesystem.py` / `policy.py` / `store.py` / `write_scope.py` / `workspace_policy.py`） |

**面试官提问**
请把这一卷读到的权限模型，按「**能不能真的越权**」排优先级，列出一份绕过面清单，并给出纵深防御方案。

**参考答案要点**
**先摆已有的防护**：三态裁决 + 路径狱（双 realpath）+ 密钥/危险/受保护元数据三道硬拦 + 审批模式单向性 + preset 硬边界 + write_scope 三层 + 授权指纹（不含参数）+ 挂起 TTL + fail-closed 的策略文件。

**绕过面清单（按可利用性排序）**：

| # | 绕过面 | 机制 | 现有防护 |
|---|---|---|---|
| 1 | **判定与使用的 TOCTOU** | realpath 在判定时解析，open 在之后 | ❌ 未覆盖（0329） |
| 2 | **判定基准不一致** | 权限 cwd ≠ 工具执行目录（0342） | ⚠️ 靠调用方传对 cwd |
| 3 | **多 allowed 根下元数据保护失效** | `protected_metadata_reason` 只认单个 `cwd`；路径狱认多根（0330） | ❌ 未覆盖 |
| 4 | **`XEYO_ALLOW_PROTECTED_METADATA`** | 进程级 env 一开，全会话 `.git` 可写（0341） | ⚠️ 默认关但无审计 |
| 5 | **preapproved 标记泄漏** | 若不复位 → 后续调用永久预批准 | ✅ 已用 `finally: reset`（0311） |
| 6 | **write_scope 与路径狱的覆盖面差** | scope 只管写前缀；区外由路径狱管；两者原因码不同（0340） | ⚠️ 需要上层同时检查两者 |
| 7 | **策略文件坏文件** | 若 fail-closed 未实现，制造解析错误即可降级权限 | ✅ 已 fail-closed（0326） |
| 8 | **包外入口（Bash/外部编辑器/构建工具）** | 不经过权限门（B03 已确立「`workspace_revision` 是检测非阻止」） | ❌ 结构外 |
| 9 | **仓库策略不得放宽** | 否则仓库作者可替你降权限 | ✅ 已有单向性约束（0331） |

**纵深防御四层**：

```
① 应用层：三态 + 路径狱 + 硬拦（已有，需补 TOCTOU 与多根一致性）
② 会话层：mode/preset/store 的活状态与单向性（已有）
③ 执行层：write_scope + WriteStore + 快照（部分）
④ 系统层：文件系统 ACL / 容器 / 沙箱（**本项目的最大空白**，尤其 POSIX 侧）
```

★ **必须点出的结构性认识**：**应用层权限永远不是安全边界**——它防的是「模型走错路」，不是「恶意进程」。真正的边界在 **OS 层**（ACL/容器/沙箱）。本项目在 Windows 侧有 Job Object（内存限额 + `KillOnJobClose`），但**没有文件系统级沙箱**；POSIX 侧连进程树都杀不干净（B05-0246）。

**评分要点**
- **及格**：说出密钥与路径狱这些已有防护。
- **良好**：能列出 3–5 条绕过面并区分「已覆盖 / 未覆盖」。
- **优秀**：把 **1（TOCTOU）与 3（多根不一致）** 这两个真实未覆盖项排到前面，并提出**系统层沙箱**这一根因级方向；指出「应用层权限 ≠ 安全边界」这一层次认识。

**典型弱答**
- 把清单写成「已有防护的重述」（没有绕过面）；
- 只提「正则更严格/黑名单更长」（改不了结构性缺口）；
- 认为应用层校验足够（忽略「进程层面」的攻击者）。

**追问**
如果要在 POSIX 侧补一层文件系统沙箱，你会选什么机制（命名空间 / chroot / 用户分离）？代价是什么？

---

### XEYO-QA-0346 【超压】密钥路径「拒绝」是否真的安全

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 密钥保护的完整面 | 只拒读够不够 | 超压 | 故障排查 | `filesystem.py:68-110,157-188` + `policy.py` 写判定 |

**面试官提问**
我们把密钥路径做成硬 DENY。请回答：**只拒绝「读」和「写」足够吗**？请从「还有哪些路径能碰到密钥」入手，找出保护缺口。

**参考答案要点**
**硬 DENY 覆盖的**：`is_secret_path` 在**读裁决**（`:280-281`）与**写裁决**（`:299-300`）都调用 → 读/写两条主路径已拦。

**仍有缺口的路径**：

| # | 路径 | 为什么可能绕过 |
|---|---|---|
| 1 | **Bash 命令** | Bash 的写/读判定是**另一套**（`policy._bash_writes_file`，0328）。若某条命令形态不在正则覆盖内（例如经解释器读文件），命令可以读到密钥再把内容**打出来** |
| 2 | **命令替换/管道** | `cat .env \| ...` 的输出进入工具结果 → 密钥进上下文（B05-0215 的「命令替换可藏任意写」是同一类） |
| 3 | **不在清单内的凭据** | 清单只有 14 个文件名 + 4 个后缀 + 4 个目录；`config/secrets.yaml`、`*.jks`、`.pgpass`、`.docker/config.json` 都不在（0306） |
| 4 | **路径形态变体** | 硬链（hard link）到密钥文件（不涉及 symlink，realpath 解析不到）；`\\?\` 长路径前缀；大小写（Windows 已有 normcase，POSIX 无） |
| 5 | **工具外的读** | 引擎自己的模块读密钥不算越权（例如 `permissions` 读配置）——这条是**设计允许**的，但要确保它不被工具的路径复用 |
| 6 | **写保护的间接破坏** | 即使不能读，能否**删除/覆盖**密钥（写裁决拦）→ 已覆盖；但能否**改权限位**（`chmod`）→ Bash 侧（B05-0215 的白名单里 `chmod` 在静默集里，即被判为「可能写」→ 清缓存，但**权限层是否拦**需看 bash 策略） |

★ 最值得注意的是 **1 与 2**：**密钥保护只在「路径裁决」这一层做，而 Bash 是一条独立的、以「命令字符串」为输入的通路**。两套判定（路径 vs 命令）之间没有统一抽象——这是本卷给出的**结构性缺口**。

**复现思路**：在 Bash 里用不经 `is_secret_path` 的形态读取密钥（例如让解释器读文件并打印），观察是否被拦；再观察输出是否进入工具结果（进上下文 = 已经泄漏）。

**正确的加固方向**：

1. **统一抽象**：把「敏感路径」判定抽成**任何通路都必须过**的一层（Bash 侧解析出的读写目标也要过 `is_secret_path`）；
2. **输出侧脱敏**：即使读到了，工具结果在**离开引擎前**对已知密钥形态做脱敏（`audit/redact.py` 已有脱敏能力，B18 面）——这是**纵深**，因为路径判定永远补不全；
3. **扩大清单 + 可配置**：允许工作区声明额外敏感路径（但要防「仓库文件降权限」，即 0331 的单向性）；
4. **环境变量注入面**：`env`/`printenv` 在 B05 的只读白名单里（`printenv` 确实在白名单），它能把**进程环境**整个打印出来——若密钥在环境变量里，这条通路完全不经路径判定。

**评分要点**
- **及格**：说出现有硬拦覆盖读/写。
- **良好**：指出 Bash 是独立通路、清单不完备这两类缺口。
- **优秀**：**主动指出第 4 条中的环境变量通路**（`printenv`/`env` 打印进程环境，与路径无关），并提出「统一敏感路径抽象 + 输出侧脱敏」两层加固；能指出「路径判定永远补不全，所以必须靠输出侧兜底」。

**典型弱答**
- 认为读+写都拦了就安全；
- 只补清单（永远补不完，且不覆盖 Bash 与 env 通路）；
- 忽略「输出进上下文即已泄漏」这一点（拦住读却让内容进上下文等于没拦）。

**追问**
如果要在**工具结果离开引擎前**做密钥脱敏，你会怎么识别「这是密钥」（形态匹配 / 已知值比对）？各自误伤与漏报如何？

---

### XEYO-QA-0347 【超压】多 agent 并发写同一文件的权限语义

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 并发写与权限的交叉 | 竞争与归因 | 超压 | 场景设计 | `write_scope.py:15-43,148-157` + `store.py:459-502` + B03 写路径 |

**面试官提问**
两个子 agent 并行工作，`scope` 分别是 `["src/a"]` 与 `["src"]`（后者是前者的父目录）。它们**同时**改 `src/a/x.py`。请说明权限层面会发生什么、正确性由谁保证、以及你会怎么改进。

**参考答案要点**
**权限层面：两者都被允许。** 因为：

| agent | scope | `path_in_write_scope("src/a/x.py")` |
|---|---|---|
| A | `["src/a"]` | 前缀命中 → **True** |
| B | `["src"]` | 前缀命中（父目录） → **True** |

即 **`write_scope` 不做「排他」**——它是**允许集合**，不是**所有权**。设计如此（docstring `:1-6` 只讲「允许/禁止」，没有任何互斥语义）。

**正确性由谁保证**：**写路径的三层防护**（B03）：

| 层 | 机制 | 在这里的作用 |
|---|---|---|
| **base hash 校验** | 每个写请求带「我看到的版本」的 base hash；磁盘版本不同 → 拒绝（stale） | 后写者若基于旧内容 → **被拒**（不会静默覆盖） |
| **分片锁** | 同一路径分片串行化 | 防止写交错（不会写出半个文件） |
| **租约** | 写者持有租约 | 防并发写者同时进临界区 |

所以**权限层放行 + 写层拒绝**是正确分工：权限回答「你有没有资格碰这个区域」，写层回答「这次改动是否基于最新内容」。

★ 但有一处**真实缺口**：`write_scope` 允许「父子 scope 重叠」，而**没有机制表达「这块归 A、不归 B」**。若产品语义是「A 负责 `src/a`，B 不应碰它」，当前模型**无法表达**——需要 `scope` 之外的所有权/租用概念（与 coord 的 worktree 隔离是同一问题的不同解法，B15 面）。

**改进方向**：

| 方向 | 说明 |
|---|---|
| **重叠检测** | 下发时就检查多个 scope 是否重叠，重叠则警告/拒绝（最省事，但语义上过严——重叠可能是合理的） |
| **优先级/所有权** | 在 scope 上加「独占」标记（`exclusive: src/a`），重叠时按独占优先 |
| **worktree 隔离** | 每个 agent 独立工作树，最后合并（coord 已有能力）——**结构性解法** |
| **归因** | 至少保证 journal/快照里能看出「这次改是哪个 agent 的」（`agent_id` + scope 一起记） |

**评分要点**
- **及格**：说出两个都允许（scope 是允许集合）。
- **良好**：说出正确性由 **base hash + 锁** 保证，并指出权限与写层职责不同。
- **优秀**：指出**「scope 不表达所有权」这一语义缺口**并给出至少两条改进（重叠检测 / 独占标记 / worktree 隔离），其中 worktree 是结构性解法；同时指出归因（agent_id）的价值。

**典型弱答**
- 认为 `write_scope` 会互斥（它只做允许判定）；
- 把正确性完全归给权限层（权限不解决并发覆盖）；
- 只想到「加锁」，没意识到「谁该改这块」是语义问题而非并发问题。

**追问**
如果 A 的写被 base hash 拒了（stale），它应该怎么做？重读后重写 —— 但如果 B 一直在改，A 可能永久失败。这需要什么机制？

---

### XEYO-QA-0348 【超压】「显示已批准但实际拒绝」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | UI 状态与执行态不一致 | 三处状态源 | 超压 | 故障排查 | `filesystem.py:17-29` + `store.py:61-244` + `runtime_mode.py:107-119` |

**面试官提问**
**故障背景**：用户点了「批准」并看到界面显示已批准，但操作仍然被拒绝。请列出所有可能原因，并给出复现思路。

**参考答案要点**
「已批准」这个状态在系统里**至少有三个来源**，三者可能不一致：

| # | 状态源 | 位置 | 它表示什么 |
|---|---|---|---|
| 1 | **挂起 store 的 resolve 结果** | `store.py`（`request_id` → 结果 + 唤醒信号） | 用户真的点了批准 |
| 2 | **grant（持久授权）** | `store.PermissionGrantStore`（指纹 + 24h TTL） | 「以后同类不再问」 |
| 3 | **执行期 preapproved 标记** | `filesystem._preapproved_ctx`（ContextVar） | 「本次执行已通过 registry 裁决」 |

**六条不一致路径**：

| # | 原因 | 机制 |
|---|---|---|
| 1 | **`preapproved` 未设置/已复位** | 工具内的 ASK 遇到 `preapproved=False` → 直接 False（`:414-415`）。若 registry 侧批准了但**没进 `mark_permission_preapproved`** → 工具内仍拒 |
| 2 | **批准与执行的 turn 不同** | 模式基线在 turn 边界重拍（0320）。上一轮批准的语义不自动延续到下一轮更高档位 |
| 3 | **grant 与「本次」混淆** | 用户看到的是「已有 grant 生效」（UI 显示允许），而**本次**因路径/参数不同仍走 ASK → 超时 → `unavailable`（按拒绝） |
| 4 | **resolve 后状态被覆盖** | 双入口并发 resolve（0344 ①），最终落盘的是 deny |
| 5 | **UI 显示的是「已发送批准」而非「已被采纳」** | 前端可能把「提交」当「成功」（B14 的 `/v1/permission/resolve` 回执面） |
| 6 | **工具内检查与 registry 检查的路径解析不同** | registry 用原始 dict，工具用 dataclass 解析后的路径（0338）→ 两次可能得到不同路径 → registry 放行、工具内拒 |

★ 最容易忽略的是 **⑥**：它不涉及任何时序或竞态，纯粹是**两次检查的输入不同**。复现：构造一个「原始 dict 路径」与「解析后路径」判定结论不同的用例（例如相对路径 + 不同 cwd 基准，0342）。

**复现思路（可答）**：
① 直接单测工具 `execute(...)`（不经 registry）→ 观察 ASK 被拒（`preapproved=False`）；
② 在 registry 已批准的前提下**手工复位** `preapproved` 再执行 → 必拒；
③ 双入口并发 resolve 观察落盘结果；
④ 用「相对路径 + working_directory」构造 cwd 不一致（0342）。

**正确性要求（可答）**：**「已批准」必须只有一个权威源**，UI 应显示**权威源**的状态（而不是「我提交了」），并且执行期标记必须由**同一个流程**设置（批准 → 设置标记 → 执行，三者原子绑定）。

**评分要点**
- **及格**：说出可能超时/未生效。
- **良好**：能区分「挂起结果」「授权」「执行期标记」三个状态源。
- **优秀**：**主动指出 ⑥（两次检查输入不同）** 这条非时序原因，并给出「单一权威源 + 原子绑定」的正确性要求——说明候选人理解「同一语义多个状态源」是这类不一致的结构根因（与 B09-0450 的回滚三载体问题同源）。

**典型弱答**
- 只答「可能超时了」；
- 认为 UI 显示即真相（忽略 UI 与执行态的分离）；
- 把问题归给「前端 bug」（后端有多个状态源才是根因）。

**追问**
如果要让「已批准」只有一个权威源，你会怎么做？（→ 挂起 store 为唯一真相；UI 只读它；`preapproved` 由 resolve 流程在**同一临界区内**设置）

---

### XEYO-QA-0349 【超压】Bash 规则引擎的绕过面

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | bash_policy 与写判定 | 命令级判定的极限 | 超压 | 安全拷问 | `python/permissions/bash_policy.py`(654，定义面) + `policy.py:742-806` |

**面试官提问**
权限层对 Bash 的判定输入是**一个命令字符串**。请说明这种判定在**原理上**能到什么程度，并列出你预期会漏掉的形态。

**参考答案要点**
先摆本卷可见的判定面：

| 组件 | 位置 | 作用 |
|---|---|---|
| 四组正则 | `policy._BASH_REDIRECT_RX` / `_WRITE_CMD_RX` / `_INTERP_RX` / `_WRITE_MARK_RX` / `_PY_OPEN_RX`（`:742-765`） | 识别「可能写」的形态 |
| 写目标提取 | `_bash_write_target` / `bash_write_target`（`:765-806`） | 从命令里抠出写目标路径 |
| 规则引擎 | `permissions/bash_policy.py`（654 行，定义面含 `bash_readonly_allow`） | 只读白名单等规则 |
| 消费者 | `policy._evaluate_bash`（`:822-1015`） | 组装最终三态 |

**原理上的极限**：命令字符串是**图灵完备语言的源文本**（shell + 解释器 + 命令替换），而判定是**正则 + 白名单**——两者能力不对等。所以判定只能做到「**识别常见形态**」，不可能完备。

**预期会漏的形态（按类别）**：

| 类别 | 例子 | 为什么难 |
|---|---|---|
| **编码/间接** | `echo <base64> \| base64 -d \| sh`、`eval "$(…)"` | 真实命令不在同一层文本里 |
| **解释器内** | `python -c "open('x','w').write(...)"` | 需要理解解释器语义（`_BASH_PY_OPEN_RX` 是**形态匹配**，不是语义分析） |
| **环境变量携带** | `printenv`、`env`（B05 只读白名单里确实含 `printenv`） | 与路径无关，判定的输入里没有「环境里有密钥」这条信息 |
| **不可见字符** | 全角字符、零宽字符、`^` 转义（cmd） | 正则的字符集假设被打破 |
| **不写入但有害** | 读密钥并打印（0346）、发起网络请求外传 | 「写判定」只看写，看不住「读了往外送」 |
| **组合爆炸** | `$(...)` 嵌套、函数定义、别名、`:` 内建 | 需要完整解析器 |

★ 最重要的一条认识：**Bash 是「逃逸出应用层权限模型」的主通道**。因为：
1. 它是**通用执行入口**（能跑任意程序）；
2. 判定只能看**文本形态**；
3. 它能**自己再生成**新的命令（`sh -c` / `eval`）。

所以工程上的正确定位是：**Bash 权限 = 尽力而为的护栏（防误操作），而不是安全边界**；真正的边界必须是系统层（沙箱/ACL/容器），或者从能力上收窄（不提供 Bash、或只提供白名单命令）。

**加固方向（可答）**：
| 方向 | 说明 |
|---|---|
| **收窄能力** | 去掉通用 Bash，改成「白名单命令集」或「专用工具路由」（B05 的 `bash_routing` 就是往这个方向走） |
| **执行期约束** | 在沙箱/容器里跑、限制可见文件系统与网络 |
| **输出侧** | 脱敏（0346） |
| **白名单优先** | `bash_readonly_allow` 已实现「只读命令自动放行」，即**默认拒绝 + 白名单放行**优于「默认放行 + 黑名单拦截」 |

**评分要点**
- **及格**：说出「正则判命令不一定可靠」。
- **良好**：给出 3 类以上漏判形态（编码间接 / 解释器 / 环境变量）。
- **优秀**：从**能力不对等**（图灵完备源文本 vs 正则）论证「不可能完备」，并给出「默认拒绝 + 白名单 + 系统层沙箱」的正确定位；指出「不写入但有害」（读密钥并外传）是写判定完全覆盖不到的一类。

**典型弱答**
- 主张「把正则写全一点」；
- 认为拦住了重定向与 `rm` 就安全了；
- 把应用层判定当安全边界（忽略系统层）。

**追问**
`bash_routing`（Bash → 专用工具透明路由）在安全上是什么价值？（→ 把「任意命令」收窄成「语义明确的读操作」，减少逃逸通道）

---

### XEYO-QA-0350 【超压】设计一套面向 Agent 的权限模型

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 权限与沙箱 | 全卷综合 | 从零设计 | 超压 | 系统设计 | 全卷 |

**面试官提问**
忘掉这份代码。现在让你从零设计「一个会读写文件、执行命令、访问网络的编码 Agent」的权限系统。请给出你的设计，并说明**每一层防什么、不防什么**。

**参考答案要点**
**六层结构（从内到外）**：

| 层 | 内容 | 防什么 | **不防什么** |
|---|---|---|---|
| ① **能力面裁剪** | 按模式移除工具（如只读模式移除 `Write`/`Edit`，B06-0253） | 模型看不到 → 减少误用面 | 幻觉调用（需下层兜） |
| ② **角色/档位** | preset（readonly / workspace-write / full）+ 审批模式（always/risk/never） | 用户意图对齐 | 绕过（full 不等于关闭硬拦） |
| ③ **三态裁决 + 挂起** | allow / ask / deny；ask 挂起 + TTL + 授权持久化 | 不确定的操作交给人 | 判定错误（规则不可能全对） |
| ④ **硬拦（绝对值）** | 密钥 / 受保护元数据 / 危险路径 / 沙箱 | 最高危目标**不可被批准** | 清单外的新型敏感文件 |
| ⑤ **执行层约束** | 路径狱（双 realpath）+ write_scope + WriteStore（base hash/锁/租约） | 路径逃逸、并发覆盖 | TOCTOU、系统调用层绕过 |
| ⑥ **系统层边界** | 容器 / 沙箱 / 文件系统 ACL / 网络策略 | **真正的安全边界** | 部署复杂度 |

**六条必须坚持的原则**（本卷各处都出现过）：

1. **单向性**：收紧即时、放宽延后（0320）；仓库文件不得放宽用户权限（0331）。
2. **fail-closed 用在「判定不确定」处**：坏策略文件按最严（0326）；DNS/模式读不到按拒绝（0336）；而**可用性关键处**（预检）才 fail-open（B05-0239）。
3. **默认值落在方向安全侧**：`scope` 空 = 只读（0322）；`preapproved` 默认 False（0311）；硬保护默认开、放宽要显式（0341）。
4. **同一语义单一权威源**：「已批准」只有挂起 store 一个真相（0348）；授权指纹只绑稳定身份、不含模型可控参数（0337）。
5. **硬拦与档位解耦**：硬拦是绝对值，不参与「取更严」的比较（0331）。
6. **可观测**：每次挂起/结果/降级都留审计（0324）；降级必须可见（B05-0249 的反面教训）。

**两处必须承认的局限**（面试加分项）：

| 局限 | 说明 |
|---|---|
| **应用层权限 ≠ 安全边界** | 它防「模型走错路」，不防「恶意进程」。缺系统层沙箱时，Bash/LSP/构建脚本/**外部编辑器**都能绕过（B03 已确立「`workspace_revision` 是检测非阻止」） |
| **判定完备性不可能** | 命令字符串是图灵完备源文本（0349）；路径清单永远不全（0346）。所以必须有**输出侧脱敏 + 系统层边界**兜底 |

**落地的三个工程取舍**（可答）：

| 取舍 | 本项目的选择 |
|---|---|
| ASK 怎么才不贵 | **授权持久化**（把成本从每次降到首次）+ 档位控制 ASK 频率（0343） |
| 硬拦清单怎么维护 | 泛化 + 豁免（`.env*` 但放 `.example`，0316）+ 允许工作区补充（受单向性约束） |
| 多 agent 怎么隔离 | `scope` 允许集合 + WriteStore 收敛（0347）；**结构性解是 worktree 隔离**（B15） |

**评分要点**
- **及格**：能给出「档位 + 三态 + 路径检查」的基本结构。
- **良好**：分层清晰，并能指出每层**不防什么**（这一项最能区分「背过资料」与「真设计过」）。
- **优秀**：主动给出**六条一致性原则**与**两处根本局限**，并把「系统层边界缺失」列为最大风险；能给出「ASK 成本靠授权持久化而非降低安全性」这类可落地的工程取舍。

**典型弱答**
- 只堆机制名词（三态、路径狱、沙箱）而不说各层边界；
- 认为「有了应用层校验就安全了」；
- 把硬拦也做成可配置档位（失去绝对性）；
- 设计里没有审计与可观测面。

**追问**
如果这套系统要交付给**企业客户**（要求合规审计），你会优先补哪两块？（→ 审计链完整性 + 系统层沙箱；并回答「策略变更的审批与留痕」）

---


---

## 批次自检表（B07）

| 项 | 结果 |
|---|---|
| 题号连续性 | XEYO-QA-0301 – XEYO-QA-0350，**无跳号无重号** |
| 难度配比实测 | 简单 **12**（0301–0312）/ 中等 **16**（0313–0328）/ 困难 **15**（0329–0343）/ 超压 **7**（0344–0350）= **50** ✅ 与矩阵 B07 一致 |
| 问法分布 | 概念确认 8 / 机制解释 17 / 对比辨析 5 / 系统设计 4 / 权衡取舍 5 / 安全拷问 6 / 故障排查 3 / 场景设计 2 = **50** |
| 覆盖子模块 | `filesystem`（三态枚举 / 路径狱 / 密钥清单 / 危险与元数据 / extra roots / 读写下裁决 / enforce_decision / preapproved / 工具级入口）· `policy`（模式与严格度 / Agent 模式白名单 / readonly_gate / 三态 ASK 的决策对象 / Bash 写判定 / 循环依赖）· `runtime_mode`（活状态与单向性 / 广播）· `runtime_preset` / `presets` / `write_scope` / `pending_ttl` / `gate` / `workspace_policy` / `store`（挂起 + 授权指纹）——共 **12 个文件** |
| 事实基线核对 | 本卷全部来源指向实际读过的文件；`filesystem.py`(435) / `runtime_mode.py`(154) / `runtime_preset.py`(62) / `presets.py`(18) / `write_scope.py`(157) / `pending_ttl.py`(53) / `gate.py`(71) **全文精读**；`policy.py`(1700) 与 `bash_policy.py`(654) 采用「Grep 定义面 + offset/limit 精读」；`store.py`(508) / `workspace_policy.py`(257) 读定义面与关键段 |
| 重复性检查 | ① 与 B04/B05/B06 的分界已守：那三卷只讲「工具如何调用权限」，本卷讲**裁决本体**（三态、优先级、边界、活状态、挂起、授权）；② 批内 `0314`（读裁决顺序）与 `0315`（写裁决差异）是「顺序 vs 增量」两件事；`0329`（realpath TOCTOU）与 `0330`（归一化不一致）分别考**时序**与**形态**两类绕过，不重复；`0337`（指纹绑定）与 `0348`（三状态源不一致）都涉及授权但角度不同（身份 vs 权威源） |
| 待确认条目（本批显式标注） | **5 处**：① `0315`/`0335` 写裁决复用读裁决 ⇒ `readable_extra_roots` 实际生效，与「写裁决不得包含」注释**存在张力**；② `0309` 策略文件 docstring 的默认（`bash=ask`/`write=ask`）与 dataclass 字段默认（`bash="default"`/`write="risk"`）**口径不同**，未确认调用方以哪个为准；③ `0330` 多 allowed 根场景下 `protected_metadata_reason` 只认单个 `cwd` ⇒ `.git` 保护可能失效（需实测确认严重程度）；④ `0344` 第③条「一次 deny 是否撤销已有 grant」的语义在代码中未见显式规则；⑤ `0349` `bash_policy.py`(654) 只读到定义面，规则引擎的**具体匹配语义**未逐行核对（`bash_readonly_allow` 的判据、规则优先级） |
| 边界遵守 | 未涉及 B04（文件工具族）/ B05（Bash 家族实现）/ B06（工具系统）；MCP 指纹与停用语义归 B16（本卷只在 `0337` 涉及 `PolicyDecision.mcp_target` 这一接口）；`/v1/permission/resolve` 等路由归 B14（本卷只讲 store 语义）；写路径三层防护（分片锁/租约/base hash）归 B03/B11（本卷只在 `0347` 引用结论） |
| 未覆盖但已计划 | `policy.py` 的 `_evaluate_bash`(822–1015) 逐行语义、`_peer_bash_conflict`(1016) / `_peer_write_conflict`(1066) / `_bash_touches_policy_file`(1092) / `_bash_write_path_block`(1109) 四个跨会话冲突判定、`_evaluate_ui_ask`(506–724)、`_memdir_write_schema_ok`(725)、`_evaluate_mcp`(1150) / `_evaluate_mcp_gateway`(1217)、`evaluate_policy_impl`(1391–1700) 的完整判定流程、`ask_store.py`(139) 与 `store` 的关系、`bash_policy` 规则引擎细节 → 如需可作补批 |
