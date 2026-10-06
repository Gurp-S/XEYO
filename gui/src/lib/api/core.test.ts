/**
 * core.test.ts — SSE 解析器的「后端在发 / 前端必须收」契约守卫。
 *
 * 背景：`title`（T5 会话标题）与 `intent`（T3 面板意图）都曾出现
 * 「后端在发、前端静默丢弃」——后端 `chat.py` 组帧齐全，前端
 * `parseSseBlock()` 的 if-chain 缺分支，落到末尾 `return null`。
 * 这类断裂不会报错、不会告警，只能靠契约测试锁住。
 */
import {describe, expect, it, vi} from 'vitest';
import {fetchWithTimeout, parseOpenAiSse, parseSseBlock} from './core';

/** 组装一条 xy 信封帧（与后端 `_xy_chunk` 同形）。 */
function frame(xy: Record<string, unknown>): string {
	return `data: ${JSON.stringify({xy: {schema_version: '1', ...xy}})}`;
}

describe('parseSseBlock · stream_gap 帧（reattach 空洞）', () => {
	it('解析空洞帧并保留两个事件号', () => {
		const ev = parseSseBlock(
			frame({
				type: 'stream_gap',
				dropped_through_event_id: 7,
				first_available_event_id: 8,
			}),
		);
		expect(ev && ev.kind).toBe('stream_gap');
		if (ev && ev.kind === 'stream_gap') {
			expect(ev.droppedThroughEventId).toBe(7);
			expect(ev.firstAvailableEventId).toBe(8);
		}
	});
});

describe('parseSseBlock · usage 上下文快照', () => {
	it('显式 null 表示该请求没有上下文遥测，不会变成 0 token', () => {
		const ev = parseSseBlock(
			frame({type: 'usage', context_tokens: null, context_limit: null}),
		);
		expect(ev && ev.kind).toBe('usage');
		if (ev && ev.kind === 'usage') {
			expect(ev.contextTokens).toBeUndefined();
			expect(ev.contextLimit).toBeUndefined();
		}
	});
});

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

/** SSE 分帧的行尾口径（SSE 规范允许 CR / CRLF，网关常转）。 */
describe('parseOpenAiSse · 行尾与跨块边界', () => {
	async function collect(chunks: string[]) {
		const enc = new TextEncoder();
		let i = 0;
		const body = new ReadableStream<Uint8Array>({
			pull(c) {
				if (i >= chunks.length) {
					c.close();
					return;
				}
				c.enqueue(enc.encode(chunks[i]));
				i += 1;
			},
		});
		const out: string[] = [];
		for await (const ev of parseOpenAiSse(body)) {
			if (ev.kind === 'delta') out.push(`delta:${ev.text}`);
			else if (ev.kind === 'done') out.push('done');
			else out.push(ev.kind);
		}
		return out;
	}

	const a = `data: ${JSON.stringify({choices: [{delta: {content: 'A'}}]})}`;
	const b = `data: ${JSON.stringify({choices: [{delta: {content: 'B'}}]})}`;

	it('LF 分帧（我们后端自己的形态）', async () => {
		expect(await collect([`${a}\n\n${b}\n\ndata: [DONE]\n\n`])).toEqual([
			'delta:A',
			'delta:B',
			'done',
		]);
	});

	it('CRLF 分帧不得把整条流当成一个块而静默丢帧', async () => {
		expect(await collect([`${a}\r\n\r\n${b}\r\n\r\ndata: [DONE]\r\n\r\n`])).toEqual([
			'delta:A',
			'delta:B',
			'done',
		]);
	});

	it('块边界正好落在 CR 与 LF 之间时也要切开', async () => {
		// 分包把 CRLF 拆断：'...\r' | '\n\r\n...'。归一化必须在拼接后进行。
		expect(
			await collect([`${a}\r`, `\n\r\n${b}\r\n\r\n`, 'data: [DONE]\r\n\r\n']),
		).toEqual(['delta:A', 'delta:B', 'done']);
	});
});

describe('fetchWithTimeout · 取消语义', () => {
	/** 假 fetch：只有传进来的 signal 被中止才 reject（模拟原生 fetch 行为）。 */
	function hangingFetch() {
		return vi.fn(
			(_url: string, init?: RequestInit) =>
				new Promise<Response>((_resolve, reject) => {
					init?.signal?.addEventListener('abort', () =>
						reject(new DOMException('aborted', 'AbortError')),
					);
				}),
		);
	}

	it('调用方 signal 取消：原样上抛 AbortError，不谎报「请求超时」', async () => {
		const fake = hangingFetch();
		vi.stubGlobal('fetch', fake);
		try {
			const caller = new AbortController();
			const p = fetchWithTimeout('http://x/', {signal: caller.signal});
			// 等一拍让 fetch 拿到 init（含合并后的 signal）再取消
			await Promise.resolve();
			caller.abort();
			await expect(p).rejects.toMatchObject({name: 'AbortError'});
		} finally {
			vi.unstubAllGlobals();
		}
	});

	it('超时：仍然给出「请求超时」消息（回归护栏）', async () => {
		vi.useFakeTimers();
		const fake = hangingFetch();
		vi.stubGlobal('fetch', fake);
		try {
			const p = fetchWithTimeout('http://x/', undefined, 1000);
			const assertion = expect(p).rejects.toThrow(/请求超时/);
			await vi.advanceTimersByTimeAsync(1001);
			await assertion;
		} finally {
			vi.useRealTimers();
			vi.unstubAllGlobals();
		}
	});
});
