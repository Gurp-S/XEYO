import path from 'node:path';

import { sha1 } from './cache.js';

// Anything that is not a path inside the source tree: URLs, protocol-relative
// paths, absolute paths and data: URIs are left alone by the emitter.
const EXTERNAL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;

export function stripSuffix(spec) {
  const cut = spec.search(/[?#]/);
  return cut === -1 ? spec : spec.slice(0, cut);
}

// Resolve a specifier against the file that mentions it. Returns a path
// relative to the source root, or null when the target is not a source path.
export function resolveDep(rel, spec) {
  if (typeof spec !== 'string' || EXTERNAL_RE.test(spec)) return null;
  const clean = stripSuffix(spec);
  if (!clean) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), clean));
  if (!target || target === '.' || target === '..' || target.startsWith('../')) return null;
  return target;
}

export function hashedName(rel, bytes) {
  const ext = path.posix.extname(rel);
  const base = path.posix.basename(rel, ext);
  return `${base}.${sha1(bytes).slice(0, 8)}${ext}`;
}
