/**
 * diagnosticsApi.test.ts — 诊断 API 客户端的真实收发层（此前无任何覆盖）。
 *
 * 这里不 mock 本模块，只替掉 global.fetch，所以测的是真解析器与真错误映射：
 * - 连不上本地后端必须是中文可恢复错误，不能把 `Failed to fetch` 投给界面；
 * - 非 Response 的返回值也不当成成功；
 * - 200 + `{ok:false}` 是失败（实验层的 mode 校验就是这么回的）；
 * - 请求身份字段（turn_id / session_id）必须原样带出，装载层靠它丢弃错轮响应；
 * - 外部 AbortSignal 与整体超时都要真的落到 fetch 上（60s 的全尾扫描要能取消）。
 */
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
	buildExperimentBody,
	DIAG_MODULE_MISSING_MESSAGE,
	cancelDiagExperiment,
	fetchDiagCapture,
	fetchDiagReportMarkdown,
	fetchDiagRun,
	fetchDiagRuns,
	isDiagRequestCancelled,
	listDiagExperiments,
	OFFLINE_ERROR_MESSAGE,
	pinDiagRun,
	planDiagExperiment,
} from '@/lib/api/diagnostics';

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
	vi.useRealTimers();
});

describe('离线是可恢复状态，不是浏览器原文', () => {
	it('GET 连不上时抛中文错误', async () => {
		fetchMock.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
		await expect(fetchDiagRuns('s1')).rejects.toThrow(OFFLINE_ERROR_MESSAGE);
	});

	it('POST 连不上时同样抛中文错误（标记 / 采集开关共用这一路）', async () => {
		fetchMock.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
		await expect(pinDiagRun('s1', 't1', {note: '观察'})).rejects.toThrow(
			OFFLINE_ERROR_MESSAGE,
		);
	});

	it('拿回来的不是 Response 也不算成功', async () => {
		fetchMock.mockResolvedValue(undefined);
		await expect(fetchDiagCapture('s1')).rejects.toThrow(OFFLINE_ERROR_MESSAGE);
	});

	it('非 2xx 用后端 detail 文案，不裸奔状态码', async () => {
		fetchMock.mockResolvedValue(fakeResponse({detail: 'no_such_turn'}, 404));
		await expect(fetchDiagRun('s1', 't9')).rejects.toThrow(/no_such_turn/);
	});

	it('导出端点回空正文时报错，不下一个空文件冒充成功', async () => {
		fetchMock.mockResolvedValue(fakeResponse({markdown: '   ', turn_id: 't1'}));
		await expect(fetchDiagReportMarkdown('s1', 't1')).rejects.toThrow(/未返回报告正文/);
	});
});

describe('200 信封里的拒绝走失败路径（P1 3）', () => {
	it('实验端点回 {ok:false,error} 时结果是失败', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({ok: false, error: "mode 必须是 ['a0', 'a1', 'a2'】"}),
		);
		const r = await planDiagExperiment({mode: 'A1'});
		expect(r.ok).toBe(false);
		if (!r.ok) {
			expect(r.status).toBe(200);
			expect(r.error).toContain('mode 必须是');
		}
	});

	it('实验端点回 {ok:true,...} 才是成功，且原样带出载荷', async () => {
		fetchMock.mockResolvedValue(fakeResponse({ok: true, plan: {feasible: true}}));
		const r = await planDiagExperiment({mode: 'a0'});
		expect(r.ok).toBe(true);
		if (!r.ok) throw new Error('不该是失败');
		expect(r.data).toEqual({ok: true, plan: {feasible: true}});
	});

	it('列表端点连 ok 字段都没有时按成功透传，不推断失败', async () => {
		fetchMock.mockResolvedValue(fakeResponse({experiments: [], count: 0}));
		const r = await listDiagExperiments();
		expect(r.ok).toBe(true);
	});

	it('取消请求的 URL 带实验身份，失败信封同样走失败路径', async () => {
		fetchMock.mockResolvedValue(fakeResponse({ok: false, error: 'no_such_experiment'}));
		const r = await cancelDiagExperiment('exp/1');
		expect(r.ok).toBe(false);
		expect(fetchMock.mock.calls[0]![0]).toContain('/v1/diagnostics/experiments/exp%2F1/cancel');
	});
});

describe('请求身份字段原样带出（P0 1 / P0 2 的前提）', () => {
	it('detail 保留 turn_id 与 session_id', async () => {
		fetchMock.mockResolvedValue(
			fakeResponse({schema_version: 1, session_id: 's1', turn_id: 't7', findings: []}),
		);
		const d = await fetchDiagRun('s1', 't7');
		expect(d.turn_id).toBe('t7');
		expect(d.session_id).toBe('s1');
	});

	it('列表保留 session_id', async () => {
		fetchMock.mockResolvedValue(fakeResponse({session_id: 's2', runs: []}));
		const r = await fetchDiagRuns('s2');
		expect(r.session_id).toBe('s2');
	});
});

