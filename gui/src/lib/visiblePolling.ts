/** One request at a time, with no timer while the document is hidden. */
export function startVisiblePolling(read: (signal: AbortSignal) => Promise<unknown>, period: number | (()=>number)): () => void {
	const controller = new AbortController();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let running = false;
	const visible = () => document.visibilityState !== 'hidden';
	const tick = async () => {
		if (controller.signal.aborted || running || !visible()) return;
		running = true;
		try { await read(controller.signal); }
		catch { /* Callers own error presentation; a failed read still releases the slot. */ }
		finally {
			running = false;
			if (!controller.signal.aborted && visible()) timer = setTimeout(tick, typeof period === 'function' ? period() : period);
		}
	};
	const visibility = () => {clearTimeout(timer); if (document.visibilityState !== 'hidden') void tick();};
	document.addEventListener('visibilitychange', visibility);
	void tick();
	return () => {controller.abort();clearTimeout(timer);document.removeEventListener('visibilitychange', visibility);};
}
