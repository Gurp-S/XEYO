/**
 * 侧栏会话行的截断可复原守卫。
 *
 * 复现的缺陷：标题那一格是 `min-w-0 flex-1 truncate`，但整行的 title 属性只在
 * 有 peerLabel 时才写 → 绝大多数被截断的标题没有任何 tooltip，文本被截掉就找不回来了。
 * 现在：标题格自己带 title（有 peer 时把「也在改 xxx」并进去，一条都不丢），
 * peer 摘要那一格也带自己的 title。
 */
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {SessionRow} from './SessionBits';

const LONG_TITLE = '把工作区样式重做的那条时间线折叠规则先简化掉再验收一遍';

type RowProps = Parameters<typeof SessionRow>[0];

function row(overrides: Partial<RowProps> = {}) {
	const onSelect = vi.fn();
	const onMenu = vi.fn();
	const props: RowProps = {
		session: {id: 's1', title: LONG_TITLE, updatedAt: 1_700_000_000_000},
		active: false,
		running: false,
		onSelect,
		onMenu,
		affordanceTitle: '对话操作',
		...overrides,
	};
	render(<SessionRow {...props} />);
	return {onSelect, onMenu};
}

/** 标题那一格（带 flex-1 truncate 的那个 span），不是 peer / 时间那一格。 */
function titleCell(): HTMLElement {
	const el = document.querySelector('span.truncate.flex-1') as HTMLElement | null;
	if (!el) throw new Error('找不到标题格');
	return el;
}

/** 行主按钮（第一个 button；第二个是悬浮的「···」菜单按钮）。 */
function mainButton(): HTMLElement {
	return screen.getAllByRole('button')[0];
}

describe('SessionRow 截断可复原', () => {
	afterEach(cleanup);

	it('没有 peer 时标题格仍带完整标题的 title', () => {
		row();
		expect(titleCell().textContent).toBe(LONG_TITLE);
		expect(titleCell()).toHaveAttribute('title', LONG_TITLE);
	});

	it('有 peer 时标题格同时给出完整标题与「也在改」', () => {
		row({peerLabel: 'Zoe'});
		const t = titleCell().getAttribute('title') ?? '';
		expect(t).toContain(LONG_TITLE);
		expect(t).toContain('也在改 Zoe');
		// peer 摘要那一格截断后也能复原；按钮整行的原 tooltip 文案没改名
		expect(screen.getByText('Zoe')).toHaveAttribute('title', '也在改 Zoe');
		expect(mainButton()).toHaveAttribute('title', '也在改 Zoe');
	});

	it('归档行的标题照样可复原', () => {
		row({
			session: {id: 's1', title: LONG_TITLE, updatedAt: 1, archived: true},
		});
		expect(titleCell()).toHaveAttribute('title', LONG_TITLE);
	});

	it('点击与三点菜单的行为不变', () => {
		const {onSelect, onMenu} = row();
		const main = mainButton();
		fireEvent.click(main);
		expect(onSelect).toHaveBeenCalledTimes(1);
		fireEvent.contextMenu(main);
		expect(onMenu).toHaveBeenCalledTimes(1);
		fireEvent.click(screen.getByRole('button', {name: '对话操作'}));
		expect(onMenu).toHaveBeenCalledTimes(2);
	});
});
