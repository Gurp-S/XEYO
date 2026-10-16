/** 本地路径的词法操作：保留 POSIX 根、盘符根和 UNC 共享根，不访问文件系统。 */

function slashPath(path: string): string {
	let value = path.trim().replace(/\\/g, '/');
	const extended = /^\/{1,2}\?\//.test(value);
	value = value.replace(/^\/{1,2}\?\//, '');
	if (extended && /^UNC\//i.test(value)) {
		value = `//${value.slice(4)}`;
	}
	const prefix = /^\/\/[^/]+\/[^/]+/.test(value) ? '//' : '';
	return prefix + value.slice(prefix.length).replace(/\/+/g, '/');
}

function rootLength(path: string): number {
	const share = /^\/\/[^/]+\/[^/]+(?:\/|$)/.exec(path);
	if (share) return share[0].length;
	if (/^[a-z]:\//i.test(path)) return 3;
	return path.startsWith('/') ? 1 : 0;
}

/** 路径比较沿用 Windows 的大小写无关语义；根目录仍有有效的比较键。 */
export function normalizePath(path: string): string {
	const value = slashPath(path);
	return (value === '/' ? value : value.replace(/\/+$/, '')).toLowerCase();
}

/** 拼接子路径并保留父路径的分隔符风格。 */
export function joinFsPath(parent: string, child: string): string {
	const raw = parent.trim();
	const name = child.trim().replace(/^[/\\]+/, '');
	if (!raw) return name;
	if (!name) return raw;
	const separator = raw.includes('\\') || /^[a-z]:/i.test(raw) ? '\\' : '/';
	const base = raw.replace(/[/\\]+$/, '');
	return `${base}${separator}${name}`;
}

/** 返回父目录；POSIX、盘符和 UNC 共享根的父目录仍为根本身。 */
export function parentDir(path: string): string {
	const raw = path.trim();
	const slashed = raw.replace(/\\/g, '/');
	// 扩展路径的前缀属于根，避免将 UNC 的共享名当作普通目录向上越过。
	const prefix = /^\/{1,2}\?\//.exec(slashed)?.[0] ?? '';
	const body = slashed.slice(prefix.length);
	const extendedUnc = prefix && /^UNC\//i.test(body);
	const canonical = extendedUnc ? `//${body.slice(4)}` : body;
	const rootSize = rootLength(canonical) + prefix.length + (extendedUnc ? 2 : 0);
	const end = Math.max(rootSize, raw.replace(/[/\\]+$/, '').length);
	const trimmed = raw.slice(0, end);
	const separatorAt = Math.max(trimmed.lastIndexOf('/'), trimmed.lastIndexOf('\\'));
	if (separatorAt < 0) return trimmed;
	return trimmed.slice(0, Math.max(rootSize, separatorAt));
}
