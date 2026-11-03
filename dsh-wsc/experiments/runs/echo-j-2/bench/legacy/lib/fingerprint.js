import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

export function sha(input) {
  return createHash('sha1').update(input).digest('hex');
}

export function shortSha(input) {
  return sha(input).slice(0, 8);
}

// A source fingerprint is derived from the source bytes only. stat metadata is
// deliberately excluded: a rewrite that keeps size and mtime must still count
// as a change.
export async function fingerprintFile(abs) {
  return sha(await readFile(abs));
}
