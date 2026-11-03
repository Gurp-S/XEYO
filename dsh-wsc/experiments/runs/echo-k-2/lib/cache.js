import { createHash } from 'node:crypto';

export function contentKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

// Kept for callers that used the original metadata-based key. The builder
// itself fingerprints source bytes so edits that preserve mtime are visible.
export function cacheKey(stat) {
  return `${stat.size}:${Math.round(stat.mtimeMs)}`;
}
