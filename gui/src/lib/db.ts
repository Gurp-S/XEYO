import {openDB, type DBSchema, type IDBPDatabase} from 'idb';
import type {
	ChatHistoryState,
	ChatMessage,
	ChatSession,
	ChatSpace,
} from './types';
import {folderName, normalizePath} from './paths';
import {coerceJsonText, parseJsonValue} from './safeJson';
import {uid} from './utils';

export const DEFAULT_SPACE_ID = 'space_default';
export const DEFAULT_SPACE_NAME = '本地工作区';
/** 侧聊虚拟 space：只作 session.spaceId 标记，不入 spaces 表（不出现在主侧栏）。 */
export const SIDE_SPACE_ID = 'side-chat-space';

interface XeyoDB extends DBSchema {
	spaces: {
		key: string;
		value: ChatSpace;
		indexes: {'by-updated': number};
	};
	sessions: {
		key: string;
		value: ChatSession;
		indexes: {'by-updated': number; 'by-space': string};
	};
	messages: {
		key: string;
		value: ChatMessage & {sessionId: string};
		indexes: {'by-session': string};
	};
	kv: {
		key: string;
		value: string;
	};
}

let dbPromise: Promise<IDBPDatabase<XeyoDB>> | null = null;

const OLD_DB_NAME = 'xenyon-web';
const NEW_DB_NAME = 'xeyo-web';
const MIGRATED_KEY = '__xeyo_migrated__';
const DELETED_SESSIONS_KEY = 'deleted-session-ids';
const DELETED_SPACES_KEY = 'deleted-space-ids';
const DELETED_SPACE_PATHS_KEY = 'deleted-space-paths';
const SIDE_CHAT_SESSIONS_KEY = 'side-chat-sessions';
const SIDE_CHAT_ACTIVE_KEY = 'side-chat-active';

function dbUpgrade(db: any, _oldVersion: number) {
	if (!db.objectStoreNames.contains('messages')) {
		const messages = db.createObjectStore('messages', {keyPath: 'id'});
		messages.createIndex('by-session', 'sessionId');
	}
	if (!db.objectStoreNames.contains('sessions')) {
		const sessions = db.createObjectStore('sessions', {keyPath: 'id'});
		sessions.createIndex('by-updated', 'updatedAt');
		sessions.createIndex('by-space', 'spaceId');
	}
	if (!db.objectStoreNames.contains('spaces')) {
		const spaces = db.createObjectStore('spaces', {keyPath: 'id'});
		spaces.createIndex('by-updated', 'updatedAt');
	}
	if (!db.objectStoreNames.contains('kv')) {
		db.createObjectStore('kv');
	}
}

async function markTombstoneId(key: string, id: string): Promise<void> {
	const trimmed = id.trim();
	if (!trimmed) {
		return;
	}
	const ids = await loadTombstoneIds(key);
	if (ids.has(trimmed)) {
		return;
	}
	ids.add(trimmed);
	await setKv(key, JSON.stringify([...ids]));
}

async function loadTombstoneIds(key: string): Promise<Set<string>> {
	const raw = await getKv(key);
	if (!raw) {
		return new Set();
	}
	try {
		const parsed = parseJsonValue(raw);
		if (!Array.isArray(parsed)) {
			return new Set();
		}
		return new Set(parsed.filter((x): x is string => typeof x === 'string'));
	} catch {
		return new Set();
	}
}

async function markMigrationComplete(db: IDBPDatabase<XeyoDB>): Promise<void> {
	await db.put('kv', '1', MIGRATED_KEY);
}

function dropOldDatabase(): void {
	try {
		indexedDB.deleteDatabase(OLD_DB_NAME);
	} catch {
		/* 忽略 */
	}
}

async function mergeKvTombstones(
	db: IDBPDatabase<XeyoDB>,
	key: string,
	incomingRaw: string | undefined,
): Promise<void> {
	if (incomingRaw === undefined) {
		return;
	}
	const existing = await db.get('kv', key);
	let merged = new Set<string>();
	for (const raw of [existing, incomingRaw]) {
		if (!raw) {
			continue;
		}
		try {
			const parsed = parseJsonValue(raw);
			if (Array.isArray(parsed)) {
				for (const item of parsed) {
					if (typeof item === 'string' && item.trim()) {
						merged.add(item.trim());
					}
				}
			}
		} catch {
			/* 忽略畸形的墓碑数据 */
		}
	}
	if (merged.size === 0) {
		return;
	}
	await db.put('kv', JSON.stringify([...merged]), key);
}

