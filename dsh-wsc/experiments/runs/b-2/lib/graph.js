import { readFile } from 'node:fs/promises';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_SOURCE = String.raw`url\(\s*(['"]?)([^'"]*?)\1\s*\)`;

export function urlPattern() {
  return new RegExp(URL_SOURCE, 'g');
}

function collect(pattern, text, group) {
  const found = [];
  for (const match of text.matchAll(pattern)) found.push(match[group]);
  return found;
}

// Every specifier a file depends on: JS imports, CSS url() targets and the JSON
// extends target. Whatever the emitter reads to produce an output must be here.
export function depsOf(text, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text, 1);
  if (ext === '.css') return collect(urlPattern(), text, 2);
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.extends === 'string') return [parsed.extends];
    } catch {
      // A malformed file is reported by the emitter, not by the graph.
    }
  }
  return [];
}

export async function readDeps(abs, ext) {
  return depsOf(await readFile(abs, 'utf8'), ext);
}
