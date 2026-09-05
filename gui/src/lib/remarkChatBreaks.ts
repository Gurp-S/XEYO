import {visit} from 'unist-util-visit';

type MdNode = {
	type: string;
	value?: string;
	children?: MdNode[];
};

/**
 * 聊天口径的单换行处理：段落内「单个 \n」转成硬换行（break → <br>）。
 *
 * 聊天输入不是 Markdown 文档流 —— 用户敲一次回车就期望换行，
 * 而 CommonMark 会把段落内单换行折叠成空格。这里在 mdast 层把
 * paragraph 里的 text 节点按 \n 拆开、插入 break 节点；
 * 代码块（inlineCode/code）、表格单元格、标题不受影响。
 * 空行（\n\n）本来就是段落边界， remark 已断段，无需处理。
 *
 * 以「插件工厂」形式传给 unified（.use(remarkChatBreaks)），
 * 不要传调用后的返回值 —— unified 会把返回的 transformer 当 attacher 再调一次。
 */
export function remarkChatBreaks() {
	return (tree: MdNode) => {
		visit(tree, (node: MdNode, index, parent) => {
			const parentNode = parent as MdNode | null | undefined;
			if (!parentNode?.children || index == null) {
				return;
			}
			if (parentNode.type !== 'paragraph' || node.type !== 'text') {
				return;
			}
			const value = node.value ?? '';
			if (!value.includes('\n')) {
				return;
			}
			const segments = value.split('\n');
			const parts: MdNode[] = [];
			for (let i = 0; i < segments.length; i += 1) {
				if (i > 0) {
					parts.push({type: 'break'});
				}
				const seg = segments[i] ?? '';
				if (seg) {
					parts.push({type: 'text', value: seg});
				}
			}
			if (parts.length === 0) {
				return;
			}
			parentNode.children.splice(index, 1, ...parts);
			return index + parts.length;
		});
	};
}
