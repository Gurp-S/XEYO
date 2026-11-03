export function cacheKey(stat) {
  return `${stat.size}:${Math.round(stat.mtimeMs)}`;
}
