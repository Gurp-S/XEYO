/**
 * diagnosticsPanel.test.tsx — 驱动 DiagnosticsPanel 的装载层（此前完全无覆盖的空白）。
 *
 * diagnostics.test.tsx 只喂手写 fixture 给视图，所以列表 / 详情的异步竞态与请求体
 * 错误一路漏到发布。这里锁的是：
 * - P0 1：慢的旧 detail 响应后到不得顶替当前轮次；
 * - P0 2：会话 A 的慢列表响应不得覆盖会话 B 的列表与选择；
 * - P1 3：200 信封里的 ok:false 走失败路径，不亮绿色徽章；付费模式必须二次确认；
 * - P1 6：离线是中文错误 + 可用重试，成功后错误自己消失；
 * - P1 7：换轮次关掉标记表单，说明与证据不会按到别的轮次头上；
 * - P1 8：静默轮询不吞掉手工翻出来的后续页。
 */
import {act, cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {MemoryRouter, useSearchParams} from 'react-router-dom';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {
	parseRunDetail,
	parseRunsResult,
	type DiagCaptureState,
	type DiagRawResult,
	type DiagRunDetail,
	type DiagRunsResult,
} from '@/lib/api/diagnostics';
import {DiagnosticsPanel} from './DiagnosticsPanel';

const api = vi.hoisted(() => ({
	fetchDiagRuns: vi.fn(),
	fetchDiagRun: vi.fn(),
	fetchDiagRunEvents: vi.fn(),
	fetchDiagCapture: vi.fn(),
	setDiagCapture: vi.fn(),
	fetchDiagReportMarkdown: vi.fn(),
	pinDiagRun: vi.fn(),
	traceDiagFact: vi.fn(),
	listDiagExperiments: vi.fn(),
	planDiagExperiment: vi.fn(),
	startDiagExperiment: vi.fn(),
	cancelDiagExperiment: vi.fn(),
}));

vi.mock('@/lib/api/diagnostics', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api/diagnostics')>();
	return {...actual, ...api};
});

vi.mock('@/stores/chatStore', () => {
	const state = {
		sessions: [
			{id: 'gui-a', title: '会话甲'},
			{id: 'gui-b', title: '会话乙'},
		],
		historyById: {} as Record<string, unknown>,
		activeId: 'gui-a',
	};
	const useChatStore = (selector?: (s: typeof state) => unknown) =>
		selector ? selector(state) : state;
	useChatStore.getState = () => state;
	return {useChatStore};
});

vi.mock('@/stores/chat/preStoreHelpers', () => ({
	activeBackendSessionId: (_historyById: unknown, id: string) => `backend-${id}`,
}));

const SESSION = 'backend-gui-a';

function runsFixture(
	sessionId: string,
	turns: Array<{turn_id: string; tool_use_ids?: string[]}>,
	over: Record<string, unknown> = {},
): DiagRunsResult {
	return parseRunsResult({
		schema_version: 1,
		ruleset_version: 1,
		session_id: sessionId,
		complete: true,
		store_root: '/diag',
		runs: turns.map(t => ({
			...t,
			model_request_count: 1,
			tool_call_count: 1,
			event_kinds: ['model.finished'],
			boundaries: ['model_request'],
		})),
		...over,
	});
}

function detailFixture(turnId: string, over: Record<string, unknown> = {}): DiagRunDetail {
	return parseRunDetail({
		schema_version: 1,
		session_id: SESSION,
		turn_id: turnId,
		...over,
	});
}

function findingOf(text: string) {
	return {
		rule_id: 'tool_failure',
		rule_version: 1,
		phenomenon: text,
		boundary: 'tool_permission',
		component: '工具执行：Read',
		status: 'unknown',
		evidence: [],
		impact: '',
		coverage_gap: '',
		allowed_conclusion: '',
	};
}

function eventsFixture(from: number, to: number) {
	const out = [];
	for (let line = from; line < to; line += 1) {
		out.push({
			seq: line,
			line_no: line,
			kind: 'job.started',
			ts: line,
			session_id: SESSION,
			turn_id: 't1',
			row: {},
			evidence: {source: 'audit', locator: '', ref_id: `L${line}`, detail: ''},
		});
	}
	return out;
}

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return {promise, resolve, reject};
}

