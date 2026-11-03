// Run `fn` over `items` with at most `limit` calls in flight. Results keep the
// input order; the first rejection aborts the remaining work.
export async function mapLimit(items, limit, fn) {
  const list = [...items];
  const results = new Array(list.length);
  const width = Math.max(1, Math.min(Math.trunc(limit) || 1, list.length));
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= list.length) return;
      results[index] = await fn(list[index], index);
    }
  };
  await Promise.all(Array.from({ length: width }, worker));
  return results;
}
