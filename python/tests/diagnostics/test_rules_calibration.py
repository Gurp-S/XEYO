"""真实数据普查确认到的误归因与作用域缺陷的回归集（19 条）。

对应 2026-09-25 对十条真实回合的普查（设计文档第 6 节的不对称判据）：

1. ``permission_snapshot_id`` 一个轮里出现多个取值曾被写成 ``confirmed_fault``，
   而授权增删本身就会合法地改变快照 id；进一步实测（同批 40 轮）发现它是**写入瞬间**
   的 ambient 身份 —— 27/40 轮里同一个 ``model_request_id`` 的两次写入就带着不同 id，
   于是它连"未定"都判不了，已从漂移比较里退出，改由采集层说明量具粒度。
2. ``frozen_head`` 把「本轮折叠账本为空」当成「没折叠过」——折叠事件按会话写、
   行内不带轮次身份，空的折叠集合证明不了任何事；而它衡量「本轮有几个不同投影」
   的前提本身是空的（投影 = 整份消息列表的哈希，一枪一个，28/28 命中轮次都能被
   "这一轮不止一枪"解释）。该规则已重新指向可核对的不变量。
3. 一个根本不存在的轮次会拿到 ``confirmed_fault`` + 引擎定责，证据来自同会话
   别处的 transcript 行与会话级 leftovers；
4. 真实 DENY 审计行（``tools/tool_registry.py`` 的只读门与策略 DENY）既不带
   ``approved`` 也不带 ``outcome``，被责任划分读成「没挡住」；
5. 折叠与验收的证据指针指向别的来源的文件（拿审计窗口路径冒充 usage 账本、
   拿 working.json 路径冒充 pin）；
6. 投影里 ``full output:`` 与 ``output truncated`` 两个字面量的计数不等被写成"可疑原因"，
   而 ``tools/job_tools.py`` 的 ``(earlier output truncated)`` 天生不带句柄 ⇒ 健康运行也会命中；
   先降到未定，再把上游判据换成"截断声明必须带可回读句柄"（engine/projection_manifest.py，
   #29）之后回到可疑档 —— 本文件钉的是新形状，不是旧计数；
7. ``model.finished`` 的 ``aborted`` / ``retry`` 被一律写成"已确认厂商或传输故障"——
   前者来自引擎的 Aborted 分支（用户停止），后者是设计里的下一步。
   2026-09-25 对最近 40 个真实轮次复跑：该规则 24 条"已确认"里有 9 条属于这两类。
8. 不带 ``request_id`` 的账本行被写成**本轮**结论，但账本行没有轮次身份：同会话的
   每一轮都报同一行（真实数据 37/40 轮、13 个轮次的消息字字相同）。作用域错位的
   事实改由采集缺项承担，笔数仍留在报告侧。
9. ``tool_failure`` 的归属通路是断的：``fault_split._tool_error_party`` 只从证据
   ``detail`` 里正则取 ``error_kind=``，而规则写进 detail 的只有
   ``is_error=true action_id=...`` —— 单测全都手写带 error_kind 的 detail 所以常绿，
   生产侧 2026-09-25 复跑尾窗 200 轮：74/74 条证据取不到 kind，工具失败一律判"未定"，
   ``_ENGINE_KINDS`` / ``_ENVIRONMENT_KINDS`` 两张表一次也没被读到（覆盖率为 0，
   且看起来"已经在按 error_kind 定责"）。现由 ``rules._tool_error_detail`` 生产该字段，
   本文件用**走真实生产者**的用例钉住两端。
10. ``INTERNAL`` 曾被列进 ``_ENGINE_KINDS``。它不是分类：``tools/base_tool.py`` 给所有
    "只回了 is_error + 文本"的错误统一填它，``error_taxonomy.classify_exception`` 什么
    都没匹配上时也返回它，而后者只接在 ``tools/orchestration.py``（子代理工具）上。
    真实尾窗 12 000 行里非空 error_kind 129/129 都是 INTERNAL ⇒ 把它当我方引擎证据，
    等于把全部工具失败判给自己；把它印进现象，等于给读者一个不存在的区分。
    现在它落到"未定"，现象里改说"错误分类未细分"，原值仍留在证据里可回读。
11. 投影 manifest 的结论不带轮次身份：``memory/working`` 只存"本会话最后一份"
    ``last_projection_manifest``，规则却把它当本轮结论报。2026-09-25 分层普查 57 轮：
    29 条投影结论里只有 7 条的 ``projection_id`` 出现在本轮的模型行里，其余 22 条是
    同一条会话级记录被同会话的别轮复用（一份 manifest 最多被 22 个轮次各自报一遍）。
    现在归不到本轮的投影一律不出结论 —— 与第 7/8 条同一族：会话级记录不得冒充轮次结论。
    同一份 manifest 还喂着 ``tool_pair_integrity``，而那条是「已确认 + 引擎定责」两级
    一起给的（``fault_split._ENGINE_RULES``）：漏归属的代价是把一个坏形状算到该会话
    每一个被问诊的轮次头上（09-20 那次孤儿 tool_result 事故正是这种形状）。
12. ``wire_gap`` 的 sse_gui 分支读的是 ``notice.channel`` 上一个**从未被任何生产者写过**
    的 ``kind_detail`` 字段（2026-09-25 生产者普查：真实行只有 strategy / provider_model
    / injected / reason 四个键），所以那条"事件流出现缺口通知"永远不命中，而界面仍按
    "该边界有规则覆盖"展示。真正的缺口信号是 ``engine/turn_runner.py`` 发出的
    ``stream_gap`` 帧 —— 它只活在那一次连接里。现在发出帧的同一处补写 ``stream.gap``
    审计行（带 session_id/turn_id 与两端事件号），规则改读它。
13. 同族的字段名错位：``llm.failure`` 的错误码写在 ``code`` 上，采集只读 ``error_code``
    ⇒ 现象里的 ``code=`` 恒为空，看着像"厂商没给码"。采集改为两者取一。
14. ``repeated_failure`` 的 impact 写着"同一参数与错误签名反复出现"，而同一条的
    coverage_gap 已经写明"签名相同不等于参数相同" —— 一条结论里两句话互相推翻。
    实测真实尾窗 12 000 行：``tool.*`` 行里 ``command`` / ``file_path`` / ``pattern``
    / ``url`` 出现次数全为 0，签名里的参数位恒为空。impact 改为只说同一工具与同一
    错误签名，并明写参数不可证。同处修掉窗口说明的假归因：``session_id`` 为空的行
    不只是"旧格式"，实测 2 320 行里 tool.* 占 1 969，绝大多数是评测/模拟器直接写入。

纠正的底线：规则要么判对，要么 ``unknown`` 并写明缺哪条记录，不得靠沉默消噪。

本文件与 ``test_rules_fixed_samples.py`` 另钉四条"读不出被写成已确认故障 / 整条读不到 /
被当成一个取值"的家族成员（2026-09-26 生产者契约对照 + 真实账本普查）：

15. ``usage_accounting`` 要求 ``retry`` / ``protocol_fallback`` 那一枪也必须有用量行。
    生产侧 ``model/deepseek.py::_record_usage_safe`` 是 ``if not usage: return`` —— 没拿到
    厂商用量尾帧就整行不写，所以被打断的一枪没有行是契约的形状。同一条判据把
    ``failed`` / ``aborted`` 排除在外，却把这两类留在里面，是自相矛盾的口径。
    真实数据：5 个会话 9 条「已确认缺账」里 4 条整条由这类尝试构成
    （sess_mu9oqy8m 2、sess_mubdisp8 1、raman-fitting 1），另 5 条是 ``ok`` 尝试真没账。
    现在拆成两条：``ok`` 无账仍是已确认故障，重打/换通道无账降为未定并写明两种可能都成立
    （账本里确有 attempt=2 的行 ⇒ 重打后也可能记到账）。
16. ``cold_reference`` 的 spill 分支把「路径 ``is_file()`` 为假」直接写成已确认的恢复性故障，
    而 ``tools/spill.py::_prune_old`` 每次落盘都会删掉超过保留期（默认 7 天）的旧句柄 ——
    到期消失是设计。真实审计 11 条 ``tool.spill`` 里 6 条落在保留期之外。
    现在越过保留期的句柄降为未定；保留期被设成 0（引擎不做清理）时判据退回已确认，
    因为那时"到期"这个借口不存在。
17. ``permission_block`` 整条通路要求 DENY 行有一个 ``permission.pending`` 兄弟，而只读门
    与策略 DENY 本来就不弹审批 —— 逐 id 追踪真实审计：214/214 行 ``permission.denied``
    在整份文件里只出现这一次，既没有 pending 也没有同 id 的 ``tool.started`` / ``tool.finished``。
    于是"这一枪为什么没执行"在最常见的一类拦截上没有任何答案（77 个真实轮次）。
    现在这类行单独成一条结论（未定：策略拒绝是执行层的设计结果，与 tool_routing 同一裁定），
    规则与理由留在证据里；实测同批 77 轮的责任划分结论改动 0 条 —— 补的是可见性，不是定责。
18. 第 14 条的续集：``repeated_failure`` 说"同一 error_kind=未记录 重复失败 N 次"。
    真实数据 508 个轮次跑出 58 条该结论，其中 **55 条的分类位是空的**（16 229 行
    tool.finished 里带 error_kind 键的 2 948 行有 2 819 行是 null，非空的 129/129 全是
    ``INTERNAL``），而审计又不带参数 ⇒ 那一组里真正相同的只有工具名。把"读不出"写成
    ``error_kind=未记录`` 仍是在造一个不存在的取值。现在分两句话：有分类位才说
    "同一错误签名"，没有就说"错误分类未记录：这一组只按工具名归"。
19. **范围词不跟范围走**：报告端点接受空 ``turn_id``（``post_report``），那时每条规则读的都是
    整个会话的行，而规则与归因块里有二十多处句子写死「本轮」—— 把会话级的行数说成一轮，
    与 ``tool_routing`` 当年为同一件事改口的理由一模一样，但只有它自己改了。
    现在 ``rules.scope_word(run)`` 是正本，两侧都从它取词，并钉两道双向门：
    会话级不许出现「本轮」，同一批事实按轮问诊时必须重新出现（否则门是空转的）。
    反面教材两条，都在这轮现场踩到：① 占位符被换成 ``scope_word(run)`` 却漏了花括号，
    f-string 于是把函数名当字面文本印出去 —— 套件全绿，只有把裁决 dump 出来才看得见；
    ② 约束正文由 ``_last_user_obligation`` 自己开转录文件取（与采集器的窗口无关），
    所以那条门必须写真实转录文件，只填 ``run.transcript_rows`` 会一句范围词都扫不到。

20. ``tool_failure`` 的 impact 是一句常量：「失败步骤已定位到工具与 action_id；
    结果正文按需在 transcript 里回读。」整份真实账本 711 条 ``tool.finished
    is_error=true`` 行里 **625 条（88%）根本不写 action_id**（生产者只写 ``request_id``），
    而证据 detail 无条件印 ``action_id=`` 后面接空 —— 结论与证据同时在说一件没发生的事；
    另有 254 条（36%）属于**没有转录文件**的会话，那句"去 transcript 里回读"是把读者
    指向一个不存在的文件（与 #74 同一族：产物丢失 ≠ 开关关闭）。现在两句都跟着事实走：
    有 action_id 才说 action_id，否则说调用标识（tool_use_id，实测 711/711 都在），
    两者都没有就只说行号；转录不在就明写"结果正文不可回读"。
"""

