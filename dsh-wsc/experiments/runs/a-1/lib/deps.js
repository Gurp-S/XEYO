export const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

const TEXT_EXTENSIONS = new Set(['.js', '.mjs', '.css', '.json']);

function collect(source, text) {
  const re = new RegExp(source.source, source.flags);
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

function jsonDeps(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return [];
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return [];
  return typeof parsed.extends === 'string' ? [parsed.extends] : [];
}

export function isTextSource(ext) {
  return TEXT_EXTENSIONS.has(ext);
}

export function extractDeps(text, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, text);
  if (ext === '.css') return collect(URL_RE, text);
  if (ext === '.json') return jsonDeps(text);
  return [];
}
