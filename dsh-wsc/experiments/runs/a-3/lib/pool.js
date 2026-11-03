export const DEFAULT_CONCURRENCY = 4;

// `--concurrency <n>` bounds how many files are built at once. Anything that is
// not a positive integer is rejected rather than silently coerced, so a typo
// cannot quietly change the build's parallelism.
export function parseConcurrency(value) {
  if (typeof value !== 'string' || !/^\d+$/.test(value.trim())) {
    throw new Error(`--concurrency needs a positive integer, got: ${value}`);
  }
  const n = Number(value.trim());
  if (!Number.isSafeInteger(n) || n < 1) {
    throw new Error(`--concurrency needs a positive integer, got: ${value}`);
  }
  return n;
}

export function normalizeConcurrency(value) {
  if (value === undefined || value === null) return DEFAULT_CONCURRENCY;
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new Error(`concurrency needs a positive integer, got: ${value}`);
    }
    return value;
  }
  return parseConcurrency(value);
}

// Runs `fn` over `items` with at most `limit` in flight. Results come back in
// input order, so the observable output order never depends on which file
// happened to finish first.
export async function mapLimit(items, limit, fn) {
  const list = Array.from(items);
  const results = new Array(list.length);
  if (list.length === 0) return results;
  const width = Math.max(1, Math.min(normalizeConcurrency(limit), list.length));
  let next = 0;
  let failure = null;

  async function worker() {
    for (;;) {
      const index = next++;
      if (index >= list.length) return;
      if (failure) return;
      try {
        results[index] = await fn(list[index], index);
      } catch (err) {
        failure ??= err;
        return;
      }
    }
  }

  await Promise.all(Array.from({ length: width }, () => worker()));
  if (failure) throw failure;
  return results;
}
