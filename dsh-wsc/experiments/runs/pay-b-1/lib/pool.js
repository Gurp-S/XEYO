/**
 * Run `fn` over `items` with at most `limit` calls in flight.
 * Results keep the input order. The first rejection aborts the whole map.
 */
export async function mapPool(items, limit, fn) {
  const list = [...items];
  const results = new Array(list.length);
  const width = Math.max(1, Math.min(Number.isFinite(limit) ? Math.floor(limit) : 1, list.length));
  let cursor = 0;
  const workers = Array.from({ length: width }, async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= list.length) return;
      results[index] = await fn(list[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}
