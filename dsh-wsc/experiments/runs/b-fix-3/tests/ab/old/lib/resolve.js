import path from 'node:path';

// Pre-fix behaviour, kept verbatim in shape so the A/B compares only the
// resolver: a specifier counts as a source path only when it starts with '.'.
// Bare names (url(img.png)) and any scheme-prefixed specifier are dropped, so
// a CSS file never records the assets it points at as dependencies.
export function resolveDep(fromRel, spec) {
  if (typeof spec !== 'string' || !spec.startsWith('.')) return null;
  const dir = path.posix.dirname(fromRel);
  const resolved = path.posix.normalize(path.posix.join(dir === '.' ? '' : dir, spec));
  if (resolved === '' || resolved === '..' || resolved.startsWith('../')) return null;
  if (path.posix.isAbsolute(resolved)) return null;
  return resolved;
}
