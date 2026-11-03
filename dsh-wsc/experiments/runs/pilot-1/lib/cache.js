import { createHash } from 'node:crypto';

// A fingerprint must describe the bytes, not the filesystem metadata: a rewrite
// that preserves size and mtime still has to invalidate the cached output.
export function cacheKey(input) {
  if (typeof input === 'string' || input instanceof Uint8Array) {
    return createHash('sha1').update(input).digest('hex');
  }
  // Legacy stat-shaped callers cannot provide content. The builder always
  // passes bytes; this fallback only keeps the old helper callable.
  return `${input.size}:${Math.round(input.mtimeMs)}`;
}
