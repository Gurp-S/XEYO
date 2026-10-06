import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';

import type {LiveUsageDay} from '@/lib/api/liveUsage';
import {TokenActivityHeatmap} from './TokenActivityHeatmap';

const day = (d: string, over: Partial<LiveUsageDay> = {}): LiveUsageDay => ({
	day: d,
	accepted: null,
	requests: 3,
	prompt_tokens: 1000,
	cache_hit: 500,
	cache_miss: 500,
	hit_rate: 0.5,
	c2_count: 0,
	output: 100,
	tokens: 1100,
	cost_cny: 0.1,
	sessions: 1,
	turns: 1,
	hour_counts: Array.from({length: 24}, () => 0),
	hour_unknown: 0,
	by_model: [],
	...over,
});

beforeEach(() => {
	vi.stubGlobal(
		'Element.prototype.getBoundingClientRect',
		function rect(this: HTMLElement) {
			return {left: 10, top: 20, right: 20, bottom: 31, width: 11, height: 11, x: 10, y: 20, toJSON: () => ({})};
		},
	);
});

afterEach(() => {
	cleanup();
	vi.unstubAllGlobals();
});

describe('每天', () => {
	it('画满 53 周 × 7 格，并区分「没跑」与「还没到」', () => {
		const {container} = render(
			<TokenActivityHeatmap
				days={[day('2026-09-30'), day('2026-10-01'), day('2026-10-02')]}
				generatedAt="2026-10-02T10:00:00+08:00"
			/>,
		);
		const cells = container.querySelectorAll('[data-a3-heat]');
		const future = container.querySelectorAll('[data-a3-heat-future]');
		// 每一格要么有值要么"还没到"，两者之和恒等于 53×7（不静默少画）。
		expect(cells.length + future.length).toBe(53 * 7);
		expect(future.length).toBeGreaterThan(0);
		// 强度档写在 data-* 上，判据不必解析内联样式。
		expect(container.querySelector('[data-a3-heat="2026-10-02"]')?.getAttribute('data-a3-heat-level')).toBe('4');
		expect(container.querySelector('[data-a3-heat="2026-09-20"]')?.getAttribute('data-a3-heat-level')).toBe('0');
		expect(container.querySelector('[data-a3-heat="2026-09-20"]')?.getAttribute('data-a3-heat-value')).toBe('0');
	});

	it('悬停出中文读数（日期 + 亿/万），不写 k/M/B', () => {
		render(
			<TokenActivityHeatmap
				days={[day('2026-10-03', {tokens: 1_082_056_006})]}
				generatedAt="2026-10-03T10:00:00+08:00"
			/>,
		);
		fireEvent.mouseOver(screen.getByTitle('10月3日 · 10.8亿 Token'));
		const tip = screen.getByRole('tooltip');
		expect(tip.textContent).toContain('10月3日');
		expect(tip.textContent).toContain('10.8亿');
		expect(tip.textContent).toContain('3 次请求');
	});

	it('tokens 读不出的日子：格子标出来，不画成零活动', () => {
		const {container} = render(
			<TokenActivityHeatmap days={[day('2026-10-03', {tokens: null})]} generatedAt="2026-10-03T10:00:00+08:00" />,
		);
		const cell = container.querySelector('[data-a3-heat="2026-10-03"]');
		expect(cell?.getAttribute('data-a3-heat-value')).toBe('');
		expect(cell?.getAttribute('title')).toContain('读不出来');
	});
});

describe('口径切换', () => {
	it('每周：一列一格；累计总量：折线图', () => {
		const {container} = render(
			<TokenActivityHeatmap
				days={[day('2026-10-01'), day('2026-10-02')]}
				generatedAt="2026-10-03T10:00:00+08:00"
			/>,
		);
		fireEvent.click(screen.getByRole('tab', {name: '每周'}));
		expect(container.querySelectorAll('[data-a3-heat]')).toHaveLength(53);

		fireEvent.click(screen.getByRole('tab', {name: '累计总量'}));
		expect(container.querySelector('[data-a3-cumulative]')).not.toBeNull();
		expect(screen.getByText(/累计 2,200 Token/)).toBeInTheDocument();
	});

	it('账本为空：说没有可分桶的日期，不画空图', () => {
		render(<TokenActivityHeatmap days={[]} generatedAt="2026-10-03T10:00:00+08:00" />);
		expect(screen.getByText('账本里还没有可分桶的日期。')).toBeInTheDocument();
		expect(screen.queryAllByText('Token 活动').length).toBe(1);
	});
});
