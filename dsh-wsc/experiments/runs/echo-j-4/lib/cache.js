import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

export function hashBytes(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

// A source's identity is its bytes. Timestamps are not part of it: a rewrite that
// restores the previous mtime still changed the file, and a touched file that kept
// its bytes still did not.
export async function fingerprint(abs) {
  try {
    return hashBytes(await readFile(abs));
  } catch (error) {
    if (error && (error.code === 'ENOENT' || error.code === 'ENOTDIR')) return 'missing';
    throw error;
  }
}
