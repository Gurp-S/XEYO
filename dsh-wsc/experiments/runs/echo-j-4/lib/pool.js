export function normalizeLimit(value) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1) return 1;
  return number;
}

export async function mapLimit(items, limit, worker) {
  const results = new Array(items.length);
  const width = Math.max(1, Math.min(normalizeLimit(limit), items.length));
  let cursor = 0;
  const runners = [];
  for (let slot = 0; slot < width; slot += 1) {
    runners.push(
      (async () => {
        for (;;) {
          const index = cursor;
          cursor += 1;
          if (index >= items.length) return;
          results[index] = await worker(items[index], index);
        }
      })(),
    );
  }
  await Promise.all(runners);
  return results;
}
