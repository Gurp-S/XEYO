/**
 * ui-audit-full.spec.ts — GUI 全量视觉审计（几何之外的补充维度，解法二）。
 *
 * 覆盖维度（与既有 ui-audit.spec.ts 几何矩阵互补）：
 *   1. 真实主页 `/`（空态 + 侧栏开关）× 多窗口几何扫描 —— 既有审计只扫 bench 合成页；
 *   2. 交互遍历：侧栏折叠/展开、命令面板 Ctrl+K、设置模态、主题选择、
 *      工作区开关、输入框展开、操作菜单 —— 每步后立即几何扫描，抓「只在某交互态出现」的错位；
 *   3. 样式异常：TINY_FONT / LOW_CONTRAST / INVISIBLE_TEXT（见 helpers/uiScanStyles.ts）；
 *   4. 控制台/页面错误 + 失败请求收集（后端未起的 fetch 失败单独归类，不算 GUI bug）；
 *   5. 动画卡顿：bench 流式回放 + 消息列表滚动期间采样 rAF 帧间隔与 longtask。
 *
 * 产物：`ui-audit-report/full/`（full-summary.md + full-<section>.json + full-shot-*.png）。
 * 用法：`npm run test:e2e:ui-audit-full`（见 playwright.ui-audit-full.config.ts）。
 */
import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {scanLayout, type ScanResultSummary, type ScanOptions} from './helpers/uiScan';
import {scanStyles, type StyleScanResult} from './helpers/uiScanStyles';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = path.resolve(__dirname, '..', 'ui-audit-report', 'full');

const VIEWPORTS = [
	{name: 'wide', width: 1440, height: 900},
	{name: 'std', width: 1280, height: 800},
	{name: 'narrow', width: 960, height: 700},
	{name: 'stress', width: 700, height: 560},
];

const GEO_OPTS: ScanOptions = {
	predicates: {H_OVERFLOW: true, V_CLIP: false, TEXT_CLIP: true, ZERO_SIZE: true, OVERLAP: false},
};
const STYLE_OPTS = {tinyFontPx: 9, contrastMin: 3.0, invisibleAlpha: 0.15};

type ConsoleItem = {type: string; text: string};
type NetFail = {url: string; method: string; failure: string};

function isExpectedBackendFail(item: ConsoleItem | NetFail): boolean {
	const s = 'url' in item ? item.url : item.text;
	return /\/v1\//.test(s) || /127\.0\.0\.1:(8000|517[0-9])/.test(s) ||
		/502 \(Bad Gateway\)/.test('text' in item ? item.text : '') ||
		/net::ERR_CONNECTION_REFUSED|net::ERR_ABORTED|Failed to fetch/i.test('text' in item ? item.text : '');
}

async function collectRuntime(
	page: Page,
): Promise<{consoleItems: ConsoleItem[]; pageErrors: string[]; netFails: NetFail[]}> {
	const consoleItems: ConsoleItem[] = [];
	const pageErrors: string[] = [];
	const netFails: NetFail[] = [];
	page.on('console', msg => {
		if (['error', 'warning'].includes(msg.type())) {
			consoleItems.push({type: msg.type(), text: msg.text()});
		}
	});
	page.on('pageerror', err => pageErrors.push(String(err)));
	page.on('requestfailed', req => {
		netFails.push({url: req.url(), method: req.method(), failure: req.failure()?.errorText ?? 'unknown'});
	});
	return {consoleItems, pageErrors, netFails};
}

/** 每次快照：几何 + 样式一次性抓齐。 */
async function snapshot(page: Page) {
	const geo = (await page.evaluate(scanLayout, GEO_OPTS)) as ScanResultSummary;
	const style = (await page.evaluate(scanStyles, STYLE_OPTS)) as StyleScanResult;
	return {geo, style};
}

function selectorOf(v: {selector: string}) {
	return v.selector;
}

async function clipShot(page: Page, selector: string, file: string): Promise<string | null> {
	try {
		const loc = page.locator(selector).first();
		if ((await loc.count()) < 1) return null;
		await loc.screenshot({path: path.join(REPORT_DIR, file), timeout: 3000});
		return file;
	} catch {
		return null;
	}
}

type Findings = {
	label: string;
	geo: ScanResultSummary;
	style: StyleScanResult;
	shot?: string;
	clips: string[];
};

async function auditState(
	page: Page,
	label: string,
	findings: Findings[],
): Promise<void> {
	await page.waitForTimeout(350); // 等动画/过渡落定
	const snap = await snapshot(page);
	const shot = `full-shot-${label.replace(/[^a-zA-Z0-9-]/g, '_')}.png`;
	await page.screenshot({path: path.join(REPORT_DIR, shot)});
	const clips: string[] = [];
	let n = 0;
	for (const v of snap.geo.violations) {
		if (n >= 6) break;
		const f = await clipShot(page, selectorOf(v), `full-clip-${label}-${n}.png`);
		if (f) clips.push(f);
		n += 1;
	}
	findings.push({label, geo: snap.geo, style: snap.style, shot, clips});
}

