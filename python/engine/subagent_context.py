"""子 Agent 短上下文构建（A3 前缀稳定 + A4 工具白名单 + 近期变更注入）。

设计（多 Agent 协同落地 #29 §2.3 / 附录 A C2/C6）：
- **稳定前缀（A3/#4）**：`[Fix System][工具 schema]` 严格连续、置于最前 —— 保证多个子 agent
  命中同一段 provider 前缀缓存。
- 任务与近期变更由 subagent_input_contract 放在独立输入消息中；system 只含稳定前缀。
  dynamic_tail 保留为旧路径的兼容字段。
- **工具白名单（A4/C2）**：按 `required_tools` 裁剪；`FORBIDDEN_SUB_TOOLS`（如 `_agent`）永不下发。
- 近期变更注入：写前让子 agent 知道"这块刚被谁改过"（解决"瞎"）。

本模块不管 L1/MEMORY.md 索引的实际加载（那由调用方注入 base_prefix），只**保证顺序不变量**。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from tools.meta import FORBIDDEN_SUB_TOOLS

# 再导出：与 tools.meta / scheduler 同源（勿再手抄 _agent）。
# 历史别名：旧白名单偶发写 `_agent`，与 Agent 同禁。
_FORBIDDEN_ALIASES = frozenset({"_agent"})


@dataclass
class SubagentContext:
    """组装好的子 agent 上下文。"""
    system_prompt: str
    base_prefix: str          # 稳定前缀（跨子 agent 应字节一致）
    dynamic_tail: str         # 旧路径的动态尾部；输入契约路径不将其拼入 system
    tool_names: list[str]     # 白名单工具名（A4/C2，已剔除禁止项）


def build_subagent_context(
    *,
    base_prefix: str,
    task_prompt: str,
    recent_changes: str = "",
    tool_whitelist: Iterable[str] = (),
) -> SubagentContext:
    """组装子 agent 上下文。

    输入契约路径的 system 与 base_prefix 相等；任务与环境事实由独立消息承载。
    A4/A8 兜底：工具白名单剔除 `FORBIDDEN_SUB_TOOLS`（如 Agent/Memory），绝不下发。
    （Phase 2：Bash/Git 可在白名单；Bash 另受工人策略沙箱约束。）
    """
    banned = FORBIDDEN_SUB_TOOLS | _FORBIDDEN_ALIASES
    allowed = sorted(n for n in tool_whitelist if n not in banned)
    dynamic_tail = task_prompt
    if recent_changes:
        # 近期变更作为"写前提醒"拼在任务前（仍是尾部，不插进 base_prefix）
        dynamic_tail = f"{recent_changes}\n\n{task_prompt}"
    system_prompt = f"{base_prefix}\n\n{dynamic_tail}".rstrip()
    from msgtypes.input_contract import enabled
    if enabled():
        system_prompt = base_prefix
    return SubagentContext(
        system_prompt=system_prompt,
        base_prefix=base_prefix,
        dynamic_tail=dynamic_tail,
        tool_names=allowed,
    )


__all__ = ["SubagentContext", "build_subagent_context"]
