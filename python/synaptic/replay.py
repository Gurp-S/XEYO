"""WSC 离线回放台：真实会话 JSONL 上的基线（XEYO C0/C1/C2）vs 突触压缩。

零 API 花费：只读 ``~/.xeyo/sessions/*.jsonl``，复用生产链已有的
``memory.simulator`` 成本模型与 ``engine.compact`` 投影口径，保证两侧
token 计量走同一套序列化（``memory.simulator.projection.emit_segment``）。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace as dc_replace
from pathlib import Path
from typing import Any, Iterable

from synaptic.assemble import AssemblyState
from synaptic.cadence import CadenceState, estimate_remaining
from synaptic.metrics import lcp_tokens, needle_survival, recoverability
from synaptic.project import project
from synaptic.seeds import harvest_needles
from synaptic.textutil import node_token_len
from synaptic.types import MODE_CLOSURE, WscParams

# ---------------------------------------------------------------------------
# 会话加载
# ---------------------------------------------------------------------------

def default_sessions_dir() -> Path:
	import os

	override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
	if override:
		return Path(override).expanduser()
	return Path.home() / ".xeyo" / "sessions"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
	if not path.is_file():
		return []
	out: list[dict[str, Any]] = []
	with path.open("r", encoding="utf-8") as fh:
		for line in fh:
			line = line.strip()
			if not line:
				continue
			try:
				obj = json.loads(line)
			except json.JSONDecodeError:
				continue
			if isinstance(obj, dict):
				out.append(obj)
	return out


def _as_api_message(row: dict[str, Any]) -> dict[str, Any]:
	role = str(row.get("role") or "user")
	content = row.get("content")
	if role == "tool":
		return {"role": "user", "content": content, "name": row.get("name")}
	msg: dict[str, Any] = {"role": role, "content": content}
	if row.get("name"):
		msg["name"] = row.get("name")
	ts = row.get("ts")
	if isinstance(ts, (int, float)):
		msg["ts"] = ts
	return msg


def iter_session_files(root: Path | None = None) -> list[Path]:
	d = root or default_sessions_dir()
	if not d.is_dir():
		return []
	return sorted(d.glob("*.jsonl"))


def _is_user_text(msg: dict[str, Any]) -> bool:
	if msg.get("role") != "user":
		return False
	c = msg.get("content")
	if isinstance(c, str):
		return True
	if isinstance(c, list):
		return all(
			not (isinstance(b, dict) and b.get("type") == "tool_result") for b in c
		)
	return False


def user_turn_starts(api_msgs: list[dict[str, Any]]) -> list[int]:
	"""用户回合起点（与 memory.simulator.replay 同口径）。"""
	idxs = [i for i, m in enumerate(api_msgs) if _is_user_text(m)]
	return idxs or ([0] if api_msgs else [])


# ---------------------------------------------------------------------------
# 记录结构
# ---------------------------------------------------------------------------

@dataclass
class TurnRecord:
	session: str
	turn: int
	mode: str
	level: str
	region_end: int
	n_messages: int
	# 三条口径统一在 simulator 的 emit_segment 空间，可直接相减
	base_tokens: int  # 未压缩（仅 C0）整段前缀
	region_raw_tokens: int  # 未压缩（仅 C0）区域内前缀，hot_tokens 的同源分母
	v61_tokens: int  # XEYO 实际 C0/C1/C2 投影
	wsc_tokens: int  # WSC 热层 + 原样尾部（= simulator 口径的 L，已含尾部）
	# 成本与命中
	v61_cost: float  # 元
	v61_hit: float  # 命中率（= 命中 token / 总 token）
	wsc_cost: float
	wsc_hit: float
	hot_tokens: int  # WSC 热层裸文本 token（不含尾部，用于「热层 2–3k」口径）
	tail_tokens: int
	# 结构
	kept: int
	pruned: int
	cards: int
	rebuilt: bool
	lcp_prev: int
	latency_ms: float
	# 收益门拒绝了这次压缩（区域太小，压了反而更大）→ 该回合按「原样发送」计
	gain_gate_skipped: bool = False
	# 基线不可得（既有 simulator 在部分会话上抛错）时，只有 WSC 侧数字有效，
	# 该回合不参与 v6.1 对比，但仍参与「相对未压缩基线」的压缩率统计。
	baseline_missing: bool = False
	needles: dict[str, dict[str, float | int]] = field(default_factory=dict)
	recover: dict[str, float | int] = field(default_factory=dict)
	# 自检（规则 2）：各段累计逐轮变动率 / 前缀失稳率，以及超阈告警条数
	churn: dict[str, float] = field(default_factory=dict)
	front_break: dict[str, float] = field(default_factory=dict)
	churn_warns: int = 0
	# 规则 8：本轮日志新增条目数 / 本轮是否重冻结 / 区域内用户原话渲染审计
	journal_appends: int = 0
	journal_refroze: bool = False
	req_rendered: int = 0
	req_total: int = 0
	#: 生产触发闸未过（未达水位 ⇒ 本回合不压缩，原样发送整段前缀）。
	#: 与 ``gain_gate_skipped``（收益不足）**分开计数**：两者的成因与治理方式不同。
	trigger_skipped: bool = False
	#: 本回合**实际发送**的是紧凑投影（头 + cursor 之后的尾部）而非整段原文。
	#: adopted 语义下它与「本回合是否折叠」是两件事：压过一次之后，每一轮都是紧凑态。
	wsc_active: bool = False
	#: 本回合发生了一次折叠（头被重新生成/追加）。
	compaction_event: bool = False
	#: 本回合实际发送的投影 token（= 下一轮水位判据的基准，对应生产 vendor
	#: ``last_prompt_tokens``）。legacy 语义下不填（0）。
	sent_tokens: int = 0
	#: project() 阶段耗时；空字典表示该回合未运行 WSC 投影。
	stage_ms: dict[str, float] = field(default_factory=dict)

	@property
	def reduction_vs_base(self) -> float:
		if self.base_tokens <= 0:
			return 0.0
		return 1.0 - self.wsc_tokens / self.base_tokens

	@property
	def reduction_vs_v61(self) -> float:
		if self.v61_tokens <= 0:
			return 0.0
		return 1.0 - self.wsc_tokens / self.v61_tokens

	def as_row(self) -> dict[str, Any]:
		d = dict(self.__dict__)
		d["reduction_vs_base"] = round(self.reduction_vs_base, 4)
		d["reduction_vs_v61"] = round(self.reduction_vs_v61, 4)
		d["latency_ms"] = round(self.latency_ms, 3)
		return d


@dataclass
class SessionRecord:
	session: str
	path: str
	mode: str
	level: str
	n_messages: int
	turns: list[TurnRecord] = field(default_factory=list)
	error: str = ""
	# 基线不可得但 WSC 侧仍可采（既有 simulator 缺陷导致），不算跳过
	degraded: str = ""
	recover: dict[str, float | int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 单会话回放
# ---------------------------------------------------------------------------

def run_session(
	path: Path,
	*,
	level: str = "Medium+",
	mode: str = MODE_CLOSURE,
	params: WscParams | None = None,
	min_prefix_messages: int = 8,
	sample_turns: int = 0,
	sim_params: Any = None,
	#: 生产触发口径（旁路开关）：>0 时只有 ``C0(prefix) tokens ≥ ratio × limit`` 才压缩。
	#: 默认 0 = 关闭（保持历史行为，便于背靠背 A/B）。生产取 0.8。
	trigger_ratio: float = 0.0,
	#: 上下文窗口上限（token）；与 ``trigger_ratio`` 配合，任一为 0 即关闭闸门。
	context_limit_tokens: int = 0,
	#: 压缩口径：
	#: - ``"legacy"``（默认，历史口径）：每回合都尝试压缩；未过闸/收益门拒绝的回合
	#:   **发送整段原文**。与生产不符（见 docs §13.8 与 §15）。
	#: - ``"adopted"``（生产语义）：一旦压过就**一直发紧凑投影**（冻结头 + cursor 之后
	#:   的尾部），水位基准是**上一枪实际发送的 prompt tokens**（生产 vendor usage）。
	#:   锚点：``memory/runtime.py:1643-1645``（任何 action 都走 apply_c2_messages）、
	#:   ``runtime.py:1910-1914``（读 last_prompt_tokens）、``engine/query_loop.py:1382``。
	compact_model: str = "legacy",
	#: 热层句柄形态：``expand``（历史形态，离线回放的默认档）/ ``read``（生产形态，
	#: 渲染成 ``Read(file_path=…, offset=…, limit=…)``，**必须**配合 ``view_dir``）。
	handle_style: str = "expand",
	#: 冷层取回视图落盘目录（`read` 档必给）。每个会话写自己一份 ⇒ 并行安全。
	#: ⚠️ 生产要求该目录在 ``<ws>/.xeyo_offload/`` 下，否则 `Read` 的 read-state 豁免失效。
	view_dir: str = "",
	#: 句柄里**渲染**用的引用基准工作区：非空时把引用渲染成相对该目录的路径
	#: （= 模型侧 `Read` 的 cwd）。空 = 绝对路径（历史口径）。
	#: 代价差别是实打实的（热层 token median 3407 → 见 docs §15.17），故必须可选。
	view_ref_base: str = "",
) -> SessionRecord:
	"""回放单个会话：逐用户回合同时跑 XEYO 基线与 WSC。"""
	rows = load_jsonl(path)
	api = [_as_api_message(r) for r in rows]
	rec = SessionRecord(
		session=path.stem, path=str(path), mode=mode, level=level, n_messages=len(api)
	)
	if len(api) < min_prefix_messages:
		rec.error = "too_short"
		return rec

	from engine.compact import keep_tail_cut, project as c0_project
	from memory.simulator.cache_model import CacheState
	from memory.simulator.params import load_params
	from memory.simulator.projection import project as sim_project
	from memory.simulator.replay import replay_messages
	from memory.simulator.scenarios import state_from_messages

	sp = sim_params or load_params()
	base_turns: list[Any] = []
	baseline_error = ""
	try:
		base = replay_messages(api, session_id=rec.session, params=sp)
		base_turns = list(base.turns)
	except Exception as exc:  # noqa: BLE001
		# 既有 simulator 在部分会话上抛错（见 docs：SimpleNamespace 缺字段）。
		# 这是仓库既有缺陷、不是 WSC 引入的；此处降级为「无 v6.1 基线」，
		# 让 WSC 侧数据仍然可采，不被基线连坐丢掉整条会话。
		baseline_error = f"{type(exc).__name__}: {exc}"

	starts = user_turn_starts(api)
	baseline_missing = False
	if base_turns and len(base_turns) != len(starts):
		# 基线回合数与本地切分不一致：整条会话的逐回合对齐不可信，弃用基线
		base_turns = []
		baseline_missing = True
	if not base_turns:
		baseline_missing = True

	pset = params or WscParams(level=level, mode=mode).for_level(level)
	view_path: Path | None = None
	view_ref = ""
	if handle_style == "read":
		import dataclasses as _dc

		pset = _dc.replace(pset, handle_style="read")
		if view_dir:
			view_path = Path(view_dir) / f"{rec.session}.txt"
			if view_ref_base:
				from memory.offload import ref_path_for

				view_ref = ref_path_for(view_path, view_ref_base)
	prev_state: AssemblyState | None = None
	prev_x = ""
	prev_hot = ""
	# ── adopted（收养后生产语义）的跨轮状态 ──────────────────────────────
	# 生产一旦压过，后续每轮都发「冻结头 + cursor 之后的右段」，**从不回退到整段原文**
	# （memory/runtime.py:1643-1645 / 1094-1096）；水位基准是**上一枪实际发送**的
	# prompt tokens（vendor usage：query_loop.py:1382 → runtime.py:1910-1914）。
	# legacy 档保留历史口径，两个档不得混用数字。
	adopted = compact_model == "adopted"
	cursor = 0
	hot_text = ""
	last_sent_tokens = 0.0
	#: `econ` 折叠节奏的跨轮状态（自我校准压缩比；见 synaptic/cadence.py）。
	#: 头的结构上界 = 紧凑渲染预算 + 日志重冻结阈值（超过就重冻结），据此给估计封顶
	#: ——不封顶会踩「估计偏高 ⇒ 拒折 ⇒ 区域更大 ⇒ 估计更高」的死亡螺旋。
	cadence_state = CadenceState(
		head_delta_cap=int(pset.hot_budget_tokens) + int(pset.journal_growth_tokens)
	)

	turn_idx = list(range(len(starts)))
	if sample_turns and len(turn_idx) > sample_turns:
		step = len(turn_idx) / float(sample_turns)
		turn_idx = [turn_idx[min(len(turn_idx) - 1, int(i * step))] for i in range(sample_turns)]

	recover_acc: dict[str, float] = {}

	for t in turn_idx:
		end = starts[t + 1] if t + 1 < len(starts) else len(api)
		prefix = api[:end]
		if len(prefix) < min_prefix_messages:
			continue
		region_end = keep_tail_cut(prefix)
		if region_end <= 1:
			continue

		region_raw = _region_raw_tokens(c0_project(prefix[:region_end]))
		# ── 生产触发口径（旁路开关，默认关）────────────────────────────
		# 生产 C2 只在「累计 prompt 过水位」时压缩一次，压缩之间原样增长；
		# 而本回放此前对**每回合**都尝试压缩 ⇒ 测的是生产不会跑的工况
		# （见 docs §13.8）。打开本开关后按生产判据触发，未过水位则本回合不压缩。
		# 锚点：memory/runtime.py:1855/1871、engine/query_loop.py:857。
		if adopted:
			# 水位基准 = 上一枪**实际发送**的 prompt tokens（生产 vendor last_prompt_tokens）。
			# 首轮无上一枪 ⇒ 基准 0 ⇒ 不触发（与生产一致：第一次请求没有 usage 可读）。
			# ── 折叠判据 ────────────────────────────────────────────────
			# `econ` 档由**算法层**的成本判据决定（synaptic.cadence，O(1)、不需要渲染）；
			# 其余走生产水位（= 上一枪实际发送的 prompt tokens ≥ ratio×limit）。
			econ_dec = None
			region_for_econ = 0
			if pset.fold_cadence == "econ":
				region_for_econ = _region_raw_tokens(prefix[cursor:region_end])
				econ_dec = cadence_state.decide(
					region_tokens_=region_for_econ,
					tail_tokens_=_region_raw_tokens(prefix[region_end:]),
					remaining_turns=estimate_remaining(prefix),
					margin=pset.fold_margin,
					price_ratio=pset.fold_price_ratio,
				)
				fired_gate = bool(econ_dec.fold)
			else:
				fired_gate = bool(
					trigger_ratio > 0
					and context_limit_tokens > 0
					and last_sent_tokens >= int(trigger_ratio * context_limit_tokens)
				)
			trigger_skipped = not fired_gate
			t0 = time.perf_counter()
			proj = (
				project(
					prefix,
					region_end=region_end,
					params=pset,
					prev=prev_state,
					session=rec.session,
					region_baseline_tokens=region_raw,
					view_path=view_path,
					view_ref=view_ref,
				)
				if fired_gate
				else None
			)
			dt_ms = (time.perf_counter() - t0) * 1000.0
			folded = bool(proj is not None and proj.result.compressed)
			hot_before = hot_text  # 必须在覆盖前取：否则 lcp_prev 变成「头与自身比」恒满
			if folded:
				# 回填实测追加比：下一次判据据此估 head_delta（无需渲染、O(1)）。
				# `carried_over` 只在**头被沿用**时为真——首折（头从无到有）与
				# 日志重冻结（整层重写）时的 head_delta 是「整个新头」，喂进去会
				# 把追加比抬到 1.0 量级、此后永久拒绝折叠（见 cadence.observe_fold）。
				if econ_dec is not None:
					cadence_state.observe_fold(
						region_tokens_=region_for_econ,
						head_delta_tokens=max(
							0, node_token_len(proj.text) - node_token_len(hot_before)
						),
						# `journal_refroze` 只是逻辑换头；append-only 仍保持前缀，
						# 是否可沿用缓存由实际 `rebuilt` 判定。
						carried_over=bool(hot_before and not proj.result.rebuilt),
					)
				cursor = region_end
				hot_text = proj.text
				prev_state = proj.state
				prev_hot = hot_text
			active = cursor > 0
			# 发什么：压过 ⇒ 头 + cursor 之后的右段；没压过 ⇒ 整段原文。
			tail_c0 = c0_project(prefix[cursor:]) if active else c0_project(prefix)
			state = state_from_messages(
				tail_c0, cursor=0, system=hot_text if active else _SYSTEM_STANDIN
			)
			sim_pr, spl, cost = _measure(state, _cache(sp, prev_x), sp)
			# 头/尾按 Projected.p_end 切分（p_s+p_c = 头），与 L 同一量纲。
			tail_tokens = max(0, int(sim_pr.length) - int(sim_pr.p_end))
			prev_x = sim_pr.x
			last_sent_tokens = float(sim_pr.length)
			# 针只在**折叠回合**采：非折叠回合的头与区域都没变 ⇒ 与上一折叠回合同值，
			# 重复采样只会白付一次建图成本（口径与 legacy 档一致）。
			needles = (
				needle_survival(
					hot_text,
					harvest_needles(
						_restrict(proj.graph, region_end),
						proj_file_states(proj),
						region_end=region_end,
					),
				)
				if folded
				else {}
			)
			rec_one = recoverability(proj) if folded else {}
			for k in ("checked", "lossless", "pruned", "bound", "unbound"):
				recover_acc[k] = recover_acc.get(k, 0.0) + float(rec_one.get(k, 0) or 0)
			rec.turns.append(
				TurnRecord(
					session=rec.session,
					turn=t,
					mode=mode,
					level=pset.level,
					region_end=region_end,
					n_messages=len(prefix),
					base_tokens=_c0_sim_tokens(prefix, c0_project, sim_pr, sp),
					region_raw_tokens=region_raw,
					v61_tokens=_v61(base_turns, t, "tokens"),
					v61_cost=_v61(base_turns, t, "cost"),
					v61_hit=_v61_hit(base_turns, t),
					wsc_tokens=int(sim_pr.length),
					wsc_cost=float(cost),
					wsc_hit=float(spl.H) / max(1.0, float(sim_pr.length)),
					hot_tokens=node_token_len(hot_text) if active else 0,
					tail_tokens=int(tail_tokens),
					kept=len(proj.result.hot.kept_nodes) if folded else 0,
					pruned=len(proj.result.hot.pruned_nodes) if folded else 0,
					cards=len(proj.result.hot.cards) if folded else 0,
					rebuilt=bool(proj.result.rebuilt) if folded else False,
					lcp_prev=lcp_tokens(hot_text, hot_before),
					latency_ms=dt_ms,
					stage_ms=dict(proj.result.stage_ms) if folded else {},
					trigger_skipped=trigger_skipped,
					gain_gate_skipped=bool(fired_gate and not folded),
					wsc_active=active,
					compaction_event=folded,
					sent_tokens=int(sim_pr.length),
					baseline_missing=baseline_missing,
					needles=needles,
					recover=rec_one,
					churn=dict(proj.result.churn) if folded else {},
					front_break=dict(proj.result.front_break) if folded else {},
					churn_warns=len(proj.result.churn_warnings) if folded else 0,
					journal_appends=int(proj.result.journal_appends) if folded else 0,
					journal_refroze=bool(proj.result.journal_refroze) if folded else False,
					req_rendered=int(proj.result.user_requests_rendered) if folded else 0,
					req_total=int(proj.result.user_requests_total) if folded else 0,
				)
			)
			continue

		prompt_tokens = _region_raw_tokens(c0_project(prefix))
		trigger_skipped = bool(
			trigger_ratio > 0
			and context_limit_tokens > 0
			and prompt_tokens < int(trigger_ratio * context_limit_tokens)
		)
		t0 = time.perf_counter()
		proj = (
			None
			if trigger_skipped
			else project(
				prefix,
				region_end=region_end,
				params=pset,
				prev=prev_state,
				session=rec.session,
				region_baseline_tokens=region_raw,
				view_path=view_path,
				view_ref=view_ref,
			)
		)
		dt_ms = (time.perf_counter() - t0) * 1000.0

		hot_text = proj.text if proj is not None else ""
		tail_c0 = c0_project(prefix[region_end:])
		# ⚠️ legacy 档的 tail_tokens 用 json.dumps 估体积：会话 JSONL 里带 reasoning
		# 等不参与投影的字段，JSON 体积会把它算进来（实测同一条尾部差 ~5 倍），
		# **与 L 不是同一量纲**。adopted 档已改为 `L − p_end`。该字段只进
		# `--dump-turns` 明细，不进报告表；保留旧值仅为与历史 dump 可比。
		tail_tokens = sum(
			node_token_len(json.dumps(m, ensure_ascii=False, sort_keys=True)) for m in tail_c0
		)

		# 不压缩的回合（生产触发闸未过 / 收益门拒绝）：该回合实际发送的就是整段前缀。
		if trigger_skipped or not proj.result.compressed:
			state = state_from_messages(c0_project(prefix), cursor=0, system=_SYSTEM_STANDIN)
			cache = _cache(sp, prev_x)
			sim_pr, spl, cost = _measure(state, cache, sp)
			prev_x = sim_pr.x
			rec.turns.append(
				TurnRecord(
					session=rec.session,
					turn=t,
					mode=mode,
					level=pset.level,
					region_end=region_end,
					n_messages=len(prefix),
					base_tokens=int(sim_pr.length),
					region_raw_tokens=region_raw,
					v61_tokens=_v61(base_turns, t, "tokens"),
					v61_cost=_v61(base_turns, t, "cost"),
					v61_hit=_v61_hit(base_turns, t),
					wsc_tokens=int(sim_pr.length),
					wsc_cost=float(cost),
					wsc_hit=float(spl.H) / max(1.0, float(sim_pr.length)),
					hot_tokens=0,
					tail_tokens=int(tail_tokens),
					kept=0,
					pruned=0,
					cards=0,
					rebuilt=False,
					lcp_prev=lcp_tokens(proj.text, prev_hot) if proj else 0,
					latency_ms=dt_ms,
					stage_ms={},
					trigger_skipped=trigger_skipped,
					gain_gate_skipped=not trigger_skipped,
					baseline_missing=baseline_missing,
					needles={},
					recover={},
					# 收益门拒绝的回合不推进组装状态，故不产生跨轮自检统计
					churn={},
					front_break={},
					churn_warns=0,
					journal_appends=0,
					journal_refroze=False,
					req_rendered=0,
					req_total=0,
				)
			)
			# 不推进组装状态：本轮没有产生压缩态，下一轮仍以「未压缩」为起点
			if proj is not None:
				prev_hot = proj.text
			continue

		# 与基线同口径：把 WSC 投影建成 simulator 的 ContextState，再算 L / H / cost。
		# 注意 sim_pr.length 已含热层 + 尾部（热层作为 p_s 传入），不要再加 tail_tokens。
		state = state_from_messages(tail_c0, cursor=0, system=hot_text)
		sim_pr, spl, cost = _measure(state, _cache(sp, prev_x), sp)
		prev_x = sim_pr.x

		wsc_tokens = int(sim_pr.length)
		needles = needle_survival(
			hot_text,
			harvest_needles(
				_restrict(proj.graph, region_end),
				proj_file_states(proj),
				region_end=region_end,
			),
		)
		rec_one = recoverability(proj)
		for k in ("checked", "lossless", "pruned", "bound", "unbound"):
			recover_acc[k] = recover_acc.get(k, 0.0) + float(rec_one.get(k, 0) or 0)

		rec.turns.append(
			TurnRecord(
				session=rec.session,
				turn=t,
				mode=mode,
				level=pset.level,
				region_end=region_end,
				n_messages=len(prefix),
				base_tokens=_c0_sim_tokens(prefix, c0_project, sim_pr, sp),
				region_raw_tokens=region_raw,
				v61_tokens=_v61(base_turns, t, "tokens"),
				v61_cost=_v61(base_turns, t, "cost"),
				v61_hit=_v61_hit(base_turns, t),
				hot_tokens=node_token_len(hot_text),
				tail_tokens=int(tail_tokens),
				wsc_tokens=wsc_tokens,
				wsc_cost=float(cost),
				wsc_hit=float(spl.H) / max(1.0, float(sim_pr.length)),
				kept=len(proj.result.hot.kept_nodes),
				pruned=len(proj.result.hot.pruned_nodes),
				cards=len(proj.result.hot.cards),
				rebuilt=bool(proj.result.rebuilt),
				lcp_prev=lcp_tokens(hot_text, prev_hot),
				latency_ms=dt_ms,
				stage_ms=dict(proj.result.stage_ms),
				baseline_missing=baseline_missing,
				needles=needles,
				recover=rec_one,
				churn=dict(proj.result.churn),
				front_break=dict(proj.result.front_break),
				churn_warns=len(proj.result.churn_warnings),
				journal_appends=int(proj.result.journal_appends),
				journal_refroze=bool(proj.result.journal_refroze),
				req_rendered=int(proj.result.user_requests_rendered),
				req_total=int(proj.result.user_requests_total),
			)
		)
		prev_state = proj.state
		prev_hot = hot_text

	rec.recover = recover_acc
	if baseline_error:
		rec.degraded = f"baseline_degraded: {baseline_error}"
	return rec


def proj_file_states(proj) -> dict:
	return {s.path: s for s in proj.result.hot.file_states}


#: 基线口径下 p_s 的占位文本。会话 JSONL 不含真实 system prompt，与
#: memory.simulator 自身对基线的处理保持一致（两侧同占位 → 可相减）。
_SYSTEM_STANDIN = "You are XEYO, a coding agent.\n"


def _restrict(graph, region_end: int):
	"""把图裁到被压缩区域。"""
	return dc_replace(graph, nodes=tuple(n for n in graph.nodes if n.idx < region_end))


def _cache(sp, prev_x: str):
	from memory.simulator.cache_model import CacheState

	return CacheState(
		provider=sp.provider,
		age_seconds=0.0,
		model=sp.model,
		slot=sp.price_slot,
		ts=sp.default_ts,
		x_prev=prev_x,
	)


def _region_raw_tokens(msgs: list[dict[str, Any]]) -> int:
	"""区域的**裸文本** token（C0 之后的）。收益门在裸文本空间比较：

