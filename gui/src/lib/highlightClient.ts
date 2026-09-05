import {isLayoutBusy, subscribeLayoutBusy} from '@/lib/layoutBusy';

type HighlightRequest = {
	id: number;
	code: string;
	lang: string;
};

type HighlightResponse = {
	id: number;
	ok: boolean;
	html?: string;
};

type Pending = {
	resolve: (html: string | null) => void;
};

type Queued = {
	lang: string;
	code: string;
	resolve: (html: string | null) => void;
};

let worker: Worker | null | undefined;
let nextId = 1;
const pending = new Map<number, Pending>();
let queue: Queued[] = [];

function getWorker(): Worker | null {
	if (worker !== undefined) {
		return worker;
	}
	if (typeof Worker === 'undefined') {
		worker = null;
		return null;
	}
	try {
		worker = new Worker(new URL('./highlightWorker.ts', import.meta.url), {
			type: 'module',
		});
		worker.onmessage = (ev: MessageEvent<HighlightResponse>) => {
			const job = pending.get(ev.data.id);
			if (!job) {
				return;
			}
			pending.delete(ev.data.id);
			job.resolve(ev.data.ok && ev.data.html != null ? ev.data.html : null);
		};
		worker.onerror = () => {
			for (const job of pending.values()) {
				job.resolve(null);
			}
			pending.clear();
		};
	} catch {
		worker = null;
	}
	return worker;
}

function postHighlight(lang: string, code: string): Promise<string | null> {
	const w = getWorker();
	if (!w) {
		return Promise.resolve(null);
	}
	const id = nextId;
	nextId += 1;
	return new Promise(resolve => {
		const t = window.setTimeout(() => {
			if (pending.delete(id)) {
				resolve(null);
			}
		}, 2500);
		pending.set(id, {
			resolve: html => {
				window.clearTimeout(t);
				resolve(html);
			},
		});
		const req: HighlightRequest = {id, code, lang};
		w.postMessage(req);
	});
}

function flushQueue() {
	if (isLayoutBusy() || queue.length === 0) {
		return;
	}
	const jobs = queue;
	queue = [];
	for (const job of jobs) {
		void postHighlight(job.lang, job.code).then(job.resolve);
	}
}

subscribeLayoutBusy(busy => {
	if (!busy) {
		flushQueue();
	}
});

/** 在 worker 中运行 Prism。失败 → null，调用方可继续使用上一次的有效 HTML。 */
export function highlightCode(lang: string, code: string): Promise<string | null> {
	if (isLayoutBusy()) {
		return new Promise(resolve => {
			queue.push({lang, code, resolve});
		});
	}
	return postHighlight(lang, code);
}
