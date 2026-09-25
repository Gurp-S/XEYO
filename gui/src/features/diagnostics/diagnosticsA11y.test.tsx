/**
 * 诊断三视图的"可操作性"断言：展开行必须真的连着被展开的那块内容，
 * 异步结果必须有读屏播报，宽表必须有可访问名，载荷身份不符必须说出来。
 *
 * 这些都不是样式装饰：缺 aria-controls 时读屏用户点开了却不知道展开了什么；
 * 缺 role=status 时异步筛选结果对他们是静默的；后端回了另一轮的事实却静默丢弃，
 * 用户看到的就是"按钮坏了"。
 */
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {parseRunDetail, traceDiagFact} from '@/lib/api/diagnostics';
import {ContextView} from './ContextView';
import {FindingsView} from './FindingsView';
import {StepsView} from './StepsView';
import {UsageView} from './UsageView';

vi.mock('@/lib/api/diagnostics', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api/diagnostics')>();
	return {
		...actual,
		traceDiagFact: vi.fn(async () => ({
			turn_id: 'other_turn',
			stages: [],
			unprovable_stages: [],
			verdict: 'unknown',
			statement: '',
			caveat: '',
		})),
	};
});

function detail(raw: Record<string, unknown> = {}) {
	return parseRunDetail({
		schema_version: 1,
		session_id: 's1',
		turn_id: 't1',
		...raw,
	});
}

const WITH_STEP = {
	model_requests: [
		{
			model_request_id: 'r1',
			model: 'deepseek-chat',
			attempt_keys: ['r1#1'],
			attempts: [{attempt: 1, kind: 'model.started', ts: 1.2}],
		},
	],
	usage: [
		{
			attempt_key: 'r1#1',
			vendor: 'deepseek',
			provider: 'deepseek',
			model: 'deepseek-chat',
			cache_hit: 10,
			cache_miss: 5,
			output: 2,
			cost_cny: 0.01,
			cost_source: 'local_pricing',
		},
	],
};

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('「步骤」视图的展开联动', () => {
	it('aria-controls 一直指向真实存在的面板；收起靠 inert 退出可达性树', () => {
		render(<StepsView detail={detail(WITH_STEP)} loadingMore={false} onLoadMore={() => {}} />);
		const head = document.querySelector<HTMLButtonElement>('.xy-dig-step-head');
		expect(head).not.toBeNull();
		expect(head?.getAttribute('aria-expanded')).toBe('false');
		// 面板常驻（收放要有高度可动画的对象），所以引用永不悬空；
		// 代价是可达性隔离必须显式做，否则"看不见却能 tab 到、读屏念得到"。
		const id = head?.getAttribute('aria-controls') ?? '';
		expect(id).toBeTruthy();
		const panel = document.getElementById(id);
		expect(panel).not.toBeNull();
		expect(panel?.hasAttribute('inert')).toBe(true);
		expect(panel?.getAttribute('aria-hidden')).toBe('true');
		// 没点过的行不挂正文：时间线可能几百行，全量常驻不值当。
		expect(panel?.textContent).toBe('');

		fireEvent.click(head!);

		expect(head?.getAttribute('aria-expanded')).toBe('true');
		expect(panel?.hasAttribute('inert')).toBe(false);
		expect(panel?.getAttribute('aria-hidden')).toBe('false');
		expect(panel?.textContent).toContain('事件类型');

		fireEvent.click(head!);
		// 收起后正文留着（再展开才有动画），但对辅助技术不可达。
		expect(panel?.hasAttribute('inert')).toBe(true);
		expect(panel?.textContent).toContain('事件类型');
	});

	it('筛选到空来源时的提示对读屏器可见（role=status）', () => {
		render(<StepsView detail={detail(WITH_STEP)} loadingMore={false} onLoadMore={() => {}} />);
		const chip = [...document.querySelectorAll<HTMLButtonElement>('.xy-dig-chip')].find(
			b => b.textContent?.startsWith('权限'),
		);
		expect(chip).toBeDefined();
		fireEvent.click(chip!);
		expect(screen.getByRole('status').textContent).toContain('该来源在本轮没有记录');
	});
});

