/**
 * skills 客户端的失败形状 —— "读不出" 绝不能变成 "这个工程没有技能"。
 *
 * 旧实现在 !res.ok 与抛异常两条路上都 `return null`，调用方手里只剩空数组，
 * 于是面板画成"0 技能"。后端刚把 `GET /v1/skills` 的同一句话修成 422
 * （工作区不存在 ≠ 什么都没装），客户端这一层不能把它又抹平回去。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchSkills} from '@/lib/api/skills';

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

describe('fetchSkills', () => {
	it('正常返回时 ok/skills 原样带出', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({ok: true, enabled_extensions: true, skills: [{name: 'a'}]}),
		);

		const report = await fetchSkills('D:/proj');

		expect(report.ok).toBe(true);
		expect(report.skills).toHaveLength(1);
	});

	it('422 不再是 null，而是带原因的空清单', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({detail: {message: 'workspace is not a readable directory', type: 'invalid_request'}}, 422),
		);

		const report = await fetchSkills('D:/gone');

		expect(report.ok).toBe(false);
		expect(report.skills).toEqual([]);
		expect(report.message).toContain('readable directory');
	});

	it('连不上时也是 ok:false + 原因，不能返回 null', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		const report = await fetchSkills('D:/proj');

		expect(report.ok).toBe(false);
		expect(report.message).toBeTruthy();
	});

	it('响应体不是 JSON 时不抛给调用方', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 502,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const report = await fetchSkills('D:/proj');

		expect(report.ok).toBe(false);
		expect(report.message).toContain('502');
	});
});
