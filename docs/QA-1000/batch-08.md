# XEYO 面试题库 · 第 8 批（B08）

> 卷名：**会话与持久化**（Agent 后端开发岗 · 三级能力域）
> 题号范围：**XEYO-QA-0351 – XEYO-QA-0400**
> 考查范围：transcript JSONL 权威落盘 · 异步写批与 fsync 崩溃窗口 · 轮转与归档链 · 去重记账 · 水化（hydrate）与未闭合工具调用修复 · 事件化回溯（surface fold / rewind / undo）· 大内容外置（blob）· workspace 归属索引 · 持久化开关 · 会话文件名安全化 · cwd 解析链
> 难度配比：简单 14 / 中等 18 / 困难 13 / 超压 5
> 事实基线（本批实际打开读过的文件与实测行数）：
> `record_transcript.py`(419, 31–240 精读 + 定义面全量) · `hydrate.py`(162, 52–151 精读) · `surface.py`(150, 55–134 精读) · `persistence.py`(62, **全文**) · `transcript_blobs.py`(115, 10–69 精读) · `ws_index.py`(130, 21–90 精读) · `state.py`(102, 定义面) · `cwd.py`(72, 定义面) · `workspace_path.py`(59, 定义面) · `message_store.py`(55, 定义面)
> **边界声明**：`engine/` 侧快照/进程账本（`turn_snapshot` / `process_ledger` / `write_store`）归 **B02/B03**；rewind 的 checkpoint/snapshot/blob_gc **服务本体**归 **B11**（本卷只讲转录侧的 surface 事件化与 `discard_rotated_transcripts`）；`server` 侧会话路由（`/v1/sessions*`）归 **B14**；GUI 侧 IndexedDB 与流式排空归 **B18**；`memory/runtime` 对 `session.md` 的消费归 **B09/B10**。
> **行号口径**：`record_transcript.py`(419) 采用「Grep 定义面 + offset/limit 精读」；写题前复核的锚点见自检表。

---

## 本卷题目总览

| 题号 | 难度 | 问法 | 考查点 | 来源 |
|---|---|---|---|---|
| 0351 | 简单 | 概念确认 | 权威对话记录的载体与位置 | `persistence.py:34-62` |
| 0352 | 简单 | 概念确认 | 会话文件名的安全化与长度兜底 | `persistence.py:42-57` |
| 0353 | 简单 | 概念确认 | 持久化开关的两级优先级 | `persistence.py:14-31` |
| 0354 | 简单 | 概念确认 | 轮转阈值与归档代数 | `record_transcript.py:50-65` |
| 0355 | 简单 | 概念确认 | 归档路径命名与读取顺序 | `record_transcript.py:68-102` |
| 0356 | 简单 | 机制解释 | 异步写队列的 seq 与 flush 判定 | `record_transcript.py:41-45,183-191` |
| 0357 | 简单 | 机制解释 | 退出时的排空兜底 | `record_transcript.py:194-202` |
| 0358 | 简单 | 概念确认 | 大内容外置阈值与目录 | `transcript_blobs.py:15-32` |
| 0359 | 简单 | 概念确认 | workspace 归属索引的形态 | `ws_index.py:36-63` |
| 0360 | 简单 | 机制解释 | 轮转归档为什么必须能读回 | `record_transcript.py:100-102` + `hydrate.py:119-133` |
| 0361 | 简单 | 机制解释 | 回溯后为什么要丢弃归档 | `record_transcript.py:105-119` |
| 0362 | 简单 | 概念确认 | 会话状态对象承载什么 | `state.py:30-101` |
| 0363 | 简单 | 概念确认 | cwd 的解析层级 | `cwd.py:20-71` |
| 0364 | 简单 | 机制解释 | 内存消息存储的定位 | `message_store.py:6-55` |
| 0365 | 中等 | 机制解释 | 磁盘临界区锁保护什么 | `record_transcript.py:36-39,143-157` |
| 0366 | 中等 | 机制解释 | 批量写的分组与原子追加 | `record_transcript.py:122-157` |
| 0367 | 中等 | 机制解释 | 去重记账与已知 id 缓存 | `record_transcript.py:33-34,220-233` |
| 0368 | 中等 | 机制解释 | flush 超时返回值的语义 | `record_transcript.py:183-191` |
| 0369 | 中等 | 机制解释 | 轮转的改名链与最旧代删除 | `record_transcript.py:81-97` |
| 0370 | 中等 | 机制解释 | 未闭合工具调用的两种合成文案 | `hydrate.py:73-116` |
| 0371 | 中等 | 机制解释 | 事件化回溯的影子化语义 | `surface.py:68-102` |
| 0372 | 中等 | 机制解释 | undo 的恢复顺序与幂等 | `surface.py:73-99` |
| 0373 | 中等 | 机制解释 | 影子首行缺失时的保守取向 | `surface.py:76-77` |
| 0374 | 中等 | 机制解释 | blob 的写入与还原 | `transcript_blobs.py:39-69` |
| 0375 | 中等 | 机制解释 | blob 缺失时的降级 | `transcript_blobs.py:61-68` |
| 0376 | 中等 | 机制解释 | workspace 索引的读写与缓存 | `ws_index.py:23-25,41-90` |
| 0377 | 中等 | 机制解释 | 索引「后行覆盖前行」的后果 | `ws_index.py:41-64` |
| 0378 | 中等 | 系统设计 | 会话恢复的完整读取链 | `hydrate.py:119-151` + `surface.py` |
| 0379 | 中等 | 对比辨析 | 会话私有 vs 工作区共享的存储域 | 全卷 + B06-0282 |
| 0380 | 中等 | 机制解释 | state 与 cwd 的 fallback 设计 | `state.py:87-101` + `cwd.py:44-71` |
| 0381 | 中等 | 系统设计 | 物理重写（v2）与事件化（v3）的取舍 | `surface.py:118-134` |
| 0382 | 中等 | 机制解释 | 消息行序列化与 blob 的分工 | `record_transcript.py:205-217` + `transcript_blobs.py:79-108` |
| 0383 | 困难 | 故障排查 | fsync 与「尾巴丢了」的窗口 | `record_transcript.py:143-157` |
| 0384 | 困难 | 安全拷问 | 轮转与 append 交错的丢行/重行 | `record_transcript.py:36-39,81-97,150-156` |
| 0385 | 困难 | 故障排查 | flush 超时后的状态一致性 | `record_transcript.py:183-191,194-202` |
| 0386 | 困难 | 场景设计 | 未闭合工具调用的重放风险 | `hydrate.py:99-114` |
| 0387 | 困难 | 安全拷问 | 归档链未清导致的「已删回合复活」 | `record_transcript.py:105-119` |
| 0388 | 困难 | 场景设计 | surface fold 的三处保守取向 | `surface.py:68-115` |
| 0389 | 困难 | 故障排查 | blob 与行的不一致窗口 | `transcript_blobs.py:39-69` |
| 0390 | 困难 | 系统设计 | 去重记账在多进程下的边界 | `record_transcript.py:33-34,220-259` |
| 0391 | 困难 | 对比辨析 | 轮转 vs blob 外置 vs spill 的三种落盘 | 全卷 + B04/B05 |
| 0392 | 困难 | 场景设计 | 「权威记录」与「派生视图」的分层 | 全卷 + B09 |
| 0393 | 困难 | 故障排查 | 会话文件名碰撞与截断 | `persistence.py:42-57` |
| 0394 | 困难 | 安全拷问 | 会话目录的横向可达面 | `persistence.py:34-39` + B07-0319 |
| 0395 | 困难 | 系统设计 | 恢复语义：什么该重放、什么不该 | `hydrate.py:73-116` + B03/B04 |
| 0396 | 超压 | 故障排查 | 崩溃点状态矩阵 | `record_transcript.py` + `transcript_blobs.py` + `surface.py` |
| 0397 | 超压 | 安全拷问 | 会话持久化的隐私与越权面总账 | `persistence.py` + `ws_index.py` + `transcript_blobs.py` |
| 0398 | 超压 | 系统设计 | 大量会话下的读写成本 | `ws_index.py` + `record_transcript.py` |
| 0399 | 超压 | 故障排查 | 「同一个 ID 出现两次」的成因总账 | `record_transcript.py` + `surface.py` |
| 0400 | 超压 | 系统设计 | 设计一套会话持久化方案 | 全卷 |

