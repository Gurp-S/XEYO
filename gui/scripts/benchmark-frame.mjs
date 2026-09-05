import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const PORT = Number(process.env.BENCH_PORT ?? 4179);
const CDP_PORT = Number(process.env.BENCH_CDP_PORT ?? 9223);
const DURATION_MS = Number(process.env.BENCH_DURATION_MS ?? 8000);
const URL = `http://127.0.0.1:${PORT}/`;

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
	if (!path) {
		throw new Error('找不到 Chromium/Chrome，请设置 CHROME_PATH');
	}
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
			const {resolve, reject} = pending.get(message.id);
			pending.delete(message.id);
			if (message.error) reject(new Error(JSON.stringify(message.error)));
			else resolve(message.result);
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

const fixture = String.raw`(() => {
	const root = document.createElement('div');
	root.id = '__xy_benchmark_root';
	root.innerHTML = '<style>#' + root.id + '{position:fixed;inset:0;z-index:2147483647;background:#151515;color:#eee;font:14px system-ui;overflow:auto;contain:strict}#' + root.id + ' .bench-list{width:min(900px,90vw);margin:20px auto;contain:content}#' + root.id + ' .row{min-height:72px;margin:8px 0;padding:14px 18px;border-radius:14px;background:rgb(35 35 40 / .92);box-shadow:0 8px 24px rgb(0 0 0 / .18);transform:translateZ(0)}#' + root.id + ' .stream{color:#9fd4ff;white-space:pre-wrap}</style><div class="bench-list"></div>';
	document.body.append(root);
	const list = root.querySelector('.bench-list');
	for (let i = 0; i < 500; i++) {
		const row = document.createElement('div');
		row.className = 'row';
		row.textContent = '本地离线压力数据 ' + i + '：Markdown 流式渲染、滚动、阴影和合成层压力测试。';
		list.append(row);
	}
	const stream = document.createElement('div');
	stream.className = 'row stream';
	stream.textContent = '';
	list.append(stream);
	return {root, list, stream};
})()`;

const measure = String.raw`(async ({duration}) => {
	const {root, list, stream} = ${fixture};
	const frames = [];
	const inputDelays = [];
	let lastFrame = performance.now();
	let latestInput = null;
	let running = true;
	const onInput = () => { latestInput = performance.now(); };
	root.addEventListener('pointermove', onInput, {passive: true});
	function frame(now) {
		if (!running) return;
		const delta = now - lastFrame;
		if (delta > 0) frames.push(delta);
		lastFrame = now;
		if (latestInput != null) {
			inputDelays.push(now - latestInput);
			latestInput = null;
		}
		requestAnimationFrame(frame);
	}
	requestAnimationFrame(frame);
	const started = performance.now();
	let token = 0;
	while (performance.now() - started < duration) {
		performance.mark('xy:fixture.update:start');
		const text = '离线流式输出：' + '内容 '.repeat(30 + (token % 20));
		stream.textContent = text;
		list.style.transform = 'translate3d(0, ' + (Math.sin(token / 10) * 2) + 'px, 0)';
		performance.mark('xy:fixture.update:end');
		performance.measure('xy:fixture.update', 'xy:fixture.update:start', 'xy:fixture.update:end');
		performance.clearMarks('xy:fixture.update:start');
		performance.clearMarks('xy:fixture.update:end');
		performance.mark('xy:fixture.scroll:start');
		root.scrollTop = (root.scrollTop + 3) % Math.max(1, root.scrollHeight - root.clientHeight);
		performance.mark('xy:fixture.scroll:end');
		performance.measure('xy:fixture.scroll', 'xy:fixture.scroll:start', 'xy:fixture.scroll:end');
		performance.clearMarks('xy:fixture.scroll:start');
		performance.clearMarks('xy:fixture.scroll:end');
		root.dispatchEvent(new PointerEvent('pointermove', {bubbles: true, clientX: token % 500, clientY: 200}));
		token++;
		await new Promise(resolve => setTimeout(resolve, 8));
	}
	running = false;
	await new Promise(resolve => setTimeout(resolve, 100));
	root.remove();
	frames.sort((a, b) => a - b);
	inputDelays.sort((a, b) => a - b);
	const percentile = (values, p) => values.length ? values[Math.min(values.length - 1, Math.floor(values.length * p))] : null;
	const lowOneCount = Math.max(1, Math.ceil(frames.length * .01));
	const slowest = frames.slice(-lowOneCount);
	const lowOneFps = slowest.length ? 1000 / Math.max(...slowest) : null;
	return {
		durationMs: duration,
		frameCount: frames.length,
		p50FrameMs: percentile(frames, .50),
		p95FrameMs: percentile(frames, .95),
		p99FrameMs: percentile(frames, .99),
		maxFrameMs: frames.at(-1) ?? null,
		averageFps: frames.length ? 1000 / (frames.reduce((a, b) => a + b, 0) / frames.length) : null,
		onePercentLowFps: lowOneFps,
		inputSamples: inputDelays.length,
		inputP50Ms: percentile(inputDelays, .50),
		inputP95Ms: percentile(inputDelays, .95),
		inputMaxMs: inputDelays.at(-1) ?? null,
	};
})`;

