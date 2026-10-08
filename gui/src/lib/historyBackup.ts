import type {IDBPDatabase} from 'idb';
import type {XeyoDB} from './db';
import type {ChatMessage} from './types';
import {compareTranscriptOrder, stampTranscriptOrder} from './transcriptOrder';
import {idbBatch} from './idbBatch';

export const historyBackupPrefix = (sessionId: string) => `input-history-backup:${encodeURIComponent(sessionId)}:`;
export const historyBackupKey = (sessionId: string, backendId: string) => `${historyBackupPrefix(sessionId)}${encodeURIComponent(backendId)}`;

/** Backup and replacement commit together; failure leaves the original rows intact. */
export async function replaceTranscriptWithBackup(
	database: IDBPDatabase<XeyoDB>, sessionId: string, backendId: string,
	local: ChatMessage[], messages: ChatMessage[], isCurrent: () => boolean,
	persistable: (message: ChatMessage) => ChatMessage,
): Promise<boolean> {
	if (!isCurrent()) return false;
	const tx = database.transaction(['messages', 'kv'], 'readwrite');
	const cancel = async () => {tx.abort(); await tx.done.catch(() => {}); return false;};
	try {
		const store = tx.objectStore('messages'); const kv = tx.objectStore('kv');
		const index = store.index('by-session');
		const original = await index.getAll(sessionId);
		if (!isCurrent()) return cancel();
		const key = historyBackupKey(sessionId, backendId);
		const existing = await kv.get(key);
		if (!isCurrent()) return cancel();
		if (existing === undefined) {
			await kv.put(JSON.stringify({version: 1, sessionId, backendId, createdAt: Date.now(),
				messages: local, persistedMessages: original.sort(compareTranscriptOrder)}), key);
		}
		if (!isCurrent()) return cancel();
		await idbBatch(original, row => store.delete(row.id));
		if (!isCurrent()) return cancel();
		await idbBatch(stampTranscriptOrder(messages), row => store.put({...persistable(row), sessionId}));
		if (!isCurrent()) return cancel();
		await tx.done;
		return true;
	} catch (error) {
		try {tx.abort();} catch { /* transaction already settled */ }
		await tx.done.catch(() => {});
		throw error;
	}
}