---

### XEYO-QA-0351 权威对话记录存在哪里、长什么样

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | persistence 会话落盘 | 权威载体与路径 | 简单 | 概念确认 | `python/session/persistence.py:34-62` |

**面试官提问**
一个编码 Agent 的对话历史，你会把它存成什么？存在哪里？为什么？

**参考答案要点**
**一行一条 JSON 的 JSONL 文件**，位于 `~/.xeyo/sessions/<安全化会话名>.jsonl`：

```python
def default_sessions_dir() -> Path:
    override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "sessions"

def transcript_path(session_id, *, sessions_dir=None) -> Path:
    root = sessions_dir or default_sessions_dir()
    return root / f"{safe_session_filename(session_id)}.jsonl"
```

为什么选 JSONL（append-only 行日志）而不是整份 JSON 或数据库：

| 选它的理由 | 说明 |
|---|---|
| **追加即落盘** | 每轮只 append 几行，不需要重写整份文件（O(1) 而非 O(n)） |
| **崩溃只损尾部** | 写到一半崩 = 最后一行可能残缺，前面的行完好；整份 JSON 崩 = 文件不可解析 |
| **可轮转** | 超限时改名归档即可（0354/0369），不需重写 |
| **可重放** | 事件化回溯（surface marker）直接往日志追加事件（0371） |
| **可人工查看** | 一行一条，`tail`/`grep` 就能定位 |

不选数据库的原因（本卷范围内）：单机单用户、写已串行化（0365）、没有跨会话查询需求（除了 `ws_index` 那种小索引）。

★ 目录可用 `XEYO_SESSIONS_DIR` 覆盖——测试隔离与多实例部署都靠它。

**评分要点**（对照候选人口述逐项打分）
- **及格**：能说出「JSONL 一行一条、放 `~/.xeyo/sessions/`」。
- **良好**：能说出 append-only 的三个收益（只追加 / 崩溃只损尾 / 可轮转）。
- **优秀**：能对比「为什么不用数据库或整份 JSON」，并指出 `XEYO_SESSIONS_DIR` 的可覆盖性对测试与多实例的意义。

**典型弱答**（听到这些就得分不高）
- 只说「存成 json 文件」（没说行式追加，无法解释崩溃与轮转语义）；
- 说存数据库但给不出查询需求（单机单用户没有跨会话查询）；
- 不知道目录可被环境变量覆盖。

**追问**
如果两个 XEYO 实例（GUI 与 CLI）同时写同一个会话文件，会发生什么？你靠什么避免？

---

### XEYO-QA-0352 会话 id 怎么变成安全的文件名

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | persistence 文件名安全化 | 字符白名单与长度兜底 | 简单 | 概念确认 | `python/session/persistence.py:42-57` |

**面试官提问**
会话 id 可能含 `:`、`/`、超长字符串。它在磁盘上会变成什么文件名？

**参考答案要点**
`safe_session_filename`（`:42-57`）三步：

