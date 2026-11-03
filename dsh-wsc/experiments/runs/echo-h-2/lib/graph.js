const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Specifiers are returned exactly as written; the caller resolves them relative
// to the file that contains them.
export function depsForText(ext, text) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      return [];
    }
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  }
  return [];
}