from __future__ import annotations

import json
import time

from diagnostics import fault_split, rules
from diagnostics.collect import RunEvidence, Window
from diagnostics.fault_split import ENGINE, MODEL, UNDETERMINED, attribute_fault
from diagnostics.identity import (
	CONFIRMED_FAULT,
	SUSPECTED_CAUSE,
	UNKNOWN,
	Finding,
	normalize_event,
)
from diagnostics.rules import evaluate_run

AUDIT_LOCATOR = r"C:\xeyo\audit\audit.jsonl"
FOLD_LOCATOR = r"C:\xeyo\usage\fold_events.jsonl"


def _ev(line_no: int, kind: str, ts: float = 1.0, **fields):
	row = {"ts": ts, "kind": kind, "session_id": "s1", "turn_id": "t1"}
	row.update(fields)
	return normalize_event(line_no, line_no, row)


def _audit_window(rows: int = 10) -> Window:
	return Window(
		source="audit",
		locator=AUDIT_LOCATOR,
		complete=True,
		rows_scanned=rows,
		rows_matched=rows,
	)


def _fold_window(*, complete: bool = True, rows_matched: int = 0) -> Window:
	return Window(
		source="fold_events",
		locator=FOLD_LOCATOR,
		complete=complete,
		rows_scanned=rows_matched,
		rows_matched=rows_matched,
	)


