/** 解析 JSON 文本；对象/数组原样返回；绝不抛错。 */
export function parseJsonValue<T = unknown>(value: unknown): T | null {
	if (value == null) {
		return null;
	}
	if (typeof value === 'object') {
		return value as T;
	}
	if (typeof value !== 'string') {
		return null;
	}
	const text = value.trim();
	if (!text) {
		return null;
	}
	try {
		return JSON.parse(text) as T;
	} catch {
		return null;
	}
}

/** 将 IndexedDB / storage 值转换为 JSON 文本。 */
export function coerceJsonText(value: unknown): string | undefined {
	if (value == null) {
		return undefined;
	}
	if (typeof value === 'string') {
		return value;
	}
	try {
		return JSON.stringify(value);
	} catch {
		return undefined;
	}
}
