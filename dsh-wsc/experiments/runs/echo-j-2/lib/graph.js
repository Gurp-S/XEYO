import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

export async function readDeps(abs, ext) {
  if (ext !== '.js' && ext !== '.mjs') return [];
  const text = await readFile(abs, 'utf8');
  return collect(IMPORT_RE, text);
}