def _run(events: list | None = None, *, windows: list | None = None, **over) -> RunEvidence:
	"""带采集窗口的视图：窗口在场才允许谈「本轮无记录」（手工构造的空对象不算采集过）。"""
	base = RunEvidence(session_id="s1", turn_id="t1")
	base.events = list(events or [])
	base.windows = list(windows if windows is not None else [_audit_window()])
	for key, value in over.items():
		setattr(base, key, value)
	return base


# ---------- 1. 快照标识：不是请求身份，退出漂移比较 ----------


def _snapshot_run() -> RunEvidence:
	return _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, permission_snapshot_id="perm:aaaa"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, permission_snapshot_id="perm:bbbb"),
			_ev(3, "model.started", 3.0, model_request_id="r3", attempt=1, permission_snapshot_id="perm:cccc"),
		]
	)


def test_snapshot_id_multiplicity_is_not_a_drift_finding() -> None:
	"""快照 id 不是请求级身份 ⇒ 不再进漂移比较（既不判"已确认"，也不再判"未定"）。
	实测（最近 40 个真实轮次）：32/40 轮的 model.* 行带着 ≥2 个快照 id，其中 27/40 轮
	是同一个 model_request_id 的两次写入就用了不同 id。这不是故障的形状，是量具粒度。"""
	findings = rules.check_instruction_drift(_snapshot_run())
	assert findings == []


def test_snapshot_split_is_reported_as_a_measurement_limit(collect) -> None:
	"""事实要说，但说在采集层：缺项必须点名这个字段与它的来源，且只在真看到分裂时出现。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "permission_snapshot_id": "perm:aaaa"},
			{"ts": 1.4, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok", "permission_snapshot_id": "perm:bbbb"},
		]
	)
	gaps = [g for g in run.gaps if g.boundary == "instruction_context" and g.reason == "not_comparable"]
	assert gaps, "同一逻辑调用带着两个快照身份，必须说清这一级判不了"
	assert "permission_snapshot_id" in gaps[0].detail
	assert "写入瞬间" in gaps[0].detail


def test_single_snapshot_id_per_request_does_not_trigger_the_gap(collect) -> None:
	"""反面对照：一轮里每个逻辑调用各自一个快照身份（哪怕彼此不同）也不发这条缺项。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "permission_snapshot_id": "perm:aaaa"},
			{"ts": 2.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r2", "attempt": 1, "permission_snapshot_id": "perm:bbbb"},
		]
	)
	assert [g for g in run.gaps if g.reason == "not_comparable"] == []


def test_other_identifier_drift_is_still_suspected() -> None:
	"""其余标识保持原判据：本次只纠正误判，不把规则一并削掉。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, tool_schema_hash="h1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, tool_schema_hash="h2"),
		]
	)
	drift = [f for f in rules.check_instruction_drift(run) if "tool_schema_hash" in f.phenomenon]
	assert drift and drift[0].status == SUSPECTED_CAUSE


# ---------- 2. 冻结头：投影按枪数变化是常态，只有重发换面才是信号 ----------


def _projection_run(fold_rows: list, fold_window: Window | None) -> RunEvidence:
	windows = [_audit_window()] + ([fold_window] if fold_window is not None else [])
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, projection_id="p2"),
			_ev(3, "model.started", 3.0, model_request_id="r3", attempt=1, projection_id="p3"),
		],
		windows=windows,
	)
	run.fold_rows = list(fold_rows)
	return run


def test_projection_changing_between_shots_is_not_a_signal() -> None:
	"""一枪一个投影是构造上的必然（投影 = 整份消息列表的哈希，projection_manifest:98）。
	真实数据 40 轮里旧前提命中 28 轮，而这 28 轮的不同投影数全都 ≤ 本枪数 ⇒ 前提只
	等价于"这一轮不止一枪"。所以三个不同调用各带一个新投影：不得产出任何冻结头结论。
	"折叠账本对本会话零记录"这一事实改由采集层说（见 test_collect_integrity 的 no_records）。"""
	assert rules.check_frozen_head(_projection_run([], _fold_window())) == []


def test_populated_fold_ledger_does_not_make_multi_shot_turn_suspicious() -> None:
	"""账本完整且有行也不改变结论：可疑级原先同样建立在"本轮多个投影"这个空前提上。"""
	run = _projection_run(
		[
			{"session_id": "s1", "fold": True, "reason": "worth_fold", "line_no": 3, "locator": FOLD_LOCATOR},
			{"session_id": "s1", "fold": False, "reason": "pays_back_too_slow", "line_no": 4, "locator": FOLD_LOCATOR},
		],
		_fold_window(complete=True, rows_matched=2),
	)
	assert rules.check_frozen_head(run) == []


def test_retry_that_changes_projection_is_suspected() -> None:
	"""重新指向真正的不变量：同一个逻辑调用的两次尝试换了字节面。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.finished", 1.4, model_request_id="r1", attempt=1, status="retry", projection_id="p1"),
			_ev(3, "model.started", 2.0, model_request_id="r1", attempt=2, projection_id="p2"),
		]
	)
	findings = rules.check_frozen_head(run)
	assert len(findings) == 1
	assert findings[0].status == SUSPECTED_CAUSE
	assert "r1" in findings[0].phenomenon
	assert findings[0].evidence
	for ref in findings[0].evidence:
		assert ref.source == "audit"
		assert ref.locator == AUDIT_LOCATOR
		assert FOLD_LOCATOR not in ref.locator, "折叠账本没参与这条结论，指针不得指它"


