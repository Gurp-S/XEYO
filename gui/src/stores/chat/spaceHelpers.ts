/**
 * spaceHelpers.ts — space / session / sidebar-collapse helper functions.
 * Extracted verbatim from preStoreHelpers.ts (auto-dismantle). Behavior unchanged.
 */
import {
	deleteServerSession,
	listServerSessions,
	loadServerSessionMessages,
} from '@/lib/api';
import {
	DEFAULT_SPACE_ID,
	SIDE_SPACE_ID,
	deleteKv,
	deleteSpaceRecord,
	getKv,
	loadDeletedSessionIds,
	loadSideChatMessages,
	markSessionDeleted,
	replaceMessages,
	saveSession,
} from '@/lib/db';
import {
	normalizePath,
	samePath,
} from '@/lib/paths';
import {
	parseJsonValue,
} from '@/lib/safeJson';
import type {
	ChatHistoryState,
	ChatSpace,
	ChatSession,
	ChatUsage,
} from '@/lib/types';
import {
	activeBackendSessionId,
} from './preStoreHelpers';

const COLLAPSED_KEY = 'xeyo-space-collapsed';
const OLD_COLLAPSED_KEY = 'xy-space-collapsed';

function loadCollapsed(): Record<string, boolean> {
	try {
		let raw = localStorage.getItem(COLLAPSED_KEY);
		if (!raw) {
			raw = localStorage.getItem(OLD_COLLAPSED_KEY);
			if (raw) localStorage.setItem(COLLAPSED_KEY, raw);
		}
		return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
	} catch {
		return {};
	}
}

function persistCollapsed(map: Record<string, boolean>) {
	localStorage.setItem(COLLAPSED_KEY, JSON.stringify(map));
}

/** 去重每个 space 的并发「新建聊天」点击。 */
const createInFlight = new Map<string, Promise<string>>();

/** 去重相同规范化路径的并发打开文件夹。 */
const openInFlight = new Map<string, Promise<string>>();

/** 防止 selectSession 被乱序 loadMessages 完成影响。 */
export const selectSeqBox = { value: 0 };

/**
 * 把后端磁盘上的用户会话导入本地 IndexedDB，用于本地索引丢失时恢复历史。
 * 仅导入本地没有的 session；幂等，不影响已有数据。已 tombstone 的会话永不导入。
 */
type SideChatSessionRow = {
	id: string;
	title?: string;
	updatedAt?: number;
	usage?: ChatUsage;
};

/** 一次性迁移：旧侧聊 KV（side-chat-sessions / side-chat:messages:*）并入 IDB。 */
async function migrateSideChatSessions(): Promise<void> {
	try {
		const raw = await getKv('side-chat-sessions');
		if (!raw) {
			return;
		}
		const parsed = parseJsonValue<SideChatSessionRow[]>(raw);
		const deleted = await loadDeletedSessionIds();
		for (const s of Array.isArray(parsed) ? parsed : []) {
			if (!s || typeof s.id !== 'string' || !s.id.startsWith('side-')) {
				continue;
			}
			if (deleted.has(s.id)) {
				await clearSideChatMessagesById(s.id);
				continue;
			}
			const msgs = await loadSideChatMessages(s.id).catch(() => []);
			await saveSession({
				id: s.id,
				spaceId: SIDE_SPACE_ID,
				title: s.title || '新对话',
				createdAt: s.updatedAt ?? Date.now(),
				updatedAt: s.updatedAt ?? Date.now(),
			});
			if (msgs.length > 0) {
				await replaceMessages(s.id, msgs);
			}
			await clearSideChatMessagesById(s.id);
		}
		await deleteKv('side-chat-sessions');
		await deleteKv('side-chat-active');
	} catch {
		// 迁移失败不阻塞 hydrate；下次启动重试。
	}
}

async function clearSideChatMessagesById(sessionId: string): Promise<void> {
	try {
		await deleteKv(`side-chat:messages:${sessionId}`);
	} catch {
		/* ignore */
	}
}

async function importServerSessions(existingIds: Set<string>): Promise<void> {
	try {
		const deleted = await loadDeletedSessionIds();
		const list = await listServerSessions();
		for (const s of list) {
			if (existingIds.has(s.id) || deleted.has(s.id)) {
				continue;
			}
			existingIds.add(s.id);
			await saveSession({
				id: s.id,
				spaceId: DEFAULT_SPACE_ID,
				title: s.title || s.id,
				createdAt: s.createdAt,
				updatedAt: s.updatedAt,
			});
			const msgs = await loadServerSessionMessages(s.id);
			if (msgs.length > 0) {
				await replaceMessages(s.id, msgs);
			}
		}
	} catch {
		// 后端不可用时静默保持本地状态。
	}
}

async function tombstoneAndDeleteOnServer(
	sessionId: string,
	historyById?: Record<string, ChatHistoryState>,
): Promise<boolean> {
	const ids = new Set<string>([sessionId.trim()].filter(Boolean));
	if (historyById) {
		const backendId = activeBackendSessionId(historyById, sessionId);
		if (backendId.trim()) {
			ids.add(backendId.trim());
		}
	}
	for (const id of ids) {
		await markSessionDeleted(id);
	}
	let ok = true;
	for (const id of ids) {
		ok = (await deleteServerSession(id)) && ok;
	}
	return ok;
}

function findSpaceByRoot(
	spaces: ChatSpace[],
	rootPath: string,
): ChatSpace | undefined {
	return spaces.find(s => s.rootPath && samePath(s.rootPath, rootPath));
}

/**
 * 合并历史上共享相同文件夹路径的重复工作区。
 * 保留最近更新的 space；将 sessions 从重复项重新分配。
 */
async function mergeDuplicateRootSpaces(
	spaces: ChatSpace[],
	sessions: ChatSession[],
): Promise<{spaces: ChatSpace[]; sessions: ChatSession[]}> {
	const groups = new Map<string, ChatSpace[]>();
	for (const s of spaces) {
		const root = s.rootPath?.trim();
		if (!root) {
			continue;
		}
		const key = normalizePath(root);
		const list = groups.get(key) ?? [];
		list.push(s);
		groups.set(key, list);
	}

	let nextSpaces = [...spaces];
	let nextSessions = [...sessions];

	for (const group of groups.values()) {
		if (group.length < 2) {
			continue;
		}
		group.sort((a, b) => b.updatedAt - a.updatedAt);
		const keeper = group[0]!;
		const doomed = group.slice(1);
		for (const dupe of doomed) {
			const moved = nextSessions.filter(s => s.spaceId === dupe.id);
			for (const sess of moved) {
				const patched = {
					...sess,
					spaceId: keeper.id,
					updatedAt: Math.max(sess.updatedAt, Date.now()),
				};
				await saveSession(patched);
				nextSessions = nextSessions.map(x =>
					x.id === sess.id ? patched : x,
				);
			}
			await deleteSpaceRecord(dupe.id);
			nextSpaces = nextSpaces.filter(x => x.id !== dupe.id);
		}
	}

	return {spaces: nextSpaces, sessions: nextSessions};
}

export {
	COLLAPSED_KEY,
	OLD_COLLAPSED_KEY,
	createInFlight,
	findSpaceByRoot,
	importServerSessions,
	loadCollapsed,
	mergeDuplicateRootSpaces,
	migrateSideChatSessions,
	openInFlight,
	persistCollapsed,
	tombstoneAndDeleteOnServer,
};
export type {SideChatSessionRow};