function renderPanel(entry?: string) {
	return render(
		<MemoryRouter initialEntries={entry ? [entry] : ['/diagnostics']}>
			<DiagnosticsPanel active />
			<LocationProbe />
		</MemoryRouter>,
	);
}

/** MemoryRouter 不写 window.location：从同一个 router 上下文里读真实 search。 */
function LocationProbe() {
	const params = useSearchParams()[0];
	return <span data-testid="loc-probe">{`?${params.toString()}`}</span>;
}

beforeEach(() => {
	for (const fn of Object.values(api)) fn.mockReset();
	api.fetchDiagCapture.mockResolvedValue({
		session_id: SESSION,
		enabled: false,
		disk_bytes: null,
		quota_bytes: null,
		locator: '',
	} satisfies DiagCaptureState);
	api.fetchDiagRunEvents.mockResolvedValue({events: [], total: 0, complete: true, nextCursor: ''});
	api.traceDiagFact.mockResolvedValue({needle: '', session_id: SESSION, turn_id: 't1', stages: [], verdict: '', statement: '', unprovable_stages: [], caveat: ''});
	api.listDiagExperiments.mockResolvedValue({ok: true, status: 200, data: {experiments: [], count: 0}});
	api.planDiagExperiment.mockResolvedValue({ok: true, status: 200, data: {plan: {}}});
	api.startDiagExperiment.mockResolvedValue({ok: true, status: 200, data: {experiment_id: 'e1'}});
	api.cancelDiagExperiment.mockResolvedValue({ok: true, status: 200, data: {cancelled: true}});
	api.pinDiagRun.mockResolvedValue({ok: true, pin: null, error: ''});
	api.setDiagCapture.mockResolvedValue({
		session_id: SESSION,
		enabled: true,
		disk_bytes: null,
		quota_bytes: null,
		locator: '',
	});
	api.fetchDiagReportMarkdown.mockResolvedValue({markdown: '# 报告', turn_id: 't1', session_id: SESSION});
});

afterEach(cleanup);

describe('运行详情的请求身份（P0 1）', () => {
	it('慢的上一轮响应后到也不顶替当前轮次', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}, {turn_id: 't2'}]));
		const slow = deferred<DiagRunDetail>();
		const fast = deferred<DiagRunDetail>();
		api.fetchDiagRun.mockImplementation((_s: string, turnId: string) =>
			turnId === 't1' ? slow.promise : fast.promise,
		);

		renderPanel();
		await waitFor(() =>
			expect(api.fetchDiagRun).toHaveBeenCalledWith(SESSION, 't1', expect.anything()),
		);

		await user.click(screen.getByRole('button', {name: /t2/}));
		await waitFor(() =>
			expect(api.fetchDiagRun).toHaveBeenCalledWith(SESSION, 't2', expect.anything()),
		);

		fast.resolve(detailFixture('t2', {findings: [findingOf('乙轮的结论')]}, ));
		expect(await screen.findByText('乙轮的结论')).toBeTruthy();

		// 先发的 t1 现在才落地：必须被丢弃，否则列表高亮 t2 而正文全是 t1。
		slow.resolve(detailFixture('t1', {findings: [findingOf('甲轮的结论')]}));
		await new Promise(r => setTimeout(r, 0));
		expect(screen.queryByText('甲轮的结论')).toBeNull();
		expect(screen.getByText('乙轮的结论')).toBeTruthy();
	});

	it('载荷自证身份：turn_id 与所请求不符的响应被丢弃', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(
			runsFixture(SESSION, [{turn_id: 't1'}, {turn_id: 't2'}]),
		);
		api.fetchDiagRun.mockImplementation(async (_s: string, turnId: string) =>
			turnId === 't2'
				? detailFixture('t1', {findings: [findingOf('串轮的结论')]})
				: deferred<DiagRunDetail>().promise,
		);
		renderPanel();
		await screen.findByText('t2');
		await user.click(screen.getByRole('button', {name: /t2/}));
		await new Promise(r => setTimeout(r, 0));
		expect(screen.queryByText('串轮的结论')).toBeNull();
	});

	it('换轮次时先清空正文，加载态真的出现', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}, {turn_id: 't2'}]));
		const pending = new Map<string, ReturnType<typeof deferred<DiagRunDetail>>>();
		api.fetchDiagRun.mockImplementation((_s: string, turnId: string) => {
			const d = deferred<DiagRunDetail>();
			pending.set(turnId, d);
			return d.promise;
		});
		const {container} = renderPanel();
		await waitFor(() => expect(pending.has('t1')).toBe(true));
		pending.get('t1')!.resolve(detailFixture('t1', {findings: [findingOf('甲轮的结论')]}));
		expect(await screen.findByText('甲轮的结论')).toBeTruthy();

		await user.click(screen.getByRole('button', {name: /t2/}));
		// 旧正文不得留在屏幕上冒充"这就是 t2 的结论"
		expect(screen.queryByText('甲轮的结论')).toBeNull();
		await waitFor(() => expect(pending.has('t2')).toBe(true));
		expect(container.querySelectorAll('.xy-usage-skeleton').length).toBeGreaterThan(0);
	});
});

