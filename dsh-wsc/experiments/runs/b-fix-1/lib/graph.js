import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_SOURCE = String.raw`url\(\s*['"]?([^'")]+)['"]?\s*\)`;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

export function urlTargets(text) {
  return collect(new RegExp(URL_SOURCE, 'g'), text);
}

export function replaceUrls(text, replacer) {
  return text.replace(new RegExp(URL_SOURCE, 'g'), replacer);
}

export function isDependencySource(ext) {
  return ext === '.js' || ext === '.mjs' || ext === '.css' || ext === '.json';
}

// Specifiers a file depends on: imports for scripts, url() targets for
// stylesheets, the base path for a JSON file with "extends".
export function parseDeps(ext, text) {
  if (ext === '.js' || ext === '.mjs') return collect(new RegExp(IMPORT_RE.source, 'g'), text);
  if (ext === '.css') return urlTargets(text);
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      return [];
    }
    if (parsed && typeof parsed === 'object' && typeof parsed.extends === 'string') return [parsed.extends];
    return [];
  }
  return [];
}

export async function readDeps(abs, ext) {
  if (!isDependencySource(ext)) return [];
  return parseDeps(ext, await readFile(abs, 'utf8'));
}
