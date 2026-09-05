import {describe, expect, it} from 'vitest';
import {buildRollbackDiffTree, diffLineStats, relativeRollbackPath} from './rollbackDiffTree';

describe('rollbackDiffTree', () => {
	it('builds nested directory nodes with file diff entries', () => {
		const tree = buildRollbackDiffTree(
			[
				{
					operation_id: 'op1',
					path: 'D:/proj/src/a.ts',
					after_hash: 'h1',
					inverse_kind: 'restore_snapshot',
					preview_diff: '--- a/a.ts\n+++ b/a.ts\n-old\n+new',
				},
				{
					operation_id: 'op2',
					path: 'D:/proj/readme.md',
					after_hash: null,
					inverse_kind: 'delete_file',
					preview_diff: '--- a/readme.md\n+++ b/readme.md\n-hello',
				},
			],
			'D:/proj',
		);
		expect(tree).toHaveLength(2);
		const srcDir = tree.find(node => node.type === 'dir' && node.name === 'src');
		expect(srcDir?.type).toBe('dir');
		if (srcDir?.type === 'dir') {
			expect(srcDir.children[0]?.type).toBe('file');
		}
	});

	it('counts diff line stats', () => {
		expect(
			diffLineStats('--- a\n+++ b\n-old\n+new\n context'),
		).toEqual({add: 1, del: 1});
	});

	it('strips workspace root from paths', () => {
		expect(relativeRollbackPath('D:/proj/src/x.ts', 'D:/proj')).toBe('src/x.ts');
	});
});