describe('运行列表的会话身份（P0 2）', () => {
	it('会话 A 的慢列表响应不覆盖会话 B 的列表，也不改写选择', async () => {
		const user = userEvent.setup();
		const slowA = deferred<DiagRunsResult>();
		const fastB = deferred<DiagRunsResult>();
		api.fetchDiagRuns.mockImplementation((sessionId: string) =>
			sessionId === SESSION ? slowA.promise : fastB.promise,
		);
		api.fetchDiagRun.mockResolvedValue(detailFixture('t-b1'));

		renderPanel();
		await waitFor(() => expect(api.fetchDiagRuns).toHaveBeenCalledWith(SESSION, expect.anything()));
		await user.selectOptions(screen.getByRole('combobox'), 'backend-gui-b');

		fastB.resolve(runsFixture('backend-gui-b', [{turn_id: 't-b1'}]));
		expect(await screen.findByText('t-b1')).toBeTruthy();

		slowA.resolve(runsFixture(SESSION, [{turn_id: 't-a1'}, {turn_id: 't-a2'}]));
		await new Promise(r => setTimeout(r, 0));
		expect(screen.queryByText('t-a1')).toBeNull();
		expect(screen.getByText('t-b1')).toBeTruthy();
	});
});

describe('离线与重试（P1 6）', () => {
	it('列表取不到时是中文错误 + 可用重试，成功后错误消失', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockRejectedValueOnce(
			new Error('无法连接本地后端（请确认 server 已启动）'),
		);
		renderPanel();

		expect(await screen.findByText(/无法连接本地后端/)).toBeTruthy();
		expect(document.body.textContent).not.toMatch(/Failed to fetch|TypeError/);
		expect(screen.queryByText('未选择轮次')).toBeNull();

		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1', {findings: [findingOf('恢复后的结论')]}));
		await user.click(screen.getByRole('button', {name: '重试'}));

		await waitFor(() => expect(api.fetchDiagRuns).toHaveBeenCalledTimes(2));
		expect(await screen.findByText('恢复后的结论')).toBeTruthy();
		await waitFor(() =>
			expect(screen.queryByText(/无法连接本地后端/)).toBeNull(),
		);
	});

	it('一次瞬时失败不得永久挡住仍在到达的数据', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockRejectedValueOnce(new Error('无法连接本地后端（请确认 server 已启动）'));
		renderPanel();
		expect(await screen.findByText(/无法连接本地后端/)).toBeTruthy();

		// 后续轮询成功：错误必须让位给数据（旧实现只在非静默路径清错）。
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1', {findings: [findingOf('轮询带回的结论')]}));
		act(() => {
			document.dispatchEvent(new Event('visibilitychange'));
		});
		expect(await screen.findByText('轮询带回的结论')).toBeTruthy();
		expect(screen.queryByText(/无法连接本地后端/)).toBeNull();
		void user;
	});
});