def test_retry_with_identical_projection_is_silent() -> None:
	"""反面对照：重发同一份投影必须零结论，规则不能恒真。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1"),
			_ev(2, "model.finished", 1.4, model_request_id="r1", attempt=1, status="retry", projection_id="p1"),
			_ev(3, "model.started", 2.0, model_request_id="r1", attempt=2, projection_id="p1"),
		]
	)
	assert rules.check_frozen_head(run) == []


def test_window_chain_break_is_still_a_confirmed_fault() -> None:
	"""同一折叠区间内摘要指纹变化是真不变量破坏：保持已确认级。"""
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1")])
	run.working = {
		"locator": r"C:\xeyo\sessions\s1.working.json",
		"compact_checkpoint": {
			"window_chain": [
				{"cursor": 8, "frozen_until": 3, "summary_fp": "aaaa"},
				{"cursor": 8, "frozen_until": 3, "summary_fp": "bbbb"},
			]
		},
	}
	finding = next(f for f in rules.check_frozen_head(run) if f.status == CONFIRMED_FAULT)
	assert "折叠区间" in finding.phenomenon


# ---------- 3. 本轮无记录：不得拿会话级 leftovers 定责 ----------


def test_session_scoped_cold_reference_is_not_this_turns_fault() -> None:
	"""采集器标为「不属于本运行」的冷引用不得算成本轮的已确认故障。"""
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	run.transcript_rows = [
		{
			"id": "m9",
			"role": "tool",
			"tool_call_id": "call_other_turn",
			"content_ref": "gone.json",
			"body_state": "missing_blob",
			"locator": r"C:\xeyo\sessions\s1.jsonl",
			"line_no": 4,
			"in_run": False,
		}
	]
	findings = rules.check_cold_references(run)
	assert not [f for f in findings if f.status == CONFIRMED_FAULT], "会话级 leftovers 不是本轮证据"
	assert findings and all(f.status == UNKNOWN for f in findings)
	assert "可归属的轮次身份" in findings[0].phenomenon


def test_run_scoped_cold_reference_is_still_a_confirmed_fault() -> None:
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	run.transcript_rows = [
		{
			"id": "m9",
			"role": "tool",
			"tool_call_id": "c1",
			"content_ref": "gone.json",
			"body_state": "missing_blob",
			"locator": r"C:\xeyo\sessions\s1.jsonl",
			"line_no": 4,
			"in_run": True,
		}
	]
	assert [f for f in rules.check_cold_references(run) if f.status == CONFIRMED_FAULT]


def test_expired_spill_handle_is_not_a_confirmed_recovery_fault(monkeypatch) -> None:
	"""越过 tools/spill.py 保留期的句柄读不到，是例行清理的形状，不是恢复性故障。

	引擎每次落 spill 都会删掉更早的（``_prune_old``，默认 7 天）。真实审计 11 条
	``tool.spill`` 里 6 条属于这一类（2026-09-26 只读普查），而 cold_reference 是
	「已确认 + 引擎定责」两级一起给的规则。
	"""
	monkeypatch.delenv("XEYO_SPILL_RETENTION_DAYS", raising=False)
	old = time.time() - 40 * 86400.0
	run = _run([_ev(1, "tool.spill", old, path=r"C:\xeyo\spill\s1\20260901-000000-ab.txt")])
	findings = rules.check_cold_references(run)
	assert not [f for f in findings if f.status == CONFIRMED_FAULT], "到期不等于丢在发射链上"
	expired = [f for f in findings if "保留期" in f.phenomenon]
	assert len(expired) == 1 and expired[0].status == UNKNOWN
	assert "不得据此判定引擎弄丢了冷层原文" in expired[0].allowed_conclusion
	# 降级不等于消失：证据指针必须还在，读者能回到那一行核对
	assert expired[0].evidence and "spill 文件缺失" in expired[0].evidence[0].detail


def test_recent_missing_spill_handle_is_still_a_confirmed_recovery_fault() -> None:
	run = _run([_ev(1, "tool.spill", time.time(), path=r"C:\xeyo\spill\s1\missing-now.txt")])
	confirmed = [f for f in rules.check_cold_references(run) if f.status == CONFIRMED_FAULT]
	assert len(confirmed) == 1
	assert "1 处冷层引用不可回读" in confirmed[0].phenomenon
	assert not [f for f in confirmed if "保留期" in f.phenomenon]


def test_retention_disabled_takes_the_expiry_excuse_away(monkeypatch) -> None:
	"""``XEYO_SPILL_RETENTION_DAYS=0`` 时引擎根本不做清理：老句柄消失只能是真丢。"""
	monkeypatch.setenv("XEYO_SPILL_RETENTION_DAYS", "0")
	old = time.time() - 40 * 86400.0
	run = _run([_ev(1, "tool.spill", old, path=r"C:\xeyo\spill\s1\gone.txt")])
	findings = rules.check_cold_references(run)
	assert [f for f in findings if f.status == CONFIRMED_FAULT]
	assert not [f for f in findings if "保留期" in f.phenomenon]


def test_truncation_claim_without_handle_is_a_suspicion() -> None:
	"""旗标含义已收窄（engine 侧 #29）：只在"截断声明拿不到回读句柄"时为真。

	旧判据是两个字面量的全局计数比大小，(earlier output truncated) 与 Bash 的
	[output truncated, full at …] 天生不带 "full output:" ⇒ 真实数据 26/40 轮被误判，
	那条只能停在未定。现在它说的是原文读不回来，可以进可疑档。
"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1")],
		projections=[
			{
				"projection_id": "p1",
				"locator": "working:projection",
				"spills": 3,
				"invariant_errors": ["truncation_without_handle"],
			}
		],
	)
	findings = [f for f in rules.check_cold_references(run) if "回读句柄" in f.phenomenon]
	assert findings, "旗标仍要作为结论报出来，不能靠沉默消噪"
	f = findings[0]
	assert f.status == SUSPECTED_CAUSE
	assert "3 个可回读句柄" in f.phenomenon
	assert "不能据此判定是哪个工具" in f.allowed_conclusion


def test_legacy_spill_flag_is_only_recorded_as_unreadable() -> None:
	"""改版前留下的旗标不能升级成可疑原因：那份 manifest 是旧判据写的。

	真实数据里 26/40 轮的这条都是旧判据（两个裸子串计数不等）误报的；
	判据换名之后，还能看见旧名就说明这份投影是改版前生成的 —— 只能登记为读不出。
	"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1")],
		projections=[
			{
				"projection_id": "p1",
				"locator": "working:projection",
				"spills": 3,
				"invariant_errors": ["spill_reference_mismatch"],
			}
		],
	)
	findings = rules.check_cold_references(run)
	assert len(findings) == 1
	assert findings[0].status == UNKNOWN
	assert "改版前" in findings[0].phenomenon
	assert not [f for f in findings if f.status == SUSPECTED_CAUSE]


def test_projection_manifest_from_another_turn_is_not_a_turn_conclusion() -> None:
	"""working 只留最后一份 manifest：它不属于本轮时，本轮就没有投影结论。

	真实数据 57 轮里 29 条投影结论只有 7 条归得到本轮；其余 22 条是同一条会话级
	记录被同会话的别轮各自报了一遍（一份最多被 22 轮复用）。会话级记录反复冒充
	轮次结论这条族，折叠账本已经修过，投影这里是第二次实测到。
	"""
	for flag in ("truncation_without_handle", "spill_reference_mismatch"):
		run = _run(
			[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p-this-turn")],
			projections=[
				{
					"projection_id": "p-other-turn",
					"locator": "working:projection",
					"spills": 3,
					"invariant_errors": [flag],
				}
			],
		)
		assert rules.check_cold_references(run) == [], flag


def test_pair_integrity_flag_from_another_turns_projection_is_not_a_verdict() -> None:
	"""不成对旗标同样要归得到本轮：它是「已确认 + 引擎定责」两级一起给的。

	working 里的 manifest 是本会话最后一份（collect 给它打了 scope=last_only）。
	本轮没提交过它就不许当本轮的结论 —— 一旦出事（09-20 那次孤儿 tool_result），
	同会话每一个被诊断的轮次都会各自领一条"投影里 call/result 不成对"的已确认故障。
	"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p-this-turn")],
		projections=[
			{
				"projection_id": "p-other-turn",
				"locator": "sessions/s1.working.json",
				"invariant_errors": ["orphan_tool_results:1"],
			}
		],
	)
	assert rules.check_tool_pair_integrity(run) == []

	mine = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1")],
		projections=[
			{
				"projection_id": "p1",
				"locator": "sessions/s1.working.json",
				"invariant_errors": ["orphan_tool_results:1"],
			}
		],
	)
	hits = [f for f in rules.check_tool_pair_integrity(mine) if f.status == CONFIRMED_FAULT]
	assert hits and "不成对" in hits[0].phenomenon, "归得到本轮时结论照旧下达，不能靠沉默消噪"


