/**
 * Run `worker` over `items` with at most `limit` calls in flight.
 *
 * Results are returned in input order regardless of completion order, so the
 * plan stays deterministic for any concurrency level.
 */
export async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  const width = Math.max(1, Math.min(Number.isFinite(limit) ? Math.floor(limit) : 1, items.length));
  let next = 0;
  const runners = [];
  for (let slot = 0; slot < width; slot += 1) {
    runners.push(
      (async () => {
        for (;;) {
          const index = next;
          next += 1;
          if (index >= items.length) return;
          results[index] = await worker(items[index], index);
        }
      })(),
    );
  }
  await Promise.all(runners);
  return results;
}
