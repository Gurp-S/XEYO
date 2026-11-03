import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_SOURCE = String.raw`url\(\s*['"]?([^'")]+)['"]?\s*\)`;

export function urlPattern() {
  return new RegExp(URL_SOURCE, 'g');
}

function collect(re, text) {
  const found = [];
  re.lastIndex = 0;
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

/** Specifiers a source of `ext` pulls in, regardless of whether they resolve. */
export function specifiersFor(ext, text) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(urlPattern(), text);
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.extends === 'string') return [parsed.extends];
    } catch {
      // an unparsable source is reported by the emit step, not here
    }
    return [];
  }
  return [];
}

export async function readDeps(abs, ext) {
  if (ext !== '.js' && ext !== '.mjs' && ext !== '.css' && ext !== '.json') return [];
  return specifiersFor(ext, await readFile(abs, 'utf8'));
}
