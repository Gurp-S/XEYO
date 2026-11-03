// Run `fn` over `items` with at most `limit` calls in flight. Results are
// returned in input order, so callers can keep deterministic reporting even
// though the work itself completes out of order.
export async function mapLimit(items, limit, fn) {
  if (!Number.isSafeInteger(limit) || limit < 1) {
    throw new Error('concurrency limit must be a positive integer');
  }
  const results = new Array(items.length);
  let next = 0;
  let failure = null;

  const worker = async () => {
    while (failure === null) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      try {
        results[index] = await fn(items[index], index);
      } catch (error) {
        if (failure === null) failure = error;
      }
    }
  };

  const workers = [];
  const width = Math.min(limit, items.length);
  for (let index = 0; index < width; index += 1) workers.push(worker());
  await Promise.all(workers);
  if (failure !== null) throw failure;
  return results;
}

export function parseConcurrency(value) {
  if (value === undefined || value === null || value === '') {
    throw new Error('--concurrency needs a value');
  }
  if (!/^\d+$/.test(String(value))) {
    throw new Error('--concurrency must be a positive integer');
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error('--concurrency must be a positive integer');
  }
  return parsed;
}
