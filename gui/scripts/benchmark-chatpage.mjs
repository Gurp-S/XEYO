import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const PORT = Number(process.env.BENCH_PORT ?? 5173);
const CDP_PORT = Number(process.env.BENCH_CDP_PORT ?? 9224);
const DURATION_MS = Number(process.env.BENCH_DURATION_MS ?? 12000);
const URL = `http://127.0.0.1:${PORT}/bench/chat`;
const OUT = process.env.BENCH_OUT ?? 'bench-results/chatpage-baseline.json';

function findBrowser() {
	const candidates = [
		process.env.CHROME_PATH,
		process.env.CHROME,
		'C:/Program Files/Google/Chrome/Application/chrome.exe',
		'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
		'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
		'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
		'/usr/bin/google-chrome',
		'/usr/bin/chromium',
	];
	const path = candidates.filter(Boolean).find(candidate => existsSync(candidate));
	if (!path) throw new Error('找不到 Chromium/Chrome，请设置 CHROME_PATH');
	return path;
}

async function waitFor(url, timeout = 30000) {
	const started = Date.now();
	while (Date.now() - started < timeout) {
		try {
			const response = await fetch(url);
			if (response.ok) return;
		} catch {}
		await new Promise(resolve => setTimeout(resolve, 100));
	}
	throw new Error(`等待 ${url} 超时`);
}

function cdp(wsUrl) {
	const socket = new WebSocket(wsUrl);
	let id = 0;
	const pending = new Map();
	const ready = new Promise((resolve, reject) => {
		socket.addEventListener('open', resolve, {once: true});
		socket.addEventListener('error', reject, {once: true});
	});
	socket.addEventListener('message', event => {
		const message = JSON.parse(event.data);
		if (message.id && pending.has(message.id)) {
			const item = pending.get(message.id);
			pending.delete(message.id);
			if (message.error) item.reject(new Error(JSON.stringify(message.error)));
			else item.resolve(message.result);
		}
	});
	return {
		async send(method, params = {}) {
			await ready;
			const requestId = ++id;
			return new Promise((resolve, reject) => {
				pending.set(requestId, {resolve, reject});
				socket.send(JSON.stringify({id: requestId, method, params}));
			});
		},
		close() { socket.close(); },
	};
}

const measure = String.raw`(async ({duration}) => {
	const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
	const startedWaiting = performance.now();
	while (!window.__XY_REPLAY__ && performance.now() - startedWaiting < 10000) await wait(50);
	const replay = window.__XY_REPLAY__;
	if (!replay) throw new Error('离线 replay API 未就绪');
	const scrollerCandidates = [...document.querySelectorAll('.xy-chat-surface.xy-hover-scroll')];
	const scroller = scrollerCandidates[0];
	if (!scroller) throw new Error('真实 MessageList 滚动容器未找到');
	await wait(500);
	replay.reset();
	await wait(200);
	performance.clearMarks();
	performance.clearMeasures();

	const frames = [];
	const inputDelays = [];
	let running = true;
	let lastFrame = performance.now();
	let latestInput = null;
	let rafId = 0;
	const onInput = () => { latestInput = performance.now(); };
	document.addEventListener('pointermove', onInput, {passive: true});
	document.addEventListener('pointerdown', onInput, {passive: true});
	function frame(now) {
		if (!running) return;
		const delta = now - lastFrame;
		if (delta > 0) frames.push(delta);
		lastFrame = now;
		if (latestInput != null) {
			inputDelays.push(Math.max(0, now - latestInput));
			latestInput = null;
		}
		rafId = requestAnimationFrame(frame);
	}
	rafId = requestAnimationFrame(frame);

	const stream = replay.streamText;
	const runStarted = performance.now();
	let offset = 0;
	let updates = 0;
	while (performance.now() - runStarted < duration) {
		const elapsed = performance.now() - runStarted;
		const target = Math.min(stream.length, Math.floor((elapsed / duration) * stream.length));
		offset = Math.max(offset + 1, target);
		const chunk = stream.slice(0, offset);
		performance.mark('xy:replay:update:start');
		replay.setStream(chunk, '本地离线回放');
		performance.mark('xy:replay:update:end');
		performance.measure('xy:replay:update', 'xy:replay:update:start', 'xy:replay:update:end');
		performance.clearMarks('xy:replay:update:start');
		performance.clearMarks('xy:replay:update:end');
		performance.mark('xy:replay:scroll:start');
		const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
		scroller.scrollTop = maxTop > 0 ? (scroller.scrollTop + 7) % maxTop : 0;
		scroller.dispatchEvent(new Event('scroll', {bubbles: true}));
		performance.mark('xy:replay:scroll:end');
		performance.measure('xy:replay:scroll', 'xy:replay:scroll:start', 'xy:replay:scroll:end');
		performance.clearMarks('xy:replay:scroll:start');
		performance.clearMarks('xy:replay:scroll:end');
		document.dispatchEvent(new PointerEvent('pointermove', {
			bubbles: true,
			clientX: 220 + (updates % 800),
			clientY: 180 + (updates % 420),
		}));
		updates += 1;
		await wait(8);
	}
	await wait(500);
	running = false;
	cancelAnimationFrame(rafId);
	document.removeEventListener('pointermove', onInput);
	document.removeEventListener('pointerdown', onInput);
	const sortedFrames = frames.slice().sort((a, b) => a - b);
	const sortedInputs = inputDelays.slice().sort((a, b) => a - b);
	const percentile = (values, p) => values.length
		? values[Math.min(values.length - 1, Math.floor(values.length * p))]
		: null;
	const lowOneCount = Math.max(1, Math.ceil(sortedFrames.length * 0.01));
	const slowest = sortedFrames.slice(-lowOneCount);
	const traceEntries = performance.getEntriesByType('measure').map(entry => ({
		name: entry.name,
		duration: entry.duration,
	}));
	const summary = {
		durationMs: duration,
		fixture: 'chatpage-real-local-replay',
		dom: {
			scrollerCandidates: scrollerCandidates.map(node => ({
				className: node.className,
				scrollHeight: node.scrollHeight,
				clientHeight: node.clientHeight,
			})),
			roundCount: document.querySelectorAll('[data-round-id]').length,
			promptCount: document.querySelectorAll('[data-xy-prompt-chip]').length,
		},
		scroller: {
			scrollHeight: scroller.scrollHeight,
			clientHeight: scroller.clientHeight,
		},
		updates,
		frameCount: sortedFrames.length,
		p50FrameMs: percentile(sortedFrames, 0.50),
		p95FrameMs: percentile(sortedFrames, 0.95),
		p99FrameMs: percentile(sortedFrames, 0.99),
		maxFrameMs: sortedFrames.at(-1) ?? null,
		averageFps: sortedFrames.length
			? 1000 / (sortedFrames.reduce((a, b) => a + b, 0) / sortedFrames.length)
			: null,
		onePercentLowFps: slowest.length ? 1000 / Math.max(...slowest) : null,
		inputSamples: sortedInputs.length,
		inputP50Ms: percentile(sortedInputs, 0.50),
		inputP95Ms: percentile(sortedInputs, 0.95),
		inputMaxMs: sortedInputs.at(-1) ?? null,
		traceEntries,
	};
	replay.reset();
	return summary;
})`;

