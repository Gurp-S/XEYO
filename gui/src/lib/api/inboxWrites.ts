import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from './core';
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));

export async function cancelInboxItem(sessionId: string, queueId: string): Promise<boolean> {
	try {
		const response = await fetchWithTimeout(apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/${encodeURIComponent(queueId)}`), {method: 'DELETE', headers: authHeaders()});
		if (!response.ok) return false;
		const receipt: unknown = await response.json();
		return record(receipt) && receipt.ok === true && receipt.session_id === sessionId && receipt.queue_id === queueId;
	} catch {return false;}
}

export async function editInboxItem(sessionId: string, queueId: string, text: string): Promise<boolean> {
	try {
		const response = await fetchWithTimeout(apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/${encodeURIComponent(queueId)}`), {
			method: 'PATCH', headers: {...authHeaders(), 'Content-Type': 'application/json'}, body: JSON.stringify({text}),
		});
		if (!response.ok) return false;
		const receipt: unknown = await response.json();
		return record(receipt) && receipt.ok === true && record(receipt.item) && receipt.item.queue_id === queueId && receipt.item.text === text.trim();
	} catch {return false;}
}
