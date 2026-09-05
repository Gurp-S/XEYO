"""会话内启停 reconcile（P0b F2.5）：push 为主 + digest 幂等。

- **push**：``set_mcp_enabled``/``set_skill_enabled``（settings.json 原子写）后
  直接发布单轮 T_now 活页块（``# 工具面变更`` / ``# 技能目录变更``）；
- **pull 兜底**：另一进程/CLI 改 settings → 本进程下次执行时由
  ``enabled_probe``（mtime 缓存重读）即时生效（DENY 门）；manager 配置重载
  检出外部变化也会经 ``publish_if_changed`` 补发一次活页块；
- **幂等**：同值重复 set 不发布（digest 未变）；同块文本去重。

不变量：活页块永不回写 MessageStore / JSONL（T_now copy-on-write 投影）；
会话内启停**永不触碰**已冻结的 ``schemas()``（原生面重塑只在下会话）。
"""

from __future__ import annotations

import hashlib
import json
import threading

_LOCK = threading.Lock()
_PENDING: list[str] = []
#: 每类变更最近一次发布的 digest（kind → digest）——发布幂等依据。
_LAST_DIGESTS: dict[str, str] = {}


def reconcile_digest(state: dict) -> str:
	"""状态聚合 digest（键排序紧凑 JSON 的 sha256 前 16 hex）。"""
	try:
		canon = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	except Exception:  # noqa: BLE001 — 不可序列化退化为 repr
		canon = repr(state)
	return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def publish_if_changed(kind: str, state: dict, build_block) -> bool:
	"""digest 变化才发布（幂等）；返回是否真的发布了一块。"""
	d = reconcile_digest(state)
	with _LOCK:
		if _LAST_DIGESTS.get(kind) == d:
			return False
		_LAST_DIGESTS[kind] = d
	block = build_block()
	if block:
		publish_reconcile_block(block)
		return True
	return False


def publish_reconcile_block(block: str) -> None:
	"""push 通道：把一块活页挂进待消费队列（去重，保序）。"""
	text = (block or "").strip()
	if not text:
		return
	with _LOCK:
		if text not in _PENDING:
			_PENDING.append(text)


def consume_reconcile_blocks() -> list[str]:
	"""T_now 注入点：取走全部待挂活页块（单轮有效，消费即清）。"""
	with _LOCK:
		blocks = list(_PENDING)
		_PENDING.clear()
	return blocks


def reset_reconcile_state() -> None:
	"""测试隔离。"""
	with _LOCK:
		_PENDING.clear()
		_LAST_DIGESTS.clear()


def build_mcp_block(enabled: bool, scope_label: str) -> str:
	"""工具面变更活页块（带归属头，防弱模型当用户新提问）。"""
	kind = "启用" if enabled else "停用"
	return (
		"# 工具面变更（background only — 非用户新提问）\n"
		f"- 用户{kind}了 {scope_label}；调用侧即时生效"
		+ ("，原生工具目录下个会话重塑。" if enabled else "（调用将被拒绝），原生工具目录下个会话重塑。")
	)


def build_skill_block(enabled: bool, name: str) -> str:
	"""技能目录变更活页块。"""
	mark = "+" if enabled else "−"
	return (
		"# 技能目录变更（background only — 非用户新提问）\n"
		f"- {mark}{name}（加载侧即时校验；下个会话重塑原生目录）"
	)
