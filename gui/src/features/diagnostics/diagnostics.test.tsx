/**
 * diagnostics.test.tsx — 诊断页的措辞纪律与不补值契约。
 *
 * 这里锁的是产品级要求，不是样式：
 * - 缺用量必须显示「费用未知」，绝不能显示 0 元；
 * - 没有已确认异常必须带免责句，不能渲染成绿色通过；
 * - 未归因必须显示「无法归因」；
 * - 同一逻辑调用的每次重试都要各占一行；
 * - 等待授权 ≠ 失败；
 * - 每条结论都必须能看到原始证据与覆盖缺口。
 */
import {cleanup, render, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, describe, expect, it} from 'vitest';
import {buildExperimentBody, parseRunDetail, parseRunsResult} from '@/lib/api/diagnostics';
import {ContextView} from './ContextView';
import {FindingsView} from './FindingsView';
import {StepsView} from './StepsView';
import {UsageView} from './UsageView';
import {selectTurnAfterRunsLoaded} from './useDiagnosticsData';
import {
	COST_BASIS_LABEL,
	DASH,
	NO_CONFIRMED_FAULT_TEXT,
	NOT_ATTRIBUTED_TEXT,
	SHOWN_LABEL,
	buildTimeline,
	describeAuditRow,
	fmtClock,
	fmtCostCny,
	fmtDuration,
	fmtInt,
	gapReasonLabel,
	groupFindingsByStatus,
	mergeDetailPreservingLoadedPages,
	pinKindLabel,
} from './model';

function detail(raw: Record<string, unknown>) {
	return parseRunDetail({
		schema_version: 1,
		session_id: 's1',
		turn_id: 't1',
		...raw,
	});
}

const EVIDENCE = [
	{source: 'audit', locator: '/x/audit.jsonl', ref_id: 'L42', detail: 'model.finished'},
];

function finding(over: Record<string, unknown>) {
	return {
		rule_id: 'tool_failure',
		rule_version: 1,
		phenomenon: '工具 Read 返回错误（error_kind=NOT_FOUND，共 1 次）',
		boundary: 'tool_permission',
		component: '工具执行：Read',
		status: 'confirmed_fault',
		evidence: EVIDENCE,
		impact: '失败步骤已定位。',
		coverage_gap: '审计不含退出码。',
		allowed_conclusion: '可确认工具在这一步失败。',
		...over,
	};
}

afterEach(cleanup);

describe('费用口径', () => {
	it('缺用量是「费用未知」，不是 0 元', () => {
		expect(fmtCostCny(null)).toBe('费用未知');
		expect(fmtCostCny(undefined)).toBe('费用未知');
		expect(fmtCostCny(Number.NaN)).toBe('费用未知');
		// 0 只能来自真实账目，措辞必须与"未知"可区分
		expect(fmtCostCny(0)).not.toBe('费用未知');
	});

	it('用量视图标注估算口径而非实付', () => {
		const d = detail({
			model_requests: [
				{
					model_request_id: 'r1',
					provider: 'deepseek',
					model: 'deepseek-chat',
					attempts: [
						{attempt: 1, kind: 'model.finished', status: 'ok', ts: 1},
						{attempt: 2, kind: 'model.finished', status: 'ok', ts: 2},
					],
					attempt_keys: ['r1#1', 'r1#2'],
					usage_by_attempt: {
						'r1#1': {request_id: 'r1', attempt: 1, attempt_key: 'r1#1', cost_cny: 0.0012, cost_source: 'estimate'},
					},
				},
			],
			usage_summary: {
				finished_attempts: 2,
				priced_attempts: 1,
				unknown_cost_attempts: 1,
				unknown_cost_keys: ['r1#2'],
				estimated_total_cny: 0.0012,
				cost_basis: 'estimate',
				cost_sources: ['estimate'],
				unlinked_usage_rows: 0,
				statement: '1 次已结束的尝试没有用量账：费用未知，未按 0 计入。',
			},
		});
		render(<UsageView detail={d} />);
		expect(screen.getAllByText('费用未知').length).toBeGreaterThan(0);
		expect(screen.getByText(COST_BASIS_LABEL)).toBeTruthy();
		expect(screen.queryByText(/^¥0$/)).toBeNull();
	});
});

