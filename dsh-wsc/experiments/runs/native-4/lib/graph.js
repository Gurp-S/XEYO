const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(pattern, text) {
  const found = [];
  const re = new RegExp(pattern.source, pattern.flags);
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Every specifier a source file depends on, whatever its extension:
// `import ... from '...'` for JS, `url(...)` for CSS, `extends` for JSON.
// Anything else has no dependencies of its own.
export function readDeps(source, ext) {
  if (ext !== '.js' && ext !== '.mjs' && ext !== '.css' && ext !== '.json') return [];
  const text = typeof source === 'string' ? source : source.toString('utf8');
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  } catch {
    return [];
  }
}
