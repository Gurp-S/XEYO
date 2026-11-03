import { createHash } from 'node:crypto';

// Fingerprints are content hashes, not stat signatures: rewriting a file with the
// same mtime (or the same size) must still be detected.
export function fingerprint(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

export function shortDigest(bytes) {
  return fingerprint(bytes).slice(0, 8);
}

export const cacheKey = fingerprint;
