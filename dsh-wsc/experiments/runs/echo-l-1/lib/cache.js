import { createHash } from 'node:crypto';

/**
 * Fingerprint a source from its bytes. mtime is deliberately not part of the
 * key: a rewrite that preserves the timestamp (or a coarse filesystem clock)
 * must still invalidate the previous build.
 */
export function contentKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

/**
 * Kept for callers that used the old stat-based helper. New code should use
 * contentKey so the key reflects content rather than metadata.
 */
export function cacheKey(stat) {
  return `${stat.size}:${Math.round(stat.mtimeMs)}`;
}
