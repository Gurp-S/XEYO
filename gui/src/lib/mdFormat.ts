export type MdFormatKind =
	| 'bold'
	| 'italic'
	| 'underline'
	| 'strike'
	| 'link'
	| 'ol'
	| 'ul'
	| 'quote'
	| 'code'
	| 'codeblock';

const INLINE_MARKS: Partial<Record<MdFormatKind, [string, string][]>> = {
	bold: [
		['**', '**'],
		['__', '__'],
	],
	italic: [
		['*', '*'],
		['_', '_'],
	],
	underline: [['<u>', '</u>']],
	strike: [['~~', '~~']],
	code: [['`', '`']],
};

function wrapLines(text: string, prefix: string): string {
	return text.split('\n').map(line => `${prefix}${line}`).join('\n');
}

function normalizeNeedle(selected: string): string {
	return selected.replace(/\r\n/g, '\n').replace(/\u00a0/g, ' ').trim();
}

function skipMarkup(src: string, i: number): number {
	if (src.startsWith('```', i)) {
		const end = src.indexOf('```', i + 3);
		return end < 0 ? src.length : end + 3;
	}
	if (src.startsWith('**', i) || src.startsWith('__', i) || src.startsWith('~~', i)) {
		return i + 2;
	}
	if (src.startsWith('<u>', i)) {
		return i + 3;
	}
	if (src.startsWith('</u>', i)) {
		return i + 4;
	}
	if (src.startsWith('](', i)) {
		const close = src.indexOf(')', i + 2);
		return close < 0 ? src.length : close + 1;
	}
	if (src.startsWith('![', i)) {
		return i + 2;
	}
	if (src[i] === '[' || src[i] === '*' || src[i] === '_' || src[i] === '`') {
		return i + 1;
	}
	const atLine = i === 0 || src[i - 1] === '\n';
	if (atLine) {
		if (src[i] === '#') {
			let j = i;
			while (src[j] === '#') {
				j += 1;
			}
			if (src[j] === ' ' || src[j] === '\t') {
				return j + 1;
			}
		}
		if (src.startsWith('- ', i) || src.startsWith('> ', i)) {
			return i + 2;
		}
		const ol = /^\d+\.\s/.exec(src.slice(i));
		if (ol) {
			return i + ol[0].length;
		}
	}
	return i;
}

function takeVisible(
	src: string,
	start: number,
	count: number,
): {idx: number; len: number; text: string} | null {
	let i = start;
	let text = '';
	let visStart = -1;
	while (i < src.length && text.length < count) {
		const next = skipMarkup(src, i);
		if (next > i) {
			i = next;
			continue;
		}
		if (visStart < 0) {
			visStart = i;
		}
		text += src[i]!;
		i += 1;
	}
	if (text.length < count || visStart < 0) {
		return null;
	}
	return {idx: visStart, len: i - visStart, text};
}

function findNeedle(src: string, selected: string): {idx: number; len: number} | null {
	const raw = selected.replace(/\r\n/g, '\n').replace(/\u00a0/g, ' ');
	if (raw) {
		const idx = src.indexOf(raw);
		if (idx >= 0) {
			return {idx, len: raw.length};
		}
	}
	const needle = normalizeNeedle(selected);
	if (!needle) {
		return null;
	}
	const idx = src.indexOf(needle);
	if (idx >= 0) {
		return {idx, len: needle.length};
	}
	const collapsed = needle.replace(/\s+/g, ' ');
	const limit = Math.min(src.length, 400_000);
	for (let i = 0; i < limit; i += 1) {
		const got = takeVisible(src, i, collapsed.length);
		if (got && got.text.replace(/\s+/g, ' ') === collapsed) {
			return {idx: got.idx, len: got.len};
		}
	}
	return null;
}