async function finalizeMigration(db: IDBPDatabase<XeyoDB>): Promise<IDBPDatabase<XeyoDB>> {
	await markMigrationComplete(db);
	dropOldDatabase();
	return db;
}

async function migrateOldDb(): Promise<IDBPDatabase<XeyoDB>> {
	try {
		const existing = await openDB<XeyoDB>(NEW_DB_NAME, 4, {upgrade: dbUpgrade});
		const flag = await existing.get('kv', MIGRATED_KEY);
		if (flag) {
			return existing;
		}
	} catch {
		/* 新库尚未就绪 */
	}

	try {
		const newDb = await openDB<XeyoDB>(NEW_DB_NAME, 4, {upgrade: dbUpgrade});
		const newHasData =
			(await newDb.count('sessions')) > 0 ||
			(await newDb.count('messages')) > 0 ||
			(await newDb.count('spaces')) > 0;

		let oldDb: IDBPDatabase<XeyoDB> | null = null;
		try {
			oldDb = await openDB<XeyoDB>(OLD_DB_NAME, 4);
		} catch {
			oldDb = null;
		}

		if (!oldDb) {
			return finalizeMigration(newDb);
		}

		const oldHasData =
			(await oldDb.count('sessions')) > 0 ||
			(await oldDb.count('messages')) > 0 ||
			(await oldDb.count('spaces')) > 0;

		if (!oldHasData || newHasData) {
			// 新库已有数据时绝不从旧库覆盖（否则每次启动会把已删条目复活）。
			oldDb.close();
			return finalizeMigration(newDb);
		}

		for (const name of ['spaces', 'sessions', 'messages'] as const) {
			const all = await oldDb.getAll(name);
			if (all.length === 0) {
				continue;
			}
			const tx = newDb.transaction(name, 'readwrite');
			for (const item of all) {
				await tx.store.put(item as ChatSpace | ChatSession | (ChatMessage & {sessionId: string}));
			}
			await tx.done;
		}

		const kvKeys = await oldDb.getAllKeys('kv');
		if (kvKeys.length > 0) {
			const tombstoneKeys = new Set([
				DELETED_SESSIONS_KEY,
				DELETED_SPACES_KEY,
				DELETED_SPACE_PATHS_KEY,
			]);
			const regularKv: Array<{key: string; value: string}> = [];
			for (const key of kvKeys) {
				if (key === MIGRATED_KEY) {
					continue;
				}
				const value = await oldDb.get('kv', key);
				if (value === undefined) {
					continue;
				}
				if (tombstoneKeys.has(key)) {
					await mergeKvTombstones(newDb, key, value);
					continue;
				}
				regularKv.push({key, value});
			}
			if (regularKv.length > 0) {
				const tx = newDb.transaction('kv', 'readwrite');
				for (const {key, value} of regularKv) {
					await tx.store.put(value, key);
				}
				await tx.done;
			}
		}

		oldDb.close();
		return finalizeMigration(newDb);
	} catch (e) {
		console.warn('[XEYO] migration skipped:', e);
		try {
			const newDb = await openDB<XeyoDB>(NEW_DB_NAME, 4, {upgrade: dbUpgrade});
			return finalizeMigration(newDb);
		} catch {
			/* 继续向下执行 */
		}
	}
	return openDB<XeyoDB>(NEW_DB_NAME, 4, {upgrade: dbUpgrade});
}

function openXEYODb() {
	if (!dbPromise) {
		dbPromise = migrateOldDb();
	}
	return dbPromise;
}

function normalizeSpace(raw: ChatSpace): ChatSpace {
	const rootPath = typeof raw.rootPath === 'string' ? raw.rootPath : '';
	let name = raw.name;
	if (
		raw.id === DEFAULT_SPACE_ID ||
		name === '默认公共区' ||
		name === '未打开文件夹'
	) {
		name = DEFAULT_SPACE_NAME;
	} else if (rootPath) {
		name = folderName(rootPath);
	}
	return {...raw, name, rootPath};
}

