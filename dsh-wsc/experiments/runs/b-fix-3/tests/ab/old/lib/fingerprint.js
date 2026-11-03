import { createHash } from 'node:crypto';

export function hashBytes(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

export function shortHash(bytes) {
  return hashBytes(bytes).slice(0, 8);
}

// Content fingerprint: independent of mtime, size and rewrite history.
export function contentKey(bytes) {
  return `sha1:${hashBytes(bytes)}`;
}
