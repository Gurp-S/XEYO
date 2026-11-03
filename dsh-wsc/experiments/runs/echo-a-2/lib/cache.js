import { createHash } from 'node:crypto';

// A source fingerprint must depend on the bytes alone: rewriting a file without
// changing its size or mtime still has to invalidate the cached output.
export function cacheKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