def test_turn_without_records_yields_only_the_no_record_finding(collect) -> None:
	"""整会话有记录、本轮一条没有：规则集只报本轮无记录，一条故障都不下。"""
	run = collect(
		[
			{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1},
			{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1, "status": "ok"},
		],
		turn_id="t1",
	)
	findings = evaluate_run(run)
	assert [f.rule_id for f in findings] == ["no_turn_records"]
	assert findings[0].status == UNKNOWN
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]


def _audit_window_shape(*, complete: bool, matched: int, scanned: int = 7097, other_turn: int = 0, other_session: int = 0) -> Window:
	return Window(
		source="audit",
		locator=AUDIT_LOCATOR,
		complete=complete,
		truncated=not complete,
		rows_scanned=scanned,
		rows_matched=matched,
		rows_other_turn=other_turn,
		rows_other_session=other_session,
	)


def test_no_record_wording_distinguishes_three_unreadable_cases() -> None:
	"""三种"读不出"不是一件事，措辞必须分开。

	真实数据分层普查 57 轮里 11 轮落在这条，全都不是"没记录"，而是尾窗没覆盖到：
	旧措辞「采集窗口里没有一条带 turn_id 的记录」+ 标题「本轮无记录」会被读成
	这一轮什么都没发生 —— 那是关于运行的事实，而我们只有关于窗口的证据。
	"""
	complete = _run([], windows=[_audit_window_shape(complete=True, matched=12)])
	f = rules.no_turn_records_finding(complete)
	assert f.status == UNKNOWN
	assert "整份读完" in f.phenomenon and "12 行" in f.phenomenon
	assert "这不是覆盖不足" in f.coverage_gap

	session_outside = _run([], windows=[_audit_window_shape(complete=False, matched=0, other_session=6800)])
	f = rules.no_turn_records_finding(session_outside)
	assert "尾窗没覆盖到这个会话" in f.phenomenon
	assert "这是采集范围，不是这一轮的性质" in f.coverage_gap

	turn_outside = _run(
		[],
		windows=[_audit_window_shape(complete=False, matched=40, other_turn=40)],
	)
	f = rules.no_turn_records_finding(turn_outside)
	assert "本会话在尾窗内有 40 行" in f.phenomenon
	assert "本轮没有发生任何事" in f.coverage_gap  # 明确否定那个误读
	assert "不得算给本轮" in f.allowed_conclusion


def test_no_record_without_window_says_it_cannot_judge() -> None:
	"""连采集窗口都没有：不能说"没有记录"，只能说无从判断。"""
	run = _run([], windows=[])
	run.windows = []
	finding = rules.no_turn_records_finding(run)
	assert finding.status == UNKNOWN
	assert "没有审计采集窗口" in finding.phenomenon
	assert "既不能说有记录，也不能说没有" in finding.coverage_gap


def test_no_record_verdict_blames_nobody_and_shows_no_borrowed_obligation(collect) -> None:
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1}],
		turn_id="t1",
	)
	verdict = attribute_fault(run, evaluate_run(run))
	assert verdict["responsibility"] == UNDETERMINED
	assert verdict["no_turn_records"] is True
	assert verdict["chain"] == [], "无记录的轮次不得有因果链"
	assert verdict["engine_confirmed"] == 0
	assert verdict["environment_confirmed"] == 0
	assert verdict["transport_gap"] is False
	assert verdict["primary_cause"] == "not_determined"
	assert verdict["obligation"]["excerpt"] == "", "不得从会话里借一条用户原话当本轮约束"
	assert "无记录不等于没发生" in verdict["why"]


def test_no_record_verdict_keeps_the_public_shape(collect) -> None:
	"""路由器与界面依赖的键必须一个不少。"""
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "other_turn", "model_request_id": "r9", "attempt": 1}],
		turn_id="t1",
	)
	verdict = attribute_fault(run, evaluate_run(run))
	for key in (
		"responsibility",
		"responsibility_label",
		"why",
		"primary_cause",
		"primary_cause_label",
		"cause_statement",
		"causes",
		"task_outcome",
		"task_outcome_label",
		"obligation",
		"shown_to_model",
		"shown_to_model_note",
		"engine_confirmed",
		"environment_confirmed",
		"transport_gap",
		"chain",
		"missing_evidence",
		"not_claimed",
	):
		assert key in verdict, key


def test_hand_built_view_is_not_reported_as_no_records() -> None:
	"""没跑过采集的空对象不适用「本轮无记录」：判据是窗口在场而本轮无记录。"""
	run = RunEvidence(session_id="s1", turn_id="t1")
	assert rules.collection_attempted(run) is False
	assert fault_split.no_turn_records(run) is False
	assert attribute_fault(run, [])["no_turn_records"] is False


def test_turn_scoping_drops_rows_attributed_to_another_turn() -> None:
	"""带别的轮次身份的行必须被剔除；不带轮次身份的旧行保留（不削规则）。"""
	kept, foreign, legacy = {"turn_id": "t1"}, {"turn_id": "t2"}, {}
	assert rules.turn_scoped([kept, foreign, legacy], "t1") == [kept, legacy]
	assert rules.turn_scoped([kept, foreign], "") == [kept, foreign]