```python
    for ch in raw:
        if ch == ":":
            parts.append("__")          # ① 冒号 -> 双下划线（可识别的替换）
        elif _SAFE_CHAR.match(ch):      # ② 白名单 [A-Za-z0-9._-] 保留
            parts.append(ch)
        else:
            parts.append("_")           # ③ 其余 -> 单下划线
    name = "".join(parts).strip("._") or "session"
    if len(name) > _MAX_FILENAME:       # _MAX_FILENAME = 180
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        name = name[:160].rstrip("._-") + "_" + digest
```

| 设计点 | 理由 |
|---|---|
| `:` → `__` | 冒号在 Windows 文件名非法；双下划线是**可识别的替换**（子 agent 的 `__agent__` 也靠它） |
| 白名单保留 | 不用黑名单（黑名单永远列不全） |
| `strip("._")` | 防隐藏文件 / 畸形名 |
| **超长时截断 + 哈希后缀** | `[:160]` + `"_" + sha256[:16]`——**可读前缀 + 哈希保证唯一** |

★ 「截断 + 哈希」这个组合是关键：只截断会让**不同 id 映射到同一文件**（静默串会话）；只哈希会失去可读性。

与 B06-0273（`agent_tool._safe_agent_id`）的差异：那里**没有长度上限**（待确认项），这里**有 180 上限**。

**评分要点**
- **及格**：能说出要过滤非法字符并给兜底名。
- **良好**：能说出白名单（保留什么）而非黑名单，并知道去首尾 `._`。
- **优秀**：主动指出「**截断后必须加哈希**」——否则不同 id 会静默映射到同一文件（串会话）。

**典型弱答**
- 只用黑名单替换 `../`、`\` 等；
- 截断但不加唯一后缀（碰撞后串会话）；
- 把冒号直接删掉（丢失「这是分隔符」的信息，且可能产生歧义）。

**追问**
如果两个不同 `session_id` 截断后前 160 字符相同、但哈希不同，结果是什么？反过来只有哈希不同而前缀相同呢？（→ 0393 的碰撞面）

---

### XEYO-QA-0353 什么时候不该落盘

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | persistence 持久化开关 | 优先级与测试隔离 | 简单 | 概念确认 | `python/session/persistence.py:14-31` |

**面试官提问**
有没有场景应该**完全不写盘**？你会怎么实现这个开关？

**参考答案要点**
有——`is_session_persistence_disabled`（`:14-31`）两级优先级：

```python
def is_session_persistence_disabled(*, session_flag: bool | None = None) -> bool:
    """优先级:
      1) 显式传入的 session_flag（SessionState 上的开关）
      2) 环境变量 XEYO_NO_SESSION_PERSISTENCE=1/true/yes
    """
    if session_flag:
        return True
    env = os.environ.get("XEYO_NO_SESSION_PERSISTENCE", "").strip().lower()
    return env in ("1", "true", "yes", "on")
```

| 场景 | 为什么要关 |
|---|---|
| **测试 / 评测** | 不污染真实会话目录（否则每次跑测试都留一堆 jsonl） |
| **隐私敏感会话** | 用户明确不希望留下记录 |
| **临时/一次性会话** | 只读问一句就走 |

**优先级设计**：**显式参数 > 环境变量**——代码里的调用点可强制关（哪怕环境没设），环境变量是运维级默认。★ 注意 `if session_flag:` 用**真值判断**，所以 `None`（未指定）与 `False`（显式开启）**无法区分**——两者都会走到环境变量。这是本卷的一处**待确认点**（是否需要三态）。

★ 对照 B09-0435 的 `resolve_modes`：那里用 `None` 表达「未提供」、非 None 表达「显式」，从而支持「请求体投影覆盖 durable 记录」；本处没有这个三态。

**评分要点**
- **及格**：能说出测试场景不该落盘。
- **良好**：能说出两级优先级。
- **优秀**：指出 `if session_flag:` 的真值判断使 `None` 与 `False` 不可区分——即**缺少三态**，并说明什么时候会出问题（调用方想强制开启但被环境变量关掉）。

**典型弱答**
- 只答「有个开关」不说优先级；
- 认为不能关（隐私与测试都需要它）；
- 把环境变量与显式参数当成同一级。

**追问**
如果调用方明确要「强制开启持久化」而环境变量是关，当前实现能满足吗？最小改法是什么？

---

### XEYO-QA-0354 单个转录文件多大要开始轮转

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | record_transcript 轮转阈值 | 阈值与代数 | 简单 | 概念确认 | `python/session/record_transcript.py:50-65` |

**面试官提问**
会话文件会一直长下去。你的轮转策略是什么？阈值多少、留几代？

**参考答案要点**
`_max_transcript_bytes`（`:50-61`）+ `_ROTATION_KEEP`（`:65`）：

```python
def _max_transcript_bytes() -> int:
    """单文件上限；超过即轮转（保留 2 代归档，可跨轮转恢复）。
    默认 32MB，可用 XEYO_TRANSCRIPT_MAX_BYTES 覆盖（下限 1MB）。"""
    raw = os.environ.get("XEYO_TRANSCRIPT_MAX_BYTES", "").strip()
    if raw:
        try:
            return max(1024, int(raw))
        except ValueError:
            pass
    return 32_000_000

