import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  return [...text.matchAll(new RegExp(re.source, re.flags))].map((match) => match[1]);
}

/**
 * Dependency specifiers of a source file, as written in the file itself.
 *
 * Covers every construct the builder actually consumes:
 *   - `*.js` / `*.mjs`: module imports
 *   - `*.css`: `url(...)` targets, inlined into the stylesheet as hashed assets
 *   - `*.json`: the `extends` base, merged into the derived object
 */
export function specifiersFor(ext, text) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      return [];
    }
    if (parsed && typeof parsed === 'object' && typeof parsed.extends === 'string') return [parsed.extends];
    return [];
  }
  return [];
}

export async function readDeps(abs, ext) {
  return specifiersFor(ext, await readFile(abs, 'utf8'));
}
