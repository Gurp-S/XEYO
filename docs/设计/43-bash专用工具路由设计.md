# 43 号计划：Bash → 专用工具路由（观测先行 + 透明路由）设计

> 状态：**已冻结**（三阶段实现并经真实会话 + 测试验证；默认 `bash_routing=off`、`bash_escalate=0`）。
> 冻结决策集（定稿，勿未评审改动）：
> - 路由面：`cat/type/Get-Content→Read`、`rg/grep/findstr→Grep`（区内，成员前置）；`ls/dir/find` **不路由**。
> - BashTool cmd 输出编码：UTF-8→GBK 回退（`tools/bash_tool/runner.py::_decode`）。
> - Phase 2 渐进强制：`bash_escalate`（默认 0=关；推荐 3、上限 5；仅 L2 路径）；
>   `GET/POST /v1/workspace/policy-bash`；GUI `gui/src/components/BashRoutingSetting.tsx`。
> - UI：工具区显示 `Bash → Read/Grep`。
> 相关代码：`tools/bash_tool/dup_redirect.py`（解析）、`tools/tool_registry.py`（执行缝）、
> `tools/bash_tool/bash_tool.py`（L2 现有重定向）、`gui/src/lib/toolActivity/`（工具活动展示）。

## 1. 背景与问题

模型常拿 Bash `cat/find/ls/rg` 干本应由 `Read/Glob/Grep` 干的活。根因：

1. **描述太软**：模型可见（schema 预算开启时）的是 `tools/meta.py` 短描述；
   旧文案 "Prefer Glob/Grep…when they fit" 是建议而非边界（已改）。
2. **激励错位**：`permissions/bash_policy.py` 的只读白名单把 `cat/type/ls/dir/rg/grep/findstr`
   全部自动放行（`bash=default` 零确认），而 Read 要绝对路径——用 Bash 读文件零成本。
3. **已上 L2（错误重定向）**：`BashTool.execute` 对"意图无歧义的纯文件读命令"返回
   `is_error` 提示（Use Read/Glob/Grep instead），模型在调用点被纠正——代价是**每
   次误用多花一次往返**（约 1.5–3s + 1–2k tokens），且模型可能换一种写法继续错。

## 2. 目标 / 非目标

- **目标**：把"误用→报错→重试"升级为"引擎透明执行等价专用工具 + 一行 [routed] 提示"，
  使往返降为 0；模型同时拿到数据与纠偏信号；误用率可观测（审计）。
- **非目标**：不拦截真正无对应工具的 Bash 命令（构建/测试/进程/网络/git 写）；
  不做 bash 权限收紧（不动 `_READONLY_BASES`，避免每次 `ls` 弹确认的副作用）；
  Phase 2 渐进强制仅作 v2。

## 3. 决策记录（用户已拍板）

| 决策点 | 结论 |
|---|---|
| 1 路由形状 | **最终（经实测修正）**：T1（cat/type/Get-Content/gc→Read）、T2（rg/grep/findstr→Grep，显式 `output_mode="content"`）**路由**；**T3（ls/dir/find）不路由**——Glob 对宽匹配 `*` 只回目录摘要（文件数）不列文件名、且 `find` 不在 bash 只读白名单（`bash=default` 先 ASK），故原样交给 bash（见 §3.1） |
| 2 学习信号 | 纯透明（A）起步；渐进强制（C）作 v2（同会话同形状第 2 次命中转 is_error） |
| 3 失败降级 | 目标工具 DENY → 回退原 Bash（已 ALLOW）；其它错误 → **原样返回目标工具的错误**；worker 子代理 **开**路由 |
| 4 落地节奏 | **观测先行**：P0 只记审计 → P1 开关灰度（`bash_routing: auto\|off`）→ P2 默认 |
| 5 UI | 工具活动"使用的工具"处显示 `Bash → Read`（实际执行工具）；**其他任何地方不标注** |

### 3.1 数据驱动的补充（真实会话基线，Phase 0 产出）

用 `scripts/analyze_bash_routing.py` 重放 43 个历史会话（387 次 Bash 调用）得到采集前基线：

- 误用命中 15 次（**3.88%**）；**T1=3**（cat/type）、**T2=0**（无 rg/grep 误用）、**T3=12**（`dir` 列目录）。
- **80%（12/15）的目标都在工作区外**（`dir C:\Users\…\.dsh\…`，DSH 数据目录）。
- 后续纠偏：correct=1(6.7%)、仍Bash=12、其他=2 → **仅软描述下模型基本不自我纠正**。

