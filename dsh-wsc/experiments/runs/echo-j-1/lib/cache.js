import { createHash } from 'node:crypto';

// A source fingerprint must depend on bytes, not on timestamps: rewriting a
// file in place can leave mtime (and size) untouched.
export function fingerprint(input) {
  return createHash('sha1').update(input).digest('hex');
}
