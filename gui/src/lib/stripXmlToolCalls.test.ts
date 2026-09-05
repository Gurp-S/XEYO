import {describe, expect, it} from 'vitest';
import {
	looksLikeRawToolMarkup,
	stripXmlToolCallsForDisplay,
} from './stripXmlToolCalls';

describe('stripXmlToolCallsForDisplay', () => {
	it('removes complete tool_call blocks', () => {
		const raw = `现在修改按钮：
<tool_call>Edit
<arg_key>file_path</arg_key>
<arg_value>D:\\lea\\Sidebar.tsx</arg_value>
</tool_call>
继续说明。`;
		expect(stripXmlToolCallsForDisplay(raw)).toBe(
			'现在修改按钮：\n\n继续说明。',
		);
	});

	it('strips unclosed streaming tool_call', () => {
		const raw = `前言 <tool_call>Edit <arg_key>file_path</arg_key> <arg_value>foo`;
		expect(stripXmlToolCallsForDisplay(raw).trim()).toBe('前言');
	});

	it('detects garbled tool markup', () => {
		expect(
			looksLikeRawToolMarkup(
				'<tool_call>Edit <arg_key>x</arg_key><arg_value>y</arg_value></tool_call>',
			),
		).toBe(true);
		expect(looksLikeRawToolMarkup('普通助手回复')).toBe(false);
	});
});
