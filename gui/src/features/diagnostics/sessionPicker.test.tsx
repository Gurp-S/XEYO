/**
 * SessionPicker 的行为断言。
 *
 * 它替代的是原生 `<select>`，所以要守住原生实现做不到的四件事：
 * 占位符不再是"一条能选的空值"、长标题截断但全文可达、键盘能走完全程、
 * 没有会话时不画出一个空弹层。
 */
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {SessionPicker} from './SessionPicker';

const SESSIONS = [
	{id: 'sess_a', label: '帮我测试出WSC当前的所有数据，要求所有详细数据'},
	{id: 'sess_b', label: '为什么A3-monitor.html快照之后无内容'},
];

function renderPicker(over: Partial<Parameters<typeof SessionPicker>[0]> = {}) {
	const onPick = vi.fn();
	render(
		<SessionPicker sessions={SESSIONS} value="" onPick={onPick} {...over} />,
	);
	return {onPick, trigger: screen.getByRole('combobox', {name: '会话'})};
}

afterEach(() => {
	cleanup();
});

describe('SessionPicker', () => {
	it('未选择时占位符只在触发器上，不作为可选条目混进列表', () => {
		const {trigger} = renderPicker();
		expect(trigger.textContent).toContain('选择会话');

		fireEvent.click(trigger);

		expect(screen.getAllByRole('option')).toHaveLength(2);
		expect(screen.queryByRole('option', {name: /选择会话/})).toBeNull();
	});

	it('点击一条会话会带上真实 id 回调，并把它标成当前项', () => {
		const {onPick, trigger} = renderPicker();
		fireEvent.click(trigger);
		fireEvent.click(screen.getByRole('option', {name: /A3-monitor/}));

		expect(onPick).toHaveBeenCalledWith('sess_b');
		// 受控组件：外部没有换 value 之前，触发器仍显示原状态（这里=未选）
		expect(trigger.textContent).toContain('选择会话');

		// 外部把 value 传回来之后：触发器显示该会话，列表里它带 aria-selected
		cleanup();
		render(<SessionPicker sessions={SESSIONS} value="sess_b" onPick={() => {}} />);
		const trigger2 = screen.getByRole('combobox', {name: '会话'});
		expect(trigger2.textContent).toContain('A3-monitor');
		fireEvent.click(trigger2);
		expect(
			screen.getByRole('option', {name: /A3-monitor/}).getAttribute('aria-selected'),
		).toBe('true');
	});

	it('重复点击当前项不产生一次"选择"（不触发回调）', () => {
		const {onPick, trigger} = renderPicker({value: 'sess_a'});
		fireEvent.click(trigger);
		fireEvent.click(screen.getByRole('option', {name: /WSC/}));
		expect(onPick).not.toHaveBeenCalled();
	});

	it('键盘走完全程：Enter 打开、↓ 移动、Enter 选中、Esc 关闭', () => {
		const {onPick, trigger} = renderPicker();

		fireEvent.keyDown(trigger, {key: 'Enter'});
		expect(trigger.getAttribute('aria-expanded')).toBe('true');
		// 高亮落在当前值上（未选 → 第 0 项），activedescendant 必须指向真实存在的行
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-0',
		);
		expect(document.getElementById('xeyo-dig-session-listbox-0')).not.toBeNull();

		fireEvent.keyDown(trigger, {key: 'ArrowDown'});
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-1',
		);
		fireEvent.keyDown(trigger, {key: 'End'});
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-1',
		);
		fireEvent.keyDown(trigger, {key: 'Enter'});
		expect(onPick).toHaveBeenCalledWith('sess_b');

		fireEvent.keyDown(trigger, {key: 'Escape'});
		expect(trigger.getAttribute('aria-expanded')).toBe('false');
	});

	it('↓ 走到末尾会回到首项（长列表里 End/Home 之外也能循环）', () => {
		const {trigger} = renderPicker();
		fireEvent.keyDown(trigger, {key: 'ArrowDown'});
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-0',
		);
		fireEvent.keyDown(trigger, {key: 'ArrowDown'});
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-1',
		);
		fireEvent.keyDown(trigger, {key: 'ArrowDown'});
		expect(trigger.getAttribute('aria-activedescendant')).toBe(
			'xeyo-dig-session-listbox-0',
		);
	});

	it('长标题截断但全文可达（option 与触发器都带 title）', () => {
		const {trigger} = renderPicker({value: 'sess_a'});
		expect(trigger.getAttribute('title')).toBe(SESSIONS[0].label);
		fireEvent.click(trigger);
		expect(
			screen.getByRole('option', {name: /WSC/}).getAttribute('title'),
		).toBe(SESSIONS[0].label);
	});

	it('没有会话时说明原因，而不是画一个空弹层', () => {
		render(<SessionPicker sessions={[]} value="" onPick={() => {}} />);
		fireEvent.click(screen.getByRole('combobox', {name: '会话'}));
		expect(screen.queryByRole('listbox')).toBeNull();
		expect(screen.getByText('后端没有可选会话。')).toBeTruthy();
	});

	it('键盘移动会把高亮项滚进可视区（长列表不跟焦就等于看不见）', () => {
		const spy = vi
			.spyOn(HTMLElement.prototype, 'scrollIntoView')
			.mockImplementation(() => {});
		try {
			const {trigger} = renderPicker();
			// 关闭状态不该滚：列表还没进 DOM。
			expect(spy).not.toHaveBeenCalled();

			fireEvent.keyDown(trigger, {key: 'Enter'});
			expect(spy).toHaveBeenCalledTimes(1);

			fireEvent.keyDown(trigger, {key: 'ArrowDown'});
			expect(spy).toHaveBeenCalledTimes(2);
			expect(spy.mock.calls.at(-1)?.[0]).toEqual({block: 'nearest'});

			fireEvent.keyDown(trigger, {key: 'Escape'});
			expect(trigger.getAttribute('aria-expanded')).toBe('false');
			// 关闭态按普通字符既不重开也不滚（Esc 后按 ↑↓ 会重新打开，与原生 select 一致）
			fireEvent.keyDown(trigger, {key: 'a'});
			expect(spy).toHaveBeenCalledTimes(2);
		} finally {
			spy.mockRestore();
		}
	});

	it('空列表下键盘不崩也不"选中"任何东西', () => {
		const onPick = vi.fn();
		render(<SessionPicker sessions={[]} value="" onPick={onPick} />);
		const trigger = screen.getByRole('combobox', {name: '会话'});

		for (const key of ['Enter', 'ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter']) {
			fireEvent.keyDown(trigger, {key});
		}
		expect(onPick).not.toHaveBeenCalled();
		expect(trigger.getAttribute('aria-activedescendant')).toBeNull();
	});
});
