// Runs `fn` over `items` with at most `limit` calls in flight. Results keep the input
// order, so a bounded run and a serial run produce the same report.
export async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  const bound = Math.max(1, Math.min(limit, items.length));
  let next = 0;
  const workers = Array.from({ length: bound }, async () => {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await fn(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}
