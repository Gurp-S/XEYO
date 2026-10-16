import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from './core';

export async function reorderInbox(sessionId: string, expected: string[], order: string[]): Promise<boolean> {
	try {
		const response = await fetchWithTimeout(apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/inbox/reorder`), {
			method: 'POST', headers: {...authHeaders(), 'Content-Type': 'application/json'},
			body: JSON.stringify({expected_order: expected, order}),
		});
		const receipt = await response.json();
		return response.ok && receipt?.ok === true && receipt.session_id === sessionId &&
			Array.isArray(receipt.order) && receipt.order.length === order.length && receipt.order.every((id: unknown, i: number) => id === order[i]);
	} catch {return false;}
}
