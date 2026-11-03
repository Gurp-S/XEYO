// Bounded concurrency.
//
// `--concurrency <n>` is a ceiling on in-flight work, not a promise about
// ordering: every task receives its item, and the caller reaps results from
// the returned array, which keeps declaration order.

export async function mapLimit(items, limit, task) {
  const list = [...items];
  const results = new Array(list.length);
  if (list.length === 0) return results;
  const width = Math.max(1, Math.min(list.length, Number.isFinite(limit) ? Math.floor(limit) : list.length));
  let next = 0;

  async function worker() {
    while (true) {
      const index = next;
      next += 1;
      if (index >= list.length) return;
      results[index] = await task(list[index], index);
    }
  }

  await Promise.all(Array.from({ length: width }, () => worker()));
  return results;
}
