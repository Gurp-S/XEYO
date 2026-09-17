"""冷层存储与 ``expand`` 句柄（热记忆稀疏，冷记忆无损）。

每个剪枝卡 / 被结论化的节点都对应一个句柄；句柄解析回**原始节点文本**，
逐字节与历史一致。这让「可恢复信息保留」不靠自述，而靠往返比对证明。
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BRANCH_PREFIX = "branch://"
NODE_PREFIX = "node://"
HEAD_PREFIX = "head://"
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


def head_handle(text: str) -> str:
	"""为一份已经发出的热层快照生成稳定句柄。

	头快照不是节点，不能伪装成 ``node://``；内容寻址也让跨轮携带冷层时
	重复绑定变成幂等操作。
	"""
	digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:20]
	return f"{HEAD_PREFIX}{digest}"


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
	if s.startswith(HEAD_PREFIX):
		return "head", s[len(HEAD_PREFIX) :]
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
	# 已发出热层的快照句柄 -> 原始热层文本（换头时只追加这个句柄，不改旧前缀）
	snapshots: dict[str, str] = field(default_factory=dict)
	# 取回视图的持久块序；新节点/快照只能追加到末尾，不能插入旧 Read 区间之前。
	view_blocks: list[tuple[str, str]] = field(default_factory=list)

	def put_nodes(self, nodes: list[tuple[int, str, dict[str, Any]]]) -> None:
		for idx, text, info in nodes:
			if idx not in self.texts:
				self.texts[idx] = text
				self.view_blocks.append(("node", str(idx)))
			self.meta.setdefault(idx, info)

	def bind(self, handle: str, nodes: tuple[int, ...]) -> None:
		self.handles[handle] = tuple(nodes)

	def put_snapshot(self, handle: str, text: str) -> None:
		handle = str(handle)
		if handle not in self.snapshots:
			self.snapshots[handle] = str(text)
			self.view_blocks.append(("head", handle))

	def expand(self, handle: str) -> tuple[str, ...]:
		"""按句柄拉回原始文本；未知句柄抛 KeyError（不静默降级）。"""
		if handle in self.snapshots:
			return (self.snapshots[handle],)
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
			"snapshots": {k: v for k, v in sorted(self.snapshots.items())},
			"view_blocks": [list(block) for block in self.view_blocks],
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
		for k, v in (raw.get("snapshots") or {}).items():
			cs.snapshots[str(k)] = str(v)
		for block in raw.get("view_blocks") or ():
			if isinstance(block, (list, tuple)) and len(block) == 2:
				cs.view_blocks.append((str(block[0]), str(block[1])))
		# 兼容旧冷层：旧格式没有块序，按旧实现的首次插入序补齐一次。
		for idx in cs.texts:
			if ("node", str(idx)) not in cs.view_blocks:
				cs.view_blocks.append(("node", str(idx)))
		for handle in cs.snapshots:
			if ("head", handle) not in cs.view_blocks:
				cs.view_blocks.append(("head", handle))
		return cs

	def write(self, path: Path) -> int:
		"""gzip 落盘，返回写入的字节数（**权威副本**，供审计与往返比对）。"""
		path.parent.mkdir(parents=True, exist_ok=True)
		blob = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True).encode("utf-8")
		with gzip.open(path, "wb") as fh:
			fh.write(blob)
		return path.stat().st_size

	# -- 取回视图（WSC 冷层的标准接口 = `Read`）-------------------------------
	def write_text_view(self, path: Path) -> dict[str, tuple[int, int]]:
		"""写**纯文本、按行可寻址**的取回视图，返回 ``句柄 -> (首行, 末行)``。

		## 为什么是这份视图，为什么用 `Read`

		2026-09-16 用户裁定：**`expand` / `offload` / `Read` 是同一个能力，只保留 `Read`**
		（专用工具 `offload_read` 已删除）。冷层的权威副本是 gzip+JSON，模型读不了 ⇒
		必须额外产出这份纯文本视图，模型才能用**已有的** `Read` 把内容取回。
		这也与 `tools/spill.py` 同策（溢出落盘 + 告诉模型 Read 这个路径）。

		## 行号约定

		文件形态：每个节点两段——一行 ``#node <idx>`` 索引头，随后是该节点原文的若干行。

		```
		#node 12          <- 索引头（**不在**区间内，纯粹给人/审计看）
		第一行原文          <- offset
		第二行原文          <- offset+limit-1
		#node 13
		...
		```

		换算：``Read(file_path=P, offset=S, limit=K)`` ≡ 视图第 ``S`` 行起 ``K`` 行。
		原文以 ``\\n`` 结尾时 `split("\\n")` 会多出一个空元素——它**照样计入一行**，
		否则区间会少一行、取回少一个换行符（有测试锁这个边界）。

		## 三份产物、三条契约（**别混**，混了就会写出「永远为假」的断言）

		| 产物 | 格式 | 契约 |
		|---|---|---|
		| `write()` 的 gzip+JSON | 权威副本 | **逐字节**等于历史原文（可恢复性 `lossless_rate` 挂这条） |
		| `write_text_view()` 的纯文本 | 取回视图 | **逐字节**等于原文的 **LF 归一化**形态 |
		| 模型经 `Read` 取回 | 视图切片 | **内容无损**，但每行带 ``cat -n`` 前缀（`tools/fileio/text.py:129` 的 ``     1→``） |

		两条口径各自的成因，都必须写清楚：
		1. **CRLF 折 LF**：`Read` 用 ``Path.read_text()``，**默认通用换行归一化**——工具既有语义，
		   冷层绕不过 ⇒ 视图侧先归一化，让「写入的行」与「读回的行」同口径；
		2. **行号前缀**：`Read` 给模型的内容一律走 `add_line_numbers`
		   （`tools/file_read_tool/file_read_tool.py:635`）⇒ **「逐字节」不能挂在「模型取回」这一环**，
		   只能挂在权威副本与视图上。行号是**寻址元数据**，不是内容丢失：
		   去掉前缀后每行逐字节等于原文（有测试机械地剥前缀比对）。
		"""
		lines: list[str] = []
		ranges: dict[str, tuple[int, int]] = {}
		# ⚠️ **按写入顺序（插入序）排块，不许按节点 idx 排序**（2026-09-16 实测修正）。
		#
		# 头是 append-only 的日志（`assemble` 的规则 8）：第 3 轮写下的
		# `Read(offset=46, limit=1)` 到第 9 轮**仍在头里**，模型随时可能照抄它。
		# 若这里按 idx 排序，而后续某轮把**更小的 idx** 判成被剪节点，新块会插在
		# 前面 ⇒ 其后所有块的行号整体平移 ⇒ **头里那批老引用静默指向别的节点**。
		# 实测（`_wsc_out/_stale_ref_probe.py`，synth 40 轮、句柄 `read`、冷层跨轮传递）：
		# 按 idx 排序时 1047 条引用样本里 **115 条含义漂移**；改成插入序后为 0。
		#
		# 插入序的确定性不由排序保证，而由**调用序列**保证：同一个会话按同一顺序
		# `put_nodes` ⇒ 同一份视图（`put_nodes` 用 `setdefault`，重复 idx 不移动位置）。
		# 块按持久插入序写出：每一轮的新块都在末尾，已有节点/头快照的
		# offset/limit 因而稳定。不要按 idx 或字典分类重排。
		known = set(self.view_blocks)
		for idx in self.texts:
			if ("node", str(idx)) not in known:
				self.view_blocks.append(("node", str(idx)))
		for handle in self.snapshots:
			if ("head", handle) not in known:
				self.view_blocks.append(("head", handle))
		for kind, key in self.view_blocks:
			if kind == "node":
				idx = int(key)
				if idx not in self.texts:
					continue
				text = self.texts[idx]
				label = f"#node {idx}"
				handle = node_handle(idx)
			else:
				if key not in self.snapshots:
					continue
				text = self.snapshots[key]
				label = f"#head {key}"
				handle = key
			# LF 归一化（见上方契约 1）：CRLF/CR 折成 LF 后再切行。
			norm = str(text).replace("\r\n", "\n").replace("\r", "\n")
			body = norm.split("\n")
			lines.append(label)
			start = len(lines) + 1  # 1 起：下一行就是正文首行
			lines.extend(body)
			end = start + len(body) - 1
			ranges[handle] = (start, end)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text("\n".join(lines) + "\n", encoding="utf-8")
		return ranges

	def read_ref(self, handle: str, ranges: dict[str, tuple[int, int]], path: Path) -> str:
		"""把一个句柄渲染成**模型可直接照抄调用**的取回引用（`Read` 口径）。

		形态与 `memory/offload.py` 的引用同源（都是 ``Read(file_path='…', offset=…, limit=…)``）：
		模型只需要认识**一种**按需取回形态。未知句柄返回空串（调用方据此退回原形态）。
		"""
		rng = ranges.get(handle)
		if not rng:
			return ""
		start, end = rng
		return f"Read(file_path='{path}', offset={start}, limit={end - start + 1})"

	#: 旧名兼容（`offload_read` 时代的方法名；调用方请用 `read_ref`）。
	offload_ref = read_ref

	@classmethod
	def read(cls, path: Path) -> "ColdStore":
		with gzip.open(path, "rb") as fh:
			raw = json.loads(fh.read().decode("utf-8"))
		return cls.from_json(raw if isinstance(raw, dict) else {})

	@property
	def size_tokens(self) -> int:
		return (sum(len(t) for t in self.texts.values()) + sum(len(t) for t in self.snapshots.values())) // 4
