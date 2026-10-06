/**
 * 样式指纹门：把「没动样式」从声明变成可复验产物。
 *
 *   node scripts/verify-style-fingerprint.mjs emit  [--base URL] [--out FILE]
 *   node scripts/verify-style-fingerprint.mjs check [--base URL] [--against FILE]
 *
 * 三块量测，各自独立判「样式有没有变」：
 *  A. scrollAudit —— 每个滚动容器：是否挂全局皮肤（::-webkit-scrollbar 宽度）、
 *     是否被标准 scrollbar-width/color 抢走渲染（Chromium 一旦设标准属性就丢掉
 *     整条 ::-webkit-scrollbar*）、hover 时滑块是否真的显形（.xy-hover-scroll-on）。
 *  B. fingerprints —— 逐元素 computed style 全属性哈希 → 计数表。不含位置/顺序，
 *     所以 DOM 重排不算变化；样式真变了才算。
 *  C. anchors —— 点名的 xy- 锚类的首个元素盒模型（规格 §11–§32 量过的那批）。
 *
 * 场景是遍历出来的：静态路由 + 每个 [aria-haspopup] 逐个打开。每个场景带
 * `stable` 前置（连取两次，不等即标不稳定并出声），避免把流式动画的抖动
 * 当成样式回归。
 */
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright';

const argv = process.argv.slice(2);
const MODE = argv[0];
if (MODE !== 'emit' && MODE !== 'check' && MODE !== 'report' && MODE !== 'diff') {
	console.error('usage: verify-style-fingerprint.mjs <emit|check|report|diff> [options]');
	process.exit(2);
}
const opt = (name, dflt) => {
	const i = argv.indexOf(`--${name}`);
	return i >= 0 ? argv[i + 1] : dflt;
};
const BASE = opt('base', 'http://localhost:5173');
const OUT = path.resolve(
	opt('out', path.join('_design_drafts', 'style-fingerprint.json')),
);
const ANCHORS = [
	'.xy-app-surface',
	'.xy-chat-surface',
	'.xy-hover-scroll',
	'.xy-menu-flyout',
	'.xy-modal-panel',
	'.xy-modal-backdrop',
	'.xy-user-prompt',
	'.xy-timeline-turn',
	'.xy-timeline-activity',
	'.xy-prompt-sticky',
	'.xy-sidebar',
	'.xy-workspace-chrome',
];

const PANEL_SEL = '.xy-menu-flyout,.xy-ctx-menu,.xy-modal-panel,[role=dialog]';

/** 逐场景注入：冻结动效与打字机，让两次取值可比。 */
const FREEZE = () => {
	const st = document.createElement('style');
	st.id = 'xy-fp-freeze';
	st.textContent =
		'*,*::before,*::after{animation:none!important;transition:none!important;' +
		'caret-color:transparent!important;scroll-behavior:auto!important}';
	document.head.appendChild(st);
	for (const a of document.getAnimations?.() ?? []) {
		try {
			a.pause();
		} catch {
			/* 已经结束的动画 */
		}
	}
	document.activeElement?.blur?.();
};

