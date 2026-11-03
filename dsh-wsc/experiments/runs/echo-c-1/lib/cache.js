import { createHash } from 'node:crypto';

// A source fingerprint is a hash of the source bytes: size and mtime cannot
// distinguish a rewrite that preserves both.
export function cacheKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
