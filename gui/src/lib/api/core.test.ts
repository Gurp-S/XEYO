/**
 * core.test.ts — SSE 解析器的「后端在发 / 前端必须收」契约守卫。
 *
 * 背景：`title`（T5 会话标题）与 `intent`（T3 面板意图）都曾出现
 * 「后端在发、前端静默丢弃」——后端 `chat.py` 组帧齐全，前端
 * `parseSseBlock()` 的 if-chain 缺分支，落到末尾 `return null`。
 * 这类断裂不会报错、不会告警，只能靠契约测试锁住。
 */
import {describe, expect, it} from 'vitest';
import {parseSseBlock} from './core';

/** 组装一条 xy 信封帧（与后端 `_xy_chunk` 同形）。 */
function frame(xy: Record<string, unknown>): string {
	return `data: ${JSON.stringify({xy: {schema_version: '1', ...xy}})}`;
}

describe('parseSseBlock · title 帧（T5）', () => {
	it('解析标题帧并保留 pinned / enhanced', () => {
		const ev = parseSseBlock(
			frame({
				type: 'title',
				title: '修复 SSE 标题帧',
				pinned: false,
				enhanced: true,
				session_id: 'sess-1',
			}),
		);
		expect(ev).not.toBeNull();
		expect(ev && ev.kind).toBe('title');
		if (ev && ev.kind === 'title') {
			expect(ev.title).toBe('修复 SSE 标题帧');
			expect(ev.pinned).toBe(false);
			expect(ev.enhanced).toBe(true);
			expect(ev.sessionId).toBe('sess-1');
		}
	});

	it('pinned 为真时如实透出（消费者据此拒绝覆盖）', () => {
		const ev = parseSseBlock(
			frame({type: 'title', title: '我的自定义名', pinned: true, enhanced: false}),
		);
		if (ev && ev.kind === 'title') {
			expect(ev.pinned).toBe(true);
		} else {
			throw new Error('title 帧未被解析');
		}
	});

	it('空标题不消费（后端首轮 sidecar 缺失时可能为空）', () => {
		expect(parseSseBlock(frame({type: 'title', title: '', pinned: false}))).toBeNull();
		expect(parseSseBlock(frame({type: 'title', pinned: false}))).toBeNull();
	});
});

describe('parseSseBlock · permission_pending.intent（T3）', () => {
	it('透出 intent 字段', () => {
		const ev = parseSseBlock(
			frame({
				type: 'permission_pending',
				request_id: 'r1',
				tool_name: 'Bash',
				input: {},
				reason: '需要确认',
				prompt: 'rm -rf build',
				intent: 'choice',
				choices: ['deny', 'remind', 'allow'],
			}),
		);
		if (ev && ev.kind === 'permission_pending') {
			expect(ev.intent).toBe('choice');
			expect(ev.choices).toEqual(['deny', 'remind', 'allow']);
		} else {
			throw new Error('permission_pending 帧未被解析');
		}
	});

	it('intent 缺失时为 undefined（由消费者按 choices 推导）', () => {
		const ev = parseSseBlock(
			frame({
				type: 'permission_pending',
				request_id: 'r2',
				tool_name: 'Write',
				input: {},
				reason: '',
				prompt: '',
			}),
		);
		if (ev && ev.kind === 'permission_pending') {
			expect(ev.intent).toBeUndefined();
		} else {
			throw new Error('permission_pending 帧未被解析');
		}
	});
});
