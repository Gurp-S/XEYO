import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

export function sha1(input) {
  return createHash('sha1').update(input).digest('hex');
}

// A source is identified by its bytes and never by its metadata: a rewrite that
// keeps the size and restores the mtime is still a new input, so the key has to
// come from the content itself. The bytes are returned so the same read feeds
// both the fingerprint and the output, leaving no window between the two.
export async function readSource(abs) {
  const bytes = await readFile(abs);
  return { bytes, key: sha1(bytes) };
}