export async function getKv(key: string): Promise<string | undefined> {
	const database = await openXEYODb();
	return coerceJsonText(await database.get('kv', key));
}

export async function setKv(key: string, value: string): Promise<void> {
	const database = await openXEYODb();
	await database.put('kv', value, key);
}

export async function deleteKv(key: string): Promise<void> {
	const database = await openXEYODb();
	await database.delete('kv', key);
}

/** 用户已删会话 tombstone：hydrate 时跳过从后端/本地 re-import。 */
export async function loadDeletedSessionIds(): Promise<Set<string>> {
	return loadTombstoneIds(DELETED_SESSIONS_KEY);
}

export async function markSessionDeleted(sessionId: string): Promise<void> {
	await markTombstoneId(DELETED_SESSIONS_KEY, sessionId);
}

/** 用户已删工作区 tombstone。 */
export async function loadDeletedSpaceIds(): Promise<Set<string>> {
	return loadTombstoneIds(DELETED_SPACES_KEY);
}

export async function loadDeletedSpacePaths(): Promise<Set<string>> {
	return loadTombstoneIds(DELETED_SPACE_PATHS_KEY);
}

export async function markSpaceDeleted(
	spaceId: string,
	rootPath?: string,
): Promise<void> {
	await markTombstoneId(DELETED_SPACES_KEY, spaceId);
	const path = rootPath?.trim();
	if (path) {
		await markTombstoneId(DELETED_SPACE_PATHS_KEY, normalizePath(path));
	}
}

export async function clearSpacePathTombstone(rootPath: string): Promise<void> {
	const path = normalizePath(rootPath);
	if (!path) {
		return;
	}
	const paths = await loadDeletedSpacePaths();
	if (!paths.has(path)) {
		return;
	}
	paths.delete(path);
	await setKv(DELETED_SPACE_PATHS_KEY, JSON.stringify([...paths]));
}

async function purgeSideChatSessions(deletedSessions: Set<string>): Promise<void> {
	if (deletedSessions.size === 0) {
		return;
	}
	const raw = await getKv(SIDE_CHAT_SESSIONS_KEY);
	if (raw) {
		try {
			const parsed = parseJsonValue(raw);
			if (Array.isArray(parsed)) {
				const next = parsed.filter(
					(row): row is {id: string} =>
						Boolean(row) &&
						typeof row === 'object' &&
						typeof (row as {id?: unknown}).id === 'string' &&
						!deletedSessions.has((row as {id: string}).id),
				);
				if (next.length !== parsed.length) {
					await setKv(SIDE_CHAT_SESSIONS_KEY, JSON.stringify(next));
					const active = await getKv(SIDE_CHAT_ACTIVE_KEY);
					if (active && deletedSessions.has(active)) {
						const nextActive = next[0]?.id ?? '';
						await setKv(SIDE_CHAT_ACTIVE_KEY, nextActive);
					}
				}
			}
		} catch {
			/* 忽略畸形的旁路聊天列表 */
		}
	}
	for (const sessionId of deletedSessions) {
		await clearSideChatMessages(sessionId).catch(() => undefined);
	}
}

/** 启动时清掉 tombstone 条目在 IndexedDB 中的残留（含旧库迁移复活）。 */
export async function purgeTombstonedLocalRecords(): Promise<void> {
	const [deletedSessions, deletedSpaces, deletedPaths] = await Promise.all([
		loadDeletedSessionIds(),
		loadDeletedSpaceIds(),
		loadDeletedSpacePaths(),
	]);
	await purgeSideChatSessions(deletedSessions);
	for (const sessionId of deletedSessions) {
		await deleteSession(sessionId).catch(() => undefined);
		await clearChatHistoryState(sessionId).catch(() => undefined);
		await clearRollbackState(sessionId).catch(() => undefined);
	}
	const database = await openXEYODb();
	const allSpaces = await database.getAll('spaces');
	for (const space of allSpaces) {
		if (space.id === DEFAULT_SPACE_ID) {
			continue;
		}
		const pathKey = space.rootPath?.trim()
			? normalizePath(space.rootPath)
			: '';
		if (
			deletedSpaces.has(space.id) ||
			(pathKey && deletedPaths.has(pathKey))
		) {
			await deleteSpace(space.id).catch(() => undefined);
		}
	}
}