test.describe('全量 UI 审计', () => {
	let consoleItems: ConsoleItem[] = [];
	let pageErrors: string[] = [];
	let netFails: NetFail[] = [];

	test.beforeEach(async ({page}) => {
		const c = await collectRuntime(page);
		consoleItems = c.consoleItems;
		pageErrors = c.pageErrors;
		netFails = c.netFails;
	});

	test('A. 真实主页几何 + 样式矩阵', async ({page}) => {
		fs.mkdirSync(REPORT_DIR, {recursive: true});
		const findings: Findings[] = [];
		for (const vp of VIEWPORTS) {
			await page.setViewportSize({width: vp.width, height: vp.height});
			await page.goto('/');
			await page.waitForTimeout(800);
			await auditState(page, `home-${vp.name}-sb-default`, findings);
			// 侧栏开（若默认关则展开）
			const expand = page.getByRole('button', {name: '展开侧栏'});
			if ((await expand.count()) > 0) {
				await expand.first().click().catch(() => {});
				await auditState(page, `home-${vp.name}-sb-on`, findings);
				const collapse = page.getByRole('button', {name: '折叠侧栏'});
				if ((await collapse.count()) > 0) {
					await collapse.first().click().catch(() => {});
				}
			}
		}
		fs.writeFileSync(
			path.join(REPORT_DIR, 'full-A-home.json'),
			JSON.stringify({findings}, null, 2), 'utf-8');
		// 断言只验证链路本身跑通；命中数是发现不是失败。
		expect(findings.length).toBeGreaterThan(0);
	});

	test('B. 交互遍历扫描（wide 视口）', async ({page}) => {
		fs.mkdirSync(REPORT_DIR, {recursive: true});
		await page.setViewportSize({width: 1440, height: 900});
		await page.goto('/');
		await page.waitForTimeout(800);
		const findings: Findings[] = [];

		// 1. 命令面板 Ctrl+K
		await page.keyboard.press('Control+k');
		await page.waitForTimeout(400);
		await auditState(page, 'palette-open', findings);
		await page.keyboard.press('Escape');
		await page.waitForTimeout(250);

		// 2. 命令面板 → 设置
		await page.keyboard.press('Control+k');
		await page.waitForTimeout(300);
		await page.keyboard.insertText('设置');
		await page.waitForTimeout(400);
		await page.keyboard.press('Enter');
		await page.waitForTimeout(600);
		await auditState(page, 'settings-modal', findings);
		await page.keyboard.press('Escape');
		await page.waitForTimeout(250);

		// 3. 主题选择 flyout
		const themeBtn = page.getByRole('button', {name: '选择主题'});
		if ((await themeBtn.count()) > 0) {
			await themeBtn.first().click().catch(() => {});
			await auditState(page, 'theme-flyout', findings);
			await page.keyboard.press('Escape');
			await page.waitForTimeout(200);
		}

		// 4. 工作区开关
		const wsBtn = page.getByRole('button', {name: /展开工作区|收起工作区/});
		if ((await wsBtn.count()) > 0) {
			await wsBtn.first().click().catch(() => {});
			await page.waitForTimeout(400);
			await auditState(page, 'workspace-toggle', findings);
		}

		// 5. 输入框展开
		const expandTa = page.getByRole('button', {name: /展开输入框|收起输入框/});
		if ((await expandTa.count()) > 0) {
			await expandTa.first().click().catch(() => {});
			await page.waitForTimeout(400);
			await auditState(page, 'composer-expand', findings);
			await expandTa.first().click().catch(() => {});
			await page.waitForTimeout(300);
		}

		// 6. 操作菜单（Composer 快速菜单）
		const opsMenu = page.getByRole('button', {name: '打开操作菜单'});
		if ((await opsMenu.count()) > 0) {
			await opsMenu.first().click().catch(() => {});
			await page.waitForTimeout(400);
			await auditState(page, 'composer-ops-menu', findings);
			await page.keyboard.press('Escape');
			await page.waitForTimeout(200);
		}

		fs.writeFileSync(
			path.join(REPORT_DIR, 'full-B-interactions.json'),
			JSON.stringify({findings}, null, 2), 'utf-8');
		expect(findings.length).toBeGreaterThan(0);
	});

	test('C. bench 流式回放：动画卡顿 + 内容态几何', async ({page}) => {
		fs.mkdirSync(REPORT_DIR, {recursive: true});
		await page.setViewportSize({width: 1280, height: 800});
		await page.goto('/bench/chat?rounds=12');
		await page.waitForFunction(() => {
			const w = window as unknown as {__XY_REPLAY__?: unknown};
			return !!w.__XY_REPLAY__;
		});
		await page.waitForTimeout(400);

		// 触发一段流式输出，同时采样帧间隔。
		const jankStream = await page.evaluate(async () => {
			const api = (window as unknown as {
				__XY_REPLAY__?: {setStream: (t: string, s?: string) => void};
			}).__XY_REPLAY__;
			const longText =
				'这是一段用于压测流式渲染的长文本。'.repeat(40) +
				'\n\n```ts\nconst x: number = 42; // streaming code\n```\n\n' +
				'| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n';
			const gaps: number[] = [];
			let last = performance.now();
			let raf = 0;
			const sample = (t: number) => {
				gaps.push(t - last);
				last = t;
				raf = requestAnimationFrame(sample);
			};
			raf = requestAnimationFrame(sample);
			// longtask 观测
			const longTasks: number[] = [];
			try {
				new PerformanceObserver(list => {
					for (const e of list.getEntries()) longTasks.push(e.duration);
				}).observe({entryTypes: ['longtask']});
			} catch { /* 环境不支持则跳过 */ }
			for (let i = 0; i < 10; i += 1) {
				api?.setStream(longText + `\n\nchunk ${i}`);
				await new Promise(r => setTimeout(r, 450));
			}
			cancelAnimationFrame(raf);
			const dropped = gaps.filter(g => g > 32).length;
			const avg = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : 0;
			return {
				avgFrameMs: Math.round(avg * 10) / 10,
				dropped,
				totalFrames: gaps.length,
				worstGapMs: gaps.length ? Math.round(Math.max(...gaps)) : 0,
				longTasksOver50: longTasks.filter(d => d > 50).length,
				worstLongTaskMs: longTasks.length ? Math.round(Math.max(...longTasks)) : 0,
			};
		});

		// 流式结束后：内容态几何 + 样式扫描（滚动到底再扫一屏）
		await page.waitForTimeout(600);
		const mid = await snapshot(page);
		await page.screenshot({path: path.join(REPORT_DIR, 'full-shot-bench-streamed.png')});
		// 滚动消息区后再扫一屏，覆盖中段内容
		const scrolled = await page.evaluate(async () => {
			const els = Array.from(document.querySelectorAll<HTMLElement>('*'))
				.filter(e => e.scrollHeight > e.clientHeight + 50 && getComputedStyle(e).overflowY !== 'visible');
			els.sort((a, b) => b.scrollHeight - a.scrollHeight);
			const target = els[0];
			if (!target) return false;
			target.scrollTop = target.scrollHeight / 2;
			await new Promise(r => setTimeout(r, 400));
			return true;
		});
		const midScrolled = scrolled ? await snapshot(page) : null;

		// 滚动期间的滚动帧率
		const jankScroll = await page.evaluate(async () => {
			const els = Array.from(document.querySelectorAll<HTMLElement>('*'))
				.filter(e => e.scrollHeight > e.clientHeight + 100 && getComputedStyle(e).overflowY !== 'visible');
			els.sort((a, b) => b.scrollHeight - a.scrollHeight);
			const target = els[0];
			if (!target) return {avgFrameMs: 0, dropped: 0, totalFrames: 0, worstGapMs: 0, longTasksOver50: 0, worstLongTaskMs: 0};
			const gaps: number[] = [];
			let last = performance.now();
			let raf = 0;
			const sample = (t: number) => {
				gaps.push(t - last);
				last = t;
				raf = requestAnimationFrame(sample);
			};
			raf = requestAnimationFrame(sample);
			for (let i = 0; i < 24; i += 1) {
				target.scrollTop += 120;
				await new Promise(r => setTimeout(r, 60));
			}
			cancelAnimationFrame(raf);
			const dropped = gaps.filter(g => g > 32).length;
			const avg = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : 0;
			return {
				avgFrameMs: Math.round(avg * 10) / 10,
				dropped,
				totalFrames: gaps.length,
				worstGapMs: gaps.length ? Math.round(Math.max(...gaps)) : 0,
				longTasksOver50: 0,
				worstLongTaskMs: 0,
			};
		});

		const payload = {jankStream, jankScroll, mid, midScrolled};
		fs.writeFileSync(
			path.join(REPORT_DIR, 'full-C-bench-jank.json'),
			JSON.stringify(payload, null, 2), 'utf-8');
		expect(jankStream.totalFrames).toBeGreaterThan(20);
	});

	test.afterEach(async () => {
		// 控制台/页面错误与失败请求归档（后端未起的 fetch 失败单独归类）。
		const realPageErrors = pageErrors;
		const realConsole = consoleItems.filter(i => !isExpectedBackendFail(i));
		const realNet = netFails.filter(i => !isExpectedBackendFail(i));
		fs.writeFileSync(
			path.join(REPORT_DIR, `full-runtime-${Date.now()}.json`),
			JSON.stringify({
				pageErrors: realPageErrors,
				consoleErrors: realConsole,
				consoleWarnCount: consoleItems.length - realConsole.length,
				netFails: realNet,
				expectedBackendFails: netFails.length - realNet.length,
			}, null, 2), 'utf-8');
	});
});
