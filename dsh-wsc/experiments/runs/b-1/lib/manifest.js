import { readFile } from 'node:fs/promises';
import { writeFileAtomic } from './fsutil.js';

export const MANIFEST_VERSION = 2;

function cleanEntry(entry) {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return null;
  return {
    key: typeof entry.key === 'string' ? entry.key : '',
    deps: entry.deps && typeof entry.deps === 'object' && !Array.isArray(entry.deps) ? entry.deps : {},
    out: Array.isArray(entry.out) ? entry.out.filter((name) => typeof name === 'string') : [],
  };
}

// A manifest that cannot be trusted (truncated by an interrupted build, wrong
// version, hand-edited garbage) is treated as absent so the next build rebuilds
// from scratch instead of crashing on it.
export async function loadManifest(file) {
  let parsed;
  try {
    parsed = JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
  if (parsed.version !== MANIFEST_VERSION) return null;
  if (!parsed.files || typeof parsed.files !== 'object' || Array.isArray(parsed.files)) return null;
  const files = {};
  for (const [rel, raw] of Object.entries(parsed.files)) {
    const entry = cleanEntry(raw);
    if (entry) files[rel] = entry;
  }
  return { version: MANIFEST_VERSION, files };
}

export async function saveManifest(file, manifest) {
  await writeFileAtomic(file, `${JSON.stringify(manifest, null, 2)}\n`, { stableTmp: true });
}
