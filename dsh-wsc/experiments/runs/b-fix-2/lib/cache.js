import { createHash } from 'node:crypto';

// A source fingerprint must be derived from the bytes themselves: size and
// mtime are metadata a writer can keep unchanged while the content changes.
export function fingerprint(input) {
  return createHash('sha1').update(input).digest('hex');
}

export function shortHash(input) {
  return fingerprint(input).slice(0, 8);
}
