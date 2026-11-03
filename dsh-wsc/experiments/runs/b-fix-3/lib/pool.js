// Run `worker` over `items` with at most `limit` in flight. Results come back in
// input order, so output bytes and report order never depend on the limit.
export async function mapLimit(items, limit, worker) {
  const list = [...items];
  const results = new Array(list.length);
  if (list.length === 0) return results;
  const width = Math.max(1, Math.min(Number.isFinite(limit) ? Math.floor(limit) : list.length, list.length));
  let cursor = 0;
  const runners = Array.from({ length: width }, async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= list.length) return;
      results[index] = await worker(list[index], index);
    }
  });
  await Promise.all(runners);
  return results;
}
