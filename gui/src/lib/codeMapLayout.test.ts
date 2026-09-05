import {describe, expect, it} from 'vitest';
import {filterGraph, fitLabel, focusFiles, layoutLanes} from './codeMapLayout';

describe('layoutLanes', () => {
	it('places layers as left-to-right columns', () => {
		const laid = layoutLanes(
			[
				{id: 'gui/src/pages', name: 'pages', layer: 'ui', files: 3},
				{id: 'python/engine', name: 'engine', layer: 'engine', files: 8},
			],
			[{from: 'gui/src/pages', to: 'python/engine'}],
			'package',
			420,
		);
		expect(laid.nodes).toHaveLength(2);
		const ui = laid.nodes.find(n => n.id === 'gui/src/pages');
		const eng = laid.nodes.find(n => n.id === 'python/engine');
		expect(ui && eng && eng.x > ui.x).toBe(true);
		expect(laid.edges).toHaveLength(1);
		expect(laid.lanes.map(l => l.layer)).toEqual(['ui', 'engine']);
	});

	it('keeps layer columns compact and bands aligned', () => {
		const laid = layoutLanes(
			[
				{id: 'a.py', name: 'a.py', layer: 'core'},
				{id: 'b.py', name: 'b.py', layer: 'core'},
			],
			[],
			'file',
			480,
		);
		const a = laid.nodes[0]!;
		const b = laid.nodes[1]!;
		expect(b.y - a.y).toBeGreaterThanOrEqual(40);
		expect(laid.lanes).toHaveLength(1);
		expect(laid.lanes[0]!.h).toBeGreaterThan(a.h);
	});

	it('splits tall layers into inner columns', () => {
		const items = Array.from({length: 20}, (_, i) => ({
			id: `f${i}.ts`,
			name: `f${i}.ts`,
			layer: 'ui',
		}));
		const laid = layoutLanes(items, [], 'file', 800);
		const xs = new Set(laid.nodes.map(n => n.x));
		expect(xs.size).toBeGreaterThan(1);
		const maxY = Math.max(...laid.nodes.map(n => n.y));
		const minY = Math.min(...laid.nodes.map(n => n.y));
		expect(maxY - minY).toBeLessThan(20 * 52);
	});
});

describe('fitLabel', () => {
	it('truncates CJK by visual width before ASCII count would', () => {
		const long = '分析XEYO工具调用架构，找溢出';
		const out = fitLabel(long, 18);
		expect(out.endsWith('…')).toBe(true);
		expect(out.length).toBeLessThan(long.length);
	});
});

describe('focusFiles', () => {
	it('keeps the hit and one-hop neighbors', () => {
		const files = [
			{id: 'a.ts', name: 'a.ts', layer: 'ui', pkg: 'gui'},
			{id: 'b.ts', name: 'b.ts', layer: 'ui', pkg: 'gui'},
			{id: 'c.ts', name: 'c.ts', layer: 'core', pkg: 'lib'},
		];
		const {files: picked} = focusFiles(
			files,
			[{from: 'a.ts', to: 'b.ts'}],
			['a.ts'],
		);
		expect(picked.map(f => f.id).sort()).toEqual(['a.ts', 'b.ts']);
	});

	it('matches focus paths by suffix when cwd prefixes differ', () => {
		const files = [
			{id: 'gui/src/a.ts', name: 'a.ts', layer: 'ui', pkg: 'gui/src'},
			{id: 'gui/src/b.ts', name: 'b.ts', layer: 'ui', pkg: 'gui/src'},
		];
		const {files: picked} = focusFiles(files, [], ['src/a.ts']);
		expect(picked.map(f => f.id)).toEqual(['gui/src/a.ts']);
	});
});

describe('filterGraph', () => {
	it('filters by id or name', () => {
		const items = [
			{id: 'python/engine', name: 'engine', layer: 'engine'},
			{id: 'gui/src/pages', name: 'pages', layer: 'ui'},
		];
		expect(filterGraph(items, 'engine')).toHaveLength(1);
		expect(filterGraph(items, '')).toHaveLength(2);
	});
});
