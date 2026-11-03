import { createHash } from 'node:crypto';

export function sha1(input) {
  return createHash('sha1').update(input).digest('hex');
}

// A source fingerprint is derived from the bytes alone: rewriting a file with the
// same size and mtime still changes it, and re-touching it changes nothing.
export function fingerprint(bytes) {
  return sha1(bytes);
}
