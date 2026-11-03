import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;

export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  const pattern = new RegExp(re.source, re.flags);
  let match;
  while ((match = pattern.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Every edge the build depends on, whatever the file type that carries it.
export async function readDeps(abs, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return collect(IMPORT_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.css') {
    return collect(URL_RE, await readFile(abs, 'utf8'));
  }
  if (ext === '.json') {
    try {
      const own = JSON.parse(await readFile(abs, 'utf8'));
      return own && typeof own.extends === 'string' ? [own.extends] : [];
    } catch {
      // An unparsable file has no readable edges; building it will surface the error.
      return [];
    }
  }
  return [];
}
