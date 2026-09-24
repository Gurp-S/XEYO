/**
 * mcp.ts — MCP 面板控制路径的错误回执（此前无任何覆盖）。
 *
 * 只替掉 global.fetch，所以测的是真的状态码→文案映射：
 * - 服务端参数校验一律回 4xx，原因在 `detail` 里；不接住就会渲染成一条
 *   `ok:false, message: undefined` 的**空白失败**（面板上看不见任何理由）；
 * - 200 + `{ok:false}` 也算失败，并要带出服务端给的 message；
 * - 后端挂了 / 响应体不是 JSON 时要有可读文案，不能把 `undefined` 投给界面。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {mcpOp} from '@/lib/api/mcp';

type FakeResponse = {
	ok: boolean;
	status: number;
	json: () => Promise<unknown>;
};

function fakeResponse(payload: unknown, status = 200): FakeResponse {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

const fetchMock = vi.fn();

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('mcpOp', () => {
	it('把 422 的 detail 当成失败原因带出来', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({detail: "server must not contain a backtick"}, 422),
		);

		const res = await mcpOp('x`y', 'enable');

		expect(res.ok).toBe(false);
		expect(res.message).toContain('backtick');
	});

	it('200 + ok:false 仍算失败，并保留服务端 message', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({ok: false, message: 'server 未声明，无法勾选'}),
		);

		const res = await mcpOp('demo', 'tool', {raw_tool: 'read', enabled: true});

		expect(res.ok).toBe(false);
		expect(res.message).toContain('server');
	});

	it('响应体不是 JSON 时回可读文案而不是 undefined', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 500,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const res = await mcpOp('demo', 'reload');

		expect(res.ok).toBe(false);
		expect(typeof res.message).toBe('string');
		expect(res.message).toContain('500');
	});

	it('成功时原样透传 ok:true', async () => {
		fetchMock.mockResolvedValue(fakeResponse({ok: true, server: 'demo', op: 'enable'}));

		const res = await mcpOp('demo', 'enable');

		expect(res.ok).toBe(true);
	});
});
