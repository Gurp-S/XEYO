import { readFile } from 'node:fs/promises';
import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;
const EXTERNAL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/|#)/i;

function collect(re, text) {
  const found = [];
  for (const match of text.matchAll(re)) found.push(match[1]);
  return found;
}

export function resolveDep(rel, spec) {
  if (typeof spec !== 'string' || EXTERNAL_RE.test(spec)) return null;
  return path.posix.normalize(path.posix.join(path.posix.dirname(rel), spec));
}

// Returns the direct dependency specifiers of a source file, whatever the
// format expresses them in: ESM imports, CSS `url(...)`, or JSON `extends`.
export async function readDeps(abs, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return collect(IMPORT_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.css') {
    return collect(URL_RE, await readFile(abs, 'utf8')).filter((spec) => resolveDep('x', spec));
  }
  if (ext === '.json') {
    const text = await readFile(abs, 'utf8');
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
