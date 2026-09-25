/**
 * 上传客户端的回执校验。
 *
 * 调用方（Composer / 消息编辑）是 try/catch 型的：不抛错就等于"附件可以进消息"。
 * 所以 200 但回执缺字段/为空必须抛——否则用户看到"已上传"，模型收到的却是
 * 指向空气的 media_ref，或者一份被服务端砍掉一半却没人说的正文。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {uploadFile, uploadMedia} from '@/lib/api/uploads';

const fetchMock = vi.fn();

function response(payload: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

const file = new File(['x'], 'a.txt', {type: 'text/plain'});

const MEDIA_OK = {
	ok: true,
	media_ref: 'm_9f2c',
	mime: 'image/png',
	width: 800,
	height: 600,
	bytes: 1234,
	original_bytes: 2345,
	filename: 'a.png',
};

const FILE_OK = {
	id: 'f_1',
	filename: 'a.txt',
	bytes: 12,
	text: '正文',
	path: '/tmp/f_1',
	truncated: false,
};

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('uploadMedia', () => {
	it('回执齐时原样带出可引用字段', async () => {
		fetchMock.mockResolvedValue(response(MEDIA_OK));

		const r = await uploadMedia(file);

		expect(r.media_ref).toBe('m_9f2c');
		expect(r.width).toBe(800);
		expect(r.filename).toBe('a.png');
	});

	it('200 但 media_ref 缺失或空白：抛错，不返回空引用', async () => {
		fetchMock.mockResolvedValue(response({...MEDIA_OK, media_ref: undefined}));
		await expect(uploadMedia(file)).rejects.toThrow(/缺 media_ref/);

		fetchMock.mockResolvedValue(response({...MEDIA_OK, media_ref: '   '}));
		await expect(uploadMedia(file)).rejects.toThrow(/缺 media_ref/);
	});

	it('200 但没有 ok：不当成确认', async () => {
		fetchMock.mockResolvedValue(response({...MEDIA_OK, ok: undefined}));

		await expect(uploadMedia(file)).rejects.toThrow(/没有确认 ok/);
	});

	it('413 带出后端原话', async () => {
		fetchMock.mockResolvedValue(response({detail: 'image too large (max 1 bytes)'}, 413));

		await expect(uploadMedia(file)).rejects.toThrow(/image too large/);
	});

	it('连不上时抛中文上下文（旧措辞保留）', async () => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

		await expect(uploadMedia(file)).rejects.toThrow(/无法连接图片上传接口/);
	});

	it('200 但回执不是 JSON：抛"未确认收下"而不是崩在解析上', async () => {
		fetchMock.mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		await expect(uploadMedia(file)).rejects.toThrow(/回执不是对象/);
	});
});

describe('uploadFile', () => {
	it('服务端截过正文时，truncated 必须传到调用方', async () => {
		fetchMock.mockResolvedValue(response({...FILE_OK, truncated: true}));

		const r = await uploadFile(file);

		expect(r.truncated).toBe(true);
	});

	it('缺 truncated 字段按未截断处理，但 id/filename/text 缺一样就抛', async () => {
		fetchMock.mockResolvedValue(response({...FILE_OK, truncated: undefined}));
		expect((await uploadFile(file)).truncated).toBe(false);

		fetchMock.mockResolvedValue(response({...FILE_OK, text: undefined}));
		await expect(uploadFile(file)).rejects.toThrow(/缺 text/);

		fetchMock.mockResolvedValue(response({...FILE_OK, filename: ''}));
		await expect(uploadFile(file)).rejects.toThrow(/缺 filename/);
	});

	it('空文件是合法的空串，不是缺字段', async () => {
		fetchMock.mockResolvedValue(response({...FILE_OK, text: ''}));

		expect((await uploadFile(file)).text).toBe('');
	});

	it('发的是 multipart 与 /v1/files', async () => {
		fetchMock.mockResolvedValue(response(FILE_OK));

		await uploadFile(file);

		const [url, init] = fetchMock.mock.calls[0];
		expect(String(url)).toContain('/v1/files');
		expect(init.method).toBe('POST');
		expect(init.body).toBeInstanceOf(FormData);
		expect((init.body as FormData).get('file')).toBeInstanceOf(File);
	});
});
