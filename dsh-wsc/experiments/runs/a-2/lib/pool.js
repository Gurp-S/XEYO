// Runs `fn` over `items` with at most `limit` calls in flight. Results keep the
// input order, so callers that merge them stay deterministic.
export async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  const width = Math.max(1, Math.min(limit, items.length));
  let next = 0;
  const workers = Array.from({ length: width }, async () => {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      results[index] = await fn(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}
