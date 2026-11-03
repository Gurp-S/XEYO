import { createHash } from 'node:crypto';

// A source fingerprint is a hash of the bytes, never of stat metadata: size and
// mtime can stay identical across a real edit, and a skipped rebuild would then
// leave stale output behind.
export function cacheKey(data) {
  return createHash('sha1').update(data).digest('hex');
}

export function shortHash(data) {
  return cacheKey(data).slice(0, 8);
}
