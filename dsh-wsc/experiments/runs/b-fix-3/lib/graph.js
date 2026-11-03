const IMPORT_RE = /import\s+(?:[^'"\n]*?\s+from\s+)?['"]([^'"]+)['"]/g;
export const URL_RE = /url\(\s*['"]?([^'")]+)['"]?\s*\)/g;

function collect(re, text) {
  const found = [];
  let match;
  while ((match = re.exec(text)) !== null) found.push(match[1]);
  return found;
}

// Specifiers a source file pulls in, per extension. Takes bytes so callers that
// already read the file (fingerprinting) do not pay for a second read.
export function readDeps(bytes, ext) {
  if (ext === '.js' || ext === '.mjs') return collect(IMPORT_RE, bytes.toString('utf8'));
  if (ext === '.css') return collect(URL_RE, bytes.toString('utf8'));
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(bytes.toString('utf8'));
    } catch {
      return [];
    }
    return parsed && typeof parsed.extends === 'string' ? [parsed.extends] : [];
  }
  return [];
}
