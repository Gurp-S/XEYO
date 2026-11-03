import { readFile } from 'node:fs/promises';

const importRe = () => /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const urlRe = () => /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

/** A fresh global `url(...)` matcher; callers must not share lastIndex state. */
export { urlRe };

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

/**
 * Dependency specifiers of a source text, per extension.
 *
 * Every edge that makes an output depend on another file has to be listed here,
 * otherwise the incremental plan cannot see the edge and the output goes stale.
 */
export function depsFromText(text, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(importRe(), text);
  if (ext === '.css') {
    return collect(urlRe(), text)
      .map((spec) => spec.trim())
      .filter(Boolean);
  }
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' && typeof parsed.extends === 'string'
        ? [parsed.extends]
        : [];
    } catch {
      return [];
    }
  }
  return [];
}

export async function readDeps(abs, ext) {
  return depsFromText(await readFile(abs, 'utf8'), ext);
}