热层替换的就是这一段文本，尾部不动，因此「热层文本 token vs 区域文本 token」
才是同量纲的比较。用 emit_segment 空间去比会带上角色头开销而偏向压缩。
	"""
	from synaptic.textutil import message_text

	return sum(node_token_len(message_text(m)) for m in msgs)


def _c0_sim_tokens(prefix: list[dict[str, Any]], c0_project, _sim_pr, sp) -> int:
	"""未压缩（仅 C0）整段前缀在 simulator emit_segment 空间的 token 数。

与 wsc_tokens / v61_tokens 同一空间，三者可直接相减。
	"""
	return _sim_tokens(c0_project(prefix), sp)


def _sim_tokens(msgs: list[dict[str, Any]], sp) -> int:
	from memory.simulator.projection import project as sim_project
	from memory.simulator.scenarios import state_from_messages

	st = state_from_messages(msgs, cursor=0, system=_SYSTEM_STANDIN)
	return int(sim_project(st).length)


def _v61(base_turns: list[Any], t: int, what: str):
	"""取 v6.1 基线的某一项；基线不可得时返回 0。"""
	if not base_turns or t >= len(base_turns):
		return 0
	bt = base_turns[t]
	return int(bt.v61_tokens) if what == "tokens" else float(bt.simulated_cost)


def _v61_hit(base_turns: list[Any], t: int) -> float:
	"""v6.1 的命中率。