describe('归因与免责措辞', () => {
	it('无已确认异常时显示免责句，不显示通过', () => {
		const d = detail({
			findings: [finding({rule_id: 'verifier', status: 'unknown', evidence: []})],
			attribution: {
				first_anomaly_boundary: '',
				last_normal_boundary: 'sse_gui',
				confirmed_count: 0,
				suspected_count: 0,
				unknown_count: 1,
				attributed: false,
				statement: '本次规则集未发现已确认异常。这不等于任务正确。',
			},
		});
		render(<FindingsView detail={d} />);
		expect(screen.getAllByText(NO_CONFIRMED_FAULT_TEXT).length).toBeGreaterThan(0);
		expect(screen.getAllByText(NOT_ATTRIBUTED_TEXT).length).toBeGreaterThan(0);
		expect(document.body.textContent).not.toMatch(/未发现问题|一切正常|通过/);
	});

	it('已确认异常带证据定位与覆盖缺口', async () => {
		const d = detail({
			boundaries: [
				{name: 'tool_permission', label: '工具与权限', present: true, evidence: EVIDENCE, evidence_count: 1, notes: []},
			],
			findings: [finding({})],
			attribution: {
				first_anomaly_boundary: 'tool_permission',
				first_anomaly_label: '工具与权限',
				last_normal_boundary: 'model_request',
				last_normal_label: '模型请求与响应',
				confirmed_count: 1,
				suspected_count: 0,
				unknown_count: 0,
				attributed: true,
				statement: '首个已确认异常边界：工具与权限。',
			},
		});
		render(<FindingsView detail={d} />);
		expect(document.body.textContent).toContain('工具与权限');
		// 证据与覆盖缺口在展开后才出现（默认收起，避免整页噪声）
		await userEvent.click(screen.getByRole('button', {expanded: false}));
		const text = document.body.textContent ?? '';
		expect(text).toMatch(/审计不含退出码/);
		expect(text).toContain('L42');
		expect(text).toContain('/x/audit.jsonl');
		expect(text).toContain('可确认工具在这一步失败');
	});

	it('分组只认三档状态，未知不并入已确认', () => {
		const groups = groupFindingsByStatus([
			finding({status: 'confirmed_fault'}) as never,
			finding({rule_id: 'wire_gap', status: 'suspected_cause'}) as never,
			finding({rule_id: 'verifier', status: 'unknown'}) as never,
			finding({rule_id: 'junk', status: '已解决'}) as never,
		]);
		expect(groups.confirmed_fault).toHaveLength(1);
		expect(groups.suspected_cause).toHaveLength(1);
		// 非法状态不得被塞进"已确认"，只能落进未知
		expect(groups.unknown).toHaveLength(2);
	});
});

