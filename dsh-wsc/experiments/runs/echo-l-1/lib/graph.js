import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

// A URL token inside url(...). Quotes are optional and the captured target is
// trimmed by callers. The same expression is used for dependency discovery and
// for rewriting so the two can never drift apart.
export const CSS_URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

/**
 * Return the raw specifiers a source depends on. Resolution (relative to the
 * source, filtering external URLs) belongs to the caller.
 *
 * `text` is an optional already-read copy of the file, which keeps planBuild
 * from reading every source twice.
 */
export async function readDeps(abs, ext, text) {
  if (ext === '.js' || ext === '.mjs') {
    const source = text ?? (await readFile(abs, 'utf8'));
    return collect(IMPORT_RE, source);
  }
  if (ext === '.css') {
    const source = text ?? (await readFile(abs, 'utf8'));
    return collect(CSS_URL_RE, source)
      .map((target) => target.trim())
      .filter((target) => target.length > 0);
  }
  if (ext === '.json') {
    const source = text ?? (await readFile(abs, 'utf8'));
    const parsed = JSON.parse(source);
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  }
  return [];
}
