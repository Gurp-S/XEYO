/**
 * 从展示文本中剥离 XML 风格 tool_call（含未闭合的流式半截）。
 * 与 python/engine/xml_tool_call.py 对齐，仅做 UI 清洗，不解析执行。
 */

const TOOL_CALL_COMPLETE =
	/<tool_call>\s*[A-Za-z_][\w.-]*\s*[\s\S]*?<\/tool_call>/gi;

/** 未闭合：从 <tool_call> 起到文末（流式输出中） */
const TOOL_CALL_OPEN = /<tool_call>\s*[A-Za-z_][\w.-]*[\s\S]*$/i;

const LOOSE_ARG_MARKUP =
	/<\/?(?:arg_key|arg_value|tool_call)\b[^>]*>/gi;

export function looksLikeRawToolMarkup(text: string): boolean {
	const s = (text || '').trim();
	if (!s) {
		return false;
	}
	const low = s.toLowerCase();
	if (!low.includes('<tool_call>') && !low.includes('<arg_key>')) {
		return false;
	}
	const stripped = stripXmlToolCallsForDisplay(s).trim();
	return stripped.length < 24;
}

/** 供 Streaming / Markdown 展示用：去掉完整与半截 tool_call。 */
export function stripXmlToolCallsForDisplay(text: string): string {
	let raw = text || '';
	if (
		!/<tool_call/i.test(raw) &&
		!/<arg_key/i.test(raw) &&
		!/<arg_value/i.test(raw)
	) {
		return raw;
	}
	raw = raw.replace(TOOL_CALL_COMPLETE, '');
	raw = raw.replace(TOOL_CALL_OPEN, '');
	// 残留的散落标签（半截参数）
	raw = raw.replace(LOOSE_ARG_MARKUP, '');
	raw = raw.replace(/\n{3,}/g, '\n\n').trimEnd();
	return raw;
}
