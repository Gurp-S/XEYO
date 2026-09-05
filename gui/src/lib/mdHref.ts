export type MdHref =
	| {kind: 'external'; href: string}
	| {kind: 'hash'; id: string}
	| {kind: 'local'; path: string; hash?: string}
	| {kind: 'unsafe'};

function splitHash(raw: string): {path: string; hash?: string} {
	const i = raw.indexOf('#');
	if (i < 0) {
		return {path: raw};
	}
	const path = raw.slice(0, i);
	const hash = decodeURIComponent(raw.slice(i + 1));
	return hash ? {path, hash} : {path};
}

export function joinWorkspace(fromFile: string, rel: string): string {
	const href = rel.replace(/\\/g, '/').replace(/^\.\//, '');
	if (/^[a-zA-Z]:\//.test(href) || href.startsWith('//')) {
		return href;
	}
	const base = fromFile.replace(/\\/g, '/');
	const dir = base.includes('/') ? base.slice(0, base.lastIndexOf('/')) : '';
	const joined = href.startsWith('/')
		? href.replace(/^\/+/, '')
		: dir
			? `${dir}/${href}`
			: href;
	const out: string[] = [];
	for (const part of joined.split('/')) {
		if (!part || part === '.') {
			continue;
		}
		if (part === '..') {
			out.pop();
			continue;
		}
		out.push(part);
	}
	return out.join('/');
}

export function resolveMdHref(
	href: string | undefined,
	fromFile = '',
): MdHref {
	if (!href) {
		return {kind: 'unsafe'};
	}
	const raw = href.trim();
	if (!raw) {
		return {kind: 'unsafe'};
	}
	if (/^(javascript|data|vbscript):/i.test(raw)) {
		return {kind: 'unsafe'};
	}
	if (/^(https?:|mailto:)/i.test(raw)) {
		return {kind: 'external', href: raw};
	}
	if (raw.startsWith('#')) {
		return {kind: 'hash', id: decodeURIComponent(raw.slice(1))};
	}
	const {path, hash} = splitHash(raw);
	if (!path) {
		return hash ? {kind: 'hash', id: hash} : {kind: 'unsafe'};
	}
	let decoded = path;
	try {
		decoded = decodeURIComponent(path);
	} catch {
		decoded = path;
	}
	return {kind: 'local', path: joinWorkspace(fromFile, decoded), hash};
}
