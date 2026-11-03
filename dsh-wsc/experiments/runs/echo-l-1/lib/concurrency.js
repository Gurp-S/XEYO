/**
 * Run an async mapper over items with at most `limit` calls in flight.
 * Results keep the input order, independent of completion order.
 */
export async function mapLimit(items, limit, mapper) {
  if (items.length === 0) return [];
  const width = Math.max(1, Math.min(limit, items.length));
  const results = new Array(items.length);
  let next = 0;

  async function worker() {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      results[index] = await mapper(items[index], index);
    }
  }

  await Promise.all(Array.from({ length: width }, worker));
  return results;
}