def test_later_turns_user_message_is_not_this_turns_obligation(tmp_path, monkeypatch) -> None:
	"""被诊断的历史轮不得拿会话里最后一条用户消息当自己的约束。"""
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = [
		'{"id": "m1", "role": "user", "ts": 1.0, "content": "本轮的原话约束"}',
		'{"id": "m2", "role": "assistant", "ts": 2.0, "content": "回话"}',
		'{"id": "m3", "role": "user", "ts": 900.0, "content": "更晚一轮的原话"}',
	]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	run = _run([_ev(1, "model.started", 10.0, model_request_id="r1", attempt=1)])
	obligation = fault_split._last_user_obligation(run)
	assert obligation["text"] == "本轮的原话约束"
	assert obligation["ts_bound"] is True


def test_obligation_beyond_the_scan_window_says_so(monkeypatch) -> None:
	"""扫描窗够不到本轮那条用户消息时如实报窗口不足，不退化成「这轮没提要求」。"""
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = ['{"id": "m%d", "role": "assistant", "ts": %d, "content": "x"}' % (i, 5000 + i) for i in range(4)]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	run = _run([_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)])
	assert fault_split._last_user_obligation(run)["state"] == "outside_scan"


def test_projection_from_a_later_turn_cannot_prove_delivery() -> None:
	"""working 只留整会话最后一份投影：它不属于本轮时既不能说送到也不能说丢了。"""
	run = _run([_ev(1, "model.started", 10.0, model_request_id="r1", attempt=1)])
	run.projections = [{"projection_id": "p9", "created_at": 900.0}]
	assert fault_split._emitted_projection_in_turn(run) is False
	run.projections = [{"projection_id": "p1", "created_at": 9.0}]
	assert fault_split._emitted_projection_in_turn(run) is True
	run.projections = []
	assert fault_split._emitted_projection_in_turn(run) is False


def test_projection_without_any_timestamp_cannot_be_attributed() -> None:
	"""一条带时间戳的记录都没有时无从核对归属 —— 这条分支以前返回 True。

	返回 True 等于默认"这份留存投影就是我们这一枪"，于是会话级报告能拿整会话最后一枪
	去判某一枪送没送到：真实数据 404 个会话里 7 个因此被判 responsibility=engine，
	而那条"引擎丢了约束"的原因条目证据是空的（2026-09-26 只读普查）。
	"""
	run = _run([])
	assert fault_split._emitted_projection_in_turn(run) is False
	run.projections = [{"projection_id": "p1", "created_at": 1.0}]
	assert fault_split._emitted_projection_in_turn(run) is False


# ---------- 4. 权限结果行的唯一读法 ----------

REAL_READONLY_DENY = {
	"kind": "permission.denied",
	"session_id": "s1",
	"turn_id": "t1",
	"request_id": "call_1",
	"tool_name": "Write",
	"reason": "readonly_mode",
	"permission_action": "deny",
	"permission_rule_id": "agent_mode.readonly",
	"permission_reason_code": "READONLY_MODE",
	"line_no": 7,
}

LEGACY_DENY_WITHOUT_FIELDS = {
	"kind": "permission.denied",
	"session_id": "s1",
	"turn_id": "t1",
	"request_id": "call_2",
	"tool_name": "XeyoUI",
	"reason": "ui_missing_path",
	"matched_rule": "ui_missing_path",
	"line_no": 8,
}


def test_real_deny_rows_count_as_blocked() -> None:
	"""真实 DENY 行既无 approved 也无 outcome：按 kind 与 permission_action 读成挡住。"""
	for row in (REAL_READONLY_DENY, LEGACY_DENY_WITHOUT_FIELDS):
		assert rules.permission_outcome(row) == "denied"
		assert rules.permission_blocked(row) is True
		assert rules.permission_outcome_unrecorded(row) is False


def test_resolved_rows_keep_their_documented_vocabulary() -> None:
	"""取值来自 permissions/store.py 与 engine/permission_coordinator.py，不发明新值。"""
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": True, "outcome": "user_decided"}) == "allowed"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "timeout"}) == "timeout"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "aborted"}) == "aborted"
	assert rules.permission_outcome({"kind": "permission.resolved", "approved": False, "outcome": "user_decided"}) == "denied"
	assert rules.permission_outcome({"kind": "permission.pending", "tool_name": "Write"}) == "unrecorded"
	assert rules.permission_outcome_unrecorded({"kind": "permission.pending"}) is False


