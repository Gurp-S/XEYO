import {apiUrl} from '@/lib/apiBase';
import {authHeaders, fetchWithTimeout} from './core';

export async function abandonSessionRecovery(sessionId: string, turnId: string): Promise<boolean> {
	if (!turnId.trim()) return false;
	try {
		const response = await fetchWithTimeout(apiUrl(`/v1/sessions/${encodeURIComponent(sessionId)}/recovery/abandon`), {
			method: 'POST', headers: {...authHeaders(), 'Content-Type': 'application/json'},
			body: JSON.stringify({turn_id: turnId}),
		});
		if (!response.ok) return false;
		const receipt: unknown = await response.json();
		return Boolean(receipt && typeof receipt === 'object' && !Array.isArray(receipt) &&
			'ok' in receipt && receipt.ok === true && 'status' in receipt && receipt.status === 'stopped' &&
			'turn_id' in receipt && receipt.turn_id === turnId);
	} catch {return false;}
}
