import { readFile } from 'node:fs/promises';
import { urlTargets } from './css.js';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Every source kind that embeds another source file must report that file here,
// otherwise a change to the embedded file never invalidates the derived output.
export async function readDeps(abs, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return collect(IMPORT_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.css') {
    return urlTargets(await readFile(abs, 'utf8'));
  }
  if (ext === '.json') {
    let own;
    try {
      own = JSON.parse(await readFile(abs, 'utf8'));
    } catch {
      // Invalid JSON only matters when the file is actually built; keep the plan alive.
      return [];
    }
    return own && typeof own.extends === 'string' ? [own.extends] : [];
  }
  return [];
}
