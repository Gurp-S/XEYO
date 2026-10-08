"""执行起点台账：按 ``call_id`` 记录「这一次调用确实进入了执行」。

**结构性根因**（本模块存在的唯一理由）：进程中断后 transcript 里只剩一个没有 result 的
``tool_use``，恢复层此前只能说「可能已执行」（``TOOL_OUTCOME_UNKNOWN``）——因为**执行起点
没有留下任何可归因记录**。在执行层入口写一条最小记录，"这一次是否开始过"就从猜测变成事实。

铁律对齐（XEYO 引擎设计理念）：
- **引擎自己完成、不给模型看**：本模块从不产生模型可见文本。模型可见文本由
  ``session/hydrate.py`` 组装，且只取**正向证据**——有开始记录才说"已进入执行"；
  没记录什么都不说（开关关着时"无记录"是机制没开造成的空事实，报出去就是假信息）。
- **fail-open**：写不进就不写、读不到就当没有，任何异常一律吞掉，绝不拖垮执行或恢复。
- **限制只在执行层**：本模块只写事实，无劝导/建议/评价文本。

开关：``XEYO_CALL_TRACE=0`` 关闭（默认开）。
落盘：``<usage_dir>/call_trace/<session_id>.jsonl``；单会话上限 ``_MAX_LINES`` 行，
超限重写保留尾部 ``_KEEP_LINES`` 行——被裁掉的旧记录只会让结论**回落到"无证据"**，
不会伪造出错误证据。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

#: 关闭取值（其余一切取值都算开）。
_OFF = {"0", "off", "false", "no", "disable", "disabled"}

_MAX_LINES = 400
_KEEP_LINES = 200
_MAX_BYTES = 64_000
_SUBDIR = "call_trace"


def enabled() -> bool:
	"""执行起点台账是否开启（``XEYO_CALL_TRACE=0`` 关闭）。"""
	return os.environ.get("XEYO_CALL_TRACE", "").strip().lower() not in _OFF


def _session_key(session_id: str) -> str:
	"""会话 id → 安全文件名（会话 id 来自运行时，不保证是文件名友好字符）。"""
	key = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(session_id or ""))[:80].strip("._-")
	return key or "unknown"


def trace_path(session_id: str) -> Path | None:
	"""台账文件路径；取不到落盘根时返回 None（fail-open）。"""
	try:
		from usage.ledger import usage_dir

		return Path(usage_dir()) / _SUBDIR / f"{_session_key(session_id)}.jsonl"
	except Exception:  # noqa: BLE001
		return None


def record_start(session_id: str, call_id: str, tool_name: str) -> bool:
	"""执行起点落一条记录。返回是否真的写成功（调用方不必据此做任何决策）。"""
	if not enabled() or not session_id or not call_id:
		return False
	path = trace_path(session_id)
	if path is None:
		return False
	try:
		path.parent.mkdir(parents=True, exist_ok=True)
		line = json.dumps(
			{"uid": str(call_id), "name": str(tool_name or ""), "ts": round(time.time(), 3)},
			ensure_ascii=False,
		)
		with path.open("a", encoding="utf-8") as fh:
			fh.write(line + "\n")
		_trim(path)
		return True
	except Exception:  # noqa: BLE001 — 归因台账 fail-open
		return False


def _trim(path: Path) -> None:
	"""超限后保留尾部（便宜、确定性：只在够大时才读回来）。"""
	try:
		if path.stat().st_size < _MAX_BYTES:
			return
		lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
		if len(lines) <= _MAX_LINES:
			return
		path.write_text("\n".join(lines[-_KEEP_LINES:]) + "\n", encoding="utf-8")
	except Exception:  # noqa: BLE001
		return


def started(session_id: str, call_id: str) -> dict | None:
	"""有正向记录 ⇒ 返回该条记录；否则 ``None``。

	``None`` 的语义严格是「**没有证据**」，不是「未开始」——调用方不得把 None 报成否定结论。
	"""
	if not enabled() or not session_id or not call_id:
		return None
	path = trace_path(session_id)
	if path is None:
		return None
	try:
		if not path.exists():
			return None
		lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_MAX_LINES:]
	except Exception:  # noqa: BLE001
		return None
	for raw in reversed(lines):
		try:
			row = json.loads(raw)
		except Exception:  # noqa: BLE001
			continue
		if isinstance(row, dict) and str(row.get("uid") or "") == str(call_id) and not row.get("phase"):
			return row
	return None
