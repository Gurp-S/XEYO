"""隔离的 WSC active 投影适配器。

本模块是行为实验用的 sidecar，不改变默认生产链。它只负责把已经通过
``synaptic.project`` 生成的 WSC 热层和未压缩尾部组成为 API 消息；生产
``query_loop`` 未接入本模块前，导入它不会改变任何会话行为。

硬边界：

* WSC 失败、收益门拒绝、视图/工具配对不完整时回退 C0/C1；
* 只有投影完整成功时才提交新的 ``AssemblyState`` 与 ``ColdStore``；
* 句柄统一使用生产 ``Read`` 形态，视图落在读取工作区的 ``.xeyo_offload``；
* 调用方显式携带 state/cold，避免用进程全局状态掩盖跨轮错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os


_ENV_ACTIVE = "XEYO_WSC_ACTIVE"


def enabled() -> bool:
	"""实验 active 档开关；默认关闭，且不读取影子档的 ``XEYO_WSC``。"""
	import os

	return os.environ.get(_ENV_ACTIVE, "").strip().lower() in ("1", "true", "on", "yes")


@dataclass(frozen=True)
class ActiveProjection:
	"""一次隔离投影的结果和可提交的跨轮状态。"""

	messages: list[dict[str, Any]]
	used_wsc: bool
	fallback_reason: str = ""
	cut: int = 0
	view_path: str = ""
	view_ref: str = ""
	projection: Any = None
	state: Any = None
	cold: Any = None


def _view_path(cwd: str | Path | None, session: str) -> Path:
	from memory.offload import _offload_root

	base = _offload_root(cwd)
	safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in session)
	return base / "wsc-active" / f"{safe[:80] or 'session'}.txt"


def _trial_view_path(view: Path) -> Path:
	"""返回不影响已发布 Read 句柄的试算视图路径。"""
	return view.with_name(view.name + ".trial")


def _discard_trial_view(path: Path) -> None:
	try:
		path.unlink()
	except FileNotFoundError:
		pass


def _clone_cold(cold: Any) -> Any:
	if cold is None:
		return None
	from synaptic.coldstore import ColdStore

	return ColdStore.from_json(cold.to_json())


def _baseline(messages: list[dict[str, Any]], cwd: str | Path | None) -> list[dict[str, Any]]:
	from engine.compact import project as c0c1

	return c0c1(list(messages), cwd=cwd)


def _tool_ids(message: dict[str, Any]) -> tuple[set[str], set[str]]:
	uses: set[str] = set()
	results: set[str] = set()
	content = message.get("content")
	if not isinstance(content, list):
		return uses, results
	for block in content:
		if not isinstance(block, dict):
			continue
		if block.get("type") == "tool_use" and block.get("id"):
			uses.add(str(block["id"]))
		elif block.get("type") == "tool_result" and block.get("tool_use_id"):
			results.add(str(block["tool_use_id"]))
	return uses, results


def _pairs_are_valid(messages: list[dict[str, Any]]) -> bool:
	"""验证发送序列没有把 assistant/tool 关系切坏。"""
	pending: set[str] = set()
	for message in messages:
		uses, results = _tool_ids(message)
		if message.get("role") == "tool":
			results.update(
				str(message["tool_call_id"])
				for _ in (0,)
				if message.get("tool_call_id")
			)
		if not results.issubset(pending):
			return False
		pending.difference_update(results)
		pending.update(uses)
	return not pending


def project_messages(
	messages: list[dict[str, Any]],
	*,
	session: str,
	cwd: str | Path | None = None,
	state: Any = None,
	cold: Any = None,
	params: Any = None,
) -> ActiveProjection:
	"""生成一次 WSC active 发送序列；异常只影响本次，确定性回退 C0/C1。

	``state`` 和 ``cold`` 是调用方上一次成功结果中的同一对对象。失败路径
	永远不提交试算期间的副作用，防止一次坏投影污染后续回合。
	"""
	base = _baseline(messages, cwd)
	try:
		from memory.runtime import c2_cut_index
		from memory.offload import ref_path_for
		from synaptic.project import project
		from synaptic.types import WscParams

		cut = int(c2_cut_index(messages, None))
		if cut <= 1 or cut >= len(messages):
			return ActiveProjection(base, False, "no_compressible_region", cut=cut)

		pset = params or WscParams(
			mode="closure", fold_cadence="econ", handle_style="read"
		).for_level("Medium+")
		if getattr(pset, "handle_style", "") != "read":
			from dataclasses import replace

			pset = replace(pset, handle_style="read")
		view = _view_path(cwd, session)
		ref = ref_path_for(view, cwd)
		trial_view = _trial_view_path(view)
		_discard_trial_view(trial_view)
		# 试算用副本；只有所有硬校验通过后才把 state/cold 交给调用方。
		trial_state = state.clone() if state is not None and hasattr(state, "clone") else state
		trial_cold = _clone_cold(cold)
		projection = project(
			list(messages),
			region_end=cut,
			params=pset,
			prev=trial_state,
			cold=trial_cold,
			session=session,
			view_path=trial_view,
			view_ref=ref,
		)
		if not projection.result.compressed:
			_discard_trial_view(trial_view)
			return ActiveProjection(base, False, "wsc_gain_gate", cut=cut)
		if not projection.view_path or not trial_view.is_file():
			_discard_trial_view(trial_view)
			return ActiveProjection(base, False, "missing_read_view", cut=cut)
		if "expand(" in projection.text:
			_discard_trial_view(trial_view)
			return ActiveProjection(base, False, "unexpected_expand_handle", cut=cut)

		from engine.compact import project as c0c1

		tail = c0c1(list(messages[cut:]), cwd=cwd)
		candidate = [
			{"role": "assistant", "content": projection.text, "name": "wsc_snapshot"},
			*tail,
		]
		if not _pairs_are_valid(candidate):
			_discard_trial_view(trial_view)
			return ActiveProjection(base, False, "broken_tool_pair", cut=cut)
		# 试算期间正式视图保持不动；通过全部校验后再发布同一份已验证字节。
		view.parent.mkdir(parents=True, exist_ok=True)
		os.replace(trial_view, view)
		projection.view_path = str(view)
		return ActiveProjection(
			candidate,
			True,
			cut=cut,
			view_path=str(view),
			view_ref=str(ref),
			projection=projection,
			state=projection.state,
			cold=projection.cold,
		)
	except Exception as exc:  # noqa: BLE001 - experiment adapter is fail-open
		if "trial_view" in locals():
			_discard_trial_view(trial_view)
		return ActiveProjection(
			base,
			False,
			f"{type(exc).__name__}:{exc}",
			cut=0,
		)


__all__ = ["ActiveProjection", "enabled", "project_messages"]