describe('深链未命中（P1 11）', () => {
	it('tool 不在审计尾窗里时明确说明，不自动改选别的轮次', async () => {
		api.fetchDiagRuns.mockResolvedValue(
			runsFixture(SESSION, [{turn_id: 't1', tool_use_ids: ['call_1']}]),
		);
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		render(
			<MemoryRouter initialEntries={['/diagnostics?tool=call_9']}>
				<DiagnosticsPanel active />
			</MemoryRouter>,
		);
		expect(await screen.findByText(/call_9 不在当前审计尾窗里/)).toBeTruthy();
	});
});

describe('标记表单的归属（P1 7）', () => {
	it('换轮次关掉表单；重新打开时说明与证据都属于新轮', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}, {turn_id: 't2'}]));
		api.fetchDiagRun.mockImplementation((_s: string, turnId: string) =>
			Promise.resolve(
				detailFixture(turnId, {
					findings: [
						{
							...findingOf(`${turnId} 的结论`),
							status: 'confirmed_fault',
							evidence: [
								{source: 'audit', locator: '/a.jsonl', ref_id: `L-${turnId}`, detail: 'tool.finished'},
							],
						},
					],
				}),
			),
		);
		api.pinDiagRun.mockResolvedValue({ok: true, pin: null, error: ''});

		renderPanel();
		expect(await screen.findByText('t2')).toBeTruthy();
		await waitFor(() => expect(screen.getByText('t1 的结论')).toBeTruthy());

		await user.click(screen.getByRole('button', {name: '标记这轮结果不对'}));
		await user.type(screen.getByLabelText(/这轮哪里不对/), '只属于第一轮的观察');
		expect(screen.getByRole('checkbox', {name: /固定证据/})).toBeTruthy();

		await user.click(screen.getByRole('button', {name: /t2/}));
		// 表单必须关掉：否则这条说明会被按到 t2 头上
		expect(screen.queryByLabelText(/这轮哪里不对/)).toBeNull();
		await waitFor(() => expect(screen.getByText('t2 的结论')).toBeTruthy());

		await user.click(screen.getByRole('button', {name: '标记这轮结果不对'}));
		await user.type(screen.getByLabelText(/这轮哪里不对/), '第二轮的观察');
		await user.click(screen.getByRole('button', {name: '标记并固定'}));

		await waitFor(() => expect(api.pinDiagRun).toHaveBeenCalled());
		const [sessionId, turnId, input] = api.pinDiagRun.mock.calls[0] as [
			string,
			string,
			{note: string; evidence: Array<{ref_id: string}>},
		];
		expect(sessionId).toBe(SESSION);
		expect(turnId).toBe('t2');
		expect(input.note).toBe('第二轮的观察');
		expect(input.evidence.map(e => e.ref_id)).toEqual(['L-t2']);
	});
});

describe('静默轮询与手工翻页（P1 8）', () => {
	it('轮询回来的第 0 页不把手工加载的后续页换掉', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		const page0 = detailFixture('t1', {
			events: eventsFixture(0, 5),
			event_total: 15,
			event_offset: 0,
			event_limit: 5,
			events_complete: false,
			next_event_cursor: '5',
		});
		api.fetchDiagRun.mockResolvedValue(page0);
		api.fetchDiagRunEvents
			.mockResolvedValueOnce({events: eventsFixture(5, 10), total: 15, complete: false, nextCursor: '10'})
			.mockResolvedValueOnce({events: eventsFixture(10, 15), total: 15, complete: false, nextCursor: '15'});

		renderPanel();
		await waitFor(() => expect(api.fetchDiagRun).toHaveBeenCalled());
		await user.click(screen.getByRole('tab', {name: '步骤'}));
		expect(await screen.findByText('5 / 15')).toBeTruthy();

		await user.click(screen.getByRole('button', {name: /继续加载/}));
		await waitFor(() => expect(screen.getByText('10 / 15')).toBeTruthy());
		await user.click(screen.getByRole('button', {name: /继续加载/}));
		await waitFor(() => expect(screen.getByText('15 / 15')).toBeTruthy());

		// 焦点回来触发的静默刷新只带第 0 页
		act(() => {
			document.dispatchEvent(new Event('visibilitychange'));
		});
		await waitFor(() => expect(api.fetchDiagRun).toHaveBeenCalledTimes(2));
		await new Promise(r => setTimeout(r, 0));
		expect(screen.getByText('15 / 15')).toBeTruthy();
	});
});

