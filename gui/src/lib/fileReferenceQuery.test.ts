import {describe, expect, it} from 'vitest';
import {
	currentFileReferenceResult,
	fileReferenceQueryKey,
} from './fileReferenceQuery';

describe('file reference query state', () => {
	it('binds results to a normalized workspace and query', () => {
		const key = fileReferenceQueryKey(' D:/project ', '  src ');
		expect(key).toBe(fileReferenceQueryKey('D:/project', 'src'));
	});

	it('does not expose results from a previous query or workspace', () => {
		const previous = {key: fileReferenceQueryKey('D:/old', 'src')!, files: ['old.ts']};
		expect(
			currentFileReferenceResult(previous, fileReferenceQueryKey('D:/new', 'src')),
		).toBeNull();
		expect(
			currentFileReferenceResult(previous, fileReferenceQueryKey('D:/old', 'test')),
		).toBeNull();
		expect(currentFileReferenceResult(previous, null)).toBeNull();
	});
});
