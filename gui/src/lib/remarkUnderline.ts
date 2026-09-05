import {visit} from 'unist-util-visit';

type MdNode = {
	type: string;
	value?: string;
	children?: MdNode[];
	data?: {hName?: string};
};

const UNDERLINE_RE = /<u>([\s\S]*?)<\/u>/gi;
const OPEN_U = /^<u>\s*$/i;
const CLOSE_U = /^<\/u>\s*$/i;

function underlineNode(children: MdNode[]): MdNode {
	return {
		type: 'underline',
		data: {hName: 'u'},
		children,
	};
}

/** 把源码里成对的 `<u>…</u>`（remark 会拆成三个节点）收成可渲染节点。 */
export function wrapUnderlineHtmlPairs(parent: MdNode): void {
	const kids = parent.children;
	if (!kids?.length) {
		return;
	}
	for (let i = 0; i < kids.length; i += 1) {
		const n = kids[i];
		if (n?.type !== 'html' || !OPEN_U.test(n.value ?? '')) {
			continue;
		}
		let close = -1;
		for (let j = i + 1; j < kids.length; j += 1) {
			if (kids[j]?.type === 'html' && CLOSE_U.test(kids[j]?.value ?? '')) {
				close = j;
				break;
			}
		}
		if (close < 0) {
			continue;
		}
		const inner = kids.slice(i + 1, close);
		kids.splice(i, close - i + 1, underlineNode(inner));
	}
}

/** 单个 html/text 节点里完整的 `<u>…</u>`。 */
export function splitUnderlineHtml(value: string): MdNode[] | null {
	UNDERLINE_RE.lastIndex = 0;
	if (!UNDERLINE_RE.test(value)) {
		return null;
	}
	UNDERLINE_RE.lastIndex = 0;
	const parts: MdNode[] = [];
	let last = 0;
	let m: RegExpExecArray | null;
	while ((m = UNDERLINE_RE.exec(value))) {
		if (m.index > last) {
			parts.push({type: 'text', value: value.slice(last, m.index)});
		}
		parts.push(underlineNode([{type: 'text', value: m[1] ?? ''}]));
		last = m.index + m[0].length;
	}
	if (last < value.length) {
		parts.push({type: 'text', value: value.slice(last)});
	}
	return parts;
}

export function remarkUnderline() {
	return (tree: MdNode) => {
		visit(tree, (node: MdNode) => {
			if (node.children) {
				wrapUnderlineHtmlPairs(node);
			}
		});
		visit(tree, (node: MdNode, index, parent) => {
			const parentNode = parent as MdNode | null | undefined;
			if (!parentNode?.children || index == null) {
				return;
			}
			if (node.type !== 'text' && node.type !== 'html') {
				return;
			}
			const parts = splitUnderlineHtml(node.value ?? '');
			if (!parts) {
				return;
			}
			parentNode.children.splice(index, 1, ...parts);
			return index + parts.length;
		});
	};
}
