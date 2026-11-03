import { createHash } from 'node:crypto';

/**
 * A source fingerprint is derived from the file's bytes, never from its
 * metadata. Rewriting a file while keeping its size and mtime must still
 * invalidate the output that was derived from the old bytes.
 */
export function fingerprint(bytes) {
  return createHash('sha1').update(bytes).digest('hex');
}
