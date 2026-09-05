/** 规范化路径以便相等性比较（Windows 友好）。 */
export function normalizePath(path: string): string {
	let p = path.trim().replace(/\\/g, '/');
	// 去除对话框 / API 返回的 Win32 扩展长度 / 设备前缀。
	if (p.toLowerCase().startsWith('//?/')) {
		p = p.slice(4);
	} else if (p.toLowerCase().startsWith('/?/')) {
		p = p.slice(3);
	}
	// 合并重复分隔符；去除尾部斜杠（保留驱动器根 "d:"）。
	p = p.replace(/\/+/g, '/').replace(/\/+$/, '');
	return p.toLowerCase();
}

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

function usesWindowsSep(path: string): boolean {
	return path.includes('\\') || /^[a-zA-Z]:/.test(path.trim());
}

/** 拼接本地绝对路径（保留父路径的分隔风格）。 */
export function joinFsPath(parent: string, child: string): string {
	const root = parent.trim().replace(/[/\\]+$/, '');
	const name = child.trim().replace(/^[/\\]+/, '');
	if (!root) {
		return name;
	}
	if (!name) {
		return parent.trim() || root;
	}
	const sep = usesWindowsSep(parent) ? '\\' : '/';
	return `${root}${sep}${name}`;
}

/** 父目录。`D:\lea\xyai` → `D:\lea`；盘符根返回 `D:\`。 */
export function parentDir(path: string): string {
	const raw = path.trim();
	const trimmed = raw.replace(/[/\\]+$/, '');
	const idx = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
	if (idx < 0) {
		return trimmed;
	}
	const parent = trimmed.slice(0, idx);
	if (/^[a-zA-Z]:$/i.test(parent)) {
		return usesWindowsSep(raw) ? `${parent}\\` : `${parent}/`;
	}
	return parent;
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