结论：路由收益主要来自**工作区内**的文件操作；对区外 `dir` 这类，路由到 Glob 会
DENY→回退 bash，等于白跑一次。因此 Phase 1 加"**成员前置**"：区内才路由，区外直行
bash（见 §4 Phase 1）。

**T3 实测否定（后续以真实会话修正原"一并纳入 T3"决策）**：真实会话中 `dir "docs\设计"`
被路由到 Glob(`pattern="*"`) 后，**只回 `./ (30 files)`（目录摘要、只有文件数、没有文件名）**，
无法满足"列出目录内容"的用户意图——因为 Glob 是"按名搜索"工具，刻意对宽匹配 `*` 只回
摘要并引导"加文件名片段"。故 **`ls`/`dir`/`ll`/`la` 一律不路由**（交给 bash 真实列目录）；
`find` **不在 bash 只读白名单**，`bash=default` 下先 ASK、ALLOW 分支到不了，路由不触发，
也不纳入解析。

## 4. 阶段划分

### Phase 0 —— 观测期（零行为变更，本阶段实施）

- `plan_bash_route(command)` 纯函数（`tools/bash_tool/dup_redirect.py`），对 T1/T2/T3
  全形状解析，返回 `BashRoutePlan(tier, tool_name, tool_input, brief, hint)`；与现有
  `redirect_hint` 同源（同一解析核心，提示文案逐字节不变）。
- `ToolRegistry.run` 的 Bash ALLOW 分支命中即记审计 `tool.routed_observed`
  （tool_name=Bash, tier, routed_to, command 摘要），**不路由、不拦截**，继续原执行。
- 现有 L2 `BashTool.execute` 重定向保持不变——观测的正是当前行为下的误用频率。
- 数据产出：命中率、T1/T2/T3 分布、误判排查 → 用于（a）决定 T3 是否/如何路由，
  （b）Phase 1 效果对比基线。
- 可离线补测：把历史 transcript 的 Bash 调用喂给 `plan_bash_route` 统计（复用
  `scripts/memory_stack_eval.py` 式样本脚本，非本期范围）。

### Phase 1 —— 透明路由（默认 off，`workspace_policy.bash_routing: auto|off`）

- 接线点：`ToolRegistry.run` ALLOW 分支（唯一执行缝；CLI/server/子 agent/MCP 网关一致）。
- **工作区内/外成员判定（前置门，§3.1 新增）**：路由前对目标工具的主路径做 workspace
  成员判定（复用 `permissions.filesystem.path_in_allowed_working_path`，
  cwd=registry.cwd / allowed_paths）：
  - **仅工作区内才路由**；工作区外 → **不路由，bash 直行**（避免"路由→DENY→回退"白跑）；
  - 无显式 path 的形状（`rg pat`、`cat 相对路径`）按 cwd=工作区 → 视为区内；
  - Read 的 `file_path` 先 `expand_to_abs`（含 `~`）再判定。
- **T1+T2** 路由执行（区内）；**ls/dir/ll/la、find 不路由**，原样交给 bash（§3.1 实测）。
- 执行方式：构造 `ToolUse(routed)` 递归 `self.run` → 目标工具自走三态权限 + 审计 +
  输出预算 + **共享 ReadFileState**（不破坏 "File unchanged since last read" 缓存与
  Edit 的 "modified since read" 检查）。绝不在 BashTool 内 new 目标工具实例。
- 降级（决策 3 + 成员前置）：
  - **成员前置失败（区外）** → **不路由**，直接走原 Bash（已 ALLOW，现状零提示）；
  - 成员前置通过但目标工具仍 DENY（会话 allowed_paths 变化等异常）
    → 回退 `_execute_audited` 原 Bash（已 ALLOW），绝不把 DENY 当结果；
  - 其它错误（不存在/二进制/超时）→ 原样返回目标工具错误 + [routed] note。
- 边界：
  - readonly 会话：Bash 被 `readonly_gate` 先拒 → 不路由（读本应直连 Read）；
  - `bash=ask`：用户批准后原样执行，不路由（批准语义是 Bash）；
  - **worker 开**：worker 的 T1/T2 同样路由（目标工具均在子代理 baseline，
    `SUBAGENT_APPEND` 的"短只读命令"意图一致，执行从 shell 换到专用工具更受控）；
  - 复合/不可映射形状一律不路由（宁放勿拦）：管道/重定向/链式/通配符/多文件/
    `ls -lt`/`rg -l/-c/-v`/`find -exec/-type`/`head/tail/wc/echo`。
