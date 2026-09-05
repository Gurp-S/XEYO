import {describe, expect, it} from 'vitest';
import {splitUnderlineHtml, wrapUnderlineHtmlPairs} from './remarkUnderline';

describe('splitUnderlineHtml', () => {
	it('turns <u> into a renderable underline node', () => {
		const parts = splitUnderlineHtml('测两轮前 <u>测两轮</u> 后');
		expect(parts).toEqual([
			{type: 'text', value: '测两轮前 '},
			{
				type: 'underline',
				data: {hName: 'u'},
				children: [{type: 'text', value: '测两轮'}],
			},
			{type: 'text', value: ' 后'},
		]);
	});

	it('ignores tags with attributes', () => {
		expect(splitUnderlineHtml('<u onclick="x">no</u>')).toBeNull();
	});

	it('returns null when there is no underline html', () => {
		expect(splitUnderlineHtml('plain **bold**')).toBeNull();
	});

	it('wraps remark-split <u> / text / </u> siblings', () => {
		const parent = {
			type: 'paragraph',
			children: [
				{type: 'text', value: '请看'},
				{type: 'html', value: '<u>'},
				{type: 'text', value: '测两轮'},
				{type: 'html', value: '</u>'},
				{type: 'text', value: '这里'},
			],
		};
		wrapUnderlineHtmlPairs(parent);
		expect(parent.children).toEqual([
			{type: 'text', value: '请看'},
			{
				type: 'underline',
				data: {hName: 'u'},
				children: [{type: 'text', value: '测两轮'}],
			},
			{type: 'text', value: '这里'},
		]);
	});
});
