type Listener = (busy: boolean) => void;

let depth = 0;
const listeners = new Set<Listener>();

export function isLayoutBusy(): boolean {
	return depth > 0;
}

export function pushLayoutBusy(): void {
	depth += 1;
	if (depth === 1) {
		for (const fn of listeners) {
			fn(true);
		}
	}
}

export function popLayoutBusy(): void {
	if (depth === 0) {
		return;
	}
	depth -= 1;
	if (depth === 0) {
		for (const fn of listeners) {
			fn(false);
		}
	}
}

export function subscribeLayoutBusy(fn: Listener): () => void {
	listeners.add(fn);
	return () => {
		listeners.delete(fn);
	};
}