def test_row_recording_no_outcome_is_unrecorded_not_allowed() -> None:
	"""结果行什么都不记时只能报未记录，不得读成「已通过」也不得读成「已拒绝」。"""
	bare = {"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12}
	assert rules.permission_outcome(bare) == "unrecorded"
	assert rules.permission_blocked(bare) is False
	assert rules.permission_outcome_unrecorded(bare) is True


def test_fault_split_uses_the_same_reading_function() -> None:
	"""两侧必须是同一个读法，否则会对同一行得出相反结论。"""
	assert fault_split.permission_outcome is rules.permission_outcome
	assert fault_split.permission_blocked is rules.permission_blocked


def test_unanswered_permission_wait_is_not_a_confirmed_fault() -> None:
	"""授权等待没人答复（outcome=timeout）或中止：执行层的 fail-closed 结果，不是产品故障。

	engine/permission_coordinator.py::wait 在超时那一刻自己写 approved=False +
	outcome="timeout"；aborted 来自 engine/abort.py 的停止分支。
	分层普查 57 个真实轮次里，该规则 7 条"已确认"全部是 timeout —— 与它自己
	「不得把预期拒绝计成产品故障」的口径矛盾。事实要留住（仍算被权限挡住），档位要落对。
	"""
	timeout_row = {
		"kind": "permission.resolved",
		"request_id": "apr9",
		"tool_name": "Bash",
		"approved": False,
		"outcome": "timeout",
		"user_choice": "deny",
		"reason": "timeout",
		"matched_rule": "bash_default_ask",
		"line_no": 21,
		"ts": 2.0,
	}
	assert rules.permission_outcome(timeout_row) == "timeout"
	assert rules.permission_blocked(timeout_row) is True, "事实层：这一枪确实没执行"

	run = _run(
		[],
		permissions=[
			{"kind": "permission.pending", "request_id": "apr9", "tool_name": "Bash", "matched_rule": "bash_default_ask", "line_no": 20, "ts": 1.0},
			timeout_row,
		],
	)
	findings = rules.check_permission_block(run)
	assert findings
	assert all(f.status == UNKNOWN for f in findings), [f.status for f in findings]
	text = findings[0].phenomenon + findings[0].allowed_conclusion
	assert "timeout" in text and "Bash" in text
	assert not [f for f in findings if f.status == CONFIRMED_FAULT]


def test_rule_reading_and_fault_split_agree_on_a_real_deny_row() -> None:
	"""同一个 DENY 行：规则报挡住，责任划分也报挡住——不再互相矛盾。"""
	run = _run(
		[],
		permissions=[
			{"kind": "permission.pending", "request_id": "apr1", "tool_name": "Bash", "matched_rule": "bash_confirm_ask", "line_no": 6, "ts": 1.0},
			dict(REAL_READONLY_DENY, request_id="apr1"),
		],
	)
	assert [f for f in rules.check_permission_block(run) if f.status == CONFIRMED_FAULT], "拒绝行必须被读成挡住"
	unmet = fault_split._required_action_unmet(run, "改完必须跑 pytest")
	assert unmet["state"] == "blocked_by_permission"
	assert unmet["evidence"]


def test_missing_permission_outcome_is_not_read_as_passed() -> None:
	"""结果行没有结果字段：本轮动作判不了，退回 unknown 而不是「已通过」。"""
	unmet = fault_split._required_action_unmet(
		_run(
			[],
			permissions=[
				{"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12, "ts": 1.0},
			],
		),
		"改完必须跑 pytest",
	)
	assert unmet["state"] == "permission_outcome_unrecorded"
	assert unmet["evidence"]


def test_unrecorded_permission_outcome_blames_nobody() -> None:
	"""未记录审批结果时不得判模型的错。"""
	run = _run(
		[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)],
		permissions=[{"kind": "permission.resolved", "request_id": "apr1", "tool_name": "Bash", "line_no": 12, "ts": 1.0}],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] != MODEL
	assert any("未记录" in m for m in [verdict["why"], *verdict["missing_evidence"]])


def test_blocked_real_deny_row_is_engine_not_model(monkeypatch) -> None:
	"""只读门的 DENY：归执行层，不归模型没干活。"""
	constraint = "改完必须跑 pytest 再说完成"
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		'{"id": "m1", "role": "user", "ts": 0.5, "content": "%s"}\n' % constraint,
		encoding="utf-8",
	)
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: ('{"c": "%s"}' % constraint, "working.json"))
	run = RunEvidence(
		session_id="s1",
		turn_id="t1",
		windows=[_audit_window()],
		events=[_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1)],
		permissions=[dict(REAL_READONLY_DENY)],
	)
	verdict = attribute_fault(run, [])
	assert verdict["responsibility"] == ENGINE
	assert any(s["party"] == ENGINE for s in verdict["chain"])


# ---------- 5. 证据指针与不削规则 ----------


def test_verifier_absence_is_a_gap_not_a_per_turn_finding(collect) -> None:
	"""没有 verifier 固定记录：以前每轮都产出一条 unknown（真实数据 40/40），
	把"未定"桶占满；现在它是采集缺项，不是一条待判结论。
	原意图一并保留：没有 pin 就绝不产生一条带伪证据指针的结论。"""
	run = collect([{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}])
	assert rules.check_verifier(run) == []
	assert [f for f in evaluate_run(run) if f.rule_id == "verifier"] == []
	gaps = [g for g in run.gaps if g.boundary == "file_verifier" and g.reason == "not_recorded"]
	assert gaps, "缺席事实要留在缺项清单里"
	assert "kind=verifier" in gaps[0].detail


