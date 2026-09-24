/**
 * 本地模型客户端的失败形状。
 *
 * 后端 `/v1/local-models*` 有三种回执：完整快照（ok:true）、业务失败
 * `{ok:false,error}`（不带 settings/status）、HTTP 层失败的 `{detail}`（连 ok 都没有）。
 * 旧实现把后两种原样当快照返回：`snap.binary.found` 直接崩掉整个设置面板，
 * 且 `ok===false` 判不出来 —— 失败被画成"没有错误"。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
	getLocalModels,
	setLocalModelSettings,
	startLocalModel,
} from '@/lib/api/localModels';

function response(payload: unknown, status = 200) {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => payload,
	};
}

const fullSnapshot = {
	ok: true,
	settings: {
		enabled: true,
		active_model: 'qwen',
		models_dir: 'D:/models',
		binary: 'llama-server',
		host: '127.0.0.1',
		port: 8080,
		ctx: 8192,
		gpu_layers: 99,
		extra_args: '',
	},
	status: {
		state: 'running',
		model: 'qwen',
		pid: 4242,
		host: '127.0.0.1',
		port: 8080,
		base_url: 'http://127.0.0.1:8080/v1',
		started_at: 1,
		uptime_s: 12,
		error: '',
		log_path: '',
		healthy: true,
	},
	models: [{id: 'qwen', present: true}],
	binary: {path: 'C:/bin/llama-server.exe', found: true},
	models_dir: 'D:/models',
	base_url: 'http://127.0.0.1:8080/v1',
	gate: {env: false, settings: true, allowed: true},
};

const fetchMock = vi.fn();

beforeEach(() => {
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('localModels 快照客户端', () => {
	it('完整快照原样带出', async () => {
		fetchMock.mockResolvedValue(response(fullSnapshot));

		const snap = await getLocalModels('D:/proj');

		expect(snap?.ok).toBe(true);
		expect(snap?.status.state).toBe('running');
		expect(snap?.models).toHaveLength(1);
	});

	it('业务失败（200 + ok:false）补齐成完整快照并带上原因', async () => {
		fetchMock.mockResolvedValue(
			response({ok: false, error: '启动失败: 权重文件未就绪'}),
		);

		const snap = await startLocalModel('qwen', 'D:/proj');

		expect(snap?.ok).toBe(false);
		expect(snap?.error).toBe('启动失败: 权重文件未就绪');
		// 调用方（LocalModelSetting）会无条件读这些字段，缺一个就白屏
		expect(snap?.settings.enabled).toBe(false);
		expect(snap?.binary.found).toBe(false);
		expect(snap?.models).toEqual([]);
	});

	it('422 的数组 detail 要翻成人话，不能画成"没有错误"', async () => {
		fetchMock.mockResolvedValue(
			response(
				{
					detail: [
						{loc: ['query', 'workspace'], msg: 'value is not a valid path', type: 'x'},
					],
				},
				422,
			),
		);

		const snap = await getLocalModels('D:/gone');

		expect(snap?.ok).toBe(false);
		expect(snap?.error).toContain('query.workspace');
		expect(snap?.error).toContain('value is not a valid path');
	});

	it('回执不是 JSON 时给出状态码而不是崩', async () => {
		fetchMock.mockResolvedValue({
			ok: false,
			status: 502,
			json: async () => {
				throw new SyntaxError('not json');
			},
		});

		const snap = await getLocalModels('D:/proj');

		expect(snap?.ok).toBe(false);
		expect(snap?.error).toContain('502');
	});

	it('ok:true 却缺字段 = 后端契约破了，按失败处理', async () => {
		fetchMock.mockResolvedValue(response({ok: true, settings: null}));

		const snap = await getLocalModels('D:/proj');

		expect(snap?.ok).toBe(false);
		expect(snap?.error).toContain('settings');
	});

	it('写设置走同一套形状校验', async () => {
		fetchMock.mockResolvedValue(response({detail: 'loopback only'}, 403));

		const snap = await setLocalModelSettings({enabled: true}, 'D:/proj');

		expect(snap?.ok).toBe(false);
		expect(snap?.error).toBe('loopback only');
	});

	it('连不上时返回 null，由调用方给兜底文案', async () => {
		fetchMock.mockRejectedValue(new Error('Failed to fetch'));

		await expect(getLocalModels('D:/proj')).resolves.toBeNull();
	});
});