- **L2 执行层拦截必须有**：随 Phase 1 **上移**到 registry（同处决策），从
  `BashTool.execute` 移除——否则回退路径会被 execute 层二次拦截（死循环），且
  execute 层拿不到共享 read_state。
- 返回：`[routed: Bash cat → Read …]` + 结果；metadata `routed_from_bash/routed_tool`；
  审计 `tool.routed`（真实命中率）。
- **UI（决策 5）**：`gui/src/lib/toolActivity/` 活动展示"使用的工具"处显示
  `Bash → Read`；其余位置零标注。
- 开关：`permissions/workspace_policy.py` 增 `bash_routing: "auto"|"off"`（默认 off）。

### Phase 2 —— 渐进强制 v2（触发场景：L2 报错与用户强制指令拉锯）

**触发场景（真实会话观察到，routing=off 时）**：用户在指令里显式要求"必须用某 Bash
命令"（如 `dir`），模型忠于用户反复用不同写法重发；L2 只报「Use … instead」而不执行，
模型在「命中→报错」与「绕过探测（`cd … && dir`、`cmd /c dir`）→执行」之间来回试探，
形成报错循环。修正后 `dir/ls` 已**不在**路由/拦截范围（§3.1），该循环对 `dir` 不再出现；
但 routing=off 下 `cat`/`rg` 等仍可能拉锯，Phase 2 主要针对这些。

**渐进强制 v2 规则**（同会话、同命令形状，按命中次数递进；**已实现**，默认 0=关）：
- 阈值 `bash_escalate`：0=关闭（保持 Phase 1 行为）；≥N 时同形状重复命中达到 N 次后
  **放行 bash 执行并返回结果**——检测到模型/用户铁了心要用 Bash 语义，就不该继续打架，
  避免死循环拉锯。
- **仅作用于 L2/报错路径**（`bash_routing=off`）：透明路由（auto）已给数据、无循环，不适用。

**会话计数状态**：per-session + per-shape（registry 生命周期内 `self._bash_repeats`，
key=`tier|tool_name|主参数`）。**设置**：`.xeyo-policy.json` 的 `bash_escalate`（int），
上限/推荐常量 `BASH_ESCALATE_MAX=5` / `BASH_ESCALATE_RECOMMENDED=3`；后端
`GET/POST /v1/workspace/policy-bash` 读写并返回推荐/上限/最小值；GUI 控件
`gui/src/components/BashRoutingSetting.tsx`（独立组件，推荐 3 / 上限 5 / 0=关）。

## 5. 测试清单

- 解析：T1/T2 各形状 → tier/tool_name/tool_input；复合/不可映射/`ls/dir/find` → None；
  `redirect_hint` 文案回归（逐字节不变）。
- P0 registry：`cat` → 行为仍为 L2 错误提示（未路由）+ 审计含 `tool.routed_observed`
  (tier=T1)；`echo hi` → 无观测事件、正常执行。
- P1 追加（实施时）：路由命中返回内容+note；**区外路径不路由（bash 直行，无 DENY 往返）**；
  区内但目标工具 DENY 回退；read_state 一致性（路由后 Read "file unchanged" 缓存仍生效）；
  worker 路由；`bash_routing=off` 不路由。
- 契测红线：`tests/test_catalog.py` 描述长度（<200）、`test_audit_log.py` 事件集不受干扰。

## 6. 风险与回退

- 语义差异（T2 ignore 清单、T3 Glob 摘要格式）→ 以观测数据决定 T3；T2 差异方向
  是"更符合项目视角"，需接受。
- **成员前置依赖 `cwd`+`allowed_paths` 一致**：会话 allowed_paths 为空/变化时按 cwd
  兜底；前置只是避免"已知 DENY"，真正的路径狱裁决仍由目标工具兜底（不回退则报错）。
- 区外误用（`dir C:\…\.dsh\…` 这类）**不路由**，属诚实的"低收益不干预"——习惯仍
  靠描述层与 v2 渐进强制。
- 模型"被路由惯了"学不会 → v2 渐进强制兜底（决策 2）。
- 回退：`bash_routing=off` 即回旧行为；P1 可整体 revert 到 P0（仅去掉路由调用，
  审计保留）。