describe('责任划分', () => {
	it('归属与"不宣称"一起渲染，缺证据按条列出', () => {
		const d = detail({
			fault: {
				responsibility: 'engine',
				responsibility_label: '引擎侧',
				why: '失败发生在执行层：Bash 被 bash_danger_ask 挡下。',
				primary_cause: 'permission_blocked_action',
				primary_cause_label: '被要求的动作由权限执行层挡下',
				cause_statement: '主原因：被要求的动作由权限执行层挡下。',
				causes: [
					{
						code: 'permission_blocked_action',
						label: '被要求的动作由权限执行层挡下',
						party: 'engine',
						proves: '动作是被执行层挡下的',
						does_not_prove: '不能把「没做」记到模型头上',
						evidence: EVIDENCE,
					},
					{
						code: 'acceptance_missing',
						label: '没跑验收，任务是否完成未知',
						party: 'undetermined',
						proves: '没有任何验收记录',
						does_not_prove: '既不能判完成也不能判失败',
						evidence: [],
					},
				],
				task_outcome: 'not_accepted',
				task_outcome_label: '未执行验收：无法判定任务是否完成',
				obligation: {source: 'pin', locator: 'p.json', ref_id: 'p0', excerpt: '改完必须跑测试'},
				shown_to_model: 'not_shown',
				shown_to_model_note: '发送投影里没有这段约束',
				engine_confirmed: 2,
				environment_confirmed: 0,
				transport_gap: false,
				chain: [
					{order: 1, boundary: 'wsc_fold', fact: '约束未进入发射投影', party: 'engine', party_label: '引擎侧', evidence: EVIDENCE},
					{order: 2, boundary: 'tool_permission', fact: 'Bash 被权限层挡下', party: 'engine', party_label: '引擎侧', evidence: EVIDENCE},
				],
				missing_evidence: ['缺适配器最终请求体：投影之后的变换不可见'],
				not_claimed: ['不宣称这是任务失败的全部原因', '不给概率或加权总分'],
			},
		});
		render(<FindingsView detail={d} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('引擎侧');
		expect(text).toContain('未执行验收');
		expect(text).toContain('改完必须跑测试');
		expect(text).toContain('事后固定的预期');
		// 失败原因逐条列出，且每条都带"能证明/不能证明"
		expect(text).toContain('被要求的动作由权限执行层挡下');
		expect(text).toContain('permission_blocked_action');
		expect(text).toContain('不能把「没做」记到模型头上');
		expect(text).toContain('既不能判完成也不能判失败');
		expect(text).toContain('约束未进入发射投影');
		expect(text).toContain('缺适配器最终请求体');
		expect(text).toContain('本报告不宣称');
		// 纪律：不出现概率/分数
		expect(text).not.toMatch(/\d+%|置信度|综合评分/);
	});

	it('后端没给 fault 时不渲染该块，也不报错', () => {
		render(<FindingsView detail={detail({findings: [finding({})]})} />);
		expect(document.body.textContent).not.toContain('本报告不宣称');
	});
});

describe('步骤时间线', () => {
	const d = detail({
		identity: {
			model_request_ids: ['r1'],
			attempt_keys: ['r1#1', 'r1#2'],
			tool_use_ids: ['c1'],
			approval_ids: ['apr1'],
			projection_ids: [],
		},
		model_requests: [
			{
				model_request_id: 'r1',
				provider: 'deepseek',
				model: 'deepseek-chat',
				attempts: [
					{attempt: 1, kind: 'model.started', ts: 1},
					{attempt: 1, kind: 'model.finished', status: 'retry', error_code: 'http_429', ts: 1.2},
					{attempt: 2, kind: 'model.started', ts: 1.4},
					{attempt: 2, kind: 'model.finished', status: 'ok', ts: 1.6},
				],
				attempt_keys: ['r1#1', 'r1#2'],
			},
		],
		tool_calls: [
			{
				tool_use_id: 'c1',
				tool_name: 'Bash',
				model_request_id: 'r1',
				paired: false,
				approval_ids: ['apr1'],
				is_error: null,
			},
		],
		permissions: [
			{request_id: 'apr1', kind: 'permission.pending', tool_name: 'Bash', approved: null, outcome: '', ts: 2, line_no: 9, tool_use_id: 'c1'},
		],
	});

	it('重试的每次尝试都各自成行，不折叠成最后一次', () => {
		render(<StepsView detail={d} loadingMore={false} onLoadMore={() => {}} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('第 1 次尝试');
		expect(text).toContain('第 2 次尝试');
		expect(text).toMatch(/存在重试/);
		// 逻辑调用 1 个、实际尝试 2 次
		expect(text).toContain('1 / 2');
	});

	it('等待授权显示为等待，不显示为失败', () => {
		render(<StepsView detail={d} loadingMore={false} onLoadMore={() => {}} />);
		const text = document.body.textContent ?? '';
		expect(text).toMatch(/等待权限授权|工具等待授权/);
		expect(/权限.{0,6}失败/.test(text)).toBe(false);
	});
});

describe('运行列表解析', () => {
	it('tool_use_ids 原样带出，缺失时是空数组', () => {
		const parsed = parseRunsResult({
			schema_version: 1,
			session_id: 's1',
			runs: [
				{turn_id: 't1', tool_call_count: 2, tool_use_ids: ['call_a', 'call_b']},
				{turn_id: 't2', tool_call_count: 0},
			],
		});
		expect(parsed.runs[0].tool_use_ids).toEqual(['call_a', 'call_b']);
		expect(parsed.runs[1].tool_use_ids).toEqual([]);
		expect(parsed.runs[0].turn_id).toBe('t1');
	});
});

describe('解析层不补值', () => {
	it('空响应解析成 null / 空数组，而不是编造汇总', () => {
		const d = detail({});
		expect(d.usage_summary).toBeNull();
		expect(d.attribution).toBeNull();
		expect(d.findings).toEqual([]);
		expect(d.model_requests).toEqual([]);
		expect(d.turn_id).toBe('t1');
		expect(d.events).toEqual([]);
		// 缺 events_complete 不等于"已全部返回"
		expect(d.events_complete).toBe(false);
	});

	it('时间与空值统一渲染成破折号', () => {
		expect(fmtClock(null)).toBe(DASH);
		expect(fmtDuration(null)).toBe(DASH);
		expect(fmtInt(null)).toBe(DASH);
	});
});

describe('缺证据不得渲染成确定的 0（P1 10）', () => {
	it('没取回归因块时不显示「已确认 0 · 疑似 0 · 未定 0」', () => {
		render(<FindingsView detail={detail({attribution: null})} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('未取回归因块');
		expect(text).not.toMatch(/已确认\s*0/);
		expect(text).not.toMatch(/疑似\s*0/);
		expect(text).not.toMatch(/未定\s*0/);
	});

	it('取回归因块时才出三档计数', () => {
		const d = detail({
			attribution: {
				first_anomaly_boundary: 'tool_permission',
				first_anomaly_label: '工具与权限',
				last_normal_boundary: 'model_request',
				last_normal_label: '模型请求与响应',
				confirmed_count: 2,
				suspected_count: 1,
				unknown_count: 0,
				attributed: true,
				statement: '',
			},
		});
		render(<FindingsView detail={d} />);
		expect(document.body.textContent).toContain('未定 0');
	});

	it('账本窗口没取回时是「未取回」，不是 0 条', () => {
		const d = detail({folds: [], projections: [], windows: []});
		render(<ContextView detail={d} sessionId="s1" turnId="t1" storeRoot="/diag" />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('未取回（本次响应没有折叠窗口）');
		expect(text).toContain('未取回（本次响应没有投影窗口）');
		expect(text).not.toMatch(/折叠记录\s*0 条/);
		expect(text).not.toMatch(/投影 manifest\s*0 份/);
	});

	it('窗口读了但不完整时保留截断标记', () => {
		const d = detail({
			folds: [{a: 1}],
			windows: [{source: 'fold_events', complete: false, rows_matched: 1, note: '尾窗截断'}],
		});
		render(<ContextView detail={d} sessionId="s1" turnId="t1" storeRoot="/diag" />);
		expect(document.body.textContent).toContain('1 条（窗口未读全，实际不少于此数）');
	});
});

describe('授权结果不得猜（P1 4）', () => {
	function permDetail(rows: Array<Record<string, unknown>>) {
		return buildTimeline(detail({permissions: rows})).find(r => r.source === 'permission');
	}

	it('permission.denied 行没有 outcome / approved 也算被挡住，不渲染成通过', () => {
		const row = permDetail([
			{request_id: 'apr1', kind: 'permission.pending', tool_name: 'Bash', ts: 1, line_no: 5, tool_use_id: 'c1'},
			{
				request_id: 'apr1',
				kind: 'permission.denied',
				tool_name: 'Bash',
				ts: 2,
				line_no: 6,
				tool_use_id: 'c1',
				matched_rule: 'bash_danger_ask',
			},
		]);
		expect(row?.title).toBe('权限层挡住该工具');
		expect(row?.tone).toBe('warn');
		expect(row?.statusText).toContain('结果 已拒绝');
		expect(row?.statusText).not.toContain('授权已通过');
	});

	it('真实 DENY 行渲染后正文里没有绿色通过措辞', () => {
		const d = detail({
			permissions: [
				{
					request_id: 'apr9',
					kind: 'permission.denied',
					tool_name: 'Bash',
					ts: 2,
					line_no: 6,
					tool_use_id: 'c9',
				},
			],
		});
		render(<StepsView detail={d} loadingMore={false} onLoadMore={() => {}} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('权限层挡住该工具');
		expect(text).not.toContain('授权已通过');
	});

	it('没有任何结果字段时是「结果未记录」+ 中性色', () => {
		const row = permDetail([
			{request_id: 'apr2', kind: 'permission.resolved', tool_name: 'Read', ts: 3, line_no: 8},
		]);
		expect(row?.title).toBe('授权结果未记录');
		expect(row?.tone).toBe('neutral');
		expect(row?.statusText).toContain('结果未记录');
	});

	it('approved=false 仍是已拒绝', () => {
		const row = permDetail([
			{
				request_id: 'apr3',
				kind: 'permission.resolved',
				tool_name: 'Write',
				approved: false,
				ts: 3,
				line_no: 9,
			},
		]);
		expect(row?.title).toBe('权限层挡住该工具');
	});

	it('approved=true 才是授权已通过', () => {
		const row = permDetail([
			{
				request_id: 'apr4',
				kind: 'permission.resolved',
				tool_name: 'Write',
				approved: true,
				ts: 3,
				line_no: 10,
			},
		]);
		expect(row?.title).toBe('授权已通过');
		expect(row?.tone).toBe('ok');
	});
});

describe('被折叠移出的约束要有中文标签（P1 9）', () => {
	it('SHOWN_LABEL 覆盖后端 fault_split 发出的 folded_out', () => {
		expect(SHOWN_LABEL.folded_out).toBe('被折叠移出投影（未送达）');
	});

	it('责任划分徽章不照抄机器名', () => {
		const d = detail({
			fault: {
				responsibility: 'engine',
				responsibility_label: '引擎侧',
				why: '约束在折叠一级被移出投影。',
				shown_to_model: 'folded_out',
				shown_to_model_note: '折叠发生在发送之前',
				causes: [],
				chain: [],
				obligation: {source: 'turn_user_message', locator: '', ref_id: '', excerpt: '改完必须跑测试'},
				missing_evidence: [],
				not_claimed: [],
			},
		});
		render(<FindingsView detail={d} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('约束：被折叠移出投影（未送达）');
		expect(text).not.toContain('folded_out');
	});

	it('固定证据的种类出中文，未知种类原样保留', () => {
		expect(pinKindLabel('run_mark')).toBe('结果标记');
		expect(pinKindLabel('verifier')).toBe('验收记录');
		expect(pinKindLabel('future_kind')).toBe('future_kind');
	});
});

describe('审计行字段中文化（P2 17）', () => {
	it('有中文标签的标量字段进状态行，其余进原文块', () => {
		const {shown, raw} = describeAuditRow({
			ts: 1,
			kind: 'sse.frame',
			session_id: 's1',
			turn_id: 't1',
			model_request_id: 'r1',
			tool_name: 'Bash',
			provider: {name: 'deepseek'},
			attempt: 2,
			is_error: true,
		});
		expect(shown).toEqual(['模型请求 r1', '工具 Bash', '尝试 2', '返回错误 是']);
		// 嵌套值不产出 `provider=` 这种吊尾标签，而是留在原文块里以 JSON 呈现。
		expect(raw.map(f => f.key)).toEqual(['provider']);
		expect(raw[0]!.value).toBe('{"name":"deepseek"}');
	});

	it('时间线里未收录的审计类型不照抄机器名到标题', () => {
		const d = detail({
			events: [
				{
					seq: 1,
					line_no: 42,
					kind: 'session.resume',
					ts: 5,
					session_id: 's1',
					turn_id: 't1',
					row: {session_id: 's1', model_request_id: 'r1', provider: 'deepseek'},
					evidence: {source: 'audit', locator: '/x/audit.jsonl', ref_id: 'L42', detail: ''},
				},
			],
		});
		render(<StepsView detail={d} loadingMore={false} onLoadMore={() => {}} />);
		const text = document.body.textContent ?? '';
		expect(text).toContain('审计记录（未收录类型）');
		// 折叠前不出现 `session_id=…` / `provider=` 这类英文键值对
		expect(text).not.toMatch(/session_id=/);
		expect(text).not.toMatch(/provider=/);
		expect(text).toContain('模型请求 r1');
	});
});

describe('静默轮询不吞掉手工翻页（P1 8）', () => {
	function eventsOf(prefix: string, from: number, to: number) {
		const out = [];
		for (let line = from; line < to; line += 1) {
			out.push({
				seq: line,
				line_no: line,
				kind: `job.${prefix}`,
				ts: line,
				session_id: 's1',
				turn_id: 't1',
				row: {},
				evidence: {source: 'audit', locator: '', ref_id: `L${line}`, detail: ''},
			});
		}
		return out;
	}

	it('第 0 页回来后保留已手工加载的后续页', () => {
		const loaded = detail({
			events: [...eventsOf('a', 0, 600)],
			event_total: 900,
			event_offset: 400,
			event_limit: 200,
			events_complete: false,
		});
		const polled = detail({
			events: [...eventsOf('b', 0, 200)],
			event_total: 900,
			event_offset: 0,
			event_limit: 200,
			events_complete: false,
		});
		const merged = mergeDetailPreservingLoadedPages(loaded, polled);
		expect(merged.events).toHaveLength(600);
		// 游标不倒退：下一次「继续加载」仍从 600 起
		expect(merged.event_offset).toBe(400);
		expect(merged.events[0].line_no).toBe(0);
		expect(merged.events[599].line_no).toBe(599);
	});

	it('轮询已覆盖全集时以轮询为准，不保留旧行', () => {
		const loaded = detail({events: eventsOf('a', 0, 600), event_total: 600, event_limit: 200, event_offset: 400});
		const polled = detail({events: eventsOf('b', 0, 600), event_total: 600, event_limit: 600, event_offset: 0, events_complete: true});
		const merged = mergeDetailPreservingLoadedPages(loaded, polled);
		expect(merged.events.map(e => e.kind)).toEqual(polled.events.map(e => e.kind));
	});
});

describe('深链选择不得顶替用户那一击（P1 11）', () => {
	const runs = parseRunsResult({
		schema_version: 1,
		session_id: 's1',
		complete: true,
		runs: [
			{turn_id: 't1', tool_use_ids: ['call_1']},
			{turn_id: 't2', tool_use_ids: ['call_2']},
		],
	});

	it('tool 命中时选中的是那一轮', () => {
		const sel = selectTurnAfterRunsLoaded({runs, currentTurn: '', deepTurn: '', toolHint: 'call_2'});
		expect(sel).toEqual({turnId: 't2', mismatch: null, toolResolved: true});
	});

	it('tool 不在尾窗里时保留原选择并报不匹配，绝不默认第一条', () => {
		const sel = selectTurnAfterRunsLoaded({runs, currentTurn: 't1', deepTurn: '', toolHint: 'call_9'});
		expect(sel.turnId).toBe('t1');
		expect(sel.mismatch).toEqual({kind: 'tool', value: 'call_9'});
		expect(sel.toolResolved).toBe(false);
	});

	it('深链 turn 不在尾窗里时同样不自动改选', () => {
		const sel = selectTurnAfterRunsLoaded({runs, currentTurn: '', deepTurn: 't9', toolHint: ''});
		expect(sel.turnId).toBe('');
		expect(sel.mismatch).toEqual({kind: 'turn', value: 't9'});
	});

	it('无深链时保留当前选择，当前选择已消失才回落第一条', () => {
		expect(
			selectTurnAfterRunsLoaded({runs, currentTurn: 't2', deepTurn: '', toolHint: ''}).turnId,
		).toBe('t2');
		expect(
			selectTurnAfterRunsLoaded({runs, currentTurn: 'gone', deepTurn: '', toolHint: ''}).turnId,
		).toBe('t1');
	});

	it('回落第一条会把用户点过的轮次换掉时必须报出来（静默换选＝正文自己跳）', () => {
		expect(
			selectTurnAfterRunsLoaded({runs, currentTurn: 'gone', deepTurn: '', toolHint: ''})
				.mismatch,
		).toEqual({kind: 'replaced', value: 'gone', alt: 't1'});
		// 从没有选过（首屏）时回落第一条不算改选，不该出提示。
		expect(
			selectTurnAfterRunsLoaded({runs, currentTurn: '', deepTurn: '', toolHint: ''}).mismatch,
		).toBeNull();
	});
});

describe('实验请求体对齐后端契约（P1 3）', () => {
	it('mode 小写、两臂走 variants、次数走 repeat、不带服务端没有的键', () => {
		const body = buildExperimentBody({
			mode: 'a1',
			sessionId: 's1',
			turnId: 't1',
			variantA: {blocks: {system: 'a'}},
			variantB: {blocks: {system: 'b'}},
			repeat: 3,
			budgetCny: 12.5,
		}) as Record<string, unknown>;
		expect(body.mode).toBe('a1');
		expect(body.variants).toEqual({A: {blocks: {system: 'a'}}, B: {blocks: {system: 'b'}}});
		expect(body.repeat).toBe(3);
		expect(body.budget_cny).toBe(12.5);
		expect(body.task_id).toContain('s1');
		// 服务端 pydantic 是 extra='ignore'：这些键发过去等于静默丢弃，必须根本不发
		expect(body.baseline).toBeUndefined();
		expect(body.candidate).toBeUndefined();
		expect(body.repeats).toBeUndefined();
		expect(body.session_id).toBeUndefined();
		expect(body.turn_id).toBeUndefined();
	});

	it('预算不是有限数字时不发送该字段（NaN 会被序列化成 null，读作"不设上限"）', () => {
		const body = buildExperimentBody({
			mode: 'a0',
			sessionId: 's1',
			turnId: 't1',
			variantA: {},
			variantB: {},
			repeat: 1,
			budgetCny: null,
		}) as Record<string, unknown>;
		expect('budget_cny' in body).toBe(false);
	});
});

describe('证据缺项的中文口径与"零结论"的指向', () => {
	// 后端把"缺席/归属不了/不可比"这类事实挪进缺项清单后，界面必须还能读：
	// 一是新原因码要有中文，二是"没有结论"要指得出缺项在哪，不能读成全清白。
	it('新原因码有中文口径，未知原因码原样带出不被吞', () => {
		expect(gapReasonLabel('unattributed_rows')).toBe('行内没有可归属的身份');
		expect(gapReasonLabel('no_records')).toBe('该来源对本会话没有记录行');
		expect(gapReasonLabel('not_comparable')).toBe('字段粒度不支持这个判断');
		expect(gapReasonLabel('field_missing')).toBe('记录里缺该字段');
		// 采集层扩窗重读的两个结果：找回来了和读完整份仍没有，是两件事。
		expect(gapReasonLabel('recovered_outside_window')).toBe('尾窗外的记录已扩窗读回');
		expect(gapReasonLabel('not_found_in_full_file')).toBe('读完整份记录仍无本轮身份');
		expect(gapReasonLabel('brand_new_code')).toContain('brand_new_code');
	});

	it('零结论时把缺项条数说出来（缺项是"判不了"的原因）', () => {
		render(
			<FindingsView
				detail={detail({
					findings: [],
					gaps: [
						{boundary: 'model_request', reason: 'unattributed_rows', detail: '1 笔用量不带 request_id'},
						{boundary: 'wsc_fold', reason: 'no_records', detail: '本会话没有折叠记录行'},
					],
				})}
			/>
		);
		expect(document.body.textContent).toContain('采集侧记了 2 项证据缺项');
	});

	it('既无结论也无缺项时不编造缺项条数', () => {
		render(<FindingsView detail={detail({findings: [], gaps: []})} />);
		expect(document.body.textContent).not.toMatch(/采集侧记了/);
	});

	it('缺项的阶段用中文标签，不裸露 snake_case', () => {
		render(
			<ContextView
				detail={detail({
					gaps: [{boundary: 'adapter', reason: 'source_absent', detail: 'wire_drops 账本不存在'}],
				})}
				sessionId="s1"
				turnId="t1"
				storeRoot="/diag"
			/>,
		);
		const list = document.querySelector('.xy-dig-gap-boundary')?.textContent ?? '';
		expect(list).toBe('适配器最终请求');
	});
});
