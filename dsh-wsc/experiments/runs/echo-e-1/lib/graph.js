const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

const TEXT_EXTENSIONS = new Set(['.js', '.mjs', '.css', '.json']);

function collect(re, text) {
  const found = [];
  let match;
  re.lastIndex = 0;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

export function isTextExtension(ext) {
  return TEXT_EXTENSIONS.has(ext);
}

export function depSpecs(ext, text) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') {
    const value = parseJson(text);
    return value && typeof value.extends === 'string' ? [value.extends] : [];
  }
  return [];
}

export function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
