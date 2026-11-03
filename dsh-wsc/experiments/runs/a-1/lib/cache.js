import { createHash } from 'node:crypto';

// Fingerprints are content hashes, never timestamps: rewriting a file with the
// same size and mtime must still invalidate it.
export function hashBytes(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
