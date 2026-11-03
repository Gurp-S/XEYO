import { createHash } from 'node:crypto';

// Fingerprints are always derived from content bytes. Timestamps and sizes are
// never part of a fingerprint: a source rewritten with the same mtime, or a
// source touched without changing, must be recognised for what it is.

export function digest(input) {
  return createHash('sha1').update(input).digest('hex');
}

export function contentKey(input) {
  return digest(input);
}

export function shortHash(input) {
  return digest(input).slice(0, 8);
}
