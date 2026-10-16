const identities = new Map<string, string>();

export function rememberTurnIdentity(sessionId: string, frame: Record<string, unknown>): void {
  const xy = (frame.xy ?? frame.xeyo) as Record<string, unknown> | undefined;
  const id = frame.xeyo_turn_id ?? xy?.turn_id;
  if (typeof id === 'string' && id) identities.set(sessionId, id);
}

export function readTurnIdentity(sessionId: string): string {
  return identities.get(sessionId) ?? '';
}
