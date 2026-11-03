// Run `fn` over `items` with at most `limit` calls in flight. Results are
// returned in input order, so callers can keep output deterministic no matter
// how the work interleaves.
export async function mapLimit(items, limit, fn) {
  const list = Array.from(items);
  const size = Math.max(1, Math.floor(limit) || 1);
  const results = new Array(list.length);
  let next = 0;

  async function worker() {
    while (true) {
      const index = next;
      next += 1;
      if (index >= list.length) return;
      results[index] = await fn(list[index], index);
    }
  }

  const workers = [];
  for (let index = 0; index < Math.min(size, list.length); index += 1) {
    workers.push(worker());
  }
  await Promise.all(workers);
  return results;
}
