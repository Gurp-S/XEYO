import {readFile} from 'node:fs/promises';

const path = process.argv[2] ?? 'bench-results/chatpage-baseline.json';
const data = JSON.parse(await readFile(path, 'utf8'));
const groups = new Map();
for (const entry of data.traceEntries ?? []) {
	const rows = groups.get(entry.name) ?? [];
	rows.push(Number(entry.duration) || 0);
	groups.set(entry.name, rows);
}
const percentile = (values, p) => values.length
	? values[Math.min(values.length - 1, Math.floor(values.length * p))]
	: 0;
const summary = [...groups].map(([name, values]) => {
	values.sort((a, b) => a - b);
	return {
		name,
		samples: values.length,
		totalMs: values.reduce((sum, value) => sum + value, 0),
		p50Ms: percentile(values, 0.5),
		p95Ms: percentile(values, 0.95),
		maxMs: values.at(-1) ?? 0,
	};
}).sort((a, b) => b.totalMs - a.totalMs);
console.log(JSON.stringify({
	file: path,
	metrics: {
		frame: {
			p50Ms: data.p50FrameMs,
			p95Ms: data.p95FrameMs,
			p99Ms: data.p99FrameMs,
			maxMs: data.maxFrameMs,
			averageFps: data.averageFps,
			onePercentLowFps: data.onePercentLowFps,
		},
		input: {
			p50Ms: data.inputP50Ms,
			p95Ms: data.inputP95Ms,
			maxMs: data.inputMaxMs,
		},
	},
	topTraces: summary.slice(0, 25),
}, null, 2));
