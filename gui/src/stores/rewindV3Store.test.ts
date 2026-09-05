/**
 * 回溯 v3 验收（设计 36 §11）。
 * §11-6 GC / §11-8 v2 回归：见文末说明与后端 test_rewind_service / blob_gc。
 */
import {beforeEach, describe, expect, it, vi} from 'vitest';
import type {ChatMessage, RewindEvent} from '@/lib/types';
import {RollbackRequestError} from '@/lib/api';

const rewindHotpath = vi.fn();
const fetchRewindStatus = vi.fn();
const fetchRewindEvents = vi.fn();
const fetchRewindCheckpoint = vi.fn();
const rewindHotpathUndo = vi.fn();
const recoverRewind = vi.fn();
const loadServerSessionMessages = vi.fn();

vi.mock('@/lib/api', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/api')>();
	return {
		...actual,
		rewindHotpath: (...args: unknown[]) => rewindHotpath(...args),
		fetchRewindStatus: (...args: unknown[]) => fetchRewindStatus(...args),
		fetchRewindEvents: (...args: unknown[]) => fetchRewindEvents(...args),
		fetchRewindCheckpoint: (...args: unknown[]) => fetchRewindCheckpoint(...args),
		rewindHotpathUndo: (...args: unknown[]) => rewindHotpathUndo(...args),
		recoverRewind: (...args: unknown[]) => recoverRewind(...args),
		loadServerSessionMessages: (...args: unknown[]) =>
			loadServerSessionMessages(...args),
	};
});

vi.mock('@/stores/chat/preStoreHelpers', async importOriginal => {
	const actual = await importOriginal<typeof import('@/stores/chat/preStoreHelpers')>();
	return {
		...actual,
		loadSessionMessagesWithBackfill: vi.fn(async () => [
			{id: 'm0', role: 'user', text: 'kept', createdAt: 1},
		]),
		activeBackendSessionId: () => 'sess_test',
	};
});

const replaceMessages = vi.fn(async (_sid: string, _msgs: ChatMessage[]) => {});

// 回溯截断/回滚会 fire-and-forget 写 IDB；node 测试环境无 indexedDB，必须 mock。
vi.mock('@/lib/db', async importOriginal => {
	const actual = await importOriginal<typeof import('@/lib/db')>();
	return {
		...actual,
		replaceMessages: (sid: string, msgs: ChatMessage[]) =>
			replaceMessages(sid, msgs),
	};
});

import {
	buildRewindIdempotencyKey,
	useRewindV3Store,
} from './rewindV3Store';
import {useChatStore} from './chatStore';

const SID = 'sess_test';

function msg(
	id: string,
	role: 'user' | 'assistant',
	text: string,
	createdAt: number,
): ChatMessage {
	return {id, role, text, createdAt};
}

function seedMessages(): ChatMessage[] {
	return [
		msg('m1', 'user', 'first', 1),
		msg('m2', 'assistant', 'a1', 2),
		msg('m3', 'user', 'second', 3),
		msg('m4', 'assistant', 'a2', 4),
	];
}

function event(partial: Partial<RewindEvent> & {rewind_id: string; status: string}): RewindEvent {
	return {
		mode: 'continue',
		target_message_id: 'm3',
		checkpoint_id: 'cp1',
		after_message_id: 'm2',
		orphan_count: 2,
		undone: false,
		ts: Date.now(),
		error: null,
		restore: null,
		pill_summary: null,
		...partial,
	} as RewindEvent;
}

beforeEach(() => {
	vi.clearAllMocks();
	localStorage.clear();
	useRewindV3Store.setState({bySession: {}, pillsBySession: {}});
	useChatStore.setState({
		activeId: SID,
		messagesById: {[SID]: seedMessages()},
		historyById: {
			[SID]: {
				activeBranch: {
					branchId: 'root',
					backendSessionId: SID,
					parentBranchId: null,
					createdAt: 1,
					forkMessageId: null,
					label: '主线',
				},
				archivedBranches: [],
			},
		},
	});
	loadServerSessionMessages.mockResolvedValue([
		{id: 'm1', role: 'user', text: 'first'},
		{id: 'm2', role: 'assistant', text: 'a1'},
		{id: 'm3', role: 'user', text: 'second'},
		{id: 'm4', role: 'assistant', text: 'a2'},
	]);
	fetchRewindCheckpoint.mockResolvedValue({
		checkpoint_id: 'cp1',
		anchor: false,
	});
	fetchRewindEvents.mockResolvedValue([]);
	useChatStore.setState({
		...useChatStore.getState(),
		sendMessage: vi.fn(async () => true),
	} as never);
});

