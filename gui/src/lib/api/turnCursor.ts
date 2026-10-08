const KEY = 'xeyo:turnCursor:';
type Cursor = {eventId: number; turnId: string};

function load(sessionId: string): Cursor | null {
	try {
		const raw = sessionStorage.getItem(KEY + sessionId);
		if (!raw) return null;
		const parsed = JSON.parse(raw) as unknown;
		if (typeof parsed === 'number') return {eventId: parsed, turnId: ''};
		if (parsed && typeof parsed === 'object') return parsed as Cursor;
	} catch { /* unavailable storage */ }
	return null;
}

export function rememberTurnCursor(sessionId: string, eventId: number, turnId?: string): void {
	if (!sessionId || !Number.isFinite(eventId) || eventId < 0) return;
	const previous = load(sessionId);
	try {
		sessionStorage.setItem(KEY + sessionId, JSON.stringify({eventId,
			turnId: turnId ?? (eventId === 0 ? '' : previous?.turnId ?? '')}));
	} catch { /* unavailable storage */ }
}

export function readTurnCursor(sessionId: string, turnId?: string): number {
	const saved = load(sessionId);
	if (!saved || (turnId && saved.turnId !== turnId)) return 0;
	return Number.isFinite(saved.eventId) && saved.eventId >= 0 ? saved.eventId : 0;
}
