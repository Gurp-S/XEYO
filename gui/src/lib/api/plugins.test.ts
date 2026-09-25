/**
 * plugins.test.ts — 扩展视图的两个报告端点：空列表与读不出必须分开。
 *
 * fetchPlugins / fetchExtensionSettings 原先写 `ok: body.ok !== false`
 * —— "信封里没写 ok"也算成功。面板拿到 ok:true + 空数组就画成
 * "这个工作区没装插件"，而后端每个分支都显式带 ok
 * （server/routers/plugins.py:155/179 等），缺字段只可能是回执变形或中间层改写。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchExtensionSettings, fetchPlugins} from '@/lib/api/plugins';

const fetchMock = vi.fn();

function response(payload: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('fetchPlugins', () => {
	it('正常回执原样带出', async () => {
		fetchMock.mockResolvedValue(response({ok: true, plugins: [{name: 'a'}], registered: []}));
		const r = await fetchPlugins();
		expect(r.ok).toBe(true);
		expect(r.plugins).toHaveLength(1);
	});

	it('200 但缺 ok 字段 = 读不出，不得画成"没有插件"', async () => {
		fetchMock.mockResolvedValue(response({plugins: [], registered: []}));
		const r = await fetchPlugins();
		expect(r.ok).toBe(false);
	});

	it('后端拒绝时带出 message', async () => {
		fetchMock.mockResolvedValue(response({ok: false, message: '扩展层默认关闭。'}));
		const r = await fetchPlugins();
		expect(r.ok).toBe(false);
		expect(r.message).toContain('扩展层默认关闭');
	});

	it('HTTP 失败也走 ok:false + 原话', async () => {
		fetchMock.mockResolvedValue(response({detail: 'workspace missing'}, 422));
		const r = await fetchPlugins();
		expect(r.ok).toBe(false);
		expect(r.message).toContain('workspace missing');
	});
});

describe('fetchExtensionSettings', () => {
	it('200 但缺 ok 字段 = 读不出', async () => {
		fetchMock.mockResolvedValue(response({enabled_extensions: true, plugins: {}}));
		const r = await fetchExtensionSettings();
		expect(r.ok).toBe(false);
	});

	it('ok:true 才算读到设置视图', async () => {
		fetchMock.mockResolvedValue(response({ok: true, enabled_extensions: true, plugins: {}, skills: {}, mcp_servers: {}}));
		const r = await fetchExtensionSettings();
		expect(r.ok).toBe(true);
		expect(r.enabled_extensions).toBe(true);
	});
});