describe('实验层的失败信封与付费授权（P1 3 / P2 15）', () => {
	async function openExperiments(user: ReturnType<typeof userEvent.setup>) {
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		renderPanel();
		await waitFor(() => expect(api.fetchDiagRun).toHaveBeenCalled());
		await user.click(screen.getByRole('tab', {name: '实验'}));
	}

	it('200 信封里的 ok:false 走失败路径，不亮绿色徽章', async () => {
		const user = userEvent.setup();
		api.listDiagExperiments.mockResolvedValue({
			ok: false,
			status: 200,
			error: "mode 必须是 ['a0', 'a1', 'a2']",
		} satisfies DiagRawResult);
		await openExperiments(user);

		expect(await screen.findByText(/实验层不可用/)).toBeTruthy();
		expect(screen.queryByText('实验端点可访问')).toBeNull();
	});

	it('列表尚未取回时也不亮绿色徽章', async () => {
		const user = userEvent.setup();
		api.listDiagExperiments.mockReturnValue(deferred<DiagRawResult>().promise);
		await openExperiments(user);
		expect(await screen.findByText('列表未取回')).toBeTruthy();
		expect(screen.queryByText('实验端点可访问')).toBeNull();
	});

	it('启动付费模式要显式确认，且发出去的 mode 是小写、键是 variants', async () => {
		const user = userEvent.setup();
		api.listDiagExperiments.mockResolvedValue({ok: true, status: 200, data: {experiments: []}});
		api.startDiagExperiment.mockResolvedValue({ok: true, status: 200, data: {experiment_id: 'e1'}});
		await openExperiments(user);

		await user.click(screen.getByRole('button', {name: /A1 同检查点单次响应配对/}));
		await user.click(screen.getByRole('button', {name: '按配置启动'}));
		expect(api.startDiagExperiment).not.toHaveBeenCalled();
		expect(await screen.findByText(/再点一次「确认启动」才执行/)).toBeTruthy();

		await user.click(screen.getByRole('button', {name: '确认启动（含付费调用）'}));
		await waitFor(() => expect(api.startDiagExperiment).toHaveBeenCalledTimes(1));
		const body = api.startDiagExperiment.mock.calls[0]![0] as Record<string, unknown>;
		expect(body.mode).toBe('a1');
		expect(body.variants).toEqual({A: {}, B: {}});
		expect(body.repeat).toBe(1);
		expect(typeof body.idempotency_key).toBe('string');
		expect(body.baseline).toBeUndefined();
	});

	it('a0 不付费，一次点击即启动', async () => {
		const user = userEvent.setup();
		api.listDiagExperiments.mockResolvedValue({ok: true, status: 200, data: {experiments: []}});
		api.startDiagExperiment.mockResolvedValue({ok: true, status: 200, data: {experiment_id: 'e0'}});
		await openExperiments(user);
		await user.click(screen.getByRole('button', {name: '按配置启动'}));
		await waitFor(() => expect(api.startDiagExperiment).toHaveBeenCalledTimes(1));
		expect((api.startDiagExperiment.mock.calls[0]![0] as Record<string, unknown>).mode).toBe('a0');
	});

	it('取消入口只认 experiments[].experiment_id，且要二次确认', async () => {
		const user = userEvent.setup();
		api.listDiagExperiments.mockResolvedValue({
			ok: true,
			status: 200,
			data: {
				experiments: [{idempotency_key: 'k1', experiment_id: 'exp-1'}],
				count: 1,
				// 干扰项：嵌套里另一个 id 不该长出取消按钮
				nested: {id: 'not-an-experiment', rows: [{id: 'also-not'}]},
			},
		});
		await openExperiments(user);

		const cancelButtons = await screen.findAllByRole('button', {name: /取消 exp-/});
		expect(cancelButtons).toHaveLength(1);
		expect(screen.queryByRole('button', {name: /取消 not-an-experiment/})).toBeNull();

		await user.click(cancelButtons[0]!);
		expect(api.cancelDiagExperiment).not.toHaveBeenCalled();
		await user.click(cancelButtons[0]!);
		await waitFor(() => expect(api.cancelDiagExperiment).toHaveBeenCalledWith('exp-1'));
	});
});