/** 页内量测：A/B/C 三块一次拿全。 */
const PROBE = ({anchors: anchorList, panelSel}) => {
	// FNV-1a：跑在浏览器里，不能引 Node 的 crypto；同一次运行内自洽即可比较。
	const sha = s => {
		let h = 0x811c9dc5;
		for (let i = 0; i < s.length; i += 1) {
			h ^= s.charCodeAt(i);
			h = Math.imul(h, 0x01000193) >>> 0;
		}
		return h.toString(16).padStart(8, '0');
	};

	// 稳定 identity：tag + 排序后的 class + role/aria-*（不含文本、不含位置）
	const kindOf = el => {
		const cls = [...el.classList].sort().join('.');
		const role = el.getAttribute('role') || '';
		const aria = [...el.attributes]
			.filter(a => a.name.startsWith('aria-'))
			.map(a => `${a.name}=${a.value}`)
			.sort()
			.join(',');
		return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}${
			role ? '[role=' + role + ']' : ''
		}${aria ? '{' + aria + '}' : ''}`;
	};

	const fingerprint = (rootSel = null) => {
		const table = new Map();
		const roots = rootSel ? [...document.querySelectorAll(rootSel)] : [...document.querySelectorAll('body *')];
		for (const el of rootSel ? roots.flatMap(r => [...r.querySelectorAll('*')]) : roots) {
			if (el.id === 'xy-fp-freeze') continue;
			const cs = getComputedStyle(el);
			const props = [];
			for (let i = 0; i < cs.length; i += 1) {
				const p = cs[i];
				props.push(`${p}:${cs.getPropertyValue(p)}`);
			}
			props.sort();
			const sig = sha(props.join(';'));
			const kind = kindOf(el);
			const hit = table.get(sig) || {c: 0, kinds: new Map()};
			hit.c += 1;
			hit.kinds.set(kind, (hit.kinds.get(kind) || 0) + 1);
			table.set(sig, hit);
		}
		const out = [];
		for (const [sig, hit] of [...table].sort((a, b) => a[0] < b[0] ? -1 : 1)) {
			out.push({
				sig,
				c: hit.c,
				kinds: [...hit.kinds]
					.sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))
					.slice(0, 3)
					.map(([k, n]) => `${k}×${n}`),
			});
		}
		return out;
	};

	const scrollAudit = () => {
		const rows = [];
		for (const el of document.querySelectorAll('*')) {
			const cs = getComputedStyle(el);
			const scrollsY = /auto|scroll/.test(cs.overflowY);
			const scrollsX = /auto|scroll/.test(cs.overflowX);
			if (!scrollsY && !scrollsX) continue;
			const hasClass = el.classList.contains('xy-hover-scroll');
			rows.push({
				kind: (() => {
					const cls = [...el.classList].sort().join('.');
					return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`;
				})(),
				axis: scrollsX && scrollsY ? 'xy' : scrollsY ? 'y' : 'x',
				client: [el.clientWidth, el.clientHeight],
				content: [el.scrollWidth, el.scrollHeight],
				// 真溢出：内容超出可视区，滚动条对用户可达
				overflowing:
					el.scrollHeight > el.clientHeight + 1 ||
					el.scrollWidth > el.clientWidth + 1,
				hoverSkin: hasClass,
				hoverOn: el.classList.contains('xy-hover-scroll-on'),
				// 标准属性非 auto ⇒ Chromium 丢弃该元素全部 ::-webkit-scrollbar*
				stdWidth: cs.scrollbarWidth,
				stdColor: cs.scrollbarColor,
				gutter: cs.scrollbarGutter,
				// ::-webkit-scrollbar 的实际生效宽度（伪元素可读）
				wkWidth: getComputedStyle(el, '::-webkit-scrollbar').width,
				wkDisplay: getComputedStyle(el, '::-webkit-scrollbar').display,
			});
		}
		return rows.sort((a, b) => (a.kind < b.kind ? -1 : 1));
	};

	const anchors = () => {
		const out = {};
		for (const sel of anchorList) {
			const el = document.querySelector(sel);
			if (!el) {
				out[sel] = null;
				continue;
			}
			const r = el.getBoundingClientRect();
			const cs = getComputedStyle(el);
			out[sel] = {
				box: [
					Math.round(r.x),
					Math.round(r.y),
					Math.round(r.width),
					Math.round(r.height),
				],
				fontSize: cs.fontSize,
				bg: cs.backgroundColor,
				color: cs.color,
				radius: cs.borderRadius,
				borderTop: cs.borderTopWidth,
			};
		}
		return out;
	};

	return {
		count: document.querySelectorAll('body *').length,
		fp: fingerprint(),
		// 浮层子树单独取：页面级指纹在活数据页上逐次不同（会话列表/角标/待批
		// 面板），只有"这次重构真正动的那些面板"能被严格门住。
		panelFp: fingerprint(panelSel),
		scroll: scrollAudit(),
		anchors: anchors(),
	};
};

async function probeOnce(page) {
	await page.evaluate(FREEZE);
	return page.evaluate(PROBE, {anchors: ANCHORS, panelSel: PANEL_SEL});
}

/**
 * 真悬停量测：`.xy-hover-scroll` 的滑块只在宿主加 `xy-hover-scroll-on` 后显形，
 * 不悬停就取值必然得到 false —— 那是恒假判据，量不出「有没有复用聊天滚动条」。
 * 所以逐元素把鼠标移进去再读回类名。
 */
