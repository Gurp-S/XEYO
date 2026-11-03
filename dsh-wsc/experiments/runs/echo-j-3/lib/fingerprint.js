import { createHash } from 'node:crypto';

export function sha1hex(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

// A source's identity is its bytes. Stat data (size/mtime) is not an identity:
// a rewrite that keeps the mtime is still a different source.
export function fingerprint(bytes) {
  return sha1hex(bytes);
}
