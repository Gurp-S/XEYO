/**
 * 分层与复用面的结构门。
 *
 * 每条规则都配一个"能失败"的自证夹具：只跑真产物不足以证明门有牙（历史上
 * 多条门在搬家后静默失去覆盖面）。夹具走内存，不落盘。
 */
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {describe, expect, it} from 'vitest';
import path from 'node:path';

const ROOT = path.resolve(process.cwd(), 'src');

function walk(dir: string, out: string[] = []): string[] {
	for (const name of readdirSync(dir)) {
		const full = path.join(dir, name);
		if (statSync(full).isDirectory()) {
			walk(full, out);
		} else if (/\.(ts|tsx)$/.test(name) && !/\.(test|guard\.test)\.(ts|tsx)$/.test(name)) {
			out.push(full);
		}
	}
	return out;
}

const allSrc = walk(ROOT);

/** 从 import/export from 语句里抽出模块说明符。 */
function specifiers(src: string): string[] {
	return [...src.matchAll(/(?:import|export)[^;]*?from\s*['"]([^'"]+)['"]/g)].map(m => m[1]);
}

describe('全局层不许回头依赖局部层', () => {
	// src/ui 是"全局"那一侧：只准依赖 react、UI 基座 hooks 与无业务知识的 lib。
	const ALLOWED = /^(@\/hooks|@\/lib\/(utils|escStack|ime|paths)(\/|$)|react|lucide-react|\.)/;
	const GLOBAL_KIT = allSrc.filter(f => path.relative(ROOT, f).startsWith(`ui${path.sep}`));
	function reverseDeps(files: string[]) {
		const bad: string[] = [];
		for (const f of files) {
			for (const s of specifiers(readFileSync(f, 'utf8'))) {
				if (!ALLOWED.test(s)) {
					bad.push(`${path.relative(ROOT, f)} → ${s}`);
				}
			}
		}
		return bad;
	}
	it('src/ui/** 不 import 组件/状态/页面/领域', () => {
		expect(GLOBAL_KIT.length).toBeGreaterThan(0);
		expect(reverseDeps(GLOBAL_KIT)).toEqual([]);
	});
	it('门自身可失败：给一条反向依赖就报出来', () => {
		expect(ALLOWED.test('@/lib/utils')).toBe(true);
		expect(ALLOWED.test('@/lib/api/core')).toBe(false);
		expect(ALLOWED.test('@/stores/chatStore')).toBe(false);
	});
});

describe('滚动条皮肤不许只挂类不接线', () => {
	// .xy-hover-scroll 的滑块底色默认 transparent，只有 useHoverScroll /
	// useScrollArea 的定时器会加 -on / host-on。漏接 = 那块区域没有滚动条。
	const WIRING = /useHoverScroll|useScrollArea/;
	function offenders(sources: Array<[string, string]>) {
		return sources.filter(([, src]) => {
			if (WIRING.test(src)) {
				return false;
			}
			// 只认"把类挂到元素上"的那一行：选择器字符串与报错文案里的类名不算
			// （bench 探针就靠 .xy-hover-scroll 定位滚动容器）。
			return src
				.split('\n')
				.some(
					line =>
						line.includes('xy-hover-scroll') &&
						/className|class=|classList/.test(line),
				);
		}).map(([name]) => name);
	}
	it('带 xy-hover-scroll 的文件必须引滚动区基座', () => {
		const bad = offenders(allSrc.map(f => [path.relative(ROOT, f), readFileSync(f, 'utf8')]));
		expect(bad).toEqual([]);
	});
	it('门自身可失败：漏接的那一份会被点名', () => {
		expect(
			offenders([
				['Good.tsx', "import {useScrollArea} from '@/ui/useScrollArea';\nclass='xy-hover-scroll'"],
				['Bad.tsx', "import {useState} from 'react';\nclass='xy-hover-scroll'"],
			]),
		).toEqual(['Bad.tsx']);
	});
});

describe('全局滚动条皮肤只有一个真源', () => {
	// Chromium 见到标准 scrollbar 属性就丢掉该元素全部 ::-webkit-scrollbar*，
	// 于是那一块退回原生条 —— 等于局部退出全局皮肤。`none`（有意隐藏）不禁。
	const CSS = (() => {
		const dir = path.join(ROOT, 'styles');
		return readdirSync(dir)
			.filter(f => f.endsWith('.css'))
			.map(
				f =>
					[
						f,
						// 注释里的字样不算违规：本文件就用注释记过"原先这里有 thin"。
						readFileSync(path.join(dir, f), 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''),
					] as [string, string],
			);
	})();
	function thinSites(sources: Array<[string, string]>) {
		return sources.filter(([, src]) => /scrollbar-width\s*:\s*thin/.test(src)).map(([f]) => f);
	}
	it('styles/*.css 不许写 scrollbar-width: thin', () => {
		expect(CSS.length).toBeGreaterThan(0);
		expect(thinSites(CSS)).toEqual([]);
	});
	it('门自身可失败：加一处 thin 就会被抓到', () => {
		expect(thinSites([['a.css', '.x{scrollbar-width: thin}'], ['b.css', '.y{scrollbar-width:none}']])).toEqual([
			'a.css',
		]);
	});
});

describe('有 JSX 的目录必须在样式契约门的扫描根里', () => {
	// 两道样式契约门（零字面色值 / 视觉回退补漏）按**目录名**扫源码。搬家或
	// 新加一层而不同批改它们，覆盖面就静默缩水 —— 本仓为此撞过六次。
	const GUARDS = [
		'styles/styleRevertContracts.guard.test.ts',
		'themePairing.guard.test.ts',
	];
	/**
	 * 已知未纳管的顶层目录，钉成精确集合（只能变短）：
	 * bench/pasture/pet 是演示与桌宠面；lib/contextMenus.tsx 与
	 * theme/ThemePicker.tsx 里有 JSX，却不在那两道门的历史扫描根内 ——
	 * 这是实测出来的既有缺口，不是本层引入的。
	 */
	const KNOWN_GAP = new Set(['bench', 'pasture', 'pet', 'lib', 'theme']);
	const rootsOf = (file: string) =>
		new Set(
			[...readFileSync(path.join(ROOT, file), 'utf8').matchAll(/['"]src\/([A-Za-z0-9_-]+)['"]/g)].map(m => m[1]),
		);
	const tsxDirs = [...new Set(
		allSrc
			.filter(f => f.endsWith('.tsx'))
			.map(f => {
				const rel = path.relative(ROOT, f).split(/[\\/]/);
				return rel.length === 1 ? '.' : rel[0];
			})
			.filter(d => d !== '.'),
	)];
	it.each(GUARDS)('%s 覆盖了每个含 JSX 的顶层目录', g => {
		expect(tsxDirs.length).toBeGreaterThan(0);
		const roots = rootsOf(g);
		expect(tsxDirs.filter(d => !roots.has(d) && !KNOWN_GAP.has(d))).toEqual([]);
	});
	it('KNOWN_GAP 不许长出新的漏口', () => {
		expect(tsxDirs.filter(d => !rootsOf(GUARDS[0]).has(d)).sort()).toEqual([...KNOWN_GAP].sort());
	});
	it('门自身可失败：少登记一个目录就报出来', () => {
		const roots = new Set(['components', 'pages']);
		expect(['components', 'pages', 'ui'].filter(d => !roots.has(d))).toEqual(['ui']);
	});
});
