"""L5 热路径开关：是否每轮跑 v6.1 decide。

``XEYO_L5``（settings.memory 权威，GUI 面板可切）：
  - ``v61``（默认，2026-09-06 用户决策）：每轮 decide（记忆压缩决策引擎自主）
  - ``project``（回退）：C0+C1 快路径，不跑 decide（超长会话 C2 走 Path A 公式，
    已固化恒 True——见 ``runtime._c2_formula_enabled``）

``XEYO_C2_GATE``：**已固化删除**（2026-09-06）——v61 默认开启后冗余（v61 下 decide
自主；project 回退用 Path A 公式，无需总闸）。旧 settings 残留值被忽略。
"""

from __future__ import annotations

ENV_KEY = "XEYO_L5"
# 上线默认 v61（2026-09-06 用户决策）；project 作快路径回退。
DEFAULT_MODE = "v61"


def l5_mode() -> str:
	"""返回当前 L5 模式：v61 或 project。

	以 ``memory_switches.get_value`` 解析（GUI settings.memory 权威；空/非法残留
	环境变量一律忽略落默认），不再直接读 os.environ，避免忘删的残留变量误切 v61。
	"""
	from memory.memory_switches import get_value

	raw = get_value(ENV_KEY).strip().lower()
	if raw in ("project", "off", "0", "false", "c0c1"):
		return "project"
	if raw == "v61":
		return "v61"
	return DEFAULT_MODE


def use_v61() -> bool:
	"""是否在热路径每轮调用 v6.1 decide。"""
	return l5_mode() == "v61"


def c2_gate() -> bool:
	"""project 模式超长会话 C2 是否允许：**恒 True**（2026-09-06 固化）。

	原为注册表开关（XEYO_C2_GATE，默认开）；v61 默认开启后冗余删除。
	project 回退下 Path A 公式（_c2_formula_enabled 恒 True）裁决 C2，
	无需总闸。读点仅兼容旧调用；恒 True。
	"""
	return True