async function measureReveal(page) {
	const out = {};
	for (const el of await page.$$('.xy-hover-scroll')) {
		// 活数据页上 React 会在两次取值之间把节点换掉，句柄失效是常态而不是
		// 事故：记成 detached 继续走，不许让整个量测崩在这里。
		try {
			const kind = await el.evaluate(
				e => `${e.tagName.toLowerCase()}.${[...e.classList].sort().join('.')}`,
			);
			const box = await el.boundingBox();
			if (!box || box.width < 4 || box.height < 4) {
				out[kind] = out[kind] || 'unmounted';
				continue;
			}
			await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
			await page.waitForTimeout(180);
			const on = await el.evaluate(e =>
				e.classList.contains('xy-hover-scroll-on'),
			);
			out[kind] = on ? 'on' : 'never';
			await page.mouse.move(2, 2);
			await page.waitForTimeout(60);
		} catch {
			continue;
		}
	}
	return out;
}

/** 连取两次：相等才算稳定，否则出声标 unstable。 */
async function probeStable(page) {
	const a = await probeOnce(page);
	await page.waitForTimeout(450);
	const b = await probeOnce(page);
	return {
		...b,
		reveal: await measureReveal(page),
		stable: JSON.stringify(a.fp) === JSON.stringify(b.fp),
	};
}

async function collect(base) {
	const browser = await chromium.launch();
	const ctx = await browser.newContext({
		viewport: {width: 1440, height: 900},
		deviceScaleFactor: 1,
		reducedMotion: 'reduce',
		colorScheme: 'light',
	});
	const page = await ctx.newPage();
	const scenes = {};

	const goto = async (url, name) => {
		await page.goto(url, {waitUntil: 'networkidle', timeout: 60_000}).catch(() => {});
		await page.waitForTimeout(700);
		scenes[name] = await probeStable(page);
	};

	await goto(`${BASE}/`, 'home');
	// bench 的参数是 rounds/seed/phase/scenario（`stage` 那套已不存在）：
	// 两档必须真不同，否则第二条是重复探针而不是覆盖面。
	await goto(`${BASE}/bench/chat?rounds=3`, 'bench-r3');
	await goto(`${BASE}/bench/chat?rounds=12`, 'bench-r12');
	await goto(`${BASE}/usage`, 'page-usage');
	await goto(`${BASE}/plugins`, 'page-plugins');
	await goto(`${BASE}/diagnostics`, 'page-diagnostics');
	// 设置页是本仓最大的抽屉，且 `.xy-settings-body` 是唯一把标准
	// scrollbar-width 压在浮动面板上的地方 —— 不打开就量不到。
	await goto(`${BASE}/`, 'settings');
	await page.click('button[aria-label="设置"]', {timeout: 4000}).catch(() => {});
	await page.waitForTimeout(500);
	scenes.settings = await probeStable(page);

	// 每个 [aria-haspopup] 逐个打开：浮层是本次重构的主战场，必须被量到。
	// 每轮重新 goto：不按坐标点空白关浮层，避免在真实会话里误触消息操作。
	// 场景名只取稳定身份并按它去重 —— 用索引命名会让活数据（多一个会话行就多
	// 一个触发点）把整批场景名错位，基线就对不上现实。
	const sweep = async (url, prefix, only) => {
		await page.goto(url, {waitUntil: 'networkidle'}).catch(() => {});
		await page.waitForTimeout(600);
		const labels = await page.evaluate(() =>
			[...document.querySelectorAll('[aria-haspopup]')].map(el => {
				const a = (el.getAttribute('aria-label') || '').trim();
				if (a) return a;
				// 无标签的触发点（模型选择器就只写模型名）不能被跳过：
				// 上一版按 aria-label 去重，把这类整批漏掉了。
				const t = (el.textContent || '').trim().slice(0, 20);
				return t ? `t:${t}` : 'unnamed';
			}),
		);
		const seen = new Set();
		for (const label0 of labels) {
			if (seen.has(label0)) continue;
			seen.add(label0);
			// /diagnostics 与 / 共用同一个壳，那里的应用菜单/主题/添加工作区等
			// 触发点全是重复覆盖面，只添不稳定不添coverage —— 只点本页独有的。
			if (only && !only.includes(label0)) continue;
			await page.goto(url, {waitUntil: 'networkidle'}).catch(() => {});
			await page.waitForTimeout(450);
			const sel = label0.startsWith('t:')
				? `[aria-haspopup]`
				: `[aria-haspopup][aria-label="${label0}"]`;
			const idx = labels.indexOf(label0);
			const loc = label0.startsWith('t:')
				? page.locator(sel).nth(idx)
				: page.locator(sel).first();
			const label = `${prefix}-${label0.replace(/^t:/, '')}`;
			const before = await page.locator(PANEL_SEL).count();
			await loc.click({timeout: 2500}).catch(() => {});
			await page.waitForTimeout(350);
			const after = await page.locator(PANEL_SEL).count();
			scenes[label] = await probeStable(page);
			scenes[label].opened = after > before;
		}
	};
	await sweep(`${BASE}/`, 'pop');
	// 诊断页独有的触发点只有会话选择器（其余都是壳上那几个的重现）。
	await sweep(`${BASE}/diagnostics`, 'digpop', ['会话']);
	await browser.close();
	return {
		generatedAt: new Date().toISOString(),
		base,
		haspopupCount: Object.keys(scenes).filter(k => /^(pop|digpop)-/.test(k)).length,
		scenes,
	};
}

