"""Synthetic scenario matrix: length × tool size × kind × TTL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from memory.simulator.cache_model import CacheState
from memory.simulator.params import Params, load_params
from memory.simulator.state_model import ContextState, Segment, freeze_s0, token_len

DEFAULT_SYSTEM = "You are XEYO, a coding agent.\n"

# Representative sizes in *tokens* (converted to chars via 4 bytes/token ASCII).
TOOL_SIZE_TOKENS = {
	"T1": 400,
	"T2": 2_000,
	"T3": 8_000,
	"T4": 30_000,
	"T5": 60_000,
}

LENGTH_TURNS = {
	"S1": 2,
	"S2": 7,
	"S3": 30,
	"S4": 70,
	"S5": 120,
	"S6": 40,  # fewer turns, huge tools
}

TTL_SECONDS = {
	"T0": 0.0,
	"T1": 60.0,
	"T2": 300.0,
	"T3": 600.0,
	"T4": 1800.0,
	"T5": 3600.0,
	"T6": 7200.0,
	"T7": 20_000.0,
}

HIGH_VALUE_NEEDLE = "测试必须使用真实数据库。"


def _blob(n_tokens: int, tag: str) -> str:
	n_chars = max(0, n_tokens * 4 - len(tag) - 1)
	return tag + "\n" + ("A" * n_chars)


def _msg_user(text: str) -> dict[str, Any]:
	return {"role": "user", "content": text}


def _msg_asst_use(uid: str, name: str, text: str = "") -> dict[str, Any]:
	blocks: list[dict[str, Any]] = []
	if text:
		blocks.append({"type": "text", "text": text})
	blocks.append({"type": "tool_use", "id": uid, "name": name, "input": {"q": uid}})
	return {"role": "assistant", "content": blocks}


def _msg_tool(uid: str, name: str, content: str) -> dict[str, Any]:
	return {
		"role": "user",
		"content": [
			{
				"type": "tool_result",
				"tool_use_id": uid,
				"content": content,
				"is_error": False,
			}
		],
		"name": name,
	}


def _msg_asst_text(text: str) -> dict[str, Any]:
	return {"role": "assistant", "content": text}


def _segments_from_message(msg: dict[str, Any], idx: int, needles: tuple[str, ...]) -> list[Segment]:
	role = str(msg.get("role") or "user")
	content = msg.get("content")
	out: list[Segment] = []
	if isinstance(content, str):
		hv = any(n in content for n in needles)
		out.append(
			Segment(id=f"m{idx}:0", text=content, role=role, kind="text", high_value=hv)
		)
		return out
	if not isinstance(content, list):
		return out
	for j, block in enumerate(content):
		if not isinstance(block, dict):
			continue
		btype = str(block.get("type") or "text")
		if btype == "tool_result":
			text = str(block.get("content") or "")
			uid = str(block.get("tool_use_id") or "")
			name = str(msg.get("name") or "tool")
			hv = any(n in text for n in needles)
			out.append(
				Segment(
					id=f"m{idx}:{j}",
					text=text,
					role=role,
					kind="tool_result",
					tool_use_id=uid,
					tool_name=name,
					high_value=hv,
				)
			)
		elif btype == "tool_use":
			text = str(block.get("name") or "") + str(block.get("input") or "")
			out.append(
				Segment(
					id=f"m{idx}:{j}",
					text=text,
					role=role,
					kind="tool_use",
					tool_use_id=str(block.get("id") or ""),
					tool_name=str(block.get("name") or "tool"),
				)
			)
		else:
			text = str(block.get("text") or block.get("content") or "")
			hv = any(n in text for n in needles)
			out.append(
				Segment(
					id=f"m{idx}:{j}",
					text=text,
					role=role,
					kind="text",
					high_value=hv,
				)
			)
	return out


def state_from_messages(
	messages: list[dict[str, Any]],
	*,
	cursor: int = 0,
	system: str = DEFAULT_SYSTEM,
	high_value_needles: tuple[str, ...] = (),
) -> ContextState:
	needles = high_value_needles
	p_s = (Segment(id="ps", text=system, role="system", kind="text"),)
	p_c_list: list[Segment] = []
	for i, msg in enumerate(messages[:cursor]):
		p_c_list.extend(_segments_from_message(msg, i, needles))
	body = messages[cursor:]
	body_segs: list[list[Segment]] = [
		_segments_from_message(msg, cursor + i, needles) for i, msg in enumerate(body)
	]
	flat_body = [seg for group in body_segs for seg in group]
	if not flat_body:
		m, t_k, t_now = (), (), ()
	elif len(body_segs) == 1:
		m, t_k, t_now = (), (), tuple(body_segs[0])
	else:
		t_now = tuple(body_segs[-1])
		rest_groups = body_segs[:-1]
		if len(rest_groups) > 3:
			m_groups, tk_groups = rest_groups[:-3], rest_groups[-3:]
		else:
			m_groups, tk_groups = [], rest_groups
		m = tuple(seg for g in m_groups for seg in g)
		try:
			from memory.fidelity_segmenter import atoms_enabled
		except Exception:
			atoms_enabled = lambda: False  # noqa: E731
		if atoms_enabled():
			# P1 缺失1：M 段按信息原子切分（Q 按原子而非消息条数计权）
			from memory.simulator.state_model import atomize_m_segments

			m = atomize_m_segments(m, needles=needles)
		t_k = tuple(seg for g in tk_groups for seg in g)
	return freeze_s0(
		ContextState(p_s=p_s, p_c=tuple(p_c_list), m=m, t_k=t_k, t_now=t_now)
	)


@dataclass
class Scenario:
	id: str
	length_class: str
	tool_size_class: str
	kind: str
	ttl_key: str
	ttl_seconds: float
	messages: list[dict[str, Any]]
	remaining_turns: int
	delta_text: str
	notes: str = ""
	endgame: bool = False

	def state(self) -> ContextState:
		needles = (HIGH_VALUE_NEEDLE,) if self.kind == "G" else ()
		return state_from_messages(self.messages, high_value_needles=needles)

	def cache(self, params: Params | None = None) -> CacheState:
		p = params or load_params()
		return CacheState(
			provider=p.provider,
			age_seconds=self.ttl_seconds,
			model=p.model,
			slot=p.price_slot,
			ts=p.default_ts,
		)


def _tool_cycle(i: int, size_tok: int, *, kind: str, repeat: bool = False) -> list[dict[str, Any]]:
	names = ["Read", "Grep", "Bash", "Read"]
	name = names[i % len(names)]
	if repeat:
		name = "Read"
		uid = "repeat_A"
		path = "A.py"
	else:
		uid = f"{name.lower()}_{i}"
		path = f"f{i}.py"
	if kind == "H":
		blob = _blob(size_tok, f"LOG {uid} tmp debug")
	elif kind == "G" and i == 0:
		blob = HIGH_VALUE_NEEDLE + "\n" + _blob(max(40, size_tok // 8), uid)
	else:
		blob = _blob(size_tok, f"{name} {path}")
	user = _msg_user("继续" if i else "开始任务")
	if kind == "G" and i == 0:
		user = _msg_user(HIGH_VALUE_NEEDLE + " 请按这个约束实现。")
	return [
		user,
		_msg_asst_use(uid, name, f"call {name}"),
		_msg_tool(uid, name, blob),
		_msg_asst_text("ok"),
	]


def _build_messages(
	*,
	n_turns: int,
	size_tok: int,
	kind: str,
	special: str | None = None,
) -> list[dict[str, Any]]:
	msgs: list[dict[str, Any]] = []
	if kind == "A":
		for i in range(max(1, n_turns)):
			msgs.append(_msg_user(f"问{i}: 解释一下 compact"))
			msgs.append(_msg_asst_text(f"答{i}: keep/C1/C2 是三种动作。"))
		return msgs
	repeat = kind == "F"
	if special == "50k":
		return _tool_cycle(0, 50_000, kind=kind)
	if special == "100k":
		return _tool_cycle(0, 100_000, kind=kind)
	if special == "5x20k":
		for i in range(5):
			msgs.extend(_tool_cycle(i, 20_000, kind=kind))
		return msgs
	if special == "10x10k":
		for i in range(10):
			msgs.extend(_tool_cycle(i, 10_000, kind=kind))
		return msgs
	n = max(1, n_turns)
	for i in range(n):
		msgs.extend(_tool_cycle(i, size_tok, kind=kind, repeat=repeat))
	return msgs


def remaining_for(length_class: str, endgame: bool) -> int:
	if endgame:
		return 1
	return {
		"S1": 4,
		"S2": 8,
		"S3": 16,
		"S4": 16,
		"S5": 16,
		"S6": 16,
	}.get(length_class, 8)


def iter_scenarios(*, smoke: bool = False) -> Iterator[Scenario]:
	"""Cover every dimension. Full cartesian is sampled, not exploded."""
	kinds = ("A", "B", "C", "D", "E", "F", "G", "H")
	length_turns = dict(LENGTH_TURNS)
	if smoke:
		length_keys = ("S1", "S2", "S3")
		tool_keys = ("T1", "T2")
		ttl_keys = ("T0", "T2")
		kinds = ("A", "B", "D", "F", "G")
		length_turns["S3"] = 8
		length_turns["S4"] = 10
		length_turns["S6"] = 6
	else:
		length_keys = tuple(LENGTH_TURNS)
		tool_keys = tuple(TOOL_SIZE_TOKENS)
		ttl_keys = tuple(TTL_SECONDS)

	# 1) one of each length × a mid tool × kind A/B
	for lk in length_keys:
		tk = "T1" if lk in ("S1", "S2") else "T2"
		if lk == "S6":
			tk = "T4"
		kind = "A" if lk == "S1" else "B" if lk in ("S2", "S3") else "C"
		yield _scenario(lk, tk, kind, "T0", n_turns=length_turns[lk])

	# 2) each tool size on S3/C
	s3_n = length_turns["S3"]
	for tk in tool_keys:
		yield _scenario("S3", tk, "C", "T0", n_turns=s3_n)

	# 3) each kind on S3 (T1 in smoke to keep CI fast)
	kind_tool = "T1" if smoke else "T2"
	for kind in kinds:
		yield _scenario("S3", kind_tool, kind, "T0", n_turns=s3_n)

	# 4) TTL sweep on S2/B
	for ttl in ttl_keys:
		yield _scenario("S2", "T1", "E", ttl)

	# 5) short-chat keep: 1,2,3,5 turns
	for n in (1, 2, 3, 5):
		msgs: list[dict[str, Any]] = []
		for i in range(n):
			msgs.append(_msg_user(f"短问{i}"))
			msgs.append(_msg_asst_text(f"短答{i}"))
		yield Scenario(
			id=f"short:{n}",
			length_class="S1",
			tool_size_class="T1",
			kind="A",
			ttl_key="T0",
			ttl_seconds=0.0,
			messages=msgs,
			remaining_turns=4 if n > 1 else 1,
			delta_text="还有吗\n",
			notes="short_chat",
			endgame=(n == 1),
		)

	# 6) R=1 endgame
	yield _scenario("S2", "T1", "A", "T0", remaining=1, extra_id="endgame")

	# 7) oversized tools
	if not smoke:
		for special, sid in (("50k", "huge50k"), ("100k", "huge100k"), ("5x20k", "huge5x20k"), ("10x10k", "huge10x10k")):
			msgs = _build_messages(n_turns=1, size_tok=1, kind="D", special=special)
			yield Scenario(
				id=sid,
				length_class="S6",
				tool_size_class="T5",
				kind="D",
				ttl_key="T0",
				ttl_seconds=0.0,
				messages=msgs,
				remaining_turns=16,
				delta_text="继续修\n",
				notes=special,
			)

	# 8) empty M
	yield Scenario(
		id="empty_m",
		length_class="S1",
		tool_size_class="T1",
		kind="A",
		ttl_key="T0",
		ttl_seconds=0.0,
		messages=[_msg_user("hi"), _msg_asst_text("hello")],
		remaining_turns=8,
		delta_text="ok\n",
		notes="empty_M",
	)

	# 9) mixed high-text M so C1 can pass Q>=θ (stubs only tools)
	mix: list[dict[str, Any]] = []
	for i in range(10):
		mix.append(_msg_user("需求说明 " + ("细节" * 80) + str(i)))
		mix.append(_msg_asst_text("已记录 " + ("要点" * 80)))
	mix.extend(_tool_cycle(0, 300, kind="B"))
	mix.extend(_tool_cycle(1, 300, kind="B"))
	yield Scenario(
		id="mixed_c1",
		length_class="S3",
		tool_size_class="T1",
		kind="B",
		ttl_key="T0",
		ttl_seconds=0.0,
		messages=mix,
		remaining_turns=16,
		delta_text="继续\n",
		notes="mixed_text_tools",
	)


def _scenario(
	lk: str,
	tk: str,
	kind: str,
	ttl: str,
	*,
	remaining: int | None = None,
	extra_id: str = "",
	n_turns: int | None = None,
) -> Scenario:
	n = n_turns if n_turns is not None else LENGTH_TURNS[lk]
	size = TOOL_SIZE_TOKENS[tk]
	if kind == "A":
		size = min(size, 200)
	msgs = _build_messages(n_turns=n, size_tok=size, kind=kind)
	sid = f"{lk}:{tk}:{kind}:{ttl}"
	if extra_id:
		sid += f":{extra_id}"
	return Scenario(
		id=sid,
		length_class=lk,
		tool_size_class=tk,
		kind=kind,
		ttl_key=ttl,
		ttl_seconds=TTL_SECONDS[ttl],
		messages=msgs,
		remaining_turns=remaining if remaining is not None else remaining_for(lk, False),
		delta_text="下一轮\n" + ("x" * 64),
		notes="",
		endgame=remaining == 1,
	)


def list_scenarios(*, smoke: bool = False) -> list[Scenario]:
	# de-dupe by id, stable order
	seen: set[str] = set()
	out: list[Scenario] = []
	for sc in iter_scenarios(smoke=smoke):
		if sc.id in seen:
			continue
		seen.add(sc.id)
		out.append(sc)
	return out
