import { createHash } from 'node:crypto';

export function cacheKey(input) {
  return createHash('sha1').update(input).digest('hex');
}