_ROTATION_KEEP = 2
```

| 设计点 | 值 | 理由 |
|---|---|---|
| 单文件上限 | **32 MB** | 够一次长会话；过大则 `load_transcript` 全量读代价高 |
| 下限夹取 | `max(1024, ...)` | 防阈值设成 0 导致**每次写都轮转** |
| 归档代数 | **2**（`.old1` / `.old2`） | 保留 2 代 ≈ 最多 96 MB 历史；**不是无限留**（磁盘可控） |
| 轮转时机 | **写前检查**（`_maybe_rotate`，`:81`） | 保证「刚超限就被挪走」，而不是等到读时才发现 |

★ 阈值是**字节**而非**条数**——因为单条消息可以很大（工具结果），按条数无法控制磁盘与读取成本。

★ 「可跨轮转恢复」是设计意图：读侧必须**把归档一起读**（`:100-102`），否则轮转等于丢历史（0360/0369）。

**评分要点**
- **及格**：能说出有大小上限并会轮转。
- **良好**：能说出默认 32MB、保留 2 代、写前检查。
- **优秀**：能指出阈值按**字节**而非条数的原因（单条可很大），以及 `max(1024, ...)` 下限防的是「每次写都轮转」。

**典型弱答**
- 说「文件无限增长就行」（读取与内存代价不可控）；
- 保留代数设很多（磁盘不可控，且旧内容本就被 blob/回溯体系接管）；
- 忘掉读侧要一起读归档。

**追问**
如果一轮里一次 append 就把文件从 10MB 推到 50MB（单条超大消息），轮转发生在什么时候？会有什么后果？

---

### XEYO-QA-0355 轮转后的归档怎么命名、怎么读回

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | record_transcript 归档链 | 命名规则与读取顺序 | 简单 | 概念确认 | `python/session/record_transcript.py:68-102` |

**面试官提问**
轮转出来的旧文件叫什么？读的时候按什么顺序拼？

**参考答案要点**
```python
def rotated_transcript_paths(path: Path) -> list[Path]:
    """按「最旧 → 最新」返回全部归档路径（不检查存在性）。"""
    return [path.with_name(path.name + f".old{i}") for i in range(_ROTATION_KEEP, 0, -1)]

def rotated_transcript_path(path: Path) -> Path:
    """最新一代归档路径（<name>.jsonl.old1）；兼容单归档调用方。"""
    return path.with_name(path.name + ".old1")

def transcript_read_paths(path: Path) -> list[Path]:
    """按时间顺序返回应读取的 transcript 文件：[归档…]（存在者）+ 当前。"""
    return [p for p in rotated_transcript_paths(path) if p.is_file()] + [path]
```

| 名字 | 含义 |
|---|---|
| `<name>.jsonl` | **当前**（最新） |
| `<name>.jsonl.old1` | **较新**归档 |
| `<name>.jsonl.old2` | **最旧**归档 |

**读取顺序 = 最旧 → 最新**（`range(2, 0, -1)` 生成 `old2, old1`，再拼当前）——与「消息按时间顺序」的要求一致。

★ 代数语义要小心：**`i` 越小越新**（`.old1` 比 `.old2` 新）。轮转做的是「`.old1` → `.old2`、当前 → `.old1`」（0369）。

★ `rotated_transcript_path`（单数）是**兼容旧调用方**的便捷函数（只给 `.old1`）——「复数返回全部、单数只给最新」的命名约定。

**评分要点**
- **及格**：能说出 `.old1`/`.old2` 这类归档名。
- **良好**：能说出读取要「归档在前、当前在后」。
- **优秀**：能指出「序号越小越新」这一反直觉约定，并说明轮转方向是 `.old1`→`.old2`、当前→`.old1`。

**典型弱答**
- 把 `.old1` 当成最旧（方向反了，拼出来的对话顺序会错）；
- 只读当前文件（轮转即丢历史）；
- 把归档命名成时间戳（无法预知路径，读取时无法枚举）。

**追问**
如果 `_ROTATION_KEEP` 改成 3，哪些函数需要同步改？有没有硬编码 2 的地方？

---

### XEYO-QA-0356 异步写队列怎么保证「都落盘了」

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | record_transcript 异步写 | 序号与 flush 判定 | 简单 | 机制解释 | `python/session/record_transcript.py:41-45,183-191` |

**面试官提问**
写盘是异步的（后台线程）。调用方怎么知道「我刚提交的行都落盘了」？

**参考答案要点**
用**两个单调序号**做判据（`:41-45`）：

```python
# 后台写入队列：(seq, path, line)。seq 单调递增，用于 flush 判定「全部落盘」。
_pending: list[tuple[int, str, str]] = []
_cv = threading.Condition()
_submitted_seq = 0
_written_seq = 0
```

```python
def flush_pending_sync(timeout: float = 5.0) -> bool:
    """阻塞等待所有已提交行落盘；返回是否在超时前排空。"""
    deadline = time.monotonic() + timeout
    with _cv:
        while _written_seq < _submitted_seq:
            if time.monotonic() >= deadline:
                return False
            _cv.wait(0.2)
        return True
```

| 机制 | 说明 |
|---|---|
| 提交时 `_submitted_seq += 1` 入队（`:170-180`） | 每行一个序号 |
| 写入线程消费一批后 `_written_seq = max(_written_seq, max_seq)`（`:138-139`） | 记「写到哪」 |
| flush 等 `_written_seq >= _submitted_seq` | **不依赖「队列空」**——出队与真正写盘是两件事 |
| 每 0.2s `_cv.wait` + 总超时 5s | 条件变量 + 上限，避免永久阻塞 |

★ 关键设计：**判据用序号而不是队列长度**。用「队列为空」会在「已出队但尚未 write 完」的窗口里误判成功——这正是「flush 假成功」的经典写法。

★ 返回值语义：`True` = 超时前排空；`False` = **超时**（不代表丢失，但**不能假设已落盘**）。

**评分要点**
- **及格**：能说出用后台线程写、要有 flush 等它。
- **良好**：能说出「提交序号 vs 写入序号」的比较方式。
- **优秀**：指出**不能用「队列为空」当判据**（出队 ≠ 已落盘），并说明 `False` 的确切含义。

**典型弱答**
- 用「队列为空」判断落盘完成（存在已出队未写完的窗口）；
- 以为 flush 返回 True 就一定 fsync 过（要看 `_write_batch`，0383）；
- 让 flush 无限等待（调用方可能永久挂住）。

**追问**
`_write_batch` 里 `f.flush()` 之后还有 `os.fsync()`。如果只有 `f.flush()`，flush 返回 True 代表什么？（→ 0383）

---

### XEYO-QA-0357 进程退出时没写完的行怎么办

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | record_transcript 退出排空 | atexit 兜底 | 简单 | 机制解释 | `python/session/record_transcript.py:194-202` |

**面试官提问**
进程要退出了，队列里还有未落盘的行。你会怎么处理？

**参考答案要点**
注册 `atexit` 排空（`:194-202`）：

```python
def _atexit_drain() -> None:
    global _stop
    with _cv:
        _stop = True
        _cv.notify_all()
    flush_pending_sync(timeout=2.0)

