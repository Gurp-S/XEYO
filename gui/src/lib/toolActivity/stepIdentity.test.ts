/**
 * stepIdentity.test.ts — ActivityStep 必须带上后端 tool_use.id。
 *
 * UI 自己的 step.id 来自 ChatMessage.id，历史轮次里它是 `turn-${seq}` 一类的合成值，
 * 不能拿去跳诊断中心；只有 toolUseId 能和审计里的 tool.* 行对上。
 */
import {describe, expect, it} from 'vitest';
import {groupTranscript, type TurnItem} from '@/lib/groupTranscript';
import type {ChatMessage} from '@/lib/types';
import {toolToStep} from '@/lib/toolActivity';

function msg(over: Partial<ChatMessage>): ChatMessage {
	return {
		id: 'm1',
		role: 'user',
		text: '',
		createdAt: 1,
		...over,
	} as ChatMessage;
}

describe('步骤身份', () => {
	it('toolToStep 把 tool_use.id 带到 ActivityStep 上', () => {
		const step = toolToStep({
			id: 'ui-7',
			toolUseId: 'call_4f9a',
			name: 'Read',
			input: '{"file_path":"a.py"}',
			result: 'ok',
			status: 'done',
			createdAt: 1,
		});
		expect(step.toolUseId).toBe('call_4f9a');
		expect(step.id).toBe('ui-7');
	});

	it('没有 tool_use.id 的旧消息不会补一个假 id', () => {
		const step = toolToStep({
			id: 'ui-8',
			name: 'Read',
			input: '',
			result: '',
			status: 'done',
			createdAt: 1,
		});
		expect(step.toolUseId ?? '').toBe('');
	});

	it('分组时 ChatMessage 上的 toolUseId 会落到 ToolView', () => {
		const blocks = groupTranscript([
			msg({id: 'a1', role: 'assistant', text: '读一下'}),
			msg({
				id: 't1',
				role: 'tool',
				text: '',
				toolName: 'Read',
				toolUseId: 'call_77',
				toolInput: '{"file_path":"a.py"}',
				toolStatus: 'done',
			}),
		]);
		const ids: Array<string | undefined> = [];
		for (const block of blocks) {
			for (const item of (block as {items?: TurnItem[]}).items ?? []) {
				if (item.kind === 'tool') ids.push(item.tool.toolUseId);
			}
		}
		expect(ids).toContain('call_77');
	});
});
