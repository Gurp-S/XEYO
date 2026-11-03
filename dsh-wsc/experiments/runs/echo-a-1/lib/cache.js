import { createHash } from 'node:crypto';

export function sha1(input) {
  return createHash('sha1').update(input).digest('hex');
}

// A source fingerprint is the hash of the source bytes. Output bytes are a pure
// function of source bytes, so any weaker key (size, mtime) can miss a change:
// a same-size edit inside the filesystem timestamp granularity looks unchanged.
export function fingerprint(bytes) {
  return sha1(bytes);
}
