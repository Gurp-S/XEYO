import { createHash } from 'node:crypto';

/** Hex sha1 of a Buffer or a UTF-8 string. */
export function sha1Hex(input) {
  return createHash('sha1').update(input).digest('hex');
}

/**
 * Fingerprint of a source file.
 *
 * This hashes the bytes on purpose. A stat-based fingerprint (size + mtime) is
 * not a function of the source bytes: restoring an mtime, `cp -p`, a checkout,
 * or a test that rewrites a file and puts the timestamp back all produce a file
 * whose bytes changed while the fingerprint did not, leaving a stale output
 * behind. Hashing the bytes makes the fingerprint (and therefore the manifest)
 * a pure function of the source bytes.
 */
export function cacheKey(bytes) {
  return sha1Hex(bytes);
}
