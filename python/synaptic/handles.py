"""句柄渲染与解析（**唯一实现**）：模型侧取回形态 = `Read`。

## 为什么单收一层

句柄在热层里出现在 **8 处**（骨架行 / 剪枝卡 / 合并卡组 / `[REQUESTS]` 四种形态 …），
而**把句柄读回来的解析器**（`budget.rendered_request_nodes` 的覆盖审计、
`tests/wsc` 的渲染↔绑定同源断言）与它们必须同源：**渲染形态一改而解析器没跟，
覆盖率会静默归零**——审计报「用户原话全丢」而实际没丢，正是本项目反复踩过的形态
（docs §13.1 的 `parse_reqs_payload` 缺陷、§11.9 的分子分母异源）。

⇒ 渲染与解析都收在本模块，别处只许调 `expression()` / `extract()` / `span()`。

## 两种形态

| style | 渲染 | 用于 |
|---|---|---|
| `expand`（默认） | ``expand(node://12)`` | 离线回放 / 不写取回视图的场景（行为与历史逐字节一致） |
| `read`（生产形态） | ``Read(file_path='…', offset=5, limit=3)`` | 冷层取回视图的行区间（2026-09-16 用户裁定：只保留 `Read` 一个取回接口） |

**回落规则（不许渲染出坏引用）**：`read` 档下若某句柄没有可用区间，**该句柄回落 `expand`**，
绝不渲染一个指向不存在区间的 `Read` 调用——坏引用比没有引用更糟（模型会照着它去调、拿回错误）。

## 多节点句柄（卡组 / 区间句柄）

`branch://B1,B2`、`reqs://5-120`、`node://1,2,3` 覆盖**多个**节点，而视图是按节点逐块排布的
⇒ 渲染成**跨该组首末节点的连续区间**：``offset = 首个成员的首行``、``limit`` 覆盖到``最末成员的末行``。

口径后果如实记：跨度**可能包含组外的节点文本**（它们也在视图里，是真实历史，不是噪声）。
这是刻意的取舍——宁可多给真实历史，也不给一个取不回的窄区间；
`Read` 自身的 25k token / 2000 行上限会在跨度过大时明确报错，模型据此收窄。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from synaptic.coldstore import node_handle

#: 旧形态：`expand(<handle>)`。
_EXPAND_RE = re.compile(r"expand\(([^)\s]+)\)")
#: 新形态：`Read(file_path='<path>', offset=<int>, limit=<int>)`（空格容错）。
_READ_RE = re.compile(
	r"Read\(file_path='(?P<path>[^']*)'\s*,\s*offset=(?P<offset>\d+)\s*,\s*limit=(?P<limit>\d+)\)"
)


@dataclass(frozen=True)
class HandleRenderer:
	"""句柄 ↔ 热层文本的唯一转换点。

	- `node_ranges`：``node://<idx> -> (首行, 末行)``（来自 `ColdStore.write_text_view`）
	- `handle_nodes`：``句柄 -> 节点 idx 元组``（来自 `ColdStore.handles`，用于多节点句柄求跨度）
	"""

	style: str = "expand"
	path: str = ""
	node_ranges: Mapping[str, tuple[int, int]] = field(default_factory=dict)
	handle_nodes: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
	#: 一个投影内 ranges/handles 都是定稿快照；同一句柄可能被多处渲染/解析，缓存不改变语义。
	_span_cache: dict[str, tuple[int, int] | None] = field(default_factory=dict, init=False, repr=False, compare=False)
	_reverse_cache: dict[tuple[str, int, int], str] | None = field(default=None, init=False, repr=False, compare=False)

	# -- 渲染 ---------------------------------------------------------------
	def span(self, handle: str) -> tuple[int, int] | None:
		"""句柄在取回视图里的 ``(首行, 末行)``；不可得返回 ``None``（调用方回落）。

		**多节点句柄要求全部成员都有区间**，缺一个就返回 ``None``（回落 `expand`）。
		只按「有区间的那些成员」求跨度，会渲染出一个**只覆盖部分成员**的 `Read` 调用：
		行里写着「用户[3]」而取回只给 1 条 —— 是**静默的部分丢失**，而且它在
		往返比对里看不出来（引用自洽地窄）；这正是本项目反复踩的形态 ⇒ 宁缺勿假。
		"""
		if handle in self._span_cache:
			return self._span_cache[handle]
		members = tuple(self.handle_nodes.get(handle) or ())
		if not members:
			# 未知句柄：单节点句柄直接查（`handle_nodes` 不全时仍可能命中）
			out = self.node_ranges.get(handle)
			self._span_cache[handle] = out
			return out
		pts = [self.node_ranges.get(node_handle(i)) for i in members]
		if any(p is None for p in pts):
			self._span_cache[handle] = None
			return None
		out = (
			min(p[0] for p in pts if p),
			max(p[1] for p in pts if p),
		)
		self._span_cache[handle] = out
		return out

	def can_render_read(self, handle: str) -> bool:
		return self.style == "read" and bool(self.path) and self.span(handle) is not None

	def expression(self, handle: str) -> str:
		"""渲染一个句柄。`read` 档下缺区间时**回落 `expand`**（见模块文档的回落规则）。"""
		if self.can_render_read(handle):
			start, end = self.span(handle) or (0, 0)
			return (
				f"Read(file_path='{self.path}', offset={start}, "
				f"limit={max(1, end - start + 1)})"
			)
		return f"expand({handle})"

	# -- 解析（与渲染同源）--------------------------------------------------
	def extract(self, text: str) -> tuple[str, ...]:
		"""从**已渲染文本**里读回句柄列表（渲染的逆运算）。

		两种形态都要认：`read` 档下不是每个句柄都能渲染成 `Read`（缺区间的回落成 `expand`），
		所以解析必须同时扫两种——只认一种就会漏掉回落的那批（覆盖率静默变低）。
		"""
		out: list[str] = []
		for m in _EXPAND_RE.finditer(text):
			out.append(m.group(1))
		rev = self._reverse_index()
		for m in _READ_RE.finditer(text):
			key = (m.group("path"), int(m.group("offset")), int(m.group("limit")))
			hit = rev.get(key)
			if hit:
				out.append(hit)
		return tuple(dict.fromkeys(out))

	def extract_nodes(self, text: str) -> frozenset[int]:
		"""从已渲染文本里读回**节点 idx 集合**（覆盖审计用）。

		区间句柄按整段展开是安全的，理由见 `budget.rendered_request_nodes` 的 docstring：
		调用方始终与本区域用户节点求交，混进的非用户节点会被滤掉。
		"""
		out: set[int] = set()
		for handle in self.extract(text):
			kind, _sep, payload = handle.partition("://")
			if kind == "node":
				for part in payload.split(","):
					part = part.strip()
					if part.isdigit():
						out.add(int(part))
			elif kind == "reqs":
				from synaptic.coldstore import parse_reqs_payload

				span = parse_reqs_payload(payload)
				if span is not None:
					out.update(range(span[0], span[1] + 1))
		return frozenset(out)

	def _reverse_index(self) -> dict[tuple[str, int, int], str]:
		"""``(path, offset, limit) -> 句柄``：让 `Read` 形态也能被解析回来。

		按**区间精确匹配**优先；同一区间被多个句柄覆盖时取字典序最小者（确定性）。
		"""
		if self._reverse_cache is not None:
			return self._reverse_cache
		if not self.path:
			return {}
		rev: dict[tuple[str, int, int], str] = {}
		for handle in sorted(set(self.handle_nodes) | set(self.node_ranges)):
			rng = self.span(handle)
			if rng is None:
				continue
			key = (self.path, rng[0], max(1, rng[1] - rng[0] + 1))
			rev.setdefault(key, handle)
		object.__setattr__(self, "_reverse_cache", rev)
		return rev


#: 不写取回视图时的默认渲染器（= 历史行为 `expand(<handle>)`）。
DEFAULT_RENDERER = HandleRenderer()

#: 未指定渲染器时的取值（供各处 `handles or DEFAULT_RENDERER` 用）。
def renderer_or_default(handles: Any) -> HandleRenderer:
	return handles if isinstance(handles, HandleRenderer) else DEFAULT_RENDERER
