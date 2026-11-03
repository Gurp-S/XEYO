import { createHash } from 'node:crypto';

export function cacheKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
