const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Dependency specifiers for every source kind the builder understands:
// JS imports, CSS url(...) references and JSON `extends` bases.
export function collectDeps(text, ext) {
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
