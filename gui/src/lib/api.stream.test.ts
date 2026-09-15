import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('@/stores/settingsStore', () => {
	const state = {
		apiKey: 'k',
		provider: 'deepseek',
		model: 'deepseek-v4-flash',
		// streamChat 读 profiles/activeProfileId（chatStream.ts:48），mock 需对齐
		// settingsStore 初始态（profiles: [], activeProfileId: ''）。
		profiles: [],
		activeProfileId: '',
		resolvedBaseUrl: () => 'https://api.deepseek.com/v1',
	};
	const useSettingsStore = Object.assign(
		(sel?: (s: typeof state) => unknown) => (sel ? sel(state) : state),
		{getState: () => state},
	);
	return {useSettingsStore};
});

import {fetchVendorModels, loadServerSessionMessages, streamChat} from './api';

function sseResponse(chunks: string[]): Response {
	const enc = new TextEncoder();
	let i = 0;
	const stream = new ReadableStream<Uint8Array>({
		pull(controller) {
			if (i >= chunks.length) {
				controller.close();
				return;
			}
			controller.enqueue(enc.encode(chunks[i]));
			i += 1;
		},
	});
	return new Response(stream, {
		status: 200,
		headers: {'Content-Type': 'text/event-stream'},
	});
}

describe('streamChat SSE — normal / extreme', () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal('fetch', fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('parses content deltas and DONE', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {"choices":[{"delta":{"content":"A"}}]}\n\n',
				'data: {"choices":[{"delta":{"content":"B"}}]}\n\n',
				'data: [DONE]\n\n',
			]),
		);
		const deltas: string[] = [];
		await streamChat('s1', 'hi', {
			onDelta: t => deltas.push(t),
			onDone: () => deltas.push('DONE'),
			onError: m => deltas.push(`ERR:${m}`),
		});
		expect(deltas).toEqual(['A', 'B', 'DONE']);
	});

	it('handles split frames across reads', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {"choices":[{"delta":{"content":"hel',
				'lo"}}]}\n\n data: [DONE]\n\n',
			]),
		);
		const deltas: string[] = [];
		await streamChat('s1', 'hi', {
			onDelta: t => deltas.push(t),
			onDone: () => undefined,
			onError: () => undefined,
		});
		expect(deltas.join('')).toBe('hello');
	});

	it('ignores malformed JSON lines', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {not-json\n\n',
				'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
				'data: [DONE]\n\n',
			]),
		);
		const deltas: string[] = [];
		await streamChat('s1', 'hi', {
			onDelta: t => deltas.push(t),
			onDone: () => undefined,
			onError: m => deltas.push(`ERR:${m}`),
		});
		expect(deltas).toEqual(['ok']);
	});

	it('surfaces SSE error object via onError', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {"error":{"message":"auth fail"}}\n\n',
			]),
		);
		let err = '';
		await streamChat('s1', 'hi', {
			onDelta: () => undefined,
			onDone: () => undefined,
			onError: m => {
				err = m;
			},
		});
		expect(err).toContain('auth fail');
	});

	it('onError when HTTP not ok', async () => {
		fetchMock.mockResolvedValue(
			new Response(JSON.stringify({detail: 'session busy'}), {
				status: 409,
			}),
		);
		let err = '';
		await streamChat('s1', 'hi', {
			onDelta: () => undefined,
			onDone: () => undefined,
			onError: m => {
				err = m;
			},
		});
		expect(err).toContain('session busy');
	});

	it('onError when missing API key', async () => {
		const {useSettingsStore} = await import('@/stores/settingsStore');
		const st = useSettingsStore.getState() as {apiKey: string};
		const prev = st.apiKey;
		st.apiKey = '';
		let err = '';
		await streamChat('s1', 'hi', {
			onDelta: () => undefined,
			onDone: () => undefined,
			onError: m => {
				err = m;
			},
		});
		st.apiKey = prev;
		expect(err).toMatch(/API Key/i);
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('trailing frame without final blank line still flushes', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {"choices":[{"delta":{"content":"z"}}]}\n\ndata: [DONE]',
			]),
		);
		const deltas: string[] = [];
		await streamChat('s1', 'hi', {
			onDelta: t => deltas.push(t),
			onDone: () => deltas.push('DONE'),
			onError: () => undefined,
		});
		expect(deltas).toEqual(['z', 'DONE']);
	});

	it('parses xy tool_call / tool_result side-channel (#8)', async () => {
		fetchMock.mockResolvedValue(
			sseResponse([
				'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
				'data: {"xy":{"type":"tool_call","name":"echo","input":{"x":1},"tool_use_id":"c1"},"choices":[{"delta":{}}]}\n\n',
				'data: {"xy":{"type":"tool_result","name":"echo","output":"1","is_error":false,"tool_use_id":"c1"},"choices":[{"delta":{}}]}\n\n',
				'data: {"choices":[{"delta":{"content":"!"}}]}\n\n',
				'data: [DONE]\n\n',
			]),
		);
		const deltas: string[] = [];
		const tools: string[] = [];
		await streamChat('s1', 'hi', {
			onDelta: t => deltas.push(t),
			onToolCall: ev =>
				tools.push(
					`call:${ev.name}:${JSON.stringify(ev.input)}:${ev.toolUseId ?? ''}`,
				),
			onToolResult: ev =>
				tools.push(
					`res:${ev.name}:${ev.output}:${ev.is_error}:${ev.toolUseId ?? ''}`,
				),
			onDone: () => deltas.push('DONE'),
			onError: m => deltas.push(`ERR:${m}`),
		});
		expect(deltas).toEqual(['hi', '!', 'DONE']);
		expect(tools).toEqual([
			'call:echo:{"x":1}:c1',
			'res:echo:1:false:c1',
		]);
	});

		it('parses xy usage side-channel (L1.2)', async () => {
			fetchMock.mockResolvedValue(
				sseResponse([
					'data: {"xy":{"type":"usage","prompt_tokens":100,"completion_tokens":50,"tokens":150,"usd":0.0018,"used_usd":0.0018,"usd_limit":0.01,"context_tokens":100,"context_limit":128000},"choices":[{"delta":{}}]}\n\n',
					'data: [DONE]\n\n',
				]),
			);
			const usages: string[] = [];
			await streamChat('s1', 'hi', {
				onDelta: () => undefined,
				onUsage: ev =>
					usages.push(
						`${ev.promptTokens}/${ev.completionTokens}/${ev.tokens}/${ev.usd}/${ev.usedUsd}/${ev.usdLimit}/${ev.contextTokens}/${ev.contextLimit}`,
					),
				onDone: () => undefined,
				onError: () => undefined,
			});
			expect(usages).toEqual(['100/50/150/0.0018/0.0018/0.01/100/128000']);
		});

		it('dispatches context compression lifecycle events', async () => {
			fetchMock.mockResolvedValue(
				sseResponse([
					'data: {"xy":{"type":"context_compression_start","source":"automatic","context_tokens":120000,"context_limit":128000},"choices":[{"delta":{}}]}\n\n',
					'data: {"xy":{"type":"context_compression_complete","source":"automatic","context_tokens":32000,"context_limit":128000},"choices":[{"delta":{}}]}\n\n',
					'data: [DONE]\n\n',
				]),
			);
			const phases: string[] = [];
			await streamChat('s1', 'hi', {
				onDelta: () => undefined,
				onCompression: ev =>
					phases.push(`${ev.phase}/${ev.source}/${ev.contextTokens}/${ev.contextLimit}`),
				onDone: () => undefined,
				onError: () => undefined,
			});
			expect(phases).toEqual([
				'start/automatic/120000/128000',
				'complete/automatic/32000/128000',
			]);
		});

		it('forwards cached context_limit to the chat request', async () => {
			fetchMock.mockImplementation((url: string) => {
				if (url.includes('/v1/models')) {
					return Promise.resolve(
						new Response(
							JSON.stringify({
								data: [{id: 'deepseek-v4-flash', context_length: 128000}],
							}),
							{status: 200, headers: {'Content-Type': 'application/json'}},
						),
					);
				}
				return Promise.resolve(sseResponse(['data: [DONE]\n\n']));
			});
			await fetchVendorModels();
			await streamChat('s1', 'hi', {
				onDelta: () => undefined,
				onDone: () => undefined,
				onError: () => undefined,
			});
			const request = fetchMock.mock.calls.find(([url]) => String(url).includes('/v1/chat/completions'))?.[1] as RequestInit;
			const payload = JSON.parse(String(request.body));
				expect(payload.context_limit).toBe(128000);
			});

			it('forwards media_refs only when explicitly provided', async () => {
				fetchMock.mockResolvedValue(sseResponse(['data: [DONE]\\n\\n']));
				await streamChat('s1', 'describe', {
					onDelta: () => undefined,
					onDone: () => undefined,
					onError: () => undefined,
				}, {mediaRefs: ['xeyo-media://' + 'a'.repeat(64)]});
				const request = fetchMock.mock.calls.find(([url]) => String(url).includes('/v1/chat/completions'))?.[1] as RequestInit;
				const payload = JSON.parse(String(request.body));
					expect(payload.media_refs).toEqual(['xeyo-media://' + 'a'.repeat(64)]);
				});

			it('marks side- prefixed sessions and omits workspace for them', async () => {
				fetchMock.mockResolvedValue(sseResponse(['data: [DONE]\n\n']));
				await streamChat('side-id_test', 'hi', {
					onDelta: () => undefined,
					onDone: () => undefined,
					onError: () => undefined,
				}, {workspace: 'D:/proj'});
				let request = fetchMock.mock.calls.find(([url]) => String(url).includes('/v1/chat/completions'))?.[1] as RequestInit;
				let payload = JSON.parse(String(request.body));
				expect(payload.side).toBe(true);
				expect(payload.workspace).toBeUndefined();

				await streamChat('sess_main', 'hi', {
					onDelta: () => undefined,
					onDone: () => undefined,
					onError: () => undefined,
				}, {workspace: 'D:/proj'});
				request = fetchMock.mock.calls.filter(([url]) => String(url).includes('/v1/chat/completions')).at(-1)?.[1] as RequestInit;
				payload = JSON.parse(String(request.body));
				expect(payload.side).toBe(false);
				expect(payload.workspace).toBe('D:/proj');
			});

				it('blocks blank or non-user-final requests before fetch', async () => {
					const errors: string[] = [];
					const handlers = {
						onDelta: () => undefined,
						onDone: () => undefined,
						onError: (message: string) => errors.push(message),
					};

					await streamChat('s1', '   ', handlers);
					await streamChat(
						's1',
						[
							{role: 'user', content: 'hello'},
							{role: 'assistant', content: 'answer'},
						],
						handlers,
					);

					expect(errors).toEqual(['消息为空', '消息为空']);
					expect(fetchMock).not.toHaveBeenCalled();
				});

				it('parses ask_user_pending and ask_user_resolved events', async () => {
					fetchMock.mockResolvedValue(
						sseResponse([
							'data: {"xy":{"type":"ask_user_pending","request_id":"a1","session_id":"s1","turn_id":"t1","question":"Pick one?","options":["x","y"],"default":"x","expires_at":123}}\n\n',
							'data: {"xy":{"type":"ask_user_resolved","request_id":"a1","answer":"y","actor":"desktop","timeout":false}}\n\n',
							'data: [DONE]\n\n',
						]),
					);
					const pending: unknown[] = [];
					const resolved: unknown[] = [];
					await streamChat('s1', 'hi', {
						onDelta: () => undefined,
						onAskUserPending: ev => pending.push(ev),
						onAskUserResolved: ev => resolved.push(ev),
						onDone: () => undefined,
						onError: () => undefined,
					});
					expect(pending).toEqual([
						{
							kind: 'ask_user_pending',
							requestId: 'a1',
							question: 'Pick one?',
							options: ['x', 'y'],
							default: 'x',
							// legacy 帧：无 questions 字段 → 空数组（回落平铺渲染）。
							questions: [],
							expiresAt: 123,
							version: undefined,
							sessionId: 's1',
							turnId: 't1',
							eventId: undefined,
						},
					]);
					expect(resolved).toEqual([
						{
							kind: 'ask_user_resolved',
							requestId: 'a1',
							answer: 'y',
							actor: 'desktop',
							timeout: false,
							resolvedAt: undefined,
							version: undefined,
							sessionId: undefined,
							turnId: undefined,
							eventId: undefined,
						},
					]);
				});

				it('parses structured questions[] on ask_user_pending (multi-question form)', async () => {
					fetchMock.mockResolvedValue(
						sseResponse([
							'data: {"xy":{"type":"ask_user_pending","request_id":"a2","session_id":"s1","turn_id":"t1","question":"1. A?\\n2. B?","options":["x","y","z"],"default":"x","questions":[{"question":"A?","options":[{"label":"x","description":"xx"},{"label":"y"}],"multiSelect":false,"default":"x"},{"question":"B?","options":["z"],"multiSelect":true,"default":null}],"expires_at":null}}\n\n',
							'data: [DONE]\n\n',
						]),
					);
					const pending: unknown[] = [];
					await streamChat('s1', 'hi', {
						onDelta: () => undefined,
						onAskUserPending: ev => pending.push(ev),
						onDone: () => undefined,
						onError: () => undefined,
					});
					expect(pending).toEqual([
						{
							kind: 'ask_user_pending',
							requestId: 'a2',
							question: '1. A?\n2. B?',
							options: ['x', 'y', 'z'],
							default: 'x',
							questions: [
								{
									question: 'A?',
									options: [
										{label: 'x', description: 'xx'},
										{label: 'y'},
									],
									multiSelect: false,
									default: 'x',
								},
								{
									question: 'B?',
									options: [{label: 'z'}],
									multiSelect: true,
									default: null,
								},
							],
							expiresAt: undefined,
							version: undefined,
							sessionId: 's1',
							turnId: 't1',
							eventId: undefined,
						},
					]);
				});
	});

	describe('loadServerSessionMessages — strips enriched Resume cue (P0-③)', () => {
		const fetchMock = vi.fn();

		beforeEach(() => {
			fetchMock.mockReset();
			globalThis.fetch = fetchMock as unknown as typeof fetch;
		});

		it('restores a [Resume] user message to its User cue', async () => {
			fetchMock.mockResolvedValueOnce(
				new Response(
					JSON.stringify({
						messages: [
							{
								id: 'u1',
								role: 'user',
								text:
									'[Resume] The user asked to continue an interrupted turn.\n' +
									'Continue the unfinished work from where it stopped.\n' +
									'Original goal:\n写一个工具\nUser cue: 继续',
								createdAt: 100,
							},
							{id: 'a1', role: 'assistant', text: '好的', createdAt: 101},
						],
					}),
					{status: 200, headers: {'content-type': 'application/json'}},
				),
			);
			const msgs = await loadServerSessionMessages('s1');
			expect(msgs[0]!.role).toBe('user');
			expect(msgs[0]!.text).toBe('继续');
			// 普通 assistant 消息不受影响
			expect(msgs[1]!.text).toBe('好的');
		});

		it('leaves non-Resume user messages untouched', async () => {
			fetchMock.mockResolvedValueOnce(
				new Response(
					JSON.stringify({
						messages: [
							{id: 'u1', role: 'user', text: '您好', createdAt: 100},
						],
					}),
					{status: 200, headers: {'content-type': 'application/json'}},
				),
			);
			const msgs = await loadServerSessionMessages('s1');
			expect(msgs[0]!.text).toBe('您好');
		});
	});


