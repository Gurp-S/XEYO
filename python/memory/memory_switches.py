"""记忆系统开关：持久化到 ``.xeyo/settings.json`` 的 ``memory`` 段，并桥接到 ``os.environ``。

运行时的各开关（``memory/l5_flag`` / ``engine/aging`` / ``memory/runtime``）都是读
``os.environ``。本模块提供统一入口：

* ``MEMORY_SWITCHES``：记忆系统开关注册表
  （key / 说明 / 合法值 / 未设默认 / **是否 GUI 暴露** / **运行时是否读该键**）。
* ``current(cwd)``：生效值 = ``settings.memory`` 覆盖 > 默认（方向安全）。每项额外带
  ``exposed``（是否在 GUI 面板暴露）/ ``ignored``（运行时是否忽略该键）/ ``effective``
  （运行时真值）。**GUI 一律按 ``exposed`` 过滤、按 ``effective`` 显示开关态**——恒关键
  的 ``source`` 报 ``"ignored"`` 而不再报 ``"settings"``，杜绝「显示开、实际关」。
* ``stale_keys`` / ``prune_stale``：已删/未知残留键的只读查询与清理。这些键运行时本就
  不读（``get_value`` 对未注册键返回空），删除无行为影响；留着会让同名键未来复活时
  **静默继承旧值**（无提示、无清理入口）。
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

# (key, 中文说明, 合法取值, 未设默认, GUI 暴露, 运行时读该键)
#
# ``GUI 暴露``：仅产品设置面板可见的开关为 True。测试 / 评测便捷开关置 False——
#   仍可经 ``save`` / settings.json 切换，只是不出现在产品 GUI（它们是测试方便用的，
#   不是产品功能）。
# ``运行时读该键``：该键是否真被运行时读取。False = 已下线 / 恒关占位（authority 面
#   仍保留注册，以免"已裁决键"凭空消失）。GUI 若展示这类键必须按 ``effective`` 显示
#   并标注已忽略，禁止出现「显示开、实际关」。
MEMORY_SWITCHES: tuple[tuple[str, str, tuple[str, ...], str, bool, bool], ...] = (
	# ---- GUI 暴露（当前唯一一项）----
	("XEYO_C2_LLM_SUMMARY", "C2 摘要 LLM 旁路：压缩摘要改由模型生成（强保真要点列表，多一次模型调用；实测吸收潜力高但输出不稳定，默认关=确定性摘要）", ("0", "1"), "0", True, True),
	# ---- 非 GUI 暴露（测试 / 评测便捷开关）----
	("XEYO_L5", "L5 模式：project=默认链(不跑每轮 decide)；v61=实验通道(每轮 decide)", ("project", "v61"), "project", False, True),
	("XEYO_TOOL_AGING", "工具结果老化：压缩后冻结区仍可按窗口紧追推进（默认关）", ("0", "1"), "0", False, True),
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
	# ---- Memory 索引常驻注入（已下线：恒关，2026-09-09 用户裁决维持下线）----
	# 事故 sess_mtiche8l（glm-4.5-air 把索引条目当任务对象）后退役；AGENTS「已下线」
	# 与此对齐。engine/query_loop._memory_index_live_enabled 恒 False（不看本键），
	# 旧 settings 残留值被忽略；受控重开须源码级 + A1（200+ 轮 live）+ A3 过门证据。
	# 本条目仅保留注册占位（authority 面不因下线而少一个已裁决键）；
	# 运行时读该键 = False → ``current()`` 的 effective 恒为默认、source 报 "ignored"。
	("XEYO_MEMORY_INDEX_LIVE", "Memory 索引常驻注入：已下线恒关（2026-09-09 裁决维持下线；事故 sess_mtiche8l 后退役；重开须源码级+A1/A3 证据门）", ("0", "1"), "0", False, False),
)

_ALLOWED = {k: v for (k, _, v, *_) in MEMORY_SWITCHES}
_LABELS = {k: v for (k, v, *_) in MEMORY_SWITCHES}
_DEFAULTS = {k: v for (k, _, _, v, *_) in MEMORY_SWITCHES}
_EXPOSED = {k: e for (k, _, _, _, e, _) in MEMORY_SWITCHES}
_RUNTIME_READS = {k: r for (k, _, _, _, _, r) in MEMORY_SWITCHES}


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


def stale_keys(cwd: str | None = None) -> list[str]:
	"""只读：settings.memory 中不属于注册表（已删 / 未知）的残留键。不写盘。"""
	store = _memory_store(_resolve_cwd(cwd))
	return sorted(k for k in store if k not in _DEFAULTS)


def prune_stale(cwd: str | None = None) -> list[str]:
	"""清理 home + workspace settings.json ``memory`` 段里的残留键，返回被删清单。

	为什么删：这些键**运行时本就不读**（``get_value`` 对未注册键返回空串），留着
	不生效、不报错、无清理入口；一旦同名键将来重新注册，历史残留值会被**静默继承**。
	删除因此是纯收益——不改变任何运行时行为。

	边界：
	- 只在确有残留时写盘（无残留 → 零写入，避免每次启动重写 settings.json）。
	- 只动 ``memory`` 段；``plugins`` / ``skills`` / ``mcp_servers`` / ``hooks`` 不碰。
	- best-effort：写盘失败只跳过该文件，不影响调用方（server 启动不应被阻断）。
	"""
	targets: list[Any] = [_cfg.home_settings_path()]
	ws = _resolve_cwd(cwd)
	if ws:
		targets.append(_cfg.workspace_settings_path(ws))
	removed: list[str] = []
	for path in targets:
		data = _cfg._read_json(path)  # noqa: SLF001
		mem = data.get("memory")
		if not isinstance(mem, dict) or not mem:
			continue
		stale = sorted(k for k in mem if k not in _DEFAULTS)
		if not stale:
			continue
		for k in stale:
			del mem[k]
		if mem:
			data["memory"] = mem
		else:
			data.pop("memory", None)
		try:
			_cfg.write_settings(path, data)  # noqa: SLF001
		except Exception:  # noqa: BLE001 — 清理失败不阻断启动/保存
			continue
		removed.extend(stale)
	return removed


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
	"""返回每个开关的生效值（settings.memory > 默认；环境变量不再参与）。

	每项额外带 ``exposed`` / ``ignored`` / ``effective``：消费者（GUI）一律按
	``exposed`` 过滤、按 ``effective`` 显示开关态。恒关键（``runtime_reads=False``）
	的 ``effective`` 恒为默认、``source`` 报 ``"ignored"``——不再出现「显示开、实际关」。
	"""
	store = _memory_store(_resolve_cwd(cwd))
	out: dict[str, Any] = {}
	for key, label, allowed, default, exposed, runtime_reads in MEMORY_SWITCHES:
		val: Any = store.get(key)
		coerced = _coerce(key, val) if val is not None else None
		if coerced is None:
			coerced = default
		if runtime_reads:
			effective = coerced
			source = "settings" if (key in store) else "default"
		else:
			# 已下线 / 恒关占位键：运行时恒为默认，settings 里的值一律被忽略。
			effective = default
			source = "ignored"
		out[key] = {
			"key": key,
			"label": label,
			"value": coerced,
			"allowed": list(allowed),
			"source": source,
			"default": default,
			"exposed": exposed,
			"ignored": not runtime_reads,
			"effective": effective,
		}
	return out


def apply_to_environ(cwd: str | None = None) -> dict[str, str]:
	"""把 settings.memory 中明确指定的键写进 os.environ（settings 权威）。

	只写 settings.memory 里实际出现的键；未出现的键保留用户手动 env / 默认，
	避免覆盖用户在 .bat / shell 里显式设置的值。
	"""
	store = _memory_store(cwd)
	applied: dict[str, str] = {}
	for key, label, allowed, default, *_rest in MEMORY_SWITCHES:
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
	# 顺带清掉已删/未知残留键：运行时本就不读，留着会被同名键将来复活时静默继承旧值。
	mem = {k: v for k, v in (data.get("memory") or {}).items() if k in _DEFAULTS}
	for key, val in updates.items():
		if key not in _DEFAULTS:
			# 未知/已删键（如已固化开启的 A4/ω/⑮）一律拒绝，防 GUI/脚本误写回惰性残留。
			raise ValueError(f"未知记忆开关 {key!r}（已删除或不存在）")
		raw = str(val).strip().lower() if not isinstance(val, bool) else ("1" if val else "0")
		coerced = _coerce(key, raw)
		if coerced is None:
			raise ValueError(f"memory switch {key} 非法取值 {val!r}，允许 {_ALLOWED.get(key)}")
		mem[key] = coerced
	if mem:
		data["memory"] = mem
	else:
		data.pop("memory", None)
	_cfg.write_settings(target, data)  # noqa: SLF001
	return data.get("memory") or {}
