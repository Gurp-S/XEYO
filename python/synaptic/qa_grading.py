# -*- coding: utf-8 -*-
"""问答集的计分纪律：**分母透明**、**缺数据不是满分**、**臂对称检查**。

本模块要治的两个历史病（都能在既有报告里复现）：

1. **缺数据 = 满分**：某版 ``Answer.rate`` 写的是 ``if total else 1.0``，于是三个
   零错误会话在 ``error_visible_next_turn`` 上各贡献 1.0 —— 6 会话平均报出
   ``wsc 0.9583 / nocompress 0.8284``，而真分母只有 3 个会话 22 个事件
   （21/22 vs 11/22）。现口径：``total == 0`` ⇒ ``status="not_applicable"``、
   ``rate is None``，**不参与任何平均**，也不得折算成任何数。
2. **分母不透明**：``forbidden_actions = 0`` 到底「没有约束」还是「约束都没违反」，
   从数字上分不出来；``F3`` 还报出过 ``11/6``（yes > total，rate = 183%）。
   现口径：比例类强制 ``0 <= yes <= total``（构造即断言，yes > total 直接抛），
   计数类显式标 ``unit="count"``，另给「每千次暴露」的密度，不再冒充比例。

另有两件必要的机器执法：
- ``gate_eligible``：``total >= MIN_GATE_DENOMINATOR`` 且不偏斜才允许进发布门，
  否则只作定性线索（``directional_only``）。
- ``arm_symmetry_violations``：同一轨迹上 ``wsc`` 的可见率**不得高于** ``nocompress``。
  违反即说明判据还残留与投影同源的针（历史：合成签名），必须红。
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
from dataclasses import dataclass, field

#: 进门禁的最小分母（讨论定的门槛：分母 < 30 只记录不门禁）。
MIN_GATE_DENOMINATOR = 30
#: 单会话占分母超过该比例 ⇒ 标 skewed（当前语料 17/23 集中在 1 个会话的教训）。
SKEW_LIMIT = 0.5


@dataclass
class Answer:
	"""一道题的答案：分子 / 分母 / 状态 / 证据，缺一不可。"""

	qid: str
	mode: str
	question: str
	kind: str  # mechanical | sample
	yes: int
	total: int
	status: str = "measured"  # measured | not_applicable | pending_sample
	unit: str = "ratio"  # ratio | count
	synth_only: int = 0  # 只有合成串命中（投影抄了签名，原文不支持）
	unanchored: int = 0  # 建不出原文针而**移出分母**的事件数（判不了 ≠ 不可见）
	evidence: list[dict] = field(default_factory=list)
	note: str = ""

	def __post_init__(self) -> None:
		if self.yes < 0 or self.total < 0:
			raise ValueError(f"{self.qid}: 分子/分母不得为负")
		if self.unit == "ratio" and self.yes > self.total:
			# 历史事故 F3 报出 11/6：分子分母不同源 ⇒ 数字无法判读。
			raise ValueError(f"{self.qid}: yes({self.yes}) > total({self.total})——分子分母不同源")

	@property
	def rate(self) -> float | None:
		"""比例类返回比例；缺分母返回 ``None``（**绝不返回 1.0**）；计数类返回 ``None``。"""
		if self.status != "measured" or self.unit != "ratio" or not self.total:
			return None
		return round(self.yes / self.total, 4)

	@property
	def density_per_1k(self) -> float | None:
		"""计数类：每千次暴露的密度（F3 这类"次数"指标的唯一可读形态）。"""
		if not self.total:
			return None
		return round(self.yes / self.total * 1000, 2)

	def row(self, *, evidence_limit: int = 6) -> dict:
		return {"qid": self.qid, "mode": self.mode, "kind": self.kind, "unit": self.unit,
		        "yes": self.yes, "total": self.total, "rate": self.rate,
		        "status": self.status, "synth_only": self.synth_only,
		        "unanchored": self.unanchored,
		        "density_per_1k": self.density_per_1k, "note": self.note,
		        "question": self.question, "evidence": self.evidence[:evidence_limit]}


def make(qid: str, mode: str, question: str, kind: str, yes: int, total: int,
         *, unit: str = "ratio", synth_only: int = 0, unanchored: int = 0,
         evidence: list[dict] | None = None, note: str = "") -> Answer:
	"""构造答案：分母为 0 ⇒ 自动 ``not_applicable``（不给任何"默认满分"的机会）。"""
	status = "measured" if total else "not_applicable"
	return Answer(qid, mode, question, kind, yes, total, status, unit,
	              synth_only, unanchored, evidence or [], note)


def wilson_ci(yes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
	"""比例类置信区间（Wilson，小样本比正态近似稳）。样本为 0 返回 ``None``。"""
	if total <= 0:
		return None
	p = yes / total
	denom = 1 + z * z / total
	centre = (p + z * z / (2 * total)) / denom
	half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
	return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def aggregate(per_session: dict[str, dict[str, Answer]]) -> dict[str, dict]:
	"""跨会话汇总：**只对 measured 求和**，并把分母构成一并报出来。

	``per_session[session_id][qid] = Answer``。
	"""
	out: dict[str, dict] = {}
	qids: list[str] = []
	for answers in per_session.values():
		for qid in answers:
			if qid not in qids:
				qids.append(qid)
	for qid in qids:
		yes = total = synth_only = unanchored = 0
		rows = 0
		contrib: list[tuple[str, int, int]] = []
		unit = "ratio"
		status = "not_applicable"
		mode = kind = question = ""
		for sid, answers in per_session.items():
			a = answers.get(qid)
			if a is None:
				continue
			unit = a.unit
			mode = mode or a.mode
			kind = kind or a.kind
			question = question or a.question
			unanchored += a.unanchored
			if a.status == "measured" and a.total:
				rows += 1
				contrib.append((sid, a.yes, a.total))
				yes += a.yes
				total += a.total
				synth_only += a.synth_only
				status = "measured"
		max_share = round(max((t for _, _, t in contrib), default=0) / total, 4) if total else None
		skewed = bool(total and max_share is not None and max_share > SKEW_LIMIT)
		rec = {"qid": qid, "unit": unit, "yes": yes, "total": total, "status": status,
		       "mode": mode, "kind": kind, "question": question,
		       "sessions_contributing": rows, "max_session_share": max_share,
		       "skewed": skewed, "synth_only": synth_only, "unanchored": unanchored,
		       "rate": (round(yes / total, 4) if (unit == "ratio" and total) else None),
		       "density_per_1k": (round(yes / total * 1000, 2) if (unit == "count" and total) else None),
		       "wilson95": wilson_ci(yes, total) if unit == "ratio" else None,
		       "gate_eligible": bool(status == "measured" and total >= MIN_GATE_DENOMINATOR
		                             and not skewed and unit == "ratio"),
		       "directional_only": bool(total < MIN_GATE_DENOMINATOR or skewed)}
		out[qid] = rec
	return out


def arm_symmetry_violations(per_arm: dict[str, dict[str, dict]], *,
                            reference: str = "nocompress", subject: str = "wsc",
                            tol: float = 0.0, whitelist: tuple[str, ...] = ()) -> list[dict]:
	"""``subject`` 臂的可见率高于 ``reference`` 臂 ⇒ 判据与投影同源的残留。

	讨论口径：「压缩后比原文更可见」在可见性维度上不可解释——不可见才是压缩的
	代价。允许白名单（附理由）以免误伤真实机制，但白名单必须有证据。
	"""
	out: list[dict] = []
	sub = per_arm.get(subject) or {}
	ref = per_arm.get(reference) or {}
	for qid, rec in sub.items():
		if qid in whitelist:
			continue
		a, b = rec.get("rate"), (ref.get(qid) or {}).get("rate")
		if a is None or b is None:
			continue
		if a > b + tol:
			out.append({"qid": qid, "subject": subject, "reference": reference,
			            "subject_rate": a, "reference_rate": b, "delta": round(a - b, 4),
			            "total": rec.get("total")})
	return out


def file_digest(path) -> str:
	"""文件 sha256（provenance 用）；读不到返回空串，绝不让它拦住出数。"""
	try:
		return hashlib.sha256(open(path, "rb").read()).hexdigest()
	except OSError:
		return ""


def provenance(paths: dict[str, object], *, extra: dict | None = None) -> dict:
	"""报告头：判定器 / 运行器 / 语料的指纹 —— 报告不可复现时拒绝出数。"""
	import platform
	import sys

	out = {"python": platform.python_version(), "executable": sys.executable,
	       "digests": {name: file_digest(p) for name, p in paths.items()}}
	if extra:
		out.update(extra)
	return out


def question_bank_digest(bank) -> str:
	"""题库指纹：题目增删即变，防止「报告对不上源码」。"""
	h = hashlib.sha256()
	for q in bank:
		row = "\x1f".join(str(getattr(q, f.name, "")) for f in dataclasses.fields(q))
		h.update(row.encode("utf-8"))
		h.update(b"\x1e")
	return h.hexdigest()[:16]


__all__ = [
	"MIN_GATE_DENOMINATOR",
	"SKEW_LIMIT",
	"Answer",
	"aggregate",
	"arm_symmetry_violations",
	"file_digest",
	"make",
	"provenance",
	"question_bank_digest",
	"wilson_ci",
]
