/** 把渲染后的 Markdown DOM 序列化回源码（预览内编辑用）。 */

function isEl(node: Node): node is HTMLElement {
	return node.nodeType === Node.ELEMENT_NODE;
}

function katexTex(el: Element): string | null {
	const ann = el.querySelector('annotation[encoding="application/x-tex"]');
	const tex = ann?.textContent?.trim();
	return tex || null;
}

function fenceWrap(code: string, lang: string): string {
	let n = 3;
	const ticks = code.match(/`+/g);
	if (ticks) {
		n = Math.max(n, ...ticks.map(t => t.length + 1));
	}
	const mark = '`'.repeat(n);
	const body = code.replace(/\n$/, '');
	return lang ? `${mark}${lang}\n${body}\n${mark}` : `${mark}\n${body}\n${mark}`;
}

function serializeInlineChildren(el: Element): string {
	let out = '';
	for (const child of Array.from(el.childNodes)) {
		out += serializeInline(child);
	}
	return out;
}

function serializeInline(node: Node): string {
	if (node.nodeType === Node.TEXT_NODE) {
		return node.textContent ?? '';
	}
	if (!isEl(node)) {
		return '';
	}
	const el = node;
	if (el.tagName === 'BUTTON' || el.tagName === 'SVG' || el.tagName === 'SCRIPT') {
		return '';
	}
	if (el.getAttribute('aria-hidden') === 'true') {
		return '';
	}
	if (el.classList.contains('katex-display')) {
		const tex = katexTex(el);
		if (tex != null) {
			return `$$\n${tex}\n$$`;
		}
	}
	if (el.classList.contains('katex')) {
		const tex = katexTex(el);
		if (tex != null) {
			return `$${tex}$`;
		}
	}
	if (el.dataset.mdSrc != null && el.tagName !== 'A') {
		const alt = el.dataset.mdAlt ?? el.getAttribute('alt') ?? '';
		return `![${alt}](${el.dataset.mdSrc})`;
	}
	const tag = el.tagName;
	if (tag === 'BR') {
		return '  \n';
	}
	if (tag === 'INPUT') {
		return '';
	}
	if (tag === 'STRONG' || tag === 'B') {
		return `**${serializeInlineChildren(el)}**`;
	}
	if (tag === 'EM' || tag === 'I') {
		return `*${serializeInlineChildren(el)}*`;
	}
	if (tag === 'DEL' || tag === 'S') {
		return `~~${serializeInlineChildren(el)}~~`;
	}
	if (tag === 'U') {
		return `<u>${serializeInlineChildren(el)}</u>`;
	}
	if (tag === 'CODE') {
		return `\`${el.textContent ?? ''}\``;
	}
	if (tag === 'A') {
		const href = el.getAttribute('href') || '';
		const text = serializeInlineChildren(el);
		return `[${text}](${href})`;
	}
	if (tag === 'IMG') {
		const alt = el.dataset.mdAlt ?? el.getAttribute('alt') ?? '';
		const src = el.dataset.mdSrc || el.getAttribute('src') || '';
		if (src.startsWith('data:')) {
			return alt ? `![${alt}]` : '';
		}
		return `![${alt}](${src})`;
	}
	const weight = el.style.fontWeight;
	const bold =
		weight === 'bold' ||
		weight === 'bolder' ||
		(parseInt(weight, 10) >= 700 && !Number.isNaN(parseInt(weight, 10)));
	const italic = el.style.fontStyle === 'italic';
	const deco = el.style.textDecoration || el.style.textDecorationLine || '';
	const under = tag === 'U' || /underline/i.test(deco);
	let inner = serializeInlineChildren(el);
	if (bold) {
		inner = `**${inner}**`;
	}
	if (italic) {
		inner = `*${inner}*`;
	}
	if (under && tag !== 'U') {
		inner = `<u>${inner}</u>`;
	}
	return inner;
}

function serializeList(el: HTMLElement, ordered: boolean): string {
	let i = 1;
	const lines: string[] = [];
	for (const child of Array.from(el.children)) {
		if (child.tagName !== 'LI') {
			continue;
		}
		const li = child as HTMLElement;
		const box = li.querySelector(':scope > input[type="checkbox"]');
		let prefix: string;
		if (box instanceof HTMLInputElement) {
			prefix = box.checked ? '- [x] ' : '- [ ] ';
		} else if (ordered) {
			prefix = `${i}. `;
		} else {
			prefix = '- ';
		}
		i += 1;
		const nested: string[] = [];
		const inlineNodes: Node[] = [];
		for (const n of Array.from(li.childNodes)) {
			if (isEl(n) && (n.tagName === 'UL' || n.tagName === 'OL')) {
				nested.push(serializeList(n, n.tagName === 'OL'));
			} else if (isEl(n) && n.tagName === 'P') {
				inlineNodes.push(...Array.from(n.childNodes));
			} else {
				inlineNodes.push(n);
			}
		}
		const text = inlineNodes.map(serializeInline).join('').trim();
		lines.push(prefix + text);
		for (const block of nested) {
			for (const line of block.split('\n')) {
				lines.push(`  ${line}`);
			}
		}
	}
	return lines.join('\n');
}

function cellText(cell: Element): string {
	return serializeInlineChildren(cell).trim().replace(/\|/g, '\\|');
}

function serializeTable(table: Element): string {
	const rows = Array.from(table.querySelectorAll('tr'));
	if (!rows.length) {
		return '';
	}
	const lines: string[] = [];
	rows.forEach((row, idx) => {
		const cells = Array.from(row.querySelectorAll('th, td')).map(cellText);
		lines.push(`| ${cells.join(' | ')} |`);
		if (idx === 0) {
			lines.push(`| ${cells.map(() => '---').join(' | ')} |`);
		}
	});
	return lines.join('\n');
}

function serializeBlock(node: Node): string {
	if (node.nodeType === Node.TEXT_NODE) {
		return (node.textContent ?? '').trim();
	}
	if (!isEl(node)) {
		return '';
	}
	const el = node;
	if (el.hasAttribute('data-md-code')) {
		return fenceWrap(el.dataset.mdCode ?? '', el.dataset.mdFence ?? '');
	}
	if (el.dataset.mdSrc != null && el.tagName !== 'A' && el.tagName !== 'IMG') {
		const alt = el.dataset.mdAlt ?? '';
		return `![${alt}](${el.dataset.mdSrc})`;
	}
	const tag = el.tagName;
	if (tag === 'H1') {
		return `# ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'H2') {
		return `## ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'H3') {
		return `### ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'H4') {
		return `#### ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'H5') {
		return `##### ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'H6') {
		return `###### ${serializeInlineChildren(el).trim()}`;
	}
	if (tag === 'P') {
		return serializeInlineChildren(el).trim();
	}
	if (tag === 'UL') {
		return serializeList(el, false);
	}
	if (tag === 'OL') {
		return serializeList(el, true);
	}
	if (tag === 'BLOCKQUOTE') {
		const inner = serializeBlocks(el);
		if (!inner) {
			return '>';
		}
		return inner
			.split('\n')
			.map(line => (line ? `> ${line}` : '>'))
			.join('\n');
	}
	if (tag === 'HR') {
		return '---';
	}
	if (tag === 'TABLE') {
		return serializeTable(el);
	}
	if (tag === 'PRE') {
		const code = el.querySelector('code');
		const lang =
			(code?.className || '').match(/language-([\w#+.-]+)/)?.[1] || '';
		return fenceWrap(code?.textContent ?? el.textContent ?? '', lang);
	}
	if (el.classList.contains('katex-display')) {
		const tex = katexTex(el);
		if (tex != null) {
			return `$$\n${tex}\n$$`;
		}
	}
	if (tag === 'DIV' || tag === 'SECTION' || tag === 'ARTICLE') {
		const table = el.querySelector(':scope > table');
		if (table) {
			return serializeTable(table);
		}
		const inner = serializeBlocks(el);
		if (inner) {
			return inner;
		}
		const inline = serializeInlineChildren(el).trim();
		return inline;
	}
	return serializeInlineChildren(el).trim();
}

function serializeBlocks(parent: Element): string {
	const parts: string[] = [];
	for (const child of Array.from(parent.childNodes)) {
		const s = serializeBlock(child);
		if (s) {
			parts.push(s);
		}
	}
	return parts.join('\n\n');
}

export function htmlToMarkdown(root: HTMLElement): string {
	try {
		const doc =
			root.matches?.('.xy-md-doc')
				? root
				: (root.querySelector('.xy-md-doc') as HTMLElement | null) ?? root;
		const md = serializeBlocks(doc).trimEnd();
		return md ? `${md}\n` : '';
	} catch {
		return '';
	}
}
