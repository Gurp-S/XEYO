const FENCE_LINE = /^(?:```|~~~)/;
const LIST_OR_QUOTE_LINE = /^(?: {0,3}(?:[-+*]|\d+[.)])\s+| {0,3}>)/;

/** 一行是否以表格行开头（允许 ≤3 个前导空格 + 竖线）。 */
export function mdPipeRowStart(line: string): boolean {
	return /^[ \t]{0,3}\|/.test(line);
}

/**
 * GFM 分隔行（表头下的 | --- | --- | 行）。
 * 只在已按换行截断的完整行上调用；正在生长的半截行不适用。
 */
export function mdTableDelimiterRow(line: string): boolean {
	const t = line.trim();
	if (!t || !t.includes('|') || !t.includes('-')) {
		return false;
	}
	return (
		/^[ \t]{0,3}\|[ \t]*:?-{1,}:?(?:[ \t]*\|[ \t]*:?-{1,}:?)*[ \t]*\|?[ \t]*$/.test(t) ||
		/^[ \t]{0,3}:?-{1,}(?:[ \t]*\|[ \t]*:?-{1,}:?)+[ \t]*$/.test(t)
	);
}

function countDisplayMathDelimiters(line: string): number {
	let count = 0;
	for (let i = 0; i < line.length - 1; i += 1) {
		if (line[i] === '$' && line[i + 1] === '$') {
			count += 1;
			i += 1;
		}
	}
	return count;
}

export type StreamFence = {
	lang: string;
	code: string;
};

export type StreamTablePending = {
	headers: string[];
	growingHeader: boolean;
};

export type StreamMarkdownParts = {
	head: string;
	live: string;
	fence: StreamFence | null;
	math: string | null;
	table: string | null;
	tablePending: StreamTablePending | null;
};

function parseFenceOpener(firstLine: string): string {
	const lang = firstLine.replace(/^(?:```|~~~)/, '').trim().split(/\s+/)[0];
	return lang || 'text';
}

function parseOpenFence(raw: string): StreamFence {
	const nl = raw.indexOf('\n');
	if (nl === -1) {
		return {lang: parseFenceOpener(raw), code: ''};
	}
	return {
		lang: parseFenceOpener(raw.slice(0, nl)),
		code: raw.slice(nl + 1),
	};
}

/**
 * 判断流式“最后一行”是否为闭合某个结构块的终止符（围栏闭合行、setext 下划线）。
 * 这类行不属于正在生长的正文，必须并入稳定 head，
 * 否则会在流式时露出 ``` 或把标题伪装成普通段落。
 * 表格分隔行不再在此处理 —— 由 scanTrailingTable 的表格状态机统一接管，
 * 否则会把尚未长完的分隔符整段吞进 head 造成行“消失又出现”。
 */
function isStructuralTail(tail: string): boolean {
	const t = tail.trim();
	if (!t) {
		return false;
	}
	if (FENCE_LINE.test(t)) {
		return true;
	}
	if (/^-{3,}$/.test(t) || /^=+$/.test(t)) {
		return true;
	}
	return false;
}

