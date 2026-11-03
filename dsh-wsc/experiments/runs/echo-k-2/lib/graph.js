import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

export async function readDeps(abs, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return collect(IMPORT_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.css') {
    return collect(URL_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.json') {
    try {
      const value = JSON.parse(await readFile(abs, 'utf8'));
      return value && typeof value.extends === 'string' ? [value.extends] : [];
    } catch {
      return [];
    }
  }
  return [];
}
