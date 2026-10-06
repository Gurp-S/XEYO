/**
 * 诊断页「事实定位」输入：IME 组词中的 Enter 不许触发定位。
 *
 * 与 promptDialog/Composer 同一教义（组词上屏的回车归输入法）。此前只挂了
 * 裸 `key === 'Enter'` ⇒ 组词中按回车会把半截组词当查询打出去
 * （登记 #8 的 ContextView 半；SessionPicker 半经核实是假阳性——它是
 * 纯按钮 combobox，无文本输入面）。
 */
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';

const mocks = vi.hoisted(() => ({trace: vi.fn()}));

vi.mock('@/lib/api/diagnostics', () => ({
	traceDiagFact: (...args: unknown[]) => mocks.trace(...args),
}));

import {ContextView} from './ContextView';

afterEach(() => {
	cleanup();
	mocks.trace.mockReset();
});

function mount() {
	// 最小真实形状：组件读 coverage/windows/boundaries/gaps/captures/folds/…
	// 缺字段会在渲染期崩（as never 不够），逐字段给足空值。
	const detail = {
		schema_version: null,
		session_id: 's1',
		turn_id: 't1',
		generated_at: null,
		coverage: {},
		boundaries: [],
		identity: {
			model_request_ids: [],
			attempt_keys: [],
			tool_use_ids: [],
			approval_ids: [],
			projection_ids: [],
		},
		model_requests: [],
		tool_calls: [],
		permissions: [],
		projections: [],
		usage: [],
		folds: [],
		wire_drops: [],
		captures: [],
		jobs: [],
		pins: [],
		working: {},
		windows: [],
		gaps: [],
		notes: [],
		events: [],
		event_total: 0,
		event_offset: 0,
		event_limit: 0,
		events_complete: true,
		next_event_cursor: '',
		findings: [],
		attribution: null,
		usage_summary: null,
		fault: null,
		versions: {commit: '', branch: '', worktree_state: '', probed_at: null},
	} as never;
	return render(
		<ContextView detail={detail} sessionId="s1" turnId="t1" storeRoot="/tmp" />,
	);
}

function composingEnter(el: Element) {
	const ev = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true});
	Object.defineProperty(ev, 'isComposing', {value: true});
	el.dispatchEvent(ev);
}

describe('ContextView 事实定位 IME', () => {
	it('组词中的 Enter 不触发定位；真实 Enter 才触发', async () => {
		mocks.trace.mockResolvedValue(null);
		mount();
		const input = screen.getByPlaceholderText(
			'输入要定位的事实片段、来源 ID 或工具调用 ID',
		);
		fireEvent.change(input, {target: {value: '半截组词'}});

		composingEnter(input);
		await new Promise(r => setTimeout(r, 0));
		expect(mocks.trace).not.toHaveBeenCalled();

		fireEvent.keyDown(input, {key: 'Enter'});
		await waitFor(() => expect(mocks.trace).toHaveBeenCalledTimes(1));
	});
});
