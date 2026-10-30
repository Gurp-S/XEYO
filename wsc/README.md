# WSC

Work State Compaction。给长期运行的 coding agent 做上下文压缩的 Python 组件。独立进程内库，旁路接入，默认关闭。

压缩最容易出的问题不是丢信息，而是"看起来接上了，实际接错了"。文件 V1 通过测试，改成 V2 后还没验证，压缩完只剩一句"文件已修改，测试通过"——字都是真的，版本对应关系没了，模型据此认为 V2 已验证。WSC 把压缩当成一次可核对的发布，而不是一次改写文本。

和摘要式压缩相比，差别在三点：

- **不可覆写**：来源按原样入库，重复投递不会产生新事件，压缩只读不写
- **不可跳步**：候选写盘不算完成，要拿到宿主的持久回执才能推进折叠位置
- **可回查**：留在上下文里的每条结论都能顺着来源序号回到原始字节

## 机制

### 简单描述

取一段不可变的来源，固定成快照，让调用方的模型决定留什么，在字节预算内生成候选视图，交给宿主原子安装，拿到持久回执之后才推进折叠位置。任何一步结果不确定，就停在原地，不猜、不重发。

### 完整描述

**1. 来源。** 原生事件（消息、工具调用、工具结果、opaque 项）按原样入库。同一 id 重复投递不产生新事件，一个批次在一个事务里提交。工具调用和结果靠 `(call_id, kind)` 唯一索引配对，缺一半直接拒绝导出，不完整的东西不许进入压缩。opaque 项原样归档，不尝试解密，也不进热上下文。

**2. 快照。** 一次压缩的输入固定成快照，绑定会话、工作区、代次、控制版本、理解版本、`cut` 和来源摘要。`cut` 是来源序号，不是压缩后数组的下标。快照每次使用前重新校验，前缀变了就拒绝。控制或理解版本变化会让旧候选失效；新到的普通尾部事件不会。

**3. 选材。** 留什么由调用方的模型决定，核心不做关键词排名，也不内置摘要提示词。三种前端（原文引用、字符区间、精确片段）只负责把选择绑到字节上：算范围、算内容哈希、校验唯一匹配。模型改写、来源对不上、路径已经变了，一律返回事实状态，不修补。标了控制位的事件（user/system/developer 角色，或显式 `control=True`）强制并入，不受选材影响。模型明确说出的判断另存为理解，带来源、类别、适用范围和版本号，修订走 CAS，没有来源的假设不会被升级成事实。

**4. 预算。** 生成前先算必留消息与视图骨架的字节下界。下界已超 `max_view_bytes` 时，在模型调用和记账之前返回 `mandatory_view_byte_budget_exhausted`；候选整体超限同样拒绝。上限按字节计，不按 token 折算，真实容量由宿主按实际请求判断。

**5. 发布。** 候选写盘只是 `ready`，不等于安装。`install` 时宿主在同一个同步边界内检查代次、控制版本、容量和在途工具，返回持久回执；只有 `confirmed` 才推进折叠游标。`rejected` 表示该操作从未安装且此后不会安装，可以安全重做；`lookup` 返回 `None` 表示结果未知，不等于没执行，此时走 `reconcile` 对账，不重发请求，也不重复执行任务工具。安装超时保留来源和未推进的游标。传入 `resource_io=ResourceIO()` 时，安装会在描述符层持有路径租约（Windows），并在安装前重新核对每个证据文件的摘要。

**6. 证据与账本。** 证据读取单独一层：授权检查加精确字节读取，部分哈希、对象哈希、观察时间、完整性分开报；引用可以带资源哈希去查当前位置，只在唯一匹配时给行号。另有可选的快照内字面检索（`SnapshotLiteralAccess`），按调用上限扫描已封存来源，命中后再做实时校验，不做语义排序。用量单独记账：调用发出前登记，失败、超时、没回执都保留，没报的用量记 `null`，汇总分成已知和未知两类。

组件不判断语义对错，不替宿主执行任务，不伪造安装回执。生成由调用方提供：组件不内置供应商、不内置提示词、不读密钥，只负责预算、边界与记账。宿主如果没有原子安装和持久查询能力，就只能停在导出边界。

### 机制图

