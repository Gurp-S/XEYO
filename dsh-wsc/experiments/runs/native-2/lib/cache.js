import { createHash } from 'node:crypto';

export function sha1(input) {
  return createHash('sha1').update(input).digest('hex');
}

export function cacheKey(bytes) {
  return sha1(bytes);
}
