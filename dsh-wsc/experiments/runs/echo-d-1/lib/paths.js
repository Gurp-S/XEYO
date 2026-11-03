import path from 'node:path';

// url()/import/extends targets that do not name a file inside the source tree.
const EXTERNAL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/\/|\/|#)/i;

export function isExternal(spec) {
  return typeof spec !== 'string' || spec === '' || EXTERNAL_RE.test(spec);
}

/**
 * Resolve a reference written inside `fromRel` to a source-relative path, or
 * null when it points outside the tree (absolute, scheme, fragment, escaping
 * `..`). Returning null means "not ours to track": the reference is left as
 * written and no dependency edge is recorded.
 */
export function resolveSourcePath(fromRel, spec) {
  if (isExternal(spec)) return null;
  const joined = path.posix.join(path.posix.dirname(fromRel), spec);
  const target = path.posix.normalize(joined);
  if (target === '' || target === '.' || target === '..') return null;
  if (target.startsWith('../') || path.posix.isAbsolute(target)) return null;
  return target;
}