```mermaid
flowchart TD
    subgraph 压缩
        E["原生事件<br/>消息 / 工具调用 / 结果 / opaque"] --> S["来源入库<br/>幂等 · 调用配对 · 单事务"]
        S --> SN["固定快照<br/>会话 · 工作区 · 代次 · 控制版本 · cut"]
        SN --> SEL["模型选材<br/>引用 / 区间 / 片段"]
        SEL --> V["候选视图<br/>必留内容 + 字节下界"]
    end

    subgraph 发布
        V --> ST["导出 stage<br/>ready"]
        ST --> IN["宿主 install<br/>同步边界内校验"]
        IN -->|confirmed| CUR["推进折叠游标"]
        IN -->|rejected| KEEP["保留来源<br/>不推进"]
        IN -->|unknown| RC["reconcile 对账"]
        RC --> IN
    end

    subgraph 回查
        RD["证据读取<br/>授权 · 精确字节 · 版本匹配"]
    end

    SN -.-> RD
    CUR -.-> RD
```

## 安装

Python 3.11 以上，运行时只用标准库。

```bash
python -m pip install --no-deps .
```

## 用法

```python
from wsc import WSC, Store, Selection, Understanding
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost

core = WSC(
    Store(db_path, session_id=session_id, workspace=workspace),
    access=current_source_permission,      # 宿主提供的授权检查
)

adapter = CodexCheckpointAdapter()
core.ingest(adapter.import_items(native_items, thread_id=native_thread_id))
core.presented(request_id, presented_source_ids, receiver=actual_receiver)
# 一个回合有多条结果时，用一次事务提交：
# core.presented_many([(request_id, source_ids, actual_receiver), ...])

snapshot = core.capture(cut=source_boundary)
view = core.prepare(snapshot, Selection(), producer=model_output_identity)

operation = core.stage(view, directory=export_directory, adapter=adapter)
host = CallbackHost(commit=atomic_host_install, lookup=durable_host_lookup)
receipt = core.install(operation, host)      # 返回已确认的回执（dict）
```

选材也可以交给模型：`core.generate(snapshot, generator, producer=..., limits=...)`。generator 收到公开材料，返回 `Generated(Selection(...), Usage(...))`；`JsonCommandGenerator` / `BoundedJsonCommandGenerator` 提供了 stdin/stdout 的 JSON 传输，带超时与输出上限。调用方负责实际模型调用和诚实用量。

构造参数里还有几个可选开关，默认全部关闭：`resource_io=ResourceIO()` 启用有界描述符 I/O 与安装期路径租约；`query_policy="prefix_index_v1"` 让快照校验走前缀索引；`publication_policy="bounded_catalog_v1"` 在最终绑定校验前释放导出的目录副本；`evidence_sync=False` 跳过逐对象 fsync（只保证进程崩溃安全，不保证掉电）。

CLI 每条命令都显式绑定 `--db`、`--session`、`--workspace`，不会去猜或改现有会话：

```bash
wsc --db state.db --session sample --workspace . import-native --input canonical-state.json
wsc --db state.db --session sample --workspace . prepare --selection selection.json --producer existing-model-output
wsc --db state.db --session sample --workspace . export --view VIEW_ID --directory checkpoint-output
wsc --db state.db --session sample --workspace . status
```

全局还有 `--resource-io`、`--prefix-index`、`--bounded-catalog` 三个开关，对应上面同名的构造参数。

## 什么时候不该用 WSC

- 宿主没有原子安装和持久查询能力。这种情况只能导出检查点，发布协议用不起来。
- 需要透明替换原生压缩。当前适配器只做显式检查点导出与恢复，不做原位替换。
- 多租户服务。CLI 走本机文件权限，必须自己接 SDK 的授权回调。
- 目标是省 token 或省费用。组件按字节管预算，不承诺 token 数或账单下降。

设计与取舍记录在 [`reviews/`](reviews/)，逐轮的验证材料在 [`validation/`](validation/)。

## 状态

接口还在演进，不保证向后兼容。仍在逐步实验中，暂不建议直接接生产链路。

## 工具大结果外置（独立旁路）

`wsc.tool_results` 提供完整UTF-8文本外置、七类按类型概览、精确分页查询及同步/异步工具包装器。SDK显式启用，独立CLI为 `wsc-results`；未自动替换原生Codex或其他宿主工具结果。[接入、默认限额和验证说明](reviews/runtime-tool-results-v1.md)。

`wsc.context_runtime.ContextRuntime` 将原来源与外置结果绑定到统一 `WSCContext` 查询，并复用现有呈现回执、连续检查点发布及对账。原文、视图和模型理解分开，默认不自动触发模型摘要。[统一生命周期与原生宿主旁路](reviews/context-lifecycle-v1.md)。

## License

MIT