export async function ensureDefaultSpace(): Promise<ChatSpace> {
	const database = await openXEYODb();
	const existing = await database.get('spaces', DEFAULT_SPACE_ID);
	if (existing) {
		const patched = normalizeSpace(existing);
		if (
			patched.rootPath !== (existing.rootPath ?? '') ||
			patched.name !== existing.name
		) {
			await database.put('spaces', patched);
		}
		return patched;
	}
	const now = Date.now();
	const space: ChatSpace = {
		id: DEFAULT_SPACE_ID,
		name: DEFAULT_SPACE_NAME,
		rootPath: '',
		createdAt: now,
		updatedAt: now,
	};
	await database.put('spaces', space);
	return space;
}

async function migrateSessionSpaceIds(): Promise<void> {
	const database = await openXEYODb();
	const all = await database.getAll('sessions');
	for (const s of all) {
		if (!s.spaceId) {
			await database.put('sessions', {...s, spaceId: DEFAULT_SPACE_ID});
		}
	}
}

export async function loadSpaces(): Promise<ChatSpace[]> {
	const database = await openXEYODb();
	await ensureDefaultSpace();
	const all = await database.getAllFromIndex('spaces', 'by-updated');
	const normalized: ChatSpace[] = [];
	for (const raw of all) {
		const space = normalizeSpace(raw);
		if (
			space.rootPath !== (raw.rootPath ?? '') ||
			space.name !== raw.name
		) {
			await database.put('spaces', space);
		}
		normalized.push(space);
	}
	return normalized.reverse();
}

export async function saveSpace(space: ChatSpace): Promise<void> {
	const database = await openXEYODb();
	await database.put('spaces', {
		...space,
		rootPath: space.rootPath ?? '',
	});
}

export async function deleteSpace(spaceId: string): Promise<void> {
	const database = await openXEYODb();
	const tx = database.transaction(
		['spaces', 'sessions', 'messages'],
		'readwrite',
	);
	const sessIdx = tx.objectStore('sessions').index('by-space');
	let cursor = await sessIdx.openCursor(spaceId);
	while (cursor) {
		const sid = cursor.value.id;
		const msgIdx = tx.objectStore('messages').index('by-session');
		let mc = await msgIdx.openCursor(sid);
		while (mc) {
			await mc.delete();
			mc = await mc.continue();
		}
		await cursor.delete();
		cursor = await cursor.continue();
	}
	await tx.objectStore('spaces').delete(spaceId);
	await tx.done;
}

/** 仅删除 space 行（sessions 已重新分配）。用于合并重复项。 */
export async function deleteSpaceRecord(spaceId: string): Promise<void> {
	const database = await openXEYODb();
	await database.delete('spaces', spaceId);
}

export async function loadSessions(): Promise<ChatSession[]> {
	const database = await openXEYODb();
	await ensureDefaultSpace();
	await migrateSessionSpaceIds();
	const all = await database.getAllFromIndex('sessions', 'by-updated');
	return all
		.map(s => (s.spaceId ? s : {...s, spaceId: DEFAULT_SPACE_ID}))
		.reverse();
}

export async function saveSession(session: ChatSession): Promise<void> {
	const database = await openXEYODb();
	await database.put('sessions', {
		...session,
		spaceId: session.spaceId || DEFAULT_SPACE_ID,
	});
}

export async function deleteSession(sessionId: string): Promise<void> {
	const database = await openXEYODb();
	const tx = database.transaction(['sessions', 'messages'], 'readwrite');
	await tx.objectStore('sessions').delete(sessionId);
	const idx = tx.objectStore('messages').index('by-session');
	let cursor = await idx.openCursor(sessionId);
	while (cursor) {
		await cursor.delete();
		cursor = await cursor.continue();
	}
	await tx.done;
}

export async function loadMessages(sessionId: string): Promise<ChatMessage[]> {
	const database = await openXEYODb();
	const rows = await database.getAllFromIndex(
		'messages',
		'by-session',
		sessionId,
	);
	return rows
		.map(({sessionId: _s, ...msg}) => msg)
		.sort((a, b) => a.createdAt - b.createdAt);
}

