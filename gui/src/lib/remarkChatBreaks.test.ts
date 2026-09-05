import {describe, expect, it} from 'vitest';
import {remarkChatBreaks} from './remarkChatBreaks';

type MdNode = {
	type: string;
	value?: string;
	depth?: number;
	children?: MdNode[];
};

function run(tree: MdNode): MdNode {
	const plugin = remarkChatBreaks();
	(plugin as (t: MdNode) => void)(tree);
	return tree;
}

function text(value: string): MdNode {
	return {type: 'text', value};
}

function para(...children: MdNode[]): MdNode {
	return {type: 'paragraph', children};
}

describe('remarkChatBreaks', () => {
	it('splits single newlines in paragraphs into break nodes', () => {
		const tree = run({
			type: 'root',
			children: [para(text('第一行\n第二行'))],
		});
		const p = tree.children![0];
		expect(p.children).toEqual([
			text('第一行'),
			{type: 'break'},
			text('第二行'),
		]);
	});

	it('keeps blank-line separated paragraphs untouched', () => {
		const tree = run({
			type: 'root',
			children: [
				para(text('第一段')),
				{
					type: 'paragraph',
					children: [text('第二段')],
				},
			],
		});
		expect(tree.children![0].children).toEqual([text('第一段')]);
		expect(tree.children![1].children).toEqual([text('第二段')]);
	});

	it('leaves inline code newlines alone', () => {
		const tree = run({
			type: 'root',
			children: [
				para(text('前\n'), {type: 'inlineCode', value: 'a\nb'}, text('后')),
			],
		});
		const p = tree.children![0];
		const code = p.children?.find(node => node.type === 'inlineCode');
		expect(code).toEqual({type: 'inlineCode', value: 'a\nb'});
	});

	it('does not touch non-paragraph parents (headings, code)', () => {
		const tree = run({
			type: 'root',
			children: [
				{type: 'heading', depth: 2, children: [text('标题\n续行')]},
				{type: 'code', value: 'a\nb'},
			],
		});
		expect(tree.children![0].children).toEqual([text('标题\n续行')]);
		expect(tree.children![1].value).toBe('a\nb');
	});

	it('handles multiline soft breaks inside list item paragraphs', () => {
		const tree = run({
			type: 'root',
			children: [
				{
					type: 'listItem',
					children: [para(text('条目一\n条目一续'))],
				},
			],
		});
		const item = tree.children![0];
		expect(item.children![0]!.children).toEqual([
			text('条目一'),
			{type: 'break'},
			text('条目一续'),
		]);
	});

	it('no-op for text without newlines', () => {
		const tree = run({type: 'root', children: [para(text('单行'))]});
		expect(tree.children![0].children).toEqual([text('单行')]);
	});
});