const browser = findBrowser();
const profile = await mkdtemp(join(tmpdir(), 'xy-chatpage-bench-'));
const server = process.env.BENCH_USE_EXISTING_SERVER
	? null
	: spawn(process.platform === 'win32' ? 'cmd.exe' : 'npm', process.platform === 'win32'
		? ['/d', '/s', '/c', `cd /d "${process.cwd()}" && npm run dev -- --host 127.0.0.1 --port ${PORT}`]
		: ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(PORT)], {stdio: 'ignore'});
let chrome;
try {
	await waitFor(`http://127.0.0.1:${PORT}/`);
	chrome = spawn(browser, [
		'--headless=new', '--no-first-run', '--no-default-browser-check',
		'--disable-background-networking', '--disable-renderer-backgrounding',
		'--disable-background-timer-throttling', `--remote-debugging-port=${CDP_PORT}`,
		`--user-data-dir=${profile}`, '--window-size=1600,1000', 'about:blank',
	], {stdio: 'ignore'});
	await waitFor(`http://127.0.0.1:${CDP_PORT}/json/version`);
	const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
	const page = targets.find(target => target.type === 'page');
	if (!page?.webSocketDebuggerUrl) throw new Error('找不到 Chromium 页面 CDP target');
	const client = cdp(page.webSocketDebuggerUrl);
	await client.send('Page.enable');
	await client.send('Runtime.enable');
	await client.send('Page.addScriptToEvaluateOnNewDocument', {
		source: 'window.__XY_PERF_TRACE__ = true;',
	});
	await client.send('Page.navigate', {url: URL});
	const result = await client.send('Runtime.evaluate', {
		expression: `${measure}(${JSON.stringify({duration: DURATION_MS})})`,
		awaitPromise: true,
		returnByValue: true,
	});
	if (result.exceptionDetails) {
		throw new Error(result.exceptionDetails.exception?.description ?? '页面回放执行失败');
	}
	const value = result.result.value;
	await writeFile(OUT, `${JSON.stringify({
		browser,
		url: URL,
		capturedAt: new Date().toISOString(),
		...value,
	}, null, 2)}\n`, 'utf8');
	console.log(JSON.stringify({browser, url: URL, output: OUT, ...value}, null, 2));
	client.close();
} finally {
	server?.kill();
	chrome?.kill();
	await new Promise(resolve => setTimeout(resolve, 500));
	try { await rm(profile, {recursive: true, force: true}); } catch {}
}
