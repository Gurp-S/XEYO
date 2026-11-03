import { createHash } from 'node:crypto';

export const MISSING = 'missing';

// A fingerprint of the file's bytes. Size and mtime are deliberately not used:
// a rewrite that restores the old mtime must still be detected.
export function cacheKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
