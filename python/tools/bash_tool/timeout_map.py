"""命令族 → 默认超时映射（#15：120s 一刀切 → 按命令族分级）。

产品痛点：``bash_tool`` 默认超时对所有命令一刀切 120s（``DEFAULT_TIMEOUT_MS``），
``pip install`` / ``npm ci`` / 编译（make/gcc/cargo）等长命令经常在 120s 被掐断，
用户被迫手动加 timeout 或反复重试。本模块提供**纯查表**的默认超时分级：

- 纯规则、不碰 LLM 判断（符合「硬编码映射不要 LLM 判断」哲学）；
- 只影响**模型未显式传 timeout** 时的默认值；显式 timeout 仍由 clamp 决定；
- worker（子 Agent）模式**不生效**（worker 30s/60s 上限是刻意的花钱护栏，
  不被命令族覆盖——``parse_input`` 侧已排除）；
- env ``XEYO_CMD_TIMEOUT_OVERRIDES`` 可覆盖（JSON：``{"pip": 600000}``）。

收益口径：这是产品体验修复（评测容器里 docker exec 另管超时、评测不疼），
判定基线 = 单元测试锁映射正确性；理论收益 = 免手动 timeout / 免分步重试。
"""

from __future__ import annotations

import json
import os
from typing import Optional

#: 命令族 → 默认超时（毫秒）。覆盖树的原则：具体家族优先于通用大类。
_FAMILY_TIMEOUTS_MS: dict[str, int] = {
	# pip/conda/uv —— 网络安装常 3-5 分钟
	"pip": 300_000,
	"pip3": 300_000,
	"uv": 300_000,
	"pdm": 300_000,
	"poetry": 300_000,
	"conda": 300_000,
	# node 包管理 —— npm ci / 原生编译常超
	"npm": 240_000,
	"npx": 240_000,
	"pnpm": 240_000,
	"yarn": 240_000,
	"bun": 240_000,
	# 系统包管理
	"apt": 300_000,
	"apt-get": 300_000,
	"apk": 300_000,
	"yum": 300_000,
	"dnf": 300_000,
	"brew": 300_000,
	# 编译工具链
	"make": 300_000,
	"cmake": 300_000,
	"ninja": 300_000,
	"gcc": 300_000,
	"g++": 300_000,
	"clang": 300_000,
	"cargo": 420_000,
	"rustc": 300_000,
	"go": 240_000,
	# JVM 构建
	"mvn": 360_000,
	"gradle": 360_000,
	"sbt": 360_000,
	# 数据集/大文件下载、测试
	"wget": 240_000,
	"curl": 180_000,
	"pytest": 300_000,
	"pytest.exe": 300_000,
}

#: 前缀词 → 家族兜底（base 命令查不到时的第二级匹配，如 "python -m pip install …"）。
_PREFIX_FAMILIES: tuple[tuple[str, str], ...] = (
	("-m pip ", "pip"),
	("-m pytest ", "pytest"),
)

_OVERRIDES: Optional[dict[str, int]] = None


def _load_overrides() -> dict[str, int]:
	"""env ``XEYO_CMD_TIMEOUT_OVERRIDES``（JSON 对象）→ 增量覆盖；坏 JSON 忽略。"""
	global _OVERRIDES
	if _OVERRIDES is None:
		raw = os.environ.get("XEYO_CMD_TIMEOUT_OVERRIDES", "").strip()
		parsed: dict[str, int] = {}
		if raw:
			try:
				data = json.loads(raw)
				if isinstance(data, dict):
					for k, v in data.items():
						try:
							parsed[str(k)] = max(1_000, int(v))
						except (TypeError, ValueError):
							continue
			except ValueError:
				parsed = {}
		_OVERRIDES = parsed
	return _OVERRIDES


def base_command_of(command: str) -> str:
	"""取命令行的 base 命令（第一个词，去路径/去 .exe；空命令返回空串）。"""
	cmd = (command or "").strip()
	if not cmd:
		return ""
	tok = cmd.split(maxsplit=1)[0]
	name = tok.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
	return name.lower()


def family_default_ms(command: str) -> int | None:
	"""按命令族返回默认超时；无命中返回 None（回落全局 120s）。

	匹配优先级：env 覆盖 > 精确 base > 前缀家族（``python -m pip`` 形态）。
	"""
	cmd = (command or "").strip()
	if not cmd:
		return None
	base = base_command_of(cmd)
	overrides = _load_overrides()
	if base in overrides:
		return int(overrides[base])
	if base in _FAMILY_TIMEOUTS_MS:
		return int(_FAMILY_TIMEOUTS_MS[base])
	# 前缀兜底：只匹配命令开头（含 "python -m pytest" 等常见形态）
	low = cmd.lower()
	for prefix, family in _PREFIX_FAMILIES:
		if low.startswith(prefix) or (" " + prefix) in low:
			if family in overrides:
				return int(overrides[family])
			return int(_FAMILY_TIMEOUTS_MS.get(family) or 0) or None
	return None
