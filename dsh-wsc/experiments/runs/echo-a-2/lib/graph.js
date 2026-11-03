const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  for (const match of text.matchAll(re)) found.push(match[1]);
  return found;
}

// Every specifier a source file depends on, whatever the dialect: module
// imports for scripts, `url(...)` targets for stylesheets, `extends` for JSON.
export function readDeps(ext, bytes) {
  const text = bytes.toString('utf8');
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
    } catch {
      return [];
    }
  }
  return [];
}
