"""WSC 回放报告：聚合指标 + 口径声明 + 偏离清单。

报告强制包含「未测量的部分」——任务成功率这类只能靠真实 A/B 才能得到的
结论，一律标为未测量，不出现在预测区。
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from synaptic.metrics import assert_no_llm_dependency
from synaptic.replay import SessionRecord, TurnRecord, iter_session_files, run_session
from synaptic.types import MODE_APPEND_ONLY, MODE_CLOSURE

NEEDLE_CATS = ("user", "error_sig", "path", "path_recent", "failure_site")


def _pct(xs: Sequence[float], p: float) -> float:
	if not xs:
		return 0.0
	s = sorted(xs)
	if p <= 0:
		return float(s[0])
	if p >= 100:
		return float(s[-1])
	k = (len(s) - 1) * (p / 100.0)
	lo = int(k)
	hi = min(lo + 1, len(s) - 1)
	w = k - lo
	return float(s[lo] * (1 - w) + s[hi] * w)


def _stat(xs: Sequence[float]) -> dict[str, float]:
	if not xs:
		return {
			"n": 0, "mean": 0.0, "median": 0.0, "p10": 0.0,
			"p50": 0.0, "p90": 0.0, "p95": 0.0, "max": 0.0,
		}
	return {
		"n": float(len(xs)),
		"mean": float(statistics.fmean(xs)),
		"median": float(statistics.median(xs)),
		"p10": _pct(xs, 10),
		"p50": _pct(xs, 50),
		"p90": _pct(xs, 90),
		"p95": _pct(xs, 95),
		"max": float(max(xs)),
	}


def _mean(xs: Sequence[float]) -> float:
	return float(statistics.fmean(xs)) if xs else 0.0


def _ratio(num: float, den: float) -> float:
	"""比值；分母为 0 时返回 0（不返回 inf/nan——报告要能直接进 JSON 与表格）。"""
	return float(num / den) if den else 0.0


@dataclass
class Aggregate:
	label: str
	level: str
	mode: str
	n_sessions: int = 0
	n_turns: int = 0
	n_skipped: int = 0
	turns: list[TurnRecord] = field(default_factory=list)
	errors: dict[str, int] = field(default_factory=dict)

	# -- 派生指标 -----------------------------------------------------------
	def _vals(self, attr: str) -> list[float]:
		return [float(getattr(t, attr)) for t in self.turns]

	def summary(self) -> dict[str, Any]:
		if not self.turns:
			return {"label": self.label, "turns": 0, "note": "no comparable turns"}
		# v6.1 对比只在基线可得的回合上做；压缩率用「未压缩基线」口径，全回合可用
		cmp_turns = [t for t in self.turns if not t.baseline_missing]
		# 冷启动稀释：每个会话的**首个可比回合**没有「上一轮投影」（`x_prev` 为空），
		# 命中必然为 0，而 v6.1 侧同样为 0。本语料 235 会话 / 651 回合 ⇒ 首回合约占 1/3，
		# 足以把均值压到不具解释力。故额外出一个「跳首回合」口径（与探针口径一致）；
		# **原口径保留不删**——它才是「含冷启动的真实平均」。
		first_turn: dict[str, int] = {}
		for t in cmp_turns:
			k = t.session
			if k not in first_turn or int(t.turn) < first_turn[k]:
				first_turn[k] = int(t.turn)
		steady = [t for t in cmp_turns if int(t.turn) != first_turn.get(t.session)]
		# ⚠️ 2026-09-15 修正：必须**同时**排除两道闸的跳过回合。
		# 触发器（trigger_skipped）= 未过生产水位，**根本没尝试压缩**；
		# 收益门（gain_gate_skipped）= 尝试了但拒绝。
		# 只排后者时，生产口径下大量"根本没压"的回合会混进来，把
		# `reduction_vs_base_compressed_only` 与 `hot_tokens` 的 median 稀释成 0
		# ——实测 trig08 报出 n=697/median=0，而真实"压过的"回合只有 210 个。
		compressed_turns = [
			t for t in self.turns if not t.gain_gate_skipped and not t.trigger_skipped
		]
		# ── adopted 口径（2026-09-16 新增）────────────────────────────────
		# legacy 档：未过闸的回合发整段原文 ⇒ 只有「压过」的回合才算压缩态。
		# adopted 档：一旦压过，后续每轮都发紧凑投影（生产 runtime.py:1643-1645）
		#   ⇒ 「紧凑态回合」才是压缩率/成本的可比群体，且它与「折叠事件回合」不是一回事。
		active_turns = [t for t in self.turns if t.wsc_active]
		event_turns = [t for t in self.turns if t.compaction_event]
		base = self._vals("base_tokens")
		wsc = self._vals("wsc_tokens")
		hot = [float(t.hot_tokens) for t in compressed_turns]
		red_base = [1 - w / b for w, b in zip(wsc, base) if b > 0]
		# 只统计「WSC 真的压了」的回合：把收益门拒绝的回合算进来会把均值稀释成
		# 「看起来压不动」，而真实语义是「这些回合本来就不该压」。
		red_base_compressed = [
			1 - float(t.wsc_tokens) / float(t.base_tokens)
			for t in compressed_turns
			if t.base_tokens > 0
		]
		# ⚠️ 这里**不能** zip(compressed_turns, base)：`base` 是全量列表，压缩子集与全量
		# 一旦错位（只要有一个回合被收益门跳过），后面每对都错行——曾报出 hot_share=198.9
		# 这种物理上不可能的值（热层 ≤ 区域基线 ≤ 整段基线 ⇒ 该比值必然 < 1）。
		hot_ratio = [
			float(t.hot_tokens) / float(t.region_raw_tokens)
			for t in compressed_turns
			if float(t.region_raw_tokens) > 0
		]
		v61 = [float(t.v61_tokens) for t in cmp_turns]
		red_v61 = [1 - float(t.wsc_tokens) / float(t.v61_tokens) for t in cmp_turns if t.v61_tokens > 0]

		needles: dict[str, dict[str, float]] = {}
		for cat in NEEDLE_CATS:
			rates = [
				float(t.needles.get(cat, {}).get("rate", 1.0))
				for t in self.turns
				if t.needles.get(cat, {}).get("n", 0)
			]
			if rates:
				needles[cat] = {
					"turns": float(len(rates)),
					"mean_rate": float(statistics.fmean(rates)),
					"min_rate": float(min(rates)),
					"p10": _pct(rates, 10),
				}

		# 信息针**池化**口径（Σhit/Σn，2026-09-16 新增）。
		# 上面的 `needles[cat]["mean_rate"]` 是「在**该针有样本的回合**上取均值」——
		# 不同触发口径下样本群体本身就变了（生产口径下短/中会话从不压缩 ⇒ 无样本
		# ⇒ 自动退出分母），跨口径相减会把"样本退出"读成"指标退化"（第七轮实测：
		# 汇总报 −10pp，同群体实为 −4.95pp）。池化口径把分子分母放在一起加，
		# 至少让**同一档内**的 cohort 拆分不会因回合数变化而漂移。
		needles_pooled: dict[str, dict[str, float]] = {}
		for cat in NEEDLE_CATS:
			hit = sum(int(t.needles.get(cat, {}).get("hit", 0)) for t in self.turns)
			n = sum(int(t.needles.get(cat, {}).get("n", 0)) for t in self.turns)
			if n:
				needles_pooled[cat] = {
					"n": float(n),
					"hit": float(hit),
					"rate": float(hit / n),
				}

		pruned = sum(int(t.recover.get("pruned", 0) or 0) for t in self.turns)
		bound = sum(int(t.recover.get("bound", 0) or 0) for t in self.turns)
		checked = sum(int(t.recover.get("checked", 0) or 0) for t in self.turns)
		lossless = sum(int(t.recover.get("lossless", 0) or 0) for t in self.turns)

		# 段落自检（规则 2）：per-turn 值为「截至该轮的累计率」，故取 mean/max 两个视角
		churn: dict[str, dict[str, float]] = {}
		for h in sorted({h for t in self.turns for h in t.front_break}):
			chg = [float(t.churn.get(h, 0.0)) for t in self.turns if h in t.churn]
			frb = [float(t.front_break.get(h, 0.0)) for t in self.turns if h in t.front_break]
			churn[h] = {
				"turns": float(len(frb)),
				"change_mean": float(statistics.fmean(chg)) if chg else 0.0,
				"change_max": float(max(chg)) if chg else 0.0,
				"front_break_mean": float(statistics.fmean(frb)) if frb else 0.0,
			}

		stage_latency: dict[str, dict[str, float]] = {}
		for name in sorted({name for t in self.turns for name in t.stage_ms}):
			stage_latency[name] = _stat(
				[float(t.stage_ms[name]) for t in self.turns if name in t.stage_ms]
			)

		return {
			"label": self.label,
			"level": self.level,
			"mode": self.mode,
			"sessions": self.n_sessions,
			"turns": self.n_turns,
			"skipped": self.n_skipped,
			"errors": dict(sorted(self.errors.items())),
			"base_tokens": _stat(base),
			"v61_tokens": _stat(v61),
			"wsc_tokens": _stat(wsc),
			"hot_tokens": _stat(hot),
			"reduction_vs_base": _stat(red_base),
			"reduction_vs_base_compressed_only": _stat(red_base_compressed),
			"reduction_vs_v61": _stat(red_v61),
			"hot_share_of_base": _stat(hot_ratio),
			"gain_gate_skipped": int(sum(1 for t in self.turns if t.gain_gate_skipped)),
			"gain_gate_skip_rate": float(
				sum(1 for t in self.turns if t.gain_gate_skipped) / max(1, len(self.turns))
			),
			# 2026-09-15：两道闸**必须分开报**——语义完全不同：
			#   trigger  = C0 未过生产水位（0.8×context_limit）⇒ **根本没尝试压缩**；
			#   gain_gate= 压了但区域太小、压了反而更大 ⇒ 尝试了但拒绝。
			# 混报会把"生产不会压缩的回合"读成"压缩了但收益不够"，正是 §13.8
			# 记的口径事故。trigger_ratio=0（闸门关闭）时该率恒为 0。
			"trigger_skipped": int(sum(1 for t in self.turns if t.trigger_skipped)),
			"trigger_skip_rate": float(
				sum(1 for t in self.turns if t.trigger_skipped) / max(1, len(self.turns))
			),
			# ── adopted 口径计数（legacy 档下 active == 压过的回合）──────────
			# 与 `trigger_skipped` 一起读：adopted 档里「未过闸」**不等于**「没压缩」，
			# 只等于「本回合没有折叠」——投影仍是上一次折叠留下的紧凑态。
			"wsc_active_turns": len(active_turns),
			"wsc_active_rate": float(len(active_turns) / max(1, len(self.turns))),
			"compaction_events": len(event_turns),
			"compaction_event_rate": float(len(event_turns) / max(1, len(self.turns))),
			# 紧凑态回合上的压缩率：adopted 档下这才是「压缩率」的可比群体
			# （全回合口径会被"从未压过"的原文回合稀释成 0，见 §14.6）。
			"reduction_vs_base_active_only": _stat(
				[
					1 - float(t.wsc_tokens) / float(t.base_tokens)
					for t in active_turns
					if t.base_tokens > 0
				]
			),
			# ── 同一批回合上的成本比（「WSC 能否替换 C2」的准入判据）──────────
			# 只在**两臂都可比**的回合上求和：v61 基线不可得的回合不进分母。
			# 2026-09-16：此前该比值由 `_r7_ab3_strict2.py` 等一次性脚本现算，
			# 现固化进报告，避免"每个结论配一个脚本、脚本口径还各不相同"。
			"cost_ratio_wsc_v61_active": _ratio(
				sum(float(t.wsc_cost) for t in active_turns if t.v61_tokens > 0),
				sum(float(t.v61_cost) for t in active_turns if t.v61_tokens > 0),
			),
			"cost_ratio_wsc_v61_active_n": int(
				sum(1 for t in active_turns if t.v61_tokens > 0)
			),
			"hit_rate_wsc": _stat([float(t.wsc_hit) for t in cmp_turns]),
			"hit_rate_v61": _stat([float(t.v61_hit) for t in cmp_turns]),
			# 跳首回合口径：只在「同一会话内有上一轮投影可比」的回合上算
			"hit_rate_wsc_steady": _stat([float(t.wsc_hit) for t in steady]),
			"hit_rate_v61_steady": _stat([float(t.v61_hit) for t in steady]),
			# ── 命中率**主指标**（2026-09-15，用户裁定）─────────────────────
			# 三条纪律，都是踩过的坑：
			#  1) **必须报 mean**：`_stat` 同时给出 mean/median，而 median 在含冷启动的
			#     分布里恒为 0（本语料实测 median=0 而 mean=0.12~0.22）——把它当主值会
			#     把"命中率崩了"和"样本里一半是首轮"混为一谈（第七轮真的这么误读过）。
			#  2) **主口径 = steady**（剔掉每会话首轮：首轮没有 x_prev，命中必为 0，
			#     是定义性稀释而非性能信号）。
			#  3) 含冷启动的 `hit_rate_*` 保留作对照，不删——它才是"真实平均"。
			"hit_rate_primary_scope": "steady(mean)",
			"hit_rate_wsc_mean": _mean([float(t.wsc_hit) for t in cmp_turns]),
			"hit_rate_v61_mean": _mean([float(t.v61_hit) for t in cmp_turns]),
			"hit_rate_wsc_steady_mean": _mean([float(t.wsc_hit) for t in steady]),
			"hit_rate_v61_steady_mean": _mean([float(t.v61_hit) for t in steady]),
			"hit_rate_steady_delta": _mean([float(t.wsc_hit) for t in steady])
			- _mean([float(t.v61_hit) for t in steady]),
			"cost_wsc_total": float(sum(float(t.wsc_cost) for t in cmp_turns)),
			"cost_v61_total": float(sum(float(t.v61_cost) for t in cmp_turns)),
			"cost_wsc_steady": float(sum(float(t.wsc_cost) for t in steady)),
			"cost_v61_steady": float(sum(float(t.v61_cost) for t in steady)),
			"compared_turns": len(cmp_turns),
			"steady_turns": len(steady),
			"baseline_missing_turns": len(self.turns) - len(cmp_turns),
			"rebuild_events": int(sum(1 for t in self.turns if t.rebuilt)),
			"rebuild_rate": float(
				sum(1 for t in self.turns if t.rebuilt) / max(1, len(self.turns))
			),
			"lcp_prev_tokens": _stat(self._vals("lcp_prev")),
			"latency_ms": _stat(self._vals("latency_ms")),
			"stage_latency_ms": stage_latency,
			"cards_per_turn": _stat(self._vals("cards")),
			"pruned_per_turn": _stat(self._vals("pruned")),
			"needle_survival": needles,
			"needle_survival_pooled": needles_pooled,
			"recoverability": {
				"pruned_nodes": pruned,
				"bound_nodes": bound,
				"coverage": (bound / pruned) if pruned else 1.0,
				"roundtrip_checked": checked,
				"roundtrip_lossless": lossless,
				"lossless_rate": (lossless / checked) if checked else 1.0,
			},
			"llm_calls": 0,
			"churn": churn,
			"churn_warn_turns": int(sum(1 for t in self.turns if t.churn_warns)),
			# 规则 8：日志布局的代价与收益
			"journal": {
				"turns": float(sum(1 for t in self.turns if t.req_total or t.journal_appends)),
				"appends_total": int(sum(int(t.journal_appends) for t in self.turns)),
				"refroze_turns": int(sum(1 for t in self.turns if t.journal_refroze)),
				"refroze_rate": float(
					sum(1 for t in self.turns if t.journal_refroze)
					/ max(1, sum(1 for t in self.turns if not t.gain_gate_skipped))
				),
				"zero_loss_turns": int(
					sum(
						1
						for t in self.turns
						if not t.gain_gate_skipped and not t.journal_refroze
					)
				),
			},
			# 信息留存审计（规则 1 空洞）：区域内用户原话的渲染覆盖
			"user_requests": {
				"total": int(sum(int(t.req_total) for t in self.turns)),
				"rendered": int(sum(int(t.req_rendered) for t in self.turns)),
				"coverage": (
					sum(int(t.req_rendered) for t in self.turns)
					/ max(1, sum(int(t.req_total) for t in self.turns))
				),
			},
		}


def aggregate(records: Sequence[SessionRecord], *, label: str, level: str, mode: str) -> Aggregate:
	agg = Aggregate(label=label, level=level, mode=mode)
	for r in records:
		if r.error:
			agg.errors[r.error] = agg.errors.get(r.error, 0) + 1
			agg.n_skipped += 1
			continue
		if r.degraded:
			agg.errors[r.degraded] = agg.errors.get(r.degraded, 0) + 1
		agg.n_sessions += 1
		agg.n_turns += len(r.turns)
		agg.turns.extend(r.turns)
	return agg


#: 会话长度分档（按被压缩窗口的消息数）——WSC 的收益只在长会话上才是主战场，
#: 混在一起统计会被「两轮就结束」的短会话稀释成看不出结论的平均值。
COHORTS: tuple[tuple[str, int, int], ...] = (
	("短会话(<30 消息)", 0, 30),
	("中会话(30-99)", 30, 100),
	("长会话(>=100)", 100, 1 << 30),
)


def cohort_of(n_messages: int) -> str:
	for name, lo, hi in COHORTS:
		if lo <= n_messages < hi:
			return name
	return COHORTS[-1][0]


def cohort_aggregates(
	records: Sequence[SessionRecord], *, level: str, mode: str
) -> list[Aggregate]:
	out: list[Aggregate] = []
	for name, _lo, _hi in COHORTS:
		turns = [
			t
			for r in records
			if not r.error
			for t in r.turns
			if cohort_of(t.n_messages) == name
		]
		agg = Aggregate(label=f"{mode} / {name}", level=level, mode=mode)
		agg.turns = turns
		agg.n_turns = len(turns)
		agg.n_sessions = len({t.session for t in turns})
		out.append(agg)
	return out


# ---------------------------------------------------------------------------
# 口径声明（报数前必读）
# ---------------------------------------------------------------------------

CAVEATS = [
	"两侧 token 计量走同一套序列化（memory.simulator.projection.emit_segment），"
	"但 WSC 的 wsc_tokens = 热层 L + 未触碰尾部的 JSON 字符数，尾部那部分与 "
	"v61_tokens 的尾部口径存在系统性差异，故 reduction_vs_v61 应看趋势而非绝对值。",
	"hit_rate 来自 memory.simulator 的 ρ̂(C) 模型，不是线上观测到的 "
	"prompt_cache_hit_tokens。模型精度见 memory/simulator/calibration.py 的标定报告。"
	"其形式为 H = ρ̂·g·⌊LCP/g⌋、hit_rate = H/L（g=64 块对齐，ρ̂(age=0)=1.0）"
	"——即「量化后的公共前缀 token / 整段投影 token」，这正是 DeepSeek "
	"prompt_cache_hit_tokens / prompt_tokens 的定义，不是被换个名字的派生量。",
	"⚠ **命中率对抽样口径极度敏感**：报告的 hit_rate 由相邻两个**被采样回合**之间的 "
	"LCP 推得。--sample-turns=N 会把 x_prev 拉到 N 轮之前，等价于每轮冷启动。"
	"实测 199 回合会话：逐回合 append_only 0.731 / closure 0.116，"
	"而 sample-turns=12 报出 0.051 / 0.016（差 7–14 倍）。**默认必须 sample_turns=0**；"
	"任何带抽样的数字都要在表头标注。v6.1 基线侧不受影响（逐回合内部重放）。",
	"任务成功率变化、重复错误率降低 需要真实任务 A/B 才能测量，本报告不出这些数字。"
	"failure_site 针存活率只是「失败现场是否还在热层」的代理指标，不等于重复犯错率。",
	"回放按会话 JSONL 逐用户回合重演，不含工具副作用、不含真实 KV 缓存 TTL 分布；"
	"age_seconds 固定为 0（连续请求）。",
	"keep_tail_cut 用生产链 engine.compact 的同名函数，故两侧尾部保护区完全一致。",
	"WSC 自身零 LLM 调用由 python/tests/synaptic/test_isolation.py 静态执法（AST 扫 import），"
	"不依赖运行期计数器。",
	"本轮为纯离线旁路，未接生产链任何开关；上线形态与接线点见 docs/synaptic-compression.md。",
]

DEVIATIONS = [
	"剪枝卡 id 用根节点下标（``branch://B37``）而非设计文档的流水号（``B12``）：流水号会随"
	"区域增长整体位移，导致 append_only 模式下每轮都判定「内容变了」而被迫整层重建。",
	"[DECISIONS] 与 [PRUNED] 不再重复同一条卡：带错误签名的卡进 DECISIONS（含句柄），"
	"其余进 PRUNED。设计文档的示例里同一条分支在两段各出现一次，纯属重复计费。",
	"[NEXT] 段默认**关闭**：它内容上是事实，但在注意力里的位置与语气会被读成导演，"
	"违反 XEYO 引擎铁律（注意力里只出现信息，不出现导演）。开启需显式 "
	"``WscParams(include_next=True)`` 并在报告里标注。",
	"主链里 token ≤ inline_max_tokens(48) 的小节点直接内联原文，不做骨架化——"
	"为省几十 token 而逼模型发一次 expand 往返，净亏。",
	"关键信息针、可恢复性、前缀连续性三个指标是设计文档里没有的，为把「98–99.5% 保留」"
	"这类自述变成可复核量而新增。",
	"**规则 1（修正，非变体）**：后继用户消息（原 [PIN] 的「指令」段）不再进热层。"
	"依据是探针实测：它逐轮变动率 93%，且内容就是最近 N 条用户消息——未被保护的尾部"
	"本来就逐字带着它们。放进 PIN 既重复计费，又让其后数千 token 的稳定内容每轮失去前缀。",
	"**规则 1 的补丁（[REQUESTS]）**：规则 1 落地后探针发现它开了信息空洞——"
	"``render_main`` 跳过 ``pin_nodes``，而 ``pin_nodes`` 含**全部**实质用户节点，"
	"故区域内（尾部之外的）用户原话一度完全没有渲染通道；又因为是 pin 不被剪，"
	"连 expand 句柄都没有 = 不可恢复。聚合签名：user 针存活率 94.6% → 71.0%。"
	"修法是**收窄而非回退**：只丢尾部确实逐字携带的那几条，区域内用户原话进 [REQUESTS]"
	"（按 idx 升序 ⇒ 段内只追加），每条附真 ``node://`` 句柄保证截断可无损拉回。",
	"**规则 2**：[PIN] 拆成 [CONSTRAINTS]/[UNRESOLVED]/[TODO]，各段按「前缀失稳率」"
	"动态排序（``stable_prefix_ordering`` 默认开，置 False 回退固定先验序用于 A/B）。"
	"排序带滞回余量与换序驻留期——次序抖动本身比内容变化更伤前缀。",
	"**规则 8（日志布局，默认开）**：热层不再是「分段仪表盘」，而是单一 append-only 日志："
	"所有条目按首次发射顺序追加、永不改写、永不重排，每行自带段头。"
	"根因是 KV 前缀缓存要求**连续**前缀匹配——分段布局下只要还有一个「会长」的段排在"
	"别的段之前，一次追加就斩断其后全部内容的缓存。实测 199 回合会话 closure："
	"189/199 回合是「串中改写」，中位 LCP 只剩 324 token；首个失配点分布 [MAIN] 102 / "
	"[WORKING SET] 49 / [UNRESOLVED] 24 / [DECISIONS] 20 / [PRUNED] 4。"
	"排序只能缓解（总有第二名会长的段），日志布局让它结构上不可能。"
	"代价是日志变胖，用 ``journal_growth_tokens`` 触发逻辑换头；换头只追加新头与旧头句柄，"
	"不改写已发前缀，故不把逻辑换头计为一次 KV 前缀 miss。"
	"关掉开关（``journal_layout=False``）即回到分段布局，用于 A/B。",
	"**自检口径修正（规则 3 的补丁）**：段统计改为落在**最终投影文本**上。"
	"旧实现在模式分支之前统计，append_only 报出的 churn 表与 closure 逐字相同，"
	"而它的最终投影是字节冻结的——自相矛盾。修好后 append_only 的段前缀失稳率恒为 0。",
	"**hot_share_of_base 口径修正**：分母从整段 base_tokens 改为同一回合的 "
	"region_raw_tokens（被压缩区域的原始 token）。用整段作分母会把未压缩尾部也算进来，"
	"并在收益门跳过一个回合时与压缩子集错行；两者都属于分子分母不同源。",
	"**热层双预算（规则 8 的补丁）**：hot_budget_tokens 拆成 "
	"fixed_segment_budget_tokens + main_segment_budget_tokens，Medium+ 为 1800+1200。"
	"REQUESTS 固定在 1200 内按 full→dedup→dedup_short→handles 降级；"
	"若固定段和主链仍超限，审计字段 fixed_overflow_tokens / main_overflow_tokens "
	"如实记账，不伪装成未超预算。",
	"**固定段硬闸**：当固定段预算连 dedup@80 都装不下时，``[REQUESTS]`` 只尝试句柄；"
	"连句柄也装不下则记录 ``request_mode=dropped`` 并关闭该段，``[PATHS]`` 同样受子段额度限制。",
	"**path 针口径放宽**：path/path_recent 的存活判定改为路径 basename 级宽松匹配，"
	"并与 working_set/recent_paths 共用排序来源；这只改变「是否可见」的判定，"
	"不会凭空恢复冷层里已经剪掉的路径。",
	"**[REQUESTS] 覆盖率的分子分母必须同源**：total 用 seeds.user_nodes 的节点数，"
	"rendered 必须解析 node://i,j,... 组句柄后按节点集合计数，不能数渲染行数；"
	"去重后的行数少于节点数是正常现象。needle_survival.user 是文本针去重口径，"
	"与 user_requests.coverage 的节点级口径不可互相换算。",
]


def build_report(
	aggregates: Sequence[Aggregate],
	*,
	corpus: str,
	n_files: int,
	determinism: dict[str, Any] | None = None,
	cohorts: Sequence[Aggregate] = (),
	mode_notes: dict[str, Any] | None = None,
	sampling: dict[str, Any] | None = None,
) -> dict[str, Any]:
	return {
		"kind": "wsc-offline-report",
		"corpus": corpus,
		"n_files": n_files,
		"sampling": sampling or {"sample_turns": 0, "decimated": False},
		"results": [a.summary() for a in aggregates],
		"cohorts": [a.summary() for a in cohorts],
		"mode_notes": mode_notes or {},
		"determinism": determinism or {},
		"static_checks": {"forbidden_imports": assert_no_llm_dependency()},
		"caveats": CAVEATS,
		"deviations": DEVIATIONS,
	}


def render_markdown(rep: dict[str, Any]) -> str:
	L: list[str] = []
	L.append("# 突触压缩（WSC）离线回放报告")
	L.append("")
	L.append(f"- 语料：`{rep['corpus']}`（{rep['n_files']} 个会话文件）")
	L.append("- 形态：纯离线旁路，未接生产链任何开关")
	sp = rep.get("sampling") or {}
	if sp.get("decimated"):
		L.append(
			f"- ⚠ **抽样口径**：sample_turns={sp.get('sample_turns')}"
			"（命中率被系统性压低，不可与逐回合结果比较，见 CAVEATS）"
		)
	else:
		L.append("- 回合口径：逐用户回合（sample_turns=0，无抽样）")
	L.append("")
	for r in rep["results"]:
		if r.get("turns", 0) == 0:
			L.append(f"## {r.get('label')} — 无可比回合")
			L.append("")
			continue
		L.append(f"## {r.get('label')}（level={r['level']}, mode={r['mode']}）")
		L.append("")
		L.append(f"- 会话 {r['sessions']} / 回合 {r['turns']}（跳过 {r['skipped']}）")
		L.append(
			f"- 收益门拒绝压缩 {r.get('gain_gate_skipped', 0)} 回合"
			f"（{r.get('gain_gate_skip_rate', 0):.1%}，区域太小、压了反而更大）"
		)
		L.append(
			f"- 触发闸未过水位 {r.get('trigger_skipped', 0)} 回合"
			f"（{r.get('trigger_skip_rate', 0):.1%}，本回合**根本没尝试压缩**）"
		)
		L.append(
			f"- 未压缩基线 token median {r['base_tokens']['median']:.0f}"
		)
		L.append(
			f"- 压缩率（全回合，含收益门拒绝）：mean {r['reduction_vs_base']['mean']:.1%} / "
			f"median {r['reduction_vs_base']['median']:.1%} / p10 {r['reduction_vs_base']['p10']:.1%}"
		)
		rc_all = r.get("reduction_vs_base_compressed_only", {})
		if rc_all.get("n"):
			L.append(
				f"- 压缩率（仅实际压缩的回合）：mean {rc_all['mean']:.1%} / "
				f"median {rc_all['median']:.1%} / p10 {rc_all['p10']:.1%} / p90 {rc_all['p90']:.1%}"
			)
		if r.get("compared_turns"):
			L.append(
				f"- 相对 XEYO v6.1：mean {r['reduction_vs_v61']['mean']:.1%} / "
				f"median {r['reduction_vs_v61']['median']:.1%}"
				f"（可比回合 {r['compared_turns']}，基线缺失 {r['baseline_missing_turns']}）"
			)
		L.append(
			f"- 热层 token：median {r['hot_tokens']['median']:.0f} / p90 {r['hot_tokens']['p90']:.0f}"
		)
		if r.get("compared_turns"):
			# 主指标先行（2026-09-15，用户裁定）：steady + mean。
			# 含冷启动口径退到下一行作对照——它的 median 恒为 0（首轮稀释），
			# 拿 median 当主值会把"命中率崩了"和"样本一半是首轮"混为一谈。
			L.append(
				f"- **命中率（主口径：跳每会话首回合，mean）**："
				f"WSC {r.get('hit_rate_wsc_steady_mean', 0):.3f} vs XEYO v6.1 "
				f"{r.get('hit_rate_v61_steady_mean', 0):.3f}"
				f"（Δ {r.get('hit_rate_steady_delta', 0):+.3f}，回合 {r.get('steady_turns', 0)}）"
			)
			L.append(
				f"- 命中率（含冷启动，可比回合 {r['compared_turns']}）："
				f"WSC {r['hit_rate_wsc']['mean']:.3f} vs XEYO v6.1 {r['hit_rate_v61']['mean']:.3f}"
			)
			steady = r.get("hit_rate_wsc_steady") or {}
			if steady.get("n"):
				L.append(
					f"- 命中率（**跳各会话首个可比回合**，steady {r['steady_turns']} 回合）："
					f"WSC {steady['mean']:.3f} vs XEYO v6.1 {r['hit_rate_v61_steady']['mean']:.3f}"
					f"（median {steady['median']:.3f} / p90 {steady['p90']:.3f}）"
					" ← 冷启动会稀释均值，报绝对水平用这一行"
				)
			L.append(
				f"- 输入成本合计（可比回合）：WSC ¥{r['cost_wsc_total']:.4f} vs v6.1 ¥{r['cost_v61_total']:.4f}"
				f"  |  steady：WSC ¥{r.get('cost_wsc_steady', 0):.4f} vs v6.1 ¥{r.get('cost_v61_steady', 0):.4f}"
			)
		L.append(
			f"- 整层重建：{r['rebuild_events']} 次 / 重建率 {r['rebuild_rate']:.1%}"
		)
		jm = r.get("journal") or {}
		if jm.get("appends_total"):
			L.append(
				f"- 日志布局：新增条目 {jm['appends_total']} 条 / 重冻结 "
				f"{jm['refroze_turns']} 次（占压缩回合 {jm['refroze_rate']:.1%}）/ "
				f"零损失回合 {jm['zero_loss_turns']}"
			)
		ur = r.get("user_requests") or {}
		if ur.get("total"):
			L.append(
				f"- 区域内用户原话渲染覆盖：{ur['rendered']}/{ur['total']}"
				f"（{ur['coverage']:.1%}，规则 1 空洞的外部审计量）"
			)
		L.append(
			f"- 压缩延迟：median {r['latency_ms']['median']:.2f} ms / p95 {r['latency_ms']['p95']:.2f} ms"
		)
		stages = r.get("stage_latency_ms") or {}
		if stages:
			top = sorted(
				stages.items(), key=lambda item: item[1].get("p95", 0.0), reverse=True
			)[:3]
			L.append(
				"- 阶段 p95（前三）："
				+ "；".join(f"{name} {stats['p95']:.2f} ms" for name, stats in top)
			)
		L.append(f"- LLM 调用：{r['llm_calls']}")
		L.append("")
		L.append("### 关键信息针存活率（热层内命中）")
		L.append("")
		L.append("| 类别 | 覆盖回合 | 均值 | 最低 | p10 |")
		L.append("|---|---:|---:|---:|---:|")
		for cat, v in r.get("needle_survival", {}).items():
			L.append(
				f"| {cat} | {v['turns']:.0f} | {v['mean_rate']:.1%} | {v['min_rate']:.1%} | {v['p10']:.1%} |"
			)
		L.append("")
		rc = r["recoverability"]
		L.append("### 可恢复性")
		L.append("")
		L.append(
			f"- 被剪节点 {rc['pruned_nodes']}，其中有句柄 {rc['bound_nodes']}（覆盖率 {rc['coverage']:.2%}）"
		)
		L.append(
			f"- expand 往返逐字节比对：{rc['roundtrip_lossless']}/{rc['roundtrip_checked']} 无损（{rc['lossless_rate']:.2%}）"
		)
		L.append("")
		ch = r.get("churn", {})
		if ch:
			L.append("### 段落逐轮变动率自检（规则 2）")
			L.append("")
			L.append("> 「变动率」超阈即告警；排序用的是「前缀失稳率」——只追加的段落变动率高但前缀稳，")
			L.append("> 把这类段落排到后面会适得其反。")
			L.append("")
			L.append("| 段落 | 观测回合 | 变动率 mean | 变动率 max | 前缀失稳率 mean |")
			L.append("|---|---:|---:|---:|---:|")
			for h, v in ch.items():
				L.append(
					f"| `{h}` | {v['turns']:.0f} | {v['change_mean']:.1%} | "
					f"{v['change_max']:.1%} | {v['front_break_mean']:.1%} |"
				)
			L.append("")
			L.append(
				f"- 触发变动率 > 50% 告警的回合：{r.get('churn_warn_turns', 0)} / {r['turns']}"
			)
			L.append("")
	if rep.get("mode_notes"):
		L.append("## 组装模式对照（closure vs append_only）")
		L.append("")
		L.append("| 指标 | " + " | ".join(rep["mode_notes"].keys()) + " |")
		L.append("|---|" + "---:|" * len(rep["mode_notes"]))
		for metric, label in (
			("turns", "回合数"),
			("reduction_vs_base", "压缩率均值(全回合)"),
			("reduction_vs_base_compressed_only", "压缩率均值(仅压缩回合)"),
			("hot_tokens", "热层 token 中位数"),
			("rebuild_rate", "整层重建率"),
			("gain_gate_skip_rate", "收益门拒绝率"),
			("trigger_skip_rate", "触发闸跳过率"),
			("hit_rate_wsc", "命中率均值"),
			("latency_ms", "延迟中位数(ms)"),
		):
			cells = []
			for v in rep["mode_notes"].values():
				if metric in ("reduction_vs_base", "reduction_vs_base_compressed_only", "hit_rate_wsc"):
					cells.append(f"{v.get(metric, {}).get('mean', 0):.4f}")
				elif metric in ("hot_tokens", "latency_ms"):
					cells.append(f"{v.get(metric, {}).get('median', 0):.1f}")
				elif metric in ("rebuild_rate", "gain_gate_skip_rate", "trigger_skip_rate"):
					cells.append(f"{v.get(metric, 0):.1%}")
				else:
					cells.append(str(v.get(metric, 0)))
			L.append(f"| {label} | " + " | ".join(cells) + " |")
		L.append("")
	if rep.get("cohorts"):
		L.append("## 按会话长度分 cohort")
		L.append("")
		L.append(
			"| cohort | 会话 | 回合 | 压缩率均值 | 压缩率中位 | 收益门拒绝 | 触发闸跳过 | 热层token中位 | 重建率 | 近期路径针 | 错误针 |"
		)
		L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
		for c in rep["cohorts"]:
			if not c.get("turns"):
				continue
			L.append(
				f"| {c['label']} | {c['sessions']} | {c['turns']} | "
				f"{c['reduction_vs_base']['mean']:.1%} | {c['reduction_vs_base']['median']:.1%} | "
				f"{c.get('gain_gate_skip_rate', 0):.1%} | "
				f"{c.get('trigger_skip_rate', 0):.1%} | "
				f"{c['hot_tokens']['median']:.0f} | {c['rebuild_rate']:.1%} | "
				f"{c.get('needle_survival', {}).get('path_recent', {}).get('mean_rate', 0):.1%} | "
				f"{c.get('needle_survival', {}).get('error_sig', {}).get('mean_rate', 0):.1%} |"
			)
		L.append("")
	if rep.get("determinism"):
		L.append("## 确定性")
		L.append("")
		for k, v in rep["determinism"].items():
			L.append(f"- {k}: {v}")
		L.append("")
	L.append("## 口径声明（报数前必读）")
	L.append("")
	for c in rep["caveats"]:
		L.append(f"- {c}")
	L.append("")
	L.append("## 与设计文档的偏离（已在代码注释中同步）")
	L.append("")
	for d in rep["deviations"]:
		L.append(f"- {d}")
	L.append("")
	if rep.get("static_checks", {}).get("forbidden_imports"):
		L.append("## 静态检查失败")
		L.append("")
		for p in rep["static_checks"]["forbidden_imports"]:
			L.append(f"- {p}")
		L.append("")
	return "\n".join(L)


def write_report(rep: dict[str, Any], outdir: Path) -> tuple[Path, Path]:
	outdir.mkdir(parents=True, exist_ok=True)
	jp = outdir / "wsc_offline_report.json"
	mp = outdir / "wsc_offline_report.md"
	jp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
	mp.write_text(render_markdown(rep), encoding="utf-8")
	return jp, mp