atexit.register(_atexit_drain)
```

| 步 | 作用 |
|---|---|
| `_stop = True` + `notify_all()` | 唤醒写入线程；它看到 `_stop` **且队列空**才退出（`:129-130`） |
| `flush_pending_sync(timeout=2.0)` | 等最多 **2 秒**把已提交行写完 |
| （写入线程）`while not _pending and not _stop: wait(0.05)` | 队列非空时继续消费，**stop 之后仍会把已有队列写完** |

★ 两处时间常量不同：`atexit` 用 **2.0s**，`flush_pending_sync` 默认 **5.0s**。退出路径更短——因为退出不能等太久，代价是**极端情况下最后几行可能没落盘**（与 0385 同一处取舍）。

★ 写入线程是 **daemon=True**（`:164-166`）——主线程真正退出后它会被强杀。所以 `atexit` 排空是「**尽力窗口**」，不是保证。

★ 覆盖不到的路径：**SIGKILL / 任务管理器强杀 / 断电** —— `atexit` 不执行，只能靠「每次写都 fsync」（0383）缩小窗口。

**评分要点**
- **及格**：能说出退出时要 flush 一下。
- **良好**：能说出用 atexit 注册、写入线程是 daemon。
- **优秀**：能指出「2s vs 5s 的差异」与「daemon 线程会被强杀」两处限制，并说明强杀/断电路径完全覆盖不到。

**典型弱答**
- 认为 atexit 一定能跑完（SIGKILL 与断电不执行）；
- 把写入线程设成非 daemon 却不 join（退出时可能卡住）；
- 不做排空（正常退出也会丢最后几行）。

**追问**
如果一次退出时有 1000 行待写（例如刚批量导入历史），2 秒够吗？你会怎么改？

---

### XEYO-QA-0358 超大的消息内容怎么存

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | transcript_blobs 外置 | 阈值与目录 | 简单 | 概念确认 | `python/session/transcript_blobs.py:15-32` |

**面试官提问**
某条消息的 content 有 5 MB（例如工具返回的巨大结果）。你会把它直接写进 JSONL 吗？

**参考答案要点**
不会——**超过阈值就外置成独立文件**（`:15-32`）：

```python
def blob_threshold_bytes() -> int:
    """超过此大小的 content 外置；默认 32KB（XEYO_TRANSCRIPT_BLOB_THRESHOLD）。"""
    ...
    return 32_768

def blobs_dir(anchor: Path) -> Path:
    """与 anchor.jsonl 同级的 blob 目录：``{stem}.blobs/``。"""
    return anchor.parent / f"{anchor.stem}.blobs"

def blob_file(anchor: Path, message_id: str) -> Path:
    return blobs_dir(anchor) / f"{message_id}.json"
```

| 设计点 | 值/形态 |
|---|---|
| 阈值 | **32 KB**（`32_768`），环境变量可覆盖（下限 512） |
| 目录 | 与 jsonl **同级**：`<stem>.blobs/` |
| 文件名 | `<message_id>.json` |
| 行内留下 | `content_ref` = `"<message_id>.json"` + `content_hash` = `"sha256:<hex>"`（`:39-48`） |

**为什么外置**：

| 问题 | 若不外置 |
|---|---|
| 轮转阈值按字节 | 一条 5MB 消息吃掉 32MB 预算的 1/6 → **轮转次数暴涨** |
| 读取成本 | `load_transcript` 每次恢复都 read + `json.loads` 整行（含 5MB） |
| 内存峰值 | 一次 hydrate 把全部大内容读进内存 |
| 局部读取 | 想看某条正文，必须解析整个文件 |

外置后：**行保持小**（只留引用），大内容按需读（`resolve_transcript_row`）。

★ 还写了 `content_hash`（`sha256:<hex>`）——**证据型字段**，可用于校验 blob 与行是否对应（0389）。

**评分要点**
- **及格**：能说出大内容要外置成文件。
- **良好**：能说出阈值默认 32KB、目录形态、行内留引用。
- **优秀**：能指出外置的三个具体收益（轮转预算不被吃 / 恢复不解析大内容 / 可按需读）与 `content_hash` 的校验价值。

**典型弱答**
- 把 5MB 直接写进 JSONL（轮转爆炸 + 每次恢复都要解析）；
- 外置但不留引用（内容找不回来）；
- 按消息序号命名 blob（消息 id 才是稳定标识）。

**追问**
如果同一条消息被写入两次（重试），blob 文件名会冲突吗？`os.replace` 会有什么后果？

---

### XEYO-QA-0359 怎么知道某个会话属于哪个工作区

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | ws_index 归属索引 | 索引形态与查询 | 简单 | 概念确认 | `python/session/ws_index.py:36-63` |

**面试官提问**
会话文件按 id 命名，那怎么回答「这个工作区有哪些会话」？

**参考答案要点**
用一份**独立的 JSONL 归属索引**（`:36-63`）：

```python
def index_path() -> Path:
    """workspace 归属索引文件路径。"""
    return _sessions_dir() / "_workspace_index.jsonl"

