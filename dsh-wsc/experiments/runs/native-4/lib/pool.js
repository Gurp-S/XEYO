// Runs `fn` over `items` with at most `limit` calls in flight, preserving the
// order of the results. Used to bound how many files are read or written at once.
export async function mapLimit(items, limit, fn) {
  const list = [...items];
  const results = new Array(list.length);
  const width = Math.max(1, Math.min(Number(limit) || 1, list.length));
  let cursor = 0;
  const workers = [];
  for (let slot = 0; slot < width; slot += 1) {
    workers.push(
      (async () => {
        while (cursor < list.length) {
          const index = cursor;
          cursor += 1;
          results[index] = await fn(list[index], index);
        }
      })(),
    );
  }
  await Promise.all(workers);
  return results;
}