def test_unlinked_usage_rows_are_a_session_gap_not_a_per_turn_finding(collect) -> None:
	"""账本行不带 request_id ⇒ 行内没有轮次身份，归属只到"会话 + 尾窗"。
	以前它被写成一条本轮结论，同会话每一轮都报同一行（真实数据 37/40 轮、
	其中 sess_mu9 的 13 个轮次报的都是同一 line_no）。事实不删，换个正确的层级说。"""
	from diagnostics.report import usage_summary
	from usage.ledger import events_path, record_from_openai_usage

	record_from_openai_usage(  # 旁路调用：没有 _meta_request_id ⇒ 行里不写 request_id
		provider="deepseek",
		model="deepseek-chat",
		api_key="sk-x",
		usage={"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
		session_id="s1",
	)
	row = json.loads(events_path().read_text(encoding="utf-8").splitlines()[-1])
	assert "request_id" not in row, "样本必须是真正的无归属行"
	run = collect(
		[{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}]
	)
	assert run.usage_rows, "无归属行仍要被采集，否则后面都是空谈"
	assert [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"] == []
	gaps = [g for g in run.gaps if g.boundary == "model_request" and g.reason == "unattributed_rows"]
	assert gaps, "笔数要留在缺项清单里"
	assert "1 笔" in gaps[0].detail
	assert "无法归轮" in gaps[0].detail, "措辞必须点明作用域只到会话"
	assert usage_summary(run)["unlinked_usage_rows"] == 1, "报告侧的笔数不能一起丢掉"


def test_audit_evidence_still_points_at_the_audit_window() -> None:
	"""防过度修正：审计类结论的指针仍要能回到审计文件。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, tool_schema_hash="h1"),
			_ev(2, "model.started", 2.0, model_request_id="r2", attempt=1, tool_schema_hash="h2"),
		]
	)
	findings = rules.check_instruction_drift(run)
	assert findings
	assert findings[0].evidence
	assert all(ref.locator == AUDIT_LOCATOR for ref in findings[0].evidence)


def test_no_confirmed_fault_and_no_engine_blame_on_an_ordinary_turn() -> None:
	"""一轮干净的模型请求：不得有任何已确认故障，也不得定责引擎。"""
	run = _run(
		[
			_ev(1, "model.started", 1.0, model_request_id="r1", attempt=1, projection_id="p1", permission_snapshot_id="perm:a"),
			_ev(2, "model.finished", 1.5, model_request_id="r1", attempt=1, status="ok", projection_id="p1", permission_snapshot_id="perm:a"),
		]
	)
	items = evaluate_run(run)
	assert [f for f in items if f.status == CONFIRMED_FAULT] == []
	verdict = attribute_fault(run, items)
	assert verdict["responsibility"] == UNDETERMINED
	assert verdict["engine_confirmed"] == 0


def test_rules_never_emit_directive_wording() -> None:
	"""模型可见文本纪律：只报事实，不出现「应该 / 建议 / 不要再」。"""
	banned = ("应该", "建议你", "请优先", "不要再")
	probe_runs = (_snapshot_run(), _projection_run([], _fold_window()), _run([]))
	for rule in rules.RULES:
		for probe in probe_runs:
			for finding in rule.check(probe):
				assert isinstance(finding, Finding)
				blob = " ".join((finding.phenomenon, finding.impact, finding.coverage_gap, finding.allowed_conclusion))
				assert not any(word in blob for word in banned), (rule.rule_id, blob)


# ---------- 7. 中止与重试不是厂商故障 ----------


def _attempt_rows(*statuses: str) -> list[dict]:
	"""按 (started, finished) 成对造审计行；statuses[i] 是第 i+1 次尝试的结束状态。"""
	rows: list[dict] = []
	ts = 1.0
	for i, st in enumerate(statuses, start=1):
		rows.append({"ts": ts, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": i})
		ts += 0.1
		if st:
			rows.append({"ts": ts, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": i, "status": st})
			ts += 0.1
	return rows


def _psf(run) -> list:
	return [f for f in rules.check_provider_stream(run) if f.rule_id == "provider_stream_failure"]


def test_user_abort_is_not_a_confirmed_provider_fault(collect) -> None:
	"""engine/query_loop.py 的 except Aborted 分支写 status=aborted：那是用户停止，
	定责到厂商或传输边界就是误归因（真实数据里 40 轮出现 7 次）。"""
	run = collect(_attempt_rows("ok", "aborted"))
	findings = _psf(run)
	assert len(findings) == 1
	f = findings[0]
	assert f.status == UNKNOWN
	assert "Aborted" in f.coverage_gap
	assert "不能据此判定模型或引擎出错" in f.allowed_conclusion


def test_retry_with_a_later_attempt_leaves_no_finding(collect) -> None:
	"""重试是设计里的下一步：后面还有尝试在跑时，中间那条 retry 不该留下"已确认故障"。"""
	run = collect(_attempt_rows("retry", "ok"))
	assert _psf(run) == []


def test_retry_as_the_last_attempt_is_undetermined(collect) -> None:
	run = collect(_attempt_rows("retry"))
	findings = _psf(run)
	assert len(findings) == 1
	assert findings[0].status == UNKNOWN
	assert "没有后续尝试记录" in findings[0].phenomenon
	assert "不能据此判定请求失败" in findings[0].allowed_conclusion


def test_protocol_fallback_stays_confirmed_but_not_blaming_prompt(collect) -> None:
	"""请求形状被厂商拒过、引擎降级重打：这确实是适配器边界的故障（白多一次请求），
	但不能读成提示词内容错误。"""
	run = collect(_attempt_rows("protocol_fallback"))
	findings = _psf(run)
	assert len(findings) == 1
	f = findings[0]
	assert f.status == CONFIRMED_FAULT
	assert "白多一次请求" in f.allowed_conclusion
	assert "不能据此判定提示词内容错误" in f.allowed_conclusion


def test_plain_failure_is_still_confirmed(collect) -> None:
	"""正向守卫：status=failed 不许被一起放宽掉。"""
	run = collect(_attempt_rows("failed"))
	findings = _psf(run)
	assert len(findings) == 1
	assert findings[0].status == CONFIRMED_FAULT


def test_drift_phenomenon_follows_the_scope_of_the_run() -> None:
	"""会话级运行的漂移结论不许说"同一轮内"：那是把整会话的两档标识算给一轮。

	这条形状在会话级扩窗（#77）之前永远不会被观察到 —— 会话级报告连一行审计都读不到。
	真实数据里确实有一个会话的 tool_schema_hash 换过两档（38 550 行账本里唯一一个）。
	"""
	events = [
		_ev(1, "model.started", tool_schema_hash="aaa"),
		_ev(2, "model.started", tool_schema_hash="bbb"),
	]
	turn = next(f for f in evaluate_run(_run(list(events))) if f.rule_id == "instruction_drift")
	session = next(
		f for f in evaluate_run(_run(list(events), turn_id="")) if f.rule_id == "instruction_drift"
	)
	assert turn.phenomenon.startswith("本轮里"), turn.phenomenon
	assert session.phenomenon.startswith("本会话里"), session.phenomenon
	assert "同一轮" not in session.phenomenon


def _tool_fail_rows(*, action_id: bool = False) -> list[dict]:
	rows = [
		{"kind": "tool.started", "ts": 1.0, "session_id": "s1", "turn_id": "t1", "request_id": "tool-a", "tool_name": "Bash"},
		{"kind": "tool.finished", "ts": 1.1, "session_id": "s1", "turn_id": "t1", "request_id": "tool-a", "tool_name": "Bash", "is_error": True},
	]
	if action_id:
		rows[1]["action_id"] = "act-7"
	return rows


def _one_tool_failure(run):
	return next(f for f in evaluate_run(run) if f.rule_id == "tool_failure")


def test_tool_failure_impact_does_not_claim_an_action_id_the_row_lacks(collect) -> None:
	"""真实生产者只在少数行上写 action_id（整账本 625/711 没有）⇒ 不许无条件说定位到它。"""
	f = _one_tool_failure(collect(_tool_fail_rows()))
	assert "已定位到工具与 action_id" not in f.impact, f.impact
	assert "tool_use_id" in f.impact, f.impact
	# 证据里也不留空字段：印 `action_id=` 后面什么都没有，等于宣称查过一个不存在的标识
	details = [e.detail for e in f.evidence]
	assert all("action_id=" not in d for d in details), details
	assert all("tool_use_id=tool-a" in d for d in details), details


def test_tool_failure_keeps_the_action_id_claim_when_the_row_carries_one(collect) -> None:
	"""反向守卫：行里真有 action_id 时不许把这句话一起删掉（否则修假话修成漏信息）。"""
	f = _one_tool_failure(collect(_tool_fail_rows(action_id=True)))
	assert "已定位到工具与 action_id" in f.impact, f.impact
	assert any("action_id=act-7" in e.detail for e in f.evidence), f.evidence


def test_tool_failure_does_not_send_the_reader_to_a_transcript_that_is_not_there(collect) -> None:
	"""没有转录文件的会话（实测 254/711 条失败行属于这类）：回读入口不存在。"""
	f = _one_tool_failure(collect(_tool_fail_rows()))
	assert "不可回读" in f.impact, f.impact
	assert "按需在 transcript 里回读" not in f.impact, f.impact


def test_tool_failure_offers_readback_when_the_transcript_exists(collect) -> None:
	from session.persistence import transcript_path

	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		'{"id": "m1", "role": "tool", "ts": 1.2, "tool_call_id": "tool-a", "content": "boom"}\n',
		encoding="utf-8",
	)
	f = _one_tool_failure(collect(_tool_fail_rows()))
	assert "按需在 transcript 里回读" in f.impact, f.impact
	assert "不可回读" not in f.impact, f.impact
