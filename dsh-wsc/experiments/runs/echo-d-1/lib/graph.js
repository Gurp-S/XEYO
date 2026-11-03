import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

/**
 * Reference specifiers written in source text, in source order.
 *
 * Every specifier that can name another file inside the source tree is
 * returned, whatever the file type: JS imports, CSS `url(...)` targets and JSON
 * `extends`. Callers resolve them and record them as dependencies, so a change
 * in a referenced file invalidates the referrer.
 */
export function depsFromText(text, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return collect(new RegExp(IMPORT_RE.source, 'g'), text);
  }
  if (ext === '.css') {
    return collect(new RegExp(URL_RE.source, 'g'), text);
  }
  if (ext === '.json') {
    const parsed = JSON.parse(text);
    const spec = parsed && typeof parsed === 'object' ? parsed.extends : undefined;
    return typeof spec === 'string' ? [spec] : [];
  }
  return [];
}

export async function readDeps(abs, ext) {
  return depsFromText(await readFile(abs, 'utf8'), ext);
}
