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
import {parseRunDetail} from '@/lib/api/diagnostics';
import {FindingsView} from './FindingsView';
import {StepsView} from './StepsView';
import {UsageView} from './UsageView';
import {
	COST_BASIS_LABEL,
	DASH,
	NO_CONFIRMED_FAULT_TEXT,
	NOT_ATTRIBUTED_TEXT,
	fmtClock,
	fmtCostCny,
	fmtDuration,
	fmtInt,
	groupFindingsByStatus,
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
				task_outcome: 'not_accepted',
				task_outcome_label: '未执行验收：无法判定任务是否完成',
				obligation: {text: 'x', source: 'pin', locator: 'p.json', ref_id: 'p0', excerpt: '改完必须跑测试'},
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
