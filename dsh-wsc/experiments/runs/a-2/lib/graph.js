import path from 'node:path';

const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  for (const match of text.matchAll(re)) found.push(match[1]);
  return found;
}

export function cssTargets(text) {
  return collect(URL_RE, text);
}

export function rewriteCss(text, names) {
  return text.replace(URL_RE, (whole, target) => `url(${names.get(target) ?? target})`);
}

export function jsonExtends(text) {
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed.extends === 'string' ? parsed.extends : null;
  } catch {
    return null;
  }
}

// Every specifier a source depends on, by extension: JS imports, CSS url()
// targets and JSON extends bases. Everything else depends on nothing.
export function depSpecifiers(rel, text) {
  const ext = path.posix.extname(rel);
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return cssTargets(text);
  if (ext === '.json') {
    const base = jsonExtends(text);
    return base ? [base] : [];
  }
  return [];
}
