import path from 'node:path';

const SCHEME_RE = /^[a-zA-Z][a-zA-Z0-9+.-]*:/;

// Reference kinds whose specifiers are always file paths, so a bare name means
// "next to me". Every other kind treats a bare name as an external package.
const SELF_RELATIVE = new Set(['.css']);

// A specifier that can never name a file in the source tree: a url scheme
// (data:, http:, blob:), a root-absolute path, a protocol-relative path, a
// fragment, or a query-only reference.
function isOpaque(spec) {
  return SCHEME_RE.test(spec) || spec.startsWith('/') || spec.startsWith('#') || spec.startsWith('?');
}

// Resolve a specifier to a source-relative path, or null when it does not point
// inside the source tree. `ext` is the extension of the file that holds the
// specifier and decides what a bare specifier means.
export function resolveDep(fromRel, spec, ext) {
  if (typeof spec !== 'string' || spec === '' || isOpaque(spec)) return null;
  if (!spec.startsWith('.') && !SELF_RELATIVE.has(ext)) return null;
  const dir = path.posix.dirname(fromRel);
  const resolved = path.posix.normalize(path.posix.join(dir === '.' ? '' : dir, spec));
  if (resolved === '' || resolved === '..' || resolved.startsWith('../')) return null;
  if (path.posix.isAbsolute(resolved)) return null;
  return resolved;
}
