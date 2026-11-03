import { availableParallelism } from 'node:os';

export const DEFAULT_CONCURRENCY = Math.max(1, availableParallelism());

// Runs `worker` over `items` with at most `limit` in flight, keeping results in
// input order so callers stay deterministic.
export async function runPool(items, limit, worker) {
  const results = new Array(items.length);
  const width = Math.max(1, Math.min(Math.trunc(limit) || 1, items.length));
  let next = 0;
  async function lane() {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: width }, lane));
  return results;
}

export function normalizeConcurrency(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 1) return DEFAULT_CONCURRENCY;
  return Math.floor(n);
}
