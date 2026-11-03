import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

/**
 * Fingerprint of a source file: the sha1 of its bytes. Content-addressing (as
 * opposed to size + mtime) means a rewrite that preserves the timestamp is
 * still detected, and a touch that leaves the bytes alone does not force work.
 */
export async function cacheKey(abs) {
  return createHash('sha1').update(await readFile(abs)).digest('hex');
}