describe('streamChat 思考开关与等级成对（缺口① 契约）', () => {
	const fetchMock = vi.fn();

	beforeEach(() => {
		fetchMock.mockReset();
		vi.stubGlobal('fetch', fetchMock);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	/** 取本次请求的实际 body（推导 thinking / reasoning_effort 的值）。 */
	async function bodyOf(options?: {
		reasoningEffort?: string;
		thinking?: 'enabled' | 'disabled';
	}): Promise<Record<string, unknown>> {
		const {useSettingsStore} = await import('@/stores/settingsStore');
		const state = useSettingsStore.getState() as Record<string, unknown>;
		const prevThinking = state.thinking;
		if (options?.thinking !== undefined) {
			state.thinking = options.thinking;
		}
		fetchMock.mockResolvedValue(sseResponse(['data: [DONE]\n\n']));
		await streamChat(
			's1',
			'hi',
			{
				onDelta: () => undefined,
				onDone: () => undefined,
				onError: () => undefined,
			},
			options?.reasoningEffort !== undefined
				? {reasoningEffort: options.reasoningEffort}
				: undefined,
		);
		state.thinking = prevThinking;
		const init = fetchMock.mock.calls[0]?.[1] as {body?: string} | undefined;
		return JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>;
	}

	it('输入框选了等级 → 自动开思考并带上该等级', async () => {
		const body = await bodyOf({reasoningEffort: 'high'});
		expect(body.thinking).toBe('enabled');
		expect(body.reasoning_effort).toBe('high');
	});

	it('显式开思考但未选等级 → 发 enabled 且不带等级', async () => {
		const body = await bodyOf({thinking: 'enabled'});
		expect(body.thinking).toBe('enabled');
		expect(body.reasoning_effort).toBeUndefined();
	});

	it('未选等级且未开思考 → 保持 disabled，不发送等级', async () => {
		const body = await bodyOf({thinking: 'disabled'});
		expect(body.thinking).toBe('disabled');
		expect(body.reasoning_effort).toBeUndefined();
	});
});
