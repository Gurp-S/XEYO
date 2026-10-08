/**
 * 归属：从 stores/chatStore.ts 巨石拆分而来（dismantle-chatstore-slice.cjs，Phase E: spaceSessionSlice）。
 * 拆分脚本已归档至 [过程]/legacy/，本文件此后为手工维护。
 * 方法自 chatStore.ts 的 create() 函数体原样迁移，行为不变；
 * 门面在原位置展开 createSpaceSessionSlice(set, get)。
 */
import type {StoreApi} from 'zustand';
import {createStreamOwnership} from './streamOwnership';
import {ensureSessionHistory} from './sessionHistoryHydration';
import {projectHistoryBackfill} from './historyBackfillProjection';
import {
	archiveServerSession,
	interruptChat,
	forkServerSession,
	renameServerSession,
	restoreServerSession,
} from '@/lib/api';
import {
	DEFAULT_SPACE_ID,
	clearChatHistoryState,
	clearRollbackState,
	clearSpacePathTombstone,
	deleteSession,
	deleteSpace,
	deleteSpaceRecord,
	loadChatHistoryState,
	loadDeletedSessionIds,
	loadDeletedSpaceIds,
	loadDeletedSpacePaths,
	loadRollbackState,
	loadSessions,
	loadSpaces,
	markSpaceDeleted,
	newSpace,
	purgeTombstonedLocalRecords,
	replaceMessages,
	saveSession,
	saveSpace,
} from '@/lib/db';
import {
	folderName,
	normalizePath,
} from '@/lib/paths';
import {
	clearPendingFieldsForSession,
	sessionErrorBannerPatch,
} from '@/lib/pendingForSession';
import {
	clearComposerDraft,
	getComposerDraft,
} from '@/lib/composerDrafts';
import {
	clearTodoDismissal,
} from '@/lib/todoDismissals';
import {
	type ChatMessage,
	type ChatSession,
} from '@/lib/types';
import {
	SIDE_SPACE_ID,
} from '@/lib/db';
import {
	uid,
} from '@/lib/utils';
import {
	useCommandPaletteStore,
} from '@/stores/commandPaletteStore';
import {
	getSessionStream,
	isSessionStreamLive,
	normalizeSessionStreams,
} from '@/lib/sessionStreams';
import {
	activeBackendSessionId,
	commitDrainForSession,
	clearSessionStreamState,
	defaultChatHistoryState,
	discardDrainForSession,
	idleRollbackState,
	loadLocalSessionMessages,
	loadLocalSessionSnapshot,
	loadSessionMessagesWithBackfill,
	normalizeChatHistoryState,
	settleAllSessionTools,
	syncWorkspaceRoot,
	type ChatState,
} from './preStoreHelpers';
import {
	createInFlight,
	findSpaceByRoot,
	importServerSessions,
	adoptWorkspaceSessions,
	mergeDuplicateRootSpaces,
	migrateSideChatSessions,
	openInFlight,
	persistCollapsed,
	tombstoneAndDeleteOnServer,
} from './spaceHelpers';
import {
	clearWaitingToolTimer,
	thoughtSyncTimers,
} from './streamHelpers';
import {
	savedPendingPermission,
	writePendingPermission,
} from './uiChromeSlice';

type SetState = StoreApi<ChatState>['setState'];
type GetState = StoreApi<ChatState>['getState'];

const SLICE_KEYS = ['hydrate', 'hydrateOnce', 'setActiveSpace', 'toggleSpaceCollapsed', 'openFolder', 'enterSpace', 'removeSpace', 'renameSpace', 'createSession', 'createSideSession', 'selectSession', 'removeSession', 'renameSession', 'forkSession', 'archiveSession', 'restoreSession'] as const;
const archiveInFlight = new Map<string, Promise<void>>();
// hydrate 收尾是整包 set({sessions, activeId: first...})。StrictMode 双挂载（dev）
// 或任意重复调用下，两个 hydrate 各带自己启动时的 IDB/服务端快照，后到者会盖掉
// 期间已落地的本地变更（10-05 归档标记三连丢、dump 钉因=迟到整包替换）。
// 同一时刻只允许一个在飞；并发调用者复用同一 Promise（hydrateOnce 为无去重原体）。
let hydrateInFlight: Promise<void> | null = null;

