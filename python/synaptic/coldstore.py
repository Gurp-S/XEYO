"""冷层存储与 ``expand`` 句柄（热记忆稀疏，冷记忆无损）。

每个剪枝卡 / 被结论化的节点都对应一个句柄；句柄解析回**原始节点文本**，
逐字节与历史一致。这让「可恢复信息保留」不靠自述，而靠往返比对证明。
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BRANCH_PREFIX = "branch://"
NODE_PREFIX = "node://"
#: 区间句柄（P1-b）：一个句柄覆盖**一批旧用户节点**。
#:
#: 动机：``[REQUESTS]`` 的固定开销是「每行约 10–15 token」，实测每回合 93 行
#: ⇒ 约 1565 token/回合，是热层里最大的一段。摘录字符数**不是**瓶颈（用户原话普遍短于
#: 80 字符，两档摘录输出逐字相同）。压它只能合并**行**。
#:
#: 形态取 ``reqs://<首>-<末>`` 而不是把上百个下标全列进 ``node://`` 的理由：
#: ① 由首末下标唯一决定 ⇒ 确定性；② 展开仍走 ``handles`` 里绑定的节点列表，
#: 逐字节返回原文 ⇒ 无损可恢复性不变；③ 审计只需解析区间就能判定这些节点有出口。
REQS_PREFIX = "reqs://"


def branch_handle(card_id: str) -> str:
	return f"{BRANCH_PREFIX}{card_id}"


def reqs_handle(first: int, last: int) -> str:
	"""旧用户节点的区间句柄。绑定时必须给出**完整**节点列表（展开不靠区间推断）。"""
	return f"{REQS_PREFIX}{int(first)}-{int(last)}"


def parse_reqs_payload(payload: str) -> tuple[int, int] | None:
	"""``"12-30"`` -> ``(12, 30)``；不合法返回 ``None``（不猜）。"""
	head, sep, tail = str(payload or "").partition("-")
	if not sep or not head.strip().isdigit() or not tail.strip().isdigit():
		return None
	first, last = int(head), int(tail)
	return (first, last) if last >= first else None


def node_handle(idx: int) -> str:
	return f"{NODE_PREFIX}{idx}"


def node_group_handle(indices: tuple[int, ...]) -> str:
	"""一个句柄覆盖多个同文本节点；展开顺序与 indices 一致。"""
	return NODE_PREFIX + ",".join(str(i) for i in indices)


def parse_handle(handle: str) -> tuple[str, str]:
	"""解析句柄 -> (类型, 载荷)。"""
	s = str(handle or "")
	if s.startswith(BRANCH_PREFIX):
		return "branch", s[len(BRANCH_PREFIX) :]
	if s.startswith(REQS_PREFIX):
		return "reqs", s[len(REQS_PREFIX) :]
	if s.startswith(NODE_PREFIX):
		return "node", s[len(NODE_PREFIX) :]
	return "unknown", s


@dataclass
class ColdStore:
	"""会话级冷层：句柄 → 原始节点文本（无损）。"""

	session: str = ""
	# 句柄 -> 节点 idx 列表
	handles: dict[str, tuple[int, ...]] = field(default_factory=dict)
	# 节点 idx -> 原始文本（只存被引用过的，控制体积）
	texts: dict[int, str] = field(default_factory=dict)
	# 节点 idx -> 元信息（审计用）
	meta: dict[int, dict[str, Any]] = field(default_factory=dict)

	def put_nodes(self, nodes: list[tuple[int, str, dict[str, Any]]]) -> None:
		for idx, text, info in nodes:
			self.texts.setdefault(idx, text)
			self.meta.setdefault(idx, info)

	def bind(self, handle: str, nodes: tuple[int, ...]) -> None:
		self.handles[handle] = tuple(nodes)

	def expand(self, handle: str) -> tuple[str, ...]:
		"""按句柄拉回原始文本；未知句柄抛 KeyError（不静默降级）。"""
		if handle not in self.handles:
			raise KeyError(f"unknown cold handle: {handle}")
		out: list[str] = []
		for idx in self.handles[handle]:
			if idx not in self.texts:
				raise KeyError(f"cold node not stored: {idx}")
			out.append(self.texts[idx])
		return tuple(out)

	def expand_loose(self, handle: str) -> tuple[str, ...]:
		"""宽松版：未知句柄返回空（用于遍历统计，不用于正确性断言）。"""
		try:
			return self.expand(handle)
		except KeyError:
			return ()

	# -- 落盘 / 读回 --------------------------------------------------------
	def to_json(self) -> dict[str, Any]:
		return {
			"session": self.session,
			"handles": {k: list(v) for k, v in sorted(self.handles.items())},
			"texts": {str(k): v for k, v in sorted(self.texts.items())},
			"meta": {str(k): v for k, v in sorted(self.meta.items())},
		}

	@classmethod
	def from_json(cls, raw: dict[str, Any]) -> "ColdStore":
		cs = cls(session=str(raw.get("session") or ""))
		for k, v in (raw.get("handles") or {}).items():
			cs.handles[str(k)] = tuple(int(x) for x in v)
		for k, v in (raw.get("texts") or {}).items():
			cs.texts[int(k)] = str(v)
		for k, v in (raw.get("meta") or {}).items():
			cs.meta[int(k)] = v if isinstance(v, dict) else {}
		return cs

	def write(self, path: Path) -> int:
		"""gzip 落盘，返回写入的字节数。"""
		path.parent.mkdir(parents=True, exist_ok=True)
		blob = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True).encode("utf-8")
		with gzip.open(path, "wb") as fh:
			fh.write(blob)
		return path.stat().st_size

	@classmethod
	def read(cls, path: Path) -> "ColdStore":
		with gzip.open(path, "rb") as fh:
			raw = json.loads(fh.read().decode("utf-8"))
		return cls.from_json(raw if isinstance(raw, dict) else {})

	@property
	def size_tokens(self) -> int:
		return sum(len(t) for t in self.texts.values()) // 4