/**
 * report：只读基线，打印「滚动条复用面」清单 —— 哪些溢出容器没走全局皮肤、
 * 哪些被标准属性抢走渲染路径、哪些挂了皮肤却永远不显形。这是滚动条这刀的
 * 验收面，也是改前的欠账清单。
 */
if (MODE === 'report') {
	const gold = JSON.parse(readFileSync(OUT, 'utf8'));
	const rows = new Map();
	for (const [sc, s] of Object.entries(gold.scenes)) {
		for (const r of s.scroll || []) {
			const k = r.kind;
			const cur = rows.get(k) || {scenes: 0, r};
			cur.scenes += 1;
			cur.ovf = cur.ovf || r.overflowing;
			const rev = (s.reveal || {})[k];
			if (rev === 'on') cur.reveal = 'on';
			else if (rev && !cur.reveal) cur.reveal = rev;
			rows.set(k, cur);
		}
	}
	const verdict = v => {
		const r = v.r;
		// 标准属性里只有 `thin` 是抢皮肤：`none` 的意图就是不出条，Chromium 走
		// 标准路径同样达成（实测 .xy-work-breadcrumbs 无条），不算未复用。
		if (r.stdWidth === 'thin') return '标准属性抢走全局皮肤 ✗';
		if (r.stdWidth === 'none')
			return r.wkDisplay === 'none' ? '有意隐藏（两路都封）' : '有意隐藏（仅标准路径）';
		if (r.kind.includes('xy-hover-scroll')) {
			if (v.reveal === 'on') return '复用聊天皮肤 ✓';
			if (v.reveal === 'never') return '挂了皮肤却从不显形 ✗';
			return '皮肤在，但未挂载/未溢出（看不到）';
		}
		if (r.wkDisplay === 'none') return '有意隐藏（webkit 路径）';
		// 没挂 .xy-hover-scroll 不等于「没走全局皮肤」：`*::-webkit-scrollbar`
		// 对任何元素都生效，它拿的是常显档。真 opt-out 只有上面的 thin。
		if (v.ovf) return '全局常显皮肤（未用 hover 档）';
		return '未溢出，暂不可见';
	};
	const list = [...rows].sort((a, b) => (a[0] < b[0] ? -1 : 1));
	console.log(`基线 ${OUT}  场景 ${Object.keys(gold.scenes).length}  滚动容器种类 ${list.length}\n`);
	for (const [kind, v] of list) {
		console.log(
			`  ${String(v.scenes).padStart(2)}×  ${kind.slice(0, 74).padEnd(74)} ${verdict(v)}`,
		);
	}
	const bad = list.filter(([, v]) => verdict(v).includes('✗'));
	console.log(`\n欠账：${bad.length} 类滚动容器未复用全局皮肤`);
	process.exit(0);
}

/**
 * 分级比对：返回 {diffs, notices}。check 与 diff 两个入口共用，保证
 * "改前 vs 改后"和"当前 vs 基线"走的是同一套判据。
 */
