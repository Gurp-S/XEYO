"""WSC 上下文能力题库（合成题 + 固定标注）与当前实现基线跑器。

**为什么是合成题而不是人类标注**：本轮要的是"评测答案预先固定，且不能由待测压缩器自己的
选取结果反向定义"。合成题满足这条：期望片段由题面写死，与被测投影无关。所以这套题的正式
名称是「合成题 + 固定标注」，**不得**对外宣称"已有人类标注"。

六类场景（顾问裁定，逐条对应）：

1. ``revision``            用户中途改要求 ⇒ 新要求完整可见，旧要求不得被呈现为唯一当前目标。
2. ``tail_constraint``     限制写在长消息**末尾**（第 80 字符之后）⇒ 仍须完整可见。
3. ``staleness``           测试通过之后代码又变了 ⇒ 结论必须仍绑定当时的观察状态。
4. ``relevance_return``    曾经被剪的分支重新相关 ⇒ 离线能恢复正确原文。
5. ``error_identity``      同一错误签名出现在不同位置 ⇒ 来源与恢复引用不得混淆。
6. ``restart``             跨进程 ⇒ 头、游标、归档引用是否符合**声明的**恢复语义。

每题固定五件事：完整输入与消息顺序 / 必须保留的原文片段与来源 / 修订关系与仍有效的要求 /
最终投影通过条件 / 哪部分只能靠真实续做验证（``real_only``，本题库**不**给它记分）。

判据口径（重要）：
- 「可见」= 片段出现在**最终发射给模型的全部内容**里（热头或尾部原文都算）；
  **只在冷层归档里存在 = 不可见**，不得算通过。
- 旧的"前 80 字符针"口径在这里改名为 **``prefix_excerpt_retention``（前缀摘录保留）**，
  只报告、**不参与**通过判定——它是产品降级阶梯的历史选档依据，已按裁定退出。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

#: 六类场景。
CATEGORIES = (
	"revision",
	"tail_constraint",
	"staleness",
	"relevance_return",
	"error_identity",
	"restart",
)

_FILLER = "填充行，用于把关键内容推到第 80 字符之后。"


@dataclass(frozen=True)
class Probe:
	"""一条固定标注：这段原文必须在最终投影里可见。"""

	name: str
	text: str
	#: 该片段所属的来源（文件/工具/消息序号），用于判"来源身份"而不只是"文本在不在"。
	source: str


@dataclass(frozen=True)
class Question:
	qid: str
	category: str
	title: str
	messages: tuple[dict, ...]
	probes: tuple[Probe, ...]
	#: 修订关系：``(旧片段名, 新片段名)`` —— 旧的不得作为唯一当前目标出现。
	revisions: tuple[tuple[str, str], ...] = ()
	#: 只能靠真实续做验证的部分（本题库不记分）。
	real_only: str = ""
	#: 允许缺席的片段（例如"旧要求已被新要求取代且不得独占"）。
	may_be_absent: tuple[str, ...] = ()
	#: 垫进题面的可压工具轮次。**必须 >0**：题面太短时 WSC 的收益门根本不触发，
	#: 投影会原样回退到原文，于是这套题在考古文而不是考压缩器（实测 21 题里只有
	#: 4 题真进了压缩器）。跑器对"没触发压缩"的题判 `not_compressed`，不判通过。
	pad_rounds: int = 10


@dataclass
class QuestionResult:
	qid: str
	category: str
	visible: tuple[str, ...]
	missing: tuple[str, ...]
	#: 前缀摘录保留（旧"80 字符针"口径）：只报告，不参与判定。
	prefix_excerpt_retention: float
	#: 只能真实续做验证 ⇒ 不计分，但必须显式列出。
	real_only: str
	passed: bool
	#: 这一题是否真的走了压缩器。False ⇒ 分数无效（题面太短，压缩器没出手）。
	compressed: bool = True
	detail: dict[str, str] = field(default_factory=dict)


def _msg(role: str, content: str) -> dict:
	return {"role": role, "content": content}


def _long(prefix: str, tail: str, *, rows: int = 24) -> str:
	"""把 ``tail`` 推到第 80 字符之后（用于 ``tail_constraint`` 类）。"""
	body = "\n".join(f"{i} {_FILLER}" for i in range(rows))
	return f"{prefix}\n{body}\n{tail}"


# ---------------------------------------------------------------------------
# 题库（20 题）
# ---------------------------------------------------------------------------

def _msg_run(command: str, result: str) -> str:
	return f"Bash({{'command': {command!r}}}) → {result}"


def _msg_edit(path: str) -> str:
	return f"Edit(file_path={path!r}) → has been updated successfully"


def _msg_read(path: str, *, rows: int) -> str:
	body = "\n".join(f"{i}\tdef f_{i}(): ...  # {_FILLER}" for i in range(rows))
	return f"Read(file_path={path!r}) →\n{body}"


QUESTIONS: tuple[Question, ...] = (
	# --- 1. 中途改要求 ---
	Question(
		qid="R1", category="revision", title="接口形状从改到不改",
		messages=(
			_msg("user", "请把 usage 面板的字段重命名，接口形状一起改掉。"),
			_msg("assistant", "好的，我改 `model.ts` 的导出签名。"),
			_msg("user", "更正一下：接口形状不要动，只改面板显示文案。"),
		),
		probes=(
			Probe("new_scope", "接口形状不要动，只改面板显示文案", "user#3"),
			Probe("old_scope", "接口形状一起改掉", "user#1"),
			Probe("target_file", "model.ts", "assistant#2"),
		),
		revisions=(("old_scope", "new_scope"),),
		may_be_absent=("old_scope",),
		real_only="续做时是否真的没改接口签名（要看 diff，不看投影）。",
	),
	Question(
		qid="R2", category="revision", title="范围收窄：从三个文件到一个",
		messages=(
			_msg("user", "把 pricing.py、ledger.py、budget.py 都重构一遍。"),
			_msg("user", "范围收窄：这轮只动 pricing.py，另两个先别碰。"),
		),
		probes=(
			Probe("new_scope", "只动 pricing.py", "user#2"),
			Probe("forbidden", "ledger.py、budget.py 都重构", "user#1"),
		),
		may_be_absent=("forbidden",),
		real_only="是否真的没去改另外两个文件。",
	),
	Question(
		qid="R3", category="revision", title="取消一条早先的硬约束",
		messages=(
			_msg("user", "全程不许碰 gui/ 目录。"),
			_msg("user", "撤销这条：gui/ 可以改，但只改 stores/chat/usageAccumulator.ts。"),
		),
		probes=(Probe("new_scope", "只改 stores/chat/usageAccumulator.ts", "user#2"),),
		real_only="续做是否只在点名的文件里落地。",
	),
	Question(
		qid="R4", category="revision", title="先讨论再实施（流程型约束）",
		messages=(
			_msg("user", "帮我实现一个 LRU。"),
			_msg("user", "改成：先只讨论方案，一行代码都不要写，等我说了再动手。"),
		),
		probes=(Probe("process", "先只讨论方案，一行代码都不要写", "user#2"),),
		real_only="是否真的没写代码（看工具调用序列，不看投影）。",
	),
	# --- 2. 长消息末尾的限制 ---
	Question(
		qid="T1", category="tail_constraint", title="限制在长需求末尾（第 80 字符之后）",
		messages=(
			_msg("user", _long("请给用量面板加一个导出按钮，导出当前筛选结果为 CSV。",
			                   "注意：导出必须走后端流式，禁止在前端拼完整字符串。")),
		),
		probes=(Probe("tail_rule", "禁止在前端拼完整字符串", "user#1"),),
	),
	Question(
		qid="T2", category="tail_constraint", title="末尾的验收口径",
		messages=(
			_msg("user", _long("修 subagent_runner 的超时处理，涉及重试与取消两条路径。",
			                   "验收只看一件事：取消后不得再有新的子进程被拉起。")),
		),
		probes=(Probe("tail_dod", "取消后不得再有新的子进程被拉起", "user#1"),),
	),
	Question(
		qid="T3", category="tail_constraint", title="末尾的禁止项（含具体符号名）",
		messages=(
			_msg("user", _long("整理 usage/ledger.py 的读取路径，顺手补类型注解。",
			                   "禁止使用 `os.kill(pid, 0)` 判活，本机恒报存活。")),
		),
		probes=(Probe("forbidden_api", "os.kill(pid, 0)", "user#1"),),
	),
	Question(
		qid="T4", category="tail_constraint", title="多条限制分散在首尾",
		messages=(
			_msg("user", "只讨论不实施。" + _long("", "另外：结论必须给到能直接引用的 file:line。", rows=20)),
		),
		probes=(
			Probe("head_rule", "只讨论不实施", "user#1"),
			Probe("tail_rule", "结论必须给到能直接引用的 file:line", "user#1"),
		),
	),
	# --- 3. 测试后代码再次变化 ---
	Question(
		qid="S1", category="staleness", title="测试通过后又改了同一个文件",
		messages=(
			_msg("assistant", _msg_run("pytest tests/test_usage_attribution.py", "12 passed")),
			_msg("assistant", _msg_edit("python/usage/pricing.py")),
		),
		probes=(
			Probe("test_fact", "tests/test_usage_attribution.py", "assistant#1"),
			Probe("later_edit", "python/usage/pricing.py", "assistant#2"),
		),
		real_only="续做时是否重新跑测试，而不是沿用旧通过结论。",
	),
	Question(
		qid="S2", category="staleness", title="失败结论被后续成功覆盖",
		messages=(
			_msg("assistant", _msg_run("pytest tests/wsc/test_fold_gap.py", "1 failed")),
			_msg("assistant", _msg_run("pytest tests/wsc/test_fold_gap.py", "1 passed")),
		),
		probes=(Probe("latest_result", "1 passed", "assistant#2"),),
		may_be_absent=("older_result",),
	),
	Question(
		qid="S3", category="staleness", title="读过的文件被自己改过",
		messages=(
			_msg("assistant", _msg_read("python/memory/runtime.py", rows=40)),
			_msg("assistant", _msg_edit("python/memory/runtime.py")),
		),
		probes=(Probe("edited_file", "python/memory/runtime.py", "assistant#2"),),
		real_only="续做是否重读该文件而不是沿用旧行号。",
	),
	# --- 4. 旧方案重新相关 ---
	Question(
		qid="X1", category="relevance_return", title="被剪掉的分支重新被问起",
		messages=(
			_msg("assistant", _msg_read("python/synaptic/cadence.py", rows=30)),
			_msg("assistant", "决定不改 cadence.py，改走 runtime 侧。"),
			_msg("user", "回到 cadence.py 那条路，把 PAYBACK_SHOTS 的推导再讲一遍。"),
		),
		probes=(
			Probe("reopened_file", "python/synaptic/cadence.py", "assistant#1"),
			Probe("reopened_symbol", "PAYBACK_SHOTS", "user#3"),
		),
		real_only="恢复后能否给出与原文一致的推导（要看答案，不看投影）。",
	),
	Question(
		qid="X2", category="relevance_return", title="早先的失败方案成为唯一出路",
		messages=(
			_msg("assistant", _msg_run("rg -n cost_cny python/usage", "no matches")),
			_msg("assistant", "改用 grep 全仓。"),
			_msg("user", "还是回到 rg 那条，把 -n 加上再试。"),
		),
		probes=(Probe("failed_tool_line", "rg -n cost_cny python/usage", "assistant#1"),),
	),
	Question(
		qid="X3", category="relevance_return", title="长会话里被剪的接口约定重新要用",
		messages=tuple(
			[_msg("assistant", _msg_read("python/msgtypes/events.py", rows=25))]
			+ [_msg("assistant", _msg_run(f"pytest tests/test_{i}.py", "all passed")) for i in range(14)]
			+ [_msg("user", "events.py 里 CrossLayerJudgment 的字段顺序是什么？")]
		),
		probes=(Probe("symbol", "CrossLayerJudgment", "user#16"),),
		real_only="答出的字段顺序是否与原文一致。",
	),
	# --- 5. 同错误签名不同位置 ---
	Question(
		qid="E1", category="error_identity", title="同一退出码 1 出现在两个不同文件",
		messages=(
			_msg("assistant", _msg_run("python -m pytest python/tests/test_a.py", "exit code 1: assertion in test_a")),
			_msg("assistant", _msg_run("python -m pytest python/tests/test_b.py", "exit code 1: assertion in test_b")),
		),
		probes=(
			Probe("site_a", "test_a", "assistant#1"),
			Probe("site_b", "test_b", "assistant#2"),
		),
		real_only="一处成功不得把另一处标成已解决（看续做结论）。",
	),
	Question(
		qid="E2", category="error_identity", title="同一异常类、不同调用点",
		messages=(
			_msg("assistant", _msg_run("read .xeyo_offload/wsc/missing.txt", "FileNotFoundError at offset 12")),
			_msg("assistant", _msg_run("read gui/src/api.ts", "FileNotFoundError at offset 991")),
		),
		probes=(
			Probe("path_a", "missing.txt", "assistant#1"),
			Probe("path_b", "gui/src/api.ts", "assistant#2"),
		),
	),
	Question(
		qid="E3", category="error_identity", title="错误被后续解决，签名仍要可追溯",
		messages=(
			_msg("assistant", _msg_run("pytest tests/wsc/test_x.py", "exit code 1")),
			_msg("assistant", _msg_run("pytest tests/wsc/test_x.py", "passed")),
			_msg("user", "test_x 第一次为什么会失败？"),
		),
		probes=(Probe("resolved_file", "tests/wsc/test_x.py", "assistant#2"),),
		real_only="能否说清第一次失败的原因（而不是只报当前通过）。",
	),
	# --- 6. 跨进程恢复 ---
	Question(
		qid="P1", category="restart", title="重启后游标与头必须一致",
		messages=(
			_msg("user", "继续上一轮：把计价诚实性缺陷改完。"),
			_msg("assistant", _msg_edit("python/usage/pricing.py")),
		),
		probes=(Probe("task", "计价诚实性缺陷", "user#1"),),
		real_only="重启后是否接着改而不是从头再来（看续做行为）。",
	),
	Question(
		qid="P2", category="restart", title="重启后归档引用仍可解析",
		messages=(
			_msg("assistant", _msg_read("python/synaptic/budget.py", rows=60)),
			_msg("user", "budget.py 里 index_segment_budget_tokens 的默认值是多少？"),
		),
		probes=(Probe("file", "python/synaptic/budget.py", "assistant#1"),),
		real_only="进程重启后该引用是否仍可执行（跑器不模拟重启，见 runner 说明）。",
	),
	Question(
		qid="P3", category="restart", title="重启后不得把旧状态当当前状态",
		messages=(
			_msg("assistant", _msg_run("pytest tests/test_money.py", "8 passed")),
			_msg("user", "重启了，继续。"),
		),
		probes=(Probe("stale_test", "tests/test_money.py", "assistant#1"),),
		real_only="续做是否重跑而不是沿用 8 passed。",
	),
	Question(
		qid="P4", category="restart", title="跨进程只接回头字节，不接回算法状态",
		messages=(
			_msg("user", "接着上面继续做 WSC 的卡面改造。"),
			_msg("assistant", _msg_edit("python/memory/wsc_projection.py")),
		),
		probes=(Probe("file", "python/memory/wsc_projection.py", "assistant#2"),),
		real_only="`prev`/`cold` 故意不落盘（`wsc_projection.py:313-315`）⇒ 重启后第一枪"
		          "整段重建是否被记成压缩质量下降（不能，属生命周期缺陷）。",
	),
)

# ---------------------------------------------------------------------------
# 鉴别力题组（2026-09-30 造）：原 21 题在当前实现上 63/63 满分 ⇒ **记分器没有能力给不及格**。
# 这三题的探针只出现在一条长工具结果的**最后几行**，而卡片只留节点开头（实测卡片形状：
# ``[MAIN] #25 工具: Bash(py -3.11 -m pytest -q) -> line0 xxx… line1 xxx… …`` ⇒ 末梢整段不见）。
# 期望形状是严格的两真一对照：``head`` / ``deep`` 两臂**该挂**、``tail`` 臂**该过**
# （同一题同一探针，只差在落在哪一侧）——这才证明分数测的是压缩器，不是判据自己写错。
# ---------------------------------------------------------------------------

def _node_tail_question(qid: str, title: str, lead: str, tail_fact: str,
                        follow: str, source: str) -> Question:
    body = "\n".join(f"line{k} " + "x" * 60 for k in range(150))
    return Question(
        qid=qid, category="node_tail", title=title,
        messages=(
            _msg("user", "先看这个文件/跑一次测试。"),
            _msg("assistant", f"{lead}\n{body}\n{tail_fact}"),
            _msg("user", follow),
        ),
        probes=(Probe("node_tail_fact", tail_fact, source),
                Probe("followup_request", follow, "user#last")),
        real_only="末梢事实进了卡片还是丢了，只能靠续做验证（本组只判在场性）。",
    )


TAIL_FACTS_QUESTIONS: tuple[Question, ...] = (
    _node_tail_question(
        "N1", "失败签名在长输出末尾",
        "Bash(py -3.11 -m pytest -q) →",
        "FAILED tests/wsc/test_x.py::test_y - AssertionError: expected 4436 got 4435",
        "先修这条失败再谈别的。", "assistant#2"),
    _node_tail_question(
        "N2", "结论计数在读取结果末尾",
        "Read(file_path='repo/sample_a.py') →",
        "本文件共 4 处 TODO，都在 auth 段",
        "把这 4 处 TODO 列进改动计划。", "assistant#2"),
    _node_tail_question(
        "N3", "键名约定在工具结果末尾",
        "Read(file_path='repo/sample_b.py') →",
        "handle=cfg-v2 必须沿用这个键名",
        "沿用这个键名，不要另造名字。", "assistant#2"),
)


# ---------------------------------------------------------------------------
# 跑器
# ---------------------------------------------------------------------------

_TAIL = re.compile(r"[。；;]\s*$")

#: 三臂。`tail` 探针在逐字尾（易，对照）；`head` 探针在被压区**末尾**（仍偏易：
#: `[REQUESTS]` 逐字保留最近 3 条）；`deep` 探针在被压区**最前部**，才是
#: "深处内容还在不在"的真靶子。
ARM_TAIL = "tail"
ARM_HEAD = "head"
ARM_DEEP = "deep"


def _pad_rounds(count: int) -> list[dict]:
	"""垫入 ``count`` 轮"大工具输出 + 一句结论"——可压、且不与任何探针争内容。"""
	out: list[dict] = []
	for i in range(count):
		body = "\n".join(f"{k}\tdef helper_{i}_{k}(): ...  # {_FILLER}" for k in range(18))
		out.append(_msg("assistant", f"Read(file_path='python/pkg/mod_{i}.py') →\n{body}"))
		out.append(_msg("assistant", f"看完 mod_{i}.py，与本任务无关，继续。"))
	return out


#: 落在**被压区内部**的可压轮次。少了它，被压区只有题面那几十 tok，WSC 的收益门必然
#: 拒压 ⇒ 该题是"未测"而不是"挂"（实测 head 臂 21 题里 17 题栽在这里）。
BULK_ROUNDS = 12
#: 落在**逐字尾部**的轮次，制造"头 + 尾"的生产形状。
TAIL_ROUNDS = 4


def materialize(question: Question, *, arm: str = ARM_HEAD) -> tuple[list[dict], int]:
	"""返回 ``(消息列表, region_end)``——与生产 `_emit` 同形：`[:region_end]` 进压缩区，
	`[region_end:]` 作为逐字尾部原样发。

	两臂的唯一差别是**探针落在哪一侧**；两臂的被压区都塞满可压 bulk，否则压缩器不出手，
	题目就退化成"对着原文打分"（这是本文件第一版踩过的空门）。
	"""
	bulk = _pad_rounds(BULK_ROUNDS)
	tail = _pad_rounds(TAIL_ROUNDS)
	own = list(question.messages)
	if arm == ARM_HEAD:
		# 探针在被压区末尾 ⇒ 仍偏易（`[REQUESTS]` 逐字保留最近 3 条用户原话）。
		return bulk + own + tail, len(bulk) + len(own)
	if arm == ARM_DEEP:
		# 探针在被压区最前部，后面还压着 bulk ⇒ 深处内容的真靶子。
		return own + bulk + tail, len(own) + len(bulk)
	# 探针在逐字尾里 ⇒ 易的对照臂。
	return bulk + tail + own, len(bulk) + len(tail)


def visible_in(projection: str, probe: Probe) -> bool:
	"""「可见」= 片段出现在最终发射内容里（热头或尾部原文）。**只在冷层不算。**"""
	needle = _TAIL.sub("", probe.text).strip()
	if not needle:
		return True
	return needle in projection


def run_question(question: Question,
                 emit: Callable[[Sequence[dict], int], tuple[str, bool]], *,
                 arm: str = ARM_HEAD) -> QuestionResult:
	"""``emit(msgs, region_end) -> (最终发射文本, 是否真的走了压缩器)``。

	第二个返回值是**自校**：没有它，题面一短压缩器就不出手，全套题会对着原文打满分。
	"""
	msgs, region_end = materialize(question, arm=arm)
	projection, compressed = emit(msgs, region_end)
	visible = tuple(p.name for p in question.probes if visible_in(projection, p))
	missing = tuple(p.name for p in question.probes
	                if p.name not in visible and p.name not in question.may_be_absent)
	# 前缀摘录保留（旧"80 字符针"口径）：只取片段前 80 字符判在不在——**只报告不判定**。
	kept = [p for p in question.probes if p.text[:80] in projection]
	retention = (len(kept) / len(question.probes)) if question.probes else 1.0
	detail: dict[str, str] = {}
	for old, new in question.revisions:
		old_present = any(old == p.name and visible_in(projection, p) for p in question.probes)
		new_present = new in visible
		if not new_present:
			detail[f"revision:{old}→{new}"] = "新要求不可见"
		elif old_present and old not in question.may_be_absent:
			detail[f"revision:{old}→{new}"] = "旧要求仍与新要求并列"
	return QuestionResult(
		qid=f"{question.qid}-{arm}",
		category=question.category,
		visible=visible, missing=missing,
		prefix_excerpt_retention=retention, real_only=question.real_only,
		passed=bool(compressed) and not missing and not detail,
		compressed=bool(compressed), detail=detail,
	)


def run_bank(emit: Callable[[Sequence[dict], int], tuple[str, bool]]) -> list[QuestionResult]:
	"""两臂都跑：``-tail`` 是易的对照（探针在逐字尾部），``-head`` 才是靶子（探针在被压区）。

	只跑一臂会出两种假象：只跑 tail ⇒ 恒过；只跑 head ⇒ 分不清"压缩器丢了东西"与
	"投影本来就没建起来"。
	"""
	return [run_question(q, emit, arm=arm) for q in QUESTIONS
	        for arm in (ARM_TAIL, ARM_HEAD, ARM_DEEP)]


def run_tail_facts(emit: Callable[[Sequence[dict], int], tuple[str, bool]]) -> list[QuestionResult]:
	"""鉴别力题组单独跑（不进 `run_bank`）：主基线 63/63 满分的含义要在别处报。"""
	return [run_question(q, emit, arm=arm) for q in TAIL_FACTS_QUESTIONS
	        for arm in (ARM_TAIL, ARM_HEAD, ARM_DEEP)]


def split_arms(results: Sequence[QuestionResult]) -> dict[str, dict[str, object]]:
	"""按臂分别汇总，便于看"易臂过、难臂挂"这个真实形状。"""
	out: dict[str, dict[str, object]] = {}
	for arm in (ARM_TAIL, ARM_HEAD, ARM_DEEP):
		suffix = "-" + arm
		sub = [r for r in results if r.qid.endswith(suffix)]
		if sub:
			out[arm] = summarize(sub)
	return out


def summarize(results: Sequence[QuestionResult]) -> dict[str, object]:
	by_cat: dict[str, dict[str, int]] = {}
	for r in results:
		cell = by_cat.setdefault(r.category, {"n": 0, "passed": 0, "not_compressed": 0})
		cell["n"] += 1
		cell["passed"] += int(r.passed)
		cell["not_compressed"] += int(not r.compressed)
	return {
		"total": len(results),
		"passed": sum(int(r.passed) for r in results),
		#: 没触发压缩的题数——**不为 0 就说明这套题在考古文，分数不可用**。
		"not_compressed": sum(int(not r.compressed) for r in results),
		#: 真挂了（压缩器出手了但内容丢了/身份混了）与"未测"必须分开报。
		"failed": sum(int(r.compressed and not r.passed) for r in results),
		"tested": sum(int(r.compressed) for r in results),
		"by_category": by_cat,
		#: 只报告、不参与判定的旧口径（顾问裁定退出选档依据）。
		"prefix_excerpt_retention_mean": (
			sum(r.prefix_excerpt_retention for r in results) / max(1, len(results))
		),
		"real_only_pending": [r.qid for r in results if r.real_only],
	}