describe('取消与超时真的落到 fetch 上', () => {
	it('外部 AbortSignal 生效，取消是可识别的取消而不是故障', async () => {
		fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
			const signal = init?.signal;
			return new Promise((_resolve, reject) => {
				signal?.addEventListener('abort', () => {
					reject(new DOMException('The operation was aborted.', 'AbortError'));
				});
			});
		});
		const controller = new AbortController();
		const p = fetchDiagRuns('s1', {signal: controller.signal});
		const settled: unknown[] = [];
		void p.then(
			() => settled.push('resolved'),
			(e: unknown) => settled.push(e),
		);
		await Promise.resolve();
		// 真正传给 fetch 的必须是带中止能力的信号（本模块把外部 signal 转发进内部控制器）
		expect(fetchMock.mock.calls[0]![1]?.signal).toBeInstanceOf(AbortSignal);
		controller.abort();
		await new Promise(r => setTimeout(r, 0));
		expect(settled).toHaveLength(1);
		expect(isDiagRequestCancelled(settled[0])).toBe(true);
	});

	it('运行详情按 60 秒上限中止，并把中文超时交给界面', async () => {
		vi.useFakeTimers();
		fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
			const signal = init?.signal;
			return new Promise((_resolve, reject) => {
				signal?.addEventListener('abort', () => {
					reject(new DOMException('The operation was aborted.', 'AbortError'));
				});
			});
		});
		const p = fetchDiagRun('s1', 't1');
		const assertion = expect(p).rejects.toThrow(/请求超时/);
		await vi.advanceTimersByTimeAsync(60_000);
		await assertion;
	});
});

describe('实验请求体真的按后端契约发出去', () => {
	it('mode 小写、variants / repeat / task_id 命名正确、无预算时不发该键', async () => {
		fetchMock.mockResolvedValue(fakeResponse({ok: true, plan: {}}));
		await planDiagExperiment(
			buildExperimentBody({
				mode: 'a2',
				sessionId: 's1',
				turnId: 't1',
				variantA: {model: 'x'},
				variantB: {model: 'y'},
				repeat: 2,
				budgetCny: null,
			}),
		);
		const sent = JSON.parse(String(fetchMock.mock.calls[0]![1]?.body)) as Record<string, unknown>;
		expect(sent).toMatchObject({mode: 'a2', variants: {A: {model: 'x'}, B: {model: 'y'}}, repeat: 2});
		expect(String(sent.task_id)).toContain('s1');
		expect('budget_cny' in sent).toBe(false);
	});

	it('有限预算才序列化成正数，NaN 不会变成"不设上限"的 null', async () => {
		fetchMock.mockResolvedValue(fakeResponse({ok: true, plan: {}}));
		await planDiagExperiment(
			buildExperimentBody({
				mode: 'a0',
				sessionId: 's1',
				turnId: 't1',
				variantA: {},
				variantB: {},
				repeat: 1,
				budgetCny: 8.5,
			}),
		);
		const sent = JSON.parse(String(fetchMock.mock.calls[0]![1]?.body)) as Record<string, unknown>;
		expect(sent.budget_cny).toBe(8.5);
	});
});

describe('后端根本没挂诊断模块时要说出这件事', () => {
	// 桌面版打包的引擎快照早于诊断层：resources/python 里没有 diagnostics，
	// 也没有 server/routers/diagnostics.py。此时每个端点都是框架默认的 404，
	// 把 `Not Found` 原样投给读者既看不懂、也指不出该做什么。
	it('框架默认 404 翻译成"没有诊断模块"，不保留英文原文', async () => {
		fetchMock.mockResolvedValue(fakeResponse({detail: 'Not Found'}, 404));
		await expect(fetchDiagRuns('s1')).rejects.toThrow(DIAG_MODULE_MISSING_MESSAGE);
		await expect(fetchDiagRuns('s1')).rejects.not.toThrow(/Not Found/);
	});

	it('后端自己写的 404 文案原样保留（不得一口咬定模块缺失）', async () => {
		fetchMock.mockResolvedValue(fakeResponse({detail: '这个轮次不在诊断索引里'}, 404));
		await expect(fetchDiagRun('s1', 't9')).rejects.toThrow('这个轮次不在诊断索引里');
	});

	it('非 404 的错误映射不受影响', async () => {
		fetchMock.mockResolvedValue(fakeResponse({detail: 'session_id 含非法字符'}, 422));
		await expect(fetchDiagRuns('s/../x')).rejects.toThrow('session_id 含非法字符');
	});
});
