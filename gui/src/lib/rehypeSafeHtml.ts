import {raw} from 'hast-util-raw';
import {visit, SKIP, CONTINUE} from 'unist-util-visit';
import rehypeRaw from 'rehype-raw';

/**
 * 流式 Markdown 的原始 HTML 安全渲染：
 * markdown 里的原始 HTML 以 {type:'raw'} 节点存在，这里逐个用
 * hast-util-raw 解析成 hast 子树，经白名单过滤后拼回原位。
 * markdown 自身生成的元素（标题/列表/表格等）不经过白名单，不受影响。
 *
 * 导出的数组末尾保留 rehype-raw 本体：streamdown 通过数组中是否含有
 * rehype-raw（恒等判断）来决定是否跳过其自带的「html→转义文本」插件；
 * 由于本插件已消费全部 raw 节点，排在后面的 rehype-raw 实际为空跑。
 *
 * 白名单：纯展示标签；属性仅允许 div/span 的 style 与 details 的 open；
 * script/style/iframe 等危险标签连子树一起丢弃；未知标签解包保留内容。
 */

const ALLOWED_TAGS = new Set([
	'div',
	'span',
	'u',
	'b',
	'i',
	'em',
	'strong',
	'br',
	'hr',
	'details',
	'summary',
	'sub',
	'sup',
	'mark',
	'kbd',
	'p',
]);

const STYLE_TAGS = new Set(['div', 'span']);

/** 连子树一起丢弃的标签（解包会让 script/style 内容变成可见文本）。 */
const DROP_TAGS = new Set([
	'script',
	'style',
	'iframe',
	'object',
	'embed',
	'link',
	'meta',
	'base',
	'title',
]);

type HastNode = {
	type: string;
	value?: string;
	tagName?: string;
	properties?: Record<string, unknown>;
	children?: HastNode[];
};

function sanitizeElement(node: HastNode): void {
	if (node.properties) {
		for (const key of Object.keys(node.properties)) {
			const keep =
				key === 'style'
					? STYLE_TAGS.has(node.tagName ?? '')
					: key === 'open' && node.tagName === 'details';
			if (!keep) {
				delete node.properties[key];
			}
		}
	}
	for (const child of node.children ?? []) {
		sanitizeElement(child);
	}
}

/** 对 raw 解析出的子树做白名单处理：危险标签删子树、未知标签解包。 */
function filterParsedTree(node: HastNode): void {
	const kept: HastNode[] = [];
	for (const child of node.children ?? []) {
		if (child.type !== 'element') {
			kept.push(child);
			continue;
		}
		const tag = child.tagName ?? '';
		if (DROP_TAGS.has(tag)) {
			continue;
		}
		filterParsedTree(child);
		if (!ALLOWED_TAGS.has(tag)) {
			// 解包：保留子内容，去掉未知标签本身
			kept.push(...(child.children ?? []));
			continue;
		}
		sanitizeElement(child);
		kept.push(child);
	}
	node.children = kept;
}

function rehypeSafeHtmlFilter() {
	// unified 插件约定：本函数是 attacher，必须返回 transformer
	return (tree: unknown) => {
		visit(
			tree as never,
			'raw',
			(node: unknown, index: number | null, parent: unknown) => {
				const rawNode = node as HastNode;
				const p = parent as {children: HastNode[]} | null | undefined;
				if (!p || typeof index !== 'number' || !rawNode.value) {
					return CONTINUE;
				}
				const parsed = raw({
					type: 'root',
					children: [{type: 'raw', value: rawNode.value}],
				}) as HastNode;
				filterParsedTree(parsed);
				p.children.splice(index, 1, ...(parsed.children ?? []));
				return [SKIP, index];
			},
		);
	};
}

/** 数组形式供 rehypePlugins 使用（顺序有讲究，见文件头注释）。 */
export const rehypeSafeHtml = [rehypeSafeHtmlFilter, rehypeRaw];