function compareScenes(base, cur) {
	const diffs = [];
	const notices = [];
	/**
	 * 判据分级（本轮实测出来的边界，不是保守起见）：
	 * - 页面级整页指纹：一律只看不判。home/usage/settings 吃 :8000 活数据，
	 *   bench 的代码块语法高亮是异步的（同一份代码两次跑差 181 个 span），
	 *   都不满足可重复性。
	 * - 浮层子树 panelFp：判，但只比"出现过哪些样式"，不比行数 —— 浮层里的
	 *   列表条目数由数据决定，样式种类才是我要钉住的东西。
	 * - 滚动条审计 / 悬停显形 / 锚点盒：判，但只在全局场景；pop-* 场景的触发点
	 *   集合本身随活数据变，整页滚动容器会时有时无。
	 */
	const isPop = name => /^(pop|digpop)-/.test(name);
	for (const [name, c] of Object.entries(cur.scenes)) {
		const b = base.scenes[name];
		if (!b) {
			notices.push(`${name}: 对照侧没有这个场景（新增触发点或改过场景表）`);
			continue;
		}
		const kindsOf = rows => new Map(rows.map(r => [r.sig, r]));
		const cmpFp = (from, to, sink, label, byCount) => {
			const g = kindsOf(from);
			const cc = kindsOf(to);
			for (const [sig, r] of g) {
				const now = cc.get(sig);
				if (!now) sink.push(`${name}: ${label}指纹消失 ${sig} ${r.kinds[0] || ''}`);
				else if (byCount && now.c !== r.c)
					sink.push(`${name}: ${label}指纹 ${sig} 计数 ${r.c}→${now.c} ${r.kinds[0] || ''}`);
			}
			for (const [sig, r] of cc)
				if (!g.has(sig)) sink.push(`${name}: ${label}新指纹 ${sig} ${r.kinds[0] || ''}`);
		};
		if (!c.stable || !b.stable) {
			notices.push(`${name}: 页面指纹不稳定（a=${b.stable} b=${c.stable}）`);
		}
		cmpFp(b.fp, c.fp, notices, '页面', true);
		if (!b.panelFp || !c.panelFp) {
			notices.push(`${name}: 有一侧没有 panelFp（旧产物，重 emit 后才有牙）`);
		} else if (b.panelFp.length === 0 && c.panelFp.length === 0) {
			notices.push(`${name}: 无浮层在场，panelFp 未参与判定`);
		} else {
			cmpFp(b.panelFp, c.panelFp, diffs, '浮层', false);
		}
		const cmpScroll = (from, to, sink) => {
			const gs = new Map(from.map(r => [`${r.kind}|${r.axis}`, r]));
			const cs = new Map(to.map(r => [`${r.kind}|${r.axis}`, r]));
			for (const [k, r] of gs) {
				const now = cs.get(k);
				if (!now) {
					// 容器在/不在是数据与异步高亮的问题（bench 的代码块要等
					// 着色完成才变成滚动容器）；**怎么被画**才是样式判据面。
					notices.push(`${name}: 滚动容器不在场 ${k}`);
					continue;
				}
				for (const f of ['hoverSkin', 'stdWidth', 'wkWidth', 'wkDisplay', 'gutter']) {
					if (String(r[f]) !== String(now[f]))
						sink.push(`${name}: 滚动条 ${k}.${f} ${r[f]}→${now[f]}`);
				}
			}
			for (const k of cs.keys()) if (!gs.has(k)) notices.push(`${name}: 新滚动容器 ${k}`);
		};
		// 悬停显形是端到端判据：改了接线就必须让它从 never 变 on（白名单外不许反向漂）
		const sink = isPop(name) ? notices : diffs;
		cmpScroll(b.scroll || [], c.scroll || [], sink);
		for (const [k, was] of Object.entries(b.reveal || {})) {
			const now = (c.reveal || {})[k];
			if (now !== was) sink.push(`${name}: hover 显形 ${k} ${was}→${now}`);
		}
		for (const sel of Object.keys(c.anchors)) {
			if (isPop(name) && !/menu-flyout|ctx-menu|modal-panel/.test(sel)) continue;
			if (JSON.stringify(b.anchors[sel]) !== JSON.stringify(c.anchors[sel]))
				sink.push(`${name}: 锚点 ${sel} ${JSON.stringify(b.anchors[sel])} → ${JSON.stringify(c.anchors[sel])}`);
		}
	}
	for (const name of Object.keys(base.scenes)) {
		if (!cur.scenes[name]) notices.push(`${name}: 实测侧缺失该场景`);
	}
	return {diffs, notices};
}

