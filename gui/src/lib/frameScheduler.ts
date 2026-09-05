type FrameTask = () => void;

type TaskQueues = {
	read: Map<string, FrameTask>;
	write: Map<string, FrameTask>;
	raf: number;
};

let nextFrameKey = 0;

const queues: TaskQueues = {
	read: new Map(),
	write: new Map(),
	raf: 0,
};

function ensureFrame() {
	if (queues.raf !== 0) {
		return;
	}
	queues.raf = requestAnimationFrame(() => {
		queues.raf = 0;
		const reads = [...queues.read.values()];
		const writes = [...queues.write.values()];
		queues.read.clear();
		queues.write.clear();

		for (const task of reads) {
			task();
		}
		for (const task of writes) {
			task();
		}

		if (queues.read.size > 0 || queues.write.size > 0) {
			ensureFrame();
		}
	});
}

export function createFrameKey(prefix: string): string {
	return `${prefix}-${++nextFrameKey}`;
}

export function scheduleFrameRead(key: string, task: FrameTask) {
	queues.read.set(key, task);
	ensureFrame();
}

export function scheduleFrameWrite(key: string, task: FrameTask) {
	queues.write.set(key, task);
	ensureFrame();
}

export function cancelFrameTask(key: string) {
	queues.read.delete(key);
	queues.write.delete(key);
}
