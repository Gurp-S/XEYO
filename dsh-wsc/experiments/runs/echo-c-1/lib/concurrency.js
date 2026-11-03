export const DEFAULT_CONCURRENCY = 4;

export function normalizeConcurrency(value) {
  if (value === undefined || value === null) return DEFAULT_CONCURRENCY;
  const count = Number(value);
  if (!Number.isInteger(count) || count < 1) {
    throw new Error(`invalid --concurrency value: ${value}`);
  }
  return count;
}

// Run `fn` over `items` with at most `limit` calls in flight, returning results
// in input order so the build stays deterministic at every concurrency.
export async function mapLimit(items, limit, fn) {
  const size = Math.max(1, Math.min(limit, items.length));
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: size }, async () => {
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
