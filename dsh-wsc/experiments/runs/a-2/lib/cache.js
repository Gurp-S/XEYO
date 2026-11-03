import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';

export function hashBytes(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

// A file's fingerprint is the hash of its bytes. Size and mtime are deliberately
// not part of it: a rewrite that keeps the size and restores the mtime is still
// a change, so it has to move the fingerprint.
export async function cacheKey(abs) {
  const hash = createHash('sha1');
  for await (const chunk of createReadStream(abs)) hash.update(chunk);
  return hash.digest('hex');
}
