/**
 * Run `worker` over `items` with at most `limit` calls in flight.
 *
 * Results are returned in input order regardless of completion order, so the
 * report and the output ordering stay deterministic for any `limit`.
 */
export async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  if (items.length === 0) return results;
  const width = Math.max(1, Math.min(Math.trunc(limit) || 1, items.length));
  let next = 0;
  const runners = new Array(width).fill(null).map(async () => {
    for (;;) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}
