import type {RemendHandler} from 'remend';
import {isWithinCodeBlock} from 'remend';

/**
 * Streamdown/remend 不管半截表格与「正在打的 ``` 收尾」。
 * 薄 handler：不回到双渲染路径，只在送进内核前软化尾部。
 */

function looksLikeTableRow(line: string): boolean {
	const t = line.trim();
	return t.includes('|') && !t.startsWith('```');
}

function isDelimiterRow(line: string): boolean {
	const t = line.trim();
	if (!t.includes('|') || !t.includes('-')) {
		return false;
	}
	return /^\|?[\s:|-]+\|?$/.test(t);
}

/** 尾部半截表格：去掉裸 `|`/`---`，保留已能成表的完整块。 */
export const incompleteTableHandler: RemendHandler = {
	name: 'xy-incomplete-table',
	priority: 85,
	handle(text) {
		if (!text.includes('|') || isWithinCodeBlock(text, text.length - 1)) {
			return text;
		}
		const lines = text.split('\n');
		let i = lines.length - 1;
		while (i >= 0 && lines[i]?.trim() === '') {
			i -= 1;
		}
		if (i < 0 || !looksLikeTableRow(lines[i] ?? '')) {
			return text;
		}

		// 从尾部向上收连续表格行
		let start = i;
		while (start > 0 && looksLikeTableRow(lines[start - 1] ?? '')) {
			start -= 1;
		}
		const block = lines.slice(start, i + 1);
		const hasDelim = block.some(isDelimiterRow);
		const dataRows = block.filter(l => !isDelimiterRow(l));

		if (hasDelim && dataRows.length >= 2) {
			// 完整表（头+分隔+至少一行）— 不动
			return text;
		}

		// 半截：用空格替代表格元字符，避免露源码；仍保留可读文字
		const softened = block.map(line =>
			line.replace(/\|/g, ' ').replace(/-{3,}/g, ' ').replace(/ {2,}/g, ' ').trimEnd(),
		);
		return [...lines.slice(0, start), ...softened, ...lines.slice(i + 1)].join('\n');
	},
};

/** 打开围栏末尾的 `` / ` 收尾噪声：从正文拿掉，等满 ``` 再闭合。 */
export const partialFenceCloserHandler: RemendHandler = {
	name: 'xy-partial-fence-closer',
	priority: 5,
	handle(text) {
		const fenceCount = (text.match(/^```/gm) || []).length;
		if (fenceCount % 2 === 0) {
			return text;
		}
		// 奇数围栏：去掉末尾单独一行的 1–2 个反引号
		return text.replace(/\n`{1,2}[ \t]*$/, '\n');
	},
};

export const xyRemendHandlers: RemendHandler[] = [
	partialFenceCloserHandler,
	incompleteTableHandler,
];
