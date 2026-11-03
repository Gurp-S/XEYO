import { createHash } from 'node:crypto';

// A source's identity is its bytes, never its mtime: a rewrite that keeps the
// timestamp must still invalidate the cache.
export function fingerprint(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

export function shortHash(bytes) {
  return fingerprint(bytes).slice(0, 8);
}