function isMarked(
	src: string,
	idx: number,
	len: number,
	pre: string,
	suf: string,
): boolean {
	if (idx < pre.length) {
		return false;
	}
	if (!src.startsWith(pre, idx - pre.length) || !src.startsWith(suf, idx + len)) {
		return false;
	}
	const before = src[idx - pre.length - 1];
	const after = src[idx + len + suf.length];
	if (pre === '*' && (before === '*' || after === '*')) {
		return false;
	}
	if (pre === '_' && (before === '_' || after === '_')) {
		return false;
	}
	return true;
}

function unwrapInline(
	src: string,
	idx: number,
	len: number,
	kind: MdFormatKind,
): string | null {
	const marks = INLINE_MARKS[kind];
	if (!marks) {
		return null;
	}
	const chunk = src.slice(idx, idx + len);
	for (const [pre, suf] of marks) {
		if (isMarked(src, idx, len, pre, suf)) {
			return (
				src.slice(0, idx - pre.length) +
				chunk +
				src.slice(idx + len + suf.length)
			);
		}
		if (chunk.startsWith(pre) && chunk.endsWith(suf) && chunk.length > pre.length + suf.length) {
			return (
				src.slice(0, idx) +
				chunk.slice(pre.length, chunk.length - suf.length) +
				src.slice(idx + len)
			);
		}
	}
	return null;
}

function linePrefix(kind: MdFormatKind): string | null {
	if (kind === 'ul') {
		return '- ';
	}
	if (kind === 'quote') {
		return '> ';
	}
	return null;
}

function unwrapLines(text: string, kind: MdFormatKind): string | null {
	const lines = text.split('\n');
	if (kind === 'ol') {
		if (!lines.every(line => /^\d+\.\s/.test(line))) {
			return null;
		}
		return lines.map(line => line.replace(/^\d+\.\s/, '')).join('\n');
	}
	const prefix = linePrefix(kind);
	if (!prefix) {
		return null;
	}
	if (!lines.every(line => line.startsWith(prefix) || line === prefix.trimEnd())) {
		return null;
	}
	return lines
		.map(line => (line.startsWith(prefix) ? line.slice(prefix.length) : line))
		.join('\n');
}

export function wrapMarkdownSelection(
	selected: string,
	kind: MdFormatKind,
	href = 'https://',
): string {
	const text = selected;
	const unwrapped = unwrapLines(text, kind);
	if (unwrapped != null) {
		return unwrapped;
	}
	switch (kind) {
		case 'bold':
			return `**${text}**`;
		case 'italic':
			return `*${text}*`;
		case 'underline':
			return `<u>${text}</u>`;
		case 'strike':
			return `~~${text}~~`;
		case 'link':
			return `[${text}](${href.trim() || 'https://'})`;
		case 'ol':
			return text
				.split('\n')
				.map((line, i) => `${i + 1}. ${line.replace(/^\s+/, '')}`)
				.join('\n');
		case 'ul':
			return text
				.split('\n')
				.map(line => `- ${line.replace(/^\s+/, '')}`)
				.join('\n');
		case 'quote':
			return wrapLines(text, '> ');
		case 'code':
			return text.includes('\n') ? `\`\`\`\n${text}\n\`\`\`` : `\`${text}\``;
		case 'codeblock':
			if (text.startsWith('```') && text.endsWith('```')) {
				return text.replace(/^```\w*\n?/, '').replace(/\n?```$/, '');
			}
			return `\`\`\`\n${text}\n\`\`\``;
		default:
			return text;
	}
}

/** 把选区第一次出现替换为格式化后的文本；已有同等标记则取消。找不到则返回 null。 */
export function applyMdFormat(
	source: string,
	selected: string,
	kind: MdFormatKind,
	href?: string,
): string | null {
	const src = source.replace(/\r\n/g, '\n');
	const found = findNeedle(src, selected);
	if (!found) {
		return null;
	}
	const {idx, len} = found;
	const chunk = src.slice(idx, idx + len);
	const undone = unwrapInline(src, idx, len, kind);
	if (undone != null) {
		return undone;
	}
	const wrapped = wrapMarkdownSelection(chunk, kind, href);
	if (wrapped === chunk) {
		return src;
	}
	return src.slice(0, idx) + wrapped + src.slice(idx + len);
}
