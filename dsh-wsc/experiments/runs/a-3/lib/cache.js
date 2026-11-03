import { createHash } from 'node:crypto';

// A source fingerprint has to describe the bytes, not the file's metadata:
// rewriting a file without touching its mtime (or keeping its size) must still
// invalidate the entry. Hashing the content is the only fingerprint that
// satisfies "output bytes are a pure function of source bytes".
export function fingerprint(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}

// The build stamp in emitted scripts is derived from the source text, so it
// uses the same digest as the manifest key.
export function shortFingerprint(bytes) {
  return fingerprint(bytes).slice(0, 8);
}