``ReplayTurn.predicted_hit`` 存的是**命中 token 数**（``shot.H``），不是比率——
直接当比率用会报出「命中率 2449」。此处统一换算成 H / L。
	"""
	if not base_turns or t >= len(base_turns):
		return 0.0
	bt = base_turns[t]
	l = max(1.0, float(bt.v61_tokens))
	return float(bt.predicted_hit) / l


def _measure(state, cache, sp):
	"""算 (投影, Split, 输入成本元)。H 按 emit_segment 口径。"""
	from memory.simulator.cache_model import prices_for
	from memory.simulator.cost_model import (
		c_biz_yuan,
		expected_output,
		split_tokens,
	)
	from memory.simulator.projection import project as sim_project

	pr = sim_project(state)
	_, spl = split_tokens(s_a=state, cache=cache, action="keep", params=sp, proj=pr)
	biz = c_biz_yuan(spl, expected_output(1.0, sp), prices_for(cache, sp))
	return pr, spl, biz


def run_sessions(
	files: Iterable[Path],
	*,
	level: str = "Medium+",
	mode: str = MODE_CLOSURE,
	min_prefix_messages: int = 8,
	sample_turns: int = 0,
	limit: int | None = None,
	params: WscParams | None = None,
) -> list[SessionRecord]:
	out: list[SessionRecord] = []
	for i, p in enumerate(files):
		if limit is not None and i >= limit:
			break
		out.append(
			run_session(
				p,
				level=level,
				mode=mode,
				min_prefix_messages=min_prefix_messages,
				sample_turns=sample_turns,
				params=params,
			)
		)
	return out


def _session_worker(payload: tuple) -> SessionRecord:
	"""ProcessPoolExecutor 的 worker —— 必须是模块级、可 pickle 的纯函数。"""
	path, kw = payload
	return run_session(path, **kw)


def run_sessions_parallel(
	files: Sequence[Path],
	*,
	workers: int = 4,
	**kw: Any,
) -> list[SessionRecord]:
	"""按**会话**并行回放（会话之间完全独立 ⇒ 天然可并行，结果与串行一致）。

	## 口径（改前先读，否则延迟数会被误用）

	``TurnRecord.latency_ms`` 是**进程内** ``perf_counter`` 测的 ``project()`` 耗时；
	``workers > 1`` 时会混入 CPU 争用 ⇒ **只有 ``workers == 1`` 才是串行延迟基线**。
	调用方必须把实际 jobs 写进报告的 ``sampling``，比对延迟前先核对那里。

	聚合类指标（压缩率 / 针 / 命中率 / lossless）**不受并行影响**：每个会话在独立
	进程里按同一确定性路径重放，唯一的共享状态是只读的。

	顺序与 ``files`` 一致（``ex.map`` 保序）⇒ 报告可复现。
	"""
	if workers <= 1 or len(files) <= 1:
		return [run_session(p, **kw) for p in files]
	from concurrent.futures import ProcessPoolExecutor

	payloads = [(p, kw) for p in files]
	out: list[SessionRecord] = []
	with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
		for rec in ex.map(_session_worker, payloads, chunksize=1):
			out.append(rec)
	return out
