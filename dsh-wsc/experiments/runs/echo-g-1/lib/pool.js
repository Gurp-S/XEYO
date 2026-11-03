export const DEFAULT_CONCURRENCY = 4;

/** Validate a `--concurrency` value; throws on anything that is not a positive integer. */
export function normalizeConcurrency(value) {
  if (value === undefined || value === null) return DEFAULT_CONCURRENCY;
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    throw new Error(`--concurrency needs a positive integer, got: ${String(value)}`);
  }
  return parsed;
}

/**
 * Run `fn` over `items` with at most `limit` calls in flight.
 * Results keep input order, so callers stay deterministic.
 */
export async function mapPool(items, limit, fn) {
  const results = new Array(items.length);
  let cursor = 0;
  const workerCount = Math.max(1, Math.min(limit, items.length));
  const workers = [];
  for (let worker = 0; worker < workerCount; worker += 1) {
    workers.push(
      (async () => {
        for (;;) {
          const index = cursor;
          cursor += 1;
          if (index >= items.length) return;
          results[index] = await fn(items[index], index);
        }
      })(),
    );
  }
  await Promise.all(workers);
  return results;
}