def _read_all() -> dict[str, str]:
    """读全量索引 → {session_id: workspace_id}（后行覆盖前行）。"""
```

| 项 | 形态 |
|---|---|
| 位置 | `~/.xeyo/sessions/_workspace_index.jsonl`（与转录**同目录**） |
| 行内容 | `{session_id, workspace_id}` |
| 语义 | **后行覆盖前行**（`:42`）——最新登记胜出 |
| 进程内缓存 | `_cache` + `_loaded` 标志（`:23-25`），懒加载（`:67-71`） |
| workspace_id 来源 | `memory.memdir.workspace_id(cwd)`（懒加载包装避免导入环，`:74-78`） |
| 写入 | `record_session_workspace`：「同会话同工作区**幂等不写盘**」，失败只记 debug（`:81-`） |

**为什么不扫描转录文件**：转录里**没有**工作区信息（只记消息），而「按工作区列会话」是 UI 高频需求（侧栏按项目分组）。若靠扫全部 jsonl + 读 sidecar 里的 cwd，成本是 O(会话数 × 文件大小)。

★ 反向查询（`sessions_for_workspace`，`:108-`）在这份小文件的**内存字典**里做，是 O(会话数) 而无磁盘 I/O。

★ 「幂等不写盘」很重要：会话每轮都会登记，若不判重会把索引写成无限长（每轮一行）。

**评分要点**
- **及格**：能说出有一份会话→工作区的索引。
- **良好**：能说出索引是 JSONL、同目录、后行覆盖前行。
- **优秀**：能指出「为什么不在转录里找答案」（转录不含工作区信息，扫描成本高）以及「幂等不写盘」防索引膨胀的作用。

**典型弱答**
- 靠扫转录文件判断归属（转录里没有 cwd）；
- 每轮都追加一行（索引无限膨胀）；
- 把索引放在工作区目录里（跨工作区查询就没了）。

**追问**
索引是「一次登记、永久记住」还是「会话结束才登记」？如果会话中途换了工作区呢？（→ 0377）

---

### XEYO-QA-0360 为什么读转录必须把归档一起读

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | 读侧与轮转的配合 | 读取链完整性 | 简单 | 机制解释 | `python/session/record_transcript.py:100-102` + `python/session/hydrate.py:119-133` |

**面试官提问**
轮转会把旧内容挪到归档。读的时候如果只读当前文件，会发生什么？

**参考答案要点**
只读当前文件 = **历史丢失**。所以读侧必须按时间顺序拼全部（`:100-102`）：

```python
def transcript_read_paths(path: Path) -> list[Path]:
    """按时间顺序返回应读取的 transcript 文件：[归档…]（存在者）+ 当前。"""
    return [p for p in rotated_transcript_paths(path) if p.is_file()] + [path]
```

`hydrate.messages_from_transcript`（`:119-133`）正是这么做的：

```python
    rows: list[dict[str, Any]] = []
    for p in transcript_read_paths(path):
        rows.extend(load_transcript(p))
    return messages_from_rows(resolve_transcript_rows(fold_surface_rows(rows), path))
```

**顺序必须是「最旧 → 最新」**，因为：

| 消费方 | 对顺序的依赖 |
|---|---|
| 消息列表 | 对话顺序（时间序） |
| `fold_surface_rows` | 「从可见面**末尾反向**定位 `shadow_from`」（`surface.py:71-72`）——顺序错了定位就错 |
| 去重记账 | `_load_written_ids` 也遍历 `transcript_read_paths`（`:236-240`） |

★ 这解释了轮转阈值不能太小的**第二个理由**（第一个是磁盘）：每次恢复都要读**全部归档 + 当前**，`_ROTATION_KEEP` 越大、单文件越大，恢复越慢。32MB × 3 ≈ 96MB 的上限就是这个平衡点。

**评分要点**
- **及格**：能说出读要包含归档。
- **良好**：能说出顺序是「最旧 → 最新」及其原因（对话顺序 + fold 依赖）。
- **优秀**：能指出「恢复成本 = 全部归档 + 当前」这一推论，并说明轮转阈值/代数其实是**磁盘与恢复速度的平衡点**。

**典型弱答**
- 只读当前文件（轮转即丢历史）；
- 顺序写成「当前在前」——fold 的末尾反向定位会错；
- 把轮转看成纯磁盘优化（它同时决定恢复成本）。

**追问**
`fold_surface_rows` 为什么强调「从末尾反向定位」而不是从头正向找？这与「同一行 id 可能出现两次」有关吗？（→ 0399）

---

### XEYO-QA-0361 回溯后为什么要把归档删掉

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | discard_rotated_transcripts | 已删内容复活 | 简单 | 机制解释 | `python/session/record_transcript.py:105-119` |

**面试官提问**
用户回滚了会话（删掉后面几轮）。如果其中有些内容已经被轮转进归档，会有什么问题？

**参考答案要点**
会**复活**。所以有一个专门的函数（`:105-119`）：

```python
def discard_rotated_transcripts(path: Path) -> list[str]:
    """删除轮转归档，防止 rollback 截断后 GET/hydrate 把已删回合再拼回来。
    返回已删除路径的字符串列表（便于审计）。当前 ``path`` 本身不动。
    """
    removed: list[str] = []
    for archived in rotated_transcript_paths(path):
        if not archived.is_file():
            continue
        try:
            archived.unlink()
            removed.append(str(archived))
        except OSError:
            _logger.debug("discard rotated transcript failed: %s", archived, exc_info=True)
    return removed
