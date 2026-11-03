import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+?)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  re.lastIndex = 0;
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Return the specifiers a source depends on. The caller resolves them against
// the source tree; remote/absolute specifiers are filtered there.
export async function readDeps(abs, ext, bytes) {
  if (ext !== '.js' && ext !== '.mjs' && ext !== '.css' && ext !== '.json') return [];
  const data = bytes ?? (await readFile(abs));
  const text = data.toString('utf8');
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  const parsed = JSON.parse(text);
  return parsed && typeof parsed === 'object' && typeof parsed.extends === 'string'
    ? [parsed.extends]
    : [];
}
