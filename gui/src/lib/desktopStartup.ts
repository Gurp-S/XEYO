/** The shell paints while services start; chat hydration waits for that one owner. */
export async function waitForDesktopBackend(read: () => Promise<boolean>, signal: AbortSignal) {
	while (!signal.aborted) {
		if (await read()) return;
		await new Promise<void>(resolve => {
			const done = () => {clearTimeout(timer); signal.removeEventListener('abort', done); resolve();};
			const timer = setTimeout(done, 200);
			signal.addEventListener('abort', done, {once: true});
			if (signal.aborted) done();
		});
	}
	throw new DOMException('Startup cancelled', 'AbortError');
}