export async function upsertMessages(
	sessionId: string,
	messages: ChatMessage[],
): Promise<void> {
	const database = await openXEYODb();
	if (messages.length === 0) {
		return;
	}
	const tx = database.transaction('messages', 'readwrite');
	for (const m of messages) {
		await tx.store.put({...m, sessionId});
	}
	await tx.done;
}

/** 只写入/更新指定消息（增量 persist，避免全量 upsert）。 */
export async function patchMessages(
	sessionId: string,
	messages: ChatMessage[],
): Promise<void> {
	if (messages.length === 0) {
		return;
	}
	const database = await openXEYODb();
	const tx = database.transaction('messages', 'readwrite');
	for (const m of messages) {
		await tx.store.put({...m, sessionId});
	}
	await tx.done;
}

export async function replaceMessages(
	sessionId: string,
	messages: ChatMessage[],
): Promise<void> {
	const database = await openXEYODb();
	const tx = database.transaction('messages', 'readwrite');
	const store = tx.store;
	const idx = store.index('by-session');
	let cursor = await idx.openCursor(sessionId);
	while (cursor) {
		await cursor.delete();
		cursor = await cursor.continue();
	}
	for (const m of messages) {
		await store.put({...m, sessionId});
	}
	await tx.done;
}

export function newSpace(name: string, rootPath = ''): ChatSpace {
	const now = Date.now();
	const path = rootPath.trim();
	return {
		id: uid('space'),
		name: (name.trim() || (path ? folderName(path) : '') || '未命名工作区'),
		rootPath: path,
		createdAt: now,
		updatedAt: now,
	};
}


const ROLLBACK_STATE_PREFIX = 'rewind:state:';
const CHAT_HISTORY_STATE_PREFIX = 'chat:history:';
const SIDE_CHAT_MESSAGES_PREFIX = 'side-chat:messages:';

export async function loadRollbackState<T>(sessionId: string): Promise<T | null> {
	const raw = await getKv(`${ROLLBACK_STATE_PREFIX}${sessionId}`);
	if (!raw) {
		return null;
	}
	try {
		return parseJsonValue<T>(raw);
	} catch {
		return null;
	}
}

export async function saveRollbackState<T>(sessionId: string, value: T): Promise<void> {
	await setKv(`${ROLLBACK_STATE_PREFIX}${sessionId}`, JSON.stringify(value));
}

export async function clearRollbackState(sessionId: string): Promise<void> {
	await deleteKv(`${ROLLBACK_STATE_PREFIX}${sessionId}`);
}

export async function loadChatHistoryState(
	sessionId: string,
): Promise<ChatHistoryState | null> {
	const raw = await getKv(`${CHAT_HISTORY_STATE_PREFIX}${sessionId}`);
	if (!raw) {
		return null;
	}
	try {
		return parseJsonValue<ChatHistoryState>(raw);
	} catch {
		return null;
	}
}

export async function clearChatHistoryState(sessionId: string): Promise<void> {
	await deleteKv(`${CHAT_HISTORY_STATE_PREFIX}${sessionId}`);
}

/**
 * 侧边 Chat 的本地 transcript 缓存。
 * 后端不可用时仍保留最后一次可见消息，避免启动/刷新把 UI 覆盖为空。
 */
export async function loadSideChatMessages(sessionId: string): Promise<ChatMessage[]> {
	const raw = await getKv(`${SIDE_CHAT_MESSAGES_PREFIX}${sessionId}`);
	if (!raw) {
		return [];
	}
	try {
		const parsed = parseJsonValue<unknown>(raw);
		if (!Array.isArray(parsed)) {
			return [];
		}
		return parsed.filter(
			(row): row is ChatMessage =>
				Boolean(row) &&
				typeof row === 'object' &&
				((row as ChatMessage).role === 'user' ||
					(row as ChatMessage).role === 'assistant') &&
				typeof (row as ChatMessage).text === 'string' &&
				typeof (row as ChatMessage).id === 'string' &&
				typeof (row as ChatMessage).createdAt === 'number',
		);
	} catch {
		return [];
	}
}

export async function clearSideChatMessages(sessionId: string): Promise<void> {
	await deleteKv(`${SIDE_CHAT_MESSAGES_PREFIX}${sessionId}`);
}
