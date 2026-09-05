import {visitParents, SKIP} from 'unist-util-visit-parents';
import {fadeOpacityForOffset} from './fadeRamp';

const SKIP_TAGS = new Set(['pre', 'code', 'svg', 'math', 'annotation']);

/** 这些标签下不能放 span（表格结构空白等）。 */
const SKIP_PARENT_TAGS = new Set([
	'table',
	'thead',
	'tbody',
	'tfoot',
	'tr',
	'pre',
	'code',
	'svg',
	'math',
]);

type HastText = {type: 'text'; value: string};
type HastElement = {
	type: 'element';
	tagName: string;
	properties?: Record<string, unknown>;
	children: Array<HastText | HastElement>;
};
type HastRoot = {type: 'root'; children: Array<HastText | HastElement>};
type HastNode = HastText | HastElement | HastRoot;

type TextHit = {
	node: HastText;
	parent: HastElement | HastRoot;
	index: number;
};

export type TailFadeBlockPlan = {
	/** 本 block 可见文本末尾应渐变的码点数（已按全局尾部窗口裁切）。 */
	fadeCount: number;
};

function isSkippableAncestor(ancestors: HastNode[]): boolean {
	return ancestors.some(
		a => a.type === 'element' && SKIP_TAGS.has((a as HastElement).tagName),
	);
}

/**
 * 按源码 block 切分，计算每个 block 落在「全文末尾 window 码点」内的渐变长度。
 * 解决「只挂 lastIndex → 只剩一行有渐变」。
 */
export function planTailFadeByBlocks(
	blocks: string[],
	windowSize: number,
): TailFadeBlockPlan[] {
	const window = Math.max(0, Math.floor(windowSize));
	const lens = blocks.map(b => Array.from(b).length);
	const total = lens.reduce((a, b) => a + b, 0);
	let start = 0;
	return lens.map(len => {
		const end = start + len;
		const charsAfter = total - end;
		const fadeCount =
			window <= 0 ? 0 : Math.max(0, Math.min(len, window - charsAfter));
		start = end;
		return {fadeCount};
	});
}

/**
 * 流式末尾渐变：末尾 fadeCount 码点逐字包 span 设透明度。
 * 透明度不改字形宽度、不产生 background-clip 裁剪层；span 边界不是换行点，
 * 配合 .xy-streamdown-live 关闭 kerning/连字，跨行/逐帧推进都不引起抖动。
 * fadeCount 由 planTailFadeByBlocks 按全局窗口分配，逐字透明度按距全文末尾偏移取值。
 */
export function createRehypeTailFade(fadeCountInput: number) {
	const fadeCount = Math.max(0, Math.floor(fadeCountInput));
	return function rehypeTailFade() {
		return (tree: HastRoot) => {
			if (fadeCount <= 0) {
				return;
			}

			const hits: TextHit[] = [];
			visitParents(tree as never, 'text', (node: HastText, ancestors: HastNode[]) => {
				if (isSkippableAncestor(ancestors)) {
					return SKIP;
				}
				if (!node.value || !/\S/.test(node.value)) {
					return;
				}
				const parent = ancestors[ancestors.length - 1] as
					| HastElement
					| HastRoot
					| undefined;
				if (!parent || !('children' in parent) || !parent.children) {
					return;
				}
				if (
					parent.type === 'element' &&
					SKIP_PARENT_TAGS.has(parent.tagName)
				) {
					return;
				}
				const index = parent.children.indexOf(node);
				if (index < 0) {
					return;
				}
				hits.push({node, parent, index});
			});

			if (hits.length === 0) {
				return;
			}

			let remaining = fadeCount;
			for (let h = hits.length - 1; h >= 0 && remaining > 0; h -= 1) {
				const hit = hits[h];
				if (!hit) {
					continue;
				}
				const points = Array.from(hit.node.value);
				if (points.length === 0) {
					continue;
				}

				const take = Math.min(remaining, points.length);
				const solidEnd = points.length - take;
				const next: Array<HastText | HastElement> = [];

				if (solidEnd > 0) {
					next.push({
						type: 'text',
						value: points.slice(0, solidEnd).join(''),
					});
				}

				for (let j = 0; j < take; j += 1) {
					const fromEnd = remaining - 1 - j;
					next.push({
						type: 'element',
						tagName: 'span',
						properties: {
							className: ['xy-char'],
							style: `opacity:${fadeOpacityForOffset(fromEnd, fadeCount).toFixed(3)}`,
						},
						children: [
							{type: 'text', value: points[solidEnd + j]},
						],
					});
				}

				hit.parent.children.splice(hit.index, 1, ...next);
				remaining -= take;
			}
		};
	};
}
