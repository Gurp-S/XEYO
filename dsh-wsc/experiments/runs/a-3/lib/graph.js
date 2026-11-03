import { readFile } from 'node:fs/promises';
import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

// `url(...)` is only meaningful inside stylesheets, but the pattern itself is
// shared with the stylesheet rewriter so both sides always agree on which
// targets exist.
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

const SCHEME_OR_ABSOLUTE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;

// A bare `#fragment` or `?query` reference points into the document that
// already contains it, so it is not a file dependency.
function isDocumentRef(spec) {
  return spec.startsWith('#') || spec.startsWith('?');
}

// Resolve a dependency specifier to a forward-slash path relative to the source
// root, or null when the specifier cannot name a file in the tree.
export function resolveDep(rel, spec) {
  if (!spec) return null;
  const trimmed = spec.trim();
  if (!trimmed || isDocumentRef(trimmed) || SCHEME_OR_ABSOLUTE.test(trimmed)) return null;
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(rel), trimmed));
  if (resolved === '..' || resolved.startsWith('../')) return null;
  return resolved;
}

export function cssUrlTargets(text) {
  const targets = [];
  URL_RE.lastIndex = 0;
  let match;
  while ((match = URL_RE.exec(text)) !== null) {
    targets.push(match[1]);
  }
  return targets;
}

// `"extends": "./base.json"` is resolved as a dependency so that a change to a
// base file rebuilds everything derived from it, including transitive bases.
export function jsonExtendsTarget(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  const spec = parsed.extends;
  return typeof spec === 'string' && spec ? spec : null;
}

// Dependency specifiers for one source file. Stylesheets depend on every
// `url(...)` target they reference and JSON depends on its `extends` base.
export function depsFromText(text, ext) {
  if (ext === '.css') {
    return cssUrlTargets(text).map((spec) => ({ spec, kind: 'url' }));
  }
  if (ext === '.json') {
    const spec = jsonExtendsTarget(text);
    return spec ? [{ spec, kind: 'extends' }] : [];
  }
  if (ext === '.js' || ext === '.mjs') {
    const specs = [];
    IMPORT_RE.lastIndex = 0;
    let match;
    while ((match = IMPORT_RE.exec(text)) !== null) specs.push({ spec: match[1], kind: 'import' });
    return specs;
  }
  return [];
}

// Kept for callers that only have a path: reads the file and returns the
// dependency specs. The planner uses `depsFromText` against the bytes it has
// already read, so a file is never read twice per build.
export async function readDeps(abs, ext) {
  const text = await readFile(abs, 'utf8');
  return depsFromText(text, ext).map((dep) => dep.spec);
}
