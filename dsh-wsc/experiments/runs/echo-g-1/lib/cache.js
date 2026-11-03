import { createHash } from 'node:crypto';

/**
 * Source fingerprint: a hash of the source *bytes*, never of stat metadata.
 *
 * Size + mtime is not a fingerprint of content: a rewrite that restores the
 * mtime (or lands in the same millisecond with the same length) is invisible to
 * it, which left stale outputs behind.
 */
export function fingerprint(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

export function shortHash(bytes) {
  return fingerprint(bytes).slice(0, 8);
}
