import {describe, expect, it} from 'vitest';
import {arbitrateSlashMenuKey} from '@/lib/slashMenuKeys';

describe('arbitrateSlashMenuKey', () => {
	it('IME 组词期间一切按键放行', () => {
		for (const key of ['up', 'down', 'enter', 'tab', 'escape'] as const) {
			expect(
				arbitrateSlashMenuKey({key, composing: true, highlight: 0, count: 3}),
			).toEqual({type: 'pass'});
		}
	});

	it('Esc 关闭弹层（即使无候选）', () => {
		expect(
			arbitrateSlashMenuKey({key: 'escape', composing: false, highlight: null, count: 0}),
		).toEqual({type: 'close'});
	});

	it('↑↓ 在无高亮时从边缘进入（↓ 第一项 / ↑ 最后一项），环形滚动', () => {
		expect(
			arbitrateSlashMenuKey({key: 'down', composing: false, highlight: null, count: 3}),
		).toEqual({type: 'move', dir: 1, next: 0});
		expect(
			arbitrateSlashMenuKey({key: 'up', composing: false, highlight: null, count: 3}),
		).toEqual({type: 'move', dir: -1, next: 2});
		expect(
			arbitrateSlashMenuKey({key: 'down', composing: false, highlight: 2, count: 3}),
		).toEqual({type: 'move', dir: 1, next: 0});
		expect(
			arbitrateSlashMenuKey({key: 'up', composing: false, highlight: 0, count: 3}),
		).toEqual({type: 'move', dir: -1, next: 2});
	});

	it('无候选时 ↑↓ 放行', () => {
		expect(
			arbitrateSlashMenuKey({key: 'down', composing: false, highlight: null, count: 0}),
		).toEqual({type: 'pass'});
	});

	it('Enter/Tab：有高亮选中该行，无高亮放行（Enter 落到提交）', () => {
		expect(
			arbitrateSlashMenuKey({key: 'enter', composing: false, highlight: 1, count: 3}),
		).toEqual({type: 'pick', index: 1});
		expect(
			arbitrateSlashMenuKey({key: 'tab', composing: false, highlight: 0, count: 3}),
		).toEqual({type: 'pick', index: 0});
		expect(
			arbitrateSlashMenuKey({key: 'enter', composing: false, highlight: null, count: 3}),
		).toEqual({type: 'pass'});
		expect(
			arbitrateSlashMenuKey({key: 'tab', composing: false, highlight: null, count: 0}),
		).toEqual({type: 'pass'});
	});

	it('越界高亮视为无高亮（防陈旧 state）', () => {
		expect(
			arbitrateSlashMenuKey({key: 'enter', composing: false, highlight: 5, count: 3}),
		).toEqual({type: 'pass'});
	});
});
