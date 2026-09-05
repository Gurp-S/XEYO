import {describe, expect, it} from 'vitest';
import {createRehypeTailFade, planTailFadeByBlocks} from './rehypeTailFade';

describe('planTailFadeByBlocks', () => {
	it('allocates fade across trailing blocks', () => {
		const plans = planTailFadeByBlocks(['aaaa', 'bbbb', 'cccc'], 6);
		expect(plans.map(p => p.fadeCount)).toEqual([0, 2, 4]);
	});

	it('puts all fade on last block when window fits', () => {
		const plans = planTailFadeByBlocks(['hello', 'world'], 3);
		expect(plans.map(p => p.fadeCount)).toEqual([0, 3]);
	});
});

describe('createRehypeTailFade', () => {
	it('wraps last N code points in per-char opacity spans', () => {
		const plugin = createRehypeTailFade(3);
		const tree = {
			type: 'root' as const,
			children: [
				{
					type: 'element' as const,
					tagName: 'p',
					children: [{type: 'text' as const, value: 'Hello'}],
				},
			],
		};
		plugin()(tree);
		const p = tree.children[0];
		expect(p?.type).toBe('element');
		if (p?.type !== 'element') {
			return;
		}
		const nodes = p.children as Array<{
			type: string;
			value?: string;
			properties?: {className?: string[]; style?: string};
			children?: Array<{value: string}>;
		}>;
		expect(nodes[0]).toEqual({type: 'text', value: 'He'});
		const chars = nodes.slice(1);
		expect(chars.map(n => (n.type === 'element' ? n.properties?.className : null)))
			.toEqual([['xy-char'], ['xy-char'], ['xy-char']]);
		expect(chars.map(n => n.children?.[0]?.value ?? ''))
			.toEqual(['l', 'l', 'o']);
		// 透明度沿阅读方向递增（离末尾越近越淡）
		const opacities = chars.map(n =>
			n.type === 'element'
				? Number((n.properties?.style ?? '').replace('opacity:', ''))
				: 0,
		);
		expect(opacities[0]).toBeGreaterThan(opacities[2]);
		expect(opacities[2]).toBeCloseTo(0.12, 2);
		expect(opacities[0]).toBeCloseTo(1, 2);
	});

	it('skips text inside code', () => {
		const plugin = createRehypeTailFade(8);
		const tree = {
			type: 'root' as const,
			children: [
				{
					type: 'element' as const,
					tagName: 'code',
					children: [{type: 'text' as const, value: 'const x'}],
				},
			],
		};
		plugin()(tree);
		const code = tree.children[0];
		expect(code?.type).toBe('element');
		if (code?.type !== 'element') {
			return;
		}
		expect(code.children).toEqual([{type: 'text', value: 'const x'}]);
	});
});
