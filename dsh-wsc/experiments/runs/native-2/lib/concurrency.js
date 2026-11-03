export async function mapLimit(items, limit, fn) {
  const list = [...items];
  const size = Math.max(1, Math.min(Math.floor(limit) || 1, list.length || 1));
  const results = new Array(list.length);
  let cursor = 0;
  const worker = async () => {
    while (cursor < list.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await fn(list[index], index);
    }
  };
  await Promise.all(Array.from({ length: size }, worker));
  return results;
}
