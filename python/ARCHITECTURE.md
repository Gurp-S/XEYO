# Python 后端代码地图

> 新人第一小时：先读本文，再按「推荐阅读顺序」进源码。

## 请求主路径（GUI / cli-ts 用这个）

```
POST /v1/chat/completions
  server/routers/chat.py          ← HTTP/SSE 入口（宜变薄，逻辑外提）
    → server/session_pool.py      ← SessionPool：引擎实例、busy 租约
      → engine/query_engine.py    ← QueryEngine：submit_message、工具注册
        → engine/query_loop.py    ← 主循环：模型 ↔ 工具多轮
          → tools/*               ← 工具实现
          → permissions/policy.py ← allow / ask / deny
          → prompt/assembler.py   ← system + T_now 投影
          → memory/runtime.py     ← 上下文 C0/C1/C2 投影
```

## 模块职责

| 目录 | 职责 |
|------|------|
| `server/` | FastAPI 应用、routers、SessionPool |
| `engine/` | QueryEngine、query_loop、scheduler、turn/subagent runner |
| `memory/` | 记忆投影、journal、compact；`simulator/` 为离线标定 |
| `prompt/` | system 左段 + `pre_llm_inject.py`（T_now 易变块） |
| `permissions/` | 工具权限三态；`policy.py` 是核心 |
| `rewind/` | 回溯 v2（`service.py`）与 v3 热路径（`hotpath.py`） |
| `session/` | MessageStore、transcript JSONL、CWD |
| `slash/` | `registry.py`（SSOT）→ `export_manifest` → TS；`dispatch.py` 服务端命令 |
| `tools/` | 每工具 `*_tool.py` + `meta.py` 登记 |
| `channels/` | 微信 filehelper / ilink（可选远程通道） |
| `cli/` | Typer：`serve`、`chat`、attach、config |
| `extension/` | 插件 / skill / MCP（默认关） |
| `bridge/` | **已废弃** — 见下方 |

## 不要从这里开始

| 路径 | 说明 |
|------|------|
| `bridge/http.py` | 遗留 stdlib HTTP 桥；**请用 `python -m server`** |
| `evals/` | 基准脚本，非运行时 |
| `scripts/memory_stack_eval.py` | 研究/压测脚本 |

## 斜杠命令

1. 改表：`slash/registry.py`
2. 生成 TS：`py -3.11 -m slash.export_manifest`（CI 跑 `--check`）
3. 服务端执行：`slash/dispatch.py`

## 回溯：读哪条？

| 版本 | 代码 | 状态 |
|------|------|------|
| **v3 热路径** | `rewind/hotpath.py` + `server/routers/rewind.py` | **现行默认** |
| v2 预览/执行 | `rewind/service.py` + sessions rollback API | 兼容/迁移中 |

设计文档：`docs/设计/31-回溯v3对齐Cursor热路径.md`

## 配置

- 环境变量：分散在 60+ 文件（`XEYO_*`）；模板见仓库根 `.env.example`
- 用户 CLI 配置：`~/.xeyo/config.toml`（`cli/config_store.py`）
- 工作区扩展：`<workspace>/.xeyo/settings.json`

## 推荐阅读顺序

1. `msgtypes/events.py` — 事件词汇表
2. `engine/query_engine.py` — 类 docstring + `submit_message` 签名
3. `engine/query_loop.py` — 只看 yield 的 Event 类型与阶段注释
4. `permissions/policy.py` — `PolicyDecision` + `evaluate_policy` 开头
5. `prompt/pre_llm_inject.py` — T_now 块列表（对照 `AGENTS.md`）

## 测试

```powershell
cd python
py -3.11 -m pytest -q --timeout=60 -m "not live"
```
