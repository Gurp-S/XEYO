/** A text cache is bounded by both entry count and retained UTF-16 code units.
 * The accounting is conservative when strings share storage; it is not heap usage.
 */
export const TEXT_CACHE_MAX_CHARS = 4_000_000;

export class TextLruCache<V> {
	private entries = new Map<string, {value: V; chars: number}>();
	private chars = 0;

	constructor(
		private maxEntries: number,
		private maxChars: number,
		private valueChars: (value: V) => number,
	) {}

	get size() { return this.entries.size; }
	get retainedChars() { return this.chars; }

	get(key: string): V | undefined {
		const entry = this.entries.get(key);
		if (!entry) return undefined;
		this.entries.delete(key);
		this.entries.set(key, entry);
		return entry.value;
	}

	set(key: string, value: V): void {
		const previous = this.entries.get(key);
		if (previous) {
			this.chars -= previous.chars;
			this.entries.delete(key);
		}
		const chars = key.length + this.valueChars(value);
		// Oversized results are returned by callers without evicting hot entries.
		if (chars > this.maxChars || this.maxEntries <= 0) return;
		this.entries.set(key, {value, chars});
		this.chars += chars;
		while (this.entries.size > this.maxEntries || this.chars > this.maxChars) {
			const oldest = this.entries.entries().next().value!;
			this.chars -= oldest[1].chars;
			this.entries.delete(oldest[0]);
		}
	}
}
