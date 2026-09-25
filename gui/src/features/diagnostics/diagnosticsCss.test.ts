/**
 * diagnostics.css 的设计契约回归。
 *
 * 这个文件顶部本来就写着纪律（只用 @theme 令牌、动画面板禁 blur、降级要收全），
 * 但此前没有任何东西在守它 —— 于是 `letter-spacing` 落到了汉字上、十个可点类
 * 一个焦点环都没有、圆角散在 6/10/12px 这些刻度外的值上。
 * 这里把"声明过的纪律"变成可执行的断言：只读 CSS，不依赖浏览器。
 */
/// <reference types="node" />
// 本项目的 tsconfig 不给测试文件带 node 类型，@types/node 是装着的，显式引用即可。
// 不用 ?raw：Vite 的 CSS 插件会把 `.css?raw` 折进 CSS 管线，测试里拿到的是空串。
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {describe, expect, it} from 'vitest';

const css = readFileSync(
	resolve(process.cwd(), 'src/styles/diagnostics.css'),
	'utf8',
);
const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
// 本文件在工作树是 CRLF，末尾多一个 \r —— 收口必须用 \}\s*$，否则整段匹配失败、
// 下面的降级断言会拿空字符串静默空跑。
const reduceMatch = stripped.match(
	/@media \(prefers-reduced-motion: reduce\)\s*\{([\s\S]*)\}\s*$/,
);
const reduceBlock = reduceMatch ? reduceMatch[1] : '';
const topLevel = stripped.replace(
	/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*$/,
	'',
);

const blocks = [...topLevel.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => ({
	sel: m[1].replace(/\s+/g, ' ').trim(),
	body: m[2],
}));

const classNames = (sel: string): string[] =>
	// 必须吃到 \w（含大写），否则 .xy-dig-tabQQ 会被截成 .xy-dig-tab，
	// 变异测试就杀不死这条断言（实测踩过）。
	[...sel.matchAll(/\.(xy-dig-[\w-]+)/g)].map(m => m[1]);

/** 某个伪类下出现过的类名集合（逗号分组的选料要逐段看，否则只会命中第一段）。 */
const classesWith = (pseudo: string): Set<string> => {
	const out = new Set<string>();
	for (const b of blocks) {
		for (const part of b.sel.split(',')) {
			if (!part.includes(pseudo)) continue;
			for (const c of classNames(part.split(pseudo)[0])) out.add(c);
		}
	}
	return out;
};

describe('diagnostics.css 设计契约', () => {
	it('能解析出规则块（防止正则空跑让下面所有断言假绿）', () => {
		expect(blocks.length).toBeGreaterThan(60);
		expect(reduceBlock.length).toBeGreaterThan(0);
	});

	it('汉字页面上不出现 letter-spacing', () => {
		expect(stripped).not.toMatch(/letter-spacing/);
	});

	it('本页不出现 blur（动画面板硬约束）', () => {
		expect(stripped).not.toMatch(/blur\(/);
	});

	it('颜色只取 @theme 令牌，不写字面色值', () => {
		expect(stripped).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
		expect(stripped).not.toMatch(/rgba?\(/);
	});

	it('圆角只允许 token、胶囊 999px 与 3px 以内的微条', () => {
		const bad: string[] = [];
		for (const b of blocks) {
			for (const decl of b.body.split(';')) {
				const m = decl.match(/border-radius:\s*([^;]+)/);
				if (!m) continue;
				const v = m[1].trim();
				const ok =
					/^var\(--xy-radius-/.test(v) ||
					v === '999px' ||
					/^(\d+(?:\.\d+)?)px$/.test(v) &&
						Number(/(\d+(?:\.\d+)?)/.exec(v)![1]) <= 3 ||
					/^var\(--xy-radius-[a-z]+\)( var\(--xy-radius-[a-z]+\)| 0px?| 0)+$/.test(
						v,
					);
				if (!ok) bad.push(`${b.sel} → ${v}`);
			}
		}
		expect(bad).toEqual([]);
	});

	it('每个可点类都有键盘焦点环', () => {
		const focused = classesWith(':focus-visible');
		const clickable = [
			'xy-dig-btn',
			'xy-dig-chip',
			'xy-dig-tab',
			'xy-dig-more',
			'xy-dig-mode',
			'xy-dig-run',
			'xy-dig-step-head',
			'xy-dig-finding-head',
			'xy-dig-evidence',
			'xy-dig-session',
			'xy-dig-input',
			'xy-dig-textarea',
			'xy-dig-step-link',
		];
		expect(clickable.filter(c => !focused.has(c))).toEqual([]);
	});

	it('声明了 cursor:pointer 的类都要有 hover 反馈', () => {
		const hovering = classesWith(':hover');
		const pointered = new Set<string>();
		for (const b of blocks) {
			if (!/cursor:\s*pointer/.test(b.body)) continue;
			for (const c of classNames(b.sel)) pointered.add(c);
		}
		expect(pointered.size).toBeGreaterThanOrEqual(10);
		expect([...pointered].filter(c => !hovering.has(c)).sort()).toEqual([]);
	});

	it('每个声明 transition 的类都在 prefers-reduced-motion 里降级', () => {
		const animated = new Set<string>();
		for (const b of blocks) {
			if (!/transition:/.test(b.body)) continue;
			for (const c of classNames(b.sel)) animated.add(c);
		}
		expect(animated.size).toBeGreaterThan(0);
		const missing = [...animated].filter(c => !reduceBlock.includes(`.${c}`));
		expect(missing.sort()).toEqual([]);
	});
});
