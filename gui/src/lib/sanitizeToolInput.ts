/**
 * 为聊天 UI / SSE 旁路缩小巨大的 Write/Edit 字符串字段。
 * 保留 path + 行数以便 activity diff 仍可用；丢弃完整正文。
 */

const MAX_KEEP = 240;

function lineCount(text: string): number {
	if (!text) {
		return 0;
	}
	return text.split('\n').length;
}

function shrinkField(text: string): {preview: string; lines: number} {
	const lines = lineCount(text);
	if (text.length <= MAX_KEEP) {
		return {preview: text, lines};
	}
	return {
		preview: `${text.slice(0, MAX_KEEP)}\n… [${lines} lines, ${text.length} chars]`,
		lines,
	};
}

/** 返回浅拷贝的普通对象，可安全 JSON.stringify 供 UI 使用。 */
export function sanitizeToolInputForUi(input: unknown): unknown {
	if (!input || typeof input !== 'object' || Array.isArray(input)) {
		return input;
	}
	const src = input as Record<string, unknown>;
	const out: Record<string, unknown> = {...src};
	let touched = false;

	if (typeof out.content === 'string' && out.content.length > MAX_KEEP) {
		const {preview, lines} = shrinkField(out.content);
		out.content = preview;
		out._content_lines = lines;
		touched = true;
	}
	for (const key of ['old_string', 'new_string'] as const) {
		const v = out[key];
		if (typeof v === 'string' && v.length > MAX_KEEP) {
			out[key] = shrinkField(v).preview;
			touched = true;
		}
	}
	return touched ? out : input;
}

export function formatToolInputForUi(input: unknown): string {
	const safe = sanitizeToolInputForUi(input);
	if (typeof safe === 'string') {
		return safe;
	}
	try {
		return JSON.stringify(safe);
	} catch {
		return String(safe);
	}
}
