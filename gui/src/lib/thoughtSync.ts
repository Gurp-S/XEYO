/** Send only unacknowledged finalized thoughts, serially per backend session. */
export type SyncThought = {id: string; text: string; thoughtMs?: number; createdAt: number};
type Sender = (sessionId: string, thoughts: SyncThought[]) => Promise<number | null>;
type State = {ack: Map<string, SyncThought>; pending: Map<string, SyncThought>; generation: number; running?: Promise<void>};

const same = (a: SyncThought | undefined, b: SyncThought) => a?.text === b.text &&
	a.thoughtMs === b.thoughtMs && a.createdAt === b.createdAt;

export function createThoughtSync(send: Sender) {
	const sessions = new Map<string, State>();
	return (sessionId: string, thoughts: SyncThought[]): Promise<void> => {
		if (!sessionId || !thoughts.length) return Promise.resolve();
		let state = sessions.get(sessionId);
		if (!state) {
			// Eviction only causes an idempotent resend, never a false acknowledgement.
			for (const [id, old] of sessions) {
				if (sessions.size < 64) break;
				if (!old.running) sessions.delete(id);
			}
			state = {ack: new Map(), pending: new Map(), generation: 0};
			sessions.set(sessionId, state);
		}
		const current = state;
		current.generation++;
		for (const thought of thoughts) {
			if (!same(current.ack.get(thought.id), thought)) current.pending.set(thought.id, {...thought});
		}
		if (current.running) return current.running;
		const drain = async () => {
			while (current.pending.size) {
				const batch: SyncThought[] = [];
				// Match UiThoughtsSyncRequest's limit without dropping older history.
				for (const [id, thought] of current.pending) {
					current.pending.delete(id);
					if (!same(current.ack.get(id), thought)) batch.push(thought);
					if (batch.length === 500) break;
				}
				if (!batch.length) break;
				const generation = current.generation;
				let written: number | null;
				try { written = await send(sessionId, batch); } catch { written = null; }
				if (written == null) {
					for (const thought of batch) {
						if (!current.pending.has(thought.id)) current.pending.set(thought.id, thought);
					}
					// A flush arriving during this request is also a retry trigger.
					if (current.generation !== generation) continue;
					return; // No new trigger: retain the batch without a busy retry loop.
				}
				for (const thought of batch) current.ack.set(thought.id, thought);
			}
		};
		current.running = drain().finally(() => { current.running = undefined; });
		return current.running;
	};
}
