import { createHash } from 'node:crypto';

/**
 * A source fingerprint is a pure function of the source bytes.
 *
 * It must not depend on stat metadata: a rewrite that preserves size and mtime
 * is still a change, and two files with equal bytes must always agree.
 */
export function fingerprint(bytes) {
  return `sha1:${createHash('sha1').update(bytes).digest('hex')}`;
}