describe('rewindV3Store · 设计 36 §11', () => {
	it('§11-1 poll failed 必回滚列表，error 未 settle（可撤销/重试/放弃）', async () => {
		rewindHotpath.mockResolvedValue({rewind_id: 'rw1', reused: false});
		fetchRewindStatus.mockResolvedValue(
			event({rewind_id: 'rw1', status: 'failed', error: 'boom'}),
		);

		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited second');
		const ok = await useRewindV3Store.getState().confirm(SID, 'continue');

		expect(ok).toBe(false);
		const st = useRewindV3Store.getState().bySession[SID]!;
		expect(st.phase).toBe('error');
		expect(st.settled).toBe(false);
		expect(st.error).toMatch(/boom|失败/);
		const msgs = useChatStore.getState().messagesById[SID] ?? [];
		expect(msgs.map(m => m.id)).toEqual(['m1', 'm2', 'm3', 'm4']);
		expect(msgs[2]?.text).toBe('edited second');
	});

	it('§11-2 重试复用同一幂等键（无 Date.now）', async () => {
		const keyA = buildRewindIdempotencyKey(SID, 'm3', 'attempt1', 'edited');
		const keyB = buildRewindIdempotencyKey(SID, 'm3', 'attempt1', 'edited');
		expect(keyA).toBe(keyB);
		expect(keyA).toMatch(/^rw:sess_test:m3:attempt1:[0-9a-f]{8}$/);
		expect(keyA).not.toMatch(/\d{13}/);

		rewindHotpath
			.mockRejectedValueOnce(new Error('network'))
			.mockResolvedValueOnce({rewind_id: 'rw1', reused: true});
		fetchRewindStatus.mockResolvedValue(
			event({rewind_id: 'rw1', status: 'committed'}),
		);

		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited');
		await useRewindV3Store.getState().confirm(SID, 'continue');

		expect(rewindHotpath).toHaveBeenCalledTimes(2);
		const k1 = rewindHotpath.mock.calls[0]?.[1]?.idempotencyKey;
		const k2 = rewindHotpath.mock.calls[1]?.[1]?.idempotencyKey;
		expect(k1).toBe(k2);
		expect(k1).toMatch(/^rw:/);
	});

	it('§11-3 重载 rehydrate：进行中 rewind 可 poll 对齐 / failed 恢复列表', async () => {
		const suffix = seedMessages().slice(2);
		useChatStore.setState({
			messagesById: {[SID]: seedMessages().slice(0, 2)},
		});
		useRewindV3Store.setState({
			bySession: {
				[SID]: {
					phase: 'running',
					targetMessageId: 'm3',
					editedText: 'edited',
					action: 'continue',
					checkpointState: 'ready',
					checkpointId: 'cp1',
					rewindId: 'rw1',
					pillRewindId: null,
					summary: null,
					error: null,
					attemptId: 'att1',
					settled: false,
					suffixBackup: suffix,
					recovery: false,
					resendPending: false,
					checkpointAnchor: null,
				},
			},
		});
		localStorage.setItem(
			`xeyo.rewindV3.state.${SID}`,
			JSON.stringify(useRewindV3Store.getState().bySession[SID]),
		);

		fetchRewindStatus.mockResolvedValue(
			event({rewind_id: 'rw1', status: 'failed', error: 'lost'}),
		);
		await useRewindV3Store.getState().rehydrate(SID);

		const st = useRewindV3Store.getState().bySession[SID]!;
		expect(st.phase).toBe('error');
		expect(st.settled).toBe(false);
		expect(useChatStore.getState().messagesById[SID]?.map(m => m.id)).toEqual([
			'm1',
			'm2',
			'm3',
			'm4',
		]);
	});

	it('§11-4 restore 只回文件；undo 后回填消息', async () => {
		rewindHotpath.mockResolvedValue({rewind_id: 'rw_restore', reused: false});
		fetchRewindStatus.mockResolvedValue(
			event({
				rewind_id: 'rw_restore',
				status: 'committed',
				mode: 'restore',
				restore: {
					restored: ['a.ts'],
					deleted: [],
					skipped_dirty: [],
				},
			}),
		);
		rewindHotpathUndo.mockResolvedValue({ok: true});

		const before = useChatStore.getState().messagesById[SID]!;
		useRewindV3Store.getState().openDialog(SID, 'm3', '');
		const ok = await useRewindV3Store.getState().confirm(SID, 'restore');
		expect(ok).toBe(true);
		expect(useChatStore.getState().messagesById[SID]).toEqual(before);
		expect(rewindHotpath.mock.calls[0]?.[1]?.mode).toBe('restore');

		useRewindV3Store.setState(s => ({
			bySession: {
				...s.bySession,
				[SID]: {...s.bySession[SID]!, rewindId: 'rw_restore', phase: 'done'},
			},
		}));
		expect(await useRewindV3Store.getState().undoLast(SID)).toBe(true);
		expect(rewindHotpathUndo).toHaveBeenCalledWith(SID, 'rw_restore');
	});

	it('§11-5 脏路径跳过写入 summary（不被覆盖提示）', async () => {
		rewindHotpath.mockResolvedValue({rewind_id: 'rw_d', reused: false});
		fetchRewindStatus.mockResolvedValue(
			event({
				rewind_id: 'rw_d',
				status: 'partial',
				mode: 'restore',
				restore: {
					restored: ['ok.ts'],
					deleted: [],
					skipped_dirty: ['hand.ts'],
				},
			}),
		);
		useRewindV3Store.getState().openDialog(SID, 'm3', '');
		await useRewindV3Store.getState().confirm(SID, 'restore');
		const summary = useRewindV3Store.getState().bySession[SID]?.summary ?? '';
		expect(summary).toMatch(/跳过手改路径/);
		expect(summary).toMatch(/hand\.ts/);
	});

	it('§11-6 GC：前端不实现；后端 blob 可达性 / 锚点 / 预算见 python rewind.blob_gc', () => {
		expect(true).toBe(true);
	});

	it('§11-7 recovery_required → recover(retry|abandon)', async () => {
		rewindHotpath.mockResolvedValue({rewind_id: 'rw_rec', reused: false});
		fetchRewindStatus
			.mockResolvedValueOnce(
				event({
					rewind_id: 'rw_rec',
					status: 'recovery_required',
					error: 'mid',
				}),
			)
			.mockResolvedValueOnce(
				event({rewind_id: 'rw_rec', status: 'committed'}),
			);
		recoverRewind.mockResolvedValue({ok: true});

		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited');
		await useRewindV3Store.getState().confirm(SID, 'continue');
		let st = useRewindV3Store.getState().bySession[SID]!;
		expect(st.recovery).toBe(true);
		expect(st.phase).toBe('error');
		// transcript 已提交：列表保持截断
		expect(useChatStore.getState().messagesById[SID]?.map(m => m.id)).toEqual([
			'm1',
			'm2',
		]);

		expect(await useRewindV3Store.getState().recover(SID, 'retry')).toBe(true);
		expect(recoverRewind).toHaveBeenCalledWith(SID, 'rw_rec', 'retry');
		st = useRewindV3Store.getState().bySession[SID]!;
		expect(st.phase).toBe('done');
		expect(st.settled).toBe(true);
	});

	it('§11-9 session_busy：不破坏本地列表，弹窗 error', async () => {
		rewindHotpath.mockRejectedValue(
			new RollbackRequestError('busy', 409, 'session_busy'),
		);
		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited');
		const ok = await useRewindV3Store.getState().confirm(SID, 'continue');
		expect(ok).toBe(false);
		const st = useRewindV3Store.getState().bySession[SID]!;
		expect(st.phase).toBe('error');
		expect(st.error).toMatch(/Agent 正运行/);
		expect(useChatStore.getState().messagesById[SID]?.map(m => m.id)).toEqual([
			'm1',
			'm2',
			'm3',
			'm4',
		]);
		// busy 不走「同 key 重放」第二次
		expect(rewindHotpath).toHaveBeenCalledTimes(1);
	});

	it('截断必须落 IDB（confirm 成功与失败回滚对称），否则刷新后旧全量列表复活', async () => {
		rewindHotpath.mockResolvedValue({rewind_id: 'rw_idb', reused: false});
		fetchRewindStatus.mockResolvedValue(
			event({rewind_id: 'rw_idb', status: 'partial'}),
		);
		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited second');
		expect(await useRewindV3Store.getState().confirm(SID, 'continue')).toBe(true);
		// 同帧截断（含目标消息）写入 IDB：m3/m4 被移除。
		const commitCall = replaceMessages.mock.calls.find(
			c => c[1]?.length === 2 && c[1][0]?.id === 'm1',
		);
		expect(commitCall).toBeDefined();
		expect(commitCall![1].map((m: ChatMessage) => m.id)).toEqual(['m1', 'm2']);

		// 失败回滚路径：IDB 同步还原为完整列表（与截断对称）。
		// 重置列表（上一步 confirm 已截断），模拟一次全新的失败回溯。
		useChatStore.setState({
			messagesById: {
				...useChatStore.getState().messagesById,
				[SID]: seedMessages(),
			},
		});
		replaceMessages.mockClear();
		rewindHotpath.mockResolvedValue({rewind_id: 'rw_idb2', reused: false});
		fetchRewindStatus.mockResolvedValue(
			event({rewind_id: 'rw_idb2', status: 'failed', error: 'boom'}),
		);
		useRewindV3Store.getState().openDialog(SID, 'm3', 'edited second');
		expect(await useRewindV3Store.getState().confirm(SID, 'continue')).toBe(false);
		const rollbackCall = replaceMessages.mock.calls.find(
			c => c[1]?.length === 4,
		);
		expect(rollbackCall).toBeDefined();
	});

	it('pill 弹窗的 undo 走 pillRewindId（P0 回归：rewindId 恒 null 曾使按钮永久无效）', async () => {
		fetchRewindEvents.mockResolvedValue([
			event({rewind_id: 'rw_pill', status: 'committed', after_message_id: 'm2'}),
		]);
		await useRewindV3Store.getState().loadPills(SID);
		const pill = useRewindV3Store.getState().pillsBySession[SID]![0]!;
		useRewindV3Store.getState().openPillDialog(SID, pill);

		rewindHotpathUndo.mockResolvedValue({ok: true});
		expect(await useRewindV3Store.getState().undoLast(SID)).toBe(true);
		expect(rewindHotpathUndo).toHaveBeenCalledWith(SID, 'rw_pill');
	});
});
