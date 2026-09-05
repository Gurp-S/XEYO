"""T14 子代理角色文件：`<workspace>/agents/*.toml`。

每个文件一个角色：

    # agents/reviewer.toml
    name = "reviewer"                      # 必填，agent_type 取值
    description = "只读代码评审"            # spawn 卡片/目录展示
    nickname = "评审员"                     # 可选，卡片友好名
    developer_instructions = "..."         # 可选，注入子代理 system 尾部

加载规则（fail-closed，坏文件跳过并 debug 日志，不挂启动）：
- name 缺失/重复 → 跳过该文件；
- 仅字符串字段生效；目录不存在 → 空表。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class AgentRole:
    name: str
    description: str = ""
    nickname: str = ""
    developer_instructions: str = ""
    source: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.nickname or self.name


def load_agent_roles(workspace_root: str | Path) -> dict[str, AgentRole]:
    """读 `<root>/agents/*.toml`；返回 name → role（稳定按文件名排序）。"""
    root = Path(workspace_root) / "agents"
    out: dict[str, AgentRole] = {}
    if not root.is_dir():
        return out
    try:
        import tomllib
    except Exception:  # pragma: no cover - py<3.11
        return out
    for path in sorted(root.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _log.debug("bad agent role file skipped: %s", path, exc_info=True)
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or "").strip()
        if not name or name in out:
            _log.debug("agent role skipped (missing/duplicate name): %s", path)
            continue
        try:
            out[name] = AgentRole(
                name=name,
                description=str(data.get("description") or "").strip(),
                nickname=str(data.get("nickname") or "").strip(),
                developer_instructions=str(
                    data.get("developer_instructions") or ""
                ).strip(),
                source=str(path),
                extra={
                    k: v
                    for k, v in data.items()
                    if k
                    not in ("name", "description", "nickname", "developer_instructions")
                },
            )
        except Exception:  # noqa: BLE001
            _log.debug("agent role build failed: %s", path, exc_info=True)
    return out


def role_developer_suffix(role: AgentRole | None) -> str:
    """把角色注入子代理 system 尾部的文本段（无角色/无指令 → 空串）。"""
    if role is None:
        return ""
    lines = [f"# Role: {role.display}"]
    if role.description:
        lines.append(role.description)
    if role.developer_instructions:
        lines.append(role.developer_instructions)
    return "\n".join(lines)
