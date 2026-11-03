import { createHash } from 'node:crypto';

export function cacheKey(bytes) {
  return `sha1:${createHash('sha1').update(bytes).digest('hex')}`;
}