describe('采集开关与尾窗措辞（P2 13 / P1 12 / P1 19）', () => {
	it('采集状态未取回时勾选框是禁用的，不再"可点但什么都不发生"', async () => {
		api.fetchDiagCapture.mockResolvedValue(null);
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		renderPanel();
		const box = (await screen.findByRole('checkbox')) as HTMLInputElement;
		await waitFor(() => expect(box.disabled).toBe(true));
		expect(screen.getByText('采集状态未取回：该端点不可达时不改动任何配置。')).toBeTruthy();
	});

	it('目录占用按人类可读单位显示并标明是采集目录', async () => {
		api.fetchDiagCapture.mockResolvedValue({
			session_id: SESSION,
			enabled: true,
			disk_bytes: 3_145_728,
			quota_bytes: 104_857_600,
			locator: '/diag/captures',
		} satisfies DiagCaptureState);
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		renderPanel();
		expect(await screen.findByText(/采集目录已占用 3.0 MB/)).toBeTruthy();
		expect(document.body.textContent).not.toMatch(/3145728 KB/);
	});

	it('空列表只说"尾窗内没有记录"，不同时挂截断徽章', async () => {
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [], {complete: false}));
		renderPanel();
		expect(await screen.findByText(/审计尾窗内没有轮次记录/)).toBeTruthy();
		expect(screen.queryByText('尾窗截断')).toBeNull();
	});

	it('有记录且不完整时才说尾窗截断', async () => {
		api.fetchDiagRuns.mockResolvedValue(
			runsFixture(SESSION, [{turn_id: 't1'}], {complete: false}),
		);
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		renderPanel();
		expect(await screen.findByText('尾窗截断')).toBeTruthy();
	});
});

describe('标签页与正文的重挂载边界（P2 16）', () => {
	it('换标签不销毁上下文视图的取证结果', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		api.traceDiagFact.mockResolvedValue({
			needle: '改完必须跑测试',
			session_id: SESSION,
			turn_id: 't1',
			stages: [{stage: 'user_request', label: '用户请求', state: 'found', evidence: [], note: ''}],
			verdict: 'found',
			statement: '该事实在各级都有记录',
			unprovable_stages: [],
			caveat: '',
		});
		renderPanel();
		await waitFor(() => expect(api.fetchDiagRun).toHaveBeenCalled());

		await user.click(screen.getByRole('tab', {name: '上下文'}));
		await user.type(screen.getByRole('textbox'), '改完必须跑测试');
		await user.click(screen.getByRole('button', {name: '定位'}));
		expect(await screen.findByText('该事实在各级都有记录')).toBeTruthy();

		await user.click(screen.getByRole('tab', {name: '问题'}));
		await user.click(screen.getByRole('tab', {name: '上下文'}));
		await waitFor(() => expect(api.traceDiagFact).toHaveBeenCalledTimes(1));
		expect(screen.getByText('该事实在各级都有记录')).toBeTruthy();
	});

	it('标签进 URL，刷新后回到同一视图', async () => {
		const user = userEvent.setup();
		api.fetchDiagRuns.mockResolvedValue(runsFixture(SESSION, [{turn_id: 't1'}]));
		api.fetchDiagRun.mockResolvedValue(detailFixture('t1'));
		renderPanel();
		await waitFor(() => expect(api.fetchDiagRun).toHaveBeenCalled());
		await user.click(screen.getByRole('tab', {name: '用量'}));
		await waitFor(() => expect(locationProbe()).toContain('tab=usage'));
		expect(locationProbe()).toContain(`session=${SESSION}`);
		expect(locationProbe()).toContain('turn=t1');
	});
});

/** MemoryRouter 不写 window.location：从同一个 router 里读实际 search。 */
function locationProbe(): string {
	return (screen.getByTestId('loc-probe').textContent ?? '').replace(/^\s+/, '');
}
