"""记忆系统开关：持久化到 ``.xeyo/settings.json`` 的 ``memory`` 段，并桥接到 ``os.environ``。

运行时的各开关（``memory/l5_flag`` / ``engine/aging`` / ``memory/runtime``）都是读
``os.environ``。本模块提供统一入口：

* ``MEMORY_SWITCHES``：记忆系统开关注册表（key / 说明 / 合法值 / 未设默认），
  取值域对齐 ``cli.feature_registry`` 的口径。
* ``current(cwd)``：生效值 = ``settings.memory`` 覆盖 > 环境变量 > 默认（方向安全）。
* ``apply_to_environ(cwd)``：把 ``settings.memory`` 中明确指定的键写进 ``os.environ``
  （服务器启动 + 每次切换时调用，使运行时读到新值）。settings 未指定的键不动环境，
  于是用户手动 ``set XEYO_*=...`` 仍然可用。
* ``save(updates, cwd)``：写工作区级（cwd 给定时）或 home 级 settings.json 的
  ``memory`` 段（原子写，复用 extension.config 的 keep-last-good 原子机制）。

设计上让「GUI 设置」成为权威来源，但又不抹掉手动 env：
- settings.memory 里有的键 → 以它为准（写进 os.environ）。
- settings.memory 里没有的键 → 环境变量或代码默认仍然生效。
"""

from __future__ import annotations

import os
from typing import Any

from extension import config as _cfg

# (key, 中文说明, 合法取值, 未设默认)
MEMORY_SWITCHES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
	("XEYO_L5", "L5 模式：project=默认链(不跑每轮 decide)；v61=实验通道(每轮 decide)", ("project", "v61"), "project"),
	("XEYO_C2_LLM_SUMMARY", "C2 摘要 LLM 旁路：压缩摘要改由模型生成（强保真要点列表，多一次模型调用；实测吸收潜力高但输出不稳定，默认关=确定性摘要）", ("0", "1"), "0"),
	("XEYO_TOOL_AGING", "工具结果老化：压缩后冻结区仍可按窗口紧追推进（默认关）", ("0", "1"), "0"),
	# ---- 固化（2026-09-06 用户决策 "v61 默认开启"）→ 删除的 7 个开关 ----
	# XEYO_C2_GATE（project 专用闸；v61 下 decide 自主，无读取意义）
	# XEYO_V61_PARETO / XEYO_V61_SI / XEYO_V61_DYNAMIC_R（B1/B2/B3 证据门未过，恒关）
	# XEYO_C2_PRESSURE_FORMULA / XEYO_C2_GAIN_FORMULA / XEYO_C2_EXTEND_FORMULA
	# （Path A 公式只服务 project 模式；v61 下 decide 接管 C2 触发。改为 _c2_formula_enabled 恒 True）
	# ---- 已固化开启（收益明确，不再是开关；只能改源码回退）----
	# 第一批：A4 sqlite 签名缓存 / A1 ω 冷却平滑 / ⑮ 检索重排偏好（原
	# XEYO_MEMORY_SQLITE_INDEX / XEYO_CACHE_COOLDOWN_OMEGA / XEYO_MEMORY_RERANK_PREFERENCE）。
	# 第二批：F4 query_reweight / C2 引用锚点 / C2 逃生舱 / A2 碎片还原 / A5 差分重写
	# （原 XEYO_MEMORY_QUERY_REWEIGHT / XEYO_C2_CITATION / XEYO_C2_ESCAPE_HATCH /
	# XEYO_MEMORY_RESTORE / XEYO_SESSION_MD_DELTA）。
	# 各固化行为所在：search.query_reweight_enabled / runtime._c2_citation_enabled /
	# runtime._c2_escape_hatch_enabled / runtime._restore_enabled（=memindex.restore_enabled）/
	# session_md.deltas_enabled —— 均恒 True。旧 settings 残留值被忽略。
	# ---- Memory 索引常驻注入（实验通道，默认关）----
	# 事故 sess_mtiche8l（glm-4.5-air 把索引条目当任务对象）后生产恒关（query_loop
	# 传 include_memory_index=False）。本键是受控重开通道：注入仍走 project_for_model
	# 的 _append_memory_index（受索引上限与 D1 模糊指代静默约束）。默认关：
	# 须 A1（200+ 轮 live）+ A3 过门证据后再开。
	("XEYO_MEMORY_INDEX_LIVE", "Memory 索引常驻注入：把 MEMORY.md 一行索引随投影注入（约 0.7k tok/上限 25KB；用户决策默认开）", ("0", "1"), "1"),
)

_ALLOWED = {k: v for (k, _, v, _) in MEMORY_SWITCHES}
_LABELS = {k: v for (k, v, _, _) in MEMORY_SWITCHES}
_DEFAULTS = {k: v for (k, _, _, v) in MEMORY_SWITCHES}


