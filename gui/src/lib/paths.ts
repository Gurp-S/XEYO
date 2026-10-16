import {normalizePath, parentDir} from './fsPathOperations';

export {joinFsPath, normalizePath, parentDir} from './fsPathOperations';

export function samePath(a: string, b: string): boolean {
	const na = normalizePath(a);
	const nb = normalizePath(b);
	return Boolean(na) && na === nb;
}

/** 文件夹路径的 basename（`D:\foo\bar` → `bar`）。 */
export function folderName(path: string): string {
	const norm = path.trim().replace(/[/\\]+$/, '');
	const parts = norm.split(/[/\\]/).filter(Boolean);
	return parts[parts.length - 1] || norm || '工作区';
}

export function uniqueParentDirs(paths: string[]): string[] {
	const seen = new Set<string>();
	const out: string[] = [];
	for (const p of paths) {
		const parent = parentDir(p);
		const key = normalizePath(parent);
		if (!key || seen.has(key)) {
			continue;
		}
		seen.add(key);
		out.push(parent);
	}
	return out;
}

/** 像本地绝对路径（回车可直接打开）。 */
export function looksLikeFsPath(query: string): boolean {
	const t = query.trim();
	if (!t) {
		return false;
	}
	if (/^[a-zA-Z]:[\\/]/.test(t)) {
		return true;
	}
	if (t.startsWith('/') || t.startsWith('\\\\')) {
		return true;
	}
	return false;
}
