import { createHash } from 'node:crypto';

// Fingerprint of source bytes. Size and mtime are not enough: a rewrite can
// preserve both, and the file would be skipped as unchanged while its output
// stays stale. The digest is also the hash used for output names and build
// markers, so a fingerprint is always a pure function of the content.
export function cacheKey(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
