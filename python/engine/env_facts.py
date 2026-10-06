"""环境事实一次性探测（供 T_now ``env_facts`` 块 / ``world_state`` 段使用）。

为什么要有这个模块：模型可见的"我在这台机器上处于什么执行环境"此前只有一处——
``tools/bash_tool`` 在**会话首个成功结果**里印一行 ``[shell: pwsh 7.6.6]``
（``bash_tool.py:906-918``）。时序错了：模型在第一次调用 Bash **之前**无从得知
shell 语义、能否提权、时区基准、哪棵目录可写，于是先按 bash 语义写命令再撞墙
（实测：单轮刷出 127KB 重复错误；向 ``%TEMP%`` 写草稿撞 ``path_denied``——两类
各白烧一整轮）。事实本身引擎早就算得出来（``tools/bash_tool/runner`` 的
``shell_display_name``、``permissions/write_scope`` 的写 scope 门），只是从没进过
注意力。

边界纪律（对齐 AGENTS.md 理念与 WSC 常设准则）：
- **只给信息**：产出只有 ``key: value`` 事实，不含建议/劝导/评价/收尾提示；
- **一次交付**：调用方按 ``dedup=True`` 登记（见 ``prompt/pre_llm_inject.py`` 的
  ``env_facts`` 行）⇒ 值不变不重发，不是每边界计费；左段（前缀）零改动；
- **绝不写盘**：``writable`` 只用权限口径 + ``os.access`` 判，不做写入探测；
- **fail-open**：单项探测失败 ⇒ 该项**不出现**（宁缺勿假），绝不抛、不阻断主循环；
- **口径同源**：可写面走 ``permissions.write_scope``（与 WriteStore 同一道门）、
  shell 走 ``tools/bash_tool.runner``（与执行层同一来源）——不另立第二份口径；
- **有界**：整段与单项都有字符上限，超长路径截断。

不做什么：不读 ``PATH`` 猜"能力清单"（那是 ``engine/runtime_capabilities`` 的预检
口径，其 docstring 明确"不进入模型 prompt"）；不探测网络；不枚举显示器数量。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from typing import Any, Callable

#: 整段字符上限（防超长路径 / 异常时区名撑爆块体积）
_MAX_TEXT_CHARS = 400
#: 单项值上限
_MAX_VALUE_CHARS = 120
#: 工作区内草稿目录（相对路径：省注意力字节，写路径自动建父目录，见
#: ``engine/write_store.py`` 的 ``path.parent.mkdir(parents=True, exist_ok=True)``）。
#: 必须落在 workspace root 内——root 外一律 ``path_denied``（实测 ``%TEMP%`` 就是这么被拒的）。
SCRATCH_REL = ".xeyo/tmp"

_FACTS_CACHE: dict[str, dict[str, str]] = {}


def _clip(value: Any) -> str:
	"""单项截断：超长只截断不报错（路径长度不可控）。"""
	text = str(value)
	if len(text) <= _MAX_VALUE_CHARS:
		return text
	return text[: _MAX_VALUE_CHARS - 1] + "…"


def _fmt(value: Any) -> str:
	"""布尔按机器可读小写渲染（``elevated: false`` 是有信息量的值，不能吞）。"""
	if isinstance(value, bool):
		return "true" if value else "false"
	return _clip(value)


def probe_shell() -> str:
	"""执行层 shell 身份：与 Bash 工具结果头同一来源（不另立口径）。"""
	from tools.bash_tool.runner import shell_display_name

	return shell_display_name()


def probe_elevated() -> bool:
	"""当前进程是否提权：Windows 查进程令牌，POSIX 查 euid。"""
	if os.name == "nt":
		import ctypes

		return bool(ctypes.windll.shell32.IsUserAnAdmin())
	return os.geteuid() == 0


def probe_tz() -> str:
	"""本地时区偏移 + 名称：把 UTC 日志/时间戳换成本地时刻的基准。"""
	now = time.localtime()
	offset = time.strftime("%z", now)
	index = 1 if (time.daylight and now.tm_isdst > 0) else 0
	name = str(time.tzname[index] or "") if time.tzname else ""
	return f"{offset} {name}".strip()


def probe_writable(cwd: str) -> str:
	"""可写根事实（不写盘）：复用写路径自己那道门 + ``os.access`` 判权限。

	口径 = ``engine/write_store.WriteStore._canon``：路径必须落在 workspace root 内
	（root 外一律 ``path_denied``，实测 Write 到 ``%TEMP%`` 就是这么被拒的），并且过
	子 Agent 写 scope 门。**故意复用同一道门而不是自己写一份判断**——本模块存在的
	意义就是不报假信息：宁可不说，也不报一棵模型其实写不进去的树。
	"""
	try:
		from engine.write_store import WriteStore

		store = WriteStore(cwd)
	except Exception:  # noqa: BLE001 — 口径不可用 ⇒ 不报可写面
		return ""
	out: list[str] = []
	for cand in (cwd, tempfile.gettempdir()):
		path = str(cand or "").strip()
		if not path or not os.path.isdir(path):
			continue
		try:
			if not os.access(path, os.W_OK | os.X_OK):
				continue
			store._canon(path)  # noqa: SLF001 — 唯一口径来源：与写路径同一道门
		except Exception:  # noqa: BLE001 — 单棵树判不了就跳过，不影响其余
			continue
		if path not in out:
			out.append(path)
	return ", ".join(out)


def probe_desktop() -> bool:
	"""是否有可用桌面（截图/托盘一类能力的前提）。NT 恒真；POSIX 看 DISPLAY。"""
	if os.name == "nt":
		return True
	return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


#: 无参探针登记表（登名字而非函数对象：测试可注入单项失败，验证 fail-open 粒度）
_PROBES: tuple[tuple[str, str], ...] = (
	("shell", "probe_shell"),
	("elevated", "probe_elevated"),
	("tz", "probe_tz"),
	("desktop", "probe_desktop"),
)


def collect(cwd: str = "") -> dict[str, str]:
	"""逐项 fail-open 采集：失败的项**不出现**，绝不抛。"""
	root = str(cwd or "").strip()
	facts: dict[str, str] = {}
	for key, probe_name in _PROBES:
		probe = globals().get(probe_name)
		if not callable(probe):
			continue
		try:
			value = probe()
		except Exception:  # noqa: BLE001 — 单项失败 ⇒ 该项缺席
			continue
		if value is None or value == "":
			continue
		facts[key] = _fmt(value)
	try:
		writable = probe_writable(root)
	except Exception:  # noqa: BLE001
		writable = ""
	if writable:
		facts["writable"] = _clip(writable)
		# 草稿目录只在工作区确实可写时报（否则报了也是假信息）
		facts["scratch"] = SCRATCH_REL
	return facts


def facts(cwd: str = "") -> dict[str, str]:
	"""按 cwd 缓存的采集结果（环境事实在一个进程/会话内稳定）。"""
	key = str(cwd or "").strip()
	cached = _FACTS_CACHE.get(key)
	if cached is None:
		cached = collect(key)
		_FACTS_CACHE[key] = cached
	return cached


def render(cwd: str = "") -> str:
	"""块正文：一行事实（压到最小体积——本块按边界常驻，省的是每轮真金白银）。

	``desktop`` 只在**偏离默认**时出现（有桌面是常态，报 true 只是噪声）。
	无任何事实 ⇒ 空串（该块缺席，调用方不注入）。
	"""
	values = facts(cwd)
	order = ("shell", "elevated", "tz", "writable", "scratch", "desktop")
	parts = [f"{key}: {values[key]}" for key in order if key in values]
	if "desktop" in values and values["desktop"] == "true":
		parts = [p for p in parts if not p.startswith("desktop:")]
	if not parts:
		return ""
	return " | ".join(parts)[:_MAX_TEXT_CHARS]


def facts_id(cwd: str = "") -> str:
	"""稳定身份（trace / 归因用）：不含时间字段，值不变则 id 不变。"""
	payload = json.dumps(
		facts(cwd), ensure_ascii=False, sort_keys=True, separators=(",", ":")
	)
	return "env:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


__all__ = ["collect", "facts", "facts_id", "render"]
