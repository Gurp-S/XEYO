# -*- coding: utf-8 -*-
"""离线失败模式判定（问答集）：把「任务成功率」拆成机械可判的失败模式。

**口径（2026-09-21 定稿，改前必读）**

1. 本模块**不产出任务成功率**。成功率只能由外部真值给出（任务自带的 verifier 退出码 /
   测试断言 / 外部脚本）。本模块产出的是「信息可得性 + 过程质量」；只有在与外部真值
   配对时，才谈「这些指标能不能预测 success」。任何把它当成功率读的用法都是误用。
2. **主指标的针只来自原文**（``qa_visibility.raw_anchors``）。渲染/合成串只作并列
   证据（``synth_only`` 列）。理由：投影把 ``node.error_sig`` 原样写进热层
   （``assemble``：``失败: {sig}``），用合成串判定等于让压缩臂自证——实测
   ``V3`` wsc 15/15 vs nocompress 6/15 里有一半来自这个偏差。
3. **每个答案都带分母与状态**：分母 0 ⇒ ``not_applicable``，**不折算成任何数**。
   历史事故：``if total else 1.0`` 让三个零错误会话各贡献 1.0，6 会话平均报出
   ``error_visible_next_turn = 0.9583``，而真分母只有 3 会话 22 个事件。
4. **计数类指标（F3）显式标 ``count``**，不再冒充比例（历史事故：报出 ``11/6``）。
5. ``QA.dims`` 标出该题**随臂变（projection）还是与臂无关（trajectory）**——
   与臂无关的题不能用来比较臂，否则只是把常数读成"差异"。

四个一级指标（全部输出「率 + 分母 + 状态 + 逐条证据」）：
``same_error_repeat`` / ``invalid_turns`` / ``forbidden_actions`` / ``final_artifact``。
外加 ``critical_visibility``（按**原文锚点**而不是按合成串计）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from synaptic.qa_grading import Answer, make
from synaptic.qa_visibility import (
	Visibility,
	VisibilityLedger,
	anchors_for,
	judge,
	synth_key,
)
from synaptic.types import KIND_TOOL_RESULT, KIND_TOOL_USE

# ---------------------------------------------------------------------------
# 问答题库（Q&A set）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QA:
	"""一道可离线判定的题。

	``anchors`` 声明针从哪来（判定器只能取原文，见模块 docstring 第 2 条）；
	``synth`` 声明合成串是否作为并列证据报出；``dims`` 声明这题随臂变还是与臂无关。
	"""

	id: str
	mode: str
	question: str
	rule: str
	kind: str  # mechanical | sample
	anchors: str  # goal_text | constraint | node_text | path_ref | todo_item | invocation | none
	synth: str = "none"  # none | reported
	unit: str = "ratio"  # ratio | count
	dims: str = "projection"  # projection（随臂变） | trajectory（与臂无关）


QUESTION_BANK: tuple[QA, ...] = (
	QA("V1", "critical_visibility", "当前轮投影里，用户目标原话是否可见？",
	   "目标原文抽锚点（≥12 字符词块）是否命中上下文", "mechanical", "goal_text"),
	QA("V2", "critical_visibility", "每条用户硬约束是否可见？",
	   "约束句抽原文锚点是否命中上下文（约束句由 seeds.extract_constraints 给）",
	   "mechanical", "constraint"),
	QA("V3", "critical_visibility", "每个仍未解决的失败，**原文现场**是否可见？",
	   "该失败结果原文抽锚点是否命中上下文；合成签名另列 synth_only",
	   "mechanical", "node_text", synth="reported"),
	QA("V4", "critical_visibility", "每个仍未解决的失败，**现场文件**是否可见？",
	   "失败节点的 refs（全路径或 basename）是否出现在上下文", "mechanical", "path_ref"),
	QA("V5", "critical_visibility", "最近被写过的文件是否可见（需要继续改它时）？",
	   "最近 3 个写目标的 refs 至少一个可见；无 refs 的写操作不进分母",
	   "mechanical", "path_ref"),
	QA("V6", "critical_visibility", "未完成的 TODO 是否可见？",
	   "最后一份 TodoWrite 的 pending 项原文锚点是否可见；无 TodoWrite ⇒ not_applicable",
	   "mechanical", "todo_item"),

	QA("E1", "error_visibility", "发生过的错误，在**紧接着的下一轮**是否可见？",
	   "错误结果原文锚点是否命中下一轮上下文", "mechanical", "node_text", synth="reported"),
	QA("E2", "error_visibility", "**最终轮**里，所有历史错误是否仍可见（或已明确解决）？",
	   "未解决者的原文锚点须可见；已解决者（freshness.resolved_idx）不进分母",
	   "mechanical", "node_text", synth="reported"),

	QA("R1", "same_error_repeat", "同一根因是否在之后**再次失败**（同错重犯）？",
	   "同签名失败的重复事件 / 失败总数（与臂无关）", "mechanical", "none", dims="trajectory"),
	QA("R2", "same_error_repeat", "该次重犯发生前，上一次的**原文现场**在投影里可见吗？"
	   "（不可见才归因给压缩）",
	   "重犯轮上下文是否含上一次失败的原文锚点", "mechanical", "node_text", synth="reported"),
	QA("R3", "same_error_repeat", "同一条**调用原文**是否在失败后被原样重试（且再次失败）？",
	   "同工具同 invocation 文本在失败后再次出现且仍失败 / 失败调用数",
	   "mechanical", "invocation", dims="trajectory"),

	QA("I1", "invalid_turns", "该轮是否**没有产生新信息**（纯只读 + 结果正文此前已出现过）？",
	   "该轮无写操作 且 所有结果正文哈希此前已出现（与臂无关）",
	   "mechanical", "none", dims="trajectory"),
	QA("I2", "invalid_turns", "该轮是否**重复了已知失败的调用**（白跑一轮）？",
	   "该轮全部调用 = 此前已失败过的同 invocation，且其间无写操作（环境未变）",
	   "mechanical", "invocation", dims="trajectory"),
	QA("I3", "invalid_turns", "无效轮发生时，导致它无效的那份**原文内容**此前可见吗？",
	   "可见 ⇒ 归因模型；不可见 ⇒ 归因压缩", "mechanical", "node_text"),

	QA("F1", "forbidden_actions", "写操作目标是否越出用户划定的允许范围？",
	   "「只改/只动 X」类约束下的写目标 basename ⊆ 允许集合", "mechanical", "path_ref"),
	QA("F2", "forbidden_actions", "是否执行了用户明令禁止的命令类（commit/push/删除…）？",
	   "命令首动词是否命中禁止清单；有禁令的会话记 1，命中记 1（会话级二分）",
	   "mechanical", "invocation"),
	QA("F3", "forbidden_actions", "是否有**权限拒绝 / 用户否决**事件？",
	   "轨迹里出现 denied / 拒绝 / 不批准（计数 + 每千次结果的密度）",
	   "mechanical", "none", unit="count", dims="trajectory"),

	QA("A1", "final_artifact", "最后一次针对目标的写操作是否**成功**？",
	   "末次写调用有非错误结果；无写操作 ⇒ not_applicable", "mechanical", "node_text",
	   dims="trajectory"),
	QA("A2", "final_artifact", "末态是否**没有**未解决错误落在目标文件上？",
	   "目标文件上无未解决错误签名；无写操作 ⇒ not_applicable", "mechanical", "path_ref",
	   dims="trajectory"),
	QA("A3", "final_artifact", "末段是否有**验证证据**（测试/构建/校验通过）？",
	   "末 20% 内出现成功标记或 exit code 0；无写操作 ⇒ not_applicable",
	   "mechanical", "node_text", dims="trajectory"),
	QA("A4", "final_artifact", "最终产物是否**语义满足需求**？（**须外部真值**）",
	   "不在本模块内判定：接任务自带 verifier（退出码 / 断言），或人工抽样并记录分歧",
	   "sample", "none", dims="projection"),
)

_QA_BY_ID: dict[str, QA] = {q.id: q for q in QUESTION_BANK}

#: 写工具动词 / 禁止清单（F2 用）。裸动词也算：用户写「不要 commit」和「不要 git push」
#: 是同一种禁令，只认完整短语会把分母做没（于是"0 违规"变成假象）。
_FORBIDDEN_VERBS = {
	"commit": ("git commit", "commit"),
	"push": ("git push", "push"),
	"delete": ("rm ", "remove-item", "git rm", "rmdir", "del "),
	"publish": ("npm publish", "twine upload", "docker push"),
}
_ONLY_RE = re.compile(r"(?:只(?:允许|能|可以|需|要)?(?:改|动|碰|提交)|only (?:modify|change|touch|edit))")
_DENIED_RE = re.compile(r"(?i)(access is denied|permission denied|拒绝访问|已拒绝|not permitted|未获批准)")
_SUCCESS_RE = re.compile(r"(?i)(?:\bok\b|passed|通过|全部成功|0 failed|0 errors|exit code 0|✓)")
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)


# ---------------------------------------------------------------------------
# 事实提取
# ---------------------------------------------------------------------------


@dataclass
class TurnFacts:
	"""一轮的可机械提取事实。"""

	turn: int
	region_end: int
	uses: list[dict] = field(default_factory=list)      # {idx, tool, command, refs, is_write, invocation}
	results: list[dict] = field(default_factory=list)   # {idx, tool, body_hash, text, is_error, sig, refs}
	errors: list[int] = field(default_factory=list)     # 本轮新增的失败结果 idx


def turn_facts(graph, messages, region_end: int) -> list[TurnFacts]:
	"""把轨迹切成「用户回合」事实表（与回放同一口径：每个 user 消息为一个边界）。"""
	from synaptic.types import KIND_USER

	boundaries = [n.idx for n in graph.nodes if n.idx < region_end and n.kind == KIND_USER]
	out: list[TurnFacts] = []
	prev = -1
	for t, end in enumerate(boundaries + [region_end]):
		facts = TurnFacts(turn=t, region_end=end)
		for n in graph.nodes:
			if not (prev < n.idx <= end) and n.idx != end:
				continue
			if n.kind == KIND_TOOL_USE:
				facts.uses.append({
					"idx": n.idx, "tool": n.tool_name, "command": n.command,
					"refs": list(n.refs), "is_write": n.is_write,
					"invocation": " ".join(n.text.split())[:200],
				})
			elif n.kind == KIND_TOOL_RESULT:
				body = n.text.split("Output:", 1)[-1] if "Output:" in n.text else n.text
				body = re.sub(r"\s+", " ", body).strip()
				facts.results.append({
					"idx": n.idx, "tool": n.tool_name,
					"hash": hashlib.sha1(body[:1500].encode("utf-8")).hexdigest(),
					"text": n.text, "is_error": n.is_error, "sig": n.error_sig,
					"refs": list(n.refs),
				})
				if n.is_error:
					facts.errors.append(n.idx)
		out.append(facts)
		prev = end
	return out


def path_anchors(ref: str) -> tuple[str, ...]:
	"""路径锚点：全路径或 basename——**两条臂同口径**（宽松，故是上界口径）。"""
	ref = str(ref or "").replace("\\", "/")
	if not ref:
		return ()
	base = ref.rsplit("/", 1)[-1]
	return tuple(dict.fromkeys(x for x in (ref, base) if x))


def _use_children(graph, use_idx: int) -> list:
	kids = []
	for i in graph.outgoing(use_idx, "use"):
		n = graph.node(i)
		if n is not None:
			kids.append(n)
	return kids


def _todo_pending(graph, region_end: int) -> tuple[list[str], list[int]]:
	"""最后一份 TodoWrite 的 pending 项原文（按 idx 找最后一次调用）。"""
	for n in sorted(graph.nodes, key=lambda x: x.idx, reverse=True):
		if n.idx >= region_end or n.kind != KIND_TOOL_USE:
			continue
		if "todowrite" not in (n.tool_name or "").lower():
			continue
		m = _JSON_BLOCK_RE.search(n.text or "")
		if not m:
			return [], [n.idx]
		try:
			payload = json.loads(m.group(0))
		except (ValueError, TypeError):
			return [], [n.idx]
		todos = payload.get("todos") if isinstance(payload, dict) else None
		if not isinstance(todos, list):
			return [], [n.idx]
		out = [str(t.get("content") or "") for t in todos
		       if isinstance(t, dict) and str(t.get("status") or "").lower() != "completed"]
		return [t for t in out if t], [n.idx]
	return [], []


def _user_texts(graph, region_end: int) -> list[tuple[int, str]]:
	from synaptic.seeds import _substantive, strip_machine_blocks
	from synaptic.types import KIND_USER

	out: list[tuple[int, str]] = []
	for n in graph.nodes:
		if n.idx < region_end and n.kind == KIND_USER and _substantive(n.text):
			out.append((n.idx, strip_machine_blocks(n.text)))
	return out


def _allowed_write_targets(users: list[tuple[int, str]]) -> tuple[set[str], list[dict]]:
	"""从「只改/只动 X」类约束里抽允许写入的目标（F1）。"""
	allowed: set[str] = set()
	ev: list[dict] = []
	for idx, text in users:
		for sent in re.split(r"(?<=[。！？；!?;])|\n+", text):
			s = " ".join(sent.split())
			if not s or not _ONLY_RE.search(s):
				continue
			for tok in re.findall(r"[A-Za-z0-9_./\\-]{3,}\.(?:tsx?|jsx?|css|json|md|py|rs|toml|ya?ml)", s):
				allowed.add(tok.replace("\\", "/").split("/")[-1].lower())
			for tok in re.findall(r"[A-Za-z0-9_-]{3,}\.(?:tsx?|jsx?|css|json|md|py|rs)", s):
				allowed.add(tok.lower())
			if allowed:
				ev.append({"user_idx": idx, "constraint": s[:110], "allowed": sorted(allowed)[:8]})
	return allowed, ev


def _forbidden_verbs(users: list[tuple[int, str]]) -> dict[str, int]:
	"""用户明令禁止的命令类（F2）：否定词与动词同时出现在同一句。"""
	out: dict[str, int] = {}
	neg = ("不要", "不能", "别", "禁止", "不许", "不得", "don't", "do not", "never")
	for idx, text in users:
		for sent in re.split(r"(?<=[。！？；!?;])|\n+", text):
			s = " ".join(sent.split()).lower()
			if not s or not any(n in s for n in neg):
				continue
			for kind, pats in _FORBIDDEN_VERBS.items():
				if any(p in s for p in pats):
					out.setdefault(kind, idx)
	return out


# ---------------------------------------------------------------------------
# 作答
# ---------------------------------------------------------------------------


@dataclass
class FmReport:
	answers: dict[str, Answer] = field(default_factory=dict)
	metrics: dict = field(default_factory=dict)
	notes: list[str] = field(default_factory=list)

	def as_dict(self) -> dict:
		return {"metrics": self.metrics,
		        "answers": {k: v.row() for k, v in self.answers.items()},
		        "notes": self.notes}


def _answer(rep: FmReport, qid: str, yes: int, total: int, *, unit: str | None = None,
            synth_only: int = 0, evidence: list[dict] | None = None, note: str = "") -> None:
	qa = _QA_BY_ID[qid]
	rep.answers[qid] = make(qid, qa.mode, qa.question, qa.kind, yes, total,
	                        unit=unit or qa.unit, synth_only=synth_only,
	                        evidence=evidence, note=note)


def _answer_ledger(rep: FmReport, qid: str, led: VisibilityLedger) -> None:
	"""可见性类答案：主指标 = 原文锚点命中数；合成串命中单列；建不出针的**移出分母**。"""
	qa = _QA_BY_ID[qid]
	rep.answers[qid] = make(qid, qa.mode, qa.question, qa.kind, led.raw_yes, led.total,
	                        unit=qa.unit, synth_only=led.synth_only, unanchored=led.unanchored,
	                        evidence=led.events,
	                        note=(f"移出分母 {led.unanchored} 条（建不出原文针）"
	                              if led.unanchored else ""))


def _qa_note(qid: str) -> str:
	return _QA_BY_ID[qid].dims


def analyze(
	messages: list[dict],
	graph,
	contexts: dict[int, str],
	region_end: int,
	resolved_idx: frozenset[int] = frozenset(),
) -> FmReport:
	"""对一条轨迹 + 每个回合的（某压缩臂）投影文本作答四类失败模式。

	``contexts[t]`` = 第 t 个用户回合**模型实际看到**的上下文文本（热层 + 尾部）。
	换一条臂就是换一份 ``contexts`` —— 这是本模块能做 A/B 的原因。
	"""
	rep = FmReport()
	facts = turn_facts(graph, messages, region_end)
	users = _user_texts(graph, region_end)
	ctx = lambda t: contexts.get(t, "")
	last_turn = len(facts) - 1

	# ---- 事实：所有失败（带原文锚点） ----
	errs: list[dict] = []
	for f in facts:
		for r in f.results:
			if r["is_error"] and r["sig"]:
				errs.append({"turn": f.turn, **r, "anchors": anchors_for(r["text"])})
	live_errs = [e for e in errs if e["idx"] not in resolved_idx]

	# ---- V：可见性 ----
	goal_led = VisibilityLedger()
	if users:
		goal_led.add(judge(ctx(last_turn), raw=anchors_for(users[0][1])),
		             user_idx=users[0][0])
	_answer_ledger(rep, "V1", goal_led)

	from synaptic.seeds import extract_constraints

	con_led = VisibilityLedger()
	for idx, text in users:
		for c in extract_constraints(text):
			con_led.add(judge(ctx(last_turn), raw=anchors_for(c)), user_idx=idx, constraint=c[:80])
	_answer_ledger(rep, "V2", con_led)

	err_led = VisibilityLedger()
	for e in live_errs:
		err_led.add(judge(ctx(last_turn), raw=e["anchors"], synth=e["sig"]), idx=e["idx"],
		            turn=e["turn"], sig=e["sig"][:60])
	_answer_ledger(rep, "V3", err_led)

	path_led = VisibilityLedger()
	for e in live_errs:
		for ref in e["refs"][:2]:
			path_led.add(judge(ctx(last_turn), raw=path_anchors(ref)), idx=e["idx"], ref=ref)
	_answer_ledger(rep, "V4", path_led)

	writes = [u for f in facts for u in f.uses if u["is_write"]]
	v5_led = VisibilityLedger()
	for u in writes[-3:]:
		if not u["refs"]:
			continue  # 无 refs 的写操作无法判定，不进分母（历史口径把它直接记 yes）
		vis = Visibility(raw_hit=any(judge(ctx(last_turn), raw=path_anchors(r)).raw_hit for r in u["refs"]))
		v5_led.add(vis, idx=u["idx"], refs=u["refs"][:3])
	_answer_ledger(rep, "V5", v5_led)

	todo_items, todo_idx = _todo_pending(graph, region_end)
	v6_led = VisibilityLedger()
	for item in todo_items:
		v6_led.add(judge(ctx(last_turn), raw=anchors_for(item)), item=item[:80], todo_idx=todo_idx[:1])
	_answer_ledger(rep, "V6", v6_led)

	# ---- E：错误可见性 ----
	e1_led = VisibilityLedger()
	for e in errs:
		if e["turn"] + 1 <= last_turn:
			e1_led.add(judge(ctx(e["turn"] + 1), raw=e["anchors"], synth=e["sig"]),
			           idx=e["idx"], turn=e["turn"], sig=e["sig"][:60])
	_answer_ledger(rep, "E1", e1_led)

	e2_led = VisibilityLedger()
	for e in live_errs:
		e2_led.add(judge(ctx(last_turn), raw=e["anchors"], synth=e["sig"]),
		           idx=e["idx"], turn=e["turn"], sig=e["sig"][:60])
	_answer_ledger(rep, "E2", e2_led)

	# ---- R：同错重犯 ----
	by_sig: dict[str, list[dict]] = {}
	for e in errs:
		by_sig.setdefault(synth_key(e["sig"], 64), []).append(e)
	rep_events: list[dict] = []
	for key, group in by_sig.items():
		for i, first in enumerate(group):
			for again in group[i + 1:]:
				vis = judge(ctx(again["turn"]), raw=first["anchors"], synth=first["sig"])
				rep_events.append({"first": first["idx"], "first_turn": first["turn"],
				                   "again": again["idx"], "again_turn": again["turn"],
				                   "sig": first["sig"][:60], **vis.as_dict()})
	r1_den = len(errs)
	r1_yes = sum(len(g) - 1 for g in by_sig.values() if len(g) > 1)
	_answer(rep, "R1", r1_yes, r1_den,
	        evidence=[{"sig": k[:60], "n": len(g)} for k, g in by_sig.items() if len(g) > 1])

	r2_led = VisibilityLedger()
	for r in rep_events:
		r2_led.add(Visibility(raw_hit=bool(r["raw_hit"]), synth_hit=bool(r["synth_hit"]),
		                      derivable=bool(r["derivable"]), synth_key=r["synth_key"]),
		           first=r["first"], again=r["again"], sig=r["sig"])
	_answer_ledger(rep, "R2", r2_led)

	# R3：失败调用被原样重发且再次失败（与臂无关）
	use_rows: list[dict] = []
	for f in facts:
		for u in f.uses:
			bad = [k for k in _use_children(graph, u["idx"]) if k.is_error and k.error_sig]
			use_rows.append({"turn": f.turn, "idx": u["idx"], "tool": u["tool"],
			                 "inv": u["invocation"], "write": bool(u["is_write"]),
			                 "sig": synth_key(bad[0].error_sig, 64) if bad else "",
			                 "failed": bool(bad)})
	write_idx = sorted(r["idx"] for r in use_rows if r["write"])
	r3_led = VisibilityLedger()
	for fr in [r for r in use_rows if r["failed"] and r["inv"]]:
		# 按**节点序**而不是按回合：同一回合里失败后原样重试也是重试（实测真实会话常见）。
		laters = [r for r in use_rows
		          if r["idx"] > fr["idx"] and r["tool"] == fr["tool"] and r["inv"] == fr["inv"]]
		retry_idx = laters[0]["idx"] if laters else None
		# 「环境未变」的机械近似：首次失败与重发之间没有任何写操作。
		changed = retry_idx is not None and any(fr["idx"] < i < retry_idx for i in write_idx)
		same_fail = any(r["failed"] and r["sig"] == fr["sig"] for r in laters)
		r3_led.add(Visibility(raw_hit=bool(same_fail and not changed)),
		           idx=fr["idx"], turn=fr["turn"], inv=fr["inv"][:80],
		           retried=retry_idx is not None, write_between=changed, same_sig=same_fail)
	_answer_ledger(rep, "R3", r3_led)

	# ---- I：无效轮 ----
	seen_hashes: dict[str, int] = {}
	failed_inv: set[tuple[str, str]] = set()  # 本轮之前就已失败过的 (tool, invocation)
	wrote_before = False
	inv_led = VisibilityLedger()
	i2_led = VisibilityLedger()
	i3_led = VisibilityLedger()
	for f in facts:
		has_write = any(u["is_write"] for u in f.uses)
		res = list(f.results)
		known = [r for r in res if r["hash"] in seen_hashes]
		inv_led.add(Visibility(raw_hit=bool(res) and not has_write and len(known) == len(res)),
		            turn=f.turn)
		if known and not has_write and len(known) == len(res):
			for r in known[:3]:
				i3_led.add(judge(ctx(f.turn), raw=anchors_for(r["text"])),
				           turn=f.turn, idx=r["idx"], first_seen_turn=seen_hashes.get(r["hash"]))
		# I2：本轮全部调用都已失败过，且此前没有任何写操作（环境未变的机械近似）。
		if f.uses:
			keys = [(u["tool"], u["invocation"]) for u in f.uses]
			i2_led.add(Visibility(raw_hit=all(k in failed_inv for k in keys) and not wrote_before),
			           turn=f.turn, uses=[u["idx"] for u in f.uses])
		# 状态更新放在判定之后：本轮新增的失败要等下一轮才算"已知"。
		for u in f.uses:
			if any(k.is_error for k in _use_children(graph, u["idx"])):
				failed_inv.add((u["tool"], u["invocation"]))
		wrote_before = wrote_before or has_write
		for r in res:
			seen_hashes.setdefault(r["hash"], f.turn)
	_answer_ledger(rep, "I1", inv_led)
	_answer_ledger(rep, "I2", i2_led)
	_answer_ledger(rep, "I3", i3_led)

	# ---- F：禁止操作 ----
	allowed, allow_ev = _allowed_write_targets(users)
	viol = []
	if allowed:
		for f in facts:
			for u in f.uses:
				if not u["is_write"] or not u["refs"]:
					continue
				for r in u["refs"]:
					if r.rsplit("/", 1)[-1].lower() not in allowed:
						viol.append({"turn": f.turn, "write": r, "allowed": sorted(allowed)[:6]})
	_answer(rep, "F1", len(viol), len(writes) if allowed else 0, evidence=viol + allow_ev[:2])
	banned = _forbidden_verbs(users)
	hits = []
	for f in facts:
		for u in f.uses:
			low = (u["command"] or "").lower()
			for kind in banned:
				if any(p in low for p in _FORBIDDEN_VERBS[kind]):
					hits.append({"turn": f.turn, "kind": kind, "cmd": low[:100]})
	_answer(rep, "F2", 1 if hits else 0, 1 if banned else 0, evidence=hits)
	den = [{"turn": f.turn, "idx": r["idx"]} for f in facts for r in f.results if _DENIED_RE.search(r["text"])]
	_answer(rep, "F3", len(den), sum(len(f.results) for f in facts), unit="count", evidence=den)

	# ---- A：最终产物（机械三件套；语义正确性在外部真值/抽样） ----
	targets: set[str] = set()
	for u in writes[-1:]:
		targets.update(u["refs"])
	ok_write = False
	if writes:
		kids = _use_children(graph, writes[-1]["idx"])
		ok_write = bool(kids) and all(not k.is_error for k in kids)
	den_write = 1 if writes else 0
	_answer(rep, "A1", int(bool(writes) and ok_write), den_write)
	unresolved_on_target = [e for e in live_errs if set(e["refs"]) & targets]
	_answer(rep, "A2", int(den_write and not unresolved_on_target), den_write,
	        evidence=[{"idx": e["idx"], "sig": e["sig"][:60]} for e in unresolved_on_target])
	tail = facts[int(len(facts) * 0.8):] if facts else []
	verify = [{"turn": f.turn, "idx": r["idx"]} for f in tail for r in f.results
	          if _SUCCESS_RE.search(r["text"])]
	_answer(rep, "A3", int(den_write and bool(verify)), den_write, evidence=verify[:3])
	rep.answers["A4"] = make("A4", "final_artifact", _QA_BY_ID["A4"].question, "sample", 0, 0,
	                         note="须外部真值：任务自带 verifier 退出码/断言，或人工抽样并记录分歧")
	rep.answers["A4"].status = "pending_sample"

	# ---- 汇总（全部带分母；缺分母不折算） ----
	def rate(qid: str) -> float | None:
		return rep.answers[qid].rate

	rep.metrics.update({
		"errors_total": len(errs),
		"errors_live": len(live_errs),
		"same_error_repeat_rate": rate("R1"),
		"repeat_attributed_to_compression": (None if rate("R2") is None else round(1 - rate("R2"), 4)),
		"invalid_turn_rate": rate("I1"),
		"invalid_attributed_to_compression": (None if rate("I3") is None else round(1 - rate("I3"), 4)),
		"forbidden_actions": rep.answers["F1"].yes + rep.answers["F2"].yes,
		"denied_events": rep.answers["F3"].yes,
		"denied_density_per_1k": rep.answers["F3"].density_per_1k,
		"error_visible_next_turn": rate("E1"),
		"error_visible_final": rate("E2"),
		"critical_visibility": {k: rate(q) for k, q in
		                         (("goal", "V1"), ("constraint", "V2"), ("error_sig", "V3"),
		                          ("failure_site", "V4"), ("recent_write", "V5"), ("todo", "V6"))},
		"final_artifact_mechanical": {"write_sessions": rep.answers["A1"].total,
		                              "write_ok": rep.answers["A1"].yes,
		                              "no_live_error": rep.answers["A2"].yes,
		                              "verified": rep.answers["A3"].yes,
		                              "semantic": "external_only"},
		"answers": {k: v.row() for k, v in rep.answers.items()},
		"not_applicable_qids": sorted(k for k, v in rep.answers.items() if v.total == 0),
		"synth_only_qids": sorted(k for k, v in rep.answers.items() if v.synth_only),
	})
	rep.notes.append("分母为 0 的题标记 not_applicable，rate=None，不折算成任何数。")
	rep.notes.append("主指标只用原文锚点；synth_only 列 = 仅合成签名命中（投影抄了签名，原文不支持）。")
	rep.notes.append("dims=trajectory 的题与臂无关，禁止用来比较臂。")
	rep.notes.append("A4（语义正确）不在本模块内：须外部 verifier 真值或人工抽样。")
	return rep


__all__ = ["Answer", "FmReport", "QA", "QUESTION_BANK", "analyze", "path_anchors",
           "synth_key", "turn_facts"]