/**
 * diff 模式：比两份已存产物（都要含 panelFp）。用于"改前 / 改后"各 emit 一次
 * 之后离线对盘，不必再开第三次浏览器。
 */
if (MODE === 'diff') {
	const a = JSON.parse(readFileSync(opt('a', OUT), 'utf8'));
	const b = JSON.parse(readFileSync(opt('b', OUT), 'utf8'));
	const {diffs, notices} = compareScenes(a, b);
	console.log(
		`diff A=${path.basename(opt('a', OUT))} B=${path.basename(opt('b', OUT))}\n` +
			`  场景 A ${Object.keys(a.scenes).length} / B ${Object.keys(b.scenes).length}` +
			`\n  提示 ${notices.length} 条`,
	);
	for (const x of notices.slice(0, 12)) console.log('  · ' + x);
	if (notices.length > 12) console.log(`  · …另 ${notices.length - 12} 条`);
	if (diffs.length === 0) {
		console.log('  ✅ 严格面零漂移');
		process.exit(0);
	}
	console.log(`  ❌ 漂移 ${diffs.length} 条:`);
	for (const d of diffs.slice(0, 120)) console.log('   - ' + d);
	if (diffs.length > 120) console.log(`   …另 ${diffs.length - 120} 条`);
	process.exit(1);
}

const data = await collect(BASE);
const unstable = Object.entries(data.scenes)
	.filter(([, s]) => !s.stable)
	.map(([k]) => k);
/** 重复探针自检：两场景指纹逐字相同 ⇒ 其中一条不提供覆盖面，必须出声。 */
const dupScenes = (() => {
	const byFp = new Map();
	const out = [];
	for (const [k, s] of Object.entries(data.scenes)) {
		const key = JSON.stringify(s.fp);
		if (byFp.has(key)) out.push(`${byFp.get(key)}≡${k}`);
		else byFp.set(key, k);
	}
	return out;
})();
const openedScenes = Object.entries(data.scenes)
	.filter(([k]) => /^(pop|digpop)-/.test(k))
	.filter(([, s]) => s.opened)
	.map(([k]) => k);

if (MODE === 'emit') {
	mkdirSync(path.dirname(OUT), {recursive: true});
	writeFileSync(OUT, JSON.stringify(data, null, 0), 'utf8');
	console.log(
		`emit → ${OUT}\n  场景 ${Object.keys(data.scenes).length}` +
			`（浮层打开成功 ${openedScenes.length}/${popupSceneCount(data)}）` +
			`\n  不稳定场景 ${unstable.length}: ${unstable.join(', ') || '无'}` +
			`\n  重复探针 ${dupScenes.length}: ${dupScenes.join(', ') || '无'}` +
			`\n  字节 ${readFileSync(OUT, 'utf8').length}`,
	);
	process.exit(0);
}

const gold = JSON.parse(readFileSync(OUT, 'utf8'));
const {diffs, notices} = compareScenes(gold, data);

console.log(
	`check against ${OUT}\n  场景 ${Object.keys(data.scenes).length}` +
		`（浮层打开成功 ${openedScenes.length}/${popupSceneCount(data)}）` +
		`\n  重复探针 ${dupScenes.length}: ${dupScenes.join(', ') || '无'}` +
		`\n  提示 ${notices.length} 条（活数据页的整页指纹只看不判）`,
);
for (const x of notices.slice(0, 20)) console.log('  · ' + x);
if (notices.length > 20) console.log(`  · …另 ${notices.length - 20} 条`);
if (diffs.length === 0) {
	console.log('  ✅ 样式零漂移');
	process.exit(0);
}
console.log(`  ❌ 漂移 ${diffs.length} 条:`);
for (const d of diffs.slice(0, 120)) console.log('   - ' + d);
if (diffs.length > 120) console.log(`   …另 ${diffs.length - 120} 条`);
process.exit(1);

function popupSceneCount(d) {
	return Object.keys(d.scenes).filter(k => /^(pop|digpop)-/.test(k)).length;
}