```

**问题机制**：回滚（物理重写路径）通常只处理**当前** jsonl；但**归档里的旧行还在**，而读侧会把归档一起读回来（0360）→ 用户看到「我回滚了但那些回合又出现了」。

| 设计点 | 说明 |
|---|---|
| 删**全部**归档而非某一个 | 无法判断被删回合落在哪一代，保守全删 |
| **不动当前文件** | 当前文件由回滚自己的物理重写负责 |
| 返回删除清单 | **便于审计**（回滚有破坏性，要知道删了什么） |
| 失败只 `debug` | 删不掉不能让回滚流程崩（但留下复活风险——这是取舍） |

★ 与 B09-0450（回滚后三载体残留）是**同一类故障**的另一处载体：被删内容的**派生副本**散落在多处（归档、sidecar、`session.md`、delta、fragments），每一处都要清。

**评分要点**
- **及格**：能说出归档里可能残留已删内容。
- **良好**：能说出「读侧会拼归档 ⇒ 必须删归档」，且返回删除清单用于审计。
- **优秀**：能把它归到「同一语义多载体」这一类结构问题，并列举类似的其它载体。

**典型弱答**
- 只回滚当前文件（归档让内容复活）；
- 删归档失败时让回滚流程抛错崩掉；
- 删归档也把当前文件删了（丢未回滚的历史）。

**追问**
如果回滚只该删「某几个回合」，而归档是全删，会不会误删仍应保留的历史？你会怎么改进？（→ 0387）

---

### XEYO-QA-0362 会话状态对象承载什么

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | session.state | 状态与回退 | 简单 | 概念确认 | `python/session/state.py:30-101` |

**面试官提问**
一个会话在内存里需要一个状态对象。你会往里放什么？它和磁盘上的转录是什么关系？

**参考答案要点**
`SessionState`（`:30-86`）承载**会话级元状态**（不是对话内容），另有 `os_path_fallback`（`:87-101`）做路径回退。

| 类别 | 例子 | 与转录的关系 |
|---|---|---|
| **持久化开关** | `session_flag`（被 `is_session_persistence_disabled` 消费，0353） | 影响是否写转录 |
| **会话标识** | session_id / 标题一类 | 转录文件名的来源 |
| **运行时视图** | 当前工作区、surface 等 | 与 `ws_index` / 归档协作 |

**关键设计原则**：**对话内容是权威（转录），状态是派生/辅助**。判据：

```
若这条信息丢了，能否从转录重建？
  能   -> 属于状态（可重建，丢了没关系）
  不能 -> 必须进转录（权威）
```

★ 这条判据在本项目反复出现：`working.WorkingSnapshot`（B09）是**机器状态**（可从转录重建），而转录本身是**权威**（B09-0432「转录是最终真相，fragments 只是抓拍」是同一原则的另一处表达）。

★ `os_path_fallback`（`:87-101`）的存在说明：状态里的路径在不同平台上可能需要回退形式（长路径 / 相对路径一类），即**状态对象要容忍路径形态差异**。

**评分要点**
- **及格**：能说出状态对象放会话元信息（不含对话内容）。
- **良好**：能说出「转录是权威、状态是派生」这条分工。
- **优秀**：能给出「能否从转录重建」这条判据，并指出它与 `WorkingSnapshot`（B09）是同一原则；进一步指出 `os_path_fallback` 说明路径形态需容错。

**典型弱答**
- 把对话内容也放进状态对象（两份真相，必不一致）；
- 认为状态丢了会话就废了（可从转录重建）；
- 不做路径形态回退（跨平台/长路径下失败）。

**追问**
如果状态对象里的某个字段与转录推导出的值冲突，应该以谁为准？为什么？

---

### XEYO-QA-0363 cwd 有哪几层解析

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | session.cwd | 解析层级与上下文 | 简单 | 概念确认 | `python/session/cwd.py:20-71` |

**面试官提问**
工具要解析相对路径，需要一个「当前目录」。这个值从哪里来？

**参考答案要点**
`cwd.py` 提供四项（`:20-71`）：`get_original_cwd()` / `get_cwd(*, _skip_context=False)` / `set_cwd(...)` / `reset_cwd_for_tests(...)`。

**解析层级（结合 B07-0342 的 `_tool_cwd` 与 `default_permission_context`）**：

```
① 显式传入（工具调用的 working_directory / context.cwd）
     ↓ 未给
② 会话级 WorkspaceContext.cwd（get_cwd 默认走它）
     ↓ 未给
