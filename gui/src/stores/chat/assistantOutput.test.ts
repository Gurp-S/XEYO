import {describe, expect, it} from 'vitest';
import {createAssistantOutput} from './assistantOutput';
import {mergeTranscript} from '@/lib/transcriptOrder';
import type {ChatMessage} from '@/lib/types';

const row = (id: string, role: ChatMessage['role'], text: string, createdAt = 1): ChatMessage =>
	({id, role, text, createdAt});

describe('assistant output / queue projection handoff', () => {
	it('drain, queue backfill and final commit keep one output in canonical order', () => {
		const output = createAssistantOutput(); output.begin('output-1');
		const prompt = row('u1', 'user', 'first', 10000);
		const queued = {...row('u2', 'user', 'next', 11000), queueState: 'queued' as const};
		const drained = output.append([prompt, queued], 'answer');
		const server = [prompt, row('output-1', 'assistant', 'answer', 2),
			row('u2', 'user', 'next', 3), row('output-2', 'assistant', 'next answer', 4)];
		const backfilled = mergeTranscript(drained, server);
		const committed = output.append(backfilled, 'answer');
		expect(committed.map(m => m.id)).toEqual(server.map(m => m.id));
	});
	it('identical text in separate model outputs remains separate', () => {
		const output = createAssistantOutput(); output.begin('a1');
		let messages = output.append([], 'same'); output.begin('a2');
		messages = output.append(messages, 'same');
		expect(messages.map(m => m.id)).toEqual(['a1', 'a2']);
	});
	it('tool segment flush and a subsequent prose tail share their transcript identity', () => {
		const output = createAssistantOutput(); output.begin('a1');
		let messages = output.append([], 'before '); output.finishSegment('before ');
		messages.push(row('tool', 'tool', 'result'));
		messages = output.append(messages, 'after');
		expect(messages.map(m => m.text)).toEqual(['before after', 'result']);
		expect(output.append(messages, 'after')).toBe(messages);
	});
});
