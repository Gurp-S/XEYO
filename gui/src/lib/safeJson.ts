/** Parse JSON text; return objects/arrays as-is; never throw. */
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

/** Coerce IndexedDB / storage values to JSON text. */
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
