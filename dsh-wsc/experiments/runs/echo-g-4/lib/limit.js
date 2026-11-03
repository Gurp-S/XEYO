/**
 * Run `task` over `items` with at most `limit` promises in flight.
 * Results come back in input order so callers stay deterministic, and the
 * first failure stops new work from being picked up.
 */
export async function mapLimit(items, limit, task) {
  const list = [...items];
  const total = list.length;
  if (total === 0) return [];

  const width = Math.min(Math.max(1, Number.isFinite(limit) ? Math.floor(limit) : total), total);
  const results = new Array(total);
  let cursor = 0;
  let failure = null;

  const worker = async () => {
    while (failure === null) {
      const index = cursor;
      cursor += 1;
      if (index >= total) return;
      try {
        results[index] = await task(list[index], index);
      } catch (error) {
        failure = failure ?? error;
      }
    }
  };

  await Promise.all(Array.from({ length: width }, worker));
  if (failure !== null) throw failure;
  return results;
}
