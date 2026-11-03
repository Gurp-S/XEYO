import { readFile } from 'node:fs/promises';
import { extractUrlTargets } from './render.js';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

/**
 * Specifiers a source depends on, in the order they appear.
 * `.js`/`.mjs` contribute `import` sources, `.css` contributes `url(...)`
 * targets, `.json` contributes its `extends` base.
 */
export function collectDeps(text, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return extractUrlTargets(text);
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) && typeof parsed.extends === 'string') {
        return [parsed.extends];
      }
    } catch {
      // Invalid JSON is reported when the file is rendered.
    }
  }
  return [];
}

export async function readDeps(abs, ext) {
  if (ext !== '.js' && ext !== '.mjs' && ext !== '.css' && ext !== '.json') return [];
  return collectDeps(await readFile(abs, 'utf8'), ext);
}