/** 补全未闭合的 ** / ` ，避免流式时露出半截标记。 */
export function balanceInlineMd(s: string): string {
	if (!s) {
		return s;
	}
	let out = s;
	const ticks = (out.match(/`/g) ?? []).length;
	if (ticks % 2 === 1) {
		out += '`';
	}
	// 强调计数前先剔除与强调无关的形态，避免误判出幻影闭合符：
	// 1) 反斜杠转义的记号；2) 行首列表标记（“* item”“1. item”）；
	// 3) 两侧空白的孤立星号（“2 * 3”）；4) 词内下划线（snake_case）。
	const emphasisView = out
		.replace(/\\([*_~`[\]!()#])/g, '_ESC_')
		.replace(/^[ \t]*(?:[-*+]|\d+[.)])[ \t]+/, '')
		.replace(/(^|[ \t])\*(?=[ \t]|$)/g, '$1')
		.replace(/(?<=\w)_(?=\w)/g, '_');
	const bolds = (emphasisView.match(/\*\*/g) ?? []).length;
	if (bolds % 2 === 1) {
		out += '**';
	}
	const stripped = emphasisView.replace(/\*\*/g, '');
	const stars = (stripped.match(/\*/g) ?? []).length;
	if (stars % 2 === 1) {
		out += '*';
	}
	const unders = (emphasisView.match(/_/g) ?? []).length;
	if (unders % 2 === 1) {
		out += '_';
	}
	// 行内强调（* / _ / ~~）和链接括号：流式过程中如果只来了半边，
	// Markdown 渲染器会把左半当作普通字符显示。这里先补成临时闭合，
	// 避免暴露未完成的原始 Markdown 源码。
	const strikePairs = (out.match(/~~/g) ?? []).length;
	if (strikePairs % 2 === 1) {
		out += '~~';
	}
	if (/!?\[[^\]]+\]\([^)]*$/.test(out)) {
		out += ')';
	}
	return out;
}

/**
 * 判断一段“正在生长的当前行”是否含有需要按 Markdown 展示的语法。
 * 纯文字返回 false，可用“逐字淡入”渲染；否则退回 MarkdownView，
 * 避免把 ** / ` / []( 等原始符号当普通字符显示。
 *
 * 块级与行内分开：StreamingMarkdown 对同一 live 行只升不降（粘性），
 * 避免 LiveChars ↔ MarkdownView 来回切导致抖动/露源码。
 */
export function hasStreamBlockSyntax(s: string): boolean {
	if (!s) {
		return false;
	}
	// 含半截 AT标题（只有 #、还没有空格/正文），避免 LiveChars 把 # 当源码露出。
	if (/^\s*(#{1,6})(\s|$)/.test(s)) {
		return true;
	}
	if (/^\s*(> ?|[-*+] |\d+[.)] )/.test(s)) {
		return true;
	}
	if (/^\s*(---|\*\*\*|___)\s*$/.test(s)) {
		return true;
	}
	return false;
}

export function hasStreamInlineSyntax(s: string): boolean {
	if (!s) {
		return false;
	}
	if (s.includes('**') || s.includes('`') || s.includes('~~')) {
		return true;
	}
	if (/\[[^\]]+\]\([^)]*$/.test(s) || /!?\[[^\]]*\]\([^)]*\)?/.test(s)) {
		return true;
	}
	/* 去掉行首列表标记再查强调，避免 “* 项目” 被当成行内 * */
	const body = s.replace(/^[ \t]*(?:[-*+]|\d+[.)])[ \t]+/, '');
	if (/^\*[^\s*]/.test(body) || /^_[^\s_]/.test(body)) {
		return true;
	}
	/* 乘号 “2 * 3”：* 两侧空白，不触发；snake_case 词内 _ 不触发 */
	if (/(?:^|[^\s*])\*(?!\*|\s)/.test(body)) {
		return true;
	}
	if (/(?:^|[^\w\s_])_(?!_|\s|\w)/.test(body) || /(?:^|\s)_[^\s_]/.test(body)) {
		return true;
	}
	return false;
}

export function hasStreamMarkdownSyntax(s: string): boolean {
	return hasStreamBlockSyntax(s) || hasStreamInlineSyntax(s);
}

/**
 * 打字机在未闭合围栏或已确立表格区域应加快追赶，
 * 否则每字一帧会把整段 code/table 重渲到卡死。
 */
export function streamNeedsFastTypewriter(text: string): boolean {
	if (!text) {
		return false;
	}
	let inFence = false;
	const lines = text.split('\n');
	for (let i = 0; i < lines.length; i += 1) {
		if (FENCE_LINE.test(lines[i]!)) {
			inFence = !inFence;
		}
	}
	if (inFence) {
		return true;
	}
	let mathOpen = false;
	for (let i = 0; i < text.length - 1; i += 1) {
		if (text[i] === '$' && text[i + 1] === '$') {
			mathOpen = !mathOpen;
			i += 1;
		}
	}
	if (mathOpen) {
		return true;
	}
	return scanTrailingTable(text) != null;
}

/** 拆 GFM 管道单元格（容忍缺失首尾 `|`）。 */
export function splitPipeCells(line: string): string[] {
	let t = line.trim();
	if (!t) {
		return [''];
	}
	if (t.startsWith('|')) {
		t = t.slice(1);
	}
	if (t.endsWith('|')) {
		t = t.slice(0, -1);
	}
	return t.split('|').map(cell => cell.trim());
}

export type StreamTableAlign = 'left' | 'center' | 'right' | null;

export type StreamTableModel = {
	headers: string[];
	aligns: StreamTableAlign[];
	/** 已换行完成的表体行。 */
	rows: string[][];
	/** 正在生长的最后一行（含半截单元格）；无则 null。 */
	liveRow: string[] | null;
	/** 源以换行结束 → 下一空行待写。 */
	liveEmpty: boolean;
};

function parseAlignCell(cell: string): StreamTableAlign {
	const t = cell.trim();
	const left = t.startsWith(':');
	const right = t.endsWith(':');
	if (left && right) {
		return 'center';
	}
	if (right) {
		return 'right';
	}
	if (left) {
		return 'left';
	}
	return null;
}

function padCells(cells: string[], width: number): string[] {
	const out = cells.slice(0, width);
	while (out.length < width) {
		out.push('');
	}
	return out;
}

/**
 * 将已确立的流式表格源码解析为可增量渲染的模型。
 * 假定 scanTrailingTable 已确认表头+分隔行存在。
 */

/** Growing GFM delimiter (only | - : whitespace), complete or partial. */
export function isDelimiterLike(line: string): boolean {
	const t = line.trim();
	if (!t) {
		return false;
	}
	if (mdTableDelimiterRow(line)) {
		return true;
	}
	return /^[|:\- \t]+$/.test(t) && t.includes('|');
}

/**
 * Header row exists but delimiter not finished — pull out of prose head
 * so `|` / `---` never render as live markdown source.
 */
export function scanPendingTable(
	text: string,
): {start: number; headers: string[]; growingHeader: boolean} | null {
	type ScanLine = {start: number; text: string};
	const lines: ScanLine[] = [];
	for (let pos = 0; pos < text.length; ) {
		const nl = text.indexOf('\n', pos);
		const end = nl === -1 ? text.length : nl;
		lines.push({start: pos, text: text.slice(pos, end)});
		pos = nl === -1 ? text.length : nl + 1;
	}
	if (lines.length === 0) {
		return null;
	}

	let inFence = false;
	for (const line of lines) {
		if (FENCE_LINE.test(line.text)) {
			inFence = !inFence;
		}
	}
	if (inFence) {
		return null;
	}

	for (const line of lines) {
		if (mdTableDelimiterRow(line.text)) {
			return null;
		}
	}

	const endsWithNl = text.endsWith('\n');
	const last = lines[lines.length - 1]!;
	const lastCompleteIdx = endsWithNl ? lines.length - 1 : lines.length - 2;

	if (!endsWithNl && mdPipeRowStart(last.text) && !isDelimiterLike(last.text)) {
		return {
			start: last.start,
			headers: splitPipeCells(last.text),
			growingHeader: true,
		};
	}

	if (!endsWithNl && isDelimiterLike(last.text)) {
		if (lastCompleteIdx >= 0) {
			const prev = lines[lastCompleteIdx]!;
			if (
				prev.text.includes('|') &&
				!isDelimiterLike(prev.text) &&
				!mdTableDelimiterRow(prev.text)
			) {
				return {
					start: prev.start,
					headers: splitPipeCells(prev.text),
					growingHeader: false,
				};
			}
		}
		return null;
	}

	if (endsWithNl && lastCompleteIdx >= 0) {
		const prev = lines[lastCompleteIdx]!;
		if (
			mdPipeRowStart(prev.text) &&
			!isDelimiterLike(prev.text) &&
			!mdTableDelimiterRow(prev.text)
		) {
			return {
				start: prev.start,
				headers: splitPipeCells(prev.text),
				growingHeader: false,
			};
		}
	}

	return null;
}

/** Drop a growing fence closer (\n` / \n``) so ticks never paint inside the code body. */
export function stripGrowingFenceCloser(code: string): {
	code: string;
	closed: boolean;
} {
	if (/(?:^|\n)(?:```|~~~)[ \t]*$/.test(code)) {
		return {code, closed: true};
	}
	const m = code.match(/(^|\n)(`{1,2}|~{1,2})$/);
	if (m && m[2]) {
		return {code: code.slice(0, code.length - m[2].length), closed: false};
	}
	return {code, closed: false};
}


export function parseStreamTable(src: string): StreamTableModel | null {
	if (!src.trim()) {
		return null;
	}
	const rawLines = src.split('\n');
	const lines: string[] = [...rawLines];
	if (lines.length < 2) {
		return null;
	}

	let delimIdx = -1;
	for (let i = 1; i < lines.length; i += 1) {
		if (mdTableDelimiterRow(lines[i]!)) {
			delimIdx = i;
			break;
		}
	}
	if (delimIdx < 1) {
		return null;
	}

	const headers = splitPipeCells(lines[delimIdx - 1]!);
	const aligns = splitPipeCells(lines[delimIdx]!).map(parseAlignCell);
	while (aligns.length < headers.length) {
		aligns.push(null);
	}

	const bodyLines = lines.slice(delimIdx + 1);
	const endsWithNl = src.endsWith('\n');
	const completeCount = endsWithNl
		? bodyLines.length
		: Math.max(0, bodyLines.length - 1);
	const rows: string[][] = [];
	for (let i = 0; i < completeCount; i += 1) {
		const line = bodyLines[i]!;
		if (!line.trim()) {
			continue;
		}
		rows.push(padCells(splitPipeCells(line), headers.length));
	}

	let liveRow: string[] | null = null;
	let liveEmpty = false;
	if (endsWithNl) {
		liveEmpty = true;
		liveRow = padCells([''], headers.length);
	} else if (bodyLines.length > completeCount) {
		const live = bodyLines[bodyLines.length - 1]!;
		liveRow = padCells(splitPipeCells(live), headers.length);
	}

	return {headers, aligns, rows, liveRow, liveEmpty};
}

type TableScan = {
	/** 区域起点字符偏移（从第一个表头候选行的行首开始）。 */
	start: number;
};

/**
 * 扫描文本尾部是否存在「已确立」的 GFM 表格区域：
 * 紧邻分隔行之上的含竖线行是表头，之后的连续非空行都是表格的一部分，
 * 直到空行、围栏或块公式边界为止。命中后把整片区域一起吸收进同一个块，
 * 让正在生长的最后一行也直接渲染进真实表格里，
 * 而不是以裸竖线段落的形式悬在表格下面。
 *
 * 返回的区域起点指向表头行首。未找到时返回 null。
 */
export function scanTrailingTable(text: string): TableScan | null {
	type ScanLine = {start: number; text: string};
	const lines: ScanLine[] = [];
	for (let pos = 0; pos < text.length; ) {
		const nl = text.indexOf('\n', pos);
		const end = nl === -1 ? text.length : nl;
		lines.push({start: pos, text: text.slice(pos, end)});
		pos = nl === -1 ? text.length : nl + 1;
	}
	if (lines.length === 0) {
		return null;
	}

	let inFence = false;
	let mathOpen = false;
	// 分隔行之前最后一个可能成为表头的行（须为紧邻的含竖线行）。
	let headerCandidate = -1;
	let regionStart = -1;
	let delimSeen = false;

	for (let idx = 0; idx < lines.length; idx += 1) {
		const line = lines[idx]!;
		// 围栏开关无条件判断（与 splitStableMarkdownBlocks 一致），
		// 否则闭合行会被当作代码体吞掉，后续表格永远无法识别。
		if (FENCE_LINE.test(line.text)) {
			inFence = !inFence;
			headerCandidate = -1;
			regionStart = -1;
			delimSeen = false;
			continue;
		}
		if (inFence) {
			continue;
		}
		if (!line.text.trim()) {
			headerCandidate = -1;
			regionStart = -1;
			delimSeen = false;
			continue;
		}
		if (countDisplayMathDelimiters(line.text) % 2 === 1) {
			mathOpen = !mathOpen;
		}
		if (mathOpen) {
			continue;
		}
		if (mdTableDelimiterRow(line.text)) {
			if (!delimSeen && headerCandidate >= 0) {
				regionStart = headerCandidate;
				delimSeen = true;
			}
			continue;
		}
		if (line.text.includes('|')) {
			// 含竖线的普通行：激活前是表头候选；激活后保持在区域内。
			if (!delimSeen) {
				headerCandidate = line.start;
			}
			continue;
		}
		// 激活后的普通散文不重置区域：把它一并吸进同一个块，
		// remark 会按 GFM 规则自动断开表尾 ——
		// 这样增量解析与全量解析在“行后无空行直接接散文”时分区一致，
		// 不会出现分区逐帧翻转。
		if (!delimSeen) {
			headerCandidate = -1;
		}
	}

	return regionStart >= 0 ? {start: regionStart} : null;
}

/**
 * 将已完成的 Markdown 头部拆成视觉上等价的稳定块。
 *
 * 只在围栏、块公式之外的空行处分割，并保守地保持列表/引用连续，
 * 因而不会改变 Markdown 的块级语义；稳定块的 React props 不再随 token 改变。
 */
export function splitStableMarkdownBlocks(text: string): string[] {
	if (!text.trim()) {
		return [];
	}
	const lines = text.split('\n');
	const blocks: string[] = [];
	let blockStart = 0;
	let inFence = false;
	let mathOpen = false;

	for (let i = 0; i < lines.length; i += 1) {
		const line = lines[i]!;
		if (FENCE_LINE.test(line)) {
			inFence = !inFence;
		}
		if (!inFence) {
			if (countDisplayMathDelimiters(line) % 2 === 1) {
				mathOpen = !mathOpen;
			}
			if (!line.trim() && !mathOpen && i > blockStart) {
				let next = i + 1;
				while (next < lines.length && !lines[next]!.trim()) {
					next += 1;
				}
				const previous = lines[i - 1]?.trim() ?? '';
				const following = lines[next]?.trim() ?? '';
				const listContinuation =
					LIST_OR_QUOTE_LINE.test(previous) || LIST_OR_QUOTE_LINE.test(following);
				const indentedContinuation = Boolean(lines[next]) && /^ {4,}\S/.test(lines[next]!);
				if (!listContinuation && !indentedContinuation) {
					const block = lines.slice(blockStart, i + 1).join('\n');
					if (block.trim()) {
						blocks.push(block);
					}
					blockStart = i + 1;
				}
			}
		}
	}
	const tail = lines.slice(blockStart).join('\n');
	if (tail.trim()) {
		blocks.push(tail);
	}
	return blocks;
}

export type StreamMarkdownCache = {
	text: string;
	parts: StreamMarkdownParts;
};

/**
 * 流式文本通常只做前缀追加。对没有结构性分隔符的更新只处理新增尾部；
 * 代码围栏/公式内部只追加 payload；已确立表格内部直接追加行；
 * 遇到闭合、回溯或新结构时回退到完整解析。
 */
export function splitStreamMarkdownIncremental(
	text: string,
	previous: StreamMarkdownCache | null,
): StreamMarkdownCache {
	if (!previous || text.length < previous.text.length || !text.startsWith(previous.text)) {
		return {text, parts: splitStreamMarkdown(text)};
	}
	if (text === previous.text) {
		return previous;
	}

	const suffix = text.slice(previous.text.length);
	const previousParts = previous.parts;
	if (previousParts.tablePending) {
		return {text, parts: splitStreamMarkdown(text)};
	}
	if (previousParts.fence) {
		const merged = previousParts.fence.code + suffix;
		const stripped = stripGrowingFenceCloser(merged);
		if (stripped.closed || suffix.includes('```') || suffix.includes('~~~')) {
			return {text, parts: splitStreamMarkdown(text)};
		}
		return {
			text,
			parts: {
				head: previousParts.head,
				live: '',
				fence: {
					lang: previousParts.fence.lang,
					code: stripped.code,
				},
				math: null,
				tablePending: null,
				table: null,
			},
		};
	}
	if (previousParts.math !== null && !suffix.includes('$$')) {
		return {
			text,
			parts: {
				head: previousParts.head,
				live: '',
				fence: null,
				math: previousParts.math + suffix,
				tablePending: null,
				table: null,
			},
		};
	}
	if (previousParts.table !== null) {
		const structuralHit =
			suffix.includes('```') ||
			suffix.includes('~~~') ||
			suffix.includes('$$') ||
			/\n[ \t\r]*\n/.test(suffix);
		if (!structuralHit) {
			// 表格仍在生长：追加内容即可，分隔行之外不会突然出现新结构。
			// 非管道行也能被安全吸收 —— remark 会自动在表格后的普通文本处断开。
			return {
				text,
				parts: {
					head: previousParts.head,
					live: '',
					fence: null,
					math: null,
					tablePending: null,
					table: previousParts.table + suffix,
				},
			};
		}
	}
	if (
		!previousParts.fence &&
		previousParts.math === null &&
		previousParts.table === null &&
		!suffix.includes('```') &&
		!suffix.includes('~~~') &&
		!suffix.includes('$$')
	) {
		// 与全量解析同一套结构扫描：表格/半截分隔绝不能掉进 live 当源码。
		const scan = scanTrailingTable(text);
		if (scan) {
			return {
				text,
				parts: {
					head: text.slice(0, scan.start),
					live: '',
					fence: null,
					math: null,
					tablePending: null,
					table: text.slice(scan.start),
				},
			};
		}
		const pending = scanPendingTable(text);
		if (pending) {
			return {
				text,
				parts: {
					head: text.slice(0, pending.start),
					live: '',
					fence: null,
					math: null,
					table: null,
					tablePending: {
						headers: pending.headers,
						growingHeader: pending.growingHeader,
					},
				},
			};
		}

		const rawLive = previous.text.slice(previousParts.head.length) + suffix;
		const lastNl = rawLive.lastIndexOf('\n');
		if (lastNl === -1) {
			return {
				text,
				parts: {
					head: previousParts.head,
					// raw live：只在 LiveInlineMarkdown 内 balance 一次，避免 ****。
					live: rawLive,
					fence: null,
					math: null,
					tablePending: null,
					table: null,
				},
			};
		}
		const liveTail = rawLive.slice(lastNl + 1);
		if (isStructuralTail(liveTail)) {
			return {text, parts: splitStreamMarkdown(text)};
		}
		return {
			text,
			parts: {
				head: previousParts.head + rawLive.slice(0, lastNl + 1),
				live: liveTail,
				fence: null,
				math: null,
				tablePending: null,
				table: null,
			},
		};
	}
	return {text, parts: splitStreamMarkdown(text)};
}

export function splitStreamMarkdown(text: string): StreamMarkdownParts {
	const empty: StreamMarkdownParts = {
		head: '',
		live: '',
		fence: null,
		math: null,
		tablePending: null,
		table: null,
	};
	if (!text) {
		return empty;
	}

	const lines = text.split('\n');
	let inFence = false;
	let fenceStart = 0;
	let offset = 0;
	for (let i = 0; i < lines.length; i += 1) {
		const line = lines[i]!;
		const last = i === lines.length - 1;
		if (FENCE_LINE.test(line)) {
			if (inFence) {
				inFence = false;
			} else {
				inFence = true;
				fenceStart = offset;
			}
		}
		offset += line.length + (last ? 0 : 1);
	}
	if (inFence) {
		const opened = parseOpenFence(text.slice(fenceStart));
		const stripped = stripGrowingFenceCloser(opened.code);
		return {
			head: text.slice(0, fenceStart),
			live: '',
			fence: {lang: opened.lang, code: stripped.code},
			math: null,
			tablePending: null,
			table: null,
		};
	}

	let mathOpen = -1;
	for (let i = 0; i < text.length - 1; i += 1) {
		if (text[i] === '$' && text[i + 1] === '$') {
			mathOpen = mathOpen === -1 ? i : -1;
			i += 1;
		}
	}
	if (mathOpen >= 0) {
		return {
			head: text.slice(0, mathOpen),
			live: '',
			fence: null,
			math: text.slice(mathOpen + 2).replace(/^\n/, ''),
			tablePending: null,
			table: null,
		};
	}

	const nl = text.lastIndexOf('\n');

	// 表格状态机：表头+分隔行一旦确定，整个区域（含生长中的最后一行，
	// 也含行后无空行直接接上的散文明文）合并为一个块交给 remark，
	// GFM 会按规则自行断开表尾。这样之前“裸竖线段落 ↔ 表格”的逐帧横跳
	// 彻底消失，且全量解析与增量快捷路径的分区始终一致。
	const scan = scanTrailingTable(text);
	if (scan) {
		return {
			head: text.slice(0, scan.start),
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: text.slice(scan.start),
		};
	}

	const pending = scanPendingTable(text);
	if (pending) {
		return {
			head: text.slice(0, pending.start),
			live: '',
			fence: null,
			math: null,
			table: null,
			tablePending: {
				headers: pending.headers,
				growingHeader: pending.growingHeader,
			},
		};
	}

	const lastNl = nl;
	if (lastNl === -1) {
		return {
			head: '',
			// raw live；balance 只在 LiveInlineMarkdown 做一次。
			live: text,
			fence: null,
			math: null,
			tablePending: null,
			table: null,
		};
	}
	const tail = text.slice(lastNl + 1);
	if (isStructuralTail(tail)) {
		return {
			head: text,
			live: '',
			fence: null,
			math: null,
			tablePending: null,
			table: null,
		};
	}
	return {
		head: text.slice(0, lastNl + 1),
		live: tail,
		fence: null,
		math: null,
		tablePending: null,
		table: null,
	};
}
