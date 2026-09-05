/** 从 Write/Edit 工具参数里取出工作区相对路径。 */
const MUTATING_TOOL_NAMES = new Set([
	'write',
	'edit',
	'writefile',
	'editfile',
	'filewrite',
	'fileedit',
	'applypatch',
	'patch',
	'replacefile',
	'notebookedit',
]);

export function filePathFromTool(
	name: string,
	input: string | undefined,
): string | null {
	const normalizedName = (name || '').trim().toLowerCase().replace(/[\s_-]+/g, '');
	if (!MUTATING_TOOL_NAMES.has(normalizedName)) {
		return null;
	}
	const raw = (input || '').trim();
	if (!raw) {
		return null;
	}
	try {
		const parsed = JSON.parse(raw) as unknown;
		if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
			return null;
		}
		const row = parsed as Record<string, unknown>;
			const path =
				row.path ??
				row.file_path ??
				row.filePath ??
				row.notebook_path ??
				row.notebookPath ??
				row.filename ??
				row.file_name;
			if (typeof path === 'string' && path.trim()) {
			return path.trim().replace(/\\/g, '/');
		}
	} catch {
		return null;
	}
	return null;
}

export function sameWorkspacePath(a: string | null | undefined, b: string): boolean {
	if (!a) {
		return false;
	}
	return a.replace(/\\/g, '/').toLowerCase() === b.replace(/\\/g, '/').toLowerCase();
}

/**
 * 预览路径是否对应工具写出的路径。
 * 允许相对 ↔ 绝对（`src/a.ts` vs `D:/proj/src/a.ts`），但要求以 `/` 为边界，
 * 避免 `a.ts` 误匹配 `extra.ts`。
 */
export function previewPathMatches(
	selected: string | null | undefined,
	written: string,
): boolean {
	if (!selected) {
		return false;
	}
	if (sameWorkspacePath(selected, written)) {
		return true;
	}
	const a = selected.replace(/\\/g, '/').toLowerCase();
	const b = written.replace(/\\/g, '/').toLowerCase();
	return a.endsWith(`/${b}`) || b.endsWith(`/${a}`);
}
