import {act, fireEvent, render} from '@testing-library/react';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {TurnRail, type TurnRailItem} from './TurnRail';

function makeItems(n: number): TurnRailItem[] {
	return Array.from({length: n}, (_, i) => ({
		id: `r${i}`,
		label: `round ${i}`,
	}));
}

describe('TurnRail', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
	});

	it('renders null for fewer than 2 rounds', () => {
		const {container} = render(
			<TurnRail items={makeItems(1)} activeId={null} onJump={() => {}} />,
		);
		expect(container.firstChild).toBeNull();
	});

	it('small sessions: full panel, no spacers (exact legacy DOM)', () => {
		// 12 ≤ MAX_TICKS(15) 且 ≤ WINDOW_THRESHOLD(60)：idle 刻度 = 全部轮次。
		const items = makeItems(12);
		const {container} = render(
			<TurnRail items={items} activeId={null} onJump={() => {}} />,
		);
		const rows = container.querySelectorAll('[data-rail-id]');
		expect(rows).toHaveLength(items.length);
		// 窗口化路径的 spacer 是 aria-hidden 的纯高度 div；非窗口路径不存在。
		const spacers = container.querySelectorAll(
			'.xy-turn-rail-list > div[aria-hidden="true"]',
		);
		expect(spacers).toHaveLength(0);
		expect(container.querySelectorAll('[data-rail-tick]')).toHaveLength(
			items.length,
		);
	});

	it('huge sessions: idle ticks capped, panel rows windowed with spacers', () => {
		const items = makeItems(300);
		const {container} = render(
			<TurnRail items={items} activeId={null} onJump={() => {}} />,
		);
		// idle 刻度恒 ≤ 15。
		expect(
			container.querySelectorAll('[data-rail-tick]').length,
		).toBeLessThanOrEqual(15);
		// 挂载的行数有界（OVERSCAN×2 + 视口，jsdom clientHeight=0 → 12 行）。
		const rows = container.querySelectorAll('[data-rail-id]');
		expect(rows.length).toBeGreaterThan(0);
		expect(rows.length).toBeLessThanOrEqual(20);
		// 底部 spacer 补齐剩余高度：jsdom rowH 兜底 26px。
		const spacers = container.querySelectorAll(
			'.xy-turn-rail-list > div[aria-hidden="true"]',
		);
		expect(spacers.length).toBe(1); // start=0 → 只有底 spacer
		expect(spacers[0]!.getAttribute('style')).toContain(
			`${(300 - rows.length) * 26}px`,
		);
	});

	it('opening the panel scrolls the active round into view (nearest)', () => {
		const items = makeItems(300);
		const activeId = items[250]!.id;
		const {container} = render(
			<TurnRail items={items} activeId={activeId} onJump={() => {}} />,
		);
		const rail = container.querySelector('.xy-turn-rail')!;
		act(() => {
			fireEvent.mouseEnter(rail);
			vi.advanceTimersByTime(200);
		});
		const list = container.querySelector(
			'.xy-turn-rail-list',
		) as HTMLElement;
		// jsdom clientHeight=0 → "nearest" 退化为把活动行顶到可视区顶：
		// scrollTop = (idx+1) * 26。
		expect(list.scrollTop).toBe(251 * 26);
		// 手动触发 scroll → 窗口应覆盖活动行。
		act(() => {
			fireEvent.scroll(list);
		});
		expect(
			container.querySelector(`[data-rail-id="${activeId}"]`),
		).not.toBeNull();
	});

	it('rows jump via onJump', () => {
		const items = makeItems(30);
		const onJump = vi.fn();
		const {container} = render(
			<TurnRail items={items} activeId={null} onJump={onJump} />,
		);
		fireEvent.click(
			container.querySelector('[data-rail-id="r7"]') as HTMLElement,
		);
		expect(onJump).toHaveBeenCalledWith('r7');
	});

	it('getBadge is only called for mounted rows (lazy badge)', () => {
		const items = makeItems(300);
		const getBadge = vi.fn(() => '1/2');
		const {container} = render(
			<TurnRail
				items={items}
				activeId={null}
				onJump={() => {}}
				getBadge={getBadge}
				badgeVersion={1}
			/>,
		);
		const rows = container.querySelectorAll('[data-rail-id]');
		// 只对挂载行回调，绝不全量调用（300 项若全扫会调 300 次）。
		expect(getBadge.mock.calls.length).toBe(rows.length);
		expect(getBadge.mock.calls.length).toBeLessThanOrEqual(20);
		// badge 渲染进面板行。
		expect(container.querySelector('.xy-turn-rail-badge')).not.toBeNull();
	});

	it('badgeVersion bump re-evaluates badges with same getBadge', () => {
		const items = makeItems(12);
		const onJump = () => {};
		const badges = new Map<string, string>([['r3', '1/2']]);
		const getBadge = (id: string) => badges.get(id);
		const {container, rerender} = render(
			<TurnRail
				items={items}
				activeId={null}
				onJump={onJump}
				getBadge={getBadge}
				badgeVersion={1}
			/>,
		);
		expect(container.querySelector('.xy-turn-rail-badge')!.textContent).toBe(
			'1/2',
		);
		badges.set('r3', '2/2');
		rerender(
			<TurnRail
				items={items}
				activeId={null}
				onJump={onJump}
				getBadge={getBadge}
				badgeVersion={2}
			/>,
		);
		expect(container.querySelector('.xy-turn-rail-badge')!.textContent).toBe(
			'2/2',
		);
		// version 未变且其余 props 引用稳定 → memo 命中 → 不重算 badge。
		badges.delete('r3');
		rerender(
			<TurnRail
				items={items}
				activeId={null}
				onJump={onJump}
				getBadge={getBadge}
				badgeVersion={2}
			/>,
		);
		expect(container.querySelector('.xy-turn-rail-badge')!.textContent).toBe(
			'2/2',
		);
	});
});
