"""T10 权限 preset：readonly / workspace-write / full 命名 bundle。

- preset = permission_mode + 只读门禁的组合语义（见 policy.session_permission_profile）。
- **会话创建时 pin**（SessionPool 首建写入，之后请求不得改写）→ 切换 preset 只影响新会话。
- 单向收紧红线不变：readonly 收紧到只读白名单；full 只放宽「确认频率」，
  不触碰 deny 黑名单 / 密钥 / `.git/.xeyo/.agents` 硬保护 / worker 沙箱。
"""

from __future__ import annotations

PERMISSION_PRESETS = frozenset({"readonly", "workspace-write", "full"})
DEFAULT_PRESET = "workspace-write"


def normalize_preset(value: object) -> str:
	"""归一化 preset 名；未知/缺省回退 workspace-write（现状行为）。"""
	v = str(value or "").strip().lower().replace("_", "-")
	return v if v in PERMISSION_PRESETS else DEFAULT_PRESET
