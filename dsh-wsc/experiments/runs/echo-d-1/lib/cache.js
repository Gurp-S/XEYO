import { createHash } from 'node:crypto';

/**
 * Source fingerprint.
 *
 * The output contract says output bytes are a pure function of source bytes, so
 * the cache key has to be derived from the bytes alone. Anything derived from
 * file metadata (size, mtime) is a fingerprint of the file *entry*, not of the
 * source: rewriting a file without touching its mtime then looks unchanged and
 * leaves a stale output behind. Keep metadata out of this module.
 */
export function fingerprint(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

/** First 8 hex of the sha1 of a string or buffer; used for output names. */
export function shortHash(input) {
  return createHash('sha1').update(input).digest('hex').slice(0, 8);
}
