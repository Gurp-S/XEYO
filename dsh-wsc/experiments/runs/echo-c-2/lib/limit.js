// Runs `fn` over `items` with at most `limit` calls in flight. Results keep the
// input order regardless of completion order.
export async function mapLimit(items, limit, fn) {
  const total = items.length;
  const results = new Array(total);
  if (total === 0) return results;
  const width = Math.max(1, Math.min(Number.isFinite(limit) ? Math.floor(limit) : total, total));
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= total) return;
      results[index] = await fn(items[index], index);
    }
  };
  await Promise.all(Array.from({ length: width }, worker));
  return results;
}
