/**
 * ui-audit.spec.ts — 解法一：程序化 GUI 几何错位扫描。
 *
 * 在 /bench/chat?rounds=N（下线确定合成转录，无后端依赖）上跑 `scanLayout`
 * 谓词，跨多个窗口尺寸 × 侧栏开/关组合出矩阵，把可量化的几何违背逐条输出
 * 到 `ui-audit-report/`：
 *   - summary.md      汇总表（按窗口 × 类型计数 + 条目）
 *   - report-<case>.json  每条违规带选择器/几何/坐标
 *   - shot-<case>.png      每 case 整页截图，供人工对照
 *
 * 只新建独立 e2e 文件与报告目录，不触碰任何生产源码。适合作为第一次摸底。
 * 用法：`npm run test:e2e:ui-audit`（见 playwright.ui-audit.config.ts）。
 */
import {test, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {
	scanLayout,
	ViolationKind,
	ScanResultSummary,
	ScanOptions,
} from './helpers/uiScan';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_DIR = path.resolve(__dirname, '..', 'ui-audit-report');

// 合成转录规模：轮数足够覆盖长文/代码/表格/工具行，又不至于 DOM 过大拖垮扫描。
const ROUNDS = Number(process.env.XEYO_UI_AUDIT_ROUNDS || '60');
// 窗口尺寸矩阵：宽窗口 + 标准 + 窄窗口（错位高发）。
const VIEWPORTS: {name: string; width: number; height: number}[] = [
	{name: 'wide', width: 1440, height: 900},
	{name: 'std', width: 1280, height: 800},
	{name: 'narrow', width: 960, height: 720},
];
// 侧栏开/关两种态（很多错位只在收起/展开的分栏反转时出现）。
const SIDEBAR_STATES: {open: boolean}[] = [{open: true}, {open: false}];

const SCAN_OPTS: ScanOptions = {
	predicates: {
		H_OVERFLOW: true,
		V_CLIP: true,
		TEXT_CLIP: true,
		ZERO_SIZE: true,
		OVERLAP: true,
	},
	overlapRatio: 0.12,
	minTextLen: 8,
};

// 让违规更醒目：太长列表截断到截图/报告可读规模。
const SCREENSHOT_VIOLATION_LIMIT = 40;

// 信号强度分级：高信号 = 明确的截断/溢出等"几何违背"；核验 = 需人工分辨
// 是否属有意叠层/预期滚动的候选。OVERLAP 天然有噪声，归入"核验"。
const HIGH_SIGNAL: Record<ViolationKind, boolean> = {
	H_OVERFLOW: true,
	V_CLIP: false,
	TEXT_CLIP: true,
	ZERO_SIZE: true,
	OVERLAP: false,
};

function signalRank(kind: ViolationKind): number {
	return HIGH_SIGNAL[kind] ? 0 : 1;
}

function caseName(vp: (typeof VIEWPORTS)[number], sb: (typeof SIDEBAR_STATES)[number]): string {
	return `r${ROUNDS}-${vp.name}-${vp.width}x${vp.height}-sidebar${sb.open ? 'on' : 'off'}`;
}

/** 对一条违规做局部裁剪截图；选择器定位不到时静默跳过（不因单条失败而中断整轮）。 */
async function clipViolation(page: Page, v: {selector: string}, outDir: string, name: string): Promise<string | null> {
	try {
		const loc = page.locator(v.selector);
		if ((await loc.count()) < 1) {
			return null;
		}
		await loc.first().screenshot({
			path: path.join(outDir, `${name}.png`),
			timeout: 3_000,
		});
		return `${name}.png`;
	} catch {
		return null;
	}
}

async function runCase(page: Page, vp: (typeof VIEWPORTS)[number], sb: (typeof SIDEBAR_STATES)[number]) {
	await page.setViewportSize({width: vp.width, height: vp.height});
	await page.goto(`/bench/chat?rounds=${ROUNDS}`);
	// 等合成回放位装完。
	await page.waitForFunction(() => {
		const w = window as unknown as {__XY_REPLAY__?: unknown};
		return !!w.__XY_REPLAY__;
	});
	// 等首屏渲染稳定。
	await page.waitForTimeout(300);

	// 侧栏态：回放接口提供 setSidebarOpen。
	await page.evaluate((open) => {
		(window as unknown as {
			__XY_REPLAY__?: {setSidebarOpen: (o: boolean) => void};
		}).__XY_REPLAY__?.setSidebarOpen(open);
	}, sb.open);
	await page.waitForTimeout(250);

	const result = (await page.evaluate(scanLayout, SCAN_OPTS)) as ScanResultSummary;

	// 整页截图。
	await page.screenshot({
		path: path.join(REPORT_DIR, `shot-${caseName(vp, sb)}.png`),
		fullPage: true,
	});

	return {vp, sb, result};
}

test('ui-audit：几何错位扫描（窗口 × 侧栏矩阵）', async ({page}) => {
	fs.mkdirSync(REPORT_DIR, {recursive: true});

	const rows: {
		name: string;
		summary: ScanResultSummary;
		screenshot: string;
		clips: {violationIndex: number; file: string}[];
	}[] = [];
	for (const vp of VIEWPORTS) {
		for (const sb of SIDEBAR_STATES) {
			const {result} = await runCase(page, vp, sb);
			const name = caseName(vp, sb);
			// 按信号强度排序：高信号（截断/溢出/零尺寸）在前，候选核验在后。
			const sorted = [...result.violations].sort((a, b) => {
				const r = signalRank(a.kind) - signalRank(b.kind);
				return r || b.detail - a.detail;
			});
			result.violations = sorted;
			// 截取每条违规的局部裁剪图（仅高信号 + 首屏若干，控制产物量与时长）。
			const clipDir = path.join(REPORT_DIR, 'clips', name);
			fs.mkdirSync(clipDir, {recursive: true});
			const clipTargets = sorted
				.map((v, i) => ({v, i}))
				.filter(({v}) => HIGH_SIGNAL[v.kind])
				.slice(0, 12);
			const clips: {violationIndex: number; file: string}[] = [];
			for (let k = 0; k < clipTargets.length; k += 1) {
				const file = `clip-${String(k + 1).padStart(2, '0')}`;
				await clipViolation(page, clipTargets[k]!.v, clipDir, file);
				clips.push({violationIndex: clipTargets[k]!.i, file});
			}
			rows.push({
				name,
				summary: result,
				screenshot: `shot-${name}.png`,
				clips,
			});
		}
	}

	// 逐 case 落 JSON（截图尺寸全量保存，含坐标便于人工复现）。
	for (const row of rows) {
		fs.writeFileSync(
			path.join(REPORT_DIR, `report-${row.name}.json`),
			JSON.stringify(row.summary, null, 2),
			'utf-8',
		);
	}

	const caps: ViolationKind[] = [
		'H_OVERFLOW',
		'V_CLIP',
		'TEXT_CLIP',
		'ZERO_SIZE',
		'OVERLAP',
	];

	// —— 汇总 md ——
	let md = `# XEYO GUI 几何错位扫描报告

> 生成方式：\`scanLayout\` 程序化几何谓词，在 \`/bench/chat?rounds=${ROUNDS}\` 合成转录上，
> 跨 ${VIEWPORTS.length} 个窗口尺寸 × ${SIDEBAR_STATES.length} 个侧栏态扫描。
> 本报告**只标记可疑项**，是否真错位需人工对照截图确认（见 §2 判定说明）。

## 1. 分 case 汇总

| case | 扫描元素数 | 命中总数 | 横向溢出 | 纵向裁切 | 文本截断 | 零尺寸 | 元素重叠 |
| --- | --- | --- | --- | --- | --- | --- | --- |
`;

	for (const row of rows) {
		const c = row.summary.byKind;
		md += `| ${row.name} | ${row.summary.scanned} | ${row.summary.violations.length} | ${c.H_OVERFLOW} | ${c.V_CLIP} | ${c.TEXT_CLIP} | ${c.ZERO_SIZE} | ${c.OVERLAP} |\n`;
	}

	md += '\n## 2. 判定与注意\n\n';
	md += `- **H_OVERFLOW**：右缘超出视口 / 内容宽超出容器。最像真实横向溢出，**优先目检**。\n`;
	md += `- **V_CLIP**：底缘超出滚动容器可见底。可能是长消息预期滚动，需确认是否该被裁切。\n`;
	md += `- **TEXT_CLIP**：scrollW/H 超 client 且 overflow 隐藏。**最像文本截断/省略号丢失**，重点看。\n`;
	md += `- **ZERO_SIZE**：有内容但渲染 ≈0 尺寸。多半是真 bug（塌陷/未挂载）。\n`;
	md += `- **OVERLAP**：非祖先的可见元素相交 ≥${Math.round((SCAN_OPTS.predicates?.OVERLAP ? 0.12 : 0.12) * 100)}%（阈值 overlapRatio）。常见误报：tooltip/徽标/绝对定位浮层**有意重叠**，需逐条排除。\n\n`;
	md += '## 3. 优化项\n\n';
	md += `- 阈值调参：\`overlapRatio\`（重叠敏感度）、\`minTextLen\`（零尺寸最小文本长度）。\n`;
	md += `- 扩大规模：\`XEYO_UI_AUDIT_ROUNDS\` 环境变量提高 \\\`rounds\\\`。\n`;
	md += `- 排除有意叠层：如需减少 OVERLAP 误报，可在 \`ScanOptions\` 增加 \\\`ignoreSelectors\\\` 白名单。\n\n`;

	// 每 case 列逐条（仅首屏可见 + 全部 kind 计数）。
	for (const row of rows) {
		md += `### ${row.name}\n\n`;
		const vs = row.summary.violations.slice(0, SCREENSHOT_VIOLATION_LIMIT);
		md += `![全页截图](${row.screenshot})\n\n`;
		if (row.clips.length > 0) {
			md += `**高信号局部裁剪（截断/溢出/零尺寸）：**\n\n`;
			for (const {violationIndex, file} of row.clips) {
				const v = row.summary.violations[violationIndex]!;
				const clipPath = `clips/${row.name}/${file}.png`;
				md += `<details><summary>#${violationIndex + 1} ${v.kind} — ${(v.preview ?? '').slice(0, 24) || v.selector}</summary>\n\n`;
				md += `![clip](${clipPath})\n\n`;
				md += `\`${v.selector}\` · ${v.hint}\n\n`;
				md += `</details>\n\n`;
			}
		}
		if (vs.length === 0) {
			md += `未命中任何几何违背。\n\n`;
			continue;
		}
		md += `| # | kind | 信号 | selector | 几何 | detail | 提示 |\n`;
		md += `| --- | --- | --- | --- | --- | --- | --- |\n`;
		vs.forEach((v, i) => {
			const sel = (v.selector || '').replace(/\|/g, '\\|');
			const geo = `${Math.round(v.geometry.x)},${Math.round(v.geometry.y)} ${Math.round(v.geometry.width)}x${Math.round(v.geometry.height)}`;
			const sig = HIGH_SIGNAL[v.kind] ? '**高**' : '核验';
			md += `| ${i + 1} | ${v.kind} | ${sig} | \`${sel}\` | ${geo} | ${v.detail} | ${v.hint} |\n`;
		});
		if (row.summary.violations.length > vs.length) {
			md += `> … 其余 ${row.summary.violations.length - vs.length} 条见 \`report-${row.name}.json\`。\n\n`;
		}
	}

	fs.writeFileSync(path.join(REPORT_DIR, 'summary.md'), md, 'utf-8');

	// 测试本身断言：至少能跑完并产出一份可读报告；不因命中数红（命中是发现，不是失败）。
	expect(rows).toHaveLength(VIEWPORTS.length * SIDEBAR_STATES.length);
	expect(fs.existsSync(path.join(REPORT_DIR, 'summary.md'))).toBe(true);
});