③ 进程当前目录（os.getcwd()）
```

| 设计点 | 证据 | 意义 |
|---|---|---|
| **「原始 cwd」与「当前 cwd」两个概念** | `get_original_cwd()` vs `get_cwd()` | 会话启动目录与**可能已变更**的当前目录要分开 |
| **`_skip_context` 参数** | `:26` | 允许**绕过上下文**取真值（供需要「真值」而非「会话视图」的调用方） |
| **`reset_cwd_for_tests`** | `:66-71` | 测试隔离（cwd 是隐式状态，必须复位） |

**为什么优先用会话上下文而不是 `os.getcwd()`**：`filesystem.default_permission_context` 的 docstring 写明（B07-0342）——「避免多并发会话读取模块级全局 cwd 而**串目录**」。`os.getcwd()` 是**进程级**的，多会话并发时会互相覆盖。

**评分要点**
- **及格**：能说出 cwd 来自会话/调用参数而不是全局。
- **良好**：能说出三层优先级与「原始 vs 当前」的区分。
- **优秀**：能指出 `os.getcwd()` 是进程级、多会话并发会**串目录**，因此必须优先走会话上下文；并解释 `_skip_context` 与 `reset_cwd_for_tests` 各自的服务对象。

**典型弱答**
- 直接用 `os.getcwd()`（多会话/子 agent 必串）；
- 只有一个 cwd 概念（分不清「原始」与「当前」）；
- 不做测试复位（测试间互相污染）。

**追问**
子 agent 应该继承主会话的 cwd 吗？如果它自己 `cd` 到别处，权限判定该用哪个？

---

### XEYO-QA-0364 内存消息存储的定位

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | message_store | 内存态与持久态 | 简单 | 机制解释 | `python/session/message_store.py:6-55` |

**面试官提问**
既然有转录落盘，为什么还需要一个内存消息存储？两者谁说了算？

**参考答案要点**
`MessageStore`（`:6-55`）是**会话的内存消息列表**，与转录的关系是「**同源、不同时效**」：

| 层 | 位置 | 特点 |
|---|---|---|
| **内存态** | `MessageStore` | 快、进程内、可追加与截断；进程退出即失 |
| **持久态** | transcript JSONL | 追加写、权威、可跨重启恢复 |

```
每轮：模型调用 -> 追加 assistant/tool 消息（内存）
                同时 -> 异步 append 到转录（磁盘）
重启：转录 -> hydrate -> 重建 MessageStore（0360/0378）
```

★ 谁是权威：**转录**。内存态可能丢（进程崩、被截断），而转录是行式追加的既成事实。与 B09 的记忆层（文件权威、sqlite 派生）和 B06-0275（Todo 从转录恢复）是同一条原则。

★ 由此推出一条**正确性要求**：**内存态的每次变更都必须同步到转录**，否则「重启后状态回退」。实现上由去重记账保证（0367）。

★ 反向要求：**转录里的行在内存态不一定都在**（例如被 surface fold 影子化的行，0371）——两者**不是简单等价**，而是「转录 = 全部事件、内存态 = 当前可见面」。

**评分要点**
- **及格**：能说出内存态用于运行、转录用于持久。
- **良好**：能说出转录是权威、重启靠 hydrate 重建。
- **优秀**：能指出两者**不是等价关系**（转录含全部事件、含被影子化的行；内存态是可见面），所以「以谁为准」要按用途区分。

**典型弱答**
- 认为内存态是权威（崩了就丢）；
- 认为两者完全等价（忽略 fold 会隐藏行）；
- 每轮全量重写转录（O(n) 写放大）。

**追问**
被 surface fold 隐藏的行还应该在内存态里吗？如果模型要求「看看我删掉的那些回合」，你会从哪读？

---

### XEYO-QA-0365 为什么磁盘写要单独一把锁

| 能力域 | 子模块 | 考查点 | 难度 | 问法 | 来源依据 |
|---|---|---|---|---|---|
| 会话与持久化 | record_transcript 并发 | 临界区范围 | 中等 | 机制解释 | `python/session/record_transcript.py:36-39,143-157` |

**面试官提问**
有两路写：后台批量线程与同步直写。它们会打架吗？你怎么防？

**参考答案要点**
会打架，所以有一把**磁盘临界区锁**（`:36-39`）：

```python
# G107: 磁盘临界区锁——后台写入线程与 record_transcript_sync 直写共用,
# 防止 rotate(rename 当前→归档)与另一路 append 交错:写者把行追加进已轮转的
# 归档或新文件出现重复/丢行。
_disk_lock = threading.Lock()
```

| 交错情形 | 后果 |
|---|---|
| A 正在 rotate（`os.replace(path, old1)`），B 同时 append 到 `path` | B 的行写进**刚被挪走的归档**（或新文件出现重复行） |
| 两路同时 `_maybe_rotate` | 归档链被挪两次（`.old2` 被覆盖，丢一代历史） |

**锁的作用范围**（`:143-157`）：

```python
		with _disk_lock:
			p.parent.mkdir(parents=True, exist_ok=True)
			_maybe_rotate(p)                      # ← rotate 与 append 同一临界区
			with p.open("a", encoding="utf-8") as f:
				f.writelines(lines)
				f.flush()
				os.fsync(f.fileno())
```

即 **`mkdir + rotate + append + fsync` 全在锁内**。

★ 还有**第二把同步原语**：`_cv = threading.Condition()`（`:43`）保护**内存队列**（`_pending` / seq）。两把锁管两个不同的东西：

| 锁 | 保护对象 | 持有时间 |
|---|---|---|
| `_cv`（Condition） | 内存队列与序号 | 短（入队/出队） |
| **`_disk_lock`** | **磁盘操作（rotate + append + fsync）** | 长（含 fsync，可能几十毫秒） |

★ 这个分离很重要：若用一把锁，`fsync` 期间会阻塞入队 → **写者被 I/O 拖住**（队列积压）。

**评分要点**
- **及格**：能说出有锁保护写盘。
- **良好**：能说出锁保护的是「rotate 与 append 必须原子」，并给出交错的具体后果。
- **优秀**：能指出**两把同步原语的分离**（Condition 管队列、`_disk_lock` 管磁盘），并说明合并成一把会因 fsync 阻塞入队。

**典型弱答**
- 认为只有一把锁就够（rotate 与 append 交错会丢行/重复行）；
- 把锁加在入队处而不是磁盘处（保护了错的对象）；
- 在 fsync 时持锁入队（写者被 I/O 阻塞，队列积压）。

**追问**
如果同一进程有两个会话在写（不同 path），`_disk_lock` 会不会无谓串行？值得细化成 per-path 锁吗？

---

<!-- APPEND -->





---

## 批次自检表（B08）

> 占位：正文完成后回填。