export function createSpaceSessionSlice(
	set: SetState,
	get: GetState,
): Pick<ChatState, (typeof SLICE_KEYS)[number]> {
	const sessionLoadTokens = new Map<string, symbol>();
	return {
	async hydrateOnce() {
		// 先把旧侧聊 KV 会话并入 IDB，再做 tombstone 清理与会话装载。
		await migrateSideChatSessions();
		await purgeTombstonedLocalRecords();
		const deletedSessions = await loadDeletedSessionIds();
		const deletedSpaces = await loadDeletedSpaceIds();
		const deletedSpacePaths = await loadDeletedSpacePaths();
		const initialSessions = (await loadSessions()).filter(
			s => !deletedSessions.has(s.id),
		);
		// 本地索引缺失（如桌面/浏览器切换）时，从后端磁盘恢复历史会话。
		await importServerSessions(initialSessions);
		let [rawSpaces, rawSessions] = await Promise.all([
			loadSpaces(),
			loadSessions(),
		]);
		rawSpaces = rawSpaces.filter(
			s =>
				!deletedSpaces.has(s.id) &&
				(!s.rootPath?.trim() ||
					!deletedSpacePaths.has(normalizePath(s.rootPath))),
		);
		rawSessions = rawSessions.filter(s => !deletedSessions.has(s.id));
		const {spaces, sessions: allSessions} = await mergeDuplicateRootSpaces(
			rawSpaces,
			rawSessions,
		);
		// 孤儿会话不进内存视图：spaceId 指向已移除的工作区（「移除工作区
		// 仅隐藏对话」语义），记录留在 IndexedDB 等待重开同一文件夹时
		// 经 adoptWorkspaceSessions 归位，无需在此复活。
		const knownSpaceIds = new Set(spaces.map(s => s.id));
		const sessions = allSessions.filter(
			s => s.spaceId === SIDE_SPACE_ID || knownSpaceIds.has(s.spaceId),
		);
		const messagesById: Record<string, ChatMessage[]> = {};
		// 启动时主视图只认主工作区会话；侧聊会话走 /side/ 路由按需选中。
		const first = sessions.find(
			s => s.spaceId !== SIDE_SPACE_ID && !s.archived,
		);
		const activeSessions = first ? [first] : [];
					const rollbackRows = await Promise.all(
				activeSessions.map(async session => {
					/* V2 前端已退役：启动一律 idle；未决态由 rewindV3Store.rehydrate 接管。 */
					void loadRollbackState(session.id).catch(() => null);
					return [session.id, idleRollbackState()] as const;
				}),
				);
				const historyRows = await Promise.all(
					activeSessions.map(async session => [
						session.id,
						normalizeChatHistoryState(
							await loadChatHistoryState(session.id),
							session.id,
						),
					] as const),
					);
				const historyById = Object.fromEntries(historyRows);

		let firstLocalRef: ChatMessage[] | undefined;
		if (first) {
			// 启动同样走「本地先行」：IDB 几 ms 内可渲染，服务端回填放后台，
			// 首屏不再等 /v1/sessions/{id}/messages 往返。
			firstLocalRef = await loadLocalSessionMessages(first.id);
			messagesById[first.id] = firstLocalRef;
		}
		const settled = settleAllSessionTools(messagesById);
		for (const sid of settled.dirtySessionIds) {
			void replaceMessages(sid, settled.messagesById[sid]!);
		}
		const activeSpaceId =
			first?.spaceId ?? spaces[0]?.id ?? DEFAULT_SPACE_ID;
		const rollbackById = Object.fromEntries(rollbackRows);
		const pendingPermission =
			savedPendingPermission &&
			sessions.some(s => s.id === savedPendingPermission?.sessionId)
				? savedPendingPermission
				: null;
		if (savedPendingPermission && !pendingPermission) {
			writePendingPermission(null);
		}
		// 水合前已经踩过守卫（pre-hydrate 窗口里发过消息）时，那条横幅属于仍将
		// 活动的会话：不许被整包水合静默抹掉——用户刚看到的"为什么没发出去"
		// 不许凭空消失（e2e 实测：未开文件夹先发送，横幅出现后又被水合清掉）。
		const preHydrateKeepBanner = Boolean(
			get().errorBanner &&
				get().errorBannerSessionId != null &&
				get().errorBannerSessionId === (first?.id ?? null),
		);
		set({
			spaces,
			sessions,
messagesById: settled.messagesById,
			messagesLoadingIds: first ? {[first.id]: true} : {},
							historyById: Object.fromEntries(historyRows),
							rollbackById,
							sessionUsageById: Object.fromEntries(
							sessions.map(s => [
								s.id,
								s.usage ? {...s.usage, usdLimit: null} : null,
							]),
						),
						sessionStreams: normalizeSessionStreams(get()),
			hydrated: true,
			activeId: first?.id ?? null,
			activeSpaceId,
			pendingPermission,
			...(preHydrateKeepBanner ? {} : sessionErrorBannerPatch(null, null)),
		});
		const activeSpace = spaces.find(s => s.id === activeSpaceId);
		void syncWorkspaceRoot(activeSpace?.rootPath);
		if (first) {
			void get().loadAgentsFor(first.id);
			const loadOwnership = createStreamOwnership(set, get, first.id, activeBackendSessionId(historyById, first.id));
			const isCurrent = loadOwnership.isCurrent;
			// Same-turn local UI/input changes survive the asynchronous backfill.
			void (async () => {
				try {
					const chosen = await loadSessionMessagesWithBackfill(
						first.id,
						historyById,
						{isCurrent},
					);
					set(cur =>
						isCurrent() && cur.sessions.some(x => x.id === first.id)
							? {
									messagesById: {
										...cur.messagesById,
										[first.id]: projectHistoryBackfill(firstLocalRef ?? [], cur.messagesById[first.id] ?? [], chosen),
									},
								}
							: cur,
					);
					const projected = get().messagesById[first.id];
					if (isCurrent() && projected && projected !== chosen) {
						await replaceMessages(first.id, projected, () => isCurrent() && get().messagesById[first.id] === projected);
					}
				} catch {}
				finally {
					set(cur => {
						if (!cur.messagesLoadingIds[first.id]) {
							return cur;
						}
						const messagesLoadingIds = {...cur.messagesLoadingIds};
						delete messagesLoadingIds[first.id];
						return {messagesLoadingIds};
					});
				}
			})();
		}
		// 后台预热其余会话：有界并发替代串行 for-await —— 会话多时
		// 不再让排在后面的会话长期处于冷状态（点击时仍要走网络）。
		void (async () => {
			const rest = sessions.filter(s => s.id !== first?.id);
			const CONCURRENCY = 6;
			let cursor = 0;
			const worker = async () => {
				while (cursor < rest.length) {
					const s = rest[cursor++]!;
					let loadOwnership = createStreamOwnership(set, get, s.id, activeBackendSessionId(get().historyById, s.id));
					void get().loadAgentsFor(s.id);
					set(cur =>
						cur.sessions.some(x => x.id === s.id)
							? {
									messagesLoadingIds: {
										...cur.messagesLoadingIds,
										[s.id]: true,
									},
								}
							: cur,
					);
					try {
						if (!loadOwnership.isCurrent() || !await ensureSessionHistory(set, get, s.id)) continue;
						loadOwnership = createStreamOwnership(set, get, s.id, activeBackendSessionId(get().historyById, s.id));
						const hist = normalizeChatHistoryState(get().historyById[s.id], s.id);
						const msgs = await loadSessionMessagesWithBackfill(s.id, {
							[s.id]: hist,
						}, {isCurrent: loadOwnership.isCurrent});
						set(cur =>
							loadOwnership.isCurrent() && cur.messagesById[s.id] === undefined &&
							cur.sessions.some(x => x.id === s.id)
								? {
										messagesById: {
											...cur.messagesById,
											[s.id]: msgs,
										},
									}
								: cur,
						);
					} catch {}
					finally {
						set(cur => {
							if (!cur.messagesLoadingIds[s.id]) {
								return cur;
							}
							const messagesLoadingIds = {...cur.messagesLoadingIds};
							delete messagesLoadingIds[s.id];
							return {messagesLoadingIds};
						});
					}
				}
			};
			await Promise.all(
				Array.from({length: Math.min(CONCURRENCY, rest.length)}, worker),
			);
		})();
	},

	async hydrate() {
		if (hydrateInFlight) {
			return hydrateInFlight;
		}
		const task = get().hydrateOnce();
		hydrateInFlight = task;
		try {
			await task;
		} finally {
			if (hydrateInFlight === task) {
				hydrateInFlight = null;
			}
		}
	},

	async setActiveSpace(spaceId) {
		set({activeSpaceId: spaceId});
		const space = get().spaces.find(s => s.id === spaceId);
		await syncWorkspaceRoot(space?.rootPath);
	},

	toggleSpaceCollapsed(spaceId) {
		set(s => {
			const collapsedSpaces = {
				...s.collapsedSpaces,
				[spaceId]: !s.collapsedSpaces[spaceId],
			};
			persistCollapsed(collapsedSpaces);
			return {collapsedSpaces};
		});
	},

	async openFolder(rootPath) {
		const path = rootPath.trim();
		if (!path) {
			throw new Error('文件夹路径为空');
		}
		await clearSpacePathTombstone(path);
		const key = normalizePath(path);
		const inflight = openInFlight.get(key);
		if (inflight) {
			return inflight;
		}

		const promise = (async () => {
			// 归属恢复结果 merge 进 store：已有会话改挂 spaceId，新导入的追加。
			const mergeAdopted = (adopted: ChatSession[]) => {
				if (adopted.length > 0) {
					set(s => ({
						sessions: s.sessions
							.map(x => adopted.find(a => a.id === x.id) ?? x)
							.concat(
								adopted.filter(
									a => !s.sessions.some(y => y.id === a.id),
								),
							),
					}));
				}
			};
			// 进入临界区后（及任何 await 后）重新检查。
			let existing = findSpaceByRoot(get().spaces, path);
			if (existing) {
				if (existing.rootPath !== path) {
					const next = {
						...existing,
						rootPath: path,
						name: folderName(path),
						updatedAt: Date.now(),
					};
					await saveSpace(next);
					set(s => ({
						spaces: s.spaces.map(x =>
							x.id === next.id ? next : x,
						),
					}));
					existing = next;
				}
				set(s => ({
					activeSpaceId: existing!.id,
					collapsedSpaces: {
						...s.collapsedSpaces,
						[existing!.id]: false,
					},
				}));
				persistCollapsed({
					...get().collapsedSpaces,
					[existing.id]: false,
				});
				await syncWorkspaceRoot(existing.rootPath);
				// An earlier open may have created this space but failed to reattach
				// its orphaned sessions. Retry adoption whenever the folder is opened.
				try {
					mergeAdopted(
						await adoptWorkspaceSessions(existing.id, existing.rootPath),
					);
				} catch {
					/* Session adoption failure does not prevent opening the workspace. */
				}
				return existing.id;
			}

			const space = newSpace(folderName(path), path);
			await saveSpace(space);

			// 另一并发打开可能已胜出 — 优先使用已存储的匹配项。
			const raced = findSpaceByRoot(
				get().spaces.filter(s => s.id !== space.id),
				path,
			);
			if (raced) {
				await deleteSpaceRecord(space.id);
				set(s => ({
					activeSpaceId: raced.id,
					collapsedSpaces: {
						...s.collapsedSpaces,
						[raced.id]: false,
					},
				}));
				persistCollapsed({
					...get().collapsedSpaces,
					[raced.id]: false,
				});
				// 重开同一文件夹：按后端 ws_index 把归属会话挂回
				//（移除工作区时被迁往默认分区的归位；本地缺的从磁盘导入）。
				try {
					mergeAdopted(await adoptWorkspaceSessions(raced.id, path));
				} catch {
					/* 归属恢复失败不影响打开 */
				}
				await syncWorkspaceRoot(raced.rootPath);
				return raced.id;
			}

			// 工作区同步为尽力而为 — 若 BE cwd API 失败不回滚已保存的 space。
			await syncWorkspaceRoot(path);
			set(s => ({
				spaces: [space, ...s.spaces.filter(x => x.id !== space.id)],
				activeSpaceId: space.id,
				collapsedSpaces: {...s.collapsedSpaces, [space.id]: false},
			}));
			persistCollapsed({...get().collapsedSpaces, [space.id]: false});
			try {
				mergeAdopted(await adoptWorkspaceSessions(space.id, path));
			} catch {
				/* 归属恢复失败不影响打开 */
			}
			return space.id;
		})().finally(() => {
			openInFlight.delete(key);
		});

		openInFlight.set(key, promise);
		return promise;
	},

	async enterSpace(spaceId) {
		const sessions = get()
			.sessions.filter(s => s.spaceId === spaceId && !s.archived)
			.sort((a, b) => b.updatedAt - a.updatedAt);
		const latest = sessions[0];
		if (latest) {
			await get().selectSession(latest.id);
			return latest.id;
		}
		return get().createSession(spaceId);
	},

	async removeSpace(spaceId) {
		const before = get();
		const doomed = before.sessions.filter(x => x.spaceId === spaceId);
		for (const sess of doomed) {
			const stream = getSessionStream(before, sess.id);
			if (stream.isLoading || stream.draining) {
				await interruptChat(
					activeBackendSessionId(before.historyById, sess.id),
				);
				stream.abortRef?.abort();
				discardDrainForSession(sess.id);
			}
		}
		const doomedSpace = before.spaces.find(x => x.id === spaceId);
		await markSpaceDeleted(spaceId, doomedSpace?.rootPath);
		// 2026-09-05（二稿）：移除工作区 = 仅从侧栏隐藏。会话记录与其
		// 消息原样留在 IndexedDB（spaceId 仍指向被移除的 space），不
		// 迁移、不 tombstone、不删后端；hydrate 会把这类孤儿会话挡在
		// 内存视图之外。重新打开同一文件夹时 openFolder →
		// adoptWorkspaceSessions 按后端 ws_index 把它们挂回新 space，
		// 对话即恢复显示（一稿曾迁入默认分区，用户不需要该中间态）。
		await deleteSpace(spaceId);
		set(s => {
			const spaces = s.spaces.filter(x => x.id !== spaceId);
			const removedIds = new Set(doomed.map(x => x.id));
			const sessions = s.sessions.filter(x => !removedIds.has(x.id));
			const messagesById = {...s.messagesById};
			for (const id of removedIds) {
				delete messagesById[id];
			}
			const messagesLoadingIds = {...s.messagesLoadingIds};
			for (const id of removedIds) {
				delete messagesLoadingIds[id];
			}
			const activeId =
				s.activeId && sessions.some(x => x.id === s.activeId)
					? s.activeId
					: (sessions.find(x => !x.archived)?.id ?? null);
			let sessionStreams = s.sessionStreams;
			for (const id of removedIds) {
				sessionStreams = clearSessionStreamState(sessionStreams, id);
			}
			return {
				spaces,
				sessions,
				messagesById,
				messagesLoadingIds,
				activeId,
				activeSpaceId:
					s.activeSpaceId === spaceId
						? (spaces[0]?.id ?? DEFAULT_SPACE_ID)
						: s.activeSpaceId,
				sessionStreams,
			};
		});
	},

	async renameSpace(spaceId, name) {
		const cur = get().spaces.find(s => s.id === spaceId);
		if (!cur) {
			return;
		}
		const next = {...cur, name: name.trim() || cur.name, updatedAt: Date.now()};
		await saveSpace(next);
		set(s => ({
			spaces: s.spaces.map(x => (x.id === spaceId ? next : x)),
		}));
	},

	async createSession(spaceId) {
		const sid = spaceId ?? get().activeSpaceId ?? DEFAULT_SPACE_ID;
		const existing = createInFlight.get(sid);
		if (existing) {
			return existing;
		}

		const promise = (async () => {
			const state = get();
			// 只复用本地已明确加载、无消息、无输入草稿的空会话。
			// 未加载会话仍可能有服务端历史；空消息会话也可能保存了待发草稿。
			const empties: ChatSession[] = [];
			for (const s of state.sessions) {
				// 归档会话是用户保留的历史项，不得作为空白草稿复用或清理。
				if (s.spaceId !== sid || s.archived) {
					continue;
				}
				// 乐观装载中（本地先行/回填未完成）的会话：既不能当空会话
				// 复用/清理，也不能用此刻的空 IDB 快照覆盖 messagesById。
				if (state.messagesLoadingIds[s.id]) {
					continue;
				}
				const cached = state.messagesById[s.id];
				if (
					cached !== undefined &&
					cached.length === 0 &&
					!getComposerDraft(s.id)
				) {
					empties.push(s);
				}
			}
			if (empties.length > 0) {
				const keep = empties[0]!;
				set(s => ({
					activeId: keep.id,
					activeSpaceId: sid,
					collapsedSpaces: {...s.collapsedSpaces, [sid]: false},
					emptyQuipSeq: s.emptyQuipSeq + 1,
				}));
				persistCollapsed({...get().collapsedSpaces, [sid]: false});
				return keep.id;
			}

			const now = Date.now();
			const session: ChatSession = {
				id: uid('sess'),
				spaceId: sid,
				title: '新对话',
				createdAt: now,
				updatedAt: now,
			};
			await saveSession(session);
			const space = get().spaces.find(s => s.id === sid);
			if (space) {
				await saveSpace({...space, updatedAt: now});
			}
			set(s => ({
				sessions: [session, ...s.sessions],
				spaces: s.spaces
					.map(x => (x.id === sid ? {...x, updatedAt: now} : x))
					.sort((a, b) => b.updatedAt - a.updatedAt),
messagesById: {...s.messagesById, [session.id]: []},
					historyById: {
						...s.historyById,
						[session.id]: defaultChatHistoryState(),
					},
					activeId: session.id,
				activeSpaceId: sid,
				collapsedSpaces: {...s.collapsedSpaces, [sid]: false},
				emptyQuipSeq: s.emptyQuipSeq + 1,
			}));
			persistCollapsed({...get().collapsedSpaces, [sid]: false});
			return session.id;
		})().finally(() => {
			createInFlight.delete(sid);
		});

		createInFlight.set(sid, promise);
		return promise;
	},

		async createSideSession() {
		// 侧聊会话：虚拟 space（side-chat-space）+ side- 前缀 id；后端据此走
		// 只读 side 模式。不切换 activeSpaceId / 工作区绑定。
		const now = Date.now();
		const session: ChatSession = {
			id: `side-${uid()}`,
			spaceId: SIDE_SPACE_ID,
			title: '新对话',
			createdAt: now,
			updatedAt: now,
		};
		await saveSession(session);
		set(s => ({
			sessions: [session, ...s.sessions],
			messagesById: {...s.messagesById, [session.id]: []},
			historyById: {
				...s.historyById,
				[session.id]: defaultChatHistoryState(session.id),
			},
			activeId: session.id,
			emptyQuipSeq: s.emptyQuipSeq + 1,
		}));
		return session.id;
	},

async selectSession(id) {
		const state = get();
		const sess = state.sessions.find(s => s.id === id);
		if (!sess) {
			// 幽灵 URL / 已删除 session — 不要将 activeId 钉到缺失 id。
			return;
		}
		const spaceId = sess.spaceId;
		// 侧聊是虚拟 space：不接管 activeSpaceId，也不动工作区 cwd 绑定，
		// 否则回到主视图的新建/选目录会落到 side-chat-space。
		const sideSession = spaceId === SIDE_SPACE_ID;
		// 深链/命令面板打开已归档会话时，先展开所属列表；否则会话虽已激活，
		// 归档筛选生效后它仍藏在折叠的 space / side-chat 分组里。
		if (sess.archived && state.collapsedSpaces[spaceId]) {
			const collapsedSpaces = {...state.collapsedSpaces, [spaceId]: false};
			set({collapsedSpaces});
			persistCollapsed(collapsedSpaces);
		}
		// 已在查看此 session — 仅刷新工作区 cwd（非阻塞）。
		if (
			state.activeId === id &&
			(sideSession || state.activeSpaceId === spaceId) &&
			state.messagesById[id] !== undefined
		) {
			const space = state.spaces.find(s => s.id === spaceId);
			void syncWorkspaceRoot(space?.rootPath);
			return;
		}

		// 多 Agent 浏览视图属于会话内存态：切会话回到主视图（浏览器式栈不跨会话）。
		if (state.activeId !== id) {
			get().resetAgentView();
		}
		void get().loadAgentsFor(id);

		// 乐观切换：同步先落 activeId（含空间绑定），调用方的路由立刻完成；
		// 冷会话消息走后台「本地 IDB 先行 → 服务端回填」，绝不阻塞切换。
		const cold = state.messagesById[id] === undefined;
		set(s => ({
			activeId: id,
			...(sideSession ? {} : {activeSpaceId: spaceId}),
			...(cold ? {messagesLoadingIds: {...s.messagesLoadingIds, [id]: true}} : {}),
		}));

		if (cold) {
			let loadOwnership = createStreamOwnership(set, get, id, activeBackendSessionId(get().historyById, id));
			// detach 的装载管线：本地 IDB（几 ms）先给 UI，网络回填随后替换。
			// 缓存按会话写入，切走后仍可完成；消息引用校验保护并发新发送。
			// 同一会话重复启动装载时，仅最新请求能结束 loading 标记。
			const loadToken = Symbol(id);
			sessionLoadTokens.set(id, loadToken);
			void (async () => {
				let localRef: ChatMessage[] | undefined;
				let localSnapshot: Awaited<ReturnType<typeof loadLocalSessionSnapshot>> | undefined;
				try {
					localSnapshot = await loadLocalSessionSnapshot(id);
					const local = localSnapshot.messages;
					// 仅在本地确有内容时先行写入：空数组不能提前落 —— 否则
					// createSession 的 empties 复用逻辑会把仍在回填的会话
					// 误判为「空对话」而复用/删除。本地为空时等服务端回填定夺。
					const current = get();
					if (
						loadOwnership.isCurrent() &&
						local.length > 0 &&
						current.sessions.some(session => session.id === id) &&
						current.messagesById[id] === undefined
					) {
						localRef = local;
						set(s => ({messagesById: {...s.messagesById, [id]: local}}));
					}
				} catch {}
				try {
					if (!loadOwnership.isCurrent() || !await ensureSessionHistory(set, get, id)) return;
					loadOwnership = createStreamOwnership(set, get, id, activeBackendSessionId(get().historyById, id));
					const hist = normalizeChatHistoryState(get().historyById[id], id);
					const chosen = await loadSessionMessagesWithBackfill(id, {
						[id]: hist,
					}, {localSnapshot, isCurrent: loadOwnership.isCurrent});
					set(s => {
						if (!loadOwnership.isCurrent()) return s;
						const cur = s.messagesById[id];
						// 覆盖条件：仍是我们本地先行写入的引用，或仍无人填充
						// （本地为空时 localRef === undefined）。期间用户发过消息 /
						// hydrate 预载写过 → 跳过，避免用服务端快照冲掉新状态。
						if (cur !== localRef && cur !== undefined) {
							return s;
						}
						if (!s.sessions.some(x => x.id === id)) {
							return s;
						}
						if (cur === chosen) return s;
						return {messagesById: {...s.messagesById, [id]: chosen}};
					});
				} catch {}
				finally {
					if (sessionLoadTokens.get(id) === loadToken) {
						sessionLoadTokens.delete(id);
						set(s => {
							if (!s.messagesLoadingIds[id]) {
								return s;
							}
							const messagesLoadingIds = {...s.messagesLoadingIds};
							delete messagesLoadingIds[id];
							return {messagesLoadingIds};
						});
					}
				}
			})();
		}

		const space = get().spaces.find(s => s.id === spaceId);
		// 永不阻塞 UI / 发送路径于工作区 API；侧聊不绑定工作区。
		if (!sideSession) {
			void syncWorkspaceRoot(space?.rootPath);
		}
		useCommandPaletteStore.getState().touchAgent({
			id: sess.id,
			title: sess.title,
			spaceName: space?.name || 'XEYO',
		});
	},

	async removeSession(id) {
		const state = get();
		const stream = getSessionStream(state, id);
		if (isSessionStreamLive(stream)) {
			// 编辑重发/回溯分叉后本地 id ≠ backend id：用错 id 的 interrupt
			// 打不到真实回合，后端会继续写已删会话的 transcript。
			await interruptChat(activeBackendSessionId(state.historyById, id));
			stream.abortRef?.abort();
		}
		// 给已删会话排队的 thoughtSync 定时器会在触发时往服务端写 ui_thoughts
		//（已删会话 transcript 复活）——一并取消。
		const pendingThought = thoughtSyncTimers.get(id);
		if (pendingThought) {
			window.clearTimeout(pendingThought);
			thoughtSyncTimers.delete(id);
		}
		discardDrainForSession(id);
		clearWaitingToolTimer(id);
		await tombstoneAndDeleteOnServer(id, state.historyById);
		await deleteSession(id);
		await clearChatHistoryState(id);
		await clearRollbackState(id);
		clearComposerDraft(id);
		clearTodoDismissal(id);
		set(s => {
			const sessions = s.sessions.filter(x => x.id !== id);
			const messagesById = {...s.messagesById};
			delete messagesById[id];
			const inboxBySession = {...s.inboxBySession};
			delete inboxBySession[id];
				const historyById = {...s.historyById};
				delete historyById[id];
				const sessionTodosById = {...s.sessionTodosById};
			delete sessionTodosById[id];
			const sessionGoalById = {...s.sessionGoalById};
			delete sessionGoalById[id];
			const sessionJobsById = {...s.sessionJobsById};
			delete sessionJobsById[id];
			// 其余 per-session Map 一并清理，避免无界增长。
			const sessionUsageById = {...s.sessionUsageById};
			delete sessionUsageById[id];
			const multiAgentTasksBySession = {...s.multiAgentTasksBySession};
			delete multiAgentTasksBySession[id];
			const agentsBySession = {...s.agentsBySession};
			delete agentsBySession[id];
			const agentTranscriptsById = {...s.agentTranscriptsById};
			for (const key of Object.keys(agentTranscriptsById)) {
				if (key === id || key.startsWith(`${id}::`)) {
					delete agentTranscriptsById[key];
				}
			}
			const liveAgentTextById = {...s.liveAgentTextById};
			for (const key of Object.keys(liveAgentTextById)) {
				if (key === id || key.startsWith(`${id}::`)) {
					delete liveAgentTextById[key];
				}
			}
			const recoveryBySession = {...s.recoveryBySession};
			delete recoveryBySession[id];
			const messagesLoadingIds = {...s.messagesLoadingIds};
			delete messagesLoadingIds[id];
			const activeId =
				s.activeId === id
					? (sessions.find(session => !session.archived)?.id ?? null)
					: s.activeId;
			const pendingCleared = clearPendingFieldsForSession(s, id);
			if (s.pendingPermission?.sessionId === id) {
				writePendingPermission(null);
			}
			return {
				sessions,
					messagesById,
					inboxBySession,
					messagesLoadingIds,
					historyById,
					sessionTodosById,
					sessionGoalById,
					sessionJobsById,
				sessionUsageById,
				multiAgentTasksBySession,
				agentsBySession,
				agentTranscriptsById,
				liveAgentTextById,
				recoveryBySession,
				activeId,
				sessionStreams: clearSessionStreamState(s.sessionStreams, id),
				...pendingCleared,
				...(s.errorBannerSessionId === id
					? sessionErrorBannerPatch(null, null)
					: {}),
			};
		});
	},

	async renameSession(id, title) {
		const clean = (title || '').trim();
		if (!clean) {
			throw new Error('标题不能为空');
		}
		const cur = get().sessions.find(x => x.id === id);
		if (!cur) {
			return;
		}
		if (cur.archived) {
			throw new Error('归档对话为只读，请先恢复');
		}
		const ok = await renameServerSession(id, clean);
		if (!ok) {
			throw new Error('重命名失败，请稍后重试');
		}
		const latest = get().sessions.find(x => x.id === id);
		if (!latest || latest.archived) {
			return;
		}
		const next = {...latest, title: clean};
		await saveSession(next);
		set(s => ({
			sessions: s.sessions.map(x => (x.id === id ? next : x)),
		}));
	},

	async forkSession(id) {
		const state = get();
		const src = state.sessions.find(x => x.id === id);
		if (!src) {
			throw new Error('会话不存在');
		}
		const fork = await forkServerSession(id);
		if (!fork) {
			throw new Error('分叉失败：服务端未返回新会话');
		}
		const sideSession = src.spaceId === SIDE_SPACE_ID;
		const now = Date.now();
		const session: ChatSession = {
			id: fork.newId,
			spaceId: src.spaceId,
			title: fork.title,
			createdAt: now,
			updatedAt: now,
		};
		await saveSession(session);
		set(s => ({
			sessions: [session, ...s.sessions],
			// 不预置 messagesById[newId]=[]：那会把"未加载"伪装成"已加载的空
			// 会话"，selectSession 的冷载判据（undefined 才算冷）随之短路 ——
			// 分叉体明明是服务端复制来的历史，界面却恒空（e2e 实测 20s 无回填，
			// 刷新后才出现）。留 undefined 让冷载管线（IDB→服务端回填）接管。
			historyById: {
				...s.historyById,
				[session.id]: defaultChatHistoryState(session.id),
			},
			activeId: session.id,
			...(sideSession
				? {}
				: {
						activeSpaceId: src.spaceId,
						collapsedSpaces: {...s.collapsedSpaces, [src.spaceId]: false},
					}),
		}));
		if (!sideSession) {
			persistCollapsed({...get().collapsedSpaces, [src.spaceId]: false});
		}
		return session.id;
	},

	async archiveSession(id) {
		const inFlight = archiveInFlight.get(id);
		if (inFlight) {
			return inFlight;
		}
		const cur = get().sessions.find(x => x.id === id);
		if (!cur || cur.archived) {
			return;
		}
		const next = {...cur, archived: true, archivedAt: Date.now()};
		// 先在本地锁定该会话，发送入口会立即按 archived 拒绝新回合。
		set(s => ({sessions: s.sessions.map(x => (x.id === id ? next : x))}));
		const operation = (async () => {
			const before = get();
			const stream = getSessionStream(before, id);
			if (isSessionStreamLive(stream)) {
				const receipt = await interruptChat(
					activeBackendSessionId(before.historyById, id),
				);
				if (!receipt.ok && receipt.message !== 'not_running') {
					throw new Error(`停止请求未被后端确认（${receipt.message}），归档已取消`);
				}
				stream.abortRef?.abort();
				commitDrainForSession(id);
				const pendingThought = thoughtSyncTimers.get(id);
				if (pendingThought) {
					window.clearTimeout(pendingThought);
					thoughtSyncTimers.delete(id);
				}
			}
			const ok = await archiveServerSession(id);
			if (!ok) {
				throw new Error('归档失败，请稍后重试');
			}
			// 服务端已经确认后立即持久化；IDB 故障不能反转服务端已完成的归档。
			const latest = get().sessions.find(x => x.id === id);
			if (latest) {
				const persisted = {
					...latest,
					archived: true,
					archivedAt: next.archivedAt,
				};
				set(s => ({
					sessions: s.sessions.map(x => (x.id === id ? persisted : x)),
				}));
				await saveSession(persisted).catch(() => undefined);
			}
		})();
		archiveInFlight.set(id, operation);
		try {
			await operation;
		} catch (error) {
			set(s => ({
				sessions: s.sessions.map(x =>
					x.id === id && x.archivedAt === next.archivedAt
						? {...x, archived: cur.archived, archivedAt: cur.archivedAt}
						: x,
				),
			}));
			throw error;
		} finally {
			if (archiveInFlight.get(id) === operation) {
				archiveInFlight.delete(id);
			}
		}
	},

	async restoreSession(id) {
		const archive = archiveInFlight.get(id);
		if (archive) {
			await archive;
		}
		const ok = await restoreServerSession(id);
		if (!ok) {
			throw new Error('恢复失败，请稍后重试');
		}
		const cur = get().sessions.find(x => x.id === id);
		if (!cur) {
			return;
		}
		const next = {...cur, archived: false, archivedAt: undefined};
		set(s => ({
			sessions: s.sessions.map(x => (x.id === id ? next : x)),
		}));
		// hydrate 会从服务端 sidecar 对账，因此本地持久化失败不会回滚已确认的恢复操作。
		await saveSession(next).catch(() => undefined);
	},
	};
}
