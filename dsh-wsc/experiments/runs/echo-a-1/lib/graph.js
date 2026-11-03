import { readFile } from 'node:fs/promises';
import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

// Fingerprint recorded for a dependency that has no source file (yet).
export const MISSING = 'missing';

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// A stylesheet depends on the assets it points at through url(...), a JSON document
// depends on the base file it names through "extends", a module depends on the
// modules it imports. Every one of those is a source whose fingerprint has to be
// part of the dependent's cache key.
export function depsFromText(text, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      return [];
    }
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  }
  return [];
}

// The caller already holds the source bytes it fingerprinted, so the text variant is
// what the planner uses; this one stays for a source read straight from disk.
export async function readDeps(abs, ext) {
  return depsFromText(await readFile(abs, 'utf8'), ext);
}

// Resolves a dependency specifier against the source that names it. Returns null for
// anything that does not point at a file inside the source tree (URLs, data URIs,
// root-absolute paths, bare fragments, paths escaping the tree).
export function resolveDep(rel, spec) {
  const bare = String(spec).split(/[?#]/)[0].trim();
  if (!bare || bare.startsWith('#')) return null;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(bare)) return null;
  const target = path.posix.normalize(path.posix.join(path.posix.dirname(rel), bare));
  if (target === '..' || target.startsWith('../')) return null;
  return target;
}