const browser = findBrowser();
const profile = await mkdtemp(join(tmpdir(), 'xy-gui-bench-'));
const server = process.env.BENCH_USE_EXISTING_SERVER
	? null
	: spawn(process.platform === 'win32' ? 'cmd.exe' : 'npm', process.platform === 'win32'
		? ['/d', '/s', '/c', `cd /d "${process.cwd()}" && npm run dev -- --host 127.0.0.1 --port ${PORT}`]
		: ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(PORT)], {stdio: 'ignore'});
let chrome;
try {
	await waitFor(URL);
	chrome = spawn(browser, [
		'--headless=new', '--no-first-run', '--no-default-browser-check',
		'--disable-background-networking', '--disable-renderer-backgrounding',
		'--disable-background-timer-throttling', `--remote-debugging-port=${CDP_PORT}`,
		`--user-data-dir=${profile}`, '--window-size=1600,1000', 'about:blank',
	], {stdio: 'ignore'});
	await waitFor(`http://127.0.0.1:${CDP_PORT}/json/version`);
	const targets = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json();
	const page = targets.find(target => target.type === 'page');
	if (!page?.webSocketDebuggerUrl) {
		throw new Error('找不到 Chromium 页面 CDP target');
	}
	const client = cdp(page.webSocketDebuggerUrl);
	await client.send('Page.enable');
	await client.send('Runtime.enable');
	await client.send('Page.addScriptToEvaluateOnNewDocument', {
		source: 'window.__XY_PERF_TRACE__ = true;',
	});
	await client.send('Page.navigate', {url: URL});
	await new Promise(resolve => setTimeout(resolve, 1500));
	await client.send('Runtime.evaluate', {expression: 'performance.clearMarks(); performance.clearMeasures();'});
	const result = await client.send('Runtime.evaluate', {expression: `${measure}(${JSON.stringify({duration: DURATION_MS})})`, awaitPromise: true, returnByValue: true});
	const traces = await client.send('Runtime.evaluate', {
		expression: `performance.getEntriesByType('measure').map(entry => ({name: entry.name, duration: entry.duration}))`,
		returnByValue: true,
	});
	const grouped = new Map();
	for (const trace of traces.result.value ?? []) {
		const rows = grouped.get(trace.name) ?? [];
		rows.push(trace.duration);
		grouped.set(trace.name, rows);
	}
	const traceSummary = [...grouped].map(([name, values]) => {
		values.sort((a, b) => a - b);
		const at = p => values[Math.min(values.length - 1, Math.floor(values.length * p))];
		return {name, samples: values.length, totalMs: values.reduce((a, b) => a + b, 0), p95Ms: at(.95), maxMs: values.at(-1)};
	}).sort((a, b) => b.totalMs - a.totalMs);
	console.log(JSON.stringify({browser, url: URL, syntheticFixture: true, traceSummary, ...result.result.value}, null, 2));
	client.close();
} finally {
	server?.kill();
	chrome?.kill();
	await new Promise(resolve => setTimeout(resolve, 500));
	try {
		await rm(profile, {recursive: true, force: true});
	} catch {
		// Windows may release the Chromium lockfile slightly after kill().
		console.error(`临时 Chromium profile 未能立即删除：${profile}`);
	}
}
