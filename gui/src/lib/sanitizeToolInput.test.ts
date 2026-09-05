import {describe, expect, it} from 'vitest';
import {
	formatToolInputForUi,
	sanitizeToolInputForUi,
} from './sanitizeToolInput';

describe('sanitizeToolInputForUi', () => {
	it('leaves small Write payloads intact', () => {
		const input = {file_path: 'a.txt', content: 'hi'};
		expect(sanitizeToolInputForUi(input)).toBe(input);
	});

	it('truncates large Write content and keeps line count', () => {
		const content = `${'line\n'.repeat(200)}end`;
		const out = sanitizeToolInputForUi({
			file_path: 'D:/big.ts',
			content,
		}) as Record<string, unknown>;
		expect(String(out.content).length).toBeLessThan(content.length);
		expect(out._content_lines).toBe(content.split('\n').length);
		expect(formatToolInputForUi({file_path: 'D:/big.ts', content})).toContain(
			'_content_lines',
		);
	});
});
