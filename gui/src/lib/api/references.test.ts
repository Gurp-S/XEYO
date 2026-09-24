/**
 * @ 文件候选的"读不出"与"没有匹配"必须分开。
 *
 * 调用方（Composer 的 @ 弹层）只在拿到非 null 报告时才标「已加载」并渲染候选：
 * 旧实现在后端明确拒绝（`ok:false`，如工作区未被索引）或回执缺 `files` 时
 * 仍返回 `{ok:false, files: []}`，于是弹层画成"没有匹配文件"——假空态。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {fetchFileReferences} from '@/lib/api/references';

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

describe('fetchFileReferences', () => {
	it('200 + files：原样带出', async () => {
		fetchMock.mockResolvedValue(response({ok: true, files: ['a/b.ts']}));

		const r = await fetchFileReferences('D:/proj', 'b');

		expect(r).toEqual({ok: true, files: ['a/b.ts']});
	});

	it('确实没有匹配才是 {ok:true, files:[]}', async () => {
		fetchMock.mockResolvedValue(response({ok: true, files: []}));

		const r = await fetchFileReferences('D:/proj', 'zzz');

		expect(r).toEqual({ok: true, files: []});
	});

	it('后端拒绝（ok:false）按读不出处理，不画成"没有匹配文件"', async () => {
		fetchMock.mockResolvedValue(response({ok: false, files: []}));

		await expect(fetchFileReferences('D:/proj', 'b')).resolves.toBeNull();
	});

	it('200 但回执缺 files 字段同样按读不出处理', async () => {
		fetchMock.mockResolvedValue(response({ok: true}));

		await expect(fetchFileReferences('D:/proj', 'b')).resolves.toBeNull();
	});

	it('422 / 断网 / 按键击作废都返回 null', async () => {
		fetchMock.mockResolvedValue(response({detail: 'workspace not indexed'}, 422));
		await expect(fetchFileReferences('D:/gone', 'b')).resolves.toBeNull();

		fetchMock.mockRejectedValue(new Error('Failed to fetch'));
		await expect(fetchFileReferences('D:/proj', 'b')).resolves.toBeNull();
	});
});
