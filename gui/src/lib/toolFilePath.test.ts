import {
	filePathFromTool,
	previewPathMatches,
	sameWorkspacePath,
} from '@/lib/toolFilePath';

describe('filePathFromTool', () => {
	it('reads path from Write input', () => {
		expect(
			filePathFromTool('Write', JSON.stringify({path: 'docs/a.md'})),
		).toBe('docs/a.md');
	});

	it('reads file_path from Edit input', () => {
		expect(
			filePathFromTool('Edit', JSON.stringify({file_path: 'src\\app.ts'})),
		).toBe('src/app.ts');
	});

	it('supports normalized file mutation tool names', () => {
		expect(
			filePathFromTool('Write_File', JSON.stringify({filename: 'src/a.ts'})),
		).toBe('src/a.ts');
		expect(
			filePathFromTool('ApplyPatch', JSON.stringify({file_path: 'src/b.ts'})),
		).toBe('src/b.ts');
		expect(
			filePathFromTool(
				'NotebookEdit',
				JSON.stringify({notebook_path: 'n.ipynb'}),
			),
		).toBe('n.ipynb');
	});

	it('ignores other tools', () => {
		expect(filePathFromTool('Read', JSON.stringify({path: 'a.ts'}))).toBeNull();
	});
});

describe('sameWorkspacePath', () => {
	it('compares slash-normalized paths', () => {
		expect(sameWorkspacePath('src\\a.ts', 'src/a.ts')).toBe(true);
	});
});

describe('previewPathMatches', () => {
	it('matches relative and absolute with slash boundary', () => {
		expect(previewPathMatches('src/a.ts', 'D:/proj/src/a.ts')).toBe(true);
		expect(previewPathMatches('src/a.ts', 'src/a.ts')).toBe(true);
		expect(previewPathMatches('a.ts', 'extra.ts')).toBe(false);
	});
});
