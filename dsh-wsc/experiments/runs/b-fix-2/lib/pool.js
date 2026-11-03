// Run `worker` over `items` with at most `limit` calls in flight. Results keep
// the input order, so a bounded run reports exactly like a sequential one.
export async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  const size = Math.max(1, Math.min(limit, items.length));
  let cursor = 0;
  let failed = false;

  async function runner() {
    for (;;) {
      if (failed) return;
      const index = cursor;
      cursor += 1;
      if (index >= items.length) return;
      try {
        results[index] = await worker(items[index], index);
      } catch (error) {
        failed = true;
        throw error;
      }
    }
  }

  await Promise.all(Array.from({ length: size }, runner));
  return results;
}
