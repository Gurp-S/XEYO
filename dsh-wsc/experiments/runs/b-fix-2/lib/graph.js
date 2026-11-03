import { readFile } from 'node:fs/promises';
import { urlSpecifiers } from './css.js';

// Static `import`/`export ... from` specifiers. The leading guard keeps
// `import.meta` and `obj.import` from matching.
const STATIC_RE = /(?:^|[^\w$])(?:import|export)\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
// `import('./x.js')` — the same reference, spelled dynamically.
const DYNAMIC_RE = /(?:^|[^\w$.])import\s*\(\s*['"]([^'"]+)['"]\s*\)/g;

const TEXT_EXTS = new Set(['.js', '.mjs', '.css', '.json']);

function collect(re, text) {
  const found = [];
  for (const match of text.matchAll(re)) found.push(match[1]);
  return found;
}

// Every reference form the contract knows about must be reported here,
// otherwise a change to the referenced file can never invalidate the
// referring file.
export function depsOf(text, ext) {
  if (ext === '.js' || ext === '.mjs') {
    return [...new Set([...collect(STATIC_RE, text), ...collect(DYNAMIC_RE, text)])];
  }
  if (ext === '.css') return [...new Set(urlSpecifiers(text))];
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
    } catch {
      // Malformed JSON is reported by the build step with source context;
      // dependency scanning stays best effort.
      return [];
    }
  }
  return [];
}

export function isTextExt(ext) {
  return TEXT_EXTS.has(ext);
}

export async function readDeps(abs, ext) {
  if (!isTextExt(ext)) return [];
  return depsOf(await readFile(abs, 'utf8'), ext);
}