describe('「问题」视图的展开面板', () => {
	const f = (phenomenon: string) => ({
		rule_id: 'tool_failure',
		rule_version: 1,
		boundary: 'tool',
		component: '工具执行',
		status: 'confirmed_fault',
		phenomenon,
		impact: `影响：${phenomenon}`,
		allowed_conclusion: '可下的结论',
		coverage_gap: '看不到的范围',
		evidence: [],
	});
	const panels = () =>
		[...document.querySelectorAll<HTMLElement>('.xy-dig-finding-panel')];

	it('收起的面板留在 DOM 但退出可达性树；展开后两者都撤掉', () => {
		render(<FindingsView detail={detail({findings: [f('工具 Bash 返回错误')]})} />);
		const head = document.querySelector<HTMLButtonElement>('.xy-dig-finding-head');
		const panel = panels()[0];
		expect(head).not.toBeNull();
		expect(panel).not.toBeNull();
		expect(panel.hasAttribute('inert')).toBe(true);
		expect(panel.getAttribute('aria-hidden')).toBe('true');
		// 面板常驻是高度动画的前提，所以可达性隔离必须显式做，
		// 否则"看不见但能 tab 到、读屏念得到"。
		expect(head?.getAttribute('aria-controls')).toBe(panel.id);

		fireEvent.click(head!);

		expect(panel.hasAttribute('inert')).toBe(false);
		expect(panel.getAttribute('aria-hidden')).toBe('false');
		expect(panel.textContent).toContain('影响：工具 Bash 返回错误');
	});

	it('前面一条结论被删掉时，展开态不得跟到后面那条上', () => {
		// 同一规则 + 同一边界可以出多条（实测 tool_failure 对 Bash / Edit 各一条）。
		// 用下标当 key 的一半时，[A,B] → [B] 会让 B 顶到 A 的位置、继承 A 的展开态：
		// 用户点开的是 Bash，看到的却是 Edit 的正文。
		const {rerender} = render(
			<FindingsView detail={detail({findings: [f('A'), f('B')]})} />,
		);
		fireEvent.click(document.querySelectorAll('.xy-dig-finding-head')[0]!);
		expect(panels()[0]?.textContent).toContain('影响：A');

		rerender(<FindingsView detail={detail({findings: [f('B')]})} />);

		expect(document.querySelectorAll('.xy-dig-finding')).toHaveLength(1);
		expect(panels()[0]?.hasAttribute('inert')).toBe(true);
		expect(panels()[0]?.textContent).not.toContain('影响：A');
	});
});

describe('「用量」视图的表格可访问名', () => {
	it('两张宽表都有名字，读屏时不是"某张表"', () => {
		render(<UsageView detail={detail(WITH_STEP)} />);
		expect(screen.getByRole('table', {name: '用量账本原始行'})).toBeTruthy();
	});

	it('cost_sources 为空时是「没有记录」，不是空白', () => {
		render(
			<UsageView
				detail={detail({
					...WITH_STEP,
					usage_summary: {
						finished_attempts: 1,
						priced_attempts: 1,
						unknown_cost_attempts: 0,
						cost_sources: [],
						unlinked_usage_rows: 0,
						unknown_cost_keys: [],
						statement: '',
						cost_basis: '按 usage 估算',
					},
				})}
			/>,
		);
		expect(document.body.textContent).toContain('账本里没有计价来源记录');
	});
});

describe('「上下文」视图的载荷自证', () => {
	it('后端回了另一轮的事实要明确说出来，不能静默丢弃', async () => {
		vi.mocked(traceDiagFact).mockResolvedValueOnce({
			turn_id: 'other_turn',
			stages: [],
			unprovable_stages: [],
			verdict: 'unknown',
			statement: '',
			caveat: '',
		} as never);
		render(<ContextView detail={detail()} sessionId="s1" turnId="t1" storeRoot="/diag" />);
		const input = document.querySelector<HTMLInputElement>('.xy-dig-input');
		expect(input).not.toBeNull();
		fireEvent.change(input!, {target: {value: '某条事实'}});
		fireEvent.click(screen.getByRole('button', {name: '定位'}));

		await waitFor(() =>
			expect(document.body.textContent).toContain('与当前轮 t1 不符，未展示'),
		);
		// 提示必须同时是 live 区，否则异步到达的那句话对读屏器不存在。
		expect(screen.getByRole('status').textContent).toContain('不符，未展示');
		expect(document.querySelector('.xy-dig-fact')).toBeNull();
	});

	it('定位请求进行中按钮带 aria-busy', async () => {
		// 用数组持有 release：写成 `let release: (()=>void)|null = null` 时
		// TS 的窄化会认为 Promise 执行器里的赋值没发生，调用点被判成 never。
		const releasers: Array<() => void> = [];
		vi.mocked(traceDiagFact).mockImplementationOnce(
			() =>
				new Promise(resolve => {
					releasers.push(() =>
						resolve({
							turn_id: 't1',
							stages: [],
							unprovable_stages: [],
							verdict: 'unknown',
							statement: '',
							caveat: '',
						} as never),
					);
				}),
		);
		render(<ContextView detail={detail()} sessionId="s1" turnId="t1" storeRoot="/diag" />);
		fireEvent.change(document.querySelector<HTMLInputElement>('.xy-dig-input')!, {
			target: {value: '片段'},
		});
		const btn = screen.getByRole('button', {name: '定位'});
		fireEvent.click(btn);
		expect(btn.getAttribute('aria-busy')).toBe('true');
		releasers[0]?.();
		await waitFor(() => expect(btn.getAttribute('aria-busy')).toBe('false'));
	});
});