def _memory_store(cwd: str | None) -> dict[str, Any]:
	"""合并 home + workspace（更具体优先）两处 settings.json 的 memory 段。"""
	home = _cfg._read_json(_cfg.home_settings_path())
	ws = _cfg._read_json(_cfg.workspace_settings_path(cwd)) if cwd else {}
	merged = dict(home.get("memory") or {})
	merged.update(ws.get("memory") or {})
	return merged


def _coerce(key: str, raw: Any) -> str | None:
	"""把原始值归一化为合法值；非法返回 None（让调用方回退默认）。"""
	allowed = _ALLOWED.get(key) or ()
	if raw is None:
		return None
	s = str(raw).strip()
	if not allowed:
		return s
	# 合法值/枚举直通（如 project/v61）；0/1 开关的合法值也在此命中。
	if s in allowed:
		return s
	# 布尔/真假归一化：真值走第一个非默认项（"1" 或 "v61"）
	truthy = s.lower() in ("1", "true", "on", "yes", "enabled", "enable")
	# 对 C2_GATE/TOOL_AGING/LLM_SUMMARY/CITATION 这类 0/1 开关：
	if set(allowed) == {"0", "1"}:
		return "1" if truthy and s not in ("off", "false", "no") else "0"
	return None


def _resolve_cwd(cwd: str | None) -> str | None:
	"""运行时无显式 cwd 时，用服务器管理的 XEYO_CWD（非记忆开关）解析工作区设置。"""
	if cwd:
		return cwd
	return os.environ.get("XEYO_CWD", "").strip() or None


def get_value(key: str, cwd: str | None = None) -> str:
	"""记忆开关生效值：**settings.memory（GUI 设置）为唯一权威** > 默认。

	- **环境变量一律不再参与**（包括合法非空值）——彻底杜绝「忘删 / 不知名位置
	  残留的环境变量」影响运行时开关。
	- 离线 gate-test / eval 如需切换模式，改为写入 settings.json memory 段
	  （``memory_switches.save``），运行时经 ``XEYO_HOME``/``XEYO_CWD`` 解析同一处。
	- 与 :func:`current` 口径一致，避免「运行时读 env、显示读 settings」不一致。
	"""
	if key not in _DEFAULTS:
		return ""
	store = _memory_store(_resolve_cwd(cwd))
	if key in store:
		coerced = _coerce(key, store[key])
		if coerced is not None:
			return coerced
		return _DEFAULTS[key]
	return _DEFAULTS[key]


def current(cwd: str | None = None) -> dict[str, Any]:
	"""返回每个开关的生效值（settings.memory > 默认；环境变量不再参与）。"""
	store = _memory_store(_resolve_cwd(cwd))
	out: dict[str, Any] = {}
	for key, label, allowed, default in MEMORY_SWITCHES:
		val: Any = store.get(key)
		coerced = _coerce(key, val) if val is not None else None
		if coerced is None:
			coerced = default
		out[key] = {
			"key": key,
			"label": label,
			"value": coerced,
			"allowed": list(allowed),
			"source": "settings" if (key in store) else "default",
			"default": default,
		}
	return out


def apply_to_environ(cwd: str | None = None) -> dict[str, str]:
	"""把 settings.memory 中明确指定的键写进 os.environ（settings 权威）。

	只写 settings.memory 里实际出现的键；未出现的键保留用户手动 env / 默认，
	避免覆盖用户在 .bat / shell 里显式设置的值。
	"""
	store = _memory_store(cwd)
	applied: dict[str, str] = {}
	for key, label, allowed, default in MEMORY_SWITCHES:
		if key not in store:
			continue
		val = _coerce(key, store[key]) or default
		os.environ[key] = val
		applied[key] = val
	return applied


def save(updates: dict[str, str | bool], cwd: str | None = None) -> dict[str, Any]:
	"""写 work 级（cwd 非空）或 home 级 settings.json 的 memory 段；返回合并后的 memory dict。

	与 extension.config 的 set_* 一致：``workspace_settings_path(cwd)`` 原子写。
	"""
	target = _cfg.workspace_settings_path(cwd) if cwd else _cfg.home_settings_path()
	data = _cfg._read_json(target)  # noqa: SLF001
	mem = dict(data.get("memory") or {})
	for key, val in updates.items():
		if key not in _DEFAULTS:
			# 未知/已删键（如已固化开启的 A4/ω/⑮）一律拒绝，防 GUI/脚本误写回惰性残留。
			raise ValueError(f"未知记忆开关 {key!r}（已删除或不存在）")
		raw = str(val).strip().lower() if not isinstance(val, bool) else ("1" if val else "0")
		coerced = _coerce(key, raw)
		if coerced is None:
			raise ValueError(f"memory switch {key} 非法取值 {val!r}，允许 {_ALLOWED.get(key)}")
		mem[key] = coerced
	data["memory"] = mem
	_cfg.write_settings(target, data)  # noqa: SLF001
	return data["memory"]
