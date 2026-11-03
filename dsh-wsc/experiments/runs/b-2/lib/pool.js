// Bounded fan-out: at most `limit` tasks in flight, results in input order.
export async function mapLimit(items, limit, fn) {
  const list = Array.from(items);
  const results = new Array(list.length);
  let cursor = 0;
  const worker = async () => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      if (index >= list.length) return;
      results[index] = await fn(list[index], index);
    }
  };
  const width = Math.max(1, Math.min(Math.floor(limit) || 1, list.length));
  await Promise.all(Array.from({ length: width }, worker));
  return results;
}
