"""突触压缩（WSC）核心数据结构。

全部为不可变 dataclass + 显式字段，方便确定性断言与快照比对。
本模块不 import 任何 XEYO 生产链模块（engine / memory / server），
只依赖标准库——保证旁路形态可整目录删除。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# 节点类型（kind）
KIND_USER = "user_text"
KIND_ASST_TEXT = "assistant_text"
KIND_TOOL_USE = "tool_use"
KIND_TOOL_RESULT = "tool_result"
KIND_OTHER = "other"

# 边的类型（关系）
EDGE_SEQ = "seq"  # 时序：i -> i+1
EDGE_USE = "use"  # 因果：assistant(tool_use) -> tool_result（语法边）
EDGE_FILE = "file"  # 共访文件：同一路径的前后访问
EDGE_ERR = "err"  # 错误归因：失败结果 -> 后续触碰同一文件的调用

# 权重信号名（五维，见 docs/synaptic-compression.md §评分）
W_GOAL = "goal_rel"
W_UNRESOLVED = "unresolved"
W_CONSTRAINT = "constraint"
W_RECENCY = "recency"
W_REPLAY = "replay_cost"

Level = Literal["Micro", "Light", "Medium", "Medium+", "Hard"]
LEVELS: tuple[str, ...] = ("Micro", "Light", "Medium", "Medium+", "Hard")

# 压缩级别 -> 触发水位（占上下文窗口比例）
LEVEL_WATERMARK: dict[str, float] = {
	"Micro": 0.60,
	"Light": 0.75,
	"Medium": 0.85,
	"Medium+": 0.82,
	"Hard": 0.95,
}

# 组装模式
MODE_APPEND_ONLY = "append_only"  # 稳定区字节冻结，只尾部追加（KV 前缀友好）
MODE_CLOSURE = "closure"  # 全量重排（最大压缩，付费一次前缀 miss）


@dataclass(frozen=True)
class Node:
	"""证据 DAG 节点 = 一条消息。

	文本按消息粒度持有（与投影/KV 前缀的改写单位一致）；原子级细化留给
	``atoms`` 字段（可选），供剪枝卡生成结论时使用。
	"""

	idx: int
	kind: str
	role: str
	text: str
	tokens: int
	tool_name: str = ""
	tool_use_id: str = ""
	is_error: bool = False
	is_write: bool = False  # 会改变文件状态的工具（Write/Edit/NotebookEdit）
	read_only: bool = False  # 只读且可安全重放（Read/Grep/Glob 及只读 Bash）
	ts: float = 0.0
	refs: tuple[str, ...] = ()  # 触碰的文件路径（归一化后）
	symbols: tuple[str, ...] = ()  # 触碰的符号（用于语义邻接的弱启发式）
	error_sig: str = ""  # 错误签名（异常类 / 首行关键片段）
	replay_cmd: str = ""  # 可重放命令（只读工具才有）
	weights: dict[str, float] = field(default_factory=dict)

	def weight(self, name: str) -> float:
		return float(self.weights.get(name, 0.0))


@dataclass(frozen=True)
class Edge:
	src: int
	dst: int
	kind: str
	weight: float = 1.0


@dataclass(frozen=True)
class Pin:
	"""强制 PIN 项：永不压缩，直接进热层。"""

	key: str
	label: str
	text: str
	nodes: tuple[int, ...] = ()


@dataclass(frozen=True)
class FileState:
	"""文件状态表条目（规则 5）。"""

	path: str
	observed_hash: str  # 最后一次有效 read 观测到的内容 hash
	last_read_idx: int
	read_ranges: tuple[tuple[int, int], ...]  # 已读区间（1-based 行号，闭区间）
	stale: bool = False  # read 之后被写工具改过
	stale_at: int = -1
	diff_summary: str = ""  # read 之后的变更摘要（写工具的 input 片段）
	related_errors: tuple[str, ...] = ()
	disk_hash: str = ""  # 若该路径当前在磁盘上，附真实 hash（可选增强）

	@property
	def is_partial(self) -> bool:
		return bool(self.read_ranges)


@dataclass(frozen=True)
class PruneCard:
	"""剪枝卡（规则 4）：被剪分支的结论化索引 + 可展开句柄。"""

	card_id: str
	conclusion: str
	files: tuple[str, ...] = ()
	error_sig: str = ""
	replay: str = ""
	nodes: tuple[int, ...] = ()
	tokens: int = 0

	@property
	def handle(self) -> str:
		return f"branch://{self.card_id}"


@dataclass(frozen=True)
class ColdRef:
	"""冷层句柄记录：可无损拉回原始节点文本。"""

	handle: str
	nodes: tuple[int, ...]


@dataclass(frozen=True)
class HotLayer:
	"""压缩后的热层（送模型的投影文本 + 结构化元数据）。"""

	text: str
	tokens: int
	kept_nodes: tuple[int, ...]
	pruned_nodes: tuple[int, ...]
	cards: tuple[PruneCard, ...]
	file_states: tuple[FileState, ...]
	pins: tuple[Pin, ...]
	level: str
	mode: str


@dataclass(frozen=True)
class WscParams:
	"""算法参数（全部显式，禁止隐式默认漂移）。"""

	level: str = "Medium+"
	mode: str = MODE_CLOSURE
	hot_budget_tokens: int = 3_000
	# 热层总预算拆成两个显式闸门：固定段（PIN / WORKING SET / REQUESTS / NEXT）
	# 与主链预算（MAIN / DECISIONS / PRUNED）。二者合计必须等于 hot_budget_tokens。
	# 旧实现只闸 kept 的选择，REQUESTS 等段在预算外生长，长会话会系统性超预算。
	fixed_segment_budget_tokens: int = 1_200
	main_segment_budget_tokens: int = 1_800
	# 反向闭包跳数：Medium+ 用 2 跳（PIN 集 2 跳内），Hard 收紧到 1 跳。
	closure_hops: int = 2
	# 五维权重
	w_goal: float = 1.0
	w_unresolved: float = 0.9
	w_constraint: float = 1.0
	w_recency: float = 0.35
	w_replay: float = 0.25
	# 剪枝卡上限（超出则合并最弱卡）
	max_cards: int = 24
	# 每条卡结论的最大字符数
	card_conclusion_chars: int = 220
	# append_only 模式下稳定区允许的追加预算（token），超出则整层重建
	append_budget_tokens: int = 1_200
	min_gain_tokens: int = 200  # 收益不足不压缩
	# 小节点直接内联原文的阈值（省一次 expand 往返）
	inline_max_tokens: int = 48
	# [NEXT] 段：设计文档里有它，但它属于「导演型文本」，与 XEYO 引擎铁律
	# （注意力里只出现信息，不出现导演）冲突。默认关；开启后报告须标注。
	include_next: bool = False
	# 规则 2：热层段落按「前缀失稳率」动态排序（最稳定的在最前）。
	# 默认开；置 False 回退固定先验序（_SECTION_PRIOR），用于 A/B 对照。
	stable_prefix_ordering: bool = True
	# 排序滞回：相邻两段的前缀失稳率差距超过该值才交换次序。
	# 次序抖动本身比内容变化更伤前缀，所以宁可少排也不抖。
	churn_margin: float = 0.15
	# 换序驻留期：一次换序后，至少再稳定这么多轮才允许下一次换序。
	# 实测（199 回合会话）无驻留时会在两个排列间以近乎 50/50 抖动，每次抖动即一次前缀失效。
	churn_dwell: int = 4
	# 自检：某段逐轮变动率超过该值即告警（规则 2 的自检项）。
	churn_warn_rate: float = 0.5
	# 自检告警的最小观测轮数（样本太少不报，避免前几轮噪声刷屏）。
	churn_min_obs: int = 3
	# 规则 8（日志布局）：热层不做「分段仪表盘」而做**单一 append-only 日志**。
	#
	# 根因：KV 前缀缓存要求**连续**前缀匹配。只要某个段落在投影中位于其他段之前、
	# 且它本轮变长了，其后所有段落的字节即使完全没变，也全部失去缓存。实测
	# 199 回合会话：closure 189/199 回合是「串中改写」而非纯追加，中位 LCP 只剩
	# 324 token（= 稳定段头）。任何「按变动率排序」都只能缓解，不能根治——
	# 只要还有第二个会长的段，它就一定在某个时刻排在别人前面。
	#
	# 日志布局把它变成结构上不可能：所有条目按**首次发射顺序**追加，永不改写、
	# 永不重排 ⇒ 整段投影逐轮单调 ⇒ LCP = 上一轮全长。代价是日志会变胖，
	# 用「重冻结」把它压回紧凑渲染（一次前缀 miss，摊到多轮）。
	journal_layout: bool = True
	# 重冻结阈值：距上次冻结累计追加了多少 token 就重冻结一次。
	# 太小 → 频繁重整（miss 变多）；太大 → 日志臃肿（token 变多）。
	#
	# **这是「压缩率 ↔ 命中率」的显式旋钮，不是可以随便取的常数。** 实测（199 回合会话，
	# 单会话扫描，成本指数 ∝ H+30U，DeepSeek miss/hit 价差 ≈30×）：
	#
	#   growth   命中率   每回合投影   ΣU(未命中)   重冻结率   成本指数
	#   900      0.514     7 478 tok    704 760     31.5%     21.93 M
	#   1 800    0.601     7 814 tok    594 543     16.5%     18.80 M
	#   3 000    0.673     8 449 tok    517 481      9.0%     16.70 M
	#   6 000    0.734     9 697 tok    464 425      4.5%     15.41 M
	#  12 000    0.797    11 990 tok    415 875      2.0%     14.46 M  ← 成本最优
	#  24 000    0.835    16 344 tok    407 244      1.0%     15.08 M
	#
	# 结论：成本最优点在 12 000（≈4× 热层预算），但那里投影比分段布局大 1.8 倍——
	# 「省钱」与「少占窗口」在命中率轴上是对立目标。默认取 **2× 热层预算**
	# （见 ``for_level``），在成本曲线的平坦段而非极值点上；要追极限成本再显式放大。
	journal_growth_tokens: int = 6_000
	# [REQUESTS] 每条用户原话内联的字符上限（超出附 expand(node://<idx>) 句柄取全文）。
	request_excerpt_chars: int = 320

	def for_level(self, level: str) -> "WscParams":
		"""按级别派生参数（水位 → 预算/跳数），保持其它权重不变。"""
		if level not in LEVELS:
			level = "Medium+"
		preset = {
			"Micro": dict(hot_budget_tokens=8_000, closure_hops=1, max_cards=8),
			"Light": dict(hot_budget_tokens=5_500, closure_hops=1, max_cards=14),
			"Medium": dict(hot_budget_tokens=4_000, closure_hops=2, max_cards=20),
			"Medium+": dict(hot_budget_tokens=3_000, closure_hops=2, max_cards=24),
			"Hard": dict(hot_budget_tokens=1_800, closure_hops=1, max_cards=32),
		}[level]
		# 固定段上限默认 1200；低档总预算不足 1200 时按总预算截断，主链拿剩余额度。
		# 这样 fixed + main 恒等于 hot_budget_tokens，不留下第三个未入账水位。
		hot_budget = int(preset["hot_budget_tokens"])
		fixed_budget = min(int(self.fixed_segment_budget_tokens), hot_budget)
		preset["fixed_segment_budget_tokens"] = fixed_budget
		preset["main_segment_budget_tokens"] = hot_budget - fixed_budget
		# 日志增长预算 = 2× 热层预算（见 journal_growth_tokens 的实测扫描）。
		preset["journal_growth_tokens"] = 2 * hot_budget
		return WscParams(
			level=level,
			mode=self.mode,
			w_goal=self.w_goal,
			w_unresolved=self.w_unresolved,
			w_constraint=self.w_constraint,
			w_recency=self.w_recency,
			w_replay=self.w_replay,
			card_conclusion_chars=self.card_conclusion_chars,
			append_budget_tokens=self.append_budget_tokens,
			min_gain_tokens=self.min_gain_tokens,
			inline_max_tokens=self.inline_max_tokens,
			include_next=self.include_next,
			stable_prefix_ordering=self.stable_prefix_ordering,
			churn_margin=self.churn_margin,
			churn_dwell=self.churn_dwell,
			churn_warn_rate=self.churn_warn_rate,
			churn_min_obs=self.churn_min_obs,
			journal_layout=self.journal_layout,
			request_excerpt_chars=self.request_excerpt_chars,
			**preset,
		)


@dataclass
class WscResult:
	"""一次压缩的完整产物 + 审计留痕（每个保留/降级/剪枝决策都有理由）。"""

	hot: HotLayer
	level: str
	mode: str
	base_tokens: int
	rebuilt: bool  # 本次是否发生了整层重建（= 一次 KV 前缀 miss）
	# 收益门：热层不比重放原文更省时不压缩（规则 7 的「收益不足不做」）。
	# False 时调用方必须原样发送未压缩区域，hot.text 仅供诊断。
	compressed: bool = True
	# 自检（规则 2）：各段逐轮变动率 / 前缀失稳率 / 超阈告警。
	# 变动率是用户的原始口径；排序用的是前缀失稳率（见 assemble.order_segments 注释）。
	# 日志布局下前缀失稳率恒为 0（结构使然），此时有意义的量是 journal_appends /
	# journal_refroze。
	churn: dict[str, float] = field(default_factory=dict)
	front_break: dict[str, float] = field(default_factory=dict)
	churn_warnings: tuple[str, ...] = ()
	# 规则 8：本轮日志新增条目数 / 本轮是否发生重冻结（=一次前缀 miss）/ 日志总 token。
	journal_appends: int = 0
	journal_refroze: bool = False
	journal_tokens: int = 0
	# 信息留存审计：区域内用户原话的渲染通道是否真的接上了（规则 1 空白的补丁）。
	user_requests_rendered: int = 0
	user_requests_total: int = 0
	#: 固定段/主链双预算审计（金额单位为 node_token_len 口径的 token）。
	budget: dict[str, int | str] = field(default_factory=dict)
	trace: list[dict[str, Any]] = field(default_factory=list)
