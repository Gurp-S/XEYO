import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

const REMOTE_RE = /^(?:[a-z][a-z0-9+.-]*:|\/|#)/i;

function matches(re, text) {
  return [...text.matchAll(re)].map((match) => match[1]);
}

// Resolve a specifier to a path relative to the source root, or null when the
// specifier does not name a file in the tree (absolute, remote, fragment).
export function resolveDep(rel, spec) {
  if (typeof spec !== 'string' || spec === '') return null;
  if (REMOTE_RE.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

// Every file a source's bytes depend on, in the format the source is written in.
export function directSpecifiers(rel, text) {
  const ext = path.posix.extname(rel);
  if (ext === '.js' || ext === '.mjs') return matches(IMPORT_RE, text);
  if (ext === '.css') return matches(URL_RE, text).filter((spec) => resolveDep(rel, spec) !== null);
  if (ext === '.json') {
    let value;
    try {
      value = JSON.parse(text);
    } catch {
      return [];
    }
    return value && typeof value.extends === 'string' ? [value.extends] : [];
  }
  return [];
}
