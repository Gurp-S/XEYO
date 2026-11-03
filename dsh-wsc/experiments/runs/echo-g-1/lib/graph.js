const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;
const EXTERNAL_RE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;

function collectImports(text) {
  const found = [];
  IMPORT_RE.lastIndex = 0;
  let match;
  while ((match = IMPORT_RE.exec(text)) !== null) found.push(match[1]);
  return found;
}

function collectUrls(text) {
  const found = [];
  URL_RE.lastIndex = 0;
  let match;
  while ((match = URL_RE.exec(text)) !== null) found.push(match[2].trim());
  return found;
}

export function isExternalSpecifier(spec) {
  return EXTERNAL_RE.test(spec) || spec.includes('?') || spec.includes('#');
}

/**
 * Every relative specifier a source file depends on, per extension:
 * JS imports, CSS `url(...)` targets, and the JSON `extends` target.
 *
 * Dependencies are the reason incremental rebuilds are correct, so each
 * transform that reads another file must declare it here.
 */
export function readDeps(rel, bytes, ext) {
  const text = bytes.toString('utf8');
  let specifiers = [];
  if (ext === '.js' || ext === '.mjs') specifiers = collectImports(text);
  else if (ext === '.css') specifiers = collectUrls(text);
  else if (ext === '.json') {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && typeof parsed.extends === 'string') {
        specifiers = [parsed.extends];
      }
    } catch {
      specifiers = [];
    }
  }
  return specifiers.filter((spec) => spec && !isExternalSpecifier(spec));
}
