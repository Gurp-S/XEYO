import {
	hasStreamBlockSyntax,
	hasStreamInlineSyntax,
	mdTableDelimiterRow,
} from './streamMarkdown';

const FENCE_LINE = /^[ \t]{0,3}(?:```|~~~)/;

/**
 * 用户输入的 Markdown 探测（历史气泡 / sticky 气泡 / Composer 预览共用）。
 *
 * 判定标准与流式侧 `hasStreamMarkdownSyntax` 同源（块级按行、行内按全文），
 * 在此基础上补上多行场景：逐行测块级语法，并识别围栏与 GFM 表格分隔行。
 * 纯文字（含「2 * 3」、snake_case、#话题 这类形态）一律返回 false，
 * 保持 whitespace-pre-wrap 的原文渲染，避免把普通消息错误渲染成 Markdown。
 */
export function looksLikeMarkdown(text: string): boolean {
	if (!text) {
		return false;
	}
	const lines = text.split('\n');
	for (const line of lines) {
		if (hasStreamBlockSyntax(line)) {
			return true;
		}
		if (FENCE_LINE.test(line)) {
			return true;
		}
		if (mdTableDelimiterRow(line)) {
			return true;
		}
	}
	return hasStreamInlineSyntax(text);
}
