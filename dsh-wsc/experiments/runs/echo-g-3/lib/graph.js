import { readFile } from 'node:fs/promises';

const IMPORT_RE = /\b(?:import|export)\b\s*(?:[^'"\n]*?\s+from\s*)?['"]([^'"]+)['"]/g;
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
  if (ext === '.json') {
    const parsed = JSON.parse(await readFile(abs, 'utf8'));
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  }
  if (ext === '.css') {
    return collect(URL_RE, await readFile(abs, 'utf8'));
  }
  return [];
}
