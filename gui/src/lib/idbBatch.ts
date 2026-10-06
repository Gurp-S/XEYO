/** Queue bounded batches inside the same transaction. Await only IDB requests:
 * yielding to a timer here would allow the transaction to auto-commit. */
export async function idbBatch<T>(
	items: readonly T[],
	request: (item: T) => Promise<unknown>,
): Promise<void> {
	for (let start = 0; start < items.length; start += 128) {
		await Promise.all(items.slice(start, start + 128).map(request));
	}
}
