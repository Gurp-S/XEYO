# 多 Agent P0/P1/文件工人 点验清单

> 产品路径：主循环 `engine.submit` + `Agent` 工具。旧 batch `_multi_agent_stream` **已删除**。
> 自动化：`python -m pytest tests/test_multi_agent_p0.py tests/test_multi_agent_hard_gate.py tests/test_multi_agent_stream_flush.py tests/test_multi_agent_p1_toolpath.py tests/test_file_worker_hardening.py -q`

## 启动前

- [ ] 后端已重启（文件工人门禁 + 只读预算）
- [ ] 工作区可写；模型可用

## P0 点验（手工）

| # | 场景 | 期望 |
|---|---|---|
| 1 | Chip **关**，问简单问题 | 正常回答；仍可自愿调 Agent |
| 2 | Chip **开**，「测多 agent：建一个临时文件」 | 主模型调 Agent → 卡片 → **最终回答围绕建文件**，不聊 Memory 索引 |
| 3 | 「测试串行」三步依赖 | `Delegated` → 卡1 → … → `Delegated/Failed` → 卡2 → …（不整坨堆在最后） |
| 4 | 「测试 3 个 agent 并发」 | 连续多条 Delegating，卡片成组挂在末条后；墙钟应接近「最慢那个」而非三者之和 |
| 5 | 子 agent 失败（权限/超时） | 主回复说明失败并回应原任务，不改题到 Memory |

## 文件工人门禁（手工）

| # | 场景 | 期望 |
|---|---|---|
| F1 | Agent **不填 scope** 做总结 | 卡片 **只读**；工具表无 Write/Edit；试图写文件被拒 |
| F2 | Agent `scope=["."]` | 降级 **只读**（`scope_too_broad`），非全仓可写 |
| F3 | Agent `scope=["某子目录"]` 改文件 | 卡片 **可写**；写冲突时 reason 含 conflict / unexpectedly modified |
| F4 | 工人写路径 | **无 ASK 弹窗**（scope 内自动放行；危险路径 DENY） |

## 省钱 / 轮次（手工）

| # | 场景 | 期望 |
|---|---|---|
| C1 | 只读双文件总结（同回合两次 Agent） | 倾向并行；勿串行「派一个等一个」 |
| C2 | 观察只读工人 | 默认 ≤4 模型轮；system 无整份 XEYO.md / Memory index |
| C3 | `python scripts/multi_agent_gate_report.py --json` | 有 `agent_tool_*`、`agent_tool_read_only_ends`、`agent_tool_avg_turns_used` |

## P1 点验（手工）

| # | 场景 | 期望 |
|---|---|---|
| 6 | Chip 开 + 「分别总结 a.md 与 b.md」 | 倾向同回合两次 Agent；软提示含「优先 spawn」 |
| 7 | 观察子 agent 用量/侧链 | system 不应再带整份 XEYO.md；无 Memory index 尾插 |

## Phase 2（已落地 — Bash 策略沙箱 + 默认 Git）

- [x] 工人白名单含 `Bash` + `Git`（`SUBSET_TOOL_BASELINE`）
- [x] 工人 Bash：仅 `bash_readonly_allow` → ALLOW；其余 **DENY**（无 ASK）；远程工人一律 DENY
- [x] 工人 Bash 默认 timeout 30s / 上限 60s（`XEYO_WORKER_BASH_TIMEOUT_MS`）；禁后台
- [x] 主会话 Bash 合同不变（只读放行 / 其余 ASK，见 Doc 34）
- [x] 仍禁：Memory、嵌套 Agent、外发；不做 OS 容器

验收：

```bash
cd python
python -m pytest tests/test_file_worker_hardening.py tests/test_sandbox_hardening.py tests/test_catalog.py tests/test_agent_tool.py -q
```

## 回归命令

```bash
cd python
python -m pytest tests/test_multi_agent_p0.py tests/test_multi_agent_hard_gate.py tests/test_multi_agent_stream_flush.py tests/test_multi_agent_p1_toolpath.py tests/test_file_worker_hardening.py tests/test_catalog.py tests/test_agent_tool.py -q
```

## 已删除 / 已瘦身 / 已加固

- `server/routers/chat.py` → 旧 `_multi_agent_stream` / `_tasks_from_raw` **已删除**
- 前端 `InlineAgentChips` 已删除（由 `AgentDoneBars` 承接）
- 空 `scope` → 工具表剔除全部 `write_path`；卡片 **只读** / **可写**
- 过宽 scope（`.` / 仓根）→ 降级只读
- 子 Agent 无 WriteStore → 拒写盘；工人写路径无 ASK
- 只读工人默认 max_turns/tool_calling=4；可写=8
- 子 agent：`include_context_blocks=False` + `include_memory_index=False`
- 同轮多 Agent：`is_concurrency_safe` + `partition_tool_calls`
- Phase 2：工人 Git 默认开；Bash 只读策略沙箱（同批）
